from datetime import date
from unittest.mock import Mock

import pytest

from app.jobs import tw_technical_input_readiness as readiness
from app.market_data.contracts import InstrumentKey

DAY = date(2026, 8, 31)
START = date(2026, 8, 3)


def value(*blockers, ready=False):
    return {"coverage_status": "complete", "technical_decision_usable": ready,
        "from_date": START, "to_date": DAY, "day_state_blockers": [
            {"trade_date": "2026-08-10", "state": "fixture", "reasons": list(blockers)}]}


@pytest.mark.parametrize("blocker,operation", [
    ("OFFICIAL_DAILY_EVIDENCE_REQUIRED", "daily_backfill"),
    ("HISTORICAL_INSTRUMENT_STATUS_UNKNOWN", "instrument_event_refresh"),
    ("PRICE_BASIS_EVENT_COVERAGE_REQUIRED", "corporate_event_refresh"),
    ("ALTERNATE_OFFICIAL_PRICE_REQUIRED", "alternate_official_price"),
    ("OFFICIAL_EVIDENCE_CONFLICT", None), ("PRICE_BASIS_CHANGED", None),
])
def test_blocker_dispatch(blocker, operation):
    assert readiness.plan_taiwan_technical_input_repairs(value(blocker)) == ((operation,) if operation else ())


@pytest.mark.parametrize("repaired", [False, True])
def test_common_readiness_dispatch_and_real_postcondition(monkeypatch, repaired):
    reader = Mock(side_effect=[value("HISTORICAL_INSTRUMENT_STATUS_UNKNOWN"), value(ready=repaired), value(ready=True)])
    refresh = Mock(return_value={"status": "success"})
    monkeypatch.setattr(readiness, "read_taiwan_technical_input", reader)
    monkeypatch.setattr(readiness, "refresh_taiwan_instrument_event_history", refresh)
    monkeypatch.setattr(readiness, "resolve_taiwan_instrument", lambda *a: InstrumentKey(
        market="TW", venue="TWSE", symbol="9998", instrument_type="stock"))
    result = readiness.prepare_taiwan_technical_inputs(Mock(), stock_ids=["9998", "9999"], to_date=DAY)
    assert result["attempted"] == ["9998"]
    assert result["unresolved"] == ([] if repaired else ["9998"])
    assert result["results"][1]["status"] == "ready"
    refresh.assert_called_once()
    assert reader.call_count == 3


def test_alternate_official_price_seam_fails_closed():
    result = readiness.resolve_alternate_taiwan_official_price(Mock(), instrument=object(), start_date=START, end_date=DAY)
    assert result["reason"] == "ALTERNATE_OFFICIAL_PRICE_ACQUISITION_UNAVAILABLE"


def test_discord_preparation_has_no_market_semantics():
    import ast
    import inspect
    from app.jobs import market_report_history
    tree = ast.parse(inspect.getsource(market_report_history))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == ["datetime", "app.dispatch.discord_market_report", "app.jobs.tw_technical_input_readiness"]
    source = inspect.getsource(market_report_history)
    assert not any(token in source for token in ("TWSE", "TPEX", "suspension", "price_basis", "MarketDailyPrice"))


def test_1102_older_blockers_are_rechecked_when_recent_day_states_omit_gaps(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_daily_day_state import resolve_taiwan_daily_day_state
    from app.market.trading_calendar import TAIWAN_TZ
    instrument = InstrumentKey(market="TW", venue="TWSE", symbol="1102", instrument_type="stock")
    older = resolve_taiwan_daily_day_state(instrument=instrument, trade_date=date(2026, 8, 20), market_open=True)
    recent = [{"trade_date": "2026-10-30", "state": "TRADED_WITH_PRICE", "blockers": []},
              {"trade_date": "2026-10-31", "state": "MARKET_CLOSED", "blockers": []}]
    raw = {**value(*older.blockers), "day_states": recent, "earliest_available_trade_date": "2026-05-12",
           "technical_reasons": ["TW_TECHNICAL_INSUFFICIENT_BARS", "TW_TECHNICAL_DECISION_WINDOW_GAP"],
           "day_state_blockers": [{"trade_date": "2026-08-20", "state": "MISSING_EVIDENCE", "reasons": list(older.blockers)}]}
    monkeypatch.setattr(readiness, "read_taiwan_technical_input", lambda *a, **k: raw)
    read = Mock(return_value=SimpleNamespace(day_states=(older,)))
    monkeypatch.setattr(TaiwanBarService, "read_bars", read)
    basis = date(2026, 10, 30)
    checked = readiness.read_taiwan_historical_repair_input(Mock(), stock_id="1102", to_date=basis)
    plan = readiness.plan_taiwan_historical_input_repair(checked, to_date=basis)
    assert plan["dates"] == {"2026-08-20": ["instrument_event_refresh", "daily_backfill"]}
    assert read.call_args.kwargs["from_time"] == datetime(2026, 8, 20, tzinfo=TAIWAN_TZ)
    assert checked["day_states"][-1]["instrument_status"] == "unknown"
    # The same outward blocker cannot override a canonical calendar unknown.
    read.return_value = SimpleNamespace(day_states=(older.model_copy(update={"market_open": None}),))
    checked = readiness.read_taiwan_historical_repair_input(Mock(), stock_id="1102", to_date=basis)
    assert not readiness.plan_taiwan_historical_input_repair(checked, to_date=basis)["dates"]


@pytest.mark.parametrize("venue,owner_name", [("TWSE", "backfill_twse_stock_day"), ("TPEX", "backfill_tpex_trading_stock")])
def test_single_stock_step_calls_only_existing_month_owner(monkeypatch, venue, owner_name):
    monkeypatch.setattr(readiness, "resolve_taiwan_instrument", lambda *a: InstrumentKey(
        market="TW", venue=venue, symbol="1102", instrument_type="stock"))
    owner = Mock(return_value={"status": "success"})
    monkeypatch.setattr(readiness, owner_name, owner)
    db = Mock()
    readiness.execute_taiwan_historical_input_step(db, stock_id="1102", basis=date(2026, 10, 30),
        operation="daily_backfill", days=["2026-08-20", "2026-08-03"], timeout_seconds=8)
    assert db.rollback.call_count == 1
    assert owner.call_args.kwargs == dict(db=db, stock_id="1102", start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 20), skip_existing_months=False, sleep_seconds=0, timeout_seconds=8)
    with pytest.raises(ValueError):
        readiness.execute_taiwan_historical_input_step(db, stock_id="1102", basis=DAY,
            operation="daily_backfill", days=["2026-07-31", "2026-08-03"])


def test_large_day_states_are_opt_in_and_do_not_expand_existing_preparation_receipts(monkeypatch):
    monkeypatch.setattr(readiness, "list_stock_ohlc_chart_data", lambda **kw: {"coverage_status": "complete"})
    monkeypatch.setattr(readiness, "build_stock_technical_report", lambda **kw: {
        "status": "ready", "data": {"input_quality": {"decision_usable": True,
            "day_states": [{"lineage": "large fixture"}] * 400}}})
    assert "day_states" not in readiness.read_taiwan_technical_input(Mock(), stock_id="1102", to_date=DAY)
    assert len(readiness.read_taiwan_technical_input(Mock(), stock_id="1102", to_date=DAY,
        include_historical_states=True)["day_states"]) == 400
