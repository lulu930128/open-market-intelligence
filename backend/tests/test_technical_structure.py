import unittest

from app.market.technical_structure import (
    build_moving_average_structure,
    build_price_moving_average_signals,
    build_price_range_signals,
)


class TechnicalStructureTests(unittest.TestCase):
    def test_structure_marks_price_below_all_averages_even_when_alignment_is_mixed(self):
        structure = build_moving_average_structure(
            price=630,
            ma5=773.4,
            ma20=967.15,
            ma60=710.77,
        )

        self.assertEqual(structure["price_state"], "below_all")
        self.assertEqual(structure["price_state_label"], "失守 MA5/MA20/MA60")
        self.assertEqual(structure["alignment"], "mixed")
        self.assertAlmostEqual(structure["distance_pct"]["ma60"], -11.3637, places=4)
        self.assertEqual(structure["primary_reference"], "ma60")

    def test_price_signals_emit_static_and_cross_below_ma60(self):
        signals, score = build_price_moving_average_signals(
            price=630,
            ma5=773.4,
            ma20=967.15,
            ma60=710.77,
            previous_price=720,
            previous_ma20=965,
            previous_ma60=708,
        )
        keys = [signal["key"] for signal in signals]

        self.assertIn("below_ma5", keys)
        self.assertIn("below_ma20", keys)
        self.assertIn("below_ma60", keys)
        self.assertIn("cross_below_ma60", keys)
        self.assertNotIn("cross_below_ma20", keys)
        self.assertLess(score, 0)
        cross = next(signal for signal in signals if signal["key"] == "cross_below_ma60")
        self.assertEqual(cross["level"], "strong")
        self.assertEqual(cross["label"], "跌破 MA60")

    def test_range_signals_use_current_price_against_finalized_levels(self):
        signals, score = build_price_range_signals(
            price=630,
            support=737,
            resistance=1220,
            donchian_upper=1220,
            donchian_lower=731.5,
            bollinger_upper=1231.46,
            bollinger_lower=702.84,
        )
        keys = [signal["key"] for signal in signals]

        self.assertEqual(
            keys,
            ["donchian_breakdown", "structure_support_break", "bollinger_breakdown"],
        )
        self.assertEqual(score, -6)


if __name__ == "__main__":
    unittest.main()
