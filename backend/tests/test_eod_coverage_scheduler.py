from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from app.jobs import eod_coverage
from app.jobs import scheduler


def test_eod_coverage_scheduler_has_immediate_startup_catchup() -> None:
    fake_scheduler = Mock()

    with patch.object(scheduler.settings, "enable_eod_coverage_scheduler", True):
        assert scheduler._add_market_eod_coverage_reconcile_job(fake_scheduler) is True

    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["trigger"] == "interval"
    assert kwargs["id"] == "market_eod_coverage_reconcile"
    assert kwargs["max_instances"] == 1
    assert kwargs["next_run_time"] is not None


def test_scheduler_skips_healthy_or_backed_off_markets_without_enqueuing() -> None:
    fake_db_tw = Mock()
    fake_db_us = Mock()

    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "TW,US"),
        patch("app.jobs.scheduler.SessionLocal", side_effect=[fake_db_tw, fake_db_us]),
        patch("app.jobs.scheduler.should_enqueue_eod_reconcile", side_effect=[False, False]),
        patch("app.jobs.scheduler.enqueue_eod_coverage_reconcile") as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    enqueue.assert_not_called()
    assert fake_db_tw.close.call_count == 1
    assert fake_db_us.close.call_count == 1


def test_scheduler_enqueues_bounded_tw_and_us_repairs() -> None:
    fake_db_tw = Mock()
    fake_db_us = Mock()
    fake_job_tw = Mock(id=11)
    fake_job_us = Mock(id=12)
    expected_tw = date(2026, 8, 27)
    expected_us = date(2026, 8, 26)

    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "TW,US"),
        patch.object(scheduler.settings, "scheduler_eod_coverage_us_max_symbols_per_run", 250),
        patch("app.jobs.scheduler.SessionLocal", side_effect=[fake_db_tw, fake_db_us]),
        patch(
            "app.jobs.scheduler.expected_eod_trade_date",
            side_effect=[expected_tw, expected_us],
        ),
        patch(
            "app.jobs.scheduler.should_enqueue_eod_reconcile",
            side_effect=[True, True],
        ) as should_enqueue,
        patch(
            "app.jobs.scheduler.enqueue_eod_coverage_reconcile",
            side_effect=[(fake_job_tw, True), (fake_job_us, True)],
        ) as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    assert enqueue.call_count == 2
    assert enqueue.call_args_list[0].kwargs["market"] == "TW"
    assert enqueue.call_args_list[0].kwargs["max_symbols"] == 2
    assert enqueue.call_args_list[0].kwargs["expected_trade_date"] == expected_tw
    assert enqueue.call_args_list[1].kwargs["market"] == "US"
    assert enqueue.call_args_list[1].kwargs["max_symbols"] == 250


def test_eod_enqueue_clamps_effective_work_to_registry_bounds() -> None:
    fake_db = Mock()
    fake_job = Mock(id=31)

    with (
        patch(
            "app.jobs.eod_coverage.job_service.find_active_job_by_target",
            return_value=None,
        ),
        patch(
            "app.jobs.eod_coverage.job_service.enqueue_job",
            return_value=(fake_job, True),
        ) as enqueue,
    ):
        job, created = eod_coverage.enqueue_eod_coverage_reconcile(
            fake_db,
            market="TW",
            max_symbols=500,
            max_runtime_seconds=1800,
        )

    assert job is fake_job
    assert created is True
    kwargs = enqueue.call_args.kwargs
    assert kwargs["request"]["max_symbols"] == 2
    assert kwargs["request"]["max_runtime_seconds"] == 120
    assert kwargs["progress_total"] == 2
    assert kwargs["task_args"][3:5] == (2, 120)
