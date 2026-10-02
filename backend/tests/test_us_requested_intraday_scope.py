from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.ai import agentic_planning, agentic_tools, ask_execution, capability_contract, decision_envelope
from app.ai.market_context.us_context import USContextDependencies, read_us_stock_context
from app.ai.schemas import AiAskRequest
from app.us_market import service
from app.us_market.daily_market_state import requested_us_completed_daily_state
from app.us_market.historical_intraday import (
    USIntradayRequestedScope as Scope,
    completed_intraday_window,
    requested_us_intraday_scope,
)
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from test_us_intraday_shared_core import _db, _yahoo_bars_payload


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=ET)


@pytest.mark.parametrize("day,clock,session,expected,reason", [
    ("2026-10-01", "2026-10-01T09:30:00-04:00", "regular", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-02T00:00:00+08:00", "regular", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-01T15:59:59-04:00", "regular", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-01T16:00:00-04:00", "regular", Scope.COMPLETED_HISTORY, None),
    ("2026-10-01", "2026-10-01T16:00:00-04:00", "extended", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-01T19:59:59-04:00", "all", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-01T20:00:00-04:00", "all", Scope.COMPLETED_HISTORY, None),
    ("2026-10-01", "2026-10-01T20:00:00-04:00", "extended", Scope.COMPLETED_HISTORY, None),
    ("2026-10-01", "2026-10-01T04:00:00-04:00", "all", Scope.CURRENT_SESSION, None),
    ("2026-10-01", "2026-10-01T08:00:00-04:00", "regular", Scope.INELIGIBLE, "US_INTRADAY_SESSION_NOT_COMPLETED"),
    ("2026-10-01", "2026-10-01T03:59:59-04:00", "all", Scope.INELIGIBLE, "US_INTRADAY_SESSION_NOT_COMPLETED"),
    ("2026-11-27", "2026-11-27T12:59:59-05:00", "regular", Scope.CURRENT_SESSION, None),
    ("2026-11-27", "2026-11-27T13:00:00-05:00", "regular", Scope.COMPLETED_HISTORY, None),
    ("2026-11-27", "2026-11-27T13:00:00-05:00", "extended", Scope.CURRENT_SESSION, None),
    ("2026-11-27", "2026-11-27T16:59:59-05:00", "all", Scope.CURRENT_SESSION, None),
    ("2026-11-27", "2026-11-27T17:00:00-05:00", "all", Scope.COMPLETED_HISTORY, None),
    ("2026-11-27", "2026-11-27T17:00:00-05:00", "extended", Scope.COMPLETED_HISTORY, None),
    ("2026-09-30", "2026-10-01T12:00:00-04:00", "regular", Scope.COMPLETED_HISTORY, None),
    ("2026-10-02", "2026-10-01T12:00:00-04:00", "regular", Scope.INELIGIBLE, "US_INTRADAY_SESSION_NOT_COMPLETED"),
    ("2026-09-07", "2026-10-01T12:00:00-04:00", "regular", Scope.INELIGIBLE, "US_INTRADAY_NO_TRADING_SESSION"),
    ("2026-09-26", "2026-10-01T12:00:00-04:00", "regular", Scope.INELIGIBLE, "US_INTRADAY_NO_TRADING_SESSION"),
    ("2026-01-02", "2026-10-01T12:00:00-04:00", "regular", Scope.INELIGIBLE, "US_INTRADAY_HISTORY_OUTSIDE_BOUNDED_HORIZON"),
])
def test_requested_scope_and_completed_guard(day, clock, session, expected, reason):
    now = datetime.fromisoformat(clock)
    result = requested_us_intraday_scope(day, now=now, session_scope=session)
    assert result.scope is expected
    assert result.reason_code == reason
    if expected is Scope.COMPLETED_HISTORY:
        _, end = completed_intraday_window(day, now=now, session_scope=session)
        assert end <= now
    else:
        with pytest.raises(ValueError, match=reason or "US_INTRADAY_SESSION_NOT_COMPLETED"):
            completed_intraday_window(day, now=now, session_scope=session)


@pytest.fixture
def current_cache():
    db = _db()
    calls = []

    def fetch(_route, requirement):
        calls.append(requirement)
        return _yahoo_bars_payload(NOW, count=10), "https://fixture.invalid/intraday"

    platform = USIntradayMarketPlatform(
        db, acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: NOW),
        bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
    )
    platform.refresh_intraday_bars(symbol="AAPL", now=NOW, trade_date="2026-10-01", max_provider_calls=1)
    assert len(calls) == 1
    assert calls[0].request.completed_only is False
    service.invalidate_us_intraday_read_cache("AAPL")
    yield db
    service.invalidate_us_intraday_read_cache("AAPL")
    db.close()


def test_explicit_current_reader_uses_same_canonical_evidence(current_cache):
    kwargs = dict(db=current_cache, symbol="AAPL", now=NOW, bypass_read_cache=True)
    implicit = service.get_us_intraday_trend(**kwargs)
    with patch("app.us_market.market_truth.read_us_historical_intraday_trend", side_effect=AssertionError("historical route")):
        explicit = service.get_us_intraday_trend(**kwargs, trade_date="2026-10-01")
    assert explicit["points"] == implicit["points"]
    assert explicit["point_count"] == 10
    assert explicit["requested_trade_date"] == "2026-10-01"
    assert explicit["session_coverage"]["current_session_satisfied"] is True
    assert explicit["session_coverage"] == implicit["session_coverage"]
    assert explicit.get("is_historical") is not True


@pytest.mark.parametrize("clock,scope,historical", [
    ("2026-10-01T16:01:00-04:00", "regular", True),
    ("2026-10-01T16:01:00-04:00", "all", False),
    ("2026-10-01T16:01:00-04:00", "extended", False),
    ("2026-11-27T13:01:00-05:00", "regular", True),
    ("2026-11-27T13:01:00-05:00", "all", False),
])
def test_reader_routes_completed_scope_only(clock, scope, historical):
    now = datetime.fromisoformat(clock)
    db = _db()
    try:
        with patch("app.us_market.market_truth.read_us_historical_intraday_trend", return_value={"historical": True}) as reader:
            result = service.get_us_intraday_trend(
                db=db, symbol="AAPL", trade_date=now.date(), now=now,
                session_scope=scope, bypass_read_cache=True,
            )
        assert reader.called is historical
        if not historical:
            assert result.get("is_historical") is not True
    finally:
        db.close()


@pytest.mark.parametrize("day,scope,now,eligible", [
    ("2026-10-01", "regular", NOW, True),
    ("2026-10-01", "all", NOW.replace(hour=17), True),
    ("2026-10-01", "regular", NOW.replace(hour=17), True),
    ("2026-09-30", "regular", NOW, True),
    ("2026-10-02", "regular", NOW, False),
    ("2026-09-07", "regular", NOW, False),
])
def test_gap_planner_and_reader_scope_parity(day, scope, now, eligible):
    db = _db()
    try:
        with patch.object(agentic_tools, "_now", return_value=now), patch.object(agentic_planning, "datetime") as clock:
            clock.now.return_value = now
            gaps = agentic_tools.scan_us_stock_gaps(
                db, "AAPL", requested_capabilities=("intraday.bars",),
                requested_trade_date=day, session_scope=scope, intraday_interval="5m",
            )
            plan = agentic_planning._selected_us_plan(
                symbol="AAPL", gaps=gaps, requested_capabilities=("intraday.bars",),
                requested_trade_date=day, session_scope=scope, intraday_interval="5m",
            )
        assert "us_intraday_trend" in gaps["missing"]
        assert bool(plan["tool_plan"]) is eligible
        if eligible:
            assert plan["tool_plan"][0]["args"]["trade_date"] == day
            assert plan["tool_plan"][0]["args"]["session_scope"] == scope
            assert not any("US_INTRADAY_SESSION_NOT_COMPLETED" in x for x in gaps["warnings"])
        else:
            assert any("US_INTRADAY_" in x for x in gaps["warnings"])
    finally:
        db.close()


def test_current_context_keeps_quote_and_exact_daily_independent(current_cache):
    dependencies = USContextDependencies(
        us_market_service=service, latest_profile=MagicMock(),
        scan_us_stock_gaps=agentic_tools.scan_us_stock_gaps, now=lambda: NOW,
    )
    params = {"trade_date": "2026-10-01", "include_intraday": True,
              "requested_capabilities": ["quote.snapshot", "intraday.bars"]}
    current = read_us_stock_context(current_cache, symbol="AAPL", market_data_params=params, dependencies=dependencies)
    assert current["data"]["compact"]["quote"]["trade_date"] == "2026-10-01"
    assert "us_daily_price_requested_trade_date" not in current["missing"]
    close_params = ask_execution._us_market_data_params(
        AiAskRequest(question="AAPL 2026-10-01 正式收盤價", market_data_params=params),
        policy={"query_plan": {"selected_capabilities": ["quote.snapshot", "intraday.bars", "daily.ohlcv"]}},
    )
    close = read_us_stock_context(current_cache, symbol="AAPL", market_data_params=close_params, dependencies=dependencies)
    assert close["data"]["compact"]["quote"].get("price") is None
    assert "us_daily_price_requested_trade_date" in close["missing"]
    assert close["data"]["compact"]["intraday_bars"]["series"]["1m"]["point_count"] == 10
    assert not requested_us_completed_daily_state(trade_date=NOW.date(), now=NOW.replace(hour=16, minute=1)).eligible


@pytest.mark.parametrize("satisfied", [False, True])
def test_current_fill_preserves_date_without_historical_completion(satisfied):
    canonical = {"ok": True, "request_status": "completed", "target": {"type": "us_stock", "id": "AAPL", "market": "US"}, "evidence": {}, "execution": {}}
    selection = {"version": "test", "required": ["intraday.bars"], "optional": []}
    payload = {"requested_trade_date": "2026-10-01", "session_scope": "regular", "interval": "1m",
               "point_count": 10 if satisfied else 0, "is_partial": True,
               "session_coverage": {"coverage_status": "partial"}}
    realtime = {"intraday.bars": {"state": "live" if satisfied else "missing", "status_class": "ready" if satisfied else "blocked",
                "decision_usable": satisfied, "refresh_recommended": not satisfied, "refresh_possible_now": True}}
    with patch.object(capability_contract, "datetime") as clock:
        clock.now.return_value = NOW
        manifest = capability_contract.build_manifest(canonical=canonical, selection=selection,
            projected_data={"intraday.bars": payload}, realtime_assessments=realtime)
    item = manifest["capabilities"][0]
    assert item["fill_state"]["satisfied"] is satisfied
    assert item["historical_fill_required"] is False
    plan = capability_contract.build_fill_plan(canonical=canonical, selection=selection, manifest=manifest, scope_type="us_stock")
    assert plan["action_count"] == (0 if satisfied else 1)
    if not satisfied:
        arguments = plan["actions"][0]["invoke"]["arguments"]
        assert arguments["market_data_params"] == {"trade_date": "2026-10-01", "session_scope": "regular", "interval": "1m"}
        assert capability_contract.selected_fill_capabilities(
            continuation=arguments["continuation"], selection=selection, target=canonical["target"],
            scope_type="us_stock", market_data_params=arguments["market_data_params"]) == ("intraday.bars",)


@pytest.mark.parametrize("diagnostics", [False, True])
def test_source_health_matches_selected_provider_per_resource(diagnostics):
    response = {
        "target": {"type": "us_stock", "id": "AAPL", "market": "US"},
        "query_plan": {"selected_capabilities": ["quote.snapshot", "intraday.bars"] + (["diagnostics.source_health"] if diagnostics else [])},
        "result": {"data": {
            "resolved_market_data": {"quote_snapshot": {"selected_provider": "yahoo_chart"}, "intraday_bars": {"selected_provider": "twelve_data"}},
            "source_health": {"kind": "us_source_health", "entries": [
                {"provider": provider, "resource": resource, "target": target, "status": "stale"}
                for provider in ("yahoo_chart", "twelve_data")
                for resource in ("quote_snapshot", "intraday_bars", "daily_price")
                for target in ("AAPL", "MSFT")
            ]},
        }},
    }
    before = deepcopy(response)
    health = decision_envelope._provider_failure_scopes(response)
    assert {(x["provider"], x["resource"], x["target"]) for x in health["selected_source_health"]} == {
        ("yahoo_chart", "quote_snapshot", "AAPL"), ("twelve_data", "intraday_bars", "AAPL")}
    assert len(health["supplemental_source_health"]) == 10
    assert response == before
