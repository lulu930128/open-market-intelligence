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
        now = datetime(2026, 6, 5, 20, 30, tzinfo=TAIWAN_TZ)

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

    def test_institutional_and_margin_windows_use_complete_file_times(self) -> None:
        before_institutional = datetime(2026, 6, 5, 19, 59, tzinfo=TAIWAN_TZ)
        after_institutional = datetime(2026, 6, 5, 20, 0, tzinfo=TAIWAN_TZ)
        before_margin = datetime(2026, 6, 5, 20, 59, tzinfo=TAIWAN_TZ)
        after_margin = datetime(2026, 6, 5, 21, 0, tzinfo=TAIWAN_TZ)

        self.assertEqual(
            taiwan_rules.expected_institutional_trade_date(now=before_institutional),
            date(2026, 6, 4),
        )
        self.assertEqual(
            taiwan_rules.expected_institutional_trade_date(now=after_institutional),
            date(2026, 6, 5),
        )
        self.assertEqual(
            taiwan_rules.expected_margin_trade_date(now=before_margin),
            date(2026, 6, 4),
        )
        self.assertEqual(
            taiwan_rules.expected_margin_trade_date(now=after_margin),
            date(2026, 6, 5),
        )

    def test_financial_expected_period_advances_after_full_deadline(self) -> None:
        cases = (
            (datetime(2026, 3, 31, 23, 59, tzinfo=TAIWAN_TZ), "2025Q3"),
            (datetime(2026, 4, 1, 0, 0, tzinfo=TAIWAN_TZ), "2025Q4"),
            (datetime(2026, 5, 15, 23, 59, tzinfo=TAIWAN_TZ), "2025Q4"),
            (datetime(2026, 5, 16, 0, 0, tzinfo=TAIWAN_TZ), "2026Q1"),
            (datetime(2026, 8, 15, 0, 0, tzinfo=TAIWAN_TZ), "2026Q2"),
            (datetime(2026, 11, 15, 0, 0, tzinfo=TAIWAN_TZ), "2026Q3"),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(
                    taiwan_rules.expected_financial_metrics_period(now=now),
                    expected,
                )

    def test_fundamental_release_windows_expose_expected_keys(self) -> None:
        now = datetime(2026, 7, 26, 12, 30, tzinfo=TAIWAN_TZ)
        revenue = taiwan_rules.monthly_revenue_release_window(now=now)
        financial = taiwan_rules.financial_metrics_release_window(now=now)

        self.assertEqual(revenue["expected_data_key"], "2026-06-01")
        self.assertEqual(revenue["next_release_at"], "2026-08-16T00:00:00+08:00")
        self.assertEqual(financial["expected_data_key"], "2026Q1")
        self.assertEqual(financial["next_release_at"], "2026-08-15T00:00:00+08:00")

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
