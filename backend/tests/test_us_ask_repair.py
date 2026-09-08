from copy import deepcopy

import pytest

from app.ai import answer_composer, decision_envelope_v4, reports
from test_ai_decision_envelope import _v2_response


@pytest.mark.parametrize("reverse", [False, True])
def test_us_daily_summary_uses_canonical_anchor_and_previous_session(reverse):
    rows = [
        {"trade_date": "2026-08-24", "close_price": 410.12},
        {"trade_date": "2026-09-03", "close_price": 417.01},
        {"trade_date": "2026-09-04", "close_price": 428.91},
        {"trade_date": "2026-09-08", "close_price": 450},
    ]
    if reverse:
        rows.reverse()
    result = reports._compact_us_stock_summary({
        "summary": {"latest_trade_date": "2026-09-04", "latest_close": 428.91},
        "data": {"daily_prices": rows},
    })
    assert result["latest"]["trade_date"] == "2026-09-04"
    assert result["latest"]["close"] == 428.91
    assert result["latest"]["change_pct"] == pytest.approx((428.91 / 417.01 - 1) * 100)


def test_us_daily_summary_missing_anchor_does_not_substitute_another_day():
    result = reports._compact_us_stock_summary({
        "summary": {"latest_trade_date": "2026-09-04"},
        "data": {"daily_prices": [{"trade_date": "2026-09-03", "close_price": 417.01}]},
    })
    assert result["latest"]["close"] is None


@pytest.mark.parametrize("locale,label", [("zh-TW", "低"), ("en-US", "Low"), ("ja-JP", "低")])
def test_final_quality_cap_renders_localized_confidence(locale, label):
    response = deepcopy(_v2_response(freshness_by_domain={"quote": "missing", "technical": "missing"}))
    response["policy"] = {"response_preferences": {"effective_locale": locale}}
    response["analysis"]["human_answer"].update(confidence="high", confidence_label="High", text="Confidence: High")
    result = decision_envelope_v4.build(response)
    assert result["quality_status"] == "blocked"
    assert result["answer"]["confidence"] == "low"
    assert result["answer"]["confidence_label"] == label
    assert "High" not in result["answer"]["text"]
    assert label in result["answer"]["text"]


@pytest.mark.parametrize("phase,closed", [("market_closed", True), ("regular", False)])
def test_historical_quote_mentions_current_closure_only_with_calendar_evidence(phase, closed):
    answer = answer_composer.build_quote_consumer_answer(
        target={"market": "US", "id": "TSM"},
        analysis_digest={"compact_evidence": {"quote": {
            "price": 428.91, "trade_date": "2026-09-04",
            "quote_semantics": "historical_regular_session_close",
            "current_session_phase": phase, "is_live": False, "is_realtime": False,
        }}},
        missing=[], warnings=[], summary_limit=4, response_preferences=None,
    )
    assert ("目前美股市場已關閉" in answer["text"]) is closed
    assert "2026-09-04" in answer["text"]
