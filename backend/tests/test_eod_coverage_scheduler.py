from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.jobs import eod_coverage
from app.jobs import scheduler
from app.db.models import Base, JobRun


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
        patch(
            "app.us_market.daily_rollout.us_daily_full_market_acquisition_enabled",
            return_value=True,
        ),
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
        patch(
            "app.us_market.daily_rollout.us_daily_full_market_acquisition_enabled",
            return_value=True,
        ),
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
    assert enqueue.call_args_list[1].kwargs["expected_trade_date"] == expected_us
    assert should_enqueue.call_args_list[0].kwargs["expected_trade_date"] == expected_tw
    assert should_enqueue.call_args_list[1].kwargs["expected_trade_date"] == expected_us


def test_scheduler_tw_only_configuration_does_not_touch_us_lifecycle() -> None:
    fake_db = Mock()
    fake_job = Mock(id=13)
    expected_tw = date(2026, 8, 27)

    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "TW"),
        patch("app.jobs.scheduler.SessionLocal", return_value=fake_db),
        patch(
            "app.jobs.scheduler.expected_eod_trade_date",
            return_value=expected_tw,
        ) as expected,
        patch(
            "app.jobs.scheduler.should_enqueue_eod_reconcile",
            return_value=True,
        ) as should_enqueue,
        patch(
            "app.jobs.scheduler.enqueue_eod_coverage_reconcile",
            return_value=(fake_job, True),
        ) as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    expected.assert_called_once_with("TW", us_port=None)
    should_enqueue.assert_called_once()
    assert should_enqueue.call_args.kwargs["market"] == "TW"
    assert should_enqueue.call_args.kwargs["us_port"] is None
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["market"] == "TW"
    fake_db.close.assert_called_once()


def test_scheduler_does_not_enqueue_us_full_market_during_canary() -> None:
    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "US"),
        patch(
            "app.us_market.daily_rollout.us_daily_full_market_acquisition_enabled",
            return_value=False,
        ),
        patch("app.jobs.scheduler.SessionLocal") as session_local,
        patch("app.jobs.scheduler.enqueue_eod_coverage_reconcile") as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    session_local.assert_not_called()
    enqueue.assert_not_called()


def test_scheduler_enqueues_priority_us_ohlc_with_bounded_request() -> None:
    fake_db = Mock()
    fake_job = Mock(id=21)

    with (
        patch("app.jobs.scheduler.SessionLocal", return_value=fake_db),
        patch(
            "app.jobs.scheduler.list_active_cross_market_us_requirement_symbols",
            return_value=("TSM", "SMH"),
        ),
        patch(
            "app.jobs.scheduler.job_service.enqueue_job",
            return_value=(fake_job, True),
        ) as enqueue,
    ):
        scheduler.enqueue_us_priority_ohlc_reconcile()

    kwargs = enqueue.call_args.kwargs
    assert kwargs["job_type"] == "us_market.priority_ohlc_reconcile"
    assert kwargs["target"] == "priority-research"
    assert kwargs["request"]["max_runtime_seconds"] > 0
    assert kwargs["request"]["max_symbols"] > 0
    assert kwargs["request"]["max_external_calls"] > 0
    assert kwargs["request"]["max_provider_attempts"] == 2
    assert set(kwargs["request"]) == {
        "max_runtime_seconds",
        "max_symbols",
        "max_external_calls",
        "max_provider_attempts",
        "cursor_symbol",
        "required_symbols",
        "continuation_remaining_count",
        "expected_trade_date",
    }
    assert kwargs["request"]["required_symbols"] == ["TSM", "SMH"]
    fake_db.close.assert_called_once()


@pytest.mark.parametrize("elapsed,continuation,status,expected_calls", [
    (59, True, "success", 0),
    (60, True, "success", 1),
    (60, False, "success", 0),
    (60, True, "error", 0),
    (1800, False, "success", 1),
])
def test_priority_restart_resumes_only_due_successful_shard(
    elapsed, continuation, status, expected_calls,
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    ended = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)
    with factory() as db:
        db.add(JobRun(job_type=scheduler.US_PRIORITY_OHLC_RECONCILE_JOB_TYPE,
            status=status, target="priority-research", ended_at=ended,
            result_json=json.dumps({"expected_trade_date": "2026-09-28", "cursor_symbol": "AAPL",
                "continuation_required": continuation, "continuation_remaining_count": 7,
                "error_count": 0})))
        db.commit()
    try:
        with (
            patch.object(scheduler, "SessionLocal", factory),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_interval_minutes", 30),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_continuation_interval_seconds", 60),
            patch.object(scheduler, "list_active_cross_market_us_requirement_symbols", return_value=()),
            patch.object(scheduler.job_service, "enqueue_job", return_value=(Mock(id=2), True)) as enqueue,
        ):
            scheduler.enqueue_us_priority_ohlc_reconcile(now=ended + timedelta(seconds=elapsed))
        assert enqueue.call_count == expected_calls
        if expected_calls:
            request = enqueue.call_args.kwargs["request"]
            assert request["cursor_symbol"] == "AAPL"
            assert request["expected_trade_date"] == "2026-09-28"
            assert request["continuation_remaining_count"] == (7 if continuation else None)
            assert request["max_symbols"] == scheduler.settings.scheduler_us_priority_ohlc_max_symbols
            assert request["max_external_calls"] == scheduler.settings.scheduler_us_priority_ohlc_max_external_calls
    finally:
        engine.dispose()


def test_priority_new_completed_session_does_not_reuse_old_cursor_or_remaining():
    previous = Mock(status="success", ended_at=datetime(2026, 9, 29, 19, 59, tzinfo=timezone.utc),
        result_json=json.dumps({"expected_trade_date": "2026-09-25", "cursor_symbol": "XEL",
            "continuation_required": True, "continuation_remaining_count": 2, "error_count": 0}))
    db = Mock()
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = previous
    with (
        patch.object(scheduler, "SessionLocal", return_value=db),
        patch.object(scheduler, "list_active_cross_market_us_requirement_symbols", return_value=()),
        patch.object(scheduler.job_service, "enqueue_job", return_value=(Mock(id=2), True)) as enqueue,
    ):
        scheduler.enqueue_us_priority_ohlc_reconcile(now=datetime(2026, 9, 29, 21, tzinfo=timezone.utc))
    request = enqueue.call_args.kwargs["request"]
    assert request["expected_trade_date"] == "2026-09-29"
    assert request["cursor_symbol"] is None and request["continuation_remaining_count"] is None


def test_interrupted_priority_worker_retries_saved_shard_after_backoff():
    ended = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)
    interrupted = Mock(status="error", ended_at=ended, result_json=None,
        request_json=json.dumps({"expected_trade_date": "2026-09-28", "cursor_symbol": "AAPL",
                                "continuation_remaining_count": 7}))
    db = Mock()
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = interrupted
    with (
        patch.object(scheduler, "SessionLocal", return_value=db),
        patch.object(scheduler.settings, "scheduler_us_priority_ohlc_interval_minutes", 30),
        patch.object(scheduler, "list_active_cross_market_us_requirement_symbols", return_value=()),
        patch.object(scheduler.job_service, "enqueue_job", return_value=(Mock(id=2), True)) as enqueue,
    ):
        scheduler.enqueue_us_priority_ohlc_reconcile(now=ended + timedelta(seconds=60))
        enqueue.assert_not_called()
        scheduler.enqueue_us_priority_ohlc_reconcile(now=ended + timedelta(minutes=30))
    request = enqueue.call_args.kwargs["request"]
    assert request["cursor_symbol"] == "AAPL" and request["continuation_remaining_count"] == 7
    assert request["expected_trade_date"] == "2026-09-28"


def test_priority_us_ohlc_scheduler_staggers_startup_reconcile() -> None:
    fake_scheduler = Mock()
    now = datetime(2026, 8, 25, 0, 0, tzinfo=scheduler._timezone())

    with (
        patch.object(scheduler.settings, "enable_us_priority_ohlc_scheduler", True),
        patch.object(
            scheduler.settings,
            "scheduler_us_priority_ohlc_startup_delay_seconds",
            30,
        ),
        patch("app.jobs.scheduler.datetime", wraps=datetime) as datetime_mock,
    ):
        datetime_mock.now.return_value = now
        assert scheduler._add_us_priority_ohlc_reconcile_job(fake_scheduler) is True

    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["next_run_time"] == now + timedelta(seconds=30)


def test_scheduler_does_not_defer_full_market_for_cache_only_priority_audit() -> None:
    fake_db = Mock()
    fake_job = Mock(id=23)

    with (
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "US"),
        patch(
            "app.us_market.daily_rollout.us_daily_full_market_acquisition_enabled",
            return_value=True,
        ),
        patch("app.jobs.scheduler.SessionLocal", return_value=fake_db),
        patch("app.jobs.scheduler.should_enqueue_eod_reconcile", return_value=True),
        patch(
            "app.jobs.scheduler.enqueue_eod_coverage_reconcile",
            return_value=(fake_job, True),
        ) as enqueue,
    ):
        scheduler.enqueue_market_eod_coverage_reconcile()

    enqueue.assert_called_once()
    fake_db.close.assert_called_once()


def test_priority_us_ohlc_scheduler_is_fail_closed_by_default() -> None:
    fake_scheduler = Mock()

    with patch.object(
        scheduler.settings,
        "enable_us_priority_ohlc_scheduler",
        False,
    ):
        assert scheduler._add_us_priority_ohlc_reconcile_job(fake_scheduler) is False

    fake_scheduler.add_job.assert_not_called()


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


def test_progressing_partial_shard_is_not_a_failed_job():
    result = {"status": "partial", "postcondition_met": False,
              "continuation_required": True, "error_count": 0}
    completed = []
    def execute(_job_id, worker):
        completed.append(worker(object(), Mock()))
    with patch.object(eod_coverage, "reconcile_eod_coverage", return_value=result), patch.object(
        eod_coverage.job_service, "run_tracked_job", side_effect=execute
    ):
        eod_coverage.run_eod_coverage_reconcile_job(1, "US", True, None, 1, 30, 0, 5, 1800)
    assert completed == [result]
    assert completed[0]["postcondition_met"] is False
