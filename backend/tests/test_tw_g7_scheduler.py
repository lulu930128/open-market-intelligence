"""Real APScheduler state machine, fake time/execution; no running scheduler threads."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_SUBMITTED
from apscheduler.executors.base import BaseExecutor
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers import base as aps_base

from app.jobs import scheduler as owner
from app.market import indices, tw_current_market_operations, tw_current_market_platform


T0 = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
JOB = "taiwan_market_breadth_summary_collector"


class HeldExecutor(BaseExecutor):
    def __init__(self):
        super().__init__()
        self.submitted = []

    def _do_submit_job(self, job, run_times):
        self.submitted.append((job.id, run_times))


class ManualScheduler(BaseScheduler):
    def wakeup(self):
        pass

    def shutdown(self, wait=True):
        super().shutdown(wait)


@pytest.fixture
def scheduler_case(monkeypatch):
    created = []

    def make(interval):
        monkeypatch.setattr(owner.settings, "enable_taiwan_market_breadth_scheduler", True)
        monkeypatch.setattr(owner.settings, "enable_taiwan_market_index_scheduler", False)
        monkeypatch.setattr(owner.settings, "scheduler_taiwan_market_breadth_interval_seconds", interval)
        executor = HeldExecutor()
        scheduler = ManualScheduler(executors={"default": executor}, timezone=timezone.utc)
        assert owner._add_taiwan_market_index_collector_job(scheduler)
        for job in scheduler.get_jobs():
            if job.id != JOB:
                scheduler.remove_job(job.id)
        job = scheduler.get_job(JOB)
        assert job.func is owner.collect_taiwan_market_breadth_summary
        assert job.max_instances == 1 and job.coalesce is True
        assert job.trigger.interval.total_seconds() == max(interval, 30)
        job.modify(next_run_time=T0)
        events = []
        scheduler.add_listener(events.append, EVENT_JOB_MAX_INSTANCES | EVENT_JOB_SUBMITTED)
        scheduler.start()
        created.append(scheduler)

        def tick(seconds):
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return (T0 + timedelta(seconds=seconds)).astimezone(tz)
            monkeypatch.setattr(aps_base, "datetime", Clock)
            scheduler._process_jobs()

        return scheduler, executor, events, tick

    yield make
    for scheduler in created:
        scheduler.shutdown()


@pytest.mark.parametrize("interval,skipped", [(30, 1), (60, 0)])
def test_40_second_sequential_pair_skips_30_tick_but_not_60(scheduler_case, interval, skipped):
    scheduler, executor, events, tick = scheduler_case(interval)
    tick(0)
    tick(30)  # Pair is still executing; executor holds its one instance.
    executor._run_job_success(JOB, [])  # Pair finishes before next 60-second tick.
    tick(60)
    assert [times for _, times in executor.submitted] == [[T0], [T0 + timedelta(seconds=60)]]
    assert sum(e.code == EVENT_JOB_MAX_INSTANCES for e in events) == skipped
    assert scheduler.get_job(JOB).next_run_time == T0 + timedelta(seconds=60 + interval)


@pytest.mark.parametrize("interval,last_due", [(30, 90), (60, 60)])
def test_delayed_scheduler_wakeup_coalesces_due_times_without_overlap(scheduler_case, interval, last_due):
    _, executor, events, tick = scheduler_case(interval)
    tick(95)  # Scheduler itself was delayed; no job was previously submitted.
    assert executor.submitted == [(JOB, [T0 + timedelta(seconds=last_due)])]
    assert [e.code for e in events] == [EVENT_JOB_SUBMITTED]


def test_direct_collector_serializes_venues_then_persists(monkeypatch):
    phases = []

    class LockTrace:
        def __enter__(self):
            phases.append("summary_lock_enter")
        def __exit__(self, *args):
            phases.append("summary_lock_exit")

    db = SimpleNamespace(commit=lambda: phases.append("derived_commit"),
                         rollback=lambda: pytest.fail("unexpected rollback"),
                         close=lambda: phases.append("close"))
    monkeypatch.setattr(owner, "SessionLocal", lambda: db)
    monkeypatch.setattr(owner, "is_taiwan_index_live_refresh_window", lambda now: True)
    monkeypatch.setattr(indices, "_SUMMARY_REFRESH_LOCK", LockTrace())
    monkeypatch.setattr(tw_current_market_operations, "build_current_market_executors", lambda *a, **k: (None, object()))

    def acquire(*args, venue, **kwargs):
        phases.extend([f"{venue}_start", f"{venue}_finish"])
        return SimpleNamespace(limitations=[])

    monkeypatch.setattr(tw_current_market_platform, "refresh_taiwan_current_breadth", acquire)
    monkeypatch.setattr(indices, "_shared_current_market_summary", lambda *a, **k: {"warnings": []})
    monkeypatch.setattr(owner, "get_cached_current_breadth_stock_rows", lambda: [])
    monkeypatch.setattr(owner, "attach_current_market_lineage_to_stock_rows", lambda *a, **k: [])
    for name in ("persist_taiwan_market_minute_state", "persist_taiwan_intraday_stock_states"):
        monkeypatch.setattr(owner, name, lambda *a, **k: {})
    owner.collect_taiwan_market_breadth_summary()
    assert phases == ["summary_lock_enter", "TWSE_start", "TWSE_finish", "TPEX_start", "TPEX_finish", "summary_lock_exit", "derived_commit", "close"]
