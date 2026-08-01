from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from app.market.monthly_revenue_continuity import (
    analyze_monthly_revenue_continuity,
)


class MonthlyRevenueContinuityTests(unittest.TestCase):
    def test_yageo_internal_gap_is_not_hidden_by_latest_period(self) -> None:
        rows = [
            SimpleNamespace(period=date(2026, month, 1))
            for month in (1, 2, 3, 4, 6)
        ]

        result = analyze_monthly_revenue_continuity(rows)

        self.assertEqual(result["status"], "interior_gap")
        self.assertEqual(result["missing_periods"], ["2026-05"])
        self.assertFalse(result["decision_usable"])
        self.assertIn("monthly_revenue_missing_2026_05", result["issues"])

    def test_complete_unique_series_is_decision_usable(self) -> None:
        rows = [
            {"period": f"2026-{month:02d}-01"}
            for month in range(1, 7)
        ]

        result = analyze_monthly_revenue_continuity(rows)

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["decision_usable"])
        self.assertEqual(result["issues"], [])

    def test_duplicate_period_stays_visible(self) -> None:
        rows = [
            {"period": "2026-01-01"},
            {"period": "2026-02-01"},
            {"period": "2026-02-01"},
        ]

        result = analyze_monthly_revenue_continuity(rows)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["duplicate_periods"], ["2026-02-01"])
        self.assertFalse(result["decision_usable"])
        self.assertIn("monthly_revenue_duplicate_period", result["issues"])

    def test_expected_window_distinguishes_leading_and_trailing_gaps(self) -> None:
        rows = [
            {"period": "2026-02-01"},
            {"period": "2026-03-01"},
        ]

        result = analyze_monthly_revenue_continuity(
            rows,
            expected_from=date(2026, 1, 1),
            expected_to=date(2026, 4, 1),
        )

        self.assertEqual(result["status"], "leading_and_trailing_gap")
        self.assertEqual(result["missing_periods"], ["2026-01", "2026-04"])
        self.assertFalse(result["decision_usable"])


if __name__ == "__main__":
    unittest.main()
