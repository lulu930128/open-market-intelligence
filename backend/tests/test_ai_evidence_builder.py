from __future__ import annotations

from datetime import date
import unittest

from app.ai import evidence_builder


class AiEvidenceBuilderTests(unittest.TestCase):
    def test_market_session_evidence_handles_closed_market(self) -> None:
        evidence = evidence_builder.market_session_evidence(
            latest_daily={"trade_date": date(2026, 6, 12)},
            technical_reports={
                "today": {
                    "phase": "market_closed",
                    "data": {
                        "market_session": {
                            "date": "2026-06-14",
                            "reason": "holiday",
                            "previous_trading_day": "2026-06-12",
                            "next_trading_day": "2026-06-15",
                        }
                    },
                }
            },
        )

        self.assertFalse(evidence["is_trading_day"])
        self.assertEqual(evidence["latest_daily_date"], "2026-06-12")
        self.assertIn("下一交易日 2026-06-15", evidence["summary"])

    def test_market_session_evidence_prefers_calendar_status(self) -> None:
        evidence = evidence_builder.market_session_evidence(
            latest_daily={"trade_date": date(2026, 6, 12)},
            technical_reports={
                "today": {
                    "phase": "regular",
                    "data": {"market_session": {"is_trading_day": True}},
                }
            },
            calendar_status={
                "market": "tw",
                "date": "2026-06-14",
                "is_trading_day": False,
                "phase": "market_closed",
                "reason": "weekend",
                "previous_trading_day": "2026-06-12",
                "next_trading_day": "2026-06-15",
                "release_windows": {
                    "market_daily_price": {
                        "status": "market_closed",
                        "expected_trade_date": "2026-06-12",
                    }
                },
            },
        )

        self.assertFalse(evidence["is_trading_day"])
        self.assertEqual(evidence["source"], "app.market.calendar_status")
        self.assertEqual(evidence["reason"], "weekend")
        self.assertIn("台股休市", evidence["summary"])

    def test_recent_volatility_classifies_large_moves(self) -> None:
        evidence = evidence_builder.recent_volatility_evidence(
            {
                "points": [
                    {"time": "2026-06-08", "close": 100, "high": 101, "low": 99},
                    {"time": "2026-06-09", "close": 106, "high": 108, "low": 100},
                    {"time": "2026-06-10", "close": 101, "high": 107, "low": 99},
                    {"time": "2026-06-11", "close": 112, "high": 113, "low": 100},
                    {"time": "2026-06-12", "close": 108, "high": 114, "low": 107},
                    {"time": "2026-06-15", "close": 119, "high": 120, "low": 108},
                ]
            }
        )

        self.assertEqual(evidence["label"], "high")
        self.assertGreaterEqual(evidence["large_move_days"], 2)
        self.assertIn("高波動", evidence["summary"])

    def test_build_stock_decision_evidence_combines_quality_and_factors(self) -> None:
        evidence = evidence_builder.build_stock_decision_evidence(
            latest_daily={
                "trade_date": date(2026, 6, 12),
                "close_price": 855,
                "trade_volume": 26000,
            },
            chart={
                "points": [
                    {"time": "2026-06-09", "close": 810, "high": 820, "low": 800},
                    {"time": "2026-06-10", "close": 830, "high": 835, "low": 805},
                    {"time": "2026-06-11", "close": 845, "high": 850, "low": 830},
                    {"time": "2026-06-12", "close": 855, "high": 865, "low": 840},
                ]
            },
            latest_revenue={
                "period": date(2026, 5, 1),
                "year_over_year_pct": 15.2,
                "month_over_month_pct": 3.1,
            },
            latest_financial={
                "period": "2026Q1",
                "eps": 8.25,
                "roe": 18.4,
            },
            technical_reports={
                "daily": {
                    "data": {
                        "daily_indicator": {
                            "close": 855,
                            "ma": {"ma20": 803},
                            "volume": 26000,
                            "volume_ma": {"volume_ma20": 10000},
                            "macd": {"macd": 4.0, "signal": 1.5, "histogram": 2.5},
                        }
                    }
                }
            },
            missing=["broker_branch_trade_daily"],
            source_refs=[
                {"type": "table", "name": "market_daily_price"},
                {"type": "derived", "name": "app.market.technical_report"},
            ],
        )

        self.assertEqual(evidence["kind"], "stock_decision_evidence_v1")
        self.assertEqual(evidence["data_quality"]["price"]["value"], 855.0)
        self.assertEqual(evidence["data_quality"]["volume"]["display_value"], "26 張")
        self.assertIn("market_daily_price", evidence["data_quality"]["source_names"])
        self.assertEqual(evidence["indicator_quality"]["macd"]["tone"], "positive")
        self.assertIn("收盤站上 MA20。", evidence["confidence_factors"]["positive"])
        self.assertIn("量能約為 20 日均量 2.6 倍。", evidence["confidence_factors"]["positive"])
        self.assertIn("broker_branch_trade_daily 尚缺或不完整。", evidence["confidence_factors"]["data_limits"])
        self.assertIn("2026-05-01 營收", evidence["fundamentals"]["monthly_revenue"]["summary"])


if __name__ == "__main__":
    unittest.main()
