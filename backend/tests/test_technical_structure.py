import unittest

from app.market.technical_structure import (
    build_moving_average_structure,
    build_price_moving_average_signals,
    build_price_range_signals,
    build_technical_current_state,
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

    def test_current_state_explains_oversold_bearish_trend_and_repair_ladder(self):
        moving_average_structure = build_moving_average_structure(
            price=138,
            ma5=139.6,
            ma20=184.775,
            ma60=149.2817,
        )

        state = build_technical_current_state(
            price=138,
            moving_average_structure=moving_average_structure,
            change_pct=-8,
            volume_ratio=1.557325,
            rsi14=24.8603,
            macd_histogram=-8.5439,
            roc12=-35.814,
            mfi14=20.5674,
            adx14=30.0938,
            plus_di14=22.6319,
            minus_di14=31.9423,
            atr_pct=12.4833,
            donchian_position=7.4219,
            support20=128.5,
            resistance20=256.5,
        )

        self.assertEqual(state["version"], "tw_technical_current_state_v1")
        self.assertEqual(state["headline"]["key"], "bearish_trend")
        self.assertEqual(state["headline"]["label"], "空方趨勢延續")
        self.assertEqual(state["qualifier"]["key"], "oversold_not_reversed")
        self.assertEqual(state["position"]["label"], "3/3 均線下方")
        self.assertEqual(state["position"]["order_label"], "MA5 < MA60 < MA20")
        self.assertEqual(
            [item["key"] for item in state["levels"]],
            ["support20", "ma5", "ma60", "ma20"],
        )
        self.assertAlmostEqual(
            next(item for item in state["levels"] if item["key"] == "ma20")[
                "move_required_pct"
            ],
            33.8949,
            places=4,
        )
        self.assertEqual(
            next(item for item in state["evidence"] if item["key"] == "volume")[
                "state_key"
            ],
            "down_on_high_volume",
        )
        self.assertEqual(
            [item["key"] for item in state["next_conditions"]],
            ["first_reclaim", "structure_repair", "risk_break"],
        )


if __name__ == "__main__":
    unittest.main()
