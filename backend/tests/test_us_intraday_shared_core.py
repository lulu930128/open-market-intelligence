from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
import inspect
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    USDailyPrice,
    USQuoteSnapshot,
    USStockMaster,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.registry import DATASET_REGISTRY
from app.market_data.integration_contracts import RequestBounds
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.us_market import service as us_market_service
from app.routers import us_market as us_market_router
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import (
    US_INTRADAY_CACHE_HISTORY_DAYS,
    USIntradayMarketPlatform,
    build_us_resolved_volume_pace,
)
from app.us_market.intraday_profiles import (
    US_BOOTSTRAP_INTRADAY_PROFILE,
    US_RECURRING_INTRADAY_PROFILE,
)
from app.us_market.intraday_repository import (
    USIntradayBarRepository,
    USIntradayVolumeSession,
)
from app.us_market.intraday_transaction import _validate_intraday_bar_identity
from app.us_market.market_data.descriptors import (
    TWELVE_INTRADAY_DESCRIPTOR,
    TWELVE_INTRADAY_RESOURCE_ID,
    TWELVE_QUOTE_DESCRIPTOR,
    TWELVE_QUOTE_RESOURCE_ID,
    YAHOO_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_RESOURCE_ID,
    YAHOO_QUOTE_DESCRIPTOR,
    YAHOO_QUOTE_RESOURCE_ID,
)
from app.us_market.schemas import USIntradayTrendRead


UTC = ZoneInfo("UTC")
US_EASTERN = ZoneInfo("America/New_York")


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        USStockMaster(
            symbol="AAPL",
            security_name="Apple Inc.",
            exchange="NASDAQ",
            asset_type="stock",
            is_etf=False,
        )
    )
    db.commit()
    return db


def _seed_daily_previous_close(
    db: Session,
    *,
    trade_date,
    close_price: float,
) -> None:
    source = SourceRegistry(
        source_name="yahoo.chart.1d",
        source_type="fixture",
        category="market_data",
        enabled=True,
    )
    db.add(source)
    db.flush()
    content_hash = f"AAPL:{trade_date.isoformat()}".ljust(64, "x")[:64]
    raw = RawFetchResult(
        source_id=source.id,
        content_hash=content_hash,
        raw_text="fixture",
        parser_version="yahoo.chart.v8",
        fetched_at=datetime.combine(trade_date, time(21, 0), tzinfo=UTC),
    )
    db.add(raw)
    db.flush()
    db.add(
        USDailyPrice(
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=trade_date,
            open_price=close_price - 1,
            high_price=close_price + 1,
            low_price=close_price - 2,
            close_price=close_price,
            trade_volume=1000,
            fetched_at=raw.fetched_at,
            source_id=source.id,
            raw_result_id=raw.id,
            authority="vendor",
            raw_contract_version="yahoo.chart.v8",
            event_at=datetime.combine(trade_date, time(20, 0), tzinfo=UTC),
            finalization="final",
            price_basis="raw",
            volume_unit="shares",
            volume_status="observed",
            raw_payload_hash=content_hash,
        )
    )
    db.commit()


def _yahoo_payload(now: datetime, *, age_seconds: int = 60) -> dict:
    start = int(now.timestamp()) - age_seconds
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "chartPreviousClose": 198.0,
                    },
                    "timestamp": [start],
                    "indicators": {
                        "quote": [
                            {
                                "open": [200.0],
                                "high": [201.0],
                                "low": [199.5],
                                "close": [200.5],
                                "volume": [1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _yahoo_bars_payload(now: datetime, *, count: int, age_seconds: int = 60) -> dict:
    last_start = int(now.timestamp()) - age_seconds
    timestamps = [last_start - 60 * offset for offset in reversed(range(count))]
    values = [200.0 + index / 100 for index in range(count)]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "chartPreviousClose": 198.0,
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": values,
                                "high": [value + 1 for value in values],
                                "low": [value - 1 for value in values],
                                "close": [value + 0.5 for value in values],
                                "volume": [1000 + index for index in range(count)],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _twelve_quote_payload(now: datetime) -> dict:
    return {
        "symbol": "AAPL",
        "timestamp": int(now.timestamp()) - 30,
        "close": "202.50",
        "open": "201.00",
        "high": "203.00",
        "low": "200.50",
        "previous_close": "200.00",
        "volume": "3500",
        "currency": "USD",
    }


def _service_clock(now: datetime):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    return patch("app.us_market.service.datetime", FrozenDateTime)


def _twelve_bars_payload(now: datetime, *, count: int) -> dict:
    local = now.astimezone(US_EASTERN).replace(second=0, microsecond=0)
    values = []
    for offset in reversed(range(count)):
        start = local - timedelta(minutes=offset + 1)
        price = Decimal("210") + Decimal(offset) / Decimal("100")
        values.append(
            {
                "datetime": start.strftime("%Y-%m-%d %H:%M:%S"),
                "open": str(price),
                "high": str(price + 1),
                "low": str(price - 1),
                "close": str(price + Decimal("0.5")),
                "volume": str(2000 + offset),
            }
        )
    return {
        "meta": {
            "symbol": "AAPL",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
        },
        "values": values,
        "status": "ok",
    }


def _canonical_bar(
    *,
    start_at: datetime,
    interval: str,
    volume: int,
    provider: str = "yahoo_chart",
) -> BarObservation:
    instrument = InstrumentKey(
        market=Market.US,
        symbol="AAPL",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )
    duration = (
        timedelta(hours=6, minutes=30)
        if interval == "1d"
        else timedelta(minutes=1)
    )
    return BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=provider,
            source=f"{provider}.{interval}",
            authority=AuthorityClass.VENDOR,
            raw_contract_version="test.v1",
            event_at=start_at + duration,
            fetched_at=start_at + duration,
            cache_hit=True,
            observation_id=f"{provider}:{interval}:{start_at.isoformat()}",
            raw_receipt_id=f"raw:{provider}:{interval}:{start_at.isoformat()}",
            content_hash="a" * 64,
        ),
        interval=interval,
        start_at=start_at,
        end_at=start_at + duration,
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100.5"),
        volume=Quantity(value=Decimal(volume), unit=QuantityUnit.SHARE),
        volume_status="observed",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )


def test_intraday_transaction_rejects_noncanonical_minute_identity() -> None:
    unaligned = _canonical_bar(
        start_at=datetime(2026, 8, 28, 14, 30, 15, tzinfo=UTC),
        interval="1m",
        volume=100,
    )
    with pytest.raises(ValueError, match="minute-aligned"):
        _validate_intraday_bar_identity(unaligned)

    aligned = _canonical_bar(
        start_at=datetime(2026, 8, 28, 14, 30, tzinfo=UTC),
        interval="1m",
        volume=100,
    )
    future_lineage = aligned.lineage.model_copy(
        update={"event_at": aligned.lineage.fetched_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="later than fetched_at"):
        _validate_intraday_bar_identity(
            aligned.model_copy(update={"lineage": future_lineage})
        )


def test_registry_separates_quote_and_intraday_lifecycles() -> None:
    quote = DATASET_REGISTRY.get("us.quote.snapshot")
    bars = DATASET_REGISTRY.get("us.intraday.bars")

    assert quote.capability_ids == ("quote.snapshot",)
    assert quote.storage_reference.endswith("us_quote_snapshot")
    assert quote.refresh_operation == "us.refresh_quote"
    assert bars.capability_ids == ("intraday.bars",)
    assert "market_intraday_bar_lineage" in bars.storage_reference
    assert bars.refresh_operation == "us.refresh_intraday_bars"


def test_intraday_response_schema_exposes_separate_current_and_bar_health() -> None:
    properties = USIntradayTrendRead.model_json_schema()["properties"]

    assert "current_observation" in properties
    assert "current_source_status" in properties
    assert "bar_source_status" in properties
    assert "source_status" in properties


def test_legacy_us_intraday_reader_is_cache_only_by_source_contract() -> None:
    source = inspect.getsource(us_market_service.get_us_intraday_trend)
    previous_close_source = inspect.getsource(
        us_market_service._read_us_daily_previous_close_reference
    )

    assert "fetch_yahoo_chart_payload" not in source
    assert "parse_yahoo_intraday_prices" not in source
    assert "_persist_us_intraday_history" not in source
    assert ".commit(" not in source
    assert "USIntradayMarketPlatform" in source
    assert ".read_intraday_bars(" in source
    assert "previous_regular_close_from_history" not in source
    assert "bars=30" in previous_close_source
    assert ".read(" in previous_close_source
    assert ".read_volume_sessions(" in source
    router_source = inspect.getsource(us_market_router.get_us_intraday_trend_api)
    assert "refresh_us_" not in router_source
    assert "fetch_" not in router_source


def test_us_quote_get_remains_cache_only_by_source_contract() -> None:
    service_source = inspect.getsource(us_market_service.get_us_quote_snapshot)
    router_source = inspect.getsource(us_market_router.get_us_quote_snapshot_api)

    assert "USIntradayMarketPlatform" in service_source
    assert ".read_quote(" in service_source
    assert ".refresh_quote(" not in service_source
    assert "fetch_" not in service_source
    assert ".commit(" not in service_source
    assert "refresh_us_quote_snapshot" not in router_source
    assert "fetch_" not in router_source


def test_quote_cache_miss_preserves_backend_owned_session_expectedness() -> None:
    db = _db()

    premarket = us_market_service.get_us_quote_snapshot(
        db,
        symbol="AAPL",
        now=datetime(2026, 8, 28, 8, 1, tzinfo=UTC),
    )
    premarket_pending = us_market_service.get_us_quote_snapshot(
        db,
        symbol="AAPL",
        now=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
    )

    assert premarket["market_phase"] == "pre_market"
    assert premarket["capability_expectation"]["expectation"] == "expected"
    assert premarket["capability_expectation"]["outcome"] == (
        "expected_but_missing"
    )
    assert premarket_pending["market_phase"] == "pre_market_pending"
    assert premarket_pending["capability_expectation"]["expectation"] == (
        "not_expected"
    )
    assert premarket_pending["capability_expectation"]["outcome"] == (
        "not_expected"
    )


def test_volume_pace_has_no_raw_daily_storage_dependency() -> None:
    source = inspect.getsource(build_us_resolved_volume_pace)

    assert "USDailyPrice" not in source
    assert "db.query" not in source
    assert "us.daily.ohlcv" in source


def test_refresh_persists_then_rereads_quote_and_intraday_candidates() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def fetch(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={
                YAHOO_QUOTE_RESOURCE_ID: fetch,
                YAHOO_INTRADAY_RESOURCE_ID: fetch,
            },
            clock=lambda: now,
        ),
    )

    quote = platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)
    bars = platform.refresh_intraday_bars(symbol="AAPL", bars=100, now=now, max_provider_calls=1)

    assert quote.result.persistence.committed is True
    assert quote.result.resolved.quote is not None
    assert quote.result.resolved.quote.lineage.cache_hit is True
    assert db.query(USQuoteSnapshot).count() == 1

    assert bars.result.persistence.committed is True
    assert len(bars.result.resolved.bars) == 1
    assert bars.result.resolved.bars[0].lineage.cache_hit is True
    stored_bar = db.query(MarketIntradayBar).one()
    stored_lineage = db.query(MarketIntradayBarLineage).one()
    assert stored_lineage.bar_id == stored_bar.id
    assert stored_lineage.raw_result_id > 0


def test_us_quote_projection_exposes_backend_owned_session_date_relation() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    _seed_daily_previous_close(
        db,
        trade_date=datetime(2026, 8, 27, tzinfo=UTC).date(),
        close_price=198.0,
    )

    def fetch(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: fetch},
            clock=lambda: now,
        ),
        quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
    )
    platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)

    projection = us_market_service.get_us_quote_snapshot(
        db,
        symbol="AAPL",
        now=now,
    )

    relation = projection["session_date_relation"]
    assert relation["status"] == "aligned"
    assert relation["expected"] is True
    assert relation["quote_date"] == "2026-08-28"
    assert relation["completed_daily_date"] == "2026-08-27"


def test_lineage_free_legacy_intraday_rows_are_not_resolution_candidates() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    db.add(
        MarketIntradayBar(
            provider="yahoo_finance_chart",
            stock_id="AAPL",
            market="NASDAQ",
            symbol="AAPL",
            interval="1m",
            bar_time=now,
            open_price=200.0,
            high_price=201.0,
            low_price=199.5,
            close_price=200.5,
            trade_volume=1200,
            source="yahoo_finance_chart",
        )
    )
    db.commit()

    read = USIntradayMarketPlatform(db).read_intraday_bars(symbol="AAPL", bars=100, now=now)

    assert read.result.resolved.bars == ()
    assert "US_INTRADAY_LEGACY_ROWS_WITHOUT_CANONICAL_LINEAGE_IGNORED" in read.result.limitations


def test_noncanonical_duplicate_minute_is_rejected_and_marks_dataset_partial() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo_bars(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo_bars},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )
    platform.refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        max_provider_calls=1,
    )
    canonical = db.query(MarketIntradayBar).one()
    lineage = db.query(MarketIntradayBarLineage).one()
    legacy = MarketIntradayBar(
        source_id=canonical.source_id,
        provider=canonical.provider,
        stock_id=canonical.stock_id,
        market=canonical.market,
        canonical_market=canonical.canonical_market,
        venue=canonical.venue,
        instrument_type=canonical.instrument_type,
        symbol=canonical.symbol,
        interval=canonical.interval,
        bar_time=canonical.bar_time + timedelta(seconds=20),
        open_price=canonical.close_price,
        high_price=canonical.close_price,
        low_price=canonical.close_price,
        close_price=canonical.close_price,
        trade_volume=0,
        source=canonical.source,
    )
    db.add(legacy)
    db.flush()
    db.add(
        MarketIntradayBarLineage(
            bar_id=legacy.id,
            source_id=lineage.source_id,
            raw_result_id=lineage.raw_result_id,
            provider=lineage.provider,
            source=lineage.source,
            authority=lineage.authority,
            raw_contract_version=lineage.raw_contract_version,
            event_at=lineage.event_at + timedelta(seconds=20),
            received_at=lineage.received_at + timedelta(seconds=20),
            fetched_at=lineage.fetched_at + timedelta(seconds=20),
            finalization=lineage.finalization,
            source_interval=lineage.source_interval,
        )
    )
    db.commit()

    read = platform.read_intraday_bars(symbol="AAPL", bars=100, now=now)

    assert len(read.result.resolved.bars) == 1
    assert {
        rejection.reason_code
        for rejection in read.result.candidate_rejections
    } == {"NON_CANONICAL_MINUTE_IDENTITY"}
    assert "NON_CANONICAL_MINUTE_IDENTITY" in read.result.limitations
    assert "DUPLICATE_MINUTE_BUCKET" in read.result.limitations
    assert read.result.dataset_health.status.value == "partial"


def test_fresh_yahoo_snapshot_with_old_trade_does_not_fall_through() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_payload(now, age_seconds=900), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    def twelve(_route, _requirement):
        return {
            "symbol": "AAPL",
            "timestamp": int(now.timestamp()) - 30,
            "close": "202.50",
            "open": "201.00",
            "high": "203.00",
            "low": "200.50",
            "previous_close": "200.00",
            "volume": "3500",
            "currency": "USD",
        }, "https://api.twelvedata.com/quote?symbol=AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo, "twelve_data.quote": twelve},
            clock=lambda: now,
        ),
    )

    refreshed = platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=2)

    assert refreshed.result.acquisition.providers_attempted == ("yahoo_chart",)
    yahoo_health = next(
        item
        for item in refreshed.result.provider_health
        if item.provider == "yahoo_chart"
    )
    assert yahoo_health.freshness.value == "fresh"
    assert yahoo_health.operational.value == "healthy"
    assert yahoo_health.detail_code == "LAST_TRADE_OLD_BUT_PROVIDER_CURRENT"
    assert refreshed.result.resolved.health.selected_provider == "yahoo_chart"
    assert refreshed.result.resolved.quote is not None
    assert refreshed.result.resolved.quote.last_trade_price == 200.5
    assert "LAST_TRADE_OLD_BUT_PROVIDER_CURRENT" in refreshed.result.limitations


def test_quote_and_bar_requirements_separate_refresh_due_from_consumer_stale() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    platform = USIntradayMarketPlatform(db)
    identity = platform.read_quote(symbol="AAPL", now=now).identity

    quote_read = platform._quote_requirement(
        identity,
        now=now,
        allow_acquisition=False,
        require_live=False,
        max_provider_calls=0,
        profile=US_RECURRING_INTRADAY_PROFILE,
    )
    quote_refresh = platform._quote_requirement(
        identity,
        now=now,
        allow_acquisition=True,
        require_live=False,
        max_provider_calls=2,
        profile=US_RECURRING_INTRADAY_PROFILE,
    )
    bar_read = platform._bar_requirement(
        identity,
        now=now,
        bars=60,
        history_days=1,
        allow_acquisition=False,
        require_live=False,
        max_provider_calls=0,
    )

    assert quote_read.freshness.max_age_seconds == 180
    assert quote_refresh.freshness.max_age_seconds == 45
    assert quote_read.freshness.basis.value == "fetched_time"
    assert bar_read.freshness.basis.value == "event_time"


def test_unusable_yahoo_quote_falls_through_to_twelve_candidate() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo(_route, _requirement):
        payload = _yahoo_payload(now)
        payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None]
        return payload, "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    def twelve(_route, _requirement):
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo, TWELVE_QUOTE_RESOURCE_ID: twelve},
            clock=lambda: now,
        ),
    )

    refreshed = platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=2)

    assert refreshed.result.acquisition.providers_attempted == (
        "yahoo_chart",
        "twelve_data",
    )
    assert refreshed.result.resolved.health.selected_provider == "twelve_data"
    assert refreshed.result.resolved.quote is not None


def test_index_quote_truthfully_exposes_single_source_and_never_routes_twelve() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    calls: list[str] = []

    def yahoo(_route, _requirement):
        calls.append("yahoo_chart")
        raise RuntimeError("Yahoo unavailable")

    def twelve(_route, _requirement):
        calls.append("twelve_data")
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=%5EGSPC"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={
                YAHOO_QUOTE_RESOURCE_ID: yahoo,
                TWELVE_QUOTE_RESOURCE_ID: twelve,
            },
            clock=lambda: now,
        ),
    )

    result = platform.refresh_quote(
        symbol="^GSPC",
        now=now,
        max_provider_calls=2,
    )

    assert calls == ["yahoo_chart"]
    assert result.result.acquisition.providers_attempted == ("yahoo_chart",)
    assert result.projection["eligible_providers"] == ["yahoo_chart"]
    assert result.projection["eligible_provider_count"] == 1
    assert result.projection["single_source"] is True
    assert "US_SINGLE_ELIGIBLE_PROVIDER" in result.projection["limitations"]


def test_stock_quote_exposes_both_eligible_provider_capabilities() -> None:
    db = _db()
    projection = USIntradayMarketPlatform(db).read_quote(
        symbol="AAPL",
        now=datetime(2026, 8, 28, 14, 32, tzinfo=UTC),
    ).projection

    assert projection["eligible_providers"] == ["yahoo_chart", "twelve_data"]
    assert projection["eligible_provider_count"] == 2
    assert projection["single_source"] is False


def test_twelve_quote_limitations_survive_persisted_reread() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def twelve(_route, _requirement):
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve},
            clock=lambda: now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    )
    refreshed = platform.refresh_quote(
        symbol="AAPL",
        now=now,
        require_live=True,
        max_provider_calls=1,
    )
    bind = db.get_bind()
    db.close()

    with Session(bind) as reread_db:
        reread = USIntradayMarketPlatform(reread_db).read_quote(
            symbol="AAPL",
            now=now + timedelta(minutes=1),
        )

    assert refreshed.result.resolved.health.selected_provider == "twelve_data"
    assert reread.result.resolved.health.selected_provider == "twelve_data"
    assert "PARTIAL_US_MARKET_VOLUME" in reread.result.resolved.health.limitations
    assert "PERSONAL_INTERNAL_USE_ONLY" in reread.result.resolved.health.limitations


def test_persisted_quote_is_bound_to_intraday_and_ranking_read_surfaces() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def twelve(_route, _requirement):
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=AAPL"

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve},
            clock=lambda: now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    ).refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)

    with _service_clock(now + timedelta(seconds=30)):
        trend = us_market_service.get_us_intraday_trend(
            symbol="AAPL",
            db=db,
        )
    overlay = us_market_service._get_us_intraday_overlay("AAPL", db=db)

    assert trend["points"] == []
    assert trend["quote_snapshot"]["selected_provider"] == "twelve_data"
    assert trend["quote_snapshot"]["quote"]["last_trade_price"] == "202.5"
    assert "PARTIAL_US_MARKET_VOLUME" in trend["quote_snapshot"]["limitations"]
    assert trend["current_observation"]["price_semantics"] == "resolved_quote_last_trade"
    assert trend["current_observation"]["provider"] == "twelve_data"
    assert trend["current_observation"]["source"] == "twelve_data.quote"
    assert trend["current_source_status"]["provider"] == "twelve_data"
    assert trend["current_source_status"]["source"] == "twelve_data.quote"
    assert trend["current_source_status"]["freshness_status"] == "current"
    assert trend["bar_source_status"] == trend["source_status"]
    assert trend["bar_source_status"]["provider"] == "unresolved"
    assert trend["bar_source_status"]["freshness_status"] == "missing"
    assert trend["market_phase"] == "regular"
    assert trend["capability_expectation"]["quote.snapshot"]["expectation"] == "required"
    assert trend["capability_expectation"]["quote.snapshot"]["outcome"] == "ready"
    assert trend["capability_expectation"]["intraday.bars"]["outcome"] == (
        "expected_but_missing"
    )
    assert trend["current_source_status"]["provider_snapshot_freshness"] == "fresh"
    assert trend["current_source_status"]["trade_recency"] == "current"
    USIntradayTrendRead.model_validate(trend)
    assert trend["quote_snapshot"]["quote"]["previous_close"] == "200.0"
    assert trend["current_observation"]["previous_close"] is None
    assert "CANONICAL_US_DAILY_PREVIOUS_CLOSE_MISSING" in trend[
        "current_observation"
    ]["limitations"]
    assert overlay is not None
    assert overlay["close"] == 202.5
    assert overlay["previous_close"] is None
    assert overlay["provider"] == "twelve_data"


def test_quote_current_observation_uses_exact_canonical_daily_previous_close() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    _seed_daily_previous_close(
        db,
        trade_date=(now.astimezone(US_EASTERN).date() - timedelta(days=1)),
        close_price=199.0,
    )

    def twelve(_route, _requirement):
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=AAPL"

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve},
            clock=lambda: now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    ).refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)

    with _service_clock(now + timedelta(seconds=30)):
        trend = us_market_service.get_us_intraday_trend(symbol="AAPL", db=db)
        overlay = us_market_service._get_us_intraday_overlay("AAPL", db=db)

    assert trend["quote_snapshot"]["quote"]["previous_close"] == "200.0"
    assert trend["previous_close"] == 199.0
    assert trend["previous_close_trade_date"] == "2026-08-27"
    assert trend["previous_close_provider"] == "yahoo_chart"
    assert trend["current_observation"]["previous_close"] == 199.0
    assert overlay is not None
    assert overlay["previous_close"] == 199.0


def test_newer_persisted_bar_wins_over_older_quote_on_current_observation() -> None:
    db = _db()
    quote_now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    bars_now = quote_now + timedelta(minutes=20)

    def twelve_quote(_route, _requirement):
        return _twelve_quote_payload(quote_now), "https://api.twelvedata.com/quote?symbol=AAPL"

    def yahoo_bars(_route, _requirement):
        return (
            _yahoo_bars_payload(bars_now, count=2),
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        )

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve_quote},
            clock=lambda: quote_now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    ).refresh_quote(symbol="AAPL", now=quote_now, max_provider_calls=1)
    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo_bars},
            clock=lambda: bars_now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=bars_now,
        max_provider_calls=1,
    )

    with _service_clock(bars_now + timedelta(seconds=30)):
        trend = us_market_service.get_us_intraday_trend(symbol="AAPL", db=db)

    assert trend["current_observation"]["price_semantics"] == "resolved_intraday_bar_close"
    assert trend["current_observation"]["observed_at"] == trend["points"][-1]["time"]
    assert trend["current_observation"]["provider"] == "yahoo_chart"
    assert trend["current_source_status"]["provider"] == "yahoo_chart"
    assert trend["current_source_status"]["freshness_status"] == "delayed"
    assert trend["bar_source_status"]["provider"] == "yahoo_chart"
    assert trend["bar_source_status"]["freshness_status"] == "delayed"
    assert trend["source_status"] == trend["bar_source_status"]
    assert trend["quote_snapshot"]["selected_provider"] == "twelve_data"


def test_chart_session_scope_does_not_change_headline_or_hide_other_coverage() -> None:
    db = _db()
    quote_now = datetime(2026, 8, 31, 12, 50, tzinfo=UTC)
    bars_now = datetime(2026, 8, 31, 12, 53, tzinfo=UTC)
    read_now = datetime(2026, 8, 31, 14, 32, tzinfo=UTC)

    def twelve_quote(_route, _requirement):
        return _twelve_quote_payload(quote_now), "https://api.twelvedata.com/quote?symbol=AAPL"

    def yahoo_bars(_route, _requirement):
        return (
            _yahoo_bars_payload(bars_now, count=2, age_seconds=0),
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        )

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve_quote},
            clock=lambda: quote_now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    ).refresh_quote(symbol="AAPL", now=quote_now, max_provider_calls=1)
    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo_bars},
            clock=lambda: bars_now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=bars_now,
        max_provider_calls=1,
    )

    with _service_clock(read_now):
        regular = us_market_service.get_us_intraday_trend(
            symbol="AAPL", session_scope="regular", db=db
        )
        extended = us_market_service.get_us_intraday_trend(
            symbol="AAPL", session_scope="extended", db=db
        )
        all_sessions = us_market_service.get_us_intraday_trend(
            symbol="AAPL", session_scope="all", db=db
        )

    assert regular["points"] == []
    assert len(extended["points"]) == 2
    assert len(all_sessions["points"]) == 2
    assert regular["current_observation"] == extended["current_observation"]
    assert extended["current_observation"] == all_sessions["current_observation"]
    assert regular["current_observation"]["price_semantics"] == (
        "resolved_intraday_bar_close"
    )
    assert regular["session_coverage"] == {
        "trade_date": "2026-08-31",
        "regular_point_count": 0,
        "extended_point_count": 2,
        "has_extended_hours": True,
        "requested_scope": "regular",
        "requested_point_count": 0,
    }
    assert regular["regular_point_count"] == 0
    assert regular["extended_point_count"] == 2
    assert extended["session_coverage"]["requested_point_count"] == 2
    assert all_sessions["session_coverage"]["requested_point_count"] == 2
    USIntradayTrendRead.model_validate(regular)


def test_fresh_quote_headline_is_not_downgraded_by_stale_bar_status() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def twelve_quote(_route, _requirement):
        return _twelve_quote_payload(now), "https://api.twelvedata.com/quote?symbol=AAPL"

    def stale_yahoo_bars(_route, _requirement):
        return (
            _yahoo_bars_payload(now, count=2, age_seconds=20 * 60),
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        )

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_QUOTE_RESOURCE_ID: twelve_quote},
            clock=lambda: now,
        ),
        quote_descriptors=(TWELVE_QUOTE_DESCRIPTOR,),
    ).refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)
    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: stale_yahoo_bars},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        max_provider_calls=1,
    )

    with _service_clock(now + timedelta(seconds=30)):
        trend = us_market_service.get_us_intraday_trend(symbol="AAPL", db=db)

    assert trend["current_observation"]["provider"] == "twelve_data"
    assert trend["current_source_status"]["provider"] == "twelve_data"
    assert trend["current_source_status"]["freshness_status"] == "current"
    assert trend["bar_source_status"]["provider"] == "yahoo_chart"
    assert trend["bar_source_status"]["freshness_status"] == "stale"
    assert trend["capability_expectation"]["intraday.bars"]["outcome"] == "stale"


def test_bar_only_current_observation_keeps_legacy_intraday_behavior() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo_bars(_route, _requirement):
        return (
            _yahoo_bars_payload(now, count=2),
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        )

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo_bars},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        max_provider_calls=1,
    )

    with _service_clock(now + timedelta(seconds=30)):
        trend = us_market_service.get_us_intraday_trend(symbol="AAPL", db=db)

    assert trend["quote_snapshot"]["facts_usable"] is False
    assert trend["current_observation"]["provider"] == "yahoo_chart"
    assert trend["current_source_status"] == trend["bar_source_status"]
    assert trend["source_status"] == trend["bar_source_status"]


def test_resolved_current_source_status_preserves_freshness_axes() -> None:
    now = datetime(2026, 8, 28, 14, 35, tzinfo=UTC)
    with patch.object(
        us_market_service,
        "build_us_calendar_status",
        return_value={"phase": "regular"},
    ):
        current = us_market_service._build_us_resolved_source_status(
            provider="twelve_data",
            source="twelve_data.quote",
            resolved_status="selected",
            selected_event_at=now - timedelta(seconds=30),
            selected_fetched_at=now - timedelta(seconds=5),
            trade_state="trade_observed",
            provider_snapshot_controls_freshness=True,
            fallback_used=False,
            facts_usable=True,
            research_usable=True,
            selection_reason="PRIMARY_SELECTED",
            limitations=(),
            session_scope="regular",
            now=now,
        )
        delayed = us_market_service._build_us_resolved_source_status(
            provider="yahoo_chart",
            source="yahoo.chart.quote",
            resolved_status="selected",
            selected_event_at=now - timedelta(seconds=30),
            selected_fetched_at=now - timedelta(seconds=5),
            trade_state="trade_observed",
            fallback_used=False,
            facts_usable=True,
            research_usable=True,
            selection_reason="PRIMARY_SELECTED",
            limitations=("DELAYED_VENDOR_EVIDENCE",),
            session_scope="regular",
            now=now,
        )
        stale = us_market_service._build_us_resolved_source_status(
            provider="twelve_data",
            source="twelve_data.time_series.1m",
            resolved_status="stale",
            selected_event_at=now - timedelta(minutes=20),
            selected_fetched_at=now - timedelta(minutes=20),
            trade_state="trade_observed",
            fallback_used=False,
            facts_usable=True,
            research_usable=False,
            selection_reason="STALE_SELECTED",
            limitations=(),
            session_scope="regular",
            now=now,
        )

    assert current["freshness_status"] == "current"
    assert current["status"] == "ok"
    assert current["provider_snapshot_freshness"] == "fresh"
    assert current["trade_recency"] == "current"
    assert delayed["freshness_status"] == "delayed"
    assert delayed["status"] == "degraded"
    assert stale["freshness_status"] == "stale"
    assert stale["provider_snapshot_freshness"] == "stale"
    assert stale["trade_recency"] == "old"
    assert stale["decision_usable"] is False


def test_old_trade_does_not_make_fresh_provider_snapshot_stale() -> None:
    now = datetime(2026, 8, 28, 11, 5, tzinfo=UTC)
    with patch.object(
        us_market_service,
        "build_us_calendar_status",
        return_value={"phase": "pre_market"},
    ):
        status = us_market_service._build_us_resolved_source_status(
            provider="twelve_data",
            source="twelve_data.quote",
            resolved_status="selected",
            selected_event_at=now - timedelta(minutes=17),
            selected_fetched_at=now - timedelta(seconds=5),
            trade_state="trade_observed",
            provider_snapshot_controls_freshness=True,
            fallback_used=False,
            facts_usable=True,
            research_usable=True,
            selection_reason="PRIMARY_SELECTED",
            limitations=(),
            session_scope="all",
            now=now,
        )

    assert status["provider_snapshot_freshness"] == "fresh"
    assert status["trade_recency"] == "old"
    assert status["freshness_status"] == "current"


def test_fresh_valid_empty_quote_snapshot_is_not_provider_unavailable() -> None:
    now = datetime(2026, 8, 28, 11, 5, tzinfo=UTC)
    with patch.object(
        us_market_service,
        "build_us_calendar_status",
        return_value={"phase": "pre_market"},
    ):
        status = us_market_service._build_us_resolved_source_status(
            provider="twelve_data",
            source="twelve_data.quote",
            resolved_status="empty",
            selected_event_at=None,
            selected_fetched_at=now - timedelta(seconds=5),
            trade_state="awaiting_first_trade",
            provider_snapshot_controls_freshness=True,
            fallback_used=False,
            facts_usable=False,
            research_usable=False,
            selection_reason="NO_TRADE_OBSERVED",
            limitations=(),
            session_scope="all",
            now=now,
        )

    assert status["status"] == "ok"
    assert status["freshness_status"] == "current"
    assert status["provider_snapshot_freshness"] == "fresh"
    assert status["trade_state"] == "awaiting_first_trade"
    assert status["trade_recency"] == "missing"


def test_after_hours_change_reference_uses_current_day_regular_close() -> None:
    now = datetime(2026, 8, 28, 20, 1, tzinfo=UTC)
    regular_close_bar = _canonical_bar(
        start_at=datetime(2026, 8, 28, 19, 59, tzinfo=UTC),
        interval="1m",
        volume=1000,
    )
    reference = us_market_service._build_us_change_reference(
        previous_close_reference={
            "previous_close": 199.0,
            "previous_close_source": "yahoo.chart.1d",
            "previous_close_trade_date": "2026-08-27",
            "previous_close_provider": "yahoo_chart",
            "previous_close_status": "current",
            "prior_regular_close": 199.0,
            "prior_regular_close_source": "yahoo.chart.1d",
            "prior_regular_close_trade_date": "2026-08-27",
            "prior_regular_close_provider": "yahoo_chart",
            "prior_regular_close_status": "current",
        },
        resolved_bars=(regular_close_bar,),
        market_phase="after_hours",
        now=now,
    )

    assert reference["current_day_regular_close"] == 100.5
    assert reference["current_day_regular_close_trade_date"] == "2026-08-28"
    assert reference["change_reference_price"] == 100.5
    assert reference["change_reference_type"] == "current_day_regular_close"
    assert reference["change_reference_reason_code"] == (
        "CURRENT_DAY_REGULAR_CLOSE_SELECTED"
    )


def test_early_close_change_reference_uses_thirteen_hundred_close() -> None:
    now = datetime(2026, 11, 27, 18, 1, tzinfo=UTC)
    early_close_bar = _canonical_bar(
        start_at=datetime(2026, 11, 27, 17, 59, tzinfo=UTC),
        interval="1m",
        volume=1000,
    )
    reference = us_market_service._build_us_change_reference(
        previous_close_reference={
            "previous_close_status": "missing",
            "prior_regular_close_status": "missing",
        },
        resolved_bars=(early_close_bar,),
        market_phase="after_hours",
        now=now,
    )

    assert reference["current_day_regular_close"] == 100.5
    assert reference["current_day_regular_close_trade_date"] == "2026-11-27"
    assert reference["change_reference_type"] == "current_day_regular_close"


def test_twelve_intraday_limitations_survive_persisted_reread() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def twelve(_route, _requirement):
        return _twelve_bars_payload(now, count=2), "https://api.twelvedata.com/time_series?symbol=AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_INTRADAY_RESOURCE_ID: twelve},
            clock=lambda: now,
        ),
        bar_descriptors=(TWELVE_INTRADAY_DESCRIPTOR,),
    )
    platform.refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        require_live=True,
        max_provider_calls=1,
    )
    bind = db.get_bind()
    db.close()

    with Session(bind) as reread_db:
        reread = USIntradayMarketPlatform(reread_db).read_intraday_bars(
            symbol="AAPL",
            bars=100,
            now=now + timedelta(minutes=1),
        )

    assert reread.result.resolved.health.selected_provider == "twelve_data"
    assert "PARTIAL_US_MARKET_VOLUME" in reread.result.resolved.health.limitations
    assert "PERSONAL_INTERNAL_USE_ONLY" in reread.result.resolved.health.limitations


def test_yahoo_only_persisted_read_does_not_gain_twelve_limitations() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo},
            clock=lambda: now,
        ),
        quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
    )
    platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)
    reread = platform.read_quote(symbol="AAPL", now=now + timedelta(minutes=1))

    assert reread.result.resolved.health.selected_provider == "yahoo_chart"
    assert "PARTIAL_US_MARKET_VOLUME" not in reread.result.resolved.health.limitations


def test_persisted_quote_session_is_owned_by_evidence_timestamp() -> None:
    db = _db()
    evidence_time = datetime(2026, 8, 28, 12, 25, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_payload(evidence_time), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo},
            clock=lambda: evidence_time,
        ),
        quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
    )
    platform.refresh_quote(symbol="AAPL", now=evidence_time, max_provider_calls=1)
    reread = platform.read_quote(
        symbol="AAPL",
        now=datetime(2026, 8, 28, 13, 31, tzinfo=UTC),
    )

    assert reread.result.requirement.session is MarketSession.CONTINUOUS
    assert reread.result.resolved.health.selected_session is MarketSession.PRE_OPEN


def test_persisted_intraday_session_is_owned_by_latest_evidence_timestamp() -> None:
    db = _db()
    evidence_time = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_payload(evidence_time), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo},
            clock=lambda: evidence_time,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )
    platform.refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=evidence_time,
        max_provider_calls=1,
    )
    reread = platform.read_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=datetime(2026, 8, 28, 22, 0, tzinfo=UTC),
    )

    assert reread.result.requirement.session is MarketSession.POST_CLOSE
    assert reread.result.resolved.health.selected_session is MarketSession.CONTINUOUS


def test_intraday_repository_honors_total_max_rows_without_provider_starvation() -> None:
    db = _db()
    yahoo_now = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)
    twelve_now = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_bars_payload(yahoo_now, count=300), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo},
            clock=lambda: yahoo_now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=300,
        now=yahoo_now,
        max_provider_calls=1,
    )

    def twelve(_route, _requirement):
        return _twelve_bars_payload(twelve_now, count=300), "https://api.twelvedata.com/time_series?symbol=AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={TWELVE_INTRADAY_RESOURCE_ID: twelve},
            clock=lambda: twelve_now,
        ),
        bar_descriptors=(TWELVE_INTRADAY_DESCRIPTOR,),
    )
    platform.refresh_intraday_bars(
        symbol="AAPL",
        bars=300,
        now=twelve_now,
        require_live=True,
        max_provider_calls=1,
    )
    requirement = platform._bar_requirement(
        platform.read_intraday_bars(symbol="AAPL", bars=1, now=twelve_now).identity,
        now=twelve_now,
        bars=300,
        history_days=US_INTRADAY_CACHE_HISTORY_DAYS,
        allow_acquisition=False,
        require_live=False,
        max_provider_calls=0,
    ).model_copy(update={"bounds": RequestBounds(max_rows=500, max_candidates=8)})

    batch = USIntradayBarRepository(db).read_bar_candidates(requirement)

    assert sum(len(candidate.bars) for candidate in batch.candidates) == 500
    assert {candidate.bars[0].lineage.provider for candidate in batch.candidates} == {
        "yahoo_chart",
        "twelve_data",
    }
    sessions = platform.read_volume_sessions(
        symbol="AAPL",
        provider="yahoo_chart",
        source="yahoo.chart.1m",
        current_trade_date=twelve_now.astimezone(US_EASTERN).date(),
        comparison_time=time(10, 0),
        max_sessions=20,
    )

    assert len(sessions) == 1
    assert sessions[0].provider == "yahoo_chart"
    assert 0 < sessions[0].cumulative_volume < sessions[0].total_volume


def test_intraday_cache_and_provider_acquisition_horizons_are_separate() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)
    captured = []

    def yahoo(_route, requirement):
        captured.append(requirement)
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    refreshed = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        max_provider_calls=1,
    )

    assert refreshed.result.requirement.request.start_at == now - timedelta(
        days=US_INTRADAY_CACHE_HISTORY_DAYS
    )
    assert captured[0].request.start_at == now - timedelta(
        days=US_RECURRING_INTRADAY_PROFILE.acquisition_history_days
    )


def test_provider_response_is_bounded_before_gateway_row_budget() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 19, 59, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_bars_payload(now, count=1000), "https://query.example.invalid/AAPL"

    refreshed = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    ).refresh_intraday_bars(
        symbol="AAPL",
        bars=600,
        now=now,
        max_provider_calls=1,
    )

    assert len(refreshed.result.resolved.bars) == 600
    assert db.query(MarketIntradayBar).count() == 600
    assert "PROVIDER_RESPONSE_TRUNCATED_TO_REQUEST_BOUND" in (
        refreshed.result.limitations
    )


def test_acquisition_enforces_total_requirement_row_bound() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 19, 59, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_bars_payload(
            now,
            count=50,
            age_seconds=600,
        ), "https://query.example.invalid/AAPL"

    def twelve(_route, _requirement):
        return _twelve_bars_payload(
            now,
            count=100,
        ), "https://api.example.invalid/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        bar_descriptors=(
            YAHOO_INTRADAY_DESCRIPTOR,
            TWELVE_INTRADAY_DESCRIPTOR,
        ),
    )
    identity = platform.read_intraday_bars(symbol="AAPL", bars=1, now=now).identity
    requirement = platform._bar_requirement(
        identity,
        now=now,
        bars=100,
        history_days=1,
        allow_acquisition=True,
        require_live=False,
        max_provider_calls=2,
    ).model_copy(
        update={
            "bounds": RequestBounds(
                max_provider_attempts=2,
                max_external_calls=2,
                max_candidates=8,
                max_rows=100,
            )
        }
    )
    plan = plan_data_acquisition_v2(
        requirement,
        (YAHOO_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_DESCRIPTOR),
    )

    acquired = USIntradayAcquisitionExecutor(
        fetchers={
            YAHOO_INTRADAY_RESOURCE_ID: yahoo,
            TWELVE_INTRADAY_RESOURCE_ID: twelve,
        },
        clock=lambda: now,
    ).acquire_bar_observations(requirement, plan)

    assert len(acquired.observations) == requirement.bounds.max_rows == 100
    assert "PROVIDER_RESPONSE_TRUNCATED_TO_REQUEST_BOUND" in (
        acquired.summary.limitations
    )


def test_bootstrap_quote_uses_fresh_snapshot_even_when_last_trade_is_old() -> None:
    db = _db()
    friday = datetime(2026, 8, 28, 19, 59, tzinfo=UTC)
    sunday = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)

    def yahoo(_route, _requirement):
        return _yahoo_payload(friday), "https://query.example.invalid/AAPL"

    platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo},
            clock=lambda: sunday,
        ),
        quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
    )
    bootstrap = platform.refresh_quote(
        symbol="AAPL",
        now=sunday,
        max_provider_calls=1,
        profile=US_BOOTSTRAP_INTRADAY_PROFILE,
    )
    recurring = platform.read_quote(
        symbol="AAPL",
        now=sunday,
        profile=US_RECURRING_INTRADAY_PROFILE,
    )

    assert bootstrap.result.persistence.committed is True
    assert recurring.postcondition_satisfied is True
    assert recurring.postcondition_reasons == ()
    assert bootstrap.postcondition_satisfied is True
    assert bootstrap.result.resolved.health.status.value == "selected"
    assert bootstrap.postcondition_reasons == ()


def test_yahoo_range_tracks_recurring_and_bootstrap_profiles() -> None:
    now = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)
    db = _db()
    with patch(
        "app.us_market.intraday_acquisition.fetch_yahoo_chart_payload",
        return_value=(
            _yahoo_payload(now),
            "https://query.example.invalid/AAPL",
        ),
    ) as fetch:
        platform = USIntradayMarketPlatform(
            db,
            quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
        )
        platform.refresh_quote(
            symbol="AAPL",
            now=now,
            max_provider_calls=1,
            profile=US_RECURRING_INTRADAY_PROFILE,
        )
        assert fetch.call_args.kwargs["range_value"] == "1d"

        platform.refresh_quote(
            symbol="AAPL",
            now=now + timedelta(minutes=1),
            max_provider_calls=1,
            profile=US_BOOTSTRAP_INTRADAY_PROFILE,
        )
        assert fetch.call_args.kwargs["range_value"] == "5d"


def test_volume_pace_can_use_twenty_complete_prior_sessions() -> None:
    current_date = datetime(2026, 8, 28, 10, 0, tzinfo=US_EASTERN)
    prior_dates = []
    cursor = current_date.date() - timedelta(days=1)
    while len(prior_dates) < 20:
        if cursor.weekday() < 5:
            prior_dates.append(cursor)
        cursor -= timedelta(days=1)
    prior_dates.reverse()
    intraday = (
        _canonical_bar(start_at=current_date, interval="1m", volume=1500),
    )
    historical_sessions = tuple(
        USIntradayVolumeSession(
            trade_date=trade_date,
            provider="yahoo_chart",
            source="yahoo_chart.chart_1m",
            cumulative_volume=1000 + index,
            total_volume=1000 + index,
        )
        for index, trade_date in enumerate(prior_dates)
    )
    daily = [
        _canonical_bar(
            start_at=datetime.combine(
                trade_date,
                current_date.timetz().replace(hour=9, minute=30),
            ),
            interval="1d",
            volume=1000 + index,
        )
        for index, trade_date in enumerate(prior_dates)
    ]

    pace = build_us_resolved_volume_pace(
        symbol="AAPL",
        intraday_bars=intraday,
        daily_bars=tuple(daily),
        historical_sessions=historical_sessions,
    )

    assert pace["same_time_baseline_5d"]["sample_days"] == 5
    assert pace["same_time_baseline_20d"]["sample_days"] == 20
    assert pace["status"] == "ready"


def test_volume_pace_is_truthfully_partial_without_twenty_sessions() -> None:
    current = datetime(2026, 8, 28, 10, 0, tzinfo=US_EASTERN)
    prior = current - timedelta(days=1)
    intraday = (
        _canonical_bar(start_at=prior, interval="1m", volume=1000),
        _canonical_bar(start_at=current, interval="1m", volume=1200),
    )
    daily = (
        _canonical_bar(
            start_at=prior.replace(hour=9, minute=30),
            interval="1d",
            volume=1000,
        ),
    )

    pace = build_us_resolved_volume_pace(
        symbol="AAPL",
        intraday_bars=intraday,
        daily_bars=daily,
    )

    assert pace["status"] == "partial"
    assert any("20 resolved" in warning for warning in pace["warnings"])


def test_persisted_identity_mismatches_fail_closed() -> None:
    db = _db()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=UTC)

    def yahoo_quote(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    quote_platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_QUOTE_RESOURCE_ID: yahoo_quote},
            clock=lambda: now,
        ),
        quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
    )
    quote_platform.refresh_quote(symbol="AAPL", now=now, max_provider_calls=1)
    quote_row = db.query(USQuoteSnapshot).one()
    quote_row.venue = "NYSE"
    db.commit()
    quote_read = quote_platform.read_quote(symbol="AAPL", now=now)

    def yahoo_bars(_route, _requirement):
        return _yahoo_payload(now), "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

    bar_platform = USIntradayMarketPlatform(
        db,
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: yahoo_bars},
            clock=lambda: now,
        ),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )
    bar_platform.refresh_intraday_bars(
        symbol="AAPL",
        bars=100,
        now=now,
        max_provider_calls=1,
    )
    bar_row = db.query(MarketIntradayBar).one()
    bar_row.symbol = "MSFT"
    db.commit()
    bar_read = bar_platform.read_intraday_bars(symbol="AAPL", bars=100, now=now)

    assert quote_read.result.resolved.quote is None
    assert {
        rejection.reason_code for rejection in quote_read.result.candidate_rejections
    } == {"US_QUOTE_INSTRUMENT_IDENTITY_MISMATCH"}
    assert bar_read.result.resolved.bars == ()
    assert {
        rejection.reason_code for rejection in bar_read.result.candidate_rejections
    } == {"US_INTRADAY_INSTRUMENT_IDENTITY_MISMATCH"}
