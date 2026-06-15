from __future__ import annotations

from datetime import date
import unittest

from app.ai import technical_analysis


class AiTechnicalAnalysisTests(unittest.TestCase):
    def test_normalize_points_accepts_stock_index_and_futures_shapes(self) -> None:
        points = technical_analysis._normalize_technical_points(
            [
                {
                    "trade_date": date(2026, 6, 12),
                    "open_price": 100,
                    "high_price": 105,
                    "low_price": 99,
                    "close_price": 104,
                    "trade_volume": 1000,
                },
                {
                    "bar_time": "2026-06-12T09:01:00",
                    "open": 22000,
                    "high": 22050,
                    "low": 21980,
                    "settlement_price": 22010,
                    "total_volume": 200,
                },
                {"time": "bad", "close": None},
            ]
        )

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["time"], "2026-06-12")
        self.assertEqual(points[1]["close"], 22010.0)
        self.assertEqual(points[1]["volume"], 200.0)

    def test_technical_report_from_points_scores_trend(self) -> None:
        points = [
            {"time": f"2026-01-{index + 1:02d}", "close": 100 + index}
            for index in range(30)
        ]

        report = technical_analysis._technical_report_from_points(
            points=points,
            timeframe="daily",
            asset_label="TEST",
        )

        self.assertEqual(report["timeframe"], "daily")
        self.assertGreater(report["score"], 0)
        self.assertIn(report["title"], {"偏多觀察", "波段偏多"})
        self.assertEqual(report["confidence"], "medium")
        self.assertIn("站上 MA20", report["summary"])

    def test_technical_analysis_summary_uses_factor_weight_model(self) -> None:
        technical_reports = {
            "daily": {
                "timeframe": "daily",
                "score": 4,
                "title": "短線偏多",
                "confidence": "high",
                "rows": [
                    {"key": "trend_structure", "direction": 1},
                    {"key": "momentum", "direction": 1},
                    {"key": "volume_flow", "direction": 30},
                    {"key": "volatility_risk", "value": 1},
                    {"key": "institutional_flow", "tone": "positive"},
                ],
            },
            "weekly": {
                "timeframe": "weekly",
                "score": 2,
                "title": "週線偏多",
                "confidence": "medium",
                "rows": [
                    {"key": "trend_structure", "direction": 1},
                    {"key": "momentum", "value": 55},
                ],
            },
        }

        summary = technical_analysis._technical_analysis_summary(
            technical_reports=technical_reports,
            requested_horizon="auto",
        )

        self.assertEqual(summary["selected_horizon"], "swing")
        self.assertEqual(summary["selected_timeframe"], "weekly")
        self.assertEqual(summary["score_model"]["version"], "technical_factor_weight_v1")
        self.assertIn("swing", summary["score_model"]["horizon_factor_scores"])
        self.assertGreater(summary["selected_score"], 0)

    def test_technical_price_levels_builds_entry_and_risk_contract(self) -> None:
        levels = technical_analysis._technical_price_levels(
            technical_reports={
                "daily": {
                    "score": 4,
                    "title": "短線偏多",
                    "data": {
                        "daily_indicator": {
                            "close": 855,
                            "ma": {"ma5": 830, "ma20": 803, "ma60": 760},
                            "atr": {"atr14": 63},
                            "donchian": {"upper20": 919, "lower20": 716},
                            "rsi": {"rsi14": 70},
                        }
                    },
                },
                "weekly": {
                    "score": 3,
                    "data": {"daily_indicator": {"rsi": {"rsi14": 82}}},
                },
            },
            latest_daily={"trade_date": date(2026, 6, 12), "close_price": 855},
        )

        self.assertEqual(levels["kind"], "technical_price_levels")
        self.assertEqual(levels["as_of"], "2026-06-12")
        self.assertTrue(levels["context"]["extended"])
        self.assertIn("preferred_zone", levels["entry"])
        self.assertIn("do_not_chase_above", levels["entry"])
        self.assertIn("short_stop", levels["risk"])
        self.assertIn("technical_invalidation", levels["risk"])


if __name__ == "__main__":
    unittest.main()
