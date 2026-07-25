from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
import unittest

from app.market import taiwan_rules
from app.market.trading_calendar import TAIWAN_TZ


class TaiwanRulesTests(unittest.TestCase):
    def test_refresh_profiles_are_normalized_and_ordered(self) -> None:
        self.assertEqual(taiwan_rules.normalize_refresh_profile(None), "full")
        self.assertEqual(taiwan_rules.normalize_refresh_profile(" BASIC "), "basic")
        self.assertEqual(
            taiwan_rules.refresh_profile_steps("chips"),
            (
                taiwan_rules.TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
                taiwan_rules.TAIWAN_REFRESH_MARGIN_TRADING,
                taiwan_rules.TAIWAN_REFRESH_BROKER_BRANCH,
                taiwan_rules.TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
            ),
        )
        self.assertEqual(taiwan_rules.refresh_profile_step_count("fundamental"), 2)

        with self.assertRaises(ValueError):
            taiwan_rules.normalize_refresh_profile("unknown")

    def test_expected_dates_follow_dataset_release_times(self) -> None:
        now = datetime(2026, 6, 5, 16, 0, tzinfo=TAIWAN_TZ)

        self.assertEqual(
            taiwan_rules.expected_date_for_dataset(
                taiwan_rules.TAIWAN_DATASET_DAILY_PRICE,
                now=now,
            ),
            date(2026, 6, 5),
        )
        self.assertEqual(
            taiwan_rules.expected_date_for_dataset(
                taiwan_rules.TAIWAN_DATASET_INSTITUTIONAL_TRADE,
                now=now,
            ),
            date(2026, 6, 5),
        )
        self.assertEqual(
            taiwan_rules.expected_date_for_dataset(
                taiwan_rules.TAIWAN_DATASET_MARGIN_TRADING,
                now=now,
            ),
            date(2026, 6, 4),
        )
        self.assertEqual(
            taiwan_rules.expected_date_for_dataset("monthly_revenue", now=now),
            date(2026, 4, 1),
        )

        insurance_extension_window = datetime(2026, 6, 11, 0, 1, tzinfo=TAIWAN_TZ)
        self.assertEqual(
            taiwan_rules.expected_date_for_dataset(
                "monthly_revenue",
                now=insurance_extension_window,
            ),
            date(2026, 4, 1),
        )

        after_conservative_deadline = datetime(2026, 6, 16, 0, 1, tzinfo=TAIWAN_TZ)
        self.assertEqual(
            taiwan_rules.expected_date_for_dataset(
                "monthly_revenue",
                now=after_conservative_deadline,
            ),
            date(2026, 5, 1),
        )

    def test_shareholding_expected_date_advances_only_after_release_window(self) -> None:
        before_release = datetime(2026, 7, 25, 11, 59, tzinfo=TAIWAN_TZ)
        after_release = datetime(2026, 7, 25, 12, 1, tzinfo=TAIWAN_TZ)

        before = taiwan_rules.shareholding_distribution_release_window(
            now=before_release
        )
        after = taiwan_rules.shareholding_distribution_release_window(
            now=after_release
        )

        self.assertEqual(before["status"], "pending")
        self.assertFalse(before["is_released"])
        self.assertEqual(before["expected_trade_date"], date(2026, 7, 17))
        self.assertEqual(after["status"], "released")
        self.assertTrue(after["is_released"])
        self.assertEqual(after["expected_trade_date"], date(2026, 7, 24))

    def test_equity_only_datasets_skip_etfs_and_warrants(self) -> None:
        spec = taiwan_rules.TAIWAN_DATASET_BY_KEY[taiwan_rules.TAIWAN_DATASET_MONTHLY_REVENUE]

        self.assertTrue(taiwan_rules.is_equity_only_dataset_required(spec, None))
        self.assertTrue(
            taiwan_rules.is_equity_only_dataset_required(
                spec,
                SimpleNamespace(instrument_type="stock"),
            )
        )
        self.assertFalse(
            taiwan_rules.is_equity_only_dataset_required(
                spec,
                SimpleNamespace(instrument_type="etf"),
            )
        )
        self.assertFalse(
            taiwan_rules.is_equity_only_dataset_required(
                spec,
                SimpleNamespace(instrument_type="warrant"),
            )
        )


if __name__ == "__main__":
    unittest.main()
