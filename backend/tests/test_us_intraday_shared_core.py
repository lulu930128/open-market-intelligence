from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
import inspect
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketIntradayBar, MarketIntradayBarLineage, USQuoteSnapshot, USStockMaster
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
from app.us_market import service as us_market_service
from app.routers import us_market as us_market_router
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import (
    US_INTRADAY_ACQUISITION_HISTORY_DAYS,
    US_INTRADAY_CACHE_HISTORY_DAYS,
    USIntradayMarketPlatform,
    build_us_resolved_volume_pace,
)
from app.us_market.intraday_repository import (
    USIntradayBarRepository,
    USIntradayVolumeSession,
)
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


def test_registry_separates_quote_and_intraday_lifecycles() -> None:
    quote = DATASET_REGISTRY.get("us.quote.snapshot")
    bars = DATASET_REGISTRY.get("us.intraday.bars")

    assert quote.capability_ids == ("quote.snapshot",)
    assert quote.storage_reference.endswith("us_quote_snapshot")
    assert quote.refresh_operation == "us.refresh_quote"
    assert bars.capability_ids == ("intraday.bars",)
    assert "market_intraday_bar_lineage" in bars.storage_reference
    assert bars.refresh_operation == "us.refresh_intraday_bars"


def test_legacy_us_intraday_reader_is_cache_only_by_source_contract() -> None:
    source = inspect.getsource(us_market_service.get_us_intraday_trend)

    assert "fetch_yahoo_chart_payload" not in source
    assert "parse_yahoo_intraday_prices" not in source
    assert "_persist_us_intraday_history" not in source
    assert ".commit(" not in source
    assert "USIntradayMarketPlatform" in source
    assert ".read_intraday_bars(" in source
    assert "previous_regular_close_from_history" not in source
    assert "bars=30" in source
    assert ".read_volume_sessions(" in source
    router_source = inspect.getsource(us_market_router.get_us_intraday_trend_api)
    assert "refresh_us_" not in router_source
    assert "fetch_" not in router_source


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


def test_stale_yahoo_quote_falls_through_to_fresh_twelve_candidate() -> None:
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

    assert refreshed.result.acquisition.providers_attempted == ("yahoo_chart", "twelve_data")
    assert refreshed.result.resolved.health.selected_provider == "twelve_data"
    assert refreshed.result.resolved.quote is not None
    assert refreshed.result.resolved.quote.last_trade_price == 202.5
    assert "PARTIAL_US_MARKET_VOLUME" in refreshed.result.limitations


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
        days=US_INTRADAY_ACQUISITION_HISTORY_DAYS
    )


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
