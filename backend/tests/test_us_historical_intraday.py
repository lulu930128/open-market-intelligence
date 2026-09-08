from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.ai import agentic_planning, ask_execution
from app.ai.schemas import AiAskRequest
from app.db.models import MarketIntradayBar
from app.us_market.historical_intraday import completed_intraday_window, regular_intraday_coverage
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from app.us_market.market_truth import read_us_historical_intraday_trend
from test_us_intraday_shared_core import _db, _yahoo_bars_payload


NOW = datetime(2026, 9, 7, 13, tzinfo=timezone.utc)


@pytest.mark.parametrize("day", ["2026-09-07", "2026-09-08", "2026-09-06", "2026-01-02"])
def test_invalid_or_incomplete_session_is_rejected_before_io(day):
    with pytest.raises(ValueError):
        completed_intraday_window(day, now=NOW)


def test_early_close_and_gap_identity():
    start, end = completed_intraday_window("2026-11-27", now=datetime(2026, 11, 28, tzinfo=timezone.utc))
    assert end.hour == 13
    slots = [start + timedelta(minutes=i) for i in range(210)]
    complete = regular_intraday_coverage(slots, trade_date=start.date())
    assert complete["coverage_status"] == "complete"
    # Equal row count must not hide a missing minute replaced by a duplicate.
    slots[100] = slots[99]
    partial = regular_intraday_coverage(slots, trade_date=start.date())
    assert partial["coverage_status"] == "partial"
    assert partial["duplicate_count"] == partial["missing_slot_count"] == 1


@pytest.mark.parametrize("count", [333, 390])
def test_completed_session_acquisition_persists_rereads_and_is_idempotent(count):
    db = _db()
    calls = []
    def fetch(_route, requirement):
        calls.append(requirement)
        assert requirement.request.completed_only is True
        assert requirement.request.start_at.hour == 13
        assert requirement.request.end_at.hour == 20
        end = datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=count)
        return _yahoo_bars_payload(end, count=count), "https://fixture.invalid/intraday"
    platform = USIntradayMarketPlatform(
        db, acquisition=USIntradayAcquisitionExecutor(fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: NOW),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )
    for _ in range(2):
        result = platform.refresh_intraday_bars(symbol="AAPL", trade_date="2026-09-04", now=NOW, max_provider_calls=1)
        assert result.projection["coverage"]["missing_slot_count"] == 390 - count
        assert result.projection["is_partial"] is (count != 390)
        assert result.postcondition_satisfied is (count == 390)
        assert db.query(MarketIntradayBar).count() == count
    with patch("app.us_market.market_truth.USIntradayMarketPlatform", return_value=platform):
        trend = read_us_historical_intraday_trend(db, symbol="AAPL", trade_date="2026-09-04", evaluated_at=NOW)
    assert trend["point_count"] == count
    assert trend["trade_date"] == "2026-09-04"
    assert trend["is_live"] is False
    assert trend["decision_usable"] is False
    assert trend["is_partial"] is (count != 390)
    assert trend["source_status"]["session_coverage"]["missing_slot_count"] == 390 - count
    assert all(point["decision_usable"] is False for point in trend["points"])
    assert calls
    db.close()


def test_planner_preserves_historical_intraday_target():
    with patch("app.ai.agentic_planning.datetime") as clock:
        clock.now.return_value = NOW
        plan = agentic_planning._selected_us_plan(
            symbol="TSM", gaps={"missing": ["us_intraday_trend"]},
            requested_capabilities=("intraday.bars",), requested_trade_date="2026-09-04",
        )
    assert plan["tool_plan"][0]["args"]["trade_date"] == "2026-09-04"


@pytest.mark.parametrize("selected,expected", [(["quote.snapshot"], False), (["quote.snapshot", "intraday.bars"], True)])
def test_ask_date_normalization_preserves_explicit_intraday_selection(selected, expected):
    params = ask_execution._us_market_data_params(
        AiAskRequest(question="TSM 2026-09-04", market_data_params={"trade_date": "2026-09-04"}),
        policy={"query_plan": {"selected_capabilities": selected}},
    )
    assert params["include_intraday"] is expected


def test_yahoo_adapter_passes_exact_historical_period_without_recent_range():
    from app.us_market.providers.yahoo import fetch_yahoo_chart_payload
    start, end = completed_intraday_window("2026-09-04", now=NOW)
    with patch("app.us_market.providers.yahoo.provider_get") as fetch:
        fetch.return_value.json.return_value = {"chart": {"result": []}}
        fetch.return_value.url = "https://fixture.invalid/chart"
        fetch_yahoo_chart_payload(symbol="TSM", range_value="1d", interval="1m", timeout_seconds=5, start_at=start, end_at=end)
    params = fetch.call_args.kwargs["params"]
    assert "range" not in params
    assert params["period1"] == int(start.timestamp())
    assert params["period2"] == int(end.timestamp())
