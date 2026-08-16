from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from app.resource_market.fx_freshness import evaluate_fx_freshness, fx_daily_data_date


class FxFreshnessTests(unittest.TestCase):
    def test_daily_data_date_uses_yahoo_exchange_timezone_metadata(self) -> None:
        self.assertEqual(
            fx_daily_data_date(
                datetime(2026, 8, 6, 23, tzinfo=timezone.utc),
                '{"exchange_timezone_name":"Europe/London"}',
            ),
            date(2026, 8, 7),
        )

    def test_daily_trend_uses_latest_completed_session_instead_of_wall_clock_age(self) -> None:
        result = evaluate_fx_freshness(
            purpose="daily_trend",
            now=datetime(2026, 6, 8, 12, tzinfo=timezone.utc),
            event_time=datetime(2026, 6, 5, 8, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 5, 8, tzinfo=timezone.utc),
            data_date=date(2026, 6, 5),
        )

        self.assertEqual(result.status, "latest_completed_session")
        self.assertTrue(result.usable)
        self.assertEqual(result.expected_data_date, date(2026, 6, 5))
        self.assertFalse(result.refresh_eligible)
        self.assertGreater(result.event_age_seconds or 0, 72 * 60 * 60)

    def test_adr_alignment_accepts_exact_trade_date_after_long_holiday_gap(self) -> None:
        result = evaluate_fx_freshness(
            purpose="adr_alignment",
            now=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
            event_time=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
            data_date=date(2026, 8, 7),
            expected_data_date=date(2026, 8, 7),
        )

        self.assertEqual(result.status, "current")
        self.assertTrue(result.usable)
        self.assertFalse(result.refresh_eligible)
        self.assertGreater(result.event_age_seconds or 0, 72 * 60 * 60)

    def test_weekend_spot_quote_reports_closed_session_without_false_stale(self) -> None:
        result = evaluate_fx_freshness(
            purpose="spot_quote",
            now=datetime(2026, 8, 9, 20, tzinfo=timezone.utc),
            event_time=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(result.session_status, "closed")
        self.assertEqual(result.status, "latest_completed_session")
        self.assertTrue(result.usable)
        self.assertFalse(result.refresh_eligible)
        self.assertIsNotNone(result.next_expected_update_at)

    def test_maintenance_window_defers_refresh_until_session_reopens(self) -> None:
        result = evaluate_fx_freshness(
            purpose="spot_quote",
            now=datetime(2026, 8, 10, 21, 30, tzinfo=timezone.utc),
            event_time=datetime(2026, 8, 10, 20, 59, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 10, 21, tzinfo=timezone.utc),
        )

        self.assertEqual(result.session_status, "maintenance")
        self.assertEqual(result.status, "latest_completed_session")
        self.assertTrue(result.usable)
        self.assertFalse(result.refresh_eligible)
        self.assertEqual(
            result.next_expected_update_at,
            datetime(2026, 8, 10, 22, tzinfo=timezone.utc),
        )

    def test_friday_close_makes_friday_the_latest_completed_daily_session(self) -> None:
        result = evaluate_fx_freshness(
            purpose="daily_trend",
            now=datetime(2026, 8, 7, 22, tzinfo=timezone.utc),
            event_time=datetime(2026, 8, 7, 20, tzinfo=timezone.utc),
            data_date=date(2026, 8, 7),
        )

        self.assertEqual(result.session_status, "closed")
        self.assertEqual(result.expected_data_date, date(2026, 8, 7))
        self.assertEqual(result.status, "latest_completed_session")
        self.assertTrue(result.usable)

    def test_future_observation_is_not_decision_usable(self) -> None:
        result = evaluate_fx_freshness(
            purpose="adr_alignment",
            now=datetime(2026, 8, 9, 12, tzinfo=timezone.utc),
            event_time=datetime(2026, 8, 9, 11, tzinfo=timezone.utc),
            data_date=date(2026, 8, 9),
            expected_data_date=date(2026, 8, 7),
        )

        self.assertEqual(result.status, "future")
        self.assertFalse(result.usable)
        self.assertFalse(result.refresh_eligible)


if __name__ == "__main__":
    unittest.main()
