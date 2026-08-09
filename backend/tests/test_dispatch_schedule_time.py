from __future__ import annotations

from datetime import datetime, timezone
import unittest
from zoneinfo import ZoneInfo

from app.dispatch.schedule_time import (
    compute_next_run_at,
    ensure_utc,
    scheduled_slot_key,
)


class DispatchScheduleTimeTests(unittest.TestCase):
    def test_compute_next_taipei_weekday_run(self) -> None:
        result = compute_next_run_at(
            send_time="08:55",
            day_of_week="mon-fri",
            timezone_name="Asia/Taipei",
            calendar_mode="weekdays",
            after=datetime(2026, 8, 3, 8, 54, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        self.assertEqual(
            result,
            datetime(2026, 8, 3, 0, 55, tzinfo=timezone.utc),
        )

    def test_compute_next_run_moves_to_next_valid_day_after_time(self) -> None:
        result = compute_next_run_at(
            send_time="08:55",
            day_of_week="mon-fri",
            timezone_name="Asia/Taipei",
            calendar_mode="weekdays",
            after=datetime(2026, 8, 3, 8, 56, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        self.assertEqual(
            result,
            datetime(2026, 8, 4, 0, 55, tzinfo=timezone.utc),
        )

    def test_calendar_days_allows_weekend(self) -> None:
        result = compute_next_run_at(
            send_time="09:00",
            day_of_week="mon-fri",
            timezone_name="Asia/Taipei",
            calendar_mode="calendar_days",
            after=datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        self.assertEqual(result.astimezone(ZoneInfo("Asia/Taipei")).weekday(), 5)

    def test_dst_nonexistent_time_moves_to_first_valid_minute(self) -> None:
        result = compute_next_run_at(
            send_time="02:30",
            day_of_week="daily",
            timezone_name="America/New_York",
            calendar_mode="calendar_days",
            after=datetime(2026, 3, 8, 0, 0, tzinfo=ZoneInfo("America/New_York")),
        )

        local = result.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((local.hour, local.minute), (3, 0))

    def test_dst_ambiguous_time_uses_first_fold(self) -> None:
        result = compute_next_run_at(
            send_time="01:30",
            day_of_week="daily",
            timezone_name="America/New_York",
            calendar_mode="calendar_days",
            after=datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo("America/New_York")),
        )

        local = result.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((local.hour, local.minute, local.fold), (1, 30, 0))

    def test_naive_database_datetime_is_normalized_as_utc(self) -> None:
        value = ensure_utc(datetime(2026, 8, 4, 1, 2, 3))
        self.assertEqual(value.tzinfo, timezone.utc)
        self.assertEqual(scheduled_slot_key(value), "2026-08-04T01:02:03Z")


if __name__ == "__main__":
    unittest.main()
