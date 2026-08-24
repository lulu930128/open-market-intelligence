from __future__ import annotations

from unittest.mock import Mock, patch

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

    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "TW,US"),
        patch.object(scheduler.settings, "scheduler_eod_coverage_us_max_symbols_per_run", 250),
        patch("app.jobs.scheduler.SessionLocal", side_effect=[fake_db_tw, fake_db_us]),
        patch("app.jobs.scheduler.should_enqueue_eod_reconcile", side_effect=[True, True]),
        patch(
            "app.jobs.scheduler.enqueue_eod_coverage_reconcile",
            side_effect=[(fake_job_tw, True), (fake_job_us, True)],
        ) as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    assert enqueue.call_count == 2
    assert enqueue.call_args_list[0].kwargs["market"] == "TW"
    assert enqueue.call_args_list[0].kwargs["max_symbols"] == 2
    assert enqueue.call_args_list[1].kwargs["market"] == "US"
    assert enqueue.call_args_list[1].kwargs["max_symbols"] == 250
