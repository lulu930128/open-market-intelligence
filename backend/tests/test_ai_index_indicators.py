from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.ai import capability_contract, query_plan, decision_envelope
from app.ai.schemas import AiAskRequest
from app.ai.market_context.taiwan_bar_projection import project_taiwan_index_indicators
from app.market.technical_parameters import get_technical_analysis_parameters
from dataclasses import asdict


def bundle(*, partial=False, period=False, usable=True):
    point = {"time": "2026-11-05T09:00:00+08:00", "close": 41574.72,
        "rsi": {"rsi14": 23.7}, "macd": {"macd": -1118, "signal": -497, "histogram": -621},
        "ma": {"ma5": 43592, "ma20": 46640, "ma60": 46490}}
    forming = {**point, "time": "2026-11-06T09:00:00+08:00", "close": 39999}
    data = {"algorithm_version": "tw.technical.indicators.v4", "points": [point, *([forming] if period else [])],
        "decision_bar_count": 1, "calculation_bar_count": 2 if partial or period else 1,
        "decision_usable": usable, "input_quality": {"status": "ready" if usable else "partial", "decision_usable": usable},
        "warmup": {"rsi": {"status": "ready"}}, "parameter_contract": asdict(get_technical_analysis_parameters()),
        "bar_series_revision": "b" * 64, "technical_revision": "t" * 64,
        "bar_lineage_digest": "l" * 64,
        "current_partial": {"point": forming, "decision_usable": False,
            "price_based_observation_usable": True, "volume_based_observation_usable": False} if partial else None}
    return SimpleNamespace(technical=SimpleNamespace(model_dump=lambda **kw: deepcopy(data)))


@pytest.mark.parametrize("usable", [True, False])
def test_index_selection_projects_exact_completed_and_partial_quality(usable):
    value = project_taiwan_index_indicators({"daily": bundle(partial=True, usable=usable),
        "weekly": bundle(period=True), "monthly": bundle()}, index_id="TAIEX")
    selection = capability_contract.normalize_selection(selection={"include": ["technical.indicators"]},
        output="evidence_only", realtime_policy="cache_only", payload_level="compact",
        scope_type="tw_index", target_market="TW", question_intent="general")
    data, unavailable = capability_contract.project_selected_data(
        response={"result": {"data": {"technical_indicators": value}}}, selection=selection)
    assert "technical.indicators" not in unavailable
    actual = data["technical.indicators"]
    assert actual["decision_usable"] is usable
    assert actual["price_unit"] == "index_points"
    assert actual["methods"]["rsi"]["parameters"]["period"] == 14
    for timeframe in ("daily", "weekly"):
        snapshot = actual["timeframes"][timeframe]
        assert snapshot["completed"]["close"] == 41574.72
        assert snapshot["completed"]["macd"]["histogram"] == -621
        assert snapshot["current_partial"]["close"] == 39999
        assert snapshot["current_partial"]["decision_usable"] is False
    assert actual["timeframes"]["daily"]["input_quality"]["decision_usable"] is usable


def test_missing_index_data_stays_unusable():
    value = project_taiwan_index_indicators({}, index_id="TAIEX")
    assert value["status"] == "missing" and value["decision_usable"] is False
    assert value["timeframes"] == {} and value["as_of"] is None


@pytest.mark.parametrize("question,expected", [
    ("加權指數 RSI、MACD 完整結果", {"technical.indicators"}),
    ("加權指數 RSI、MACD 與今天日 K 開盤", {"technical.indicators", "daily.ohlcv"}),
    ("加權指數今天日 K", {"daily.ohlcv"}),
    ("加權指數 RSI 與市場廣度", {"technical.indicators", "market.breadth"}),
])
def test_specific_index_question_selects_requested_research_without_default_breadth(question, expected):
    plan = query_plan.build_query_plan(payload=AiAskRequest(question=question,
        target={"type": "tw_index", "id": "TAIEX", "market": "TW"}),
        scope_type="tw_index", target_market="TW", question_intent="general", effective_mode="data_only")
    selected = set(plan.selection["required"])
    assert expected <= selected
    assert ("market.breadth" in selected) == ("market.breadth" in expected)


def test_explicit_index_breadth_and_general_market_question_retain_requirements():
    for selection in ({}, {"include": ["technical.indicators", "market.breadth"]}):
        plan = query_plan.build_query_plan(payload=AiAskRequest(question="加權指數概況",
            target={"type": "tw_index", "id": "TAIEX"}, selection=selection),
            scope_type="tw_index", target_market="TW", question_intent="general", effective_mode="data_only")
        assert "market.breadth" in plan.selection["required"]


@pytest.mark.parametrize("scope,target_type,symbol", [("stock", "tw_stock", "2330"), ("tw_index", "tw_index", "TAIEX")])
def test_public_budget_compaction_preserves_partial_denial_and_applicability(scope, target_type, symbol):
    from test_ai_decision_envelope import _v2_response
    response = _v2_response()
    response["target"] = {"type": target_type, "id": symbol, "market": "TW"}
    response["resolution"]["target"] = dict(response["target"])
    response["query_plan"] = {"target_type": scope, "payload_level": "compact",
        "selection": capability_contract.normalize_selection(
            selection={"include": ["technical.indicators"], "max_response_bytes": 32768},
            output="evidence_only", realtime_policy="cache_only", payload_level="compact",
            scope_type=scope, target_market="TW", question_intent="general")}
    value = project_taiwan_index_indicators({"daily": bundle(partial=True)}, index_id=symbol)
    partial = value["timeframes"]["daily"]["current_partial"]
    partial.update({"indicator_applicability": {"rsi": "provisional_observation", "mfi": "not_applicable_missing_final_volume"},
        "observation_revision": "r" * 64, "limitations": ["TW_CURRENT_PARTIAL_NOT_DECISION_USABLE"],
        "calculation_diagnostics": "x" * 50000})
    response["result"]["data"]["compact"]["technical_indicators"] = value
    canonical = decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")
    assert canonical["request_status"] == "completed"
    assert canonical["projection"]["truncated"] is True
    assert canonical["projection"]["required_payload_preserved"] is True
    actual = canonical["evidence"]["data"]["technical.indicators"]["timeframes"]["daily"]["current_partial"]
    for field in ("decision_usable", "bar_status", "price_based_observation_usable",
                  "volume_based_observation_usable", "indicator_applicability", "observation_revision", "limitations"):
        assert actual[field] == partial[field]
