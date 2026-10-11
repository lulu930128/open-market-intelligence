"""Explicit offline R1D test support; never loaded by application code.

Fresh lifecycle state is monkeypatched only while a fixture owns it. The event
loop fixture simulates IO readiness; g3_offline_guard still denies all network
and production DB access. Import required fixtures explicitly in each test file.
"""
import asyncio
import selectors
import time
from threading import BoundedSemaphore
import pytest
from sqlalchemy.orm import Session
from app.jobs import service
from app.jobs import us_intraday_materializer_scheduler as publisher


def _fresh_publisher_lifecycle(monkeypatch):
    """Test-only fresh process state; never erase a surviving worker."""
    assert not publisher._READ_MODEL_PUBLISH_TASKS
    for name, value in {
        "_READ_MODEL_PUBLISH_TASKS": {}, "_READ_MODEL_PUBLISH_CLOSED": False,
        "_READ_MODEL_PUBLISH_COMPLETED": 0, "_READ_MODEL_PUBLISH_FAILURES": 0,
        "_READ_MODEL_PUBLISH_SKIPPED": 0,
        "_READ_MODEL_PUBLISH_LAST_EXIT_AT": None,
    }.items():
        monkeypatch.setattr(publisher, name, value)


def _join_fixture_publishers():
    publisher.begin_intraday_publisher_drain()
    for task in tuple(publisher._READ_MODEL_PUBLISH_TASKS.values()):
        if task.thread is not None and task.thread.ident is not None:
            task.thread.join(timeout=5)
            assert not task.thread.is_alive()
    publisher.intraday_publisher_drain_status()


@pytest.fixture(autouse=True)
def isolated_publisher_lifecycle(monkeypatch):
    _fresh_publisher_lifecycle(monkeypatch)
    yield
    _join_fixture_publishers()


class NoIOSelector(selectors.BaseSelector):
    """Only timers/Tasks/Futures are tested; no OS sockets even for wakeups."""
    def register(self, *_): raise AssertionError("fixture loop forbids IO")
    def unregister(self, *_): raise AssertionError("fixture loop forbids IO")
    def modify(self, *_): raise AssertionError("fixture loop forbids IO")
    def get_map(self): return {}
    def select(self, timeout=None):
        time.sleep(min(max(timeout or 0, 0), 0.002))
        return []


class OfflineLoop(asyncio.SelectorEventLoop):
    def __init__(self): super().__init__(selector=NoIOSelector())
    def _make_self_pipe(self): pass
    def _close_self_pipe(self): pass
    def _write_to_self(self): pass


@pytest.fixture(autouse=True)
def offline_asyncio(monkeypatch):
    # Windows' real Proactor socketpair is denied by g3_offline_guard. Keep that
    # guard intact and explicitly simulate only event-loop IO, not drain logic.
    monkeypatch.setattr(asyncio.events, "new_event_loop", OfflineLoop)


@pytest.fixture(autouse=True)
def offline_crypto_policy_session(request, monkeypatch):
    # Existing crypto source-health tests pass self.db, but collector status
    # independently opens its policy SessionLocal. Bind it to that SAME fixture.
    if request.node.path.name == "test_crypto_market.py":
        from app.crypto_market import ws_runtime
        monkeypatch.setattr(ws_runtime, "SessionLocal", lambda: Session(request.instance.engine))


@pytest.fixture(autouse=True)
def isolated_job_lifecycle(monkeypatch):
    """Fresh process simulation only in tests; no production rearm API exists."""
    assert not service._pending_tasks and not service._active_enqueues
    _fresh_publisher_lifecycle(monkeypatch)
    for name, value in {
        "_executor": None, "_materialization_executors": {}, "_pending_tasks": {},
        "_admission_closed": False, "_active_enqueues": 0, "_task_failures": 0,
        "_enqueue_failures": 0,
        "_materialization_slots": {name: BoundedSemaphore(size) for name, size in (
            ("market_interactive", 8), ("market_background", 2), ("market_completed", 3),
        )},
    }.items():
        monkeypatch.setattr(service, name, value)
    yield
    _join_fixture_publishers()
    # Every blocking fixture releases its own Event in finally before this check.
    service.begin_job_drain()
    deadline = time.monotonic() + 5
    while (service._pending_tasks or service._active_enqueues) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not service._pending_tasks and not service._active_enqueues
    service.shutdown_job_executor()
    for pool in [service._executor, *service._materialization_executors.values()]:
        if pool is not None:
            pool.shutdown(wait=True)
