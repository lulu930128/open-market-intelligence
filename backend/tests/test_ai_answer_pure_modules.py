from __future__ import annotations

import unittest

from app.ai import answer_composer, answer_data_limits, answer_localization, answer_scenarios


class AIAnswerPureModuleTests(unittest.TestCase):
    def test_answer_composer_keeps_localization_and_data_limit_facades(self) -> None:
        self.assertIs(answer_composer.text_value, answer_localization.text_value)
        self.assertIs(answer_composer.consumer_text, answer_localization.consumer_text)
        self.assertIs(
            answer_composer.warning_is_data_limit,
            answer_data_limits.warning_is_data_limit,
        )
        self.assertIs(
            answer_composer.apply_confidence_cap,
            answer_data_limits.apply_confidence_cap,
        )
        self.assertIs(
            answer_composer.scenario_plan_from_levels,
            answer_scenarios.scenario_plan_from_levels,
        )
        self.assertIs(
            answer_composer.position_scenarios_from_decision,
            answer_scenarios.position_scenarios_from_decision,
        )

    def test_consumer_text_keeps_locale_specific_headings(self) -> None:
        answer = {
            "headline": "Hold",
            "stance_label": "Neutral",
            "confidence_label": "Medium",
            "summary": ["Wait for confirmation"],
        }

        english = answer_localization.consumer_text(
            answer,
            response_preferences={"effective_locale": "en-US"},
        )
        japanese = answer_localization.consumer_text(
            answer,
            response_preferences={"effective_locale": "ja-JP"},
        )

        self.assertTrue(english.startswith("Conclusion: Hold"))
        self.assertIn("Key points:", english)
        self.assertTrue(japanese.startswith("結論：Hold"))
        self.assertIn("要点：", japanese)

    def test_critical_missing_data_caps_confidence_at_low(self) -> None:
        answer = {
            "headline": "觀望",
            "confidence": "high",
            "confidence_label": "高",
            "summary": [],
            "data_limits": [],
        }

        capped = answer_data_limits.apply_confidence_cap(
            answer,
            analysis_digest={"source_refs": []},
            missing=["market_daily_price"],
            warnings=[],
        )

        self.assertEqual(capped["confidence"], "low")
        self.assertEqual(capped["confidence_label"], "低")
        self.assertTrue(any("資料可信度限制" in item for item in capped["data_limits"]))

    def test_scenario_builder_keeps_entry_and_invalidation_structure(self) -> None:
        scenarios = answer_scenarios.scenario_plan_from_levels(
            question_intent="entry_decision",
            fields={"preferred": "100-102", "invalidation": "96"},
            numbers={"latest": 101, "preferred_low": 100, "preferred_high": 102},
            score=2,
            weak_evidence=False,
        )

        self.assertEqual([item["label"] for item in scenarios], ["回測支撐", "失效防守"])
        self.assertIn("100-102", scenarios[0]["text"])
        self.assertIn("96", scenarios[1]["text"])


if __name__ == "__main__":
    unittest.main()
