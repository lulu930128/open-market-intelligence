from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.jobs import scheduler
from app.jp_market.providers.jpx import parse_jpx_market_holidays
from app.jp_market.trading_calendar import is_jp_trading_day
from app.kr_market.providers import krx as krx_provider
from app.kr_market.providers.krx import parse_krx_market_holidays
from app.market.calendar_status import build_jp_calendar_status
from app.market import exchange_calendar_cache
from app.market.exchange_calendar_cache import (
    CalendarCacheUpdate,
    cached_market_holiday,
    invalidate_exchange_calendar_cache,
    market_calendar_cache_metadata,
    write_exchange_calendar_refresh,
)
from app.market.exchange_calendar_refresh import refresh_exchange_calendars
from app.market.providers.twse import parse_twse_holiday_schedule
from app.routers import market as market_router
from app.us_market.providers.nyse import parse_nyse_market_holidays


TEST_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "calendar-tests"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


class _TestProcessLock:
    def __init__(self, _path: Path) -> None:
        pass

    def acquire(self, **_kwargs) -> bool:
        return True

    def release(self) -> None:
        pass


@contextmanager
def _cache_path(name: str):
    path = TEST_TMP_ROOT / f"{name}.json"
    path.unlink(missing_ok=True)
    try:
        yield path
    finally:
        invalidate_exchange_calendar_cache()
        path.unlink(missing_ok=True)


class OfficialCalendarParserTests(unittest.TestCase):
    def test_twse_parser_excludes_trading_start_rows(self) -> None:
        payload = [
            {"Name": "中華民國開國紀念日", "Date": "1150101", "Description": "依規定放假1日。"},
            {"Name": "國曆新年開始交易日", "Date": "1150102", "Description": "國曆新年開始交易。"},
            {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212", "Description": ""},
            {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150213", "Description": ""},
            {"Name": "農曆除夕及春節", "Date": "1150216", "Description": "依規定放假。"},
            {"Name": "農曆除夕及春節", "Date": "1150217", "Description": "依規定放假。"},
            {"Name": "農曆除夕及春節", "Date": "1150218", "Description": "依規定放假。"},
            {"Name": "農曆除夕及春節", "Date": "1150219", "Description": "依規定放假。"},
            {"Name": "和平紀念日", "Date": "1150227", "Description": "補假。"},
        ]

        holidays = parse_twse_holiday_schedule(payload)

        self.assertIn(date(2026, 2, 12), holidays)
        self.assertNotIn(date(2026, 1, 2), holidays)

    def test_jpx_parser_reads_year_from_each_official_table(self) -> None:
        rows = "".join(
            f"<tr><td>{month}. {day} (Mon.)</td><td>Holiday {day}</td></tr>"
            for month, day in (
                ("Jan", 1),
                ("Jan", 2),
                ("Feb", 11),
                ("Mar", 20),
                ("Apr", 29),
                ("May", 3),
                ("Jul", 20),
                ("Dec", 31),
            )
        )
        html = f"<h2>2026</h2><table class='overtable'><tbody>{rows}</tbody></table>"
        html = html.replace("May. 3", "May 3")

        holidays = parse_jpx_market_holidays(html)

        self.assertEqual(holidays[date(2026, 7, 20)], "Holiday 20")
        self.assertEqual(holidays[date(2026, 5, 3)], "Holiday 3")

    def test_nyse_parser_reads_multi_year_header(self) -> None:
        rows = "".join(
            f"<tr><td>{name}</td><td>Monday, {month} {day}</td></tr>"
            for name, month, day in (
                ("New Year's Day", "January", 1),
                ("MLK Day", "January", 19),
                ("Washington's Birthday", "February", 16),
                ("Good Friday", "April", 3),
                ("Memorial Day", "May", 25),
                ("Juneteenth", "June", 19),
                ("Independence Day", "July", 3),
                ("Christmas Day", "December", 25),
            )
        )
        html = f"<table><tr><th>Holiday</th><th>2026</th></tr>{rows}</table>"

        holidays = parse_nyse_market_holidays(html)

        self.assertEqual(holidays[date(2026, 4, 3)], "Good Friday")

    def test_krx_parser_keeps_lunar_and_ad_hoc_closures(self) -> None:
        dates = (
            ("2026-01-01", "신정"),
            ("2026-02-16", "설날"),
            ("2026-02-17", "설날"),
            ("2026-02-18", "설날"),
            ("2026-03-02", "삼일절(대체휴일)"),
            ("2026-05-01", "근로자의날"),
            ("2026-06-03", "임시공휴일"),
            ("2026-12-31", "연말휴장일"),
        )
        payload = {
            "block1": [
                {"calnd_dd": day, "holdy_nm": name}
                for day, name in dates
            ]
        }

        holidays = parse_krx_market_holidays(payload, year=2026)

        self.assertEqual(holidays[date(2026, 6, 3)], "임시공휴일")
        self.assertEqual(holidays[date(2026, 12, 31)], "연말휴장일")

    def test_krx_fetch_uses_session_request_for_method_aware_transport(self) -> None:
        session = SimpleNamespace(request=Mock())
        page_response = SimpleNamespace(
            text='<select name="search_bas_yy"><option value="2026">2026</option></select>',
            url=krx_provider.KRX_MARKET_HOLIDAY_PAGE_URL,
        )
        otp_response = SimpleNamespace(text="x" * 32)
        rows = [
            {"calnd_dd": f"2026-01-{day:02d}", "holdy_nm": f"Holiday {day}"}
            for day in range(1, 9)
        ]
        data_response = SimpleNamespace(
            json=Mock(return_value={"block1": rows}),
            url=krx_provider.KRX_MARKET_HOLIDAY_DATA_URL,
        )

        with (
            patch.object(krx_provider.requests, "Session", return_value=session),
            patch.object(
                krx_provider,
                "provider_get",
                side_effect=[page_response, otp_response],
            ) as provider_get,
            patch.object(
                krx_provider,
                "provider_post",
                return_value=data_response,
            ) as provider_post,
        ):
            holidays, _url = krx_provider.fetch_krx_market_holidays(
                year=2026,
                timeout_seconds=20,
            )

        self.assertEqual(len(holidays), 8)
        self.assertIs(provider_get.call_args_list[0].kwargs["request_callable"], session.request)
        self.assertIs(provider_get.call_args_list[1].kwargs["request_callable"], session.request)
        self.assertIs(provider_post.call_args.kwargs["request_callable"], session.request)


class ExchangeCalendarCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        invalidate_exchange_calendar_cache()

    def test_cache_is_authoritative_for_a_verified_year(self) -> None:
        with _cache_path("authoritative") as cache_path:
            refreshed_at = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
            with patch.object(
                exchange_calendar_cache,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                write_exchange_calendar_refresh(
                    updates={
                        "jp": CalendarCacheUpdate(
                            provider="jpx_calendar",
                            source="JPX Market Holidays",
                            source_url="https://www.jpx.co.jp/calendar",
                            fetched_at=refreshed_at,
                            holidays={
                                date(2026, 7, 20): "Marine Day",
                                date(2026, 7, 21): "Emergency Market Holiday",
                            },
                            verified_years=frozenset({2026}),
                        )
                    },
                    errors={},
                    attempted_at=refreshed_at,
                    path=cache_path,
                )

            holiday = cached_market_holiday("jp", date(2026, 7, 21), path=cache_path)
            metadata = market_calendar_cache_metadata(
                "jp",
                year=2026,
                now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                path=cache_path,
            )

            self.assertTrue(holiday.covered)
            self.assertEqual(holiday.name, "Emergency Market Holiday")
            self.assertEqual(metadata["calendar_cache_status"], "current")

    def test_calendar_status_uses_cached_official_holiday(self) -> None:
        with _cache_path("calendar-status") as cache_path:
            refreshed_at = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
            with patch.object(
                exchange_calendar_cache,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                write_exchange_calendar_refresh(
                    updates={
                        "jp": CalendarCacheUpdate(
                            provider="jpx_calendar",
                            source="JPX Market Holidays",
                            source_url="https://www.jpx.co.jp/calendar",
                            fetched_at=refreshed_at,
                            holidays={date(2026, 7, 21): "Emergency Market Holiday"},
                            verified_years=frozenset({2026}),
                        )
                    },
                    errors={},
                    attempted_at=refreshed_at,
                    path=cache_path,
                )

            with patch.object(
                exchange_calendar_cache.settings,
                "market_calendar_cache_path",
                cache_path,
            ):
                invalidate_exchange_calendar_cache()
                status = build_jp_calendar_status(
                    now=datetime(2026, 7, 21, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
                )
                self.assertFalse(is_jp_trading_day(date(2026, 7, 21)))

            self.assertFalse(status["is_trading_day"])
            self.assertEqual(status["reason"], "holiday")
            self.assertEqual(status["calendar_cache_status"], "current")
            self.assertEqual(status["holiday_name"], "Emergency Market Holiday")


class ExchangeCalendarRefreshServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        invalidate_exchange_calendar_cache()

    def test_refresh_is_bounded_and_preserves_partial_success(self) -> None:
        calls: list[str] = []

        def fetcher(market: str, **_kwargs):
            calls.append(market)
            if market == "kr":
                raise RuntimeError("KRX unavailable")
            return (
                {date(2026, 1, day): f"Holiday {day}" for day in range(1, 9)},
                f"https://example.test/{market}",
            )

        with _cache_path("partial-refresh") as cache_path:
            with patch.object(
                exchange_calendar_cache,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                result = refresh_exchange_calendars(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_calendar=fetcher,
                )

        self.assertEqual(calls, ["tw", "us", "jp", "kr"])
        self.assertEqual(result["request_limit"], 6)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["results"]["kr"]["status"], "error")

    def test_manual_refresh_route_keeps_market_scope(self) -> None:
        db = SimpleNamespace()
        expected = {
            "kind": "market_calendar_refresh",
            "requested_markets": ["jp"],
        }
        with patch.object(
            market_router,
            "refresh_exchange_calendars",
            return_value=expected,
        ) as refresh:
            result = market_router.refresh_market_calendar("jp", db)

        self.assertIs(result, expected)
        refresh.assert_called_once_with(markets=["jp"], db=db)

    def test_scheduler_registers_immediate_daily_calendar_refresh(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(scheduler.settings, "enable_market_calendar_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_market_calendar_refresh_time",
                "07:15",
            ),
        ):
            added = scheduler._add_market_calendar_refresh_job(fake_scheduler)

        self.assertTrue(added)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.refresh_market_calendars,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["hour"], 7)
        self.assertEqual(kwargs["minute"], 15)
        self.assertEqual(kwargs["id"], "market_calendar_refresh")
        self.assertIsNotNone(kwargs["next_run_time"])


if __name__ == "__main__":
    unittest.main()
