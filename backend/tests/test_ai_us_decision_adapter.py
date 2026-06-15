from __future__ import annotations

import unittest

from app.ai.us_decision_adapter import build_us_stock_decision_adapter


def make_context(*, source_health_status: str = "current") -> dict:
    return {
        "summary": {
            "profile": {
                "company_name": "Example Corp",
                "sector": "Technology",
                "profit_margin": 0.22,
                "pe_ratio": 24.0,
            }
        },
        "data": {
            "daily_prices": [
                {"trade_date": "2026-06-12", "close_price": 110.0, "trade_volume": 1800},
                {"trade_date": "2026-06-11", "close_price": 100.0, "trade_volume": 1000},
                {"trade_date": "2026-06-10", "close_price": 98.0, "trade_volume": 1000},
                {"trade_date": "2026-06-09", "close_price": 99.0, "trade_volume": 1000},
                {"trade_date": "2026-06-08", "close_price": 97.0, "trade_volume": 1000},
            ],
            "sec_fundamentals": {"metric_count": 4},
            "short_volume": [
                {"trade_date": "2026-06-12", "short_ratio": 0.2},
            ],
            "source_health": {
                "summary": {
                    "entry_count": 3,
                    "ok_count": 3 if source_health_status == "current" else 1,
                    "empty_count": 0 if source_health_status == "current" else 1,
                    "stale_count": 0 if source_health_status == "current" else 1,
                    "error_count": 0,
                },
                "entries": [
                    {
                        "resource": "daily_price",
                        "provider": "yahoo_chart",
                        "status": source_health_status,
                    },
                    {
                        "resource": "profile",
                        "provider": "alphavantage",
                        "status": "available",
                    },
                    {
                        "resource": "sec_facts",
                        "provider": "sec_edgar",
                        "status": "available"
                        if source_health_status == "current"
                        else "empty",
                    },
                ],
            },
        },
        "missing": [],
        "warnings": [],
    }


class USDecisionAdapterTests(unittest.TestCase):
    def test_us_adapter_scores_price_volume_fundamentals_and_short_volume(self) -> None:
        decision = build_us_stock_decision_adapter(make_context(), "swing")

        component_keys = [component["key"] for component in decision["components"]]
        self.assertEqual(decision["kind"], "us_stock_decision_adapter_v1")
        self.assertEqual(decision["selected_horizon"], "swing")
        self.assertEqual(decision["stance"], "bullish")
        self.assertGreater(decision["selected_score"], 15)
        self.assertIn("price_trend", component_keys)
        self.assertIn("volume", component_keys)
        self.assertIn("fundamentals", component_keys)
        self.assertIn("short_volume", component_keys)
        self.assertIn("source_health", component_keys)

    def test_us_adapter_penalizes_stale_or_empty_source_health(self) -> None:
        healthy = build_us_stock_decision_adapter(make_context(), "long")
        weak_health = build_us_stock_decision_adapter(
            make_context(source_health_status="stale"),
            "long",
        )

        self.assertLess(weak_health["selected_score"], healthy["selected_score"])
        source_component = next(
            component
            for component in weak_health["components"]
            if component["key"] == "source_health"
        )
        self.assertLess(source_component["score"], 0)


if __name__ == "__main__":
    unittest.main()
