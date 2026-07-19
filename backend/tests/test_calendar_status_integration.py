from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.jobs import scheduler
from app.market.taiwan_rules import (
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
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
        self.assertEqual(request["categories"], [TAIWAN_REFRESH_INSTITUTIONAL_TRADE])
        self.assertTrue(request["include_today"])
        self.assertTrue(task_args[4])
        self.assertEqual(request["calendar_phase"], "post_close")
        fake_db.close.assert_called_once()

    def test_scheduler_margin_refresh_uses_margin_release_window(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-06-15",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_MARGIN_TRADING: {"is_released": True},
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=20), True),
            ) as enqueue,
        ):
            scheduler.enqueue_market_margin_daily_refresh()

        request = enqueue.call_args.kwargs["request"]
        task_args = enqueue.call_args.kwargs["task_args"]
        self.assertEqual(request["categories"], [TAIWAN_REFRESH_MARGIN_TRADING])
        self.assertTrue(request["include_today"])
        self.assertEqual(task_args[2], [TAIWAN_REFRESH_MARGIN_TRADING])
        self.assertTrue(task_args[4])
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

    def test_scheduler_market_chip_margin_refresh_uses_margin_window(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-06-15",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                "market_chip_margin_daily": {
                    "expected_trade_date": "2026-06-15",
                    "is_released": True,
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
                return_value=(SimpleNamespace(id=21), True),
            ) as enqueue,
        ):
            scheduler.enqueue_market_chip_margin_daily_refresh()

        request = enqueue.call_args.kwargs["request"]
        task_args = enqueue.call_args.kwargs["task_args"]
        self.assertEqual(request["trade_date"], date(2026, 6, 15))
        self.assertTrue(request["include_today"])
        self.assertEqual(task_args[1], date(2026, 6, 15))
        self.assertTrue(task_args[2])

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
        calendar_status = {
            "market": "jp",
            "date": "2026-07-15",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                "jp_daily_price": {
                    "expected_trade_date": "2026-07-15",
                    "status": "released",
                    "is_released": True,
                }
            },
        }

        with (
            patch.object(scheduler, "build_jp_calendar_status", return_value=calendar_status),
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
        self.assertEqual(request["market_date"], "2026-07-15")
        self.assertEqual(request["expected_trade_date"], date(2026, 7, 15))
        self.assertEqual(request["calendar_phase"], "post_close")
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

    def test_scheduler_skips_jp_refresh_when_calendar_is_closed(self) -> None:
        calendar_status = {
            "market": "jp",
            "date": "2026-07-20",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "release_windows": {},
        }

        with (
            patch.object(scheduler, "build_jp_calendar_status", return_value=calendar_status),
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            scheduler.enqueue_jp_market_watchlist_resource_refresh()

        enqueue.assert_not_called()

    def test_scheduler_kr_watchlist_resource_refresh_queues_job(self) -> None:
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch.object(scheduler.settings, "scheduler_kr_market_refresh_outputsize", "compact"),
            patch.object(scheduler.settings, "scheduler_kr_market_refresh_provider", "auto"),
            patch.object(
                scheduler.settings,
                "scheduler_kr_market_refresh_include_investors",
                True,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_kr_market_refresh_include_fundamentals",
                False,
            ),
            patch.object(
                scheduler,
                "resolve_market_refresh_interval_seconds",
                return_value=1.75,
            ) as resolve_sleep,
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=22), True),
            ) as enqueue,
        ):
            scheduler.enqueue_kr_market_watchlist_resource_refresh()

        kwargs = enqueue.call_args.kwargs
        request = kwargs["request"]
        task_args = kwargs["task_args"]
        self.assertEqual(kwargs["job_type"], "kr_market.scheduler.watchlist_resource_refresh")
        self.assertEqual(kwargs["target"], "all")
        self.assertEqual(request["schedule"], "kr_market_watchlist_resource_refresh")
        self.assertIsNone(request["group_id"])
        self.assertTrue(request["include_children"])
        self.assertTrue(request["enabled_only"])
        self.assertTrue(request["include_daily"])
        self.assertTrue(request["include_investors"])
        self.assertFalse(request["include_fundamentals"])
        self.assertEqual(request["outputsize"], "compact")
        self.assertEqual(request["provider"], "auto")
        self.assertEqual(
            task_args,
            (None, True, True, True, True, False, "compact", "auto", 1.75, None),
        )
        resolve_sleep.assert_called_once_with(market="kr")
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

    def test_taiwan_futures_provider_failure_backoff_is_bounded(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        failed_at = datetime(2026, 7, 17, 19, 30, tzinfo=timezone)

        with (
            patch.object(scheduler, "_LAST_TAIWAN_FUTURES_FAILURE_AT", failed_at),
            patch.object(
                scheduler.settings,
                "scheduler_taiwan_futures_failure_backoff_seconds",
                300,
            ),
        ):
            self.assertFalse(
                scheduler._should_attempt_taiwan_futures_refresh(
                    failed_at + timedelta(seconds=299)
                )
            )
            self.assertTrue(
                scheduler._should_attempt_taiwan_futures_refresh(
                    failed_at + timedelta(seconds=300)
                )
            )

    def test_taiwan_futures_collector_skips_during_provider_failure_backoff(self) -> None:
        with (
            patch.object(scheduler, "_is_taiwan_futures_live_window", return_value=True),
            patch.object(scheduler, "_should_attempt_taiwan_futures_refresh", return_value=False),
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

    def test_taiwan_futures_collector_records_failure_and_retry_time(self) -> None:
        fake_db = SimpleNamespace(close=Mock(), rollback=Mock())

        with (
            patch.object(scheduler, "_LAST_TAIWAN_FUTURES_FAILURE_AT", None),
            patch.object(scheduler, "_is_taiwan_futures_live_window", return_value=True),
            patch.object(scheduler.settings, "scheduler_taiwan_futures_symbols", "TXF"),
            patch.object(scheduler.settings, "scheduler_taiwan_futures_session", "auto"),
            patch.object(scheduler.settings, "taiwan_futures_quote_provider", "taifex_mis"),
            patch.object(
                scheduler.settings,
                "scheduler_taiwan_futures_failure_backoff_seconds",
                300,
            ),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "refresh_taiwan_futures_quotes",
                side_effect=scheduler.TaiwanFuturesFetchError("HTTP 520"),
            ),
            patch.object(scheduler, "record_provider_event") as record_event,
        ):
            scheduler.collect_taiwan_futures_quotes()

            self.assertIsNotNone(scheduler._LAST_TAIWAN_FUTURES_FAILURE_AT)
            detail = record_event.call_args.kwargs["detail"]
            self.assertIsNotNone(detail["retry_at"])

        fake_db.rollback.assert_called_once()
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

    def test_taiwan_derivatives_release_guard_requires_trading_day_and_1620(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")

        self.assertFalse(
            scheduler._is_taiwan_derivatives_refresh_ready(
                datetime(2026, 7, 17, 16, 19, tzinfo=timezone)
            )
        )
        self.assertTrue(
            scheduler._is_taiwan_derivatives_refresh_ready(
                datetime(2026, 7, 17, 16, 20, tzinfo=timezone)
            )
        )
        self.assertFalse(
            scheduler._is_taiwan_derivatives_refresh_ready(
                datetime(2026, 7, 19, 16, 20, tzinfo=timezone)
            )
        )

    def test_taiwan_derivatives_scheduler_queues_bounded_deduped_job(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        now = datetime(2026, 7, 17, 16, 20, tzinfo=timezone)
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.settings,
                "scheduler_taiwan_derivatives_success_cooldown_seconds",
                43200,
            ),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=51), True),
            ) as enqueue,
        ):
            datetime_mock.now.return_value = now
            scheduler.enqueue_taiwan_derivatives_refresh()

        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["job_type"], "scheduler.taiwan_derivatives_refresh")
        self.assertEqual(kwargs["target"], "TXF/TXO")
        self.assertEqual(kwargs["progress_total"], 5)
        self.assertEqual(kwargs["request"]["provider_request_limit"], 5)
        self.assertEqual(kwargs["request"]["expected_trade_date"], "2026-07-17")
        self.assertEqual(kwargs["task_args"], (date(2026, 7, 17),))
        self.assertEqual(kwargs["reuse_success_within_seconds"], 43200)
        fake_db.close.assert_called_once()

    def test_taiwan_derivatives_scheduler_skips_before_release(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        with (
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(scheduler, "SessionLocal") as session_local,
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            datetime_mock.now.return_value = datetime(
                2026,
                7,
                17,
                16,
                19,
                tzinfo=timezone,
            )
            scheduler.enqueue_taiwan_derivatives_refresh()

        session_local.assert_not_called()
        enqueue.assert_not_called()

    def test_taiwan_derivatives_refresh_job_is_registered_as_cron_job(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())

        with (
            patch.object(scheduler.settings, "enable_taiwan_derivatives_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_taiwan_derivatives_refresh_time",
                "16:20",
            ),
            patch.object(
                scheduler.settings,
                "scheduler_taiwan_derivatives_refresh_day_of_week",
                "mon-fri",
            ),
        ):
            added = scheduler._add_taiwan_derivatives_refresh_job(fake_scheduler)

        self.assertTrue(added)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.enqueue_taiwan_derivatives_refresh,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["day_of_week"], "mon-fri")
        self.assertEqual(kwargs["hour"], 16)
        self.assertEqual(kwargs["minute"], 20)
        self.assertEqual(kwargs["id"], "taiwan_derivatives_refresh")

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

    def test_kr_market_refresh_job_is_registered_as_cron_job(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())

        with (
            patch.object(scheduler.settings, "enable_scheduler", True),
            patch.object(scheduler.settings, "enable_kr_market_scheduler", True),
            patch.object(scheduler.settings, "scheduler_kr_market_refresh_time", "16:20"),
            patch.object(scheduler.settings, "scheduler_kr_market_refresh_day_of_week", "mon-fri"),
        ):
            added = scheduler._add_kr_market_refresh_job(fake_scheduler)

        self.assertTrue(added)
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.enqueue_kr_market_watchlist_resource_refresh,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["day_of_week"], "mon-fri")
        self.assertEqual(kwargs["hour"], 16)
        self.assertEqual(kwargs["minute"], 20)
        self.assertEqual(kwargs["id"], "kr_market_watchlist_resource_refresh")

    def test_watchlist_radar_auto_snapshot_queues_job_after_daily_release(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-07-07",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_DAILY_PRICE: {
                    "expected_trade_date": "2026-07-07",
                    "is_released": True,
                }
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_group_ids", "1,2"),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_modes", "action,risk"),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_max_results", 20),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_calculation_limit", 80),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_use_intraday", False),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_intraday_limit", 30),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_evaluate_lookback_days", 10),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_require_daily_release", True),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.radar_automation,
                "get_watchlist_radar_daily_coverage",
                return_value={
                    "complete": False,
                    "reconciliation_complete": False,
                    "snapshot_date": "2026-07-07",
                    "covered_count": 0,
                    "expected_count": 4,
                    "pending_evaluation_count": 0,
                },
            ),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=24), True),
            ) as enqueue,
        ):
            scheduler.enqueue_watchlist_radar_auto_snapshot()

        kwargs = enqueue.call_args.kwargs
        request = kwargs["request"]
        task_args = kwargs["task_args"]
        self.assertEqual(kwargs["job_type"], "watchlist.scheduler.radar_snapshot")
        self.assertEqual(kwargs["target"], "1,2")
        self.assertEqual(request["schedule"], "watchlist_radar_auto_snapshot")
        self.assertEqual(request["group_ids"], ["1", "2"])
        self.assertEqual(request["modes"], "action,risk")
        self.assertEqual(request["evaluate_before_date"], date(2026, 7, 7))
        self.assertEqual(task_args[0], ["1", "2"])
        self.assertEqual(task_args[1], "action,risk")
        self.assertEqual(task_args[4], 20)
        self.assertEqual(task_args[5], 80)
        self.assertEqual(task_args[9], 10)
        self.assertTrue(task_args[10])
        self.assertEqual(kwargs["progress_total"], 4)
        fake_db.close.assert_called_once()

    def test_watchlist_radar_auto_snapshot_skips_before_daily_release(self) -> None:
        calendar_status = {
            "market": "tw",
            "date": "2026-07-07",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_DAILY_PRICE: {
                    "expected_trade_date": "2026-07-07",
                    "is_released": False,
                }
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_require_daily_release", True),
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            scheduler.enqueue_watchlist_radar_auto_snapshot()

        enqueue.assert_not_called()

    def test_watchlist_radar_auto_snapshot_skips_when_daily_coverage_is_complete(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        calendar_status = {
            "market": "tw",
            "date": "2026-07-07",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_DAILY_PRICE: {
                    "expected_trade_date": "2026-07-07",
                    "is_released": True,
                }
            },
        }

        with (
            patch.object(scheduler, "build_taiwan_calendar_status", return_value=calendar_status),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler.radar_automation,
                "get_watchlist_radar_daily_coverage",
                return_value={
                    "complete": True,
                    "reconciliation_complete": True,
                    "snapshot_date": "2026-07-07",
                    "covered_count": 35,
                    "expected_count": 35,
                    "pending_evaluation_count": 0,
                },
            ),
            patch.object(scheduler.job_service, "enqueue_job") as enqueue,
        ):
            scheduler.enqueue_watchlist_radar_auto_snapshot()

        enqueue.assert_not_called()
        fake_db.close.assert_called_once()

    def test_watchlist_radar_auto_snapshot_job_is_registered_as_cron_job(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())

        with (
            patch.object(scheduler.settings, "enable_watchlist_radar_scheduler", True),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_time", "15:45"),
            patch.object(scheduler.settings, "scheduler_watchlist_radar_day_of_week", "mon-fri"),
            patch.object(
                scheduler.settings,
                "scheduler_watchlist_radar_reconcile_interval_minutes",
                30,
            ),
        ):
            added = scheduler._add_watchlist_radar_auto_snapshot_job(fake_scheduler)

        self.assertTrue(added)
        self.assertEqual(fake_scheduler.add_job.call_count, 2)
        cron_call, reconcile_call = fake_scheduler.add_job.call_args_list
        kwargs = cron_call.kwargs
        self.assertIs(
            cron_call.args[0],
            scheduler.enqueue_watchlist_radar_auto_snapshot,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["day_of_week"], "mon-fri")
        self.assertEqual(kwargs["hour"], 15)
        self.assertEqual(kwargs["minute"], 45)
        self.assertEqual(kwargs["id"], "watchlist_radar_auto_snapshot")
        self.assertIs(
            reconcile_call.args[0],
            scheduler.reconcile_watchlist_radar_auto_snapshot,
        )
        self.assertEqual(reconcile_call.kwargs["trigger"], "interval")
        self.assertEqual(reconcile_call.kwargs["minutes"], 30)
        self.assertEqual(
            reconcile_call.kwargs["id"],
            "watchlist_radar_auto_snapshot_reconcile",
        )

    def test_watchlist_radar_reconciliation_respects_configured_time(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")

        with (
            patch.object(scheduler.settings, "scheduler_watchlist_radar_time", "15:45"),
            patch.object(
                scheduler.settings,
                "scheduler_watchlist_radar_reconcile_until",
                "18:15",
            ),
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(scheduler, "enqueue_watchlist_radar_auto_snapshot") as enqueue,
        ):
            datetime_mock.now.return_value = datetime(2026, 7, 7, 15, 44, tzinfo=timezone)
            scheduler.reconcile_watchlist_radar_auto_snapshot()
            enqueue.assert_not_called()

            datetime_mock.now.return_value = datetime(2026, 7, 7, 15, 45, tzinfo=timezone)
            scheduler.reconcile_watchlist_radar_auto_snapshot()
            enqueue.assert_called_once_with()

            datetime_mock.now.return_value = datetime(2026, 7, 7, 18, 16, tzinfo=timezone)
            scheduler.reconcile_watchlist_radar_auto_snapshot()
            enqueue.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
