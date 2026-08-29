from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.db.models import JobRun, utc_now
from app.jobs import backfill_tasks
from app.jobs import service as job_service
from app.market import monthly_revenue_history_backfill, stock_selection_refresh
from app.routers.jobs import _parse_date, _retry_config
from app.stocks.bootstrap import BOOTSTRAP_JOB_TYPE, run_stock_master_bootstrap_job


class JobRetryTests(unittest.TestCase):
    def test_retry_config_recreates_stock_master_bootstrap_task(self) -> None:
        request = {
            "reason": "empty_stock_master",
            "markets": ["TWSE", "TPEX"],
            "provider_policy": "official_bounded",
        }
        job = SimpleNamespace(
            id=11,
            job_type=BOOTSTRAP_JOB_TYPE,
            status="error",
            target="TWSE,TPEX",
            progress_current=2,
            progress_total=6,
            message=None,
            error_message="provider unavailable",
            request_json=json.dumps(request),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, retried_request = _retry_config(job)

        self.assertIs(task, run_stock_master_bootstrap_job)
        self.assertEqual(task_args, (True,))
        self.assertEqual(retried_request, request)

    def test_monthly_revenue_backfill_targets_latest_released_period_not_latest_cache(self) -> None:
        with patch.object(
            monthly_revenue_history_backfill,
            "expected_monthly_revenue_period",
            return_value=date(2026, 6, 1),
        ):
            months = monthly_revenue_history_backfill._target_months(
                db=SimpleNamespace(),
                stock_id="2330",
                from_period=None,
                to_period=None,
                lookback_months=3,
            )

        self.assertEqual(
            months,
            [date(2026, 6, 1), date(2026, 5, 1), date(2026, 4, 1)],
        )

    def test_retry_config_recreates_stock_selection_refresh_task(self) -> None:
        job = SimpleNamespace(
            id=12,
            job_type="market.stock_selection_refresh",
            status="error",
            target="2330",
            progress_current=0,
            progress_total=1,
            message=None,
            error_message="network timeout",
            request_json=json.dumps(
                {"stock_id": "2330", "include_today": True, "sleep_seconds": 0.05}
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_stock_selection_refresh_job)
        self.assertEqual(task_args, ("2330", True, 0.05, "full"))
        self.assertEqual(request["stock_id"], "2330")

    def test_retry_config_recreates_market_chip_refresh_task(self) -> None:
        job = SimpleNamespace(
            id=14,
            job_type="market.market_chip_daily_refresh",
            status="error",
            target="market-chips",
            progress_current=0,
            progress_total=2,
            message=None,
            error_message="source unavailable",
            request_json=json.dumps(
                {
                    "index_ids": ["TAIEX", "TPEX"],
                    "trade_date": "2026-06-09",
                    "include_today": True,
                    "force": False,
                }
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_market_chip_daily_refresh_job)
        self.assertEqual(
            task_args,
            (["TAIEX", "TPEX"], date(2026, 6, 9), True, False),
        )
        self.assertEqual(request["index_ids"], ["TAIEX", "TPEX"])

    def test_retry_config_recreates_scheduled_margin_refresh_task(self) -> None:
        job = SimpleNamespace(
            id=15,
            job_type="scheduler.market_margin_daily_refresh",
            status="error",
            target="2026-07-24",
            progress_current=0,
            progress_total=1,
            message=None,
            error_message="provider unavailable",
            request_json=json.dumps(
                {
                    "start_date": "2026-07-24",
                    "end_date": "2026-07-24",
                    "categories": ["margin_trading"],
                    "sleep_seconds": 0.2,
                    "skip_existing": True,
                }
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_market_daily_metrics_job)
        self.assertEqual(
            task_args,
            (
                date(2026, 7, 24),
                date(2026, 7, 24),
                ["margin_trading"],
                30,
                False,
                0.2,
                True,
                date(2026, 7, 24),
                None,
            ),
        )
        self.assertEqual(request["categories"], ["margin_trading"])

    def test_retry_config_recreates_fundamental_snapshot_task(self) -> None:
        job = SimpleNamespace(
            id=17,
            job_type="scheduler.tw_stock_detail_financial_metrics_refresh",
            status="error",
            target="market:2026Q1",
            progress_current=0,
            progress_total=1,
            message=None,
            error_message="source still stale",
            request_json=json.dumps(
                {
                    "category": "financial_metrics",
                    "dataset": "financial_metric_quarterly",
                    "expected_key": "2026Q1",
                    "completion_target": "market:2026Q1",
                    "sleep_seconds": 0.2,
                }
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(
            task,
            backfill_tasks.run_taiwan_fundamental_snapshot_refresh_job,
        )
        self.assertEqual(
            task_args,
            (
                "financial_metrics",
                "financial_metric_quarterly",
                "2026Q1",
                "market:2026Q1",
                0.2,
            ),
        )
        self.assertEqual(request["expected_key"], "2026Q1")

    def test_retry_config_preserves_basic_selection_refresh_profile(self) -> None:
        job = SimpleNamespace(
            id=13,
            job_type="market.stock_selection_refresh",
            status="error",
            target="2330",
            progress_current=0,
            progress_total=1,
            message=None,
            error_message="network timeout",
            request_json=json.dumps(
                {
                    "stock_id": "2330",
                    "include_today": None,
                    "profile": "basic",
                    "sleep_seconds": 0.05,
                }
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_stock_selection_refresh_job)
        self.assertEqual(task_args, ("2330", None, 0.05, "basic"))
        self.assertEqual(request["profile"], "basic")

    def test_retry_config_recreates_taiwan_derivatives_refresh_task(self) -> None:
        job = SimpleNamespace(
            id=16,
            job_type="scheduler.taiwan_derivatives_refresh",
            status="error",
            target="TXF/TXO",
            progress_current=4,
            progress_total=5,
            message="Job failed.",
            error_message="delta unavailable",
            request_json=json.dumps(
                {
                    "expected_trade_date": "2026-07-17",
                    "provider_request_limit": 5,
                }
            ),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_taiwan_derivatives_refresh_job)
        self.assertEqual(task_args, (date(2026, 7, 17),))
        self.assertEqual(request["provider_request_limit"], 5)

    def test_parse_date_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            _parse_date("not-a-date")

    def test_basic_selection_refresh_runs_only_lightweight_steps(self) -> None:
        released_date = date(2026, 6, 4)

        with (
            patch.object(
                stock_selection_refresh,
                "expected_daily_price_date",
                return_value=released_date,
            ),
            patch.object(
                stock_selection_refresh,
                "expected_institutional_trade_date",
                return_value=released_date,
            ),
            patch.object(
                stock_selection_refresh,
                "expected_margin_trade_date",
                return_value=released_date,
            ),
            patch.object(
                stock_selection_refresh,
                "expected_broker_branch_date",
                return_value=released_date,
            ),
            patch.object(
                stock_selection_refresh,
                "_ensure_current_month_daily_prices",
                return_value={"status": "success"},
            ) as daily_price,
            patch.object(
                stock_selection_refresh,
                "ensure_stock_daily_metrics",
                return_value={"status": "success"},
            ) as daily_metrics,
            patch.object(stock_selection_refresh, "ensure_broker_branch_daily") as branch,
            patch.object(stock_selection_refresh, "ensure_stock_shareholding_history") as shareholding,
            patch.object(stock_selection_refresh, "ensure_stock_monthly_revenue_history") as revenue,
            patch.object(stock_selection_refresh, "ensure_stock_financial_metrics_history") as financials,
        ):
            result = stock_selection_refresh.refresh_selected_stock_data(
                db=SimpleNamespace(),
                stock_id="2330",
                include_today=None,
                sleep_seconds=0.05,
                profile="basic",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["profile"], "basic")
        self.assertEqual(result["requested_count"], 2)
        self.assertEqual(result["completed_count"], 2)
        self.assertEqual(result["refreshed_count"], 0)
        self.assertEqual(result["unchanged_count"], 2)
        self.assertEqual(
            result["refreshed_count_semantics"],
            "datasets_with_inserted_or_updated_rows",
        )
        self.assertEqual(set(result["results"]), {"daily_price", "institutional_trade"})
        daily_price.assert_called_once()
        daily_metrics.assert_called_once()
        self.assertEqual(daily_metrics.call_args.kwargs["categories"], ["institutional_trade"])
        branch.assert_not_called()
        shareholding.assert_not_called()
        revenue.assert_not_called()
        financials.assert_not_called()

    def test_custom_selection_refresh_runs_only_requested_dataset(self) -> None:
        with (
            patch.object(
                stock_selection_refresh,
                "ensure_stock_monthly_revenue_history",
                return_value={
                    "status": "success",
                    "inserted_count": 1,
                    "updated_count": 0,
                },
            ) as revenue,
            patch.object(
                stock_selection_refresh,
                "_ensure_current_month_daily_prices",
            ) as daily_price,
            patch.object(
                stock_selection_refresh,
                "ensure_stock_daily_metrics",
            ) as daily_metrics,
            patch.object(
                stock_selection_refresh,
                "ensure_broker_branch_daily",
            ) as branch,
            patch.object(
                stock_selection_refresh,
                "ensure_stock_shareholding_history",
            ) as shareholding,
            patch.object(
                stock_selection_refresh,
                "ensure_stock_financial_metrics_history",
            ) as financials,
        ):
            result = stock_selection_refresh.refresh_selected_stock_data(
                db=SimpleNamespace(),
                stock_id="2330",
                steps=["monthly_revenue"],
            )

        self.assertEqual(result["profile"], "custom")
        self.assertEqual(result["requested_count"], 1)
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(result["changed_row_count"], 1)
        self.assertEqual(
            result["results"]["monthly_revenue"]["refresh_outcome"],
            "updated",
        )
        self.assertEqual(set(result["results"]), {"monthly_revenue"})
        revenue.assert_called_once()
        daily_price.assert_not_called()
        daily_metrics.assert_not_called()
        branch.assert_not_called()
        shareholding.assert_not_called()
        financials.assert_not_called()

    def test_shareholding_no_change_records_refresh_cooldown(self) -> None:
        telemetry_db = Mock(spec=Session)
        with (
            patch.object(
                stock_selection_refresh,
                "ensure_stock_shareholding_history",
                return_value={"status": "success", "inserted_count": 0},
            ),
            patch.object(
                stock_selection_refresh,
                "SessionLocal",
                return_value=telemetry_db,
            ),
            patch.object(
                stock_selection_refresh,
                "record_provider_event",
            ) as record_event,
        ):
            result = stock_selection_refresh.refresh_selected_stock_data(
                db=SimpleNamespace(),
                stock_id="2330",
                steps=["shareholding_distribution"],
            )

        self.assertEqual(
            result["results"]["shareholding_distribution"][
                "refresh_outcome"
            ],
            "unchanged",
        )
        record_event.assert_called_once()
        call = record_event.call_args
        self.assertIs(call.args[0], telemetry_db)
        self.assertEqual(call.kwargs["event_type"], "refresh_no_change")
        self.assertEqual(
            call.kwargs["detail"]["refresh_outcome"],
            "unchanged",
        )
        self.assertIn(
            "next_eligible_refresh_at",
            call.kwargs["detail"],
        )
        telemetry_db.rollback.assert_not_called()
        telemetry_db.close.assert_called_once()

    def test_shareholding_inner_error_is_a_failed_selected_refresh(self) -> None:
        with (
            patch.object(
                stock_selection_refresh,
                "ensure_stock_shareholding_history",
                return_value={
                    "status": "error",
                    "error_count": 1,
                    "results": [
                        {
                            "stock_id": "8299",
                            "status": "error",
                            "error_message": "TDCC request timed out",
                        }
                    ],
                },
            ),
            patch.object(
                stock_selection_refresh,
                "_record_shareholding_refresh_outcome",
            ) as record_outcome,
        ):
            result = stock_selection_refresh.refresh_selected_stock_data(
                db=SimpleNamespace(),
                stock_id="8299",
                steps=["shareholding_distribution"],
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["refresh_outcome"], "failed")
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["completed_count"], 0)
        failed_step = result["failed_steps"][0]
        self.assertEqual(
            failed_step["dataset"],
            "shareholding_distribution",
        )
        self.assertEqual(failed_step["provider"], "tdcc")
        self.assertEqual(failed_step["target"], "8299")
        self.assertEqual(
            failed_step["error_message"],
            "TDCC request timed out",
        )
        recorded = record_outcome.call_args.kwargs["result"]
        self.assertEqual(recorded["refresh_outcome"], "failed")
        self.assertEqual(recorded["error_message"], "TDCC request timed out")

    def test_shareholding_telemetry_failure_does_not_poison_caller_session(
        self,
    ) -> None:
        caller_db = Mock(spec=Session)
        telemetry_db = Mock(spec=Session)
        with (
            patch.object(
                stock_selection_refresh,
                "ensure_stock_shareholding_history",
                return_value={"status": "success", "inserted_count": 0},
            ),
            patch.object(
                stock_selection_refresh,
                "ensure_stock_monthly_revenue_history",
                return_value={"status": "success", "inserted_count": 1},
            ) as revenue,
            patch.object(
                stock_selection_refresh,
                "SessionLocal",
                return_value=telemetry_db,
            ),
            patch.object(
                stock_selection_refresh,
                "record_provider_event",
                side_effect=RuntimeError("telemetry commit failed"),
            ),
            patch.object(
                stock_selection_refresh.logger,
                "exception",
            ) as log_exception,
        ):
            result = stock_selection_refresh.refresh_selected_stock_data(
                db=caller_db,
                stock_id="2330",
                steps=[
                    "shareholding_distribution",
                    "monthly_revenue",
                ],
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["completed_count"], 2)
        self.assertEqual(result["refreshed_count"], 1)
        revenue.assert_called_once()
        caller_db.rollback.assert_not_called()
        telemetry_db.rollback.assert_called_once()
        telemetry_db.close.assert_called_once()
        log_exception.assert_called()

    def test_serialize_job_can_return_compact_polling_summary(self) -> None:
        job = SimpleNamespace(
            id=99,
            job_type="market.stock_daily_metrics_history_backfill",
            status="success",
            target="2330",
            progress_current=2,
            progress_total=2,
            message="done",
            error_message=None,
            request_json=json.dumps({"stock_id": "2330", "sleep_seconds": 0.05}),
            result_json=json.dumps(
                {
                    "status": "partial_success",
                    "requested_count": 2,
                    "success_count": 1,
                    "error_count": 1,
                    "inserted_count": 4,
                    "results": [
                        {
                            "stock_id": "2330",
                            "status": "success",
                            "message": "ok",
                            "raw_payload": "x" * 5000,
                        },
                        {
                            "stock_id": "2454",
                            "stock_name": "聯發科",
                            "status": "error",
                            "error_message": "source unavailable",
                            "raw_payload": "y" * 5000,
                        },
                    ],
                }
            ),
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        serialized = job_service.serialize_job(job, include_payload=False)

        self.assertIsNone(serialized["request"])
        self.assertEqual(serialized["result"]["status"], "partial_success")
        self.assertEqual(serialized["result"]["requested_count"], 2)
        self.assertEqual(serialized["result"]["error_count"], 1)
        self.assertEqual(serialized["result"]["inserted_count"], 4)
        self.assertEqual(serialized["result"]["result_count"], 2)
        self.assertEqual(serialized["result"]["results"][0]["stock_id"], "2454")
        self.assertNotIn("raw_payload", serialized["result"]["results"][0])

    def test_compact_job_list_query_defers_full_payload_columns(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        JobRun.__table__.create(bind=engine)
        now = utc_now()

        with Session(engine) as db:
            job = JobRun(
                job_type="market.stock_selection_refresh",
                status="success",
                target="2330",
                progress_current=1,
                progress_total=1,
                message="Job completed.",
                error_message=None,
                request_json=json.dumps({"stock_id": "2330", "raw": "x" * 5000}),
                result_json=json.dumps({"status": "success", "raw": "y" * 5000}),
                result_summary_json=json.dumps({"status": "success"}),
                created_at=now,
                started_at=now,
                ended_at=now,
                updated_at=now,
            )
            db.add(job)
            db.commit()
            db.expire_all()

            rows = job_service.list_jobs(db, limit=1, include_payload=False)
            row = rows[0]
            unloaded = sqlalchemy_inspect(row).unloaded
            serialized = job_service.serialize_job(row, include_payload=False)

        self.assertIn("request_json", unloaded)
        self.assertIn("result_json", unloaded)
        self.assertEqual(serialized["request"], None)
        self.assertEqual(serialized["result"], {"status": "success"})

    def test_retry_config_recreates_us_ohlc_history_repair(self) -> None:
        request = {
            "symbol": "UMC",
            "timeframe": "daily",
            "bars": 180,
            "provider": "yahoo_chart",
            "adjusted": False,
            "max_provider_calls": 2,
            "force_full": False,
        }
        job = SimpleNamespace(
            id=201,
            job_type="us_market.ohlc_history_repair",
            status="error",
            target="UMC:daily:180",
            progress_current=1,
            progress_total=1,
            message="Job failed.",
            error_message="continuity failed",
            request_json=json.dumps(request),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, retried_request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_us_ohlc_history_repair_job)
        self.assertEqual(
            task_args,
            ("UMC", "daily", 180, "yahoo_chart", False, 2, False),
        )
        self.assertEqual(retried_request, request)

    def test_retry_config_recreates_priority_us_ohlc_reconcile(self) -> None:
        request = {
            "max_runtime_seconds": 600,
            "cursor_symbol": "UMC",
        }
        job = SimpleNamespace(
            id=202,
            job_type="us_market.priority_ohlc_reconcile",
            status="error",
            target="priority-research",
            progress_current=1,
            progress_total=1,
            message="Job failed.",
            error_message="provider unavailable",
            request_json=json.dumps(request),
            result_json=None,
            created_at=None,
            started_at=None,
            ended_at=None,
            updated_at=None,
        )

        task, task_args, retried_request = _retry_config(job)

        self.assertIs(task, backfill_tasks.run_us_priority_ohlc_reconcile_job)
        self.assertEqual(task_args, (600, "UMC"))
        self.assertEqual(retried_request, request)


if __name__ == "__main__":
    unittest.main()
