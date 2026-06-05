from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.db.models import JobRun, utc_now
from app.jobs import backfill_tasks
from app.jobs import service as job_service
from app.market import stock_selection_refresh
from app.routers.jobs import _parse_date, _retry_config


class JobRetryTests(unittest.TestCase):
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

    def test_parse_date_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            _parse_date("not-a-date")

    def test_basic_selection_refresh_runs_only_lightweight_steps(self) -> None:
        released_date = date(2026, 6, 4)

        with (
            patch.object(
                stock_selection_refresh,
                "latest_released_trading_day",
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
        self.assertEqual(set(result["results"]), {"daily_price", "institutional_trade"})
        daily_price.assert_called_once()
        daily_metrics.assert_called_once()
        self.assertEqual(daily_metrics.call_args.kwargs["categories"], ["institutional_trade"])
        branch.assert_not_called()
        shareholding.assert_not_called()
        revenue.assert_not_called()
        financials.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
