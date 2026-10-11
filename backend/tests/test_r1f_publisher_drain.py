"""R1F: only injected sessions/projections and real owned fixture threads."""
import asyncio
from contextlib import ExitStack
from threading import Barrier, Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.jobs import service, scheduler
from app.jobs import us_intraday_materializer_scheduler as publisher
from app.runtime import RuntimeCoordinator, RuntimeDrainError
from app.us_market import service as market_service
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


def bind(monkeypatch, *, read=None, close=None, rollback=None, factory=None):
    db = SimpleNamespace(close=Mock(side_effect=close), rollback=Mock(side_effect=rollback))
    make = Mock(side_effect=factory or (lambda: db))
    monkeypatch.setattr(publisher, "SessionLocal", make)
    monkeypatch.setattr(market_service, "get_us_intraday_trend", read or Mock())
    return db, make


def drain(seconds=1):
    return asyncio.run(publisher.drain_intraday_publishers(deadline=time.monotonic() + seconds))


async def eventually(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.002)


def coord(*, leader=False):
    lock = Mock()
    owner = RuntimeCoordinator(schema_lock=Mock(), background_lock=lock)
    owner.background_leader = leader
    owner.started = True
    return owner, lock


def test_close_must_finish_before_thread_and_session_drain(monkeypatch):
    entered, release = Event(), Event()
    def close():
        entered.set()
        assert release.wait(3)
    db, make = bind(monkeypatch, close=close)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    try:
        result = drain(0.02)
        assert result.state == "timeout" and not result.drained
        assert result.unclosed_sessions == ("TSM",)
        assert task.thread.is_alive() and task.session is db
        assert not publisher._schedule_intraday_consumer_read_model("MU")
        make.assert_called_once()
    finally:
        release.set()
    result = drain()
    assert result.drained and result.completed == 1
    assert not task.thread.is_alive() and task.session_closed
    assert drain() == result
    db.close.assert_called_once()


def test_active_projection_is_awaited_without_cancel(monkeypatch):
    entered, release = Event(), Event()
    def read(**_):
        entered.set()
        assert release.wait(3)
    db, _ = bind(monkeypatch, read=read)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    async def scenario():
        pending = asyncio.create_task(publisher.drain_intraday_publishers(deadline=time.monotonic()+2))
        await asyncio.sleep(0.015)
        assert not pending.done()
        db.close.assert_not_called()
        release.set()
        assert (await pending).drained
    try:
        asyncio.run(scenario())
    finally:
        release.set()


@pytest.mark.parametrize("failure", ["worker", "base_exception", "rollback", "close", "factory"])
def test_outcome_failure_is_telemetry_but_unclosed_session_blocks_drain(monkeypatch, failure):
    def read(**_):
        if failure == "base_exception": raise SystemExit("fixture")
        if failure in {"worker", "rollback"}: raise ValueError("fixture")
    def close():
        if failure == "close": raise ValueError("fixture close")
    def rollback():
        if failure == "rollback": raise ValueError("fixture rollback")
    def factory(): raise ValueError("fixture factory")
    db, _ = bind(monkeypatch, read=read, close=close, rollback=rollback,
                 factory=factory if failure == "factory" else None)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    task.thread.join(2)
    result = drain()
    assert result.failures == 1
    assert result.drained is (failure != "close")
    assert result.ownership_failures == int(failure == "close")
    if failure == "factory":
        db.close.assert_not_called()
    else:
        db.close.assert_called_once()
    if failure == "close":
        assert result.state == "error"
        assert result.unclosed_sessions == ("TSM",)
        assert publisher._READ_MODEL_PUBLISH_TASKS["TSM"] is task and task.session is db
    else:
        assert result.retained_symbols == ()
    assert drain() == result


@pytest.mark.parametrize("launched", [False, True])
def test_start_failure_retains_uncertain_owner(monkeypatch, launched):
    entered, release = Event(), Event()
    real_thread = Thread
    def read(**_):
        entered.set()
        assert release.wait(3)
    bind(monkeypatch, read=read)
    class FailingStart(real_thread):
        def start(self):
            if launched: super().start()
            raise RuntimeError("fixture start")
    monkeypatch.setattr(publisher, "Thread", FailingStart)
    try:
        with pytest.raises(RuntimeError, match="fixture start"):
            publisher._schedule_intraday_consumer_read_model("TSM")
        task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
        if launched: assert entered.wait(2)
        result = drain(0.01)
        assert not result.drained and result.failures == 1
        assert publisher._READ_MODEL_PUBLISH_TASKS["TSM"] is task
        assert not publisher._schedule_intraday_consumer_read_model("TSM")
    finally:
        release.set()
    assert drain().drained is launched


def test_unknown_completion_retains_dead_thread(monkeypatch):
    bind(monkeypatch)
    monkeypatch.setattr(publisher, "_publish_intraday_consumer_read_model", lambda _: None)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    task.thread.join(2)
    assert drain().state == "unknown"
    assert publisher._READ_MODEL_PUBLISH_TASKS["TSM"] is task


def test_stop_before_delayed_worker_entry_never_constructs_session(monkeypatch):
    entered, release = Event(), Event()
    target = publisher._publish_intraday_consumer_read_model
    def delayed(symbol):
        entered.set()
        assert release.wait(3)
        target(symbol)
    _, make = bind(monkeypatch)
    monkeypatch.setattr(publisher, "_publish_intraday_consumer_read_model", delayed)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    try:
        publisher.begin_intraday_publisher_drain()
        assert not publisher._schedule_intraday_consumer_read_model("MU")
        assert not drain(0.01).drained
        make.assert_not_called()
    finally:
        release.set()
    result = drain()
    assert result.drained and result.skipped == 1
    make.assert_not_called()


@pytest.mark.parametrize("iteration", range(12))
def test_concurrent_admission_stop_race(monkeypatch, iteration):
    _, make = bind(monkeypatch)
    barrier = Barrier(9)
    results, errors = [], []
    def submit(index):
        try:
            barrier.wait(2)
            results.append(publisher._schedule_intraday_consumer_read_model(str(index % 3)))
        except BaseException as exc: errors.append(exc)
    threads = [Thread(target=submit, args=(index,)) for index in range(8)]
    for thread in threads: thread.start()
    barrier.wait(2)
    publisher.begin_intraday_publisher_drain()
    at_fence = make.call_count
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert not errors and len(results) == 8
    for _ in range(5): assert not publisher._schedule_intraday_consumer_read_model("LATE")
    assert drain().drained
    assert make.call_count == at_fence


def test_capacity_recovers_only_after_actual_thread_exit(monkeypatch):
    release = Event()
    bind(monkeypatch, read=lambda **_: release.wait(3))
    try:
        for symbol in ("TSM", "MU", "AAPL", "^GSPC"):
            assert publisher._schedule_intraday_consumer_read_model(symbol)
        assert not publisher._schedule_intraday_consumer_read_model("TSM")
        assert not publisher._schedule_intraday_consumer_read_model("^SOX")
        release.set()
        for task in tuple(publisher._READ_MODEL_PUBLISH_TASKS.values()): task.thread.join(2)
        assert publisher._schedule_intraday_consumer_read_model("^SOX")
        assert drain().drained
    finally:
        release.set()


@pytest.mark.parametrize("leader", [False, True])
def test_runtime_fences_synchronously_and_waits_parent_step(monkeypatch, leader):
    events = []
    _, make = bind(monkeypatch)
    owner, lock = coord(leader=leader)
    original = service.begin_job_drain
    def begin():
        original()
        events.append("job-fence")
    monkeypatch.setattr(service, "begin_job_drain", begin)
    def pause():
        assert service.job_drain_status().admission_closed
        assert publisher.intraday_publisher_drain_status().admission_closed
        events.append("pause")
    def parent_finish(**_):
        events.append("parent-step")
        result = publisher._publish_intraday_consumer_read_models({"results":[
            {"symbol":"TSM", "status":"success", "consumer_cache_invalidated":True}]})
        assert result["consumer_cache_publish_scheduled_count"] == 0
        assert result["consumer_cache_publish_deferred_symbols"] == ["TSM"]
    owner.scheduler = SimpleNamespace(pause=pause, shutdown=parent_finish)
    async def scenario():
        with ExitStack() as stack:
            for name in ("stop_fugle_realtime", "stop_crypto_realtime_collectors", "stop_crypto_auto_refresh"):
                stack.enter_context(patch("app.runtime."+name, new=AsyncMock()))
            result = await owner.stop()
            assert result.publisher.drained and result.state == "REGISTERED_DRAINED"
            assert not result.all_writers_drained
            assert await owner.stop() is result
        lock.release.assert_not_called()
    asyncio.run(scenario())
    if leader: assert events.index("job-fence") < events.index("pause") < events.index("parent-step")
    make.assert_not_called()


@pytest.mark.parametrize("cancel", [False, True])
def test_runtime_timeout_keeps_thread_receipt_and_terminal_result(monkeypatch, cancel):
    entered, release = Event(), Event()
    def read(**_):
        entered.set()
        assert release.wait(3)
    bind(monkeypatch, read=read)
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    owner, lock = coord()
    async def scenario():
        caller = asyncio.create_task(owner.stop(timeout_seconds=0.04))
        await asyncio.sleep(0.005)
        if cancel:
            caller.cancel()
            with pytest.raises(asyncio.CancelledError): await caller
        else:
            with pytest.raises(RuntimeDrainError): await caller
        with pytest.raises(RuntimeDrainError) as error: await owner.stop()
        result = error.value.result
        assert result.state == "INCOMPLETE" and result.publisher.state == "timeout"
        assert not result.all_writers_drained
        assert publisher._READ_MODEL_PUBLISH_TASKS["TSM"] is task and task.thread.is_alive()
        release.set()
        await eventually(lambda: not task.thread.is_alive())
        assert (await publisher.drain_intraday_publishers(deadline=time.monotonic()+1)).drained
        with pytest.raises(RuntimeDrainError) as repeat: await owner.stop()
        assert repeat.value.result is result  # no post-deadline upgrade
        lock.release.assert_not_called()
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_cancel_publisher_observer_does_not_cancel_worker(monkeypatch):
    entered, release = Event(), Event()
    bind(monkeypatch, read=lambda **_: (entered.set(), release.wait(3)))
    assert publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    async def scenario():
        observer = asyncio.create_task(publisher.drain_intraday_publishers(deadline=time.monotonic()+2))
        await asyncio.sleep(0.01)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError): await observer
        assert task.thread.is_alive() and publisher._READ_MODEL_PUBLISH_TASKS["TSM"] is task
        release.set()
        assert (await publisher.drain_intraday_publishers(deadline=time.monotonic()+1)).drained
    try: asyncio.run(scenario())
    finally: release.set()


def test_publisher_only_terminal_fence_blocks_new_runtime_and_scheduler_before_io(monkeypatch):
    publisher.begin_intraday_publisher_drain()
    migration = Mock(side_effect=AssertionError("must not migrate"))
    monkeypatch.setattr("app.runtime.run_database_migrations", migration)
    owner, lock = coord()
    with pytest.raises(RuntimeError, match="terminal"): asyncio.run(owner.start())
    with pytest.raises(RuntimeError, match="terminal"): scheduler.start_scheduler()
    lock.acquire.assert_not_called()
    migration.assert_not_called()


def test_startup_failure_closes_publisher_and_new_coordinator_cannot_rearm(monkeypatch):
    owner, lock = coord()
    owner.started = False
    monkeypatch.setattr("app.runtime.run_database_migrations", Mock(side_effect=ValueError("fixture migration")))
    with pytest.raises(ValueError): asyncio.run(owner.start())
    assert publisher.intraday_publisher_drain_status().drained
    with pytest.raises(RuntimeError, match="terminal"): asyncio.run(owner.start())
    fresh, _ = coord()
    with pytest.raises(service.JobAdmissionClosed): asyncio.run(fresh.start())


@pytest.mark.parametrize("unknown", [False, True])
def test_runtime_publisher_error_or_unknown_is_incomplete(monkeypatch, unknown):
    if unknown:
        monkeypatch.setattr(publisher, "drain_intraday_publishers", AsyncMock(side_effect=RuntimeError("fixture")))
    else:
        bind(monkeypatch, close=lambda: (_ for _ in ()).throw(ValueError("fixture close")))
        publisher._schedule_intraday_consumer_read_model("TSM")
        publisher._READ_MODEL_PUBLISH_TASKS["TSM"].thread.join(2)
    owner, lock = coord()
    with pytest.raises(RuntimeDrainError) as error: asyncio.run(owner.stop(timeout_seconds=0.05))
    assert error.value.result.publisher.state == ("unknown" if unknown else "error")
    assert not error.value.result.all_writers_drained
    lock.release.assert_not_called()


def test_unregistered_direct_publisher_cannot_open_session(monkeypatch):
    _, make = bind(monkeypatch)
    with pytest.raises(RuntimeError, match="registered"): publisher._publish_intraday_consumer_read_model("TSM")
    make.assert_not_called()


def test_transient_read_failure_then_success_does_not_poison_runtime_quiescence(monkeypatch):
    attempts = []
    def read(**kwargs):
        attempts.append(kwargs["symbol"])
        if len(attempts) == 1: raise ValueError("transient projection failure")
    db, make = bind(monkeypatch, read=read)
    for _ in range(2):
        assert publisher._schedule_intraday_consumer_read_model("TSM")
        publisher._READ_MODEL_PUBLISH_TASKS["TSM"].thread.join(2)
    owner, _ = coord()
    result = asyncio.run(owner.stop())
    assert result.state == "REGISTERED_DRAINED"
    assert result.publisher.drained and result.publisher.failures == 1
    assert result.publisher.completed == 2 and result.publisher.ownership_failures == 0
    assert not result.publisher.retained_symbols and not result.all_writers_drained
    assert make.call_count == db.close.call_count == 2
    db.rollback.assert_called_once()


def test_finally_receipt_alone_does_not_release_live_thread(monkeypatch):
    entered, release = Event(), Event()
    target = publisher._publish_intraday_consumer_read_model
    def delayed_exit(symbol):
        target(symbol)
        entered.set()
        assert release.wait(3)
    db, _ = bind(monkeypatch)
    monkeypatch.setattr(publisher, "_publish_intraday_consumer_read_model", delayed_exit)
    publisher._schedule_intraday_consumer_read_model("TSM")
    assert entered.wait(2)
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    try:
        assert task.finished and task.session_closed
        assert not publisher._schedule_intraday_consumer_read_model("TSM")
        result = drain(0.01)
        assert result.state == "timeout" and result.retained_symbols == ("TSM",)
        assert not result.unclosed_sessions
    finally:
        release.set()
    assert drain().drained


def test_running_parent_scheduler_step_finishes_without_late_publisher(monkeypatch):
    entered, release = Event(), Event()
    _, make = bind(monkeypatch)
    parent_results = []
    def parent_step():
        entered.set()
        assert release.wait(3)
        parent_results.append(publisher._publish_intraday_consumer_read_models({"results":[
            {"symbol":"MU", "status":"partial", "consumer_cache_invalidated":True}]}))
    parent = Thread(target=parent_step)
    parent.start()
    assert entered.wait(2)
    owner, _ = coord(leader=True)
    owner.scheduler = SimpleNamespace(pause=Mock(), shutdown=lambda **_: parent.join(2))
    async def scenario():
        with ExitStack() as stack:
            for name in ("stop_fugle_realtime", "stop_crypto_realtime_collectors", "stop_crypto_auto_refresh"):
                stack.enter_context(patch("app.runtime."+name, new=AsyncMock()))
            stopping = asyncio.create_task(owner.stop(timeout_seconds=2))
            await eventually(lambda: owner._scheduler_drain is not None)
            await asyncio.sleep(0.01)
            assert not stopping.done() and parent.is_alive()
            release.set()
            result = await stopping
            assert result.scheduler_state == "drained" and result.publisher.drained
    try: asyncio.run(scenario())
    finally:
        release.set()
        parent.join(2)
    assert parent_results[0]["consumer_cache_publish_deferred_symbols"] == ["MU"]
    make.assert_not_called()


def test_late_exit_observation_cannot_upgrade_expired_deadline(monkeypatch):
    bind(monkeypatch)
    publisher._schedule_intraday_consumer_read_model("TSM")
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    deadline = time.monotonic()
    task.thread.join(2)
    result = asyncio.run(publisher.drain_intraday_publishers(deadline=deadline))
    assert result.state == "timeout" and not result.drained
    assert result.last_exit_observed_at > deadline
    assert not task.thread.is_alive()
    assert drain().drained  # separate later evidence; Runtime keeps its first receipt


def test_exit_between_status_and_orphan_check_is_reaped(monkeypatch):
    bind(monkeypatch)
    publisher._schedule_intraday_consumer_read_model("TSM")
    task = publisher._READ_MODEL_PUBLISH_TASKS["TSM"]
    task.thread.join(2)
    actual = task.thread.is_alive
    observed = iter([True])
    monkeypatch.setattr(task.thread, "is_alive", lambda: next(observed, actual()))
    assert drain().drained
    assert not publisher._READ_MODEL_PUBLISH_TASKS
