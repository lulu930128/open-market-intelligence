from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.db.models import MarketIntradayBar, RawFetchResult, USDailyPrice, USStockMaster
from app.us_market import intraday_materializer as owner
from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from app.us_market.schemas import USOhlcChartRead
from test_us_intraday_shared_core import _db, _seed_daily_previous_close, _yahoo_bars_payload


DAY = date(2026, 10, 8)
START = datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)
AFTER_HOURS = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)  # NY 21:00


def platform_fixture(db, counts, calls, now=AFTER_HOURS):
    def fetch(_route, requirement):
        symbol = requirement.target.instrument.symbol
        calls.append(symbol)
        count = counts[symbol]
        payload = _yahoo_bars_payload(START + timedelta(minutes=count), count=count)
        result = payload["chart"]["result"][0]
        result["meta"]["symbol"] = symbol
        if symbol == "SSO" and count == 237:
            # 236 real rows, one internal missing slot and one missing tail.
            del result["timestamp"][120]
            for values in result["indicators"]["quote"][0].values():
                del values[120]
        return payload, "https://fixture.invalid/intraday"

    return USIntradayMarketPlatform(
        db, acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: now,
        ), bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )


def test_eod_236_390_zero_canonical_postconditions_and_retry_bounds():
    db = _db()
    for symbol in ("SSO", "AMD"):
        db.add(USStockMaster(symbol=symbol, exchange="NASDAQ", is_etf=symbol == "SSO"))
    db.commit()
    calls = []
    counts = {"SSO": 237, "AAPL": 390, "AMD": 0}
    platform = platform_fixture(db, counts, calls)
    for symbol in ("SSO", "AAPL"):
        platform.refresh_intraday_bars(symbol=symbol, trade_date=DAY, now=AFTER_HOURS, max_provider_calls=1)
    calls.clear()

    def run(now):
        return owner.reconcile_us_intraday_session(
            configured_symbols="SSO,AMD", trade_date=DAY, max_symbols=2,
            max_external_calls=2, now=now, session_factory=lambda: db,
            platform_factory=lambda _db: platform,
        )

    result = run(AFTER_HOURS)
    sso, amd = result["results"]
    aapl = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: db, platform_factory=lambda _db: platform,
    )["results"][0]
    assert result["status"] == "partial"
    assert sso["coverage"]["point_count"] == 236
    assert sso["coverage"]["missing_slot_count"] == 154
    assert sso["coverage"]["gap_count"] == 2
    assert aapl["status"] == "complete" and not aapl["acquisition_attempted"]
    assert amd["status"] == "missing" and amd["coverage"]["missing_slot_count"] == 390
    assert calls == ["SSO", "AMD"]
    assert run(AFTER_HOURS + timedelta(minutes=1))["results"][0]["reason"] == "cooldown"
    for minutes in (15, 30, 45):
        result = run(AFTER_HOURS + timedelta(minutes=minutes))
    assert result["results"][0]["reason"] == "acquisition_plan_unfillable"
    assert "PROVIDER_ALREADY_RESERVED" in result["results"][0]["acquisition_limitations"]
    assert len(calls) == 2
    assert db.query(MarketIntradayBar).count() == 626  # no fabricated bars
    db.close()


def test_eod_success_requires_persisted_reread_and_uses_no_streaming_window():
    db = _db()
    calls = []
    platform = platform_fixture(db, {"AAPL": 390}, calls)
    result = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: db, platform_factory=lambda _db: platform,
    )
    assert result["status"] == "success"
    assert result["results"][0]["persistence_committed"]
    assert result["results"][0]["coverage"]["point_count"] == 390
    summary = owner.us_intraday_materializer_runtime_summary()["runs_by_lane"]["equity_eod"]["intraday.bars"]
    assert summary["postconditions_by_symbol"]["AAPL"]["status"] == "complete"
    assert db.query(MarketIntradayBar).count() == 390
    db.close()


def test_job_success_without_rows_cannot_complete_and_budget_reserves_failures():
    db = _db()
    missing = SimpleNamespace(result=SimpleNamespace(resolved=SimpleNamespace(bars=(), health=SimpleNamespace(facts_usable=False))))
    calls = []
    class Platform:
        def read_intraday_bars_for_trade_date(self, **kwargs): return missing
        def refresh_intraday_bars(self, **kwargs):
            from test_us_eod_durable import fixture_route
            kwargs["before_acquire"](fixture_route())
            calls.append(kwargs)
            raise TimeoutError("fixture timeout")
    result = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL,AMD", trade_date=DAY, max_external_calls=1,
        now=AFTER_HOURS, session_factory=lambda: db, platform_factory=lambda _db: Platform(),
    )
    assert len(calls) == 1
    assert result["reserved_external_call_count"] == 1
    assert result["results"][0]["status"] == "missing"
    assert result["results"][1]["reason"] == "external_call_budget_exhausted"


@pytest.mark.parametrize("now", [START, AFTER_HOURS + timedelta(days=6)])
def test_eod_ineligible_date_never_opens_db(now):
    def forbidden(): raise AssertionError("DB opened for ineligible scope")
    with pytest.raises(ValueError):
        owner.reconcile_us_intraday_session(configured_symbols="AAPL", trade_date=DAY, now=now, session_factory=forbidden)


def test_provisional_daily_uses_canonical_regular_bars_and_finalized_daily_wins():
    db = _db()
    now = START + timedelta(minutes=60)
    platform = platform_fixture(db, {"AAPL": 60}, [], now=now)
    platform.refresh_intraday_bars(symbol="AAPL", now=now, max_provider_calls=1)
    _seed_daily_previous_close(db, trade_date=date(2026, 10, 7), close_price=198)
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", return_value=platform):
        chart = USOhlcChartRead.model_validate(read_us_daily_ohlcv_chart(db, symbol="AAPL", include_intraday_overlay=True, now=now))
    overlay = chart.intraday_overlay
    assert overlay is not None
    assert overlay.trade_date == DAY
    assert overlay.finalization == "provisional" and overlay.authority == "derived"
    assert overlay.release_status == "pending_release" and not overlay.decision_usable
    assert overlay.coverage.point_count == 60 and overlay.coverage.missing_slot_count == 330
    assert overlay.point.open == 200 and overlay.point.close == 201.09
    assert chart.point_count == 1 and len(chart.points) == 1
    assert all(point.time < DAY for point in chart.points)
    assert chart.points[-1].close == 198
    assert chart.latest_finalized_data_date == date(2026, 10, 7)
    # Daily reference remains the reference for the finalized chart, not overlay.
    assert chart.expected_previous_close_trade_date == date(2026, 10, 6)
    # No overlay persistence or contamination of daily inputs.
    assert db.query(MarketIntradayBar).count() == 60
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", side_effect=AssertionError("research/AI daily default must not even read intraday")):
        canonical = read_us_daily_ohlcv_chart(db, symbol="AAPL", now=now)
    assert canonical["intraday_overlay"] is None
    assert canonical["points"] == [point.model_dump() for point in chart.points]
    daily = db.query(USDailyPrice).one()
    daily.trade_date = DAY
    daily.open_price, daily.high_price, daily.low_price, daily.close_price = 204, 206, 203, 205
    daily.event_at = START + timedelta(minutes=390)
    daily.fetched_at = START + timedelta(minutes=450)
    db.get(RawFetchResult, daily.raw_result_id).fetched_at = daily.fetched_at
    db.commit()
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", side_effect=AssertionError("final daily must win without intraday IO")):
        chart = read_us_daily_ohlcv_chart(db, symbol="AAPL", include_intraday_overlay=True, now=AFTER_HOURS)
    assert chart["intraday_overlay"] is None and chart["points"][-1]["close"] == 205
    db.close()


def test_scheduler_is_opt_in_and_keeps_explicit_symbols_outside_streaming_hours(monkeypatch):
    from app.jobs import us_intraday_materializer_scheduler as scheduler
    calls = []
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", True)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO,AMD")
    def reconcile(**kwargs):
        calls.append(kwargs)
        return dict(status="partial", succeeded_count=0, failed_count=2, reserved_external_call_count=kwargs["max_external_calls"], results=[])
    monkeypatch.setattr(scheduler, "_load_eod_durable_snapshot", lambda **_: None)
    monkeypatch.setattr(scheduler, "expire_us_intraday_obligations", lambda **_: [])
    monkeypatch.setattr(scheduler, "reconcile_us_intraday_session", reconcile)
    scheduler.reconcile_us_completed_intraday_bars(now=AFTER_HOURS)
    assert calls[0]["trade_date"] == DAY
    assert calls[0]["configured_symbols"] == "SSO,AMD"
    assert type(scheduler.settings).model_fields["enable_us_intraday_reconciliation"].default is False


def test_ohlc_route_keeps_unfinalized_daily_out_of_points_and_is_read_only(monkeypatch):
    from app.routers import us_market as router
    db = _db()
    now = START + timedelta(minutes=60)
    platform = platform_fixture(db, {"AAPL": 60}, [], now=now)
    platform.refresh_intraday_bars(symbol="AAPL", now=now, max_provider_calls=1)
    _seed_daily_previous_close(db, trade_date=date(2026, 10, 7), close_price=198)
    previous = db.query(USDailyPrice).one()
    db.add(USDailyPrice(
        provider=previous.provider, symbol="AAPL", trade_date=DAY,
        open_price=900, high_price=902, low_price=899, close_price=901,
        trade_volume=1, fetched_at=now, source_id=previous.source_id,
        raw_result_id=previous.raw_result_id, authority="vendor",
        raw_contract_version=previous.raw_contract_version, event_at=now,
        finalization="provisional", price_basis="raw", volume_unit="shares", volume_status="observed",
        raw_payload_hash=previous.raw_payload_hash,
    ))
    db.commit()
    real_reader = read_us_daily_ohlcv_chart
    monkeypatch.setattr(router, "read_us_daily_ohlcv_chart", lambda **kwargs: real_reader(**kwargs, now=now))
    with patch.object(db, "commit", side_effect=AssertionError("GET must not commit")), patch.object(platform, "refresh_intraday_bars", side_effect=AssertionError("GET must not refresh")), patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", return_value=platform):
        result = USOhlcChartRead.model_validate(router.get_us_ohlc_chart_data("AAPL", timeframe="daily", bars=90, to_date=None, db=db))
    assert result.point_count == len(result.points) == 1
    assert result.points[-1].time == date(2026, 10, 7)
    assert result.intraday_overlay.point.close == 201.09
    assert result.intraday_overlay.coverage.missing_slot_count == 330
    assert db.query(USDailyPrice).count() == 2
    db.close()


def test_empty_or_historical_chart_never_invents_provisional_bar():
    db = _db()
    for now in (START - timedelta(minutes=5), START + timedelta(minutes=60)):
        chart = read_us_daily_ohlcv_chart(db, symbol="AAPL", include_intraday_overlay=True, now=now)
        assert chart["intraday_overlay"] is None and chart["points"] == []
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", side_effect=AssertionError("dated history must not overlay")):
        chart = read_us_daily_ohlcv_chart(db, symbol="AAPL", include_intraday_overlay=True, now=AFTER_HOURS, to_date=date(2026, 10, 7))
    assert chart["intraday_overlay"] is None
    db.close()
