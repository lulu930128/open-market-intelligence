from __future__ import annotations

import unittest

from app.watchlists.radar_scoring_v2 import score_radar_signals


class WatchlistRadarScoringV2Tests(unittest.TestCase):
    def test_duplicate_signal_does_not_inflate_score(self) -> None:
        once = score_radar_signals(signal_keys=["donchian_breakout"])
        duplicated = score_radar_signals(
            signal_keys=[
                "donchian_breakout",
                "donchian_breakout",
                "donchian_breakout",
            ]
        )

        self.assertEqual(once["direction_score"], duplicated["direction_score"])
        self.assertEqual(once["evidence_score"], duplicated["evidence_score"])
        self.assertEqual(duplicated["known_signal_count"], 1)

    def test_same_family_signals_saturate(self) -> None:
        one = score_radar_signals(signal_keys=["donchian_breakout"])
        two = score_radar_signals(
            signal_keys=["donchian_breakout", "bollinger_breakout"]
        )
        three = score_radar_signals(
            signal_keys=[
                "donchian_breakout",
                "bollinger_breakout",
                "structure_resistance_breakout",
            ]
        )

        first_gain = two["direction_score"] - one["direction_score"]
        second_gain = three["direction_score"] - two["direction_score"]
        self.assertGreater(first_gain, 0)
        self.assertGreater(second_gain, 0)
        self.assertLess(second_gain, first_gain)

    def test_cross_family_conflict_is_visible(self) -> None:
        result = score_radar_signals(
            signal_keys=[
                "above_ma20",
                "above_ma60",
                "ma20_above_ma60",
                "macd_negative",
                "roc_negative",
                "rsi_weak",
            ]
        )

        self.assertGreater(result["cross_family_conflict_score"], 60)
        self.assertGreater(result["conflict_score"], 25)
        self.assertLess(result["confidence_score"], result["evidence_score"])

    def test_opposing_signals_inside_family_are_not_double_counted_as_evidence(self) -> None:
        aligned = score_radar_signals(
            signal_keys=["macd_positive", "roc_positive", "rsi_bull_zone"]
        )
        conflicted = score_radar_signals(
            signal_keys=[
                "macd_positive",
                "roc_positive",
                "rsi_bull_zone",
                "macd_negative",
                "roc_negative",
                "rsi_weak",
            ]
        )

        self.assertGreater(conflicted["within_family_conflict_score"], 80)
        self.assertLess(conflicted["confidence_score"], aligned["confidence_score"])

    def test_modifier_changes_risk_but_not_technical_direction(self) -> None:
        base = score_radar_signals(
            signal_keys=["donchian_breakout", "above_ma20"]
        )
        with_risk = score_radar_signals(
            signal_keys=[
                "donchian_breakout",
                "above_ma20",
                "rsi_overheated",
                "atr_high_volatility",
            ]
        )

        self.assertEqual(base["direction_score"], with_risk["direction_score"])
        self.assertGreater(with_risk["risk_score"], base["risk_score"])
        self.assertIn("overheated", with_risk["risk_tags"])
        self.assertIn("high_volatility", with_risk["risk_tags"])

    def test_context_alignment_is_reported_but_not_used_in_direction(self) -> None:
        opposed = score_radar_signals(
            signal_keys=["donchian_breakout", "above_ma20"],
            context_alignment_score=-100,
        )
        aligned = score_radar_signals(
            signal_keys=["donchian_breakout", "above_ma20"],
            context_alignment_score=100,
        )

        self.assertEqual(opposed["direction_score"], aligned["direction_score"])
        self.assertEqual(opposed["confidence_score"], aligned["confidence_score"])
        self.assertEqual(opposed["context_alignment_score"], -100)
        self.assertEqual(aligned["context_alignment_score"], 100)

    def test_quality_and_regime_clarity_discount_confidence_only(self) -> None:
        full = score_radar_signals(
            signal_keys=[
                "donchian_breakout",
                "structure_resistance_breakout",
                "macd_positive",
            ]
        )
        discounted = score_radar_signals(
            signal_keys=[
                "donchian_breakout",
                "structure_resistance_breakout",
                "macd_positive",
            ],
            data_quality_score=0.5,
            regime_clarity=0.5,
        )

        self.assertEqual(full["direction_score"], discounted["direction_score"])
        self.assertAlmostEqual(
            discounted["confidence_score"],
            full["confidence_score"] * 0.25,
            places=5,
        )

    def test_unknown_signals_are_explicitly_limited(self) -> None:
        result = score_radar_signals(
            signal_keys=["donchian_breakout", "future_signal"]
        )

        self.assertEqual(result["known_signal_count"], 1)
        self.assertEqual(result["unknown_signal_keys"], ["future_signal"])
        self.assertEqual(
            result["limitations"][0]["code"],
            "unknown_signal_definitions",
        )

    def test_normalization_is_absolute_and_batch_independent(self) -> None:
        keys = [
            "donchian_breakout",
            "structure_resistance_breakout",
            "cross_above_ma60",
            "volume_price_up",
            "macd_positive",
            "roc_positive",
            "above_ma20",
            "above_ma60",
        ]
        result = score_radar_signals(signal_keys=keys)

        self.assertEqual(result, score_radar_signals(signal_keys=reversed(keys)))
        self.assertIn(result["evidence_grade"], {"medium", "strong"})
        self.assertGreater(result["direction_score"], 30)
        self.assertEqual(result["direction"], 1)
        self.assertEqual(result["primary_bucket"], "breakout_high")


if __name__ == "__main__":
    unittest.main()
