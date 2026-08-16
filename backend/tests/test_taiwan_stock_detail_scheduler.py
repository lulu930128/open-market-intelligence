from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.jobs import scheduler
from app.jobs import taiwan_fundamental_scheduler
from app.market import financial_metrics_history_backfill
from app.market import taiwan_fundamental_snapshot_refresh


class TaiwanStockDetailDailySchedulerTests(unittest.TestCase):
    def test_registers_release_plus_five_daily_jobs_and_startup_catchup(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(scheduler.settings, "enable_tw_stock_detail_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_tw_institutional_refresh_time",
                "20:05",
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_margin_refresh_time",
                "21:05",
            ),
        ):
            added = scheduler._add_taiwan_stock_detail_daily_refresh_jobs(
                fake_scheduler
            )

        self.assertTrue(added)
        self.assertEqual(fake_scheduler.add_job.call_count, 3)
        institutional, margin, startup = fake_scheduler.add_job.call_args_list
        self.assertEqual((institutional.kwargs["hour"], institutional.kwargs["minute"]), (20, 5))
        self.assertEqual((margin.kwargs["hour"], margin.kwargs["minute"]), (21, 5))
        self.assertEqual(startup.kwargs["trigger"], "date")

    def test_daily_startup_catchup_allows_closed_market(self) -> None:
        with (
            patch.object(scheduler, "enqueue_market_daily_refresh") as institutional,
            patch.object(scheduler, "enqueue_market_margin_daily_refresh") as margin,
        ):
            scheduler.enqueue_taiwan_stock_detail_daily_startup_catchup()

        institutional.assert_called_once_with(allow_non_trading_day=True)
        margin.assert_called_once_with(allow_non_trading_day=True)

    def test_weekend_branch_reconcile_does_not_repeat_catchup(self) -> None:
        with (
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(
                scheduler,
                "enqueue_taiwan_broker_branch_market_refresh",
            ) as enqueue,
        ):
            datetime_mock.now.return_value = SimpleNamespace(weekday=lambda: 6)
            scheduler.reconcile_taiwan_broker_branch_market_refresh()

        enqueue.assert_not_called()

    def test_registers_bounded_daily_metric_repair_and_startup_reconcile(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(
                scheduler.settings,
                "enable_market_daily_repair_scheduler",
                True,
            ),
            patch.object(scheduler.settings, "enable_scheduler", False),
            patch.object(scheduler.settings, "enable_tw_stock_detail_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_market_daily_repair_interval_minutes",
                30,
            ),
        ):
            added = scheduler._add_taiwan_daily_metric_repair_jobs(fake_scheduler)

        self.assertTrue(added)
        self.assertEqual(fake_scheduler.add_job.call_count, 2)
        interval, startup = fake_scheduler.add_job.call_args_list
        self.assertEqual(interval.kwargs["trigger"], "interval")
        self.assertEqual(interval.kwargs["minutes"], 30)
        self.assertEqual(interval.kwargs["max_instances"], 1)
        self.assertEqual(startup.kwargs["trigger"], "date")


class TaiwanFundamentalSchedulerTests(unittest.TestCase):
    def test_registers_bounded_release_and_deadline_jobs(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(
                taiwan_fundamental_scheduler.settings,
                "enable_tw_stock_detail_scheduler",
                True,
            ),
            patch.object(
                taiwan_fundamental_scheduler.settings,
                "scheduler_tw_shareholding_refresh_time",
                "12:05",
            ),
            patch.object(
                taiwan_fundamental_scheduler.settings,
                "scheduler_tw_revenue_refresh_time",
                "00:05",
            ),
            patch.object(
                taiwan_fundamental_scheduler.settings,
                "scheduler_tw_financial_refresh_time",
                "00:05",
            ),
        ):
            added = taiwan_fundamental_scheduler.add_taiwan_fundamental_refresh_jobs(
                fake_scheduler
            )

        self.assertTrue(added)
        self.assertEqual(fake_scheduler.add_job.call_count, 8)
        calls = {
            call.kwargs["id"]: call
            for call in fake_scheduler.add_job.call_args_list
        }
        self.assertEqual(calls["tw_shareholding_snapshot_refresh"].kwargs["hour"], "12-18")
        self.assertEqual(calls["tw_revenue_regular_deadline_refresh"].kwargs["day"], 11)
        self.assertEqual(calls["tw_revenue_market_deadline_refresh"].kwargs["day"], 16)
        self.assertEqual(calls["tw_financial_annual_deadline_refresh"].kwargs["month"], 4)
        self.assertEqual(calls["tw_financial_q1_deadline_refresh"].kwargs["day"], 16)

    def test_completed_target_skips_enqueue(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        with (
            patch.object(
                taiwan_fundamental_scheduler,
                "SessionLocal",
                return_value=fake_db,
            ),
            patch.object(
                taiwan_fundamental_scheduler,
                "_completed_event_exists",
                return_value=True,
            ),
            patch.object(
                taiwan_fundamental_scheduler.job_service,
                "enqueue_job",
            ) as enqueue,
        ):
            taiwan_fundamental_scheduler._enqueue_snapshot(
                category="monthly_revenue",
                dataset="monthly_revenue",
                expected_key="2026-06-01",
                scope="market",
                schedule="test",
            )

        enqueue.assert_not_called()
        fake_db.close.assert_called_once()

    def test_missing_completion_marker_enqueues_exact_target(self) -> None:
        fake_db = SimpleNamespace(close=Mock())
        with (
            patch.object(
                taiwan_fundamental_scheduler,
                "SessionLocal",
                return_value=fake_db,
            ),
            patch.object(
                taiwan_fundamental_scheduler,
                "_completed_event_exists",
                return_value=False,
            ),
            patch.object(
                taiwan_fundamental_scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=88), True),
            ) as enqueue,
        ):
            taiwan_fundamental_scheduler._enqueue_snapshot(
                category="monthly_revenue",
                dataset="monthly_revenue",
                expected_key="2026-06-01",
                scope="market",
                schedule="test",
            )

        self.assertEqual(enqueue.call_args.kwargs["target"], "market:2026-06-01")
        self.assertEqual(
            enqueue.call_args.kwargs["task_args"][2],
            "2026-06-01",
        )


class TaiwanFundamentalSnapshotTests(unittest.TestCase):
    def test_current_sources_record_completion_event(self) -> None:
        fake_db = Mock()
        with (
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "ensure_fundamental_metrics",
                return_value={"status": "success", "results": []},
            ),
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "_source_coverage",
                return_value={"complete": True, "sources": []},
            ),
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "record_provider_event",
            ) as record,
        ):
            result = (
                taiwan_fundamental_snapshot_refresh.refresh_taiwan_fundamental_snapshot(
                    fake_db,
                    category="monthly_revenue",
                    dataset="monthly_revenue",
                    expected_key="2026-06-01",
                    completion_target="market:2026-06-01",
                    job_run_id=7,
                )
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(record.call_args.kwargs["status"], "success")
        self.assertEqual(record.call_args.kwargs["job_run_id"], 7)

    def test_stale_sources_remain_partial_and_retryable(self) -> None:
        fake_db = Mock()
        with (
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "ensure_fundamental_metrics",
                return_value={"status": "success", "results": []},
            ),
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "_source_coverage",
                return_value={"complete": False, "sources": []},
            ),
            patch.object(
                taiwan_fundamental_snapshot_refresh,
                "record_provider_event",
            ) as record,
        ):
            result = (
                taiwan_fundamental_snapshot_refresh.refresh_taiwan_fundamental_snapshot(
                    fake_db,
                    category="financial_metrics",
                    dataset="financial_metric_quarterly",
                    expected_key="2026Q1",
                    completion_target="market:2026Q1",
                )
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(record.call_args.kwargs["status"], "stale")

    def test_existing_old_quarter_does_not_block_new_reportable_quarter(self) -> None:
        fake_query = Mock()
        fake_query.filter.return_value = fake_query
        fake_query.order_by.return_value = fake_query
        fake_query.first.return_value = SimpleNamespace(fiscal_year=2025, quarter=4)
        fake_db = SimpleNamespace(query=Mock(return_value=fake_query))
        with patch.object(
            financial_metrics_history_backfill,
            "_latest_reportable_quarter",
            return_value=(2026, 1),
        ):
            result = financial_metrics_history_backfill._latest_known_quarter(
                fake_db,
                "2330",
            )

        self.assertEqual(result, (2026, 1))


if __name__ == "__main__":
    unittest.main()
