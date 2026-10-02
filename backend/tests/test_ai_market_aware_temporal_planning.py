from copy import deepcopy
import ast
from datetime import date, datetime
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.ai import agentic_tools, query_plan
from app.ai.ask_execution import _us_market_data_params
from app.ai.market_context.us_context import USContextDependencies, read_us_stock_context
from app.ai.market_date_request import resolve_us_market_date_request
from app.ai.schemas import AiAskRequest
from app.us_market.daily_market_state import requested_us_completed_daily_state


NOW = datetime(2026, 10, 2, 8, 30, tzinfo=ZoneInfo("America/New_York"))


@pytest.mark.parametrize("market", [None, "US", "JP"])
@pytest.mark.parametrize("question", ["AAPL 今天盤前走勢", "AAPL pre-market trend"])
def test_ambiguous_premarket_is_not_an_auction_without_tw_target(market, question):
    assert not query_plan.has_auction_intent(question, market=market)


def test_temporal_imports_remain_market_owned():
    for name in ("app.us_market.historical_intraday", "app.us_market.trading_calendar"):
        module = importlib.import_module(name)
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(name.startswith("app.ai") for name in imports)


@pytest.mark.parametrize("question,technical", [
    ("AAPL 今天盤前走勢", False),
    ("AAPL 今天盤前走勢如何？再一起看最近日K技術結構與資料新鮮度。", True),
    ("AAPL pre-market trend and daily technical structure", True),
    ("AAPL premarket trend and daily technical structure", True),
])
@pytest.mark.parametrize("intent", ["stock", "quote", "trend_view"])
def test_us_premarket_is_bounded_and_market_aware(question, technical, intent):
    payload = AiAskRequest(question=question, realtime_policy="cache_only")
    before = payload.model_dump()
    plan = query_plan.build_query_plan(payload=payload, scope_type="us_stock", target_market="US",
                                       question_intent=intent, effective_mode="data_only")
    selected = set(plan.selected_capabilities)
    assert {"target.identity", "quote.snapshot", "intraday.bars", "data.freshness"} <= selected
    assert not selected & {"quote.auction", "fundamentals.financials", "corporate.actions", "market.short_volume"}
    if technical:
        assert {"daily.ohlcv", "technical.structure"} <= selected
    params = _us_market_data_params(payload, policy={"query_plan": plan.as_dict()})
    assert params["session_scope"] == "extended"
    assert params["include_intraday"] is True
    assert payload.model_dump() == before


@pytest.mark.parametrize("question", ["台積電盤前試搓", "台積電盤前", "台積電 indicative auction"])
def test_tw_retains_auction_intent(question):
    plan = query_plan.build_query_plan(payload=AiAskRequest(question=question), scope_type="stock",
                                       target_market="TW", question_intent="quote", effective_mode="data_only")
    assert "quote.auction" in plan.selected_capabilities
    assert "intraday.bars" not in plan.selected_capabilities
    assert query_plan.has_auction_intent(question, market="TW")
    assert plan.inferred_session_scope is None


def test_explicit_selection_scope_and_close_flag_survive_nlp():
    payload = AiAskRequest(question="AAPL 今天盤前走勢", realtime_policy="cache_only",
                           selection={"include": ["daily.ohlcv"]},
                           market_data_params={"trade_date": "2026-10-02", "session_scope": "regular",
                                               "require_daily_close": True})
    before = payload.model_dump()
    plan = query_plan.build_query_plan(payload=payload, scope_type="us_stock", target_market="US",
                                       question_intent="stock", effective_mode="data_only")
    assert set(plan.selected_capabilities) == {"target.identity", "daily.ohlcv", "data.freshness"}
    params = _us_market_data_params(payload, policy={"query_plan": plan.as_dict()})
    assert params["require_daily_close"] is True
    assert params["session_scope"] == "regular"
    assert payload.model_dump() == before


def test_negated_premarket_does_not_request_extended_intraday():
    plan = query_plan.build_query_plan(payload=AiAskRequest(question="AAPL 不要盤前，只看日K技術結構"),
                                       scope_type="us_stock", target_market="US",
                                       question_intent="stock", effective_mode="data_only")
    assert "intraday.bars" not in plan.selected_capabilities
    assert plan.inferred_session_scope is None


@pytest.mark.parametrize("day,caps,close,expected", [
    ("2026-10-02", ("intraday.bars", "daily.ohlcv"), False, None),
    ("2026-10-02", ("intraday.bars", "technical.structure"), False, None),
    ("2026-10-02", ("intraday.bars", "daily.ohlcv"), True, "2026-10-02"),
    ("2026-10-02", ("daily.ohlcv",), False, "2026-10-02"),
    ("2026-10-01", ("daily.ohlcv",), False, "2026-10-01"),
    ("2026-10-01", ("intraday.bars", "daily.ohlcv"), False, "2026-10-01"),
    ("2026-10-03", ("intraday.bars", "daily.ohlcv"), False, "2026-10-03"),
    (None, ("intraday.bars", "technical.structure"), False, None),
])
@pytest.mark.parametrize("scope", ["regular", "extended", "all"])
def test_capability_scoped_date(day, caps, close, expected, scope):
    request = resolve_us_market_date_request(explicit_value=day, requested_capabilities=caps,
                                             session_scope=scope, require_daily_close=close, now=NOW)
    assert request.trade_date == (date.fromisoformat(day) if day else None)
    assert request.daily_trade_date == (date.fromisoformat(expected) if expected else None)
    if close:
        assert not request.current_quote_allowed
        state = requested_us_completed_daily_state(trade_date=request.daily_trade_date, now=NOW)
        assert not state.eligible
        assert state.reason_code == "US_DAILY_REQUESTED_SESSION_NOT_RELEASED"


@pytest.mark.parametrize("technical", [False, True])
@pytest.mark.parametrize("day,close,expected", [
    ("2026-10-02", False, None),
    ("2026-10-01", False, date(2026, 10, 1)),
    ("2026-10-02", True, date(2026, 10, 2)),
    (None, False, None),
])
def test_context_and_gap_scan_share_scoped_daily_date(technical, day, close, expected):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    service = MagicMock()
    service.build_us_source_health.return_value = {"entries": [], "summary": {}}
    service.get_us_quote_snapshot.return_value = None
    service.get_us_intraday_trend.return_value = {"points": [], "session_scope": "extended"}
    service.read_us_daily_ohlcv_chart.return_value = {"point_count": 0}
    service.build_us_market_research.return_value = {}
    caps = ("intraday.bars", "technical.structure" if technical else "daily.ohlcv")
    params = {"trade_date": day, "require_daily_close": close, "session_scope": "extended",
              "include_intraday": True, "requested_capabilities": list(caps)}
    before = deepcopy(params)
    result = SimpleNamespace(projection={"bars": [], "limitations": []}, postcondition_satisfied=False)
    with patch("app.ai.market_context.us_context.USDailyOhlcvPlatform") as platform, \
         patch("app.ai.agentic_tools.USDailyOhlcvPlatform") as gap_platform, \
         patch.object(agentic_tools.us_market_service, "get_us_intraday_trend", return_value={"points": []}):
        platform.return_value.read.return_value = result
        gap_platform.return_value.read.return_value = result
        context = read_us_stock_context(db, symbol="AAPL", market_data_params=params,
            dependencies=USContextDependencies(us_market_service=service, latest_profile=MagicMock(),
                                               scan_us_stock_gaps=agentic_tools.scan_us_stock_gaps, now=lambda: NOW))
    assert platform.return_value.read.call_args.kwargs["to_date"] == expected
    if not close:
        assert gap_platform.return_value.read.call_args.kwargs["to_date"] == expected
        assert not any("US_DAILY_REQUESTED_SESSION_NOT_RELEASED" in x for x in context["warnings"])
    else:
        gap_platform.return_value.read.assert_not_called()
        assert "us_daily_price_requested_trade_date" in context["missing"]
        assert context["data"]["compact"]["quote"].get("price") is None
    if technical:
        assert service.build_us_market_research.call_args.kwargs.get("to_date") == expected
    else:
        assert service.read_us_daily_ohlcv_chart.call_args.kwargs["to_date"] == expected
    assert service.get_us_intraday_trend.call_args.kwargs.get("trade_date") == day
    assert service.get_us_intraday_trend.call_args.kwargs["persist_history"] is False
    db.commit.assert_not_called()
    db.flush.assert_not_called()
    assert params == before
