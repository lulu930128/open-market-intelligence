from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    USDailyPrice,
    USStockMaster,
)
from app.market_data.eod_coverage import (
    cached_eod_coverage_projection,
    compute_eod_coverage,
    persist_eod_coverage,
    reconcile_eod_coverage,
    taiwan_bulk_eod_refresh_window,
)
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)
from app.pipelines.parse_pipeline import _guard_market_daily_replacement
from app.parsers.twse_daily import parse_twse_daily_raw
from app.us_market.errors import USMarketDataFetchError


EXPECTED = date(2026, 8, 21)
STALE = date(2026, 8, 20)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source_and_raw(db: Session) -> tuple[SourceRegistry, RawFetchResult]:
    source = SourceRegistry(
        source_name="coverage-fixture",
        source_type="fixture",
        category="market_data",
        enabled=True,
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(source_id=source.id, raw_text="[]")
    db.add(raw)
    db.flush()
    return source, raw


def test_tw_coverage_partitions_current_partial_stale_and_missing(db: Session) -> None:
    source, raw = _source_and_raw(db)
    db.add_all(
        [
            StockMaster(stock_id="1101", market="TWSE", instrument_type="stock"),
            StockMaster(stock_id="1102", market="TWSE", instrument_type="stock"),
            StockMaster(stock_id="5501", market="TPEX", instrument_type="stock"),
            StockMaster(stock_id="5502", market="TPEX", instrument_type="stock"),
            StockMaster(stock_id="0050", market="TWSE", instrument_type="ETF"),
        ]
    )
    db.add_all(
        [
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="1101",
                trade_date=EXPECTED,
                close_price=50,
            ),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="1102",
                trade_date=EXPECTED,
                close_price=None,
            ),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="5501",
                trade_date=STALE,
                close_price=20,
            ),
        ]
    )
    db.commit()

    coverage = compute_eod_coverage(db, market="TW", expected_trade_date=EXPECTED)

    assert coverage.universe_count == 4
    assert coverage.current_symbols == {"1101"}
    assert coverage.partial_symbols == {"1102"}
    assert coverage.stale_symbols == {"5501"}
    assert coverage.missing_symbols == {"5502"}
    assert coverage.status == "partial"


def test_us_coverage_uses_official_active_non_etf_non_test_stock_universe(db: Session) -> None:
    db.add_all(
        [
            USStockMaster(symbol="A", exchange="NYSE", asset_type="stock", is_active=True),
            USStockMaster(symbol="B", exchange="NASDAQ", asset_type="stock", is_active=True),
            USStockMaster(symbol="C", exchange="NASDAQ", asset_type="stock", is_active=True),
            USStockMaster(symbol="D", exchange="NYSE", asset_type="stock", is_active=True),
            USStockMaster(symbol="ETF1", exchange="NYSE Arca", asset_type="ETF", is_active=True),
            USStockMaster(
                symbol="TEST",
                exchange="NASDAQ",
                asset_type="stock",
                is_active=True,
                is_test_issue=True,
            ),
        ]
    )
    db.add_all(
        [
            USDailyPrice(provider="yahoo_chart", symbol="A", trade_date=EXPECTED, close_price=10),
            USDailyPrice(provider="yahoo_chart", symbol="B", trade_date=EXPECTED),
            USDailyPrice(provider="yahoo_chart", symbol="C", trade_date=STALE, close_price=9),
        ]
    )
    db.commit()

    coverage = compute_eod_coverage(db, market="US", expected_trade_date=EXPECTED)

    assert coverage.universe_count == 4
    assert coverage.current_symbols == {"A"}
    assert coverage.partial_symbols == {"B"}
    assert coverage.stale_symbols == {"C"}
    assert coverage.missing_symbols == {"D"}


def test_persisted_checkpoint_is_idempotent_and_cache_projection_is_read_only(db: Session) -> None:
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    db.commit()
    coverage = compute_eod_coverage(db, market="TW", expected_trade_date=EXPECTED)

    first = persist_eod_coverage(db, coverage)
    second = persist_eod_coverage(db, coverage)
    projection = cached_eod_coverage_projection(db, market="TW")

    assert first.id == second.id
    assert projection["cache_only"] is True
    assert projection["checkpoint_count"] == 1
    checkpoint = projection["checkpoints"][0]
    assert checkpoint["universe_count"] == 1
    assert checkpoint["missing_count"] == 1


def test_us_repair_rotates_after_cursor_and_resumes_only_unresolved_symbols(db: Session) -> None:
    db.add_all(
        [
            USStockMaster(symbol="A", exchange="NYSE", asset_type="stock", is_active=True),
            USStockMaster(symbol="B", exchange="NYSE", asset_type="stock", is_active=True),
            USStockMaster(symbol="C", exchange="NYSE", asset_type="stock", is_active=True),
        ]
    )
    db.add(USDailyPrice(provider="yahoo_chart", symbol="A", trade_date=EXPECTED, close_price=10))
    db.commit()
    initial = compute_eod_coverage(db, market="US", expected_trade_date=EXPECTED)
    row = persist_eod_coverage(db, initial)
    row.cursor_symbol = "B"
    db.commit()
    calls: list[str] = []

    def fake_refresh(*, db: Session, symbol: str, **_kwargs):
        calls.append(symbol)
        db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol=symbol,
                trade_date=EXPECTED,
                close_price=20,
            )
        )
        db.commit()
        return {"status": "success", "fetched_count": 1, "inserted_count": 1, "updated_count": 0}

    with patch("app.market_data.eod_coverage.refresh_us_daily_prices", side_effect=fake_refresh):
        first = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=1,
            max_runtime_seconds=30,
            sleep_seconds=0,
        )
        second = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=1,
            max_runtime_seconds=30,
            sleep_seconds=0,
        )

    assert calls == ["C", "B"]
    assert first["checkpoint"]["current_count"] == 2
    assert second["status"] == "completed"
    assert second["checkpoint"]["current_count"] == 3


def test_daily_parser_guard_refuses_large_same_date_regression_before_delete(db: Session) -> None:
    source, raw = _source_and_raw(db)
    db.add_all(
        [
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id=f"{index:04d}",
                trade_date=EXPECTED,
                close_price=10,
            )
            for index in range(100)
        ]
    )
    db.commit()

    with pytest.raises(ValueError, match="Refusing destructive market daily replacement"):
        _guard_market_daily_replacement(
            db,
            source_id=source.id,
            parsed_rows=[
                {"stock_id": f"{index:04d}", "trade_date": EXPECTED}
                for index in range(20)
            ],
        )

    assert db.query(MarketDailyPrice).count() == 100


def test_us_rate_limit_stops_shard_and_persists_retry_boundary(db: Session) -> None:
    db.add_all(
        [
            USStockMaster(symbol="A", exchange="NYSE", asset_type="stock", is_active=True),
            USStockMaster(symbol="B", exchange="NYSE", asset_type="stock", is_active=True),
        ]
    )
    db.commit()
    failure = ProviderHttpFailure(
        context=ProviderRequestContext(
            market="us",
            provider="yahoo_chart",
            resource="daily_price",
            target="A",
        ),
        status="rate_limited",
        source_url="https://query1.finance.yahoo.com/v8/finance/chart/A",
        http_status_code=429,
        rate_limited=True,
        retry_after_seconds=120,
        error_message="HTTP 429",
    )

    def fail_refresh(**_kwargs):
        provider_error = ProviderHttpError("HTTP 429", failure=failure)
        raise USMarketDataFetchError("HTTP 429") from provider_error

    with patch("app.market_data.eod_coverage.refresh_us_daily_prices", side_effect=fail_refresh) as refresh:
        result = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=2,
            max_runtime_seconds=30,
            sleep_seconds=0,
            error_backoff_seconds=300,
        )

    assert refresh.call_count == 1
    assert result["status"] == "partial"
    assert result["checkpoint"]["repair_status"] == "rate_limited"
    assert result["checkpoint"]["next_retry_at"] is not None
    assert result["checkpoint"]["failed_count"] == 1


def test_taiwan_bulk_window_blocks_live_session_and_allows_closed_day_catchup() -> None:
    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 20),
        now=datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
    )
    assert eligible is False
    assert retry_at is not None
    assert reason == "current_trading_session_not_finalized"

    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 21),
        now=datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc),
    )
    assert eligible is True
    assert retry_at is None
    assert reason == "closed_day_latest_bulk_snapshot"


def test_twse_parser_uses_expected_trade_date_for_dateless_weekend_payload(db: Session) -> None:
    source, _raw = _source_and_raw(db)
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc),
        raw_text='[{"Code":"2330","Name":"TSMC","ClosingPrice":"100"}]',
    )
    db.add(raw)
    db.flush()

    rows, skipped = parse_twse_daily_raw(
        raw,
        fallback_trade_date=date(2026, 8, 21),
    )

    assert skipped == 0
    assert rows[0]["trade_date"] == date(2026, 8, 21)
