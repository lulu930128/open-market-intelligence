"""Real managed-lane capacity, original-demand retry and SQLite CAS regression."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from threading import Barrier, Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from r1d_test_support import isolated_job_lifecycle  # noqa: F401
from app.db.models import Base, JobRun, StockMaster, TaiwanIntradaySchedulerState
from app.jobs import service as jobs
from app.jobs import taiwan_intraday_demand as demand
from app.jobs import taiwan_intraday_bar_scheduler as scheduler
from app.market.trading_calendar import TAIWAN_TZ

NOW = datetime(2026, 11, 2, 10, tzinfo=TAIWAN_TZ)


def wait_for(predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        sleep(0.005)
    assert predicate()


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'capacity.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine, tables=[StockMaster.__table__, JobRun.__table__, TaiwanIntradaySchedulerState.__table__])
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([StockMaster(stock_id=s, stock_name=s, market="TWSE", instrument_type="stock", is_active=True)
            for s in ("2330", "2409", "3481", "2317", "0050")])
        db.commit()
    clock = [NOW]
    ready = set()
    acquisitions = []
    def reread(db, request, now):
        satisfied = request["stock_id"] in ready
        return {"reread_ready": satisfied, "reread_trade_date": request["trade_date"],
            "current_session_bar_count": 60 if satisfied else 0,
            "target_covered_bucket_count": 60 if satisfied else 0, "target_expected_bucket_count": 60}
    def acquire(db, **kwargs):
        acquisitions.append(kwargs["stock_id"])
        ready.add(kwargs["stock_id"])
        return SimpleNamespace(acquisition=SimpleNamespace(status="completed", external_calls=1, limitations=()),
            persistence=SimpleNamespace(attempted=True, committed=True, observations_written=60))
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    monkeypatch.setattr(demand, "_now", lambda: clock[0])
    monkeypatch.setattr(demand, "_reread", reread)
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars", acquire)
    from app.ai import refresh_status
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)
    monkeypatch.setattr(refresh_status, "datetime", FrozenDateTime)
    releases = []
    def fill(lane):
        release, entered = Event(), Event()
        releases.append(release)
        def block(job_id):
            entered.set()
            assert release.wait(10)
        count = {"market_background": 2, "market_interactive": 8, "market_completed": 3}[lane]
        for n in range(count):
            jobs.submit_job_task(block, -n - 1, execution_lane=lane)
        assert entered.wait(2)
        return release
    yield SimpleNamespace(factory=factory, clock=clock, ready=ready, acquisitions=acquisitions, fill=fill)
    for release in releases:
        release.set()
    wait_for(lambda: not jobs._pending_tasks)
    engine.dispose()


def enqueue(env, *, stock_id="2330", consumer="scheduler", timeout=120, calls=2):
    with env.factory() as db:
        job, _ = demand.enqueue_intraday_materialization_demand(db, stock_id=stock_id,
            requested_at=env.clock[0], consumer=consumer, timeout_seconds=timeout, max_external_calls=calls,
            trade_date="2026-10-30" if consumer in {"completed_session", "completed_session_repair"} else None)
        return job.id


def queued(env, monkeypatch, **kwargs):
    with monkeypatch.context() as patch:
        patch.setattr(jobs, "submit_job_task", lambda *a, **kw: None)
        job_id = enqueue(env, **kwargs)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        job.status = "queued"
        db.commit()
    return job_id


@pytest.mark.parametrize("consumer,lane", [("scheduler", "market_background"),
    ("completed_session", "market_completed"), ("viewer", "market_interactive")])
def test_full_real_lane_defers_same_job_then_dispatches_once(env, consumer, lane):
    release = env.fill(lane)
    job_id = enqueue(env, consumer=consumer)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        original = job.request_json
        result = json.loads(job.result_json)
        assert job.status == "queued" and job.ended_at is None and job.error_message is None
        assert result["reason_code"] == "TW_INTRADAY_DEMAND_CAPACITY_WAIT"
        assert result["last_failure"]["error_type"] == "JobExecutionCapacityFull"
        assert result["last_failure"]["subphase"] == "queue_full"
        assert result["attempt_count"] == result["external_call_budget_used"] == result["external_call_count"] == 0
        assert demand.is_restart_handoff(job)
        from app.ai.refresh_status import read_refresh_status
        db.execute(text("PRAGMA query_only=ON"))
        try:
            public = read_refresh_status(db=db, job_id=job_id)
            assert public["status"] == "queued" and public["error"] is None
            assert public["next_retry_at"] == result["next_retry_at"]
            assert public["reason_code"] == "TW_INTRADAY_DEMAND_CAPACITY_WAIT"
        finally:
            db.execute(text("PRAGMA query_only=OFF"))
        assert demand.dispatch_due_materializations(db, requested_at=NOW + timedelta(seconds=14)) == 0
    assert not env.acquisitions
    release.set()
    wait_for(lambda: not jobs._pending_tasks)
    env.clock[0] += timedelta(seconds=15)
    with env.factory() as db:
        assert demand.dispatch_due_materializations(db, requested_at=env.clock[0]) == 1
    wait_for(lambda: not jobs._pending_tasks)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == "success" and job.request_json == original
        assert result["attempt_count"] == result["external_call_count"] == 1
        assert result["external_call_budget_used"] == 2
        assert db.query(JobRun).count() == 1
    assert env.acquisitions == ["2330"]


def test_repeated_capacity_wait_expires_without_io_or_budget_reset(env):
    env.fill("market_background")
    job_id = enqueue(env, timeout=32)
    for seconds in (15, 30):
        env.clock[0] = NOW + timedelta(seconds=seconds)
        with env.factory() as db:
            assert demand.dispatch_due_materializations(db, requested_at=env.clock[0]) == 0
            assert db.get(JobRun, job_id).status == "queued"
    env.clock[0] = NOW + timedelta(seconds=32)
    with env.factory() as db:
        assert demand.dispatch_due_materializations(db, requested_at=env.clock[0]) == 0
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == "error" and result["reason_code"] == "TW_INTRADAY_DEMAND_EXPIRED"
        assert result["attempt_count"] == result["external_call_budget_used"] == result["external_call_count"] == 0
        assert db.query(JobRun).count() == 1
    assert not env.acquisitions


def test_capacity_preserves_consumed_quota_provider_backoff_and_request(env, monkeypatch):
    job_id = queued(env, monkeypatch, calls=6)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        original = job.request_json
        result = json.loads(job.result_json)
        until = (NOW + timedelta(seconds=45)).isoformat()
        result.update(attempt_count=1, external_call_budget_used=2, external_call_count=1,
            bars_written_count=3, retry_not_before_at=until)
        job.result_json = json.dumps(result)
        db.commit()
    env.fill("market_background")
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert not demand._dispatch(db, job, NOW)
        result = json.loads(job.result_json)
        assert job.status == "queued" and job.request_json == original
        assert result["next_retry_at"] == result["retry_not_before_at"] == until
        assert result["attempt_count"] == 1 and result["external_call_budget_used"] == 2
        assert result["external_call_count"] == 1 and result["bars_written_count"] == 3
        assert not demand.dispatch_due_materializations(db, requested_at=NOW + timedelta(seconds=30))
    assert not env.acquisitions


def test_background_refusals_do_not_starve_independent_completed_lane(env, monkeypatch):
    for symbol in ("2330", "2409", "3481", "2317"):
        queued(env, monkeypatch, stock_id=symbol, consumer="completed_session_repair")
    completed = queued(env, monkeypatch, stock_id="0050", consumer="completed_session")
    env.fill("market_background")
    with env.factory() as db:
        assert demand.dispatch_due_materializations(db, requested_at=NOW, limit=1) == 1
    wait_for(lambda: env.acquisitions == ["0050"])
    with env.factory() as db:
        assert db.get(JobRun, completed).status == "success"
        assert db.query(JobRun).filter(JobRun.status == "queued").count() == 4


def test_two_scheduler_admissions_keep_refused_jobs_queued_without_sqlite_contention(env, monkeypatch):
    env.clock[0] = NOW.replace(hour=13, minute=26)
    env.fill("market_background")
    barrier = Barrier(2)
    original = scheduler._background_slots
    def slots(db):
        value = original(db)
        barrier.wait(timeout=5)
        return value
    monkeypatch.setattr(scheduler, "_background_slots", slots)
    def current():
        return scheduler.collect_taiwan_intraday_bars(now=env.clock[0], session_factory=env.factory,
            universe_resolver=lambda db: {"symbols": ["2330"]})
    def close_tail():
        return scheduler.reconcile_taiwan_intraday_close_tails(now=env.clock[0], session_factory=env.factory,
            universe_resolver=lambda db, **kw: {"symbols": ["2409"]})
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(current), pool.submit(close_tail)]
        results = [future.result(timeout=10) for future in futures]
    assert all(result["results"][0]["status"] == "queued" for result in results)
    with env.factory() as db:
        assert db.query(JobRun).filter(JobRun.status == "queued").count() == 2
        assert original(db) == 0
    assert not env.acquisitions


def test_two_connections_claim_one_rejected_dispatch_and_one_recovered_execution(env, monkeypatch):
    job_id = queued(env, monkeypatch)
    release = env.fill("market_background")
    submitted = []
    submit = jobs.submit_job_task
    def counted(*args, **kwargs):
        submitted.append(args[1])
        return submit(*args, **kwargs)
    monkeypatch.setattr(jobs, "submit_job_task", counted)
    def race():
        barrier = Barrier(2)
        def dispatch():
            with env.factory() as db:
                job = db.get(JobRun, job_id)
                barrier.wait(timeout=5)
                return demand._dispatch(db, job, env.clock[0])
        with ThreadPoolExecutor(2) as pool:
            return list(pool.map(lambda _: dispatch(), range(2)))
    assert race() == [False, False]
    assert submitted == [job_id]
    release.set()
    wait_for(lambda: not jobs._pending_tasks)
    env.clock[0] += timedelta(seconds=15)
    assert sum(race()) == 1
    wait_for(lambda: not jobs._pending_tasks)
    assert submitted == [job_id, job_id] and env.acquisitions == ["2330"]


def test_goal_merge_during_capacity_handoff_does_not_orphan_running_claim(env, monkeypatch):
    env.fill("market_background")
    handback = demand._requeue_unstarted
    def merge(db, job, **kwargs):
        with env.factory() as other:
            row = other.get(JobRun, job.id)
            request = json.loads(row.request_json)
            request["desired_coverage_end_at"] = (NOW + timedelta(minutes=1)).isoformat()
            row.request_json = json.dumps(request)
            other.commit()
        return handback(db, job, **kwargs)
    monkeypatch.setattr(demand, "_requeue_unstarted", merge)
    job_id = enqueue(env)
    with env.factory() as db:
        row = db.get(JobRun, job_id)
        assert row.status == "queued" and demand.is_restart_handoff(row)
        assert demand.materialization_request(row)["desired_coverage_end_at"] == (NOW + timedelta(minutes=1)).isoformat()
        assert demand.materialization_request(row)["expires_at"] == (NOW + timedelta(seconds=120)).isoformat()
    assert not env.acquisitions


def test_expired_stale_queued_reader_cannot_terminalize_another_running_claim(env, monkeypatch):
    job_id = queued(env, monkeypatch, timeout=20)
    with env.factory() as stale, env.factory() as owner:
        old = stale.get(JobRun, job_id)
        with monkeypatch.context() as patch:
            patch.setattr(jobs, "submit_job_task", lambda *a, **kw: None)
            assert demand._dispatch(owner, owner.get(JobRun, job_id), NOW)
        assert not demand._dispatch(stale, old, NOW + timedelta(seconds=21))
        owner.expire_all()
        assert owner.get(JobRun, job_id).status == "running"
