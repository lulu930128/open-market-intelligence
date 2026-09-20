from copy import deepcopy

import pytest

from app.ai import capability_contract, decision_envelope_v4


def market_response(capabilities, compact, *, output="decision_with_evidence", locale="zh-TW"):
    selection = capability_contract.normalize_selection(
        selection={"required": capabilities}, output=output,
        realtime_policy="cache_only", payload_level="standard",
        scope_type="market", target_market="TW", question_intent="general",
    )
    return {
        "kind": "ai_ask", "contract_version": "omi.ai.ask.v2", "ok": True,
        "request_status": "completed", "question": "台股市場摘要",
        "target": {"type": "market", "id": "TW", "market": "TW"},
        "mode": {"response": "analysis", "payload_level": "standard"},
        "facts_ready": True, "answer_ready": True, "analysis_ready": True,
        "analysis": {"question_intent": "general", "human_answer": {}},
        "result": {"kind": "market_overview", "data": {"compact": compact}},
        "policy": {"response_preferences": {"locale": locale}},
        "query_plan": {"selection": selection, "target_type": "market"},
        "missing": [], "warnings": [], "source_refs": [],
    }


@pytest.mark.parametrize("output", ["decision", "decision_with_evidence"])
@pytest.mark.parametrize("locale", ["zh-TW", "en-US", "ja-JP"])
def test_factual_breadth_survives_empty_answer_and_blocked_other_capability(output, locale):
    breadth = {
        "status": "partial", "advance_count": 1134, "decline_count": 702,
        "unchanged_count": 0, "trade_date": "2026-09-16",
        "as_of": "2026-09-16T10:30:00+08:00", "label": "上市上櫃已覆蓋範圍",
        "facts_usable": True, "decision_usable": False,
    }
    response = market_response(["market.breadth", "market.hot_groups"], {"breadth": breadth}, output=output, locale=locale)
    original = deepcopy(response)
    result = decision_envelope_v4.build(response)
    text = result["answer"].get("text") or ""
    assert "1,134" in text
    assert "702" in text
    assert "2026-09-16" in text
    assert result["status"]["readiness"]["answer_ready"] is True
    assert result["status"]["readiness"]["decision_ready"] is False
    assert response == original


def test_intraday_ranking_answer_renders_rows_and_eligible_universe():
    ranking = {
        "status": "partial", "metric": "change_pct", "unit": "percent",
        "event_time": "2026-09-16T11:30:00+08:00", "facts_usable": True,
        "coverage": {"ranking_eligible_count": 51, "universe_count": 1967},
        "rows": [
            {"rank": i, "stock_id": str(6000 + i), "stock_name": f"股票{i}", "value": 11 - i, "metric": "change_pct"}
            for i in range(1, 11)
        ],
    }
    response = market_response(["screening.intraday"], {"screening": {"intraday": ranking}})
    result = decision_envelope_v4.build(response)
    text = result["answer"].get("text") or ""
    for row in ranking["rows"]:
        assert row["stock_id"] in text
    assert "51" in text and "1,967" in text
    assert "change_pct" in text and "%" in text
    assert "2026-09-16" in text
    assert "有限樣本" in text


def test_empty_projected_answer_cannot_be_ready_but_evidence_only_can():
    response = market_response(["market.hot_groups"], {})
    result = decision_envelope_v4.build(response)
    assert result["status"]["readiness"]["answer_ready"] is False
    evidence_response = market_response(["market.breadth"], {
        "breadth": {"advance_count": 0, "decline_count": 0, "status": "pending"},
    }, output="evidence_only")
    evidence_result = decision_envelope_v4.build(evidence_response)
    assert evidence_result["answer"] == {}


def test_final_budget_projection_rechecks_answer_content():
    envelope = {"answer": {}, "mode": {"output": "decision"}, "status": {
        "readiness": {"response_ready": True, "answer_ready": True, "answer_kind": "factual_summary"},
    }}
    projection = {}
    decision_envelope_v4._finalize_projection(envelope, projection=projection, max_bytes=1000)
    assert envelope["status"]["readiness"]["answer_ready"] is False


@pytest.mark.parametrize("locale,expected", [("zh-TW", "盤中證據不足"), ("en-US", "insufficient intraday evidence"), ("ja-JP", "データが不足")])
def test_intraday_gap_replaces_bullish_daily_headline_and_actions(locale, expected):
    response = market_response(["intraday.bars", "technical.structure"], {}, locale=locale)
    response["target"] = {"type": "tw_stock", "id": "6147", "market": "TW"}
    response["policy"]["analysis_horizon"] = {"effective": "intraday"}
    response["query_plan"]["target_type"] = "stock"
    response["query_plan"]["selection"] = capability_contract.normalize_selection(
        selection={"required": ["intraday.bars", "technical.structure"]},
        output="decision_with_evidence", realtime_policy="cache_only", payload_level="standard",
        scope_type="stock", target_market="TW", question_intent="trend_view",
    )
    response["analysis"] = {
        "question_intent": "trend_view",
        "human_answer": {"headline": "波段偏多，適合買入", "text": "買入", "summary": ["偏多"]},
    }
    response["result"]["data"]["compact"] = {
        "intraday": {"points": [], "status": "missing"},
        "technical": {"as_of": "2026-09-15", "selected_score": 8, "status": "ready"},
    }
    result = decision_envelope_v4.build(response)
    assert expected in result["answer"]["headline"]
    assert "波段偏多" not in result["answer"]["text"]
    assert "2026-09-15" in result["answer"]["text"]
    assert result["decision"]["action_plan"] == []
    assert result["decision"]["price_levels"] == {}
    assert result["status"]["readiness"]["decision_ready"] is False


def test_text_only_answer_is_content_but_confidence_label_alone_is_not():
    from app.ai.answer_composer import has_answer_content
    assert has_answer_content({"text": "已取得市場資料，僅供限定範圍觀察。"})
    assert not has_answer_content({"text": "信心：低", "confidence_label": "低"})
