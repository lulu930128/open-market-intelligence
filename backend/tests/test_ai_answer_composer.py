from __future__ import annotations

import unittest

from app.ai import answer_composer
from app.ai import ask as ai_ask


def _technical_levels() -> dict[str, object]:
    return {
        "kind": "technical_price_levels",
        "latest_price": 930,
        "entry": {
            "preferred_zone": {"low": 803, "high": 834},
            "do_not_chase_above": {"price": 871},
            "breakout_confirm_above": {"price": 950},
        },
        "risk": {
            "short_stop": {"price": 771},
            "technical_invalidation": {"price": 716},
        },
    }


class AiAnswerComposerTests(unittest.TestCase):
    def test_entry_answer_uses_price_levels_and_data_limits(self) -> None:
        answer = answer_composer.build_question_aware_consumer_answer(
            question_intent="entry_decision",
            target={"label": "2327 國巨"},
            analysis_digest={
                "selected_score": 3,
                "selected_confidence": "high",
                "display": "中短線偏多",
                "technical_levels": _technical_levels(),
                "decision_evidence": {
                    "market_session": {
                        "is_trading_day": False,
                        "date": "2026-06-14",
                        "latest_daily_date": "2026-06-12",
                        "next_trading_day": "2026-06-15",
                        "summary": "2026-06-14 非台股交易日，使用 2026-06-12 日線。",
                    },
                    "data_quality": {
                        "price": {"source": "market_daily_price.close_price", "as_of": "2026-06-12"}
                    },
                },
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "question_intent")
        self.assertIn("不建議追價", answer["headline"])
        self.assertIn("追價上限 871", answer["summary"][0])
        self.assertIn("2026-06-14 非台股交易日", answer["data_limits"][0])
        self.assertIn("價格來源 market_daily_price.close_price", answer["data_limits"][1])
        self.assertIn("結論：", answer["text"])

    def test_llm_answer_filters_soft_missing_data_when_backend_has_no_gap(self) -> None:
        answer = answer_composer.build_llm_consumer_answer(
            report={
                "headline": "偏多但等確認",
                "stance": "bullish",
                "confidence": "high",
                "key_observations": ["站上 MA20", "缺少盤中成交快照"],
                "interpretation": ["回檔守住前低再評估"],
                "next_checks": ["等量能確認"],
                "risks": ["跌破 MA20 轉弱"],
                "missing_data": ["缺少 intraday_trend"],
            },
            target={"label": "2330 台積電"},
            analysis_digest={"display": "中短線偏多"},
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "llm_report")
        self.assertEqual(answer["data_limits"], [])
        self.assertNotIn("缺少盤中成交快照", answer["summary"])
        self.assertNotIn("缺少 intraday_trend", answer["detail"])
        self.assertIn("站上 MA20", answer["summary"])

    def test_position_decision_answer_keeps_decision_contract(self) -> None:
        answer = answer_composer.build_position_decision_consumer_answer(
            position_decision={
                "headline": "2330 低於成本但尚未觸發 -5% 停損",
                "stance": "bullish",
                "confidence": "high",
                "summary": ["成本 2,390 / 最新 2,310，浮動約 -3.35%。"],
                "action_plan": [{"label": "技術停損", "text": "觀察 MA20 2,280。"}],
                "risks": ["缺少部位大小。"],
                "data_limits": ["缺少部位大小。"],
                "direct_answer": "先看 MA20 是否失守。",
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "position_decision")
        self.assertEqual(answer["intent"], "position_risk_decision")
        self.assertIn("position_decision", answer)
        self.assertIn("方向：偏多", answer["text"])

    def test_ask_wrappers_delegate_to_answer_composer(self) -> None:
        answer = {
            "headline": "測試",
            "stance_label": "偏多",
            "confidence_label": "高",
            "summary": ["第一點"],
            "action_plan": [{"label": "現在", "text": "觀察"}],
        }

        self.assertEqual(
            ai_ask._consumer_text(answer),
            answer_composer.consumer_text(answer),
        )
        self.assertEqual(
            ai_ask._generic_data_limits(missing=["x"], warnings=[]),
            answer_composer.generic_data_limits(missing=["x"], warnings=[]),
        )


if __name__ == "__main__":
    unittest.main()
