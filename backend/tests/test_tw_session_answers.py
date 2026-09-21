from copy import deepcopy
from datetime import datetime

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


@pytest.mark.parametrize("locale", ["zh-TW", "en-US", "ja-JP"])
@pytest.mark.parametrize("status", ["provisional", "partial", "stale"])
@pytest.mark.parametrize("actual_ready", [False, True])
def test_auction_intent_selects_canonical_breadth_without_mutating_actual(locale, status, actual_ready):
    markets = {
        "TWSE": dict(advance_count=431, decline_count=109, unchanged_count=156,
                     coverage_count=696, universe_count=1080),
        "TPEX": dict(advance_count=290, decline_count=44, unchanged_count=87,
                     coverage_count=421, universe_count=887),
    }
    for component in markets.values():
        component.update(status=status, as_of="2026-09-21T08:40:00+08:00")
    breadth = dict(status="ready" if actual_ready else "pending",
                   advance_count=0, decline_count=0, unchanged_count=0,
                   decision_usable=actual_ready, auction_breadth=dict(
                       status=status, is_provisional=True, decision_usable=False,
                       price_semantics="auction_indicative", markets=markets))
    response = market_response(["market.breadth"], {"breadth": breadth}, locale=locale)
    response["question"] = "現在台股試搓狀況如何？請說明漲跌家數，不要把試搓當正式成交。"
    original = deepcopy(response)
    result = decision_envelope_v4.build(response)
    text = result["answer"]["text"]
    for expected in ("431 / 109 / 156", "290 / 44 / 87", "696 / 1080", "421 / 887",
                     "decision_usable=false", status, "08:40:00"):
        assert expected in text
    assert "0 / 0 / 0" not in text
    assert result["status"]["readiness"]["decision_ready"] is False
    assert response == original


@pytest.mark.parametrize("auction", [None, {}, {"status": "missing"},
                                    {"status": "not_applicable", "advance_count": 999},
                                    {"status": "failed", "advance_count": 999},
                                    {"status": "unknown", "advance_count": 999}])
def test_missing_auction_never_falls_back_to_actual_counts(auction):
    breadth = dict(status="ready", decision_usable=True, advance_count=1234,
                   decline_count=456, unchanged_count=789, auction_breadth=auction)
    response = market_response(["market.breadth"], {"breadth": breadth})
    response["question"] = "現在試搓漲跌家數？"
    text = decision_envelope_v4.build(response)["answer"]["text"]
    assert "1234" not in text and "1,234" not in text and "999" not in text
    assert "無資料" in text


def test_regular_intent_does_not_select_auction_breadth():
    breadth = dict(status="ready", decision_usable=True, advance_count=1234,
                   decline_count=456, unchanged_count=789,
                   auction_breadth=dict(status="provisional", advance_count=431))
    response = market_response(["market.breadth"], {"breadth": breadth})
    response["question"] = "不要查試搓，只看正式成交漲跌家數"
    text = decision_envelope_v4.build(response)["answer"]["text"]
    assert "1,234" in text and "431" not in text


def test_partial_auction_keeps_missing_market_and_invalid_counts_visible():
    breadth = {"auction_breadth": {
        "status": "partial", "missing_markets": ["TPEX"],
        "markets": {"TWSE": {
            "status": "provisional", "advance_count": None,
            "decline_count": -1, "unchanged_count": 0,
            "coverage_count": 0, "universe_count": 1080,
        }},
    }}
    response = market_response(["market.breadth"], {"breadth": breadth})
    response["question"] = "台股試搓漲跌家數"
    text = decision_envelope_v4.build(response)["answer"]["text"]
    assert "無資料 / 無資料 / 0" in text
    assert "missing_markets=TPEX" in text
    assert "上漲家數較多" not in text and "下跌家數較多" not in text


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


@pytest.mark.parametrize("availability,freshness,coverage,count,research,expected", [
    ("missing", "missing", "missing", 0, False, "缺失或不可用"),
    ("unavailable", "unknown", "unknown", None, False, "缺失或不可用"),
    ("available", "unavailable", "missing", 0, False, "缺失或不可用"),
    ("available", "delayed", "complete", 50, False, "延遲或已過期"),
    ("available", "stale", "partial", 55, False, "延遲或已過期"),
    ("available", "live", "partial", 50, False, "覆蓋或使用條件"),
    ("available", "live", "complete", 55, False, "尚不足以支持本次盤中分析"),
    ("available", "live", "complete", 55, True, "可供盤中研究"),
    ("unknown", "unknown", "unknown", None, False, "尚未確認"),
])
def test_intraday_answer_quality_matrix(availability, freshness, coverage, count, research, expected):
    from app.ai.answer_composer import build_intraday_evidence_gap_answer
    quality = dict(availability_status=availability, freshness_status=freshness,
                   coverage_status=coverage, facts_usable=availability == "available" and count != 0,
                   intraday_research_usable=research, decision_usable=False,
                   reason_codes=["fixture_analysis_gate"])
    original = deepcopy(quality)
    answer = build_intraday_evidence_gap_answer(
        target={"id": "2344" if count == 0 else "2330"}, background_date=None,
        intraday_quality=quality, intraday_evidence={"point_count": count}, response_preferences=None,
    )
    assert expected in answer["text"]
    if count:
        assert "缺失或不可用" not in answer["text"]
    assert "point_count=" not in answer["text"]
    assert "fixture_analysis_gate" not in answer["text"]
    assert quality == original
    assert answer["action_plan"] == []


@pytest.mark.parametrize("intraday_gap", [False, True])
def test_unusable_hot_groups_still_render_stale_and_coverage_limits(intraday_gap):
    groups = {"status": "partial", "facts_usable_for_ranking": False,
              "last_trade_recency": "stale", "event_time": "2026-09-21T09:55:00+08:00",
              "groups": [{"group_name": "半導體", "member_count": 100, "classified_count": 4,
                          "status": "partial", "last_trade_recency": "stale",
                          "facts_usable_for_ranking": False, "mean_return_pct": 99,
                          "ranking_ineligibility_reasons": ["COVERAGE_BELOW_MINIMUM"]}]}
    response = market_response(["market.hot_groups", *(["intraday.bars"] if intraday_gap else [])],
                               {"screening": {"hot_groups": groups}})
    if intraday_gap:
        response["policy"]["analysis_horizon"] = {"effective": "intraday"}
    result = decision_envelope_v4.build(response)
    text = result["answer"]["text"]
    for value in ("族群強弱", "過期", "4/100", "覆蓋不足", "暫不宜排名"):
        assert value in text
    assert "mean_return_pct=99" not in text
    assert "COVERAGE_BELOW_MINIMUM" not in text
    assert result["status"]["readiness"]["decision_ready"] is False


@pytest.mark.parametrize("point_count", [0, 50, 55])
def test_v4_gap_composer_consumes_the_outward_quality_and_count(monkeypatch, point_count):
    from app.ai import answer_composer, realtime_contract
    # This is the observed regular-session request, regardless of when pytest
    # runs. Let the real contract evaluate it with its supported clock input.
    annotate = realtime_contract.annotate_selected_data
    def annotate_at_observation(data, **kwargs):
        return annotate(data, now=datetime.fromisoformat("2026-09-21T09:55:49+08:00"), **kwargs)
    monkeypatch.setattr(realtime_contract, "annotate_selected_data", annotate_at_observation)
    response = market_response(["intraday.bars"], {"intraday": {
        "status": "missing" if point_count == 0 else "delayed",
        "point_count": point_count, "is_complete": False,
        "points": [] if point_count == 0 else [{"time": "2026-09-21T09:49:00+08:00", "close": 2480}],
    }})
    response["policy"]["analysis_horizon"] = {"effective": "intraday"}
    captured = []
    original = answer_composer.build_intraday_evidence_gap_answer
    def capture(**kwargs):
        captured.append(deepcopy(kwargs))
        return original(**kwargs)
    monkeypatch.setattr(answer_composer, "build_intraday_evidence_gap_answer", capture)
    result = decision_envelope_v4.build(response)
    assert len(captured) == 1
    assert captured[0]["intraday_quality"] == result["evidence"]["quality"]["capabilities"]["intraday.bars"]
    assert captured[0]["intraday_quality"]["decision_usable"] is False
    assert captured[0]["intraday_evidence"]["point_count"] == point_count
    if point_count:
        assert "缺失或不可用" not in result["answer"]["text"]
    assert "point_count=" not in result["answer"]["text"]
