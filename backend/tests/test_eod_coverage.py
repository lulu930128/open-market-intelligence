from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from unittest.mock import Mock, patch

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
    should_enqueue_eod_reconcile,
    taiwan_bulk_eod_refresh_window,
)
from app.jobs import eod_coverage as eod_coverage_jobs
from app.jobs import service as job_service
from app.sources.defaults import TPEX_DAILY_QUOTES_SOURCE_NAME
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)
from app.pipelines.parse_pipeline import _guard_market_daily_replacement
from app.parsers.twse_daily import parse_twse_daily_raw
from app.us_market.errors import USMarketDataFetchError
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE


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


def _us_daily_row(
    db: Session,
    *,
    symbol: str,
    trade_date: date,
    close_price: float | None,
) -> USDailyPrice:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == "us-eod-fixture")
        .first()
    )
    if source is None:
        source = SourceRegistry(
            source_name="us-eod-fixture",
            source_type="fixture",
            category="market_data",
            enabled=True,
        )
        db.add(source)
        db.flush()
    content_hash = f"{symbol}:{trade_date.isoformat()}".encode().hex().ljust(64, "0")[:64]
    raw = RawFetchResult(
        source_id=source.id,
        content_hash=content_hash,
        raw_text="fixture",
        fetched_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    db.add(raw)
    db.flush()
    return USDailyPrice(
        provider="yahoo_chart",
        symbol=symbol,
        trade_date=trade_date,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        source_id=source.id,
        raw_result_id=raw.id,
        authority="vendor",
        raw_contract_version="yahoo.chart.v8",
        event_at=datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc),
        finalization="final",
        price_basis="raw",
        volume_status="observed",
        volume_unit="shares",
        trade_volume=100,
        raw_payload_hash=content_hash,
    )


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
    detail = coverage.detail()
    assert detail["instrument_inventory_count"] == 5
    assert detail["eligible_count"] == 4
    assert detail["not_eligible_count"] == 1
    assert detail["classification_total"] == 5
    assert detail["classification_invariant_satisfied"] is True
    assert next(
        item
        for item in detail["symbol_classifications"]
        if item["symbol"] == "0050"
    ) == {
        "symbol": "0050",
        "venue": "TWSE",
        "instrument_type": "ETF",
        "classification": "not_eligible",
        "reason": "outside_active_ordinary_stock_dataset_scope",
    }
    venue_breakdown = detail["venue_breakdown"]
    assert venue_breakdown["TWSE"] == {
        "universe_count": 2,
        "current_count": 1,
        "partial_count": 1,
        "stale_count": 0,
        "missing_count": 0,
        "coverage_ratio": 0.5,
        "status": "partial",
    }
    assert venue_breakdown["TPEX"]["current_count"] == 0
    assert venue_breakdown["TPEX"]["stale_count"] == 1
    assert venue_breakdown["TPEX"]["missing_count"] == 1


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
            _us_daily_row(db, symbol="A", trade_date=EXPECTED, close_price=10),
            _us_daily_row(db, symbol="B", trade_date=EXPECTED, close_price=None),
            _us_daily_row(db, symbol="C", trade_date=STALE, close_price=9),
        ]
    )
    db.commit()

    coverage = compute_eod_coverage(
        db,
        market="US",
        expected_trade_date=EXPECTED,
        us_port=US_FULL_MARKET_EOD_LIFECYCLE,
    )

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
    db.add(_us_daily_row(db, symbol="A", trade_date=EXPECTED, close_price=10))
    db.commit()
    initial = compute_eod_coverage(
        db,
        market="US",
        expected_trade_date=EXPECTED,
        us_port=US_FULL_MARKET_EOD_LIFECYCLE,
    )
    row = persist_eod_coverage(db, initial)
    row.cursor_symbol = "B"
    db.commit()
    calls: list[str] = []

    def fake_refresh(db: Session, *, symbol: str, **_kwargs):
        calls.append(symbol)
        db.add(
            _us_daily_row(
                db,
                symbol=symbol,
                trade_date=EXPECTED,
                close_price=20,
            )
        )
        db.commit()
        return {"status": "success", "fetched_count": 1, "inserted_count": 1, "updated_count": 0}

    with patch.object(
        US_FULL_MARKET_EOD_LIFECYCLE,
        "refresh_symbol",
        side_effect=fake_refresh,
    ):
        first = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=1,
            max_runtime_seconds=30,
            sleep_seconds=0,
            us_port=US_FULL_MARKET_EOD_LIFECYCLE,
        )
        second = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=1,
            max_runtime_seconds=30,
            sleep_seconds=0,
            us_port=US_FULL_MARKET_EOD_LIFECYCLE,
        )

    assert calls == ["C", "B"]
    assert first["postcondition_met"] is False
    assert first["checkpoint"]["current_count"] == 2
    assert second["status"] == "completed"
    assert second["postcondition_met"] is True
    assert second["checkpoint"]["current_count"] == 3


def test_partial_coverage_job_fails_terminal_status_but_preserves_partial_result() -> None:
    partial_result = {
        "status": "partial",
        "postcondition_met": False,
        "market": "TW",
        "universe_count": 1973,
        "current_count": 861,
        "partial_count": 19,
        "stale_count": 1091,
        "missing_count": 2,
    }
    captured: list[job_service.JobExecutionError] = []

    def execute(_job_id, worker):
        try:
            worker(object(), Mock())
        except job_service.JobExecutionError as exc:
            captured.append(exc)

    with (
        patch.object(
            eod_coverage_jobs,
            "reconcile_eod_coverage",
            return_value=partial_result,
        ) as reconcile_mock,
        patch.object(
            eod_coverage_jobs.job_service,
            "run_tracked_job",
            side_effect=execute,
        ),
    ):
        eod_coverage_jobs.run_eod_coverage_reconcile_job(
            1,
            "TW",
            True,
            EXPECTED,
            250,
            600,
            0,
            5,
            1800,
        )

    assert len(captured) == 1
    assert (
        reconcile_mock.call_args.kwargs["taiwan_venue_refresher"]
        is eod_coverage_jobs.refresh_taiwan_official_daily_venue
    )
    assert captured[0].result == partial_result
    assert "current=861/1973" in str(captured[0])


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

    def fail_refresh(_db: Session, **_kwargs):
        provider_error = ProviderHttpError("HTTP 429", failure=failure)
        raise USMarketDataFetchError("HTTP 429") from provider_error

    with patch.object(
        US_FULL_MARKET_EOD_LIFECYCLE,
        "refresh_symbol",
        side_effect=fail_refresh,
    ) as refresh:
        result = reconcile_eod_coverage(
            db,
            market="US",
            expected_trade_date=EXPECTED,
            max_symbols=2,
            max_runtime_seconds=30,
            sleep_seconds=0,
            error_backoff_seconds=300,
            us_port=US_FULL_MARKET_EOD_LIFECYCLE,
        )

    assert refresh.call_count == 1
    assert result["status"] == "partial"
    assert result["checkpoint"]["repair_status"] == "rate_limited"
    assert result["checkpoint"]["next_retry_at"] is not None
    assert result["checkpoint"]["failed_count"] == 1


def test_taiwan_bulk_window_allows_released_previous_session_catchup() -> None:
    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 20),
        now=datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
    )
    assert eligible is True
    assert retry_at is None
    assert reason == "released_historical_session"

    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 27),
        now=datetime(2026, 8, 27, 16, 13, tzinfo=timezone.utc),
    )
    assert eligible is True
    assert retry_at is None
    assert reason == "released_historical_session"

    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 27),
        now=datetime(2026, 8, 28, 7, 15, tzinfo=timezone.utc),
    )
    assert eligible is True
    assert retry_at is None
    assert reason == "released_historical_session"


def test_taiwan_bulk_window_keeps_same_day_release_guard_and_rejects_future_date() -> None:
    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 21),
        now=datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
    )
    assert eligible is False
    assert retry_at == datetime(2026, 8, 21, 7, 15, tzinfo=timezone.utc)
    assert reason == "current_trading_session_not_finalized"

    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 24),
        now=datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
    )
    assert eligible is False
    assert retry_at is None
    assert reason == "requested_date_is_not_released"


def test_taiwan_bulk_window_allows_closed_day_latest_session() -> None:

    eligible, retry_at, reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=date(2026, 8, 21),
        now=datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc),
    )
    assert eligible is True
    assert retry_at is None
    assert reason == "closed_day_latest_bulk_snapshot"


def test_release_guard_retry_is_rechecked_without_bypassing_provider_backoff(
    db: Session,
) -> None:
    source, raw = _source_and_raw(db)
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            stock_id="2330",
            trade_date=date(2026, 8, 26),
            close_price=100,
        )
    )
    db.commit()
    expected = date(2026, 8, 27)
    now = datetime(2026, 8, 27, 16, 13, tzinfo=timezone.utc)
    row = persist_eod_coverage(
        db,
        compute_eod_coverage(db, market="TW", expected_trade_date=expected),
    )
    row.repair_status = "deferred"
    row.next_retry_at = now + timedelta(hours=15)
    row.detail_json = json.dumps(
        {
            "repair": {
                "phase": "release_guard",
                "reason": "current_trading_session_not_finalized",
            }
        }
    )
    db.commit()

    assert should_enqueue_eod_reconcile(
        db,
        market="TW",
        expected_trade_date=expected,
        now=now,
    ) is True

    row.repair_status = "rate_limited"
    row.detail_json = json.dumps({"repair": {"phase": "provider_refresh"}})
    db.commit()

    assert should_enqueue_eod_reconcile(
        db,
        market="TW",
        expected_trade_date=expected,
        now=now,
    ) is False


def test_reconcile_bypasses_expired_release_semantics_but_keeps_pinned_date(
    db: Session,
) -> None:
    source, raw = _source_and_raw(db)
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            stock_id="2330",
            trade_date=date(2026, 8, 26),
            close_price=100,
        )
    )
    db.commit()
    expected = date(2026, 8, 27)
    now = datetime(2026, 8, 27, 16, 13, tzinfo=timezone.utc)
    row = persist_eod_coverage(
        db,
        compute_eod_coverage(db, market="TW", expected_trade_date=expected),
    )
    row.repair_status = "deferred"
    row.next_retry_at = now + timedelta(hours=15)
    row.detail_json = json.dumps(
        {"repair": {"phase": "release_guard"}}
    )
    db.commit()

    repair_result = {
        "status": "partial",
        "postcondition_met": False,
        "market": "TW",
        "expected_trade_date": expected,
    }
    with (
        patch("app.market_data.eod_coverage.utc_now", return_value=now),
        patch(
            "app.market_data.eod_coverage._repair_tw_eod",
            return_value=repair_result,
        ) as repair,
    ):
        result = reconcile_eod_coverage(
            db,
            market="TW",
            expected_trade_date=expected,
        )

    assert result == repair_result
    assert repair.call_args.kwargs["computation"].expected_trade_date == expected


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


def test_tw_healthy_lifecycle_performs_zero_provider_calls(db: Session) -> None:
    source, raw = _source_and_raw(db)
    db.add_all(
        [
            StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"),
            StockMaster(stock_id="6488", market="TPEX", instrument_type="stock"),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="2330",
                trade_date=EXPECTED,
                close_price=100,
            ),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="6488",
                trade_date=EXPECTED,
                close_price=200,
            ),
        ]
    )
    db.commit()

    with patch("app.market_data.eod_coverage.refresh_source") as refresh:
        result = reconcile_eod_coverage(
            db,
            market="TW",
            expected_trade_date=EXPECTED,
            repair=True,
        )

    refresh.assert_not_called()
    assert result["status"] == "completed"
    assert result["attempted_count"] == 0
    assert result["dataset_health"]["status"] == "healthy"
    assert (
        result["dataset_lifecycle"]["refresh_operation"]
        == "tw.reconcile_full_market_eod"
    )
    assert (
        result["checkpoint"]["detail"]["dataset_lifecycle"]["health"]["status"]
        == "healthy"
    )


def test_tw_lifecycle_repairs_only_unresolved_venue_then_rereads_coverage(
    db: Session,
) -> None:
    source, raw = _source_and_raw(db)
    tpex_source = SourceRegistry(
        source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
        source_type="api",
        category="market_data",
        endpoint_url="https://example.test/tpex",
        enabled=True,
    )
    db.add(tpex_source)
    db.flush()
    db.add_all(
        [
            StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"),
            StockMaster(stock_id="6488", market="TPEX", instrument_type="stock"),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="2330",
                trade_date=EXPECTED,
                close_price=100,
            ),
        ]
    )
    db.commit()
    calls: list[int] = []

    def fake_refresh(*, db: Session, source_id: int, trade_date: date):
        calls.append(source_id)
        receipt = RawFetchResult(
            source_id=source_id,
            fetched_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            raw_text="[]",
            content_hash="tpex-lifecycle-fixture",
        )
        db.add(receipt)
        db.flush()
        db.add(
            MarketDailyPrice(
                source_id=source_id,
                raw_result_id=receipt.id,
                stock_id="6488",
                trade_date=trade_date,
                close_price=200,
            )
        )
        db.commit()
        return {
            "fetch_status": "success",
            "parse_status": "success",
            "parsed_count": 1,
            "data_quality_status": "valid",
            "error_message": None,
        }

    with (
        patch(
            "app.market_data.eod_coverage.taiwan_bulk_eod_refresh_window",
            return_value=(True, None, "test_completed_session"),
        ),
        patch(
            "app.market_data.eod_coverage.refresh_source",
            side_effect=fake_refresh,
        ),
    ):
        result = reconcile_eod_coverage(
            db,
            market="TW",
            expected_trade_date=EXPECTED,
            repair=True,
            max_symbols=500,
            max_runtime_seconds=1800,
        )

    assert calls == [tpex_source.id]
    assert result["status"] == "completed"
    assert result["attempted_count"] == 1
    assert result["checkpoint"]["current_count"] == 2
    assert result["dataset_health"]["status"] == "healthy"
    assert result["dataset_lifecycle"]["refresh_bounds"]["max_calls"] == 2


def test_tw_transport_success_with_previous_date_payload_is_not_repair_success(
    db: Session,
) -> None:
    source, raw = _source_and_raw(db)
    tpex_source = SourceRegistry(
        source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
        source_type="api",
        category="market_data",
        endpoint_url="https://example.test/tpex",
        enabled=True,
    )
    db.add(tpex_source)
    db.flush()
    db.add_all(
        [
            StockMaster(stock_id="6488", market="TPEX", instrument_type="stock"),
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                stock_id="6488",
                trade_date=STALE,
                close_price=200,
            ),
        ]
    )
    db.commit()

    with (
        patch(
            "app.market_data.eod_coverage.taiwan_bulk_eod_refresh_window",
            return_value=(True, None, "test_completed_session"),
        ),
        patch(
            "app.market_data.eod_coverage.refresh_source",
            return_value={
                "fetch_status": "success",
                "parse_status": "success",
                "parsed_count": 1,
                "data_quality_status": "valid",
                "raw_result_id": 99,
                "fetched_at": datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc),
                "is_duplicate": True,
                "replaced_trade_dates": [STALE],
                "error_message": None,
            },
        ),
    ):
        result = reconcile_eod_coverage(
            db,
            market="TW",
            expected_trade_date=EXPECTED,
            repair=True,
        )

    assert result["status"] == "partial"
    assert result["postcondition_met"] is False
    assert result["success_count"] == 0
    assert result["transport_success_count"] == 1
    assert result["unchanged_count"] == 1
    assert result["checkpoint"]["succeeded_count"] == 0
    assert result["checkpoint"]["last_success_at"] is None
    provider_result = result["checkpoint"]["detail"]["repair"][
        "provider_results"
    ][0]
    assert provider_result["dataset_status"] == "stale_payload"
    assert provider_result["expected_trade_date_observed"] is False
    assert provider_result["dataset_advanced"] is False
    assert provider_result["coverage_before"] == provider_result["coverage_after"]


def test_scheduler_decision_recomputes_persisted_coverage_instead_of_trusting_checkpoint(
    db: Session,
) -> None:
    source, raw = _source_and_raw(db)
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    row = MarketDailyPrice(
        source_id=source.id,
        raw_result_id=raw.id,
        stock_id="2330",
        trade_date=EXPECTED,
        close_price=100,
    )
    db.add(row)
    db.commit()
    persist_eod_coverage(
        db,
        compute_eod_coverage(db, market="TW", expected_trade_date=EXPECTED),
    )
    row.trade_date = STALE
    db.commit()

    with patch(
        "app.market_data.eod_coverage.expected_eod_trade_date",
        return_value=EXPECTED,
    ):
        assert should_enqueue_eod_reconcile(db, market="TW") is True
