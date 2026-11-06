"""Regression coverage for usable research facts without fabricated decisions."""
from copy import deepcopy

import pytest

from app.ai import answer_composer, capability_contract, decision_envelope, query_plan
from app.ai.schemas import AiAskRequest
from test_ai_decision_envelope import _v2_response


@pytest.mark.parametrize("market,scope,symbol,expected", [
    ("US", "us_stock", "AAPL", "technical.structure"),
    ("TW", "stock", "2330", "technical.breakout"),
])
def test_natural_breakout_uses_supported_market_research(market, scope, symbol, expected):
    plan = query_plan.build_query_plan(
        payload=AiAskRequest(question=f"{symbol} 有突破嗎？", target={
            "type": "us_stock" if market == "US" else "tw_stock", "id": symbol}),
        scope_type=scope, target_market=market, question_intent="trend_view",
        effective_mode="full",
    )
    assert expected in plan.selected_capabilities
    if market == "US":
        assert "technical.breakout" not in plan.selected_capabilities


def test_explicit_unsupported_capability_is_not_silently_remapped():
    plan = query_plan.build_query_plan(
        payload=AiAskRequest(question="AAPL breakout", target={"type": "us_stock", "id": "AAPL"},
                             selection={"include": ["technical.breakout"]}),
        scope_type="us_stock", target_market="US", question_intent="trend_view", effective_mode="full",
    )
    assert "technical.structure" not in plan.selected_capabilities
    assert any(item["capability"] == "technical.breakout"
               for item in plan.selection["unmet_required_capabilities"])


@pytest.fixture
def indicators():
    return {
        "status": "partial", "as_of": "2026-09-01T20:00:00Z", "price_basis": "raw_unadjusted",
        "bar_count": 260, "timeframe": "daily",
        "current": {"close": 150, "moving_averages": {"ma5": 149, "ma20": 147},
                    "rsi": {"rsi14": 58}, "macd": {"line": 2, "signal": 3, "histogram": -1},
                    "atr": {"atr14": 4}, "volume_vs_ma20_pct": 0},
        "quality": {"facts_usable": True, "decision_usable": False,
                    "status": "partial", "reason_codes": ["CORPORATE_ACTION_COVERAGE_INCOMPLETE"]},
    }


def test_factual_answer_preserves_indicators_zero_and_quality(indicators):
    original = deepcopy(indicators)
    quality = {"capabilities": {"technical.indicators": {
        **indicators["quality"], "temporal": {"latest_date": "2026-09-01"},
    }}}
    answer = answer_composer.build_selected_technical_consumer_answer(
        target={"id": "AAPL"}, projected_data={"technical.indicators": indicators},
        quality=quality, response_preferences=None,
    )
    assert "MA20 147" in answer["text"] and "RSI14 58" in answer["text"]
    assert "HISTOGRAM -1" in answer["text"] and "均量: 0%" in answer["text"]
    assert "公司行動覆蓋尚未確認" in answer["text"]
    assert answer["action_plan"] == [] and answer["scenarios"] == []
    assert indicators == original
    quality["capabilities"]["technical.indicators"]["facts_usable"] = False
    assert answer_composer.build_selected_technical_consumer_answer(
        target={"id": "AAPL"}, projected_data={"technical.indicators": indicators},
        quality=quality, response_preferences=None,
    ) == {}


def test_tw_selected_daily_facts_use_completed_snapshot_and_keep_corporate_limits():
    evidence = {"as_of": "2026-11-05", "price_basis": "raw_unadjusted", "timeframes": {"daily": {
        "completed_bars": 80,
        "completed": {"close": 120, "ma": {"ma20": 118}, "kd": {"k9": 0, "d9": 12},
                      "volume": 0, "volume_unit": "shares", "volume_ma": {"volume_ma20": 1234}},
        "current_partial": {"close": 999},
        "corporate_action": {"adjustment_applied": False, "affected_dates": ["2026-10-01"]},
    }}}
    answer = answer_composer.build_selected_technical_consumer_answer(
        target={"id": "2330"}, projected_data={"technical.indicators": evidence},
        quality={"capabilities": {"technical.indicators": {"facts_usable": True, "decision_usable": True}}},
        response_preferences=None,
    )
    assert "日線收盤: 120" in answer["text"] and "999" not in answer["text"]
    assert "MA20 118" in answer["text"] and "K9 0" in answer["text"]
    assert "成交量: 0 (shares)" in answer["text"] and "20 日均量: 1,234" in answer["text"]
    assert "價格尚未還原權息" in answer["text"]
    assert answer["action_plan"] == []


@pytest.mark.parametrize("style", ["context_status_summary", "existing_research"])
def test_public_tw_facts_replace_only_generic_status_answer(indicators, style):
    response = _v2_response()
    response["question"] = "2330 技術指標"
    response["analysis"]["human_answer"]["style"] = style
    response["query_plan"] = {"target_type": "stock", "payload_level": "full",
        "selection": capability_contract.normalize_selection(
            selection={"include": ["technical.indicators"]}, output="decision_with_evidence",
            realtime_policy="cache_only", payload_level="full", scope_type="stock",
            target_market="TW", question_intent="general",
        )}
    response["result"]["data"]["compact"]["technical_indicators"] = indicators
    canonical = decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")
    if style == "context_status_summary":
        assert canonical["answer"]["style"] == "selected_technical_facts"
        assert "RSI14 58" in canonical["answer"]["text"]
    else:
        # The existing finalizer may independently downgrade unsafe research,
        # but the factual fallback must not replace that answer.
        assert canonical["answer"].get("style") != "selected_technical_facts"


@pytest.mark.parametrize("output", ["decision_with_evidence", "evidence_only"])
def test_public_v4_technical_facts_do_not_upgrade_decision_readiness(indicators, output):
    response = _v2_response(freshness_by_domain={"technical": "latest_completed_session"})
    response["target"] = {"type": "us_stock", "id": "AAPL", "market": "US"}
    response["resolution"]["target"] = dict(response["target"])
    response["question"] = "AAPL 技術指標"
    response["analysis"] = {}
    response["query_plan"] = {
        "target_type": "us_stock", "payload_level": "full",
        "selection": capability_contract.normalize_selection(
            selection={"include": ["technical.indicators"]}, output=output,
            realtime_policy="cache_only", payload_level="full", scope_type="us_stock",
            target_market="US", question_intent="general",
        ),
    }
    response["result"]["data"]["compact"] = {"technical_indicators": indicators}
    canonical = decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")
    assert canonical["evidence"]["quality"]["capabilities"]["technical.indicators"]["decision_usable"] is False
    assert canonical["status"]["readiness"]["decision_ready"] is False
    if output != "evidence_only":
        assert canonical["answer"]["style"] == "selected_technical_facts"
        assert "RSI14 58" in canonical["answer"]["text"]
    else:
        assert not canonical["answer"]
