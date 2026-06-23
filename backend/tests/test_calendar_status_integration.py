from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.jobs import scheduler
from app.market.taiwan_rules import (
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
)


class CalendarStatusIntegrationTests(unittest.TestCase):
    def test_scheduler_daily_refresh_uses_release_windows_for_include_today(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-06-15",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_INSTITUTIONAL_TRADE: {"is_released": True},
                TAIWAN_DATASET_MARGIN_TRADING: {"is_released": False},
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=17), True),
            ) as enqueue,
        ):
            scheduler.enqueue_market_daily_refresh()

        request = enqueue.call_args.kwargs["request"]
        task_args = enqueue.call_args.kwargs["task_args"]
        self.assertFalse(request["include_today"])
        self.assertFalse(task_args[4])
        self.assertEqual(request["calendar_phase"], "post_close")
        fake_db.close.assert_called_once()

    def test_scheduler_market_chip_refresh_uses_calendar_expected_trade_date(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-06-15",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                "market_chip_daily": {
                    "expected_trade_date": "2026-06-12",
                    "is_released": False,
                }
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler, "normalize_market_chip_index_ids", return_value=["TAIEX"]),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=18), True),
            ) as enqueue,
        ):
            scheduler.enqueue_market_chip_daily_refresh()

        request = enqueue.call_args.kwargs["request"]
        task_args = enqueue.call_args.kwargs["task_args"]
        self.assertEqual(request["trade_date"], date(2026, 6, 12))
        self.assertFalse(request["include_today"])
        self.assertEqual(task_args[1], date(2026, 6, 12))
        self.assertFalse(task_args[2])

    def test_scheduler_skips_us_refresh_when_calendar_is_closed(self) -> None:
        calendar_status = {
            "market": "us",
            "date": "2026-06-19",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "release_windows": {},
        }

        with (
            patch.object(scheduler, "build_us_calendar_status", return_value=calendar_status),
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            scheduler.enqueue_us_market_daily_refresh()

        enqueue.assert_not_called()

    def test_scheduler_jp_watchlist_resource_refresh_queues_job(self) -> None:
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch.object(scheduler.settings, "scheduler_jp_market_refresh_outputsize", "compact"),
            patch.object(scheduler.settings, "scheduler_jp_market_refresh_provider", "auto"),
            patch.object(
                scheduler.settings,
                "scheduler_jp_market_refresh_include_fundamentals",
                True,
            ),
            patch.object(
                scheduler,
                "resolve_market_refresh_interval_seconds",
                return_value=1.5,
            ) as resolve_sleep,
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=19), True),
            ) as enqueue,
        ):
            scheduler.enqueue_jp_market_watchlist_resource_refresh()

        kwargs = enqueue.call_args.kwargs
        request = kwargs["request"]
        task_args = kwargs["task_args"]
        self.assertEqual(kwargs["job_type"], "jp_market.scheduler.watchlist_resource_refresh")
        self.assertEqual(kwargs["target"], "all")
        self.assertEqual(request["schedule"], "jp_market_watchlist_resource_refresh")
        self.assertIsNone(request["group_id"])
        self.assertTrue(request["include_children"])
        self.assertTrue(request["enabled_only"])
        self.assertTrue(request["include_daily"])
        self.assertTrue(request["include_fundamentals"])
        self.assertEqual(request["outputsize"], "compact")
        self.assertEqual(request["provider"], "auto")
        self.assertEqual(task_args, (None, True, True, True, True, "compact", "auto", 1.5))
        resolve_sleep.assert_called_once_with(market="jp")
        fake_db.close.assert_called_once()

    def test_taiwan_futures_live_window_matches_regular_and_after_hours_sessions(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")

        self.assertTrue(
            scheduler._is_taiwan_futures_live_window(
                datetime(2026, 6, 15, 9, 0, tzinfo=timezone)
            )
        )
        self.assertTrue(
            scheduler._is_taiwan_futures_live_window(
                datetime(2026, 6, 13, 4, 0, tzinfo=timezone)
            )
        )
        self.assertFalse(
            scheduler._is_taiwan_futures_live_window(
                datetime(2026, 6, 14, 9, 0, tzinfo=timezone)
            )
        )
        self.assertFalse(
            scheduler._is_taiwan_futures_live_window(
                datetime(2026, 6, 15, 2, 0, tzinfo=timezone)
            )
        )

    def test_taiwan_futures_collector_skips_outside_live_window(self) -> None:
        with (
            patch.object(scheduler, "_is_taiwan_futures_live_window", return_value=False),
            patch.object(scheduler, "SessionLocal") as session_local,
            patch.object(scheduler, "refresh_taiwan_futures_quotes") as refresh,
        ):
            scheduler.collect_taiwan_futures_quotes()

        session_local.assert_not_called()
        refresh.assert_not_called()

    def test_taiwan_futures_collector_refreshes_quotes_and_records_sampled_success(self) -> None:
        fake_db = SimpleNamespace(close=Mock(), rollback=Mock())

        with (
            patch.object(scheduler, "_is_taiwan_futures_live_window", return_value=True),
            patch.object(scheduler.settings, "scheduler_taiwan_futures_symbols", "TXF,MXF"),
            patch.object(scheduler.settings, "scheduler_taiwan_futures_session", "auto"),
            patch.object(scheduler.settings, "taiwan_futures_quote_provider", "taifex_mis"),
            patch.object(scheduler, "_should_record_taiwan_futures_success", return_value=True),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "refresh_taiwan_futures_quotes",
                return_value=[SimpleNamespace(symbol="TXF"), SimpleNamespace(symbol="MXF")],
            ) as refresh,
            patch.object(scheduler, "record_provider_event") as record_event,
        ):
            scheduler.collect_taiwan_futures_quotes()

        refresh.assert_called_once_with(
            db=fake_db,
            symbols=["TXF", "MXF"],
            session="auto",
            active_only=True,
            provider="taifex_mis",
        )
        record_event.assert_called_once()
        self.assertEqual(record_event.call_args.kwargs["provider"], "taifex_mis")
        self.assertEqual(record_event.call_args.kwargs["resource"], "tw_futures_quote")
        self.assertEqual(record_event.call_args.kwargs["target"], "TXF,MXF")
        self.assertEqual(record_event.call_args.kwargs["status"], "success")
        fake_db.close.assert_called_once()

    def test_taiwan_futures_collector_job_is_registered_as_interval_job(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())

        with (
            patch.object(scheduler.settings, "enable_taiwan_futures_scheduler", True),
            patch.object(scheduler.settings, "scheduler_taiwan_futures_interval_seconds", 30),
        ):
            added = scheduler._add_taiwan_futures_collector_job(fake_scheduler)

        self.assertTrue(added)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(fake_scheduler.add_job.call_args.args[0], scheduler.collect_taiwan_futures_quotes)
        self.assertEqual(kwargs["trigger"], "interval")
        self.assertEqual(kwargs["seconds"], 30)
        self.assertEqual(kwargs["id"], "taiwan_futures_quote_collector")

    def test_jp_market_refresh_job_is_registered_as_cron_job(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())

        with (
            patch.object(scheduler.settings, "enable_scheduler", True),
            patch.object(scheduler.settings, "enable_jp_market_scheduler", True),
            patch.object(scheduler.settings, "scheduler_jp_market_refresh_time", "16:10"),
            patch.object(scheduler.settings, "scheduler_jp_market_refresh_day_of_week", "mon-fri"),
        ):
            added = scheduler._add_jp_market_refresh_job(fake_scheduler)

        self.assertTrue(added)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.enqueue_jp_market_watchlist_resource_refresh,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["day_of_week"], "mon-fri")
        self.assertEqual(kwargs["hour"], 16)
        self.assertEqual(kwargs["minute"], 10)
        self.assertEqual(kwargs["id"], "jp_market_watchlist_resource_refresh")


if __name__ == "__main__":
    unittest.main()
