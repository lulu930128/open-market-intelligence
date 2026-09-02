from __future__ import annotations

from datetime import date

import pytest
from unittest.mock import patch

from app.jobs import service as job_service
from app.jobs.taiwan_bar_bootstrap import run_taiwan_index_daily_bootstrap_job


def _run_inline(_job_id, worker):
    return worker(None, lambda *_args: None)


def test_tracked_index_bootstrap_job_preserves_success_result() -> None:
    expected = {
        "status": "success",
        "postcondition": {"satisfied": True},
    }
    captured: dict = {}

    def capture_inline(_job_id, worker):
        captured.update(worker(None, lambda *_args: None))

    with (
        patch(
            "app.jobs.taiwan_bar_bootstrap.bootstrap_taiex_official_daily_history",
            return_value=expected,
        ),
        patch(
            "app.jobs.taiwan_bar_bootstrap.job_service.run_tracked_job",
            side_effect=capture_inline,
        ),
    ):
        run_taiwan_index_daily_bootstrap_job(
            11,
            ("TAIEX",),
            date(2025, 8, 1),
            date(2026, 9, 2),
            300,
            300,
        )

    assert captured["status"] == "success"
    assert captured["results"] == [expected]


def test_tracked_index_bootstrap_job_fails_closed_on_partial_postcondition() -> None:
    partial = {
        "status": "partial",
        "postcondition": {"satisfied": False},
    }

    with (
        patch(
            "app.jobs.taiwan_bar_bootstrap.bootstrap_tpex_completed_derived_daily_history",
            return_value=partial,
        ),
        patch(
            "app.jobs.taiwan_bar_bootstrap.job_service.run_tracked_job",
            side_effect=_run_inline,
        ),
        pytest.raises(job_service.JobExecutionError) as exc_info,
    ):
        run_taiwan_index_daily_bootstrap_job(
            12,
            ("TPEX",),
            date(2025, 8, 1),
            date(2026, 9, 2),
            300,
            300,
        )

    assert exc_info.value.result == {
        "contract_version": "tw.index_daily.bootstrap_job.v1",
        "status": "partial",
        "results": [partial],
    }
