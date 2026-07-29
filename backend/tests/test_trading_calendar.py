from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.kr_market import trading_calendar as kr_trading_calendar
from app.market.calendar_status import (
    build_jp_calendar_status,
    build_kr_calendar_status,
    build_market_calendar_status,
    build_taiwan_calendar_status,
    build_us_calendar_status,
)
from app.jp_market.trading_calendar import (
    expected_jp_daily_price_date,
    is_jp_trading_day,
    jp_market_holiday_name,
    next_jp_trading_day,
    previous_jp_trading_day,
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

    def test_taiwan_status_exposes_closing_auction_separately(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")

        regular = build_taiwan_calendar_status(
            now=datetime(2026, 6, 15, 13, 24, 59, tzinfo=timezone),
        )
        auction = build_taiwan_calendar_status(
            now=datetime(2026, 6, 15, 13, 25, 0, tzinfo=timezone),
        )
        closed = build_taiwan_calendar_status(
            now=datetime(2026, 6, 15, 13, 30, 0, tzinfo=timezone),
        )

        self.assertEqual(regular["phase"], "regular")
        self.assertEqual(auction["phase"], "closing_auction")
        self.assertTrue(auction["session"]["is_polling_window"])
        self.assertEqual(closed["phase"], "post_close")

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

    def test_us_status_distinguishes_pre_market_regular_and_after_hours(self) -> None:
        timezone = ZoneInfo("America/New_York")

        pre_market = build_us_calendar_status(
            now=datetime(2026, 6, 18, 8, 0, tzinfo=timezone),
        )
        regular = build_us_calendar_status(
            now=datetime(2026, 6, 18, 10, 0, tzinfo=timezone),
        )
        after_hours = build_us_calendar_status(
            now=datetime(2026, 6, 18, 17, 0, tzinfo=timezone),
        )

        self.assertEqual(pre_market["phase"], "pre_market")
        self.assertFalse(pre_market["session"]["is_polling_window"])
        self.assertTrue(pre_market["session"]["is_extended_polling_window"])
        self.assertEqual(pre_market["session"]["pre_market_open_time"], "04:00")
        self.assertEqual(pre_market["session"]["after_hours_close_time"], "20:00")

        self.assertEqual(regular["phase"], "regular")
        self.assertTrue(regular["session"]["is_polling_window"])
        self.assertFalse(regular["session"]["is_extended_polling_window"])

        self.assertEqual(after_hours["phase"], "after_hours")
        self.assertFalse(after_hours["session"]["is_polling_window"])
        self.assertTrue(after_hours["session"]["is_extended_polling_window"])
        self.assertTrue(after_hours["session"]["is_after_close"])

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

    def test_kr_verified_2026_fallback_skips_official_closures(self) -> None:
        no_cache = SimpleNamespace(covered=False, name=None)
        with patch.object(
            kr_trading_calendar,
            "cached_market_holiday",
            return_value=no_cache,
        ):
            self.assertFalse(is_kr_trading_day(date(2026, 7, 17)))
            self.assertEqual(
                previous_kr_trading_day(
                    date(2026, 7, 18),
                    include_value=True,
                ),
                date(2026, 7, 16),
            )

    def test_jp_calendar_models_jpx_holidays_and_observed_days(self) -> None:
        self.assertFalse(is_jp_trading_day(date(2026, 5, 6)))
        self.assertFalse(is_jp_trading_day(date(2026, 7, 20)))
        self.assertFalse(is_jp_trading_day(date(2026, 9, 22)))
        self.assertFalse(is_jp_trading_day(date(2026, 12, 31)))
        self.assertEqual(jp_market_holiday_name(date(2026, 9, 22)), "Citizen's Holiday")
        self.assertEqual(
            previous_jp_trading_day(date(2026, 9, 24), include_value=False),
            date(2026, 9, 18),
        )
        self.assertEqual(next_jp_trading_day(date(2026, 9, 18)), date(2026, 9, 24))

    def test_jp_status_models_lunch_break_and_daily_release(self) -> None:
        timezone = ZoneInfo("Asia/Tokyo")
        lunch = build_jp_calendar_status(
            now=datetime(2026, 7, 15, 12, 0, tzinfo=timezone),
        )
        before_release = build_jp_calendar_status(
            now=datetime(2026, 7, 15, 15, 45, tzinfo=timezone),
        )
        after_release = build_jp_calendar_status(
            now=datetime(2026, 7, 15, 16, 20, tzinfo=timezone),
        )

        self.assertEqual(lunch["market"], "jp")
        self.assertEqual(lunch["phase"], "lunch_break")
        self.assertFalse(lunch["session"]["is_polling_window"])
        self.assertEqual(lunch["session"]["lunch_start_time"], "11:30")
        self.assertEqual(lunch["session"]["lunch_end_time"], "12:30")
        self.assertEqual(
            lunch["session"]["next_session_start_at"],
            "2026-07-15T12:30:00+09:00",
        )
        self.assertEqual(
            before_release["release_windows"]["jp_daily_price"]["expected_trade_date"],
            "2026-07-14",
        )
        self.assertEqual(
            expected_jp_daily_price_date(
                now=datetime(2026, 7, 15, 16, 20, tzinfo=timezone),
            ),
            date(2026, 7, 15),
        )
        self.assertEqual(
            after_release["release_windows"]["jp_daily_price"]["expected_trade_date"],
            "2026-07-15",
        )
        self.assertIsNone(after_release["calendar_limit"])

    def test_market_calendar_status_can_filter_market(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        status = build_market_calendar_status(
            market="tw",
            now=datetime(2026, 6, 14, 14, 0, tzinfo=timezone),
        )

        self.assertEqual(status["kind"], "market_calendar_status")
        self.assertEqual(set(status["markets"]), {"tw"})

        jp_status = build_market_calendar_status(
            market="jp",
            now=datetime(2026, 7, 15, 16, 20, tzinfo=ZoneInfo("Asia/Tokyo")),
        )
        self.assertEqual(set(jp_status["markets"]), {"jp"})
        self.assertEqual(
            jp_status["markets"]["jp"]["release_windows"]["jp_daily_price"][
                "expected_trade_date"
            ],
            "2026-07-15",
        )


if __name__ == "__main__":
    unittest.main()
