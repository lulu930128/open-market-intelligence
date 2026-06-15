from __future__ import annotations

import unittest

from app.ai import ask as ai_ask
from app.ai import decision_engine


def _technical_levels(
    *,
    latest_price: float = 930,
    breakout: float = 950,
) -> dict[str, object]:
    return {
        "kind": "technical_price_levels",
        "latest_price": latest_price,
        "entry": {
            "preferred_zone": {"low": 803, "high": 834},
            "aggressive_zone": {"low": 835, "high": 855},
            "conservative_zone": {"low": 905, "high": 919},
            "do_not_chase_above": {"price": 871},
            "breakout_confirm_above": {"price": breakout},
        },
        "risk": {
            "short_stop": {"price": 771},
            "technical_invalidation": {"price": 716},
        },
        "context": {"extended": True},
    }


class AiDecisionEngineTests(unittest.TestCase):
    def test_technical_level_fields_and_numbers_parse_entry_and_risk_levels(self) -> None:
        levels = _technical_levels()

        fields = decision_engine.technical_level_fields(levels)
        numbers = decision_engine.technical_level_numbers(levels)

        self.assertEqual(fields["latest"], "930")
        self.assertEqual(fields["preferred"], "803-834")
        self.assertEqual(fields["chase"], "871")
        self.assertEqual(fields["breakout"], "950")
        self.assertEqual(fields["stop"], "771")
        self.assertEqual(fields["invalidation"], "716")
        self.assertEqual(numbers["preferred_low"], 803)
        self.assertEqual(numbers["preferred_high"], 834)
        self.assertEqual(numbers["chase"], 871)
        self.assertEqual(numbers["breakout"], 950)

    def test_entry_decision_with_levels_warns_when_price_is_above_chase(self) -> None:
        levels = _technical_levels()
        fields = decision_engine.technical_level_fields(levels)
        numbers = decision_engine.technical_level_numbers(levels)

        headline, summary, action_plan = decision_engine.entry_decision_with_levels(
            target_label="2327 國巨",
            score=3,
            weak_evidence=False,
            fields=fields,
            numbers=numbers,
        )

        self.assertIn("不建議追價", headline)
        self.assertIn("追價上限 871", summary[0])
        self.assertEqual(action_plan[0]["label"], "現在")
        self.assertIn("追高", action_plan[0]["text"])
        self.assertIn("803-834", action_plan[1]["text"])
        self.assertIn("950", action_plan[1]["text"])

    def test_build_position_decision_calculates_cost_distance_and_data_limits(self) -> None:
        result = {
            "data": {
                "latest_daily": {
                    "trade_date": "2026-06-12",
                    "close_price": 2310,
                },
                "technical_reports": {
                    "daily": {
                        "ma20": 2280,
                        "ma60": 2200,
                    },
                },
                "chart": {
                    "points": [
                        {"time": "2026-06-01", "close": 2400, "low": 2380, "high": 2420},
                        {"time": "2026-06-12", "close": 2310, "low": 2268, "high": 2340},
                    ]
                },
            }
        }

        decision = decision_engine.build_position_decision(
            question="我買在2390，如果跌下去我該加碼還是認賠？停損要守哪？",
            position_context={
                "has_position_context": True,
                "entry_price": 2390,
                "decision_topic": "stop_loss",
            },
            target={"label": "2330 台積電"},
            result=result,
            analysis_digest={
                "selected_score": 2,
                "selected_confidence": "high",
                "display": "中短線偏多但需守支撐",
            },
            supplemental_data_limits=["仍有 1 項資料缺口，結論需保留彈性。"],
        )

        self.assertEqual(decision["kind"], "position_decision")
        self.assertEqual(decision["latest_price"], 2310)
        self.assertAlmostEqual(decision["unrealized_return_pct"], -3.3473, places=4)
        self.assertEqual(decision["stance"], "bullish")
        self.assertEqual(decision["llm_status"], "not_requested")
        self.assertIn("低於成本 2,390", decision["headline"])
        self.assertIn("MA20 2,280", decision["direct_answer"])
        self.assertIn("仍有 1 項資料缺口", decision["data_limits"][1])
        self.assertIn("data.latest_daily.close_price", decision["evidence_used"])

    def test_ask_wrappers_delegate_to_decision_engine(self) -> None:
        levels = _technical_levels()

        self.assertEqual(
            ai_ask._technical_level_fields(levels),
            decision_engine.technical_level_fields(levels),
        )
        self.assertEqual(
            ai_ask._technical_level_summary_lines(levels),
            decision_engine.technical_level_summary_lines(levels),
        )


if __name__ == "__main__":
    unittest.main()
