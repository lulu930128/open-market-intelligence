from __future__ import annotations

from types import SimpleNamespace
import json
import unittest

from app.jobs import backfill_tasks
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
        self.assertEqual(task_args, ("2330", True, 0.05))
        self.assertEqual(request["stock_id"], "2330")

    def test_parse_date_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            _parse_date("not-a-date")


if __name__ == "__main__":
    unittest.main()
