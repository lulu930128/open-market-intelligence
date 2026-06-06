import unittest

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


if __name__ == "__main__":
    unittest.main()
