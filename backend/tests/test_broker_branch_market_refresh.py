from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    BrokerBranchTradeDaily,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.jobs import scheduler
from app.routers import jobs as jobs_router
from app.market import broker_branch_market_refresh as market_refresh
from app.market.taiwan_rules import TAIWAN_DATASET_BROKER_BRANCH


class BrokerBranchMarketRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.trade_date = date(2026, 7, 20)
        self.source = SourceRegistry(
            source_name="test broker branch",
            source_type="http_api",
            category="broker_branch_trade",
        )
        self.raw = RawFetchResult(
            source=self.source,
            url="https://example.test/branch",
            method="GET",
        )
        self.db.add_all(
            [
                self.source,
                self.raw,
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="環球晶",
                    market="TPEx",
                    instrument_type="stock",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="0050",
                    stock_name="元大台灣50",
                    market="TWSE",
                    instrument_type="etf",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="700050",
                    stock_name="測試權證",
                    market="TPEx",
                    instrument_type="unknown",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="9999",
                    stock_name="下市股票",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=False,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_branch_row(self, stock_id: str) -> BrokerBranchTradeDaily:
        row = BrokerBranchTradeDaily(
            source_id=self.source.id,
            raw_result_id=self.raw.id,
            trade_date=self.trade_date,
            stock_id=stock_id,
            stock_name=stock_id,
            branch_code=f"B{stock_id}",
            branch_name=f"Branch {stock_id}",
            net_lots=10,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_universe_contains_only_active_twse_tpex_ordinary_stocks(self) -> None:
        self.assertEqual(
            market_refresh.list_taiwan_broker_branch_stock_ids(self.db),
            ["2330", "6488"],
        )

    def test_refresh_skips_existing_rows_and_completes_missing_stock(self) -> None:
        self._add_branch_row("2330")

        def store_missing(db: Session, *, stock_id: str, **_: object):
            self.assertEqual(stock_id, "6488")
            return [self._add_branch_row(stock_id)]

        with (
            patch.object(
                market_refresh,
                "probe_broker_branch_release",
                return_value={
                    "stock_id": "2330",
                    "trade_date": self.trade_date,
                    "row_count": 30,
                    "source_url": "https://example.test/branch",
                },
            ) as probe,
            patch.object(
                market_refresh,
                "ensure_broker_branch_daily",
                side_effect=store_missing,
            ) as ensure,
            patch.object(market_refresh, "_record_collection_event") as event,
        ):
            result = market_refresh.refresh_taiwan_broker_branch_market(
                self.db,
                trade_date=self.trade_date,
                sleep_seconds=0,
                max_stocks=10,
                max_runtime_seconds=60,
            )

        probe.assert_called_once_with("2330")
        ensure.assert_called_once()
        event.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["covered_before_count"], 1)
        self.assertEqual(result["covered_count"], 2)
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["remaining_count"], 0)

    def test_refresh_stops_when_provider_has_not_released_target_date(self) -> None:
        previous_date = date(2026, 7, 17)
        with (
            patch.object(
                market_refresh,
                "probe_broker_branch_release",
                return_value={
                    "stock_id": "2330",
                    "trade_date": previous_date,
                    "row_count": 30,
                    "source_url": "https://example.test/branch",
                },
            ),
            patch.object(market_refresh, "ensure_broker_branch_daily") as ensure,
            patch.object(market_refresh, "_record_collection_event"),
        ):
            result = market_refresh.refresh_taiwan_broker_branch_market(
                self.db,
                trade_date=self.trade_date,
                sleep_seconds=0,
            )

        ensure.assert_not_called()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "provider_not_ready")
        self.assertEqual(result["provider_trade_date"], previous_date)
        self.assertEqual(result["request_count"], 1)


class BrokerBranchSchedulerTests(unittest.TestCase):
    def test_scheduler_queues_bounded_missing_coverage_job(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        now = datetime(2026, 7, 20, 16, 0, tzinfo=timezone)
        target_date = date(2026, 7, 20)
        calendar_status = {
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "post_close",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_BROKER_BRANCH: {
                    "expected_trade_date": "2026-07-20",
                    "is_released": True,
                }
            },
        }
        fake_db = SimpleNamespace(close=Mock())

        with (
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(
                scheduler,
                "build_taiwan_calendar_status",
                return_value=calendar_status,
            ),
            patch.object(
                scheduler,
                "is_release_released_from_calendar",
                return_value=True,
            ),
            patch.object(
                scheduler,
                "expected_trade_date_from_calendar",
                return_value=target_date,
            ),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "get_taiwan_broker_branch_market_coverage",
                return_value={
                    "trade_date": target_date,
                    "expected_count": 1973,
                    "covered_count": 73,
                    "missing_count": 1900,
                    "complete": False,
                },
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_sleep_seconds",
                0.5,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_max_stocks",
                2500,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_max_runtime_seconds",
                7200,
            ),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=88), True),
            ) as enqueue,
        ):
            datetime_mock.now.return_value = now
            scheduler.enqueue_taiwan_broker_branch_market_refresh()

        kwargs = enqueue.call_args.kwargs
        self.assertEqual(
            kwargs["job_type"],
            "scheduler.tw_broker_branch_market_refresh",
        )
        self.assertEqual(kwargs["target"], "2026-07-20")
        self.assertEqual(kwargs["progress_total"], 1900)
        self.assertEqual(kwargs["request"]["provider_request_limit"], 2501)
        self.assertEqual(kwargs["task_args"], (target_date, 0.5, 2500, 7200))
        fake_db.close.assert_called_once()

    def test_scheduler_registers_cron_and_reconciliation_jobs(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(scheduler.settings, "enable_tw_broker_branch_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_refresh_time",
                "16:00",
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_refresh_day_of_week",
                "mon-fri",
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_broker_branch_reconcile_interval_minutes",
                30,
            ),
        ):
            added = scheduler._add_taiwan_broker_branch_market_refresh_job(
                fake_scheduler
            )

        self.assertTrue(added)
        self.assertEqual(fake_scheduler.add_job.call_count, 3)
        cron_call, reconcile_call, startup_call = fake_scheduler.add_job.call_args_list
        self.assertIs(
            cron_call.args[0],
            scheduler.enqueue_taiwan_broker_branch_market_refresh,
        )
        self.assertEqual(cron_call.kwargs["day_of_week"], "mon-fri")
        self.assertEqual(cron_call.kwargs["hour"], 16)
        self.assertEqual(cron_call.kwargs["minute"], 0)
        self.assertEqual(
            cron_call.kwargs["id"],
            "tw_broker_branch_market_refresh",
        )
        self.assertIs(
            reconcile_call.args[0],
            scheduler.reconcile_taiwan_broker_branch_market_refresh,
        )
        self.assertEqual(reconcile_call.kwargs["minutes"], 30)
        self.assertIs(
            startup_call.args[0],
            scheduler.enqueue_taiwan_broker_branch_market_refresh,
        )
        self.assertEqual(startup_call.kwargs["trigger"], "date")
        self.assertEqual(
            startup_call.kwargs["id"],
            "tw_broker_branch_market_refresh_startup_catchup",
        )

    def test_scheduler_startup_can_catch_previous_trade_date(self) -> None:
        timezone = ZoneInfo("Asia/Taipei")
        now = datetime(2026, 7, 21, 8, 0, tzinfo=timezone)
        target_date = date(2026, 7, 20)
        calendar_status = {
            "date": "2026-07-21",
            "is_trading_day": True,
            "phase": "preopen",
            "reason": "trading_day",
            "release_windows": {
                TAIWAN_DATASET_BROKER_BRANCH: {
                    "expected_trade_date": "2026-07-20",
                    "is_released": False,
                }
            },
        }
        fake_db = SimpleNamespace(close=Mock())
        with (
            patch.object(scheduler, "datetime") as datetime_mock,
            patch.object(
                scheduler,
                "build_taiwan_calendar_status",
                return_value=calendar_status,
            ),
            patch.object(
                scheduler,
                "is_release_released_from_calendar",
                return_value=False,
            ),
            patch.object(
                scheduler,
                "expected_trade_date_from_calendar",
                return_value=target_date,
            ),
            patch.object(scheduler, "SessionLocal", return_value=fake_db),
            patch.object(
                scheduler,
                "get_taiwan_broker_branch_market_coverage",
                return_value={
                    "trade_date": target_date,
                    "expected_count": 2,
                    "covered_count": 1,
                    "missing_count": 1,
                    "complete": False,
                },
            ),
            patch.object(
                scheduler.job_service,
                "enqueue_job",
                return_value=(SimpleNamespace(id=89), True),
            ) as enqueue,
        ):
            datetime_mock.now.return_value = now
            scheduler.enqueue_taiwan_broker_branch_market_refresh()

        self.assertEqual(enqueue.call_args.kwargs["target"], "2026-07-20")
        self.assertEqual(
            enqueue.call_args.kwargs["request"]["collection_mode"],
            "startup_catchup",
        )
        fake_db.close.assert_called_once()

    def test_scheduled_job_supports_update_center_retry(self) -> None:
        job = SimpleNamespace(
            id=99,
            job_type="scheduler.tw_broker_branch_market_refresh",
            status="error",
            target="2026-07-20",
            progress_current=0,
            progress_total=1900,
            message="failed",
            error_message="provider unavailable",
            request_json=(
                '{"expected_trade_date":"2026-07-20","sleep_seconds":0.5,'
                '"max_stocks":2500,"max_runtime_seconds":7200}'
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = jobs_router._retry_config(job)

        self.assertIs(
            task,
            scheduler.backfill_tasks.run_taiwan_broker_branch_market_refresh_job,
        )
        self.assertEqual(
            task_args,
            (date(2026, 7, 20), 0.5, 2500, 7200),
        )
        self.assertEqual(request["expected_trade_date"], "2026-07-20")


if __name__ == "__main__":
    unittest.main()
