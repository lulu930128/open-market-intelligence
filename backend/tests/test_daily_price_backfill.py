from __future__ import annotations

from datetime import date
import unittest

from app.market.backfill import _should_skip_existing_month


class DailyPriceBackfillSkipTests(unittest.TestCase):
    def test_current_month_with_only_latest_day_is_not_complete(self) -> None:
        self.assertFalse(
            _should_skip_existing_month(
                existing_count=1,
                latest_existing_date=date(2026, 5, 26),
                effective_start=date(2026, 5, 1),
                effective_end=date(2026, 5, 26),
                month_end=date(2026, 5, 31),
                today=date(2026, 5, 26),
            )
        )

    def test_current_month_with_expected_trading_days_is_complete(self) -> None:
        self.assertTrue(
            _should_skip_existing_month(
                existing_count=17,
                latest_existing_date=date(2026, 5, 26),
                effective_start=date(2026, 5, 1),
                effective_end=date(2026, 5, 26),
                month_end=date(2026, 5, 31),
                today=date(2026, 5, 26),
            )
        )

    def test_closed_month_with_sparse_last_day_is_not_complete(self) -> None:
        self.assertFalse(
            _should_skip_existing_month(
                existing_count=1,
                latest_existing_date=date(2026, 4, 30),
                effective_start=date(2026, 4, 1),
                effective_end=date(2026, 4, 30),
                month_end=date(2026, 4, 30),
                today=date(2026, 5, 26),
            )
        )


if __name__ == "__main__":
    unittest.main()
