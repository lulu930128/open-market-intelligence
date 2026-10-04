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
