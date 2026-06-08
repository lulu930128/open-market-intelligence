from datetime import date, datetime
import unittest
from unittest.mock import patch

from app.watchlists import ranking_service


class WatchlistRankingLimitStatusTests(unittest.TestCase):
    def test_limit_status_from_change_pct(self):
        self.assertEqual(ranking_service._limit_status_from_change_pct(9.5), "limit_up")
        self.assertEqual(ranking_service._limit_status_from_change_pct(-9.5), "limit_down")
        self.assertIsNone(ranking_service._limit_status_from_change_pct(9.49))
        self.assertIsNone(ranking_service._limit_status_from_change_pct(None))

    def test_previous_close_prefers_price_change(self):
        self.assertEqual(
            ranking_service._previous_close_from_change(
                close=204.5,
                change=18.5,
                change_pct=9.9462,
            ),
            186.0,
        )

    def test_previous_close_can_fallback_to_change_pct(self):
        self.assertAlmostEqual(
            ranking_service._previous_close_from_change(
                close=204.5,
                change=None,
                change_pct=9.9462365591,
            ),
            186.0,
            places=4,
        )

    def test_ranking_freshness_marks_old_rows_stale(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[{"time": "2026-06-05"}],
                requested_stock_count=1,
            )

        self.assertFalse(freshness["is_current"])
        self.assertEqual(freshness["target_trade_date"], date(2026, 6, 8))
        self.assertEqual(freshness["trade_date"], date(2026, 6, 5))
        self.assertEqual(freshness["current_stock_count"], 0)
        self.assertEqual(freshness["stale_stock_count"], 1)

    def test_ranking_freshness_accepts_target_trade_date(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[
                    {"time": "2026-06-08"},
                    {"time": date(2026, 6, 8)},
                ],
                requested_stock_count=2,
            )

        self.assertTrue(freshness["is_current"])
        self.assertEqual(freshness["current_stock_count"], 2)
        self.assertEqual(freshness["stale_stock_count"], 0)

    def test_ranking_freshness_accepts_intraday_rows_after_previous_release(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[{"time": datetime(2026, 6, 8, 9, 1)}],
                requested_stock_count=1,
            )

        self.assertTrue(freshness["is_current"])
        self.assertEqual(freshness["trade_date"], date(2026, 6, 8))
        self.assertEqual(freshness["current_stock_count"], 1)


if __name__ == "__main__":
    unittest.main()
