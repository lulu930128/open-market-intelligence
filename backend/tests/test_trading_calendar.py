from __future__ import annotations

from datetime import date, datetime, time
import unittest
from zoneinfo import ZoneInfo

from app.market.calendar_status import (
    build_kr_calendar_status,
    build_market_calendar_status,
    build_taiwan_calendar_status,
    build_us_calendar_status,
)
from app.market.trading_calendar import is_taiwan_trading_day, latest_released_trading_day
from app.us_market.trading_calendar import (
    is_us_trading_day,
    next_us_trading_day,
    previous_us_trading_day,
    us_market_holiday_name,
)
from app.kr_market.trading_calendar import (
    is_kr_trading_day,
    next_kr_trading_day,
    previous_kr_trading_day,
)


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


class MarketCalendarStatusTests(unittest.TestCase):
    def test_taiwan_status_reports_weekend_and_next_trading_day(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        status = build_taiwan_calendar_status(
            now=datetime(2026, 6, 14, 14, 0, tzinfo=timezone),
        )

        self.assertEqual(status["market"], "tw")
        self.assertFalse(status["is_trading_day"])
        self.assertEqual(status["phase"], "market_closed")
        self.assertEqual(status["reason"], "weekend")
        self.assertEqual(status["previous_trading_day"], "2026-06-12")
        self.assertEqual(status["next_trading_day"], "2026-06-15")
        self.assertEqual(
            status["release_windows"]["market_daily_price"]["expected_trade_date"],
            "2026-06-12",
        )
        self.assertEqual(
            status["session"]["next_session_start_at"],
            "2026-06-15T08:30:00+08:00",
        )

    def test_taiwan_status_waits_for_daily_release_time(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        before_release = build_taiwan_calendar_status(
            now=datetime(2026, 6, 15, 15, 0, tzinfo=timezone),
        )
        after_release = build_taiwan_calendar_status(
            now=datetime(2026, 6, 15, 15, 20, tzinfo=timezone),
        )

        self.assertTrue(before_release["is_trading_day"])
        self.assertEqual(before_release["phase"], "post_close")
        self.assertEqual(
            before_release["release_windows"]["market_daily_price"]["status"],
            "pending",
        )
        self.assertEqual(
            before_release["release_windows"]["market_daily_price"]["expected_trade_date"],
            "2026-06-12",
        )
        self.assertEqual(
            after_release["release_windows"]["market_daily_price"]["status"],
            "released",
        )
        self.assertEqual(
            after_release["release_windows"]["market_daily_price"]["expected_trade_date"],
            "2026-06-15",
        )

    def test_us_status_reports_holiday_and_next_trading_day(self) -> None:
        timezone = ZoneInfo("America/New_York")

        self.assertFalse(is_us_trading_day(date(2026, 6, 19)))
        self.assertEqual(
            us_market_holiday_name(date(2026, 6, 19)),
            "Juneteenth National Independence Day",
        )
        self.assertEqual(previous_us_trading_day(date(2026, 6, 19), include_value=True), date(2026, 6, 18))
        self.assertEqual(next_us_trading_day(date(2026, 6, 19)), date(2026, 6, 22))

        status = build_us_calendar_status(
            now=datetime(2026, 6, 19, 12, 0, tzinfo=timezone),
        )

        self.assertEqual(status["market"], "us")
        self.assertFalse(status["is_trading_day"])
        self.assertEqual(status["reason"], "holiday")
        self.assertEqual(status["holiday_name"], "Juneteenth National Independence Day")
        self.assertEqual(status["previous_trading_day"], "2026-06-18")
        self.assertEqual(status["next_trading_day"], "2026-06-22")
        self.assertEqual(
            status["release_windows"]["us_daily_price"]["expected_trade_date"],
            "2026-06-18",
        )

    def test_kr_status_reports_weekend_and_daily_release_window(self) -> None:
        timezone = ZoneInfo("Asia/Seoul")

        self.assertFalse(is_kr_trading_day(date(2026, 6, 14)))
        self.assertEqual(previous_kr_trading_day(date(2026, 6, 14), include_value=True), date(2026, 6, 12))
        self.assertEqual(next_kr_trading_day(date(2026, 6, 14)), date(2026, 6, 15))

        before_release = build_kr_calendar_status(
            now=datetime(2026, 6, 15, 16, 0, tzinfo=timezone),
        )
        after_release = build_kr_calendar_status(
            now=datetime(2026, 6, 15, 16, 20, tzinfo=timezone),
        )

        self.assertEqual(before_release["market"], "kr")
        self.assertTrue(before_release["is_trading_day"])
        self.assertEqual(before_release["session"]["close_time"], "15:30")
        self.assertEqual(
            before_release["release_windows"]["kr_daily_price"]["status"],
            "pending",
        )
        self.assertEqual(
            before_release["release_windows"]["kr_daily_price"]["expected_trade_date"],
            "2026-06-12",
        )
        self.assertEqual(
            after_release["release_windows"]["kr_daily_price"]["status"],
            "released",
        )
        self.assertEqual(
            after_release["release_windows"]["kr_daily_price"]["expected_trade_date"],
            "2026-06-15",
        )

    def test_market_calendar_status_can_filter_market(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        status = build_market_calendar_status(
            market="tw",
            now=datetime(2026, 6, 14, 14, 0, tzinfo=timezone),
        )

        self.assertEqual(status["kind"], "market_calendar_status")
        self.assertEqual(set(status["markets"]), {"tw"})


if __name__ == "__main__":
    unittest.main()
