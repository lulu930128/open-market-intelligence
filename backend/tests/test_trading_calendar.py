from __future__ import annotations

from datetime import date, datetime, time
import unittest
from zoneinfo import ZoneInfo

from app.market.trading_calendar import is_taiwan_trading_day, latest_released_trading_day


class TaiwanTradingCalendarTests(unittest.TestCase):
    def test_2026_holidays_are_not_trading_days(self) -> None:
        self.assertFalse(is_taiwan_trading_day(date(2026, 2, 16)))
        self.assertFalse(is_taiwan_trading_day(date(2026, 2, 27)))
        self.assertFalse(is_taiwan_trading_day(date(2026, 6, 19)))

    def test_release_day_skips_holiday_and_waits_for_release_time(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")

        self.assertEqual(
            latest_released_trading_day(
                release_time=time(15, 15),
                now=datetime(2026, 2, 16, 16, 0, tzinfo=timezone),
            ),
            date(2026, 2, 11),
        )
        self.assertEqual(
            latest_released_trading_day(
                release_time=time(15, 15),
                now=datetime(2026, 2, 23, 15, 0, tzinfo=timezone),
            ),
            date(2026, 2, 11),
        )
        self.assertEqual(
            latest_released_trading_day(
                release_time=time(15, 15),
                now=datetime(2026, 2, 23, 16, 0, tzinfo=timezone),
            ),
            date(2026, 2, 23),
        )


if __name__ == "__main__":
    unittest.main()
