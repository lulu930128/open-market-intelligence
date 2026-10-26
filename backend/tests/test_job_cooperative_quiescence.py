"""Real JobService/Future/SQLite fixtures; no live backend or provider IO."""
import asyncio
import json
import time
from datetime import date
from threading import Event, Thread

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.models import Base, JobRun, BrokerBranchSnapshotQuality, BrokerBranchTradeDaily, StockMaster
from app.jobs import service, backfill_tasks, resumption
from app.jobs.cooperative import JobPaused, JobStopToken, checkpoint_after_transaction, current_job_stop
from app.market import broker_branch, broker_branch_market_refresh as market
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401
from test_owned_restart_preflight import restart_runtime  # noqa: F401


DAY = date(2026, 10, 16)
TASK = backfill_tasks.run_taiwan_broker_branch_market_refresh_job
ARGS = (DAY, 0.0, 2500, 7200)


def wait_idle():
    deadline = time.monotonic() + 5
    while service._pending_tasks or service._active_enqueues:
        assert time.monotonic() < deadline, service.observe_job_quiescence()
        time.sleep(.005)


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "jobs.sqlite").as_posix(), poolclass=NullPool)
    # sqlite3 legacy transaction mode otherwise commits every DDL statement.
    # Keep durable, independent databases without hundreds of schema fsyncs.
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN")
        Base.metadata.create_all(connection)

    def factory():
        # A different thread must acquire the fence even during Session creation.
        acquired = Event()
        def check():
            with service._executor_lock:
                acquired.set()
        thread = Thread(target=check)
        thread.start()
        thread.join(1)
        assert acquired.is_set(), "DB IO under JobService executor lock"
        return Session(engine)

    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    with Session(engine) as db:
        for stock_id in ("1101", "2330", "6488"):
            db.add(StockMaster(stock_id=stock_id, stock_name=stock_id, market="TWSE",
                               instrument_type="stock", is_active=True))
        db.commit()
    yield engine
    wait_idle()
    engine.dispose()


def make_job(engine, **kwargs):
    with Session(engine) as db:
        return service.create_job(db, job_type="fixture", **kwargs).id


def snapshot(engine, job_id):
    with Session(engine) as db:
        return service.serialize_job(service.get_job(db, job_id))


def provider_result(stock_id, *, empty=False):
    payload = {"data": {"更新日期": DAY.isoformat(), "股票代號": stock_id,
        "股票名稱": stock_id, "買超top15": [] if empty else [{
            "分點代號": "A001", "分點名稱": "fixture", "買張": "10", "賣張": "0",
            "買超排名": "1", "買超": "10"}], "賣超top15": []}}
    return broker_branch.BrokerBranchFetchResult("https://fixture.invalid", 200,
        "application/json", json.dumps(payload), payload)


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("stop_at", ["provider", "commit"])
def test_active_and_queued_pause_after_commit_and_resume(database, monkeypatch, empty, stop_at):
    entered, release = Event(), Event()
    fetched = []
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})

    def fetch(stock_id):
        fetched.append(stock_id)
        if stock_id == "1101" and stop_at == "provider":
            entered.set()
            assert release.wait(5)
        return provider_result(stock_id, empty=empty and stock_id == "1101")

    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)

    def before_commit(session):
        if (stop_at == "commit" and fetched == ["1101"] and not entered.is_set()
                and session.query(BrokerBranchSnapshotQuality).filter_by(stock_id="1101").count()):
            entered.set()
            assert release.wait(5)

    event.listen(Session, "before_commit", before_commit)
    first, second = make_job(database), make_job(database)
    service.submit_job_task(TASK, first, *ARGS)
    try:
        assert entered.wait(3)
        service.submit_job_task(TASK, second, *ARGS)
        lease = service.request_job_pause()
        assert service.request_job_pause() is lease
        assert not service.jobs_paused(lease)
        assert snapshot(database, first)["status"] == "running"
        assert snapshot(database, second)["status"] == "queued"
        with Session(database) as db:
            assert db.query(BrokerBranchSnapshotQuality).count() == 0
        assert fetched == ["1101"]
        assert service.observe_job_quiescence()["tasks"][0]["cooperation"] == "CHECKPOINT_CAPABLE"
    finally:
        release.set()
        wait_idle()
        event.remove(Session, "before_commit", before_commit)
    assert service.jobs_paused(lease)
    assert fetched == ["1101"]
    for job_id in (first, second):
        saved = snapshot(database, job_id)
        assert saved["status"] == "paused" and saved["public_status"] == "partial"
        assert resumption.RESUME_KEY not in saved["result"]
        assert saved["error_message"] is None and saved["ended_at"] is None
    assert snapshot(database, first)["progress_current"] == 1
    with Session(database) as db:
        quality = db.query(BrokerBranchSnapshotQuality).one()
        assert quality.fetch_status == ("empty" if empty else "success")
        assert service.mark_interrupted_jobs(db) == 0
    service.resume_jobs(lease)
    wait_idle()
    assert fetched == ["1101", "2330", "6488"]
    assert snapshot(database, first)["status"] == "success"
    assert snapshot(database, second)["status"] == "success"
    if empty:
        assert snapshot(database, second)["result"]["status"] == "partial"
        assert snapshot(database, second)["result"]["remaining_count"] == 1


def test_checkpoint_rejects_open_transaction(database):
    token = JobStopToken()
    token.requested.set()
    context = current_job_stop.set(token)
    try:
        with Session(database) as db:
            db.execute(text("SELECT 1"))
            with pytest.raises(RuntimeError, match="TRANSACTION_OPEN"):
                checkpoint_after_transaction(db, {"safe_point": "stock_transaction_complete"})
            db.rollback()
            with pytest.raises(JobPaused):
                checkpoint_after_transaction(db, {"safe_point": "stock_transaction_complete"})
    finally:
        current_job_stop.reset(context)


@pytest.mark.parametrize("lane", ["default", "market_background", "market_interactive", "market_completed"])
def test_every_lane_uses_fence_and_uncooperative_timeout_blocks(database, lane):
    entered, release = Event(), Event()
    def unknown(_):
        entered.set()
        assert release.wait(5)
    service.submit_job_task(unknown, make_job(database), execution_lane=lane)
    assert entered.wait(2)
    try:
        lease = service.request_job_pause()
        with pytest.raises(service.JobAdmissionClosed):
            service.submit_job_task(TASK, make_job(database), *ARGS, execution_lane=lane)
        evidence = service.observe_job_quiescence()
        assert evidence["tasks"][0]["cooperation"] == "UNCOOPERATIVE/UNKNOWN"
        assert evidence["tasks"][0]["stop_requested"]
        assert not service.jobs_paused(lease)
        service.resume_jobs(lease)
        assert not service.observe_job_quiescence()["tasks"][0]["stop_requested"]
        result = asyncio.run(service.drain_job_executor(deadline=time.monotonic() + .02))
        assert not result.drained
        with pytest.raises(service.JobAdmissionClosed):
            service.resume_jobs(lease)
    finally:
        release.set()
    wait_idle()


def test_finished_failed_pause_commit_allows_drain_and_keeps_original_job(database, monkeypatch):
    entered, release = Event(), Event()
    def active(_):
        entered.set()
        assert release.wait(5)
    service.submit_job_task(active, make_job(database))
    assert entered.wait(2)
    queued = make_job(database)
    service.submit_job_task(TASK, queued, *ARGS)
    def fail_pause(session):
        if any(isinstance(row, JobRun) and row.status == "paused" for row in session.dirty):
            raise RuntimeError("fixture commit failure")
    event.listen(Session, "before_commit", fail_pause)
    try:
        service.begin_job_drain()
        release.set()
        wait_idle()
        assert service.job_drain_status().drained
        assert service.job_drain_status().unresolved_enqueues == 1
        assert snapshot(database, queued)["status"] == "queued"
    finally:
        release.set()
        event.remove(Session, "before_commit", fail_pause)


def test_unsupported_queued_callable_never_executes_or_claims_pause(database):
    entered, release, forbidden = Event(), Event(), Event()
    def active(_):
        entered.set()
        assert release.wait(5)
    service.submit_job_task(active, make_job(database))
    assert entered.wait(2)
    queued = make_job(database)
    service.submit_job_task(lambda _: forbidden.set(), queued)
    service.begin_job_drain()
    release.set()
    wait_idle()
    assert not forbidden.is_set()
    assert service.job_drain_status().drained
    assert service.job_drain_status().unresolved_enqueues == 1
    assert snapshot(database, queued)["status"] == "queued"


@pytest.mark.parametrize("payload", [
    [], float("nan"), float("inf"), {"type": "tuple", "value": "bad"},
    {"type": "dict", "value": []}, {"type": "date", "value": 1},
    {"type": "tuple", "value": [], "extra": 1}, {"type": [], "value": []},
])
def test_decode_rejects_malformed_shape(payload):
    with pytest.raises(ValueError):
        resumption.decode(payload)


def test_unknown_resume_does_not_import_or_execute(database, monkeypatch):
    job_id = make_job(database)
    with Session(database) as db:
        job = service.get_job(db, job_id)
        job.status = "paused"
        job.result_json = json.dumps({resumption.RESUME_KEY: {"module": "os", "name": "system"}})
        db.commit()
        monkeypatch.setattr(resumption.importlib, "import_module",
                            lambda _: pytest.fail("untrusted module imported"))
        with pytest.raises(ValueError, match="DESCRIPTOR_INVALID"):
            service.recover_paused_jobs(db)
    assert not service._pending_tasks
    assert snapshot(database, job_id)["status"] == "paused"


def test_valid_shape_cannot_import_untrusted_module(monkeypatch):
    descriptor = dict(module="os", name="run_system", args=resumption.encode(()), lane="default",
                      previous_status="queued", previous_result=None,
                      checkpoint={"safe_point": "not_started"})
    monkeypatch.setattr(resumption.importlib, "import_module",
                        lambda _: pytest.fail("untrusted module imported"))
    with pytest.raises(ValueError, match="TASK_UNSUPPORTED"):
        resumption.validate(descriptor)


def test_typed_arguments_roundtrip_and_running_unsupported_checkpoint_rejected():
    args = (DAY, 0.5, ["2330"], {"force": False, "optional": None}, (1, 2))
    assert resumption.decode(resumption.encode(args)) == args
    descriptor = resumption.describe(backfill_tasks.run_market_index_summary_refresh_job, (), "default")
    descriptor.update(previous_status="running", previous_result=None,
                      checkpoint={"safe_point": "stock_transaction_complete"})
    with pytest.raises(ValueError, match="CHECKPOINT_UNSUPPORTED"):
        resumption.validate(descriptor)


def test_immediate_callback_rearm_does_not_lose_reserved_continuation(monkeypatch):
    with pytest.raises(service.JobAdmissionClosed):
        service.resume_jobs(None)
    descriptor = resumption.describe(backfill_tasks.run_market_index_summary_refresh_job, (), "default")
    descriptor.update(previous_status="queued", previous_result=None,
                      checkpoint={"safe_point": "not_started"})
    service._paused_tasks[1] = descriptor
    calls = []
    def submit(task, job_id, *args, **kwargs):
        calls.append(job_id)
        if len(calls) == 1:
            # Immediate callback finished a second pause after its lease rearmed,
            # before the original submit returned and released its reservation.
            service._paused_tasks[job_id] = descriptor
            service._resume_ready_tasks()
    monkeypatch.setattr(service, "submit_job_task", submit)
    service._resume_ready_tasks()
    assert calls == [1, 1]
    assert not service._paused_tasks and not service._resuming_jobs and not service._active_enqueues


def test_other_managed_task_queue_resumes_once_without_replaying_started_work(database, monkeypatch):
    entered, release = Event(), Event()
    calls = []
    def active(_):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(backfill_tasks, "refresh_market_index_summary",
                        lambda **_: calls.append("fetch") or {"indices": []})
    monkeypatch.setattr(backfill_tasks, "persist_taiwan_market_minute_state", lambda *_, **__: {})
    service.submit_job_task(active, make_job(database))
    assert entered.wait(2)
    queued = make_job(database)
    service.submit_job_task(backfill_tasks.run_market_index_summary_refresh_job, queued)
    lease = service.request_job_pause()
    release.set()
    wait_idle()
    assert calls == [] and snapshot(database, queued)["status"] == "paused"
    service.resume_jobs(lease)
    wait_idle()
    assert calls == ["fetch"] and snapshot(database, queued)["status"] == "success"
    with Session(database) as db:
        assert service.recover_paused_jobs(db) == 0
    assert calls == ["fetch"]


def test_rearm_during_pause_commit_resumes_only_after_callback_exit(database, monkeypatch):
    entered, release, pausing, persist_release = Event(), Event(), Event(), Event()
    calls = []
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        calls.append(stock_id)
        if stock_id == "1101":
            entered.set()
            assert release.wait(5)
        return provider_result(stock_id)
    def before_commit(db):
        if any(isinstance(row, JobRun) and row.status == "paused" for row in db.dirty):
            pausing.set()
            assert persist_release.wait(5)
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    event.listen(Session, "before_commit", before_commit)
    job_id = make_job(database)
    service.submit_job_task(TASK, job_id, *ARGS)
    try:
        assert entered.wait(3)
        lease = service.request_job_pause()
        release.set()
        assert pausing.wait(3)
        assert not service.jobs_paused(lease)
        assert snapshot(database, job_id)["status"] == "running"
        service.resume_jobs(lease)
        assert calls == ["1101"]
    finally:
        release.set()
        persist_release.set()
        wait_idle()
        event.remove(Session, "before_commit", before_commit)
    assert calls == ["1101", "2330", "6488"]
    assert snapshot(database, job_id)["status"] == "success"


def test_stock_rollback_is_not_saved_completion_and_is_retried_on_resume(database, monkeypatch):
    entered, release = Event(), Event()
    fetched, failed = [], []
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        if len(fetched) == 1:
            entered.set()
            assert release.wait(5)
        return provider_result(stock_id)
    def before_commit(db):
        if (fetched == ["1101"] and not failed
                and db.query(BrokerBranchSnapshotQuality).filter_by(stock_id="1101").count()):
            failed.append(True)
            raise RuntimeError("fixture stock commit failed")
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    event.listen(Session, "before_commit", before_commit)
    job_id = make_job(database)
    service.submit_job_task(TASK, job_id, *ARGS)
    try:
        assert entered.wait(3)
        lease = service.request_job_pause()
    finally:
        release.set()
        wait_idle()
        event.remove(Session, "before_commit", before_commit)
    assert failed and snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        assert db.query(BrokerBranchSnapshotQuality).count() == 0
        assert db.query(BrokerBranchTradeDaily).count() == 0
    service.resume_jobs(lease)
    wait_idle()
    assert fetched == ["1101", "1101", "2330", "6488"]
    assert snapshot(database, job_id)["status"] == "success"


def test_durable_paused_status_is_not_ack_until_session_and_future_exit(database, monkeypatch):
    entered, release, closing, close_release = Event(), Event(), Event(), Event()
    original_factory = service.SessionLocal
    def factory():
        db = original_factory()
        original_close = db.close
        def close():
            if any(isinstance(row, JobRun) and row.status == "paused" for row in db.identity_map.values()):
                closing.set()
                assert close_release.wait(5)
            original_close()
        db.close = close
        return db
    monkeypatch.setattr(service, "SessionLocal", factory)
    def active(_):
        entered.set()
        assert release.wait(5)
    service.submit_job_task(active, make_job(database))
    assert entered.wait(2)
    queued = make_job(database)
    service.submit_job_task(TASK, queued, *ARGS)
    lease = service.request_job_pause()
    release.set()
    try:
        assert closing.wait(3)
        assert snapshot(database, queued)["status"] == "paused"
        assert not service.jobs_paused(lease)
        assert service.observe_job_quiescence()["unfinished_future_count"] == 1
    finally:
        close_release.set()
    wait_idle()
    assert service.jobs_paused(lease)


def test_enqueue_commit_pause_race_leaves_recoverable_record(database, monkeypatch):
    original = service.create_job
    def commit_then_pause(*args, **kwargs):
        job = original(*args, **kwargs)
        service.request_job_pause()
        return job
    monkeypatch.setattr(service, "create_job", commit_then_pause)
    with Session(database) as db:
        job, created = service.enqueue_job(db, job_type="fixture", task=TASK, task_args=ARGS)
        assert created and job.status == "paused"
        assert job.error_message is None
    assert service.jobs_paused(service._admission_pause)


def test_new_python_process_recovers_active_and_queued_obligations(database, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path

    entered, release = Event(), Event()
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        assert stock_id == "1101"
        entered.set()
        assert release.wait(5)
        return provider_result(stock_id, empty=True)
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    first, second = make_job(database), make_job(database)
    service.submit_job_task(TASK, first, *ARGS)
    try:
        assert entered.wait(3)
        service.submit_job_task(TASK, second, *ARGS)
        service.begin_job_drain()
    finally:
        release.set()
    wait_idle()
    assert service.job_drain_status().drained
    # This child owns only the disposable fixture DB, never the live runtime.
    child = '''
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path('backend/tests').resolve()))
import g3_offline_guard
g3_offline_guard.install()
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_job_cooperative_quiescence import service, market, broker_branch, provider_result, DAY, wait_idle
engine = create_engine(sys.argv[1], poolclass=NullPool)
service.SessionLocal = lambda: Session(engine)
service.settings.job_worker_max_concurrency = 1
market.probe_broker_branch_release = lambda _: {'trade_date': DAY}
fetched = []
def fetch(stock_id):
    fetched.append(stock_id)
    return provider_result(stock_id)
broker_branch._fetch_nstock_branch_top15 = fetch
with Session(engine) as db:
    assert service.mark_interrupted_jobs(db) == 0
    assert service.recover_paused_jobs(db) == 2
wait_idle()
with Session(engine) as db:
    assert all(job.status == 'success' for job in db.query(service.JobRun).all())
assert fetched == ['2330', '6488'], fetched
service.shutdown_job_executor(wait=True)
engine.dispose()
print(json.dumps({'fetched': fetched, 'recovered': 2}))
'''
    result = subprocess.run([sys.executable, "-B", "-c", child, str(database.url)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip())["recovered"] == 2
    assert snapshot(database, first)["status"] == "success"
    assert snapshot(database, second)["status"] == "success"


@pytest.mark.parametrize("origin", ["committed_enqueue", "running_exception"])
def test_unknown_durable_job_survives_drain_and_new_process_marks_interrupted(
    database, monkeypatch, origin,
):
    """Execution closure never claims durable success or authorizes queue replay."""
    import subprocess
    import sys
    from pathlib import Path

    if origin == "committed_enqueue":
        create = service.create_job
        def committed_without_response(*args, **kwargs):
            create(*args, **kwargs)
            raise RuntimeError("fixture response lost after durable INSERT")
        monkeypatch.setattr(service, "create_job", committed_without_response)
        with Session(database) as db:
            with pytest.raises(RuntimeError, match="response lost"):
                service.enqueue_job(db, job_type="fixture", request={"retained": origin},
                                    task=lambda _: pytest.fail("Unknown enqueue must not execute"))
            job_id = db.query(JobRun).one().id
        expected = "queued"
    else:
        job_id = make_job(database, request={"retained": origin})
        def escaping_task(job_id):
            with Session(database) as db:
                service.start_job(db, job_id)
            raise RuntimeError("fixture running task outcome unknown")
        service.submit_job_task(escaping_task, job_id)
        wait_idle()
        expected = "running"
    before = snapshot(database, job_id)
    assert before["status"] == expected
    service.begin_job_drain()
    assert service.job_drain_status().drained
    assert service.job_drain_status().unresolved_enqueues == 1
    assert snapshot(database, job_id) == before
    # Read/status cannot reconcile, query, or submit. The explicit startup owner
    # below alone changes the durable disposition, in a disposable new process.
    with monkeypatch.context() as read_only:
        read_only.setattr(service, "SessionLocal", lambda: pytest.fail("Status queried DB"))
        assert service.observe_job_quiescence()["reconciliation_required"]
        assert service.job_drain_status().unresolved_enqueues == 1
    child = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path('backend/tests').resolve()))
import g3_offline_guard
g3_offline_guard.install()
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from app import runtime as module
from app.jobs import service
engine = create_engine(sys.argv[1], poolclass=NullPool)
module.SessionLocal = lambda: Session(engine)
def forbidden(*args, **kwargs):
    raise AssertionError('Unknown durable job must not be replayed')
service.submit_job_task = forbidden
with Session(engine) as db:
    job = db.query(service.JobRun).one()
    before = (job.id, job.request_json, job.result_json, job.created_at, job.started_at)
    assert job.status == sys.argv[2]
runtime = module.RuntimeCoordinator()
runtime._mark_interrupted_jobs()
with Session(engine) as db:
    job = db.query(service.JobRun).one()
    assert (job.id, job.request_json, job.result_json, job.created_at, job.started_at) == before
    assert job.status == 'error'
    assert job.error_message == 'Job interrupted by application restart.'
    assert job.ended_at is not None
    ended_at = job.ended_at
    assert service.read_paused_job_obligations(db) == {}
runtime._mark_interrupted_jobs()
with Session(engine) as db:
    assert db.query(service.JobRun).one().ended_at == ended_at
assert not service._pending_tasks
engine.dispose()
'''
    result = subprocess.run([sys.executable, "-B", "-c", child, str(database.url), expected],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(database, job_id)["status"] == "error"
    assert service.job_drain_status().unresolved_enqueues == 1


def test_interrupted_cleanup_commit_failure_preserves_original_obligation(database, monkeypatch):
    from app import runtime as module
    job_id = make_job(database, request={"retained": "unknown"})
    before = snapshot(database, job_id)
    monkeypatch.setattr(module, "SessionLocal", lambda: Session(database))
    def fail_commit(session):
        raise RuntimeError("fixture interrupted cleanup commit failed")
    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="cleanup commit failed"):
            module.RuntimeCoordinator()._mark_interrupted_jobs()
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert snapshot(database, job_id) == before


def test_real_prepare_waits_for_job_checkpoint_and_rearms_without_stop(restart_runtime, monkeypatch):
    runtime, _, engine, _ = restart_runtime
    Base.metadata.create_all(engine)
    monkeypatch.setattr(service, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    with Session(engine) as db:
        db.add(StockMaster(stock_id="1101", stock_name="fixture", market="TWSE",
                           instrument_type="stock", is_active=True))
        db.commit()
    entered, release = Event(), Event()
    def fetch(stock_id):
        entered.set()
        assert release.wait(5)
        return provider_result(stock_id)
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    first, second = make_job(engine), make_job(engine)
    service.submit_job_task(TASK, first, *ARGS)
    assert entered.wait(3)
    service.submit_job_task(TASK, second, *ARGS)

    async def scenario():
        preparing = asyncio.create_task(runtime.prepare_owned_restart(timeout_seconds=3))
        while service._admission_pause is None:
            await asyncio.sleep(.005)
        assert not preparing.done()
        assert service.observe_job_quiescence()["unfinished_future_count"] == 2
        release.set()
        prepared = await preparing
        assert prepared["state"] == "WRITERS_PREPARED"
        assert service.jobs_paused(service._admission_pause)
        assert runtime._stop_task is None and runtime._restart_guard.held
        assert runtime.abort_owned_restart()
        assert runtime.owned_restart_rearmed()
        deadline = time.monotonic() + 3
        while service._pending_tasks or service._active_enqueues:
            assert time.monotonic() < deadline
            await asyncio.sleep(.005)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert snapshot(engine, first)["status"] == "success"
    assert snapshot(engine, second)["status"] == "success"


@pytest.mark.parametrize("collector_failure", [False, True])
def test_runtime_startup_validates_first_dispatches_only_after_components_ready(
    database, monkeypatch, collector_failure,
):
    from unittest.mock import Mock, AsyncMock
    from app import runtime as module
    from test_runtime import scheduler_receipt

    job_id = make_job(database)
    task = backfill_tasks.run_market_index_summary_refresh_job
    service._persist_job_pause(job_id, task, (), "default", {"safe_point": "not_started"})
    service._paused_tasks.clear()  # New-process fixture: only durable state survives.
    before = snapshot(database, job_id)
    with Session(database) as db:
        assert job_id in service.read_paused_job_obligations(db)
    assert not service._pending_tasks and not service._paused_tasks
    assert snapshot(database, job_id) == before

    order, provider_calls = [], []
    monkeypatch.setattr(module, "SessionLocal", lambda: Session(database))
    monkeypatch.setattr(module, "run_database_migrations", lambda: order.append("migration"))
    monkeypatch.setattr(module.job_scheduler, "start_scheduler", lambda: order.append("scheduler") or Mock())
    monkeypatch.setattr(module.job_scheduler, "stop_scheduler", lambda _: scheduler_receipt())
    async def auto():
        order.append("auto")
    async def collectors():
        order.append("collectors")
        if collector_failure:
            raise RuntimeError("fixture collector startup failure")
    async def fugle():
        order.append("fugle")
    monkeypatch.setattr(module, "start_crypto_auto_refresh", auto)
    monkeypatch.setattr(module, "start_crypto_realtime_collectors", collectors)
    monkeypatch.setattr(module, "start_fugle_realtime", fugle)
    for name in ("stop_crypto_auto_refresh", "stop_crypto_realtime_collectors", "stop_fugle_realtime"):
        monkeypatch.setattr(module, name, AsyncMock())
    monkeypatch.setattr(backfill_tasks, "refresh_market_index_summary",
                        lambda **_: provider_calls.append("fetch") or {"indices": []})
    monkeypatch.setattr(backfill_tasks, "persist_taiwan_market_minute_state", lambda *_, **__: {})
    runtime = module.RuntimeCoordinator(schema_lock=Mock(acquire=Mock(return_value=True)),
                                        background_lock=Mock(acquire=Mock(return_value=True)))
    monkeypatch.setattr(runtime, "_reconcile_dispatch_runs", lambda: order.append("reconcile"))
    monkeypatch.setattr(runtime, "_enqueue_stock_master_bootstrap", lambda: order.append("bootstrap"))
    original_resume = service.resume_job_obligations
    def resume(obligations):
        assert runtime.started and runtime.background_leader
        assert order == ["migration", "reconcile", "scheduler", "auto", "collectors", "fugle", "bootstrap"]
        order.append("resume")
        return original_resume(obligations)
    monkeypatch.setattr(service, "resume_job_obligations", resume)
    if collector_failure:
        with pytest.raises(RuntimeError, match="collector startup failure"):
            asyncio.run(runtime.start())
        assert "resume" not in order and not provider_calls and not service._pending_tasks
        assert snapshot(database, job_id) == before
        assert runtime.drain_result.state == "REGISTERED_DRAINED"
    else:
        asyncio.run(runtime.start())
        wait_idle()
        assert order[-1] == "resume" and provider_calls == ["fetch"]
        assert snapshot(database, job_id)["status"] == "success"
        asyncio.run(runtime.stop())
