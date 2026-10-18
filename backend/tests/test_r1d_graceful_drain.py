"""R1D source-only fixtures. Run through g3_offline_guard.py, never a live app."""
import asyncio
import base64
import json
from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs import service, scheduler
from app.runtime import RuntimeCoordinator, RuntimeDrainError


from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


def run(coro):
    return asyncio.run(coro)


async def eventually(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.002)


@pytest.mark.parametrize("lane", ["default", "market_interactive", "market_background", "market_completed"])
def test_future_deadline_and_late_submit_no_resurrection(lane):
    entered, release = Event(), Event()
    def work(_):
        entered.set()
        assert release.wait(3)
    service.submit_job_task(work, 1, execution_lane=lane)
    assert entered.wait(2)
    try:
        async def scenario():
            result = await service.drain_job_executor(deadline=time.monotonic() + 0.02)
            assert not result.drained and result.pending_by_lane == {lane: 1}
            for target in (lane, "default"):
                with pytest.raises(service.JobAdmissionClosed):
                    service.submit_job_task(work, 2, execution_lane=target)
            with pytest.raises(service.JobAdmissionClosed):
                service._get_executor()
        run(scenario())
    finally:
        release.set()
    assert run(service.drain_job_executor(deadline=time.monotonic() + 2)).drained
    assert run(service.drain_job_executor(deadline=time.monotonic() + 2)).drained
    with pytest.raises(service.JobAdmissionClosed):
        service._get_executor()


def test_submit_fence_is_atomic_with_registration(monkeypatch):
    entered, release = Event(), Event()
    future = Future()
    class Executor:
        def submit(self, *_):
            entered.set()
            assert release.wait(3)
            return future
        def shutdown(self, **_):
            pass
    monkeypatch.setattr(service, "_executor", Executor())
    submit = Thread(target=service.submit_job_task, args=(lambda _: None, 1))
    fence = Thread(target=service.begin_job_drain)
    submit.start()
    assert entered.wait(2)
    fence.start()
    try:
        assert not service._admission_closed
    finally:
        release.set()
        submit.join(2)
        fence.join(2)
    assert service.job_drain_status().pending_by_lane == {"default": 1}
    future.set_result(None)
    assert service.job_drain_status().drained


@pytest.mark.parametrize("outcome", ["success", "exception", "cancelled", "submit_failure"])
def test_immediate_callback_and_slot_recovery(monkeypatch, outcome):
    future = Future()
    if outcome == "exception":
        future.set_exception(ValueError("fixture"))
    elif outcome == "cancelled":
        future.cancel()
    else:
        future.set_result(None)
    executor = Mock()
    executor.submit.side_effect = RuntimeError("submit failed") if outcome == "submit_failure" else None
    executor.submit.return_value = future
    monkeypatch.setattr(service, "_materialization_executors", {"market_background": executor})
    if outcome == "submit_failure":
        with pytest.raises(RuntimeError, match="submit failed"):
            service.submit_job_task(lambda _: None, 1, execution_lane="market_background")
    else:
        service.submit_job_task(lambda _: None, 1, execution_lane="market_background")
    assert not service._pending_tasks
    slots = service._materialization_slots["market_background"]
    assert slots.acquire(False) and slots.acquire(False)
    assert not slots.acquire(False)
    slots.release()
    slots.release()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    service.JobRun.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_closed_enqueue_does_not_touch_database(db, monkeypatch):
    service.begin_job_drain()
    monkeypatch.setattr(service, "create_job", Mock(side_effect=AssertionError("DB touched")))
    with pytest.raises(service.JobAdmissionClosed):
        service.enqueue_job(db, job_type="fixture", task=lambda _: None)
    assert db.query(service.JobRun).count() == 0


@pytest.mark.parametrize("compensation_failure", [False, True])
def test_commit_submit_race_has_terminal_record_or_truthful_unresolved(db, monkeypatch, compensation_failure):
    original = service.create_job
    def create_then_fence(*args, **kwargs):
        job = original(*args, **kwargs)
        service.begin_job_drain()
        assert service.job_drain_status().active_enqueues == 1
        return job
    monkeypatch.setattr(service, "create_job", create_then_fence)
    if compensation_failure:
        monkeypatch.setattr(service, "fail_job", Mock(side_effect=RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            service.enqueue_job(db, job_type="fixture", task=lambda _: None)
        assert service.job_drain_status().unresolved_enqueues == 1
        assert not run(service.drain_job_executor(deadline=time.monotonic())).drained
    else:
        job, created = service.enqueue_job(db, job_type="fixture", task=lambda _: None)
        assert created and job.status == "error"
        assert "JOB_ADMISSION_CLOSED" in job.error_message
        assert service.job_drain_status().drained
    assert service.job_drain_status().active_enqueues == 0
    assert not service._pending_tasks


def test_job_quiescence_observation_preserves_pending_and_failure_state(monkeypatch):
    """Memory-only evidence cannot dismiss a recorded uncertain enqueue."""
    running, complete = Future(), Future()
    running.set_running_or_notify_cancel()
    complete.set_result(None)
    monkeypatch.setattr(service.time, "monotonic", lambda: 20.0)
    with service._executor_lock:
        service._pending_tasks[running] = service.PendingJobTask("market_background", 1, "work", 10.0, 12.0)
        service._pending_tasks[complete] = service.PendingJobTask("market_completed", 2, "work", 10.0, 11.0, 13.0)
    monkeypatch.setattr(service, "_active_enqueues", 1)
    monkeypatch.setattr(service, "_enqueue_failures", 1)
    monkeypatch.setattr(service, "_task_failures", 2)
    try:
        before = dict(service._pending_tasks)
        observed = service.observe_job_quiescence()
        assert observed == {
            "reason": "UNRESOLVED_ENQUEUE",
            "admission_closed": False,
            "admission_paused": False,
            "pending_by_lane": {"market_background": 1, "market_completed": 1},
            "completed_pending_by_lane": {"market_completed": 1},
            "cancelled_pending_by_lane": {},
            "active_enqueues": 1,
            "unresolved_enqueues": 1,
            "task_failures": 2,
            "unfinished_future_count": 1,
            "completed_pending_count": 1,
            "tasks": [
                {"job_id": 1, "task_name": "work", "execution_lane": "market_background",
                 "state": "running", "queue_wait_seconds": 2.0, "execution_seconds": 8.0},
                {"job_id": 2, "task_name": "work", "execution_lane": "market_completed",
                 "state": "done", "queue_wait_seconds": 1.0, "execution_seconds": 2.0},
            ],
            "tasks_omitted": 0,
            "default_executor_max_workers": None,
        }
        assert dict(service._pending_tasks) == before
        assert service.pause_jobs_if_idle() is None
        # Even if all active futures have exited, a sticky uncertain enqueue
        # is still a blocker. Never reset it to claim restart safety.
        with service._executor_lock:
            service._pending_tasks.clear()
        monkeypatch.setattr(service, "_active_enqueues", 0)
        assert service.observe_job_quiescence()["reason"] == "UNRESOLVED_ENQUEUE"
        assert service.pause_jobs_if_idle() is None
        assert service._enqueue_failures == 1
    finally:
        with service._executor_lock:
            service._pending_tasks.clear()


def test_single_default_worker_reports_bounded_queue_without_payload(monkeypatch):
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    entered, release = Event(), Event()
    completed = []

    def radar_work(job_id, payload):
        entered.set()
        assert release.wait(3)
        completed.append(job_id)

    def other_work(job_id, payload):
        completed.append(job_id)

    service.submit_job_task(radar_work, 100, "secret-payload")
    assert entered.wait(2)
    try:
        for job_id in range(101, 116):
            service.submit_job_task(other_work, job_id, {"token": "secret-payload"})
        observed = service.observe_job_quiescence()
        assert observed["default_executor_max_workers"] == 1
        assert observed["unfinished_future_count"] == 16
        assert observed["pending_by_lane"] == {"default": 16}
        assert observed["tasks_omitted"] == 4
        assert len(observed["tasks"]) == service.PENDING_TASK_DIAGNOSTIC_LIMIT
        assert observed["tasks"][0]["state"] == "running"
        assert observed["tasks"][0]["task_name"] == "radar_work"
        assert observed["tasks"][0]["execution_seconds"] >= 0
        assert all(row["state"] == "queued" and row["execution_seconds"] is None
                   for row in observed["tasks"][1:])
        assert "secret-payload" not in repr(observed) and "token" not in repr(observed)
        assert completed == []
        assert service.pause_jobs_if_idle() is None
    finally:
        release.set()
    assert run(service.drain_job_executor(deadline=time.monotonic() + 2)).drained
    assert completed == list(range(100, 116))


def test_async_legacy_wait_is_rejected():
    async def scenario():
        with pytest.raises(RuntimeError, match="async drain"):
            service.shutdown_job_executor(wait=True)
    run(scenario())


@pytest.mark.parametrize("status", ["partial_success", "error", "success"])
def test_scheduled_radar_jobrun_public_status_preserves_result(db, monkeypatch, status):
    from app.jobs import backfill_tasks
    from app.watchlists.radar_outcome_v2_service import RadarOutcomeWorkSlice

    job = service.create_job(db, job_type="watchlist.radar_v2.outcome_reconcile", progress_total=2)
    job_id = job.id
    monkeypatch.setattr(service, "SessionLocal", lambda: db)

    def reconcile(**kwargs):
        assert isinstance(kwargs["work_slice"], RadarOutcomeWorkSlice)
        assert kwargs["work_slice"].budget_seconds == 5.0
        kwargs["progress_callback"](0, 2, "Durable remainder")
        return {"status": status, "message": "Durable remainder", "remaining_due_count": 3,
                "initialization_pending_count": 2}

    monkeypatch.setattr(backfill_tasks, "reconcile_watchlist_radar_v2_outcomes", reconcile)
    backfill_tasks.run_watchlist_radar_outcome_reconcile_job(job_id, [7], "action", 200, 200, None)
    saved = service.get_job(db, job_id)
    for include_payload in (True, False):
        public = service.serialize_job(saved, include_payload=include_payload)
        assert public["public_status"] == {"partial_success": "partial", "error": "failed", "success": "completed"}[status]
        assert public["result"]["remaining_due_count"] == 3
        assert public["result"]["initialization_pending_count"] == 2
    if status == "partial_success":
        assert saved.status == "success"  # Existing JobRun execution enum.
        assert saved.progress_current == 0 and saved.progress_total == 2
        assert saved.message == "Durable remainder"


def test_scheduler_join_is_observed_not_assumed():
    release, entered = Event(), Event()
    events = []
    class Scheduler:
        def pause(self): events.append("pause")
        def shutdown(self, *, wait):
            assert wait
            events.append("join")
            entered.set()
            assert release.wait(3)
    owner = Scheduler()
    receipt = scheduler.stop_scheduler(owner)
    try:
        assert entered.wait(2) and receipt.admission_stopped.is_set()
        assert scheduler.stop_scheduler(owner) is receipt
        assert not receipt.completion.done()
    finally:
        release.set()
    receipt.completion.result(2)
    assert events == ["pause", "join"]


@pytest.mark.parametrize("phase", ["pause", "shutdown"])
def test_scheduler_exception_receipt(phase):
    owner = SimpleNamespace(pause=Mock(), shutdown=Mock())
    getattr(owner, phase).side_effect = RuntimeError("fixture")
    receipt = scheduler.stop_scheduler(owner)
    with pytest.raises(RuntimeError, match="fixture"):
        receipt.completion.result(2)
    assert receipt.admission_stopped.is_set() == (phase == "shutdown")


def test_actual_apscheduler_executor_join_tracks_direct_job():
    from apscheduler.schedulers.background import BackgroundScheduler
    entered, release = Event(), Event()
    owner = BackgroundScheduler(timezone="UTC")
    def work():
        entered.set()
        assert release.wait(3)
    owner.add_job(work)
    owner.start()
    try:
        assert entered.wait(2)
        receipt = scheduler.stop_scheduler(owner)
        assert receipt.admission_stopped.wait(2)
        assert not receipt.completion.done()
    finally:
        release.set()
    receipt.completion.result(2)


def runtime_fixture(stack, *, leader=True, failure=None):
    import app.runtime as runtime
    lock = Mock()
    coord = RuntimeCoordinator(schema_lock=Mock(), background_lock=lock)
    coord.background_leader = leader
    coord.started = True
    coord.scheduler = None
    for name in ("stop_fugle_realtime", "stop_crypto_realtime_collectors", "stop_crypto_auto_refresh"):
        stop = Mock(side_effect=RuntimeError("init")) if failure == name + "_init" else AsyncMock(
            side_effect=RuntimeError("stop") if failure == name else None,
        )
        stack.enter_context(patch.object(runtime, name, stop))
    return coord, lock


@pytest.mark.parametrize("leader", [False, True])
def test_runtime_success_idempotency_terminal_no_process_claim(leader):
    async def scenario():
        with ExitStack() as stack:
            coord, lock = runtime_fixture(stack, leader=leader)
            first, second = await asyncio.gather(coord.stop(), coord.stop())
            assert first is second and first.state == "REGISTERED_DRAINED"
            assert not first.all_writers_drained and first.unknown_writers
            assert first.background_ownership_retained == leader
            assert first.scheduler_state == ("drained" if leader else "not_owned")
            assert first.scheduler_admission_stopped is (True if leader else None)
            lock.release.assert_not_called()
            with pytest.raises(RuntimeError, match="terminal"):
                await coord.start()
    run(scenario())


@pytest.mark.parametrize("failure", ["stop_fugle_realtime", "stop_crypto_realtime_collectors",
    "stop_crypto_auto_refresh", "stop_fugle_realtime_init", "scheduler", "executor"])
def test_runtime_error_has_structured_result_and_retains_ownership(failure):
    async def scenario():
        with ExitStack() as stack:
            coord, lock = runtime_fixture(stack, failure=failure)
            if failure == "scheduler":
                stack.enter_context(patch.object(scheduler, "stop_scheduler", side_effect=RuntimeError("fixture")))
            if failure == "executor":
                stack.enter_context(patch.object(service, "drain_job_executor", new=AsyncMock(side_effect=RuntimeError("fixture"))))
            for _ in range(2):
                with pytest.raises(RuntimeDrainError) as error:
                    await coord.stop(timeout_seconds=0.1)
                assert error.value.result.state == "INCOMPLETE"
            lock.release.assert_not_called()
    run(scenario())


def test_runtime_deadline_caller_cancellation_does_not_cancel_owner():
    async def scenario():
        with ExitStack() as stack:
            coord, lock = runtime_fixture(stack)
            release = asyncio.Event()
            async def stop(**_): await release.wait()
            stack.enter_context(patch("app.runtime.stop_crypto_realtime_collectors", stop))
            caller = asyncio.create_task(coord.stop(timeout_seconds=0.03))
            await asyncio.sleep(0.005)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError): await caller
            try:
                with pytest.raises(RuntimeDrainError) as error:
                    await coord.stop()
                assert error.value.result.collectors["crypto realtime collectors"] == "timeout"
                assert not coord._collector_stops["crypto realtime collectors"].done()
                lock.release.assert_not_called()
            finally:
                release.set()
                await asyncio.gather(*coord._collector_stops.values())
    run(scenario())


def update(price=1):
    return SimpleNamespace(resource="quote", data={"price": price}, key=lambda: ("fixture",))


def test_crypto_persistence_stop_tracks_thread_no_overlap_and_reconverges():
    from app.crypto_market.realtime_persistence import CryptoRealtimePersistenceManager
    async def scenario():
        entered, release = Event(), Event()
        batches = []
        def persist(_db, updates):
            batches.append([item.data["price"] for item in updates])
            if len(batches) == 1:
                entered.set()
                assert release.wait(3)
            return {"persisted_count": len(updates)}
        manager = CryptoRealtimePersistenceManager(enabled=True, session_factory=lambda: MockSession(), persist_func=persist)
        manager.enqueue(update(1))
        flush = asyncio.create_task(manager.flush_once())
        await eventually(entered.is_set)
        manager.enqueue(update(2))
        flush.cancel()
        with pytest.raises(asyncio.CancelledError): await flush
        try:
            with pytest.raises(asyncio.TimeoutError):
                await manager.stop(timeout_seconds=0.02)
            assert manager.status()["flush_in_flight"] and batches == [[1]]
            assert not manager.enqueue(update(3))
            with pytest.raises(RuntimeError, match="incomplete"):
                await manager.start()
        finally:
            release.set()
        await manager.stop(timeout_seconds=2)
        assert batches == [[1], [2]] and not manager.status()["pending_count"]
        await manager.start()
        assert manager.enqueue(update(4))
        await manager.stop(drain=True)
        assert batches[-1] == [4]
        with pytest.raises(RuntimeError, match="terminal"): await manager.start()
    run(scenario())


class MockSession:
    def __init__(self): self.rollback = Mock()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def get_bind(self): return SimpleNamespace(dialect=SimpleNamespace(name="fixture"))


@pytest.mark.parametrize("failure", ["exception", "returned_error", "partial"])
def test_crypto_persistence_failed_flush_keeps_pending_and_rollback(failure):
    from app.crypto_market.realtime_persistence import CryptoRealtimePersistenceManager
    session = MockSession()
    def persist(*_):
        if failure == "exception": raise ValueError("fixture")
        return {"status": "partial" if failure == "partial" else "error", "error_count": 1}
    manager = CryptoRealtimePersistenceManager(enabled=True, session_factory=lambda: session, persist_func=persist)
    manager.enqueue(update())
    with pytest.raises(RuntimeError, match="unpersisted"):
        run(manager.stop(drain=True))
    assert manager.status()["pending_count"] == 1
    assert session.rollback.call_count == (1 if failure == "exception" else 0)


def test_auto_refresh_stop_is_bounded_and_manual_run_reconverges(monkeypatch):
    from app.crypto_market import auto_refresh as module
    async def scenario():
        entered, release = Event(), Event()
        def load():
            entered.set()
            assert release.wait(3)
            return []
        monkeypatch.setattr(module, "_load_auto_refresh_plans", load)
        monkeypatch.setattr(module.settings, "enable_crypto_market_auto_refresh", False)
        owner = module.CryptoAutoRefreshManager()
        once = asyncio.create_task(owner.run_once(force=True))
        await eventually(entered.is_set)
        try:
            with pytest.raises(asyncio.TimeoutError): await owner.stop(timeout_seconds=0.02)
            assert owner._active_runs
            with pytest.raises(RuntimeError, match="closed"): await owner.run_once(force=True)
        finally:
            release.set()
        await once
        await owner.stop(timeout_seconds=2)
        await owner.reload()
        await owner.run_once(force=True)
        await owner.stop(drain=True)
        with pytest.raises(RuntimeError, match="terminal"): await owner.start()
    run(scenario())


def test_fugle_waits_materializer_final_flush_and_global_terminal(monkeypatch):
    from app.market.providers import fugle_realtime_runtime as module
    async def scenario():
        entered, release = Event(), Event()
        calls = []
        owner = module.FugleRealtimeRuntime(api_key="fixture")
        def materialize():
            calls.append("flush")
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)
        monkeypatch.setattr(owner, "_materialize_once", materialize)
        monkeypatch.setattr(module, "_FUGLE_RUNTIME", owner)
        owner._materializer_task = asyncio.create_task(owner._materialize_loop())
        await eventually(entered.is_set)
        try:
            with pytest.raises(asyncio.TimeoutError): await owner.stop(drain=True, timeout_seconds=0.02)
            assert not owner._materializer_task.done()
            assert module.get_fugle_realtime_runtime() is owner
        finally:
            release.set()
        await module.stop_fugle_realtime(drain=True)
        assert calls == ["flush", "flush"]
        assert module.get_fugle_realtime_runtime() is owner
        with pytest.raises(RuntimeError, match="terminal"): await owner.start()
    run(scenario())


def test_collector_stop_start_overlap_retains_stream_owner(monkeypatch):
    from app.crypto_market import ws_runtime as module
    async def scenario():
        owner = module.CryptoRealtimeCollectorManager()
        entered, release = asyncio.Event(), asyncio.Event()
        async def stream():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                entered.set()
                await release.wait()
        stream_task = asyncio.create_task(stream())
        await asyncio.sleep(0)
        owner._running = True
        owner._tasks = [stream_task]
        persistence = SimpleNamespace(stop=AsyncMock(), start=AsyncMock(), status=lambda: {})
        monkeypatch.setattr(module, "crypto_realtime_persistence_manager", persistence)
        monkeypatch.setattr(module.settings, "enable_crypto_market_ws_collector", False)
        caller = asyncio.create_task(owner.stop(timeout_seconds=0.02))
        await entered.wait()
        try:
            with pytest.raises(RuntimeError, match="incomplete"): await owner.start()
            with pytest.raises(asyncio.TimeoutError): await caller
            assert owner._tasks == [stream_task] and not stream_task.done()
        finally:
            release.set()
        await owner.stop(timeout_seconds=2)
        assert stream_task.done() and owner._tasks == []
        await owner.start()  # disabled normal lifecycle can reconverge
        await owner.stop(drain=True)
        with pytest.raises(RuntimeError, match="terminal"): await owner.start()
    run(scenario())


def test_auto_refresh_writer_thread_timeout_and_run_once_reconvergence(monkeypatch):
    from app.crypto_market import auto_refresh as module
    async def scenario():
        entered, release = Event(), Event()
        plan = module.CryptoAutoRefreshPlan("quote", 1, providers="fixture", symbols=("FIXTURE",))
        calls = []
        monkeypatch.setattr(module, "_load_auto_refresh_plans", lambda: [plan])
        def execute(value):
            calls.append(value)
            entered.set()
            assert release.wait(3)
            return {"status": "success", "refreshed_count": 1}
        monkeypatch.setattr(module, "_execute_auto_refresh_plan", execute)
        monkeypatch.setattr(module.settings, "enable_crypto_market_auto_refresh", False)
        owner = module.CryptoAutoRefreshManager()
        once = asyncio.create_task(owner.run_once(force=True))
        await eventually(entered.is_set)
        try:
            with pytest.raises(asyncio.TimeoutError): await owner.stop(timeout_seconds=0.02)
            assert owner._states[plan.state_key()].running
            assert owner._active_runs and not once.done()
        finally:
            release.set()
        await once
        await owner.stop(timeout_seconds=2)
        await owner.reload()
        await owner.run_once(force=True)
        assert len(calls) == 2
        await owner.stop(drain=True)
    run(scenario())


def test_fugle_final_flush_failure_rolls_back_and_keeps_owner(monkeypatch):
    from app.market.providers import fugle_realtime_runtime as module
    async def scenario():
        session = SimpleNamespace(rollback=Mock(), close=Mock())
        owner = module.FugleRealtimeRuntime(api_key="fixture", session_factory=lambda: session)
        owner.materializer = SimpleNamespace(materialize=Mock(side_effect=ValueError("fixture final persist")))
        owner._materializer_task = asyncio.create_task(asyncio.sleep(0))
        await owner._materializer_task
        monkeypatch.setattr(module, "_FUGLE_RUNTIME", owner)
        with pytest.raises(ValueError, match="fixture final persist"):
            await module.stop_fugle_realtime(drain=True)
        session.rollback.assert_called_once()
        session.close.assert_called_once()
        assert module.get_fugle_realtime_runtime() is owner
        assert owner._final_flush_task.exception() is not None
        with pytest.raises(RuntimeError): await owner.start()
    run(scenario())


def test_scheduler_pause_precedes_collector_stop_and_lock_is_retained():
    async def scenario():
        events = []
        with ExitStack() as stack:
            coord, lock = runtime_fixture(stack)
            coord.scheduler = SimpleNamespace(
                pause=lambda: events.append("pause"), shutdown=lambda **_: events.append("join"),
            )
            async def stop(**_):
                assert "pause" in events
                events.append("collector")
            stack.enter_context(patch("app.runtime.stop_fugle_realtime", stop))
            await coord.stop()
            assert events.index("pause") < events.index("collector")
            lock.release.assert_not_called()
    run(scenario())


def test_runtime_receipts_are_explicit_success_and_timeout(tmp_path):
    async def scenario():
        with ExitStack() as stack:
            success, _ = runtime_fixture(stack, leader=False)
            success_receipt = await success.stop()
            # A second coordinator here only observes the already-fenced fixture;
            # it never calls start(), and is not a production rearm path.
            timed, lock = runtime_fixture(stack)
            release = asyncio.Event()
            async def wait(**_): await release.wait()
            stack.enter_context(patch("app.runtime.stop_fugle_realtime", wait))
            try:
                with pytest.raises(RuntimeDrainError) as error:
                    await timed.stop(timeout_seconds=0.01)
                failed_receipt = error.value.result
                lock.release.assert_not_called()
                assert not failed_receipt.all_writers_drained
                (tmp_path / "drain-receipts.json").write_text(json.dumps({
                    "scope": "OFFLINE_FIXTURE_ONLY", "success": asdict(success_receipt),
                    "timeout": asdict(failed_receipt),
                }, indent=2), encoding="utf-8")
            finally:
                release.set()
                await asyncio.gather(*timed._collector_stops.values())
    run(scenario())


@pytest.mark.parametrize("exit_code,expected_starts", [(0, 1), (7, 3)])
def test_disposable_runner_normal_exit_and_bounded_crash_recovery(tmp_path, exit_code, expected_starts):
    root = Path(__file__).resolve().parents[2]
    child = tmp_path / "owned_fixture.py"
    child.write_text(f"print('DISPOSABLE_R1D_ONLY')\nraise SystemExit({exit_code})\n", encoding="utf-8")
    encoded = base64.b64encode(json.dumps([str(child)]).encode()).decode()
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-File", str(root / "scripts/run-service-logged.ps1"),
        "-ServiceName", "backend", "-RepoRoot", str(tmp_path), "-WorkingDirectory", str(tmp_path),
        "-FilePath", sys.executable, "-ArgumentsJsonBase64", encoded, "-LauncherPid", "0",
        "-MaxRestartAttempts", "2", "-RestartBackoffSecondsCsv", "0",
    ], capture_output=True, text=True, timeout=20)
    assert result.returncode == exit_code, result.stdout + result.stderr
    logs = list((tmp_path / "logs/backend").glob("*/backend.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8-sig").count("Service child started.") == expected_starts


def test_powershell_legacy_stop_contract_mock_only(tmp_path):
    """AST-extracted existing stop function; replace every process-affecting API."""
    root = Path(__file__).resolve().parents[2]
    source = str(root / "scripts/omi-launcher.ps1").replace("'", "''")
    script = tmp_path / "mock-stop.ps1"
    script.write_text("""
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'parse failed' }
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Stop-ProcessTree'},$true)
function Test-ProcessRunning { param($Process) return ($null -ne $Process) }
function Start-Process { param($FilePath,$ArgumentList,[switch]$Wait,$WindowStyle) $script:called=@($ArgumentList) }
function Write-LauncherLog { param($Message,$Level) }
Invoke-Expression $node.Extent.Text
$script:called=@()
Stop-ProcessTree $null 'fixture'
if ($script:called.Count) { throw 'null identity acted on' }
$p=[pscustomobject]@{Id=123456}
Stop-ProcessTree $p 'fixture'
if (($script:called -join ' ') -notmatch '/T /F') { throw 'expected forced legacy semantics' }
@{scope='MOCK_ONLY';graceful=$false;signal='UNIMPLEMENTED';forced=$true} | ConvertTo-Json -Compress
""".replace("SOURCE", source), encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"graceful":false' in result.stdout


def test_powershell_identity_exit_and_respawn_checkpoint_matrix(tmp_path):
    root = Path(__file__).resolve().parents[2]
    contract = str(root / "docs/exec-plans/active/us-r0-r5-20261009/R1D-Handshake-Contract.ps1").replace("'", "''")
    script = tmp_path / "mock-handshake.ps1"
    script.write_text(". '" + contract + "'\n" + r"""
$ErrorActionPreference='Stop'
$baseline=@{IdentityKnown=$true;ChildPid=123;ChildStart='fixture-start';DeadlineExpired=$false;
 Forced=$false;Crashed=$false;StopIntentLatched=$true;RespawnInhibited=$true;TransportVerified=$true;
 AuthenticatedAck=$true;AckPid=123;AckStart='fixture-start';AckInstance='fixture-instance';Instance='fixture-instance';
 AllWritersCovered=$true;AllWritersDrained=$true;ExactProcessExited=$true}
$cases=@(
 @{Name='normal';Change=@{};Reason='SIMULATED_EVIDENCE_ONLY'},
 @{Name='unknown';Change=@{IdentityKnown=$false};Reason='IDENTITY_UNKNOWN'},
 @{Name='reused-pid';Change=@{AckStart='different'};Reason='ACK_IDENTITY_MISMATCH'},
 @{Name='wrong-pid';Change=@{AckPid=456};Reason='ACK_IDENTITY_MISMATCH'},
 @{Name='wrong-instance';Change=@{AckInstance='different'};Reason='ACK_IDENTITY_MISMATCH'},
 @{Name='unauthenticated';Change=@{AuthenticatedAck=$false};Reason='ACK_IDENTITY_MISMATCH'},
 @{Name='crash';Change=@{Crashed=$true};Reason='UNCLEAN_EXIT'},
 @{Name='forced';Change=@{Forced=$true};Reason='UNCLEAN_EXIT'},
 @{Name='deadline';Change=@{DeadlineExpired=$true};Reason='DEADLINE_EXCEEDED'},
 @{Name='respawn';Change=@{RespawnInhibited=$false};Reason='RUNNER_MAY_RESPAWN'},
 @{Name='no-intent';Change=@{StopIntentLatched=$false};Reason='RUNNER_MAY_RESPAWN'},
 @{Name='no-signal';Change=@{TransportVerified=$false};Reason='OS_TRANSPORT_UNVERIFIED'},
 @{Name='unknown-writer';Change=@{AllWritersCovered=$false};Reason='WRITER_COVERAGE_INCOMPLETE'},
 @{Name='not-drained';Change=@{AllWritersDrained=$false};Reason='WRITER_COVERAGE_INCOMPLETE'},
 @{Name='listener-gone-only';Change=@{ExactProcessExited=$false};Reason='EXIT_UNCONFIRMED'}
)
foreach ($case in $cases) {
 $e=$baseline.Clone(); foreach($key in $case.Change.Keys) {$e[$key]=$case.Change[$key]}
 $r=Get-R1DGracefulStopCheckpoint ([pscustomobject]$e)
 if($r.Reason -ne $case.Reason -or $r.ProductionGate -ne 'BLOCKED' -or $r.SignalAction -ne 'NONE' -or $r.ForceFallback -or $r.RestartAuthorized) {throw $case.Name}
}
Write-Output '15 MOCK_ONLY checkpoints passed; production BLOCKED'
""", encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "15 MOCK_ONLY" in result.stdout
