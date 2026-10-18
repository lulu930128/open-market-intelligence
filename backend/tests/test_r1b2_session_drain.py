"""R1-B2 explicit owners only; run with g3_offline_guard, no app.main/start."""
import asyncio
import json
from threading import Barrier, Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as owner
from app.runtime import RuntimeCoordinator, RuntimeDrainError
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_scopes(monkeypatch):
    assert not owner._session_scopes
    monkeypatch.setattr(owner, "_session_scopes", {})
    monkeypatch.setattr(owner, "_session_scope_closed", False)
    monkeypatch.setattr(owner, "_session_scope_last_exit", None)
    yield
    # Only deliberate fake close failures may survive. Every real worker is
    # released/joined in its own finally, and every real Session closes normally.
    assert all(r.close_failed and isinstance(r.session, SimpleNamespace)
               for r in owner._session_scopes.values())


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "owned.sqlite").as_posix(),
                           connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE receipt (value INTEGER)"))
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(owner, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


def drain(seconds=1):
    return asyncio.run(owner.drain_session_scopes(deadline=time.monotonic() + seconds))


def coordinator(enabled=True):
    return RuntimeCoordinator(schema_lock=Mock(), background_lock=Mock(),
                              drain_owned_sessions=enabled)


def test_default_dependency_fenced_while_other_engine_remains_unattested(database):
    from fastapi import HTTPException
    owner.begin_session_scope_drain()
    dependency = owner.get_db()
    with pytest.raises(HTTPException) as error:
        next(dependency)
    assert error.value.status_code == 503
    with database[1]() as db:
        db.execute(text("INSERT INTO receipt VALUES (1)"))
        db.commit()
    assert drain().drained
    result = asyncio.run(coordinator().stop())
    assert not result.all_writers_drained
    assert any("raw DBAPI" in item for item in result.unknown_writers)
    assert result.sessions.evidence_scope == "explicit_session_scopes_only"


@pytest.mark.parametrize("finish", ["commit", "rollback", "close", "exception"])
def test_real_transaction_semantics_and_no_implicit_commit(database, finish):
    engine, _ = database
    try:
        with owner.owned_session("api_request") as db:
            db.execute(text("INSERT INTO receipt VALUES (7)"))
            owner.begin_session_scope_drain()
            assert not drain(0).drained
            if finish == "exception":
                raise ValueError("original business failure")
            if finish in {"commit", "rollback"}:
                getattr(db, finish)()
            # Even after commit/rollback, owner may start another transaction.
            assert not drain(0).drained
    except ValueError as exc:
        assert finish == "exception" and str(exc) == "original business failure"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM receipt")).scalar() == (finish == "commit")
    assert drain().drained


def test_constructor_reserved_before_stop_and_first_sql_still_owned(database, monkeypatch):
    entered, release = Event(), Event()
    factory = database[1]
    def delayed_factory():
        entered.set()
        assert release.wait(3)
        return factory()
    monkeypatch.setattr(owner, "SessionLocal", delayed_factory)
    outcomes = []
    def work():
        with owner.owned_session("api_request") as db:
            # Deliberately the first SQL occurs AFTER terminal stop admission.
            assert owner._session_scope_closed
            db.execute(text("INSERT INTO receipt VALUES (2)"))
            db.commit()
        outcomes.append("done")
    thread = Thread(target=work)
    thread.start()
    try:
        assert entered.wait(2)
        result = drain(0.01)
        assert result.state == "timeout" and result.pending_constructors == 1
        assert result.active_owners == ("api_request",)
        with pytest.raises(owner.SessionAdmissionClosed):
            with owner.owned_session("runtime_startup"):
                pytest.fail("late admission")
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and outcomes == ["done"]
    assert not result.drained  # Immutable late completion cannot upgrade receipt.
    assert drain().drained


@pytest.mark.parametrize("phase", ["execute", "commit", "rollback", "close"])
def test_active_sql_commit_rollback_close_block_runtime_receipt(database, monkeypatch, phase):
    entered, release = Event(), Event()
    errors = []
    def block(*_):
        entered.set()
        assert release.wait(3)
    def work():
        try:
            with owner.owned_session("api_request") as db:
                if phase == "execute":
                    event.listen(db, "do_orm_execute", block, once=True)
                elif phase == "commit":
                    event.listen(db, "before_commit", block, once=True)
                elif phase == "rollback":
                    event.listen(db, "after_rollback", block, once=True)
                elif phase == "close":
                    original = db.close
                    def close():
                        block()
                        original()
                    db.close = close
                db.execute(text("INSERT INTO receipt VALUES (3)"))
                if phase == "rollback":
                    db.rollback()
                else:
                    db.commit()
        except BaseException as exc:
            errors.append(exc)
    thread = Thread(target=work)
    thread.start()
    runtime = coordinator()
    try:
        assert entered.wait(2)
        with pytest.raises(RuntimeDrainError) as failure:
            asyncio.run(runtime.stop(timeout_seconds=0.02))
        receipt = failure.value.result
        assert receipt.sessions.state == "timeout" and not receipt.all_writers_drained
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and not errors
    with pytest.raises(RuntimeDrainError) as repeated:
        asyncio.run(runtime.stop(timeout_seconds=5))
    assert repeated.value.result is receipt
    assert drain().drained


@pytest.mark.parametrize("failure", [ValueError, SystemExit, asyncio.CancelledError])
def test_constructor_failure_removes_only_reservation(monkeypatch, failure):
    monkeypatch.setattr(owner, "SessionLocal", Mock(side_effect=failure("factory")))
    with pytest.raises(failure):
        with owner.owned_session("api_request"):
            pytest.fail("constructor failed")
    assert drain().drained


def test_close_failure_retains_exact_reference_and_is_not_retried(monkeypatch):
    db = SimpleNamespace(close=Mock(side_effect=ValueError("unknown close")))
    monkeypatch.setattr(owner, "SessionLocal", lambda: db)
    with pytest.raises(ValueError, match="unknown close"):
        with owner.owned_session("api_request"):
            pass
    result = drain()
    assert result.state == "error" and result.close_failures == 1 and not result.drained
    assert next(iter(owner._session_scopes.values())).session is db
    assert drain() == result
    db.close.assert_called_once()


def test_rollback_failure_preserves_original_error_and_close_semantics(monkeypatch):
    db = SimpleNamespace(close=Mock(), rollback=Mock(side_effect=ValueError("rollback failed")))
    monkeypatch.setattr(owner, "SessionLocal", lambda: db)
    with pytest.raises(ValueError, match="rollback failed"):
        with owner.owned_session("api_request") as active:
            active.rollback()
    db.close.assert_called_once()
    assert drain().drained


def test_owner_cancellation_retains_unknown_without_racing_worker_close(monkeypatch):
    db = SimpleNamespace(close=Mock(), rollback=Mock(), commit=Mock())
    monkeypatch.setattr(owner, "SessionLocal", lambda: db)
    with pytest.raises(asyncio.CancelledError):
        with owner.owned_session("api_request"):
            raise asyncio.CancelledError
    db.close.assert_not_called()
    db.rollback.assert_not_called()
    db.commit.assert_not_called()
    assert drain().state == "unknown"
    assert drain().uncertain_owners == ("api_request",)
    # Fake has no worker/connection; discard only this isolated test state.
    owner._session_scopes.clear()


def test_observer_cancellation_never_releases_active_owner(database):
    async def scenario():
        with owner.owned_session("api_request"):
            task = asyncio.create_task(owner.drain_session_scopes(deadline=time.monotonic()+2))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert owner._session_scope_closed and len(owner._session_scopes) == 1
            assert not (await owner.drain_session_scopes(deadline=time.monotonic())).drained
        assert (await owner.drain_session_scopes(deadline=time.monotonic()+1)).drained
    asyncio.run(scenario())


def test_stop_caller_cancel_and_double_stop_share_deadline(database):
    async def scenario():
        runtime = coordinator()
        with owner.owned_session("api_request"):
            first = asyncio.create_task(runtime.stop(timeout_seconds=1))
            await asyncio.sleep(0.01)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(runtime.stop(timeout_seconds=0))
            await asyncio.sleep(0.01)
            assert not second.done() and not runtime._stop_task.cancelled()
        result = await second
        assert result.sessions.drained and not result.all_writers_drained
        assert await runtime.stop() is result
        with pytest.raises(owner.SessionAdmissionClosed):
            owner.require_session_scope_admission()
    asyncio.run(scenario())


def test_late_close_cannot_pass_original_deadline(database):
    with owner.owned_session("api_request"):
        deadline = time.monotonic()
        owner.begin_session_scope_drain()
    assert owner.session_scope_drain_status(deadline=deadline).state == "timeout"


@pytest.mark.parametrize("iteration", range(12))
def test_admission_and_stop_atomic_race(monkeypatch, iteration):
    barrier, release = Barrier(2), Event()
    made = Mock(return_value=SimpleNamespace(close=Mock()))
    monkeypatch.setattr(owner, "SessionLocal", made)
    outcome = []
    def work():
        barrier.wait(2)
        try:
            with owner.owned_session("api_request"):
                outcome.append("admitted")
                assert release.wait(3)
        except owner.SessionAdmissionClosed:
            outcome.append("rejected")
    thread = Thread(target=work)
    thread.start()
    try:
        barrier.wait(2)
        result = drain(0)
        if result.drained:
            assert made.call_count == 0
        else:
            assert result.active_owners == ("api_request",)
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and len(outcome) == 1
    assert made.call_count == (outcome == ["admitted"])
    assert drain().drained


def test_external_engine_and_unknown_thread_are_not_claimed(database):
    engine, _ = database
    result = asyncio.run(coordinator().stop())
    outcomes = []
    def external_work():
        # A separate engine/Session is deliberately not registered with owner.
        external = create_engine(engine.url)
        try:
            with Session(external) as db:
                db.execute(text("INSERT INTO receipt VALUES (8)"))
                db.commit()
            outcomes.append("external write")
        finally:
            external.dispose()
    thread = Thread(target=external_work)
    thread.start()
    thread.join(3)
    assert not thread.is_alive() and outcomes == ["external write"]
    assert not result.all_writers_drained
    assert "other processes/checkout/scripts" in result.unknown_writers
    with pytest.raises(ValueError, match="Unclassified"):
        with owner.owned_session("external"):
            pytest.fail("arbitrary owner label")


def test_borrowed_session_reuse_is_unknown_not_global_sqlalchemy_policy(database):
    with owner.owned_session("api_request") as borrowed:
        pass
    receipt = drain()
    # SQLAlchemy Session.close is intentionally reusable. Escapes require a
    # separate ownership gate; this receipt MUST NOT claim global quiescence.
    borrowed.execute(text("INSERT INTO receipt VALUES (9)"))
    borrowed.commit()
    borrowed.close()
    assert receipt.drained and not receipt.all_writers_drained


def test_runtime_startup_exact_direct_owner_is_fenced(database, monkeypatch):
    from app import runtime as runtime_module
    monkeypatch.setattr(runtime_module, "SessionLocal", database[1])
    def mark(db):
        assert tuple(r.owner for r in owner._session_scopes.values()) == ("runtime_startup",)
        db.execute(text("INSERT INTO receipt VALUES (4)"))
        db.commit()
        return 1
    monkeypatch.setattr(runtime_module.job_service, "mark_interrupted_jobs", mark)
    runtime = coordinator()
    runtime._mark_interrupted_jobs()
    assert not owner._session_scopes
    owner.begin_session_scope_drain()
    with pytest.raises(owner.SessionAdmissionClosed):
        runtime._mark_interrupted_jobs()


def test_same_deadline_for_jobs_publisher_sessions(monkeypatch):
    from app import runtime as runtime_module
    deadlines = []
    for module, name in [(runtime_module.job_service, "drain_job_executor"),
                         (runtime_module.intraday_publisher, "drain_intraday_publishers"),
                         (owner, "drain_session_scopes")]:
        original = getattr(module, name)
        async def observed(*, deadline, original=original):
            deadlines.append(deadline)
            return await original(deadline=deadline)
        monkeypatch.setattr(module, name, observed)
    result = asyncio.run(coordinator().stop())
    assert len(deadlines) == 3 and len(set(deadlines)) == 1
    assert result.sessions.drained


def test_session_observer_error_fails_closed(monkeypatch):
    async def broken(**_):
        raise ValueError("observer")
    monkeypatch.setattr(owner, "drain_session_scopes", broken)
    with pytest.raises(RuntimeDrainError) as failure:
        asyncio.run(coordinator().stop())
    assert failure.value.result.sessions.state == "unknown"
    assert not failure.value.result.all_writers_drained


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), -float("inf")])
def test_invalid_deadline_cannot_report_success(deadline):
    with pytest.raises(ValueError):
        asyncio.run(owner.drain_session_scopes(deadline=deadline))
    assert not owner._session_scope_closed


def test_fixture_api_get_post_error_and_503_after_stop(database):
    app = FastAPI()  # No production lifespan/main/migrations/collectors.
    app.dependency_overrides[owner.get_db] = owner.get_draining_db
    @app.get("/rows")
    def rows(db=Depends(owner.get_db)):
        return db.execute(text("SELECT count(*) FROM receipt")).scalar()
    @app.post("/rows")
    def insert(db=Depends(owner.get_db)):
        db.execute(text("INSERT INTO receipt VALUES (5)"))
        db.commit()
        return {"ok": True}
    @app.post("/error")
    def error(db=Depends(owner.get_db)):
        db.execute(text("INSERT INTO receipt VALUES (6)"))
        raise ValueError("business failure")
    async def request(method, path):
        messages = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": method, "path": path, "raw_path": path.encode(),
                 "query_string": b"", "headers": [], "scheme": "http",
                 "server": ("fixture", 80), "client": ("fixture", 1), "root_path": ""}
        try:
            await app(scope, receive, send)
        except ValueError as exc:
            assert path == "/error" and str(exc) == "business failure"
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return status, body
    async def scenario():
        assert json.loads((await request("GET", "/rows"))[1]) == 0
        assert (await request("POST", "/rows"))[0] == 200
        assert (await request("POST", "/error"))[0] == 500
        assert json.loads((await request("GET", "/rows"))[1]) == 1
        assert not owner._session_scopes
        receipt = await coordinator().stop()
        assert receipt.sessions.drained and not receipt.all_writers_drained
        assert (await request("POST", "/rows"))[0] == 503
        assert (await request("GET", "/rows"))[0] == 503
    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_request", [False, True])
def test_real_asgi_sync_request_stop_and_cancel_cannot_hide_worker(database, monkeypatch, cancel_request):
    import gc

    entered, release, finished = Event(), Event(), Event()
    closed = Mock()
    factory = database[1]
    def make():
        db = factory()
        original = db.close
        def close():
            closed()
            original()
        db.close = close
        return db
    monkeypatch.setattr(owner, "SessionLocal", make)
    app = FastAPI()
    app.dependency_overrides[owner.get_db] = owner.get_draining_db
    @app.post("/blocked")
    def blocked(db=Depends(owner.get_db)):
        entered.set()
        try:
            assert release.wait(4)
            db.execute(text("INSERT INTO receipt VALUES (10)"))
            db.commit()
        finally:
            finished.set()
        return {"ok": True}
    async def scenario():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(_):
            pass
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "path": "/blocked", "raw_path": b"/blocked",
                 "query_string": b"", "headers": [], "scheme": "http",
                 "server": ("fixture", 80), "client": ("fixture", 1), "root_path": ""}
        task = asyncio.create_task(app(scope, receive, send))
        deadline = time.monotonic() + 3
        try:
            while not entered.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.002)
            runtime = coordinator()
            stop = asyncio.create_task(runtime.stop(timeout_seconds=0.03))
            await asyncio.sleep(0.005)
            if cancel_request:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                gc.collect()  # Include abandoned sync generator finalization.
            closed.assert_not_called()
            assert not finished.is_set()
            with pytest.raises(RuntimeDrainError) as failure:
                await stop
            assert not failure.value.result.sessions.drained
            assert owner._session_scopes
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while entered.is_set() and not finished.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.002)
            if not cancel_request:
                await task
            else:
                # Test-only cleanup AFTER the real worker proves completion.
                # Runtime has no such release/reset API or automatic promotion.
                del task
                gc.collect()
                for record in tuple(owner._session_scopes.values()):
                    assert record.session is not None
                    record.session.close()
                owner._session_scopes.clear()
    asyncio.run(scenario())


def test_premature_dependency_generator_close_retains_unknown(database):
    dependency = owner.get_draining_db()
    db = next(dependency)
    dependency.close()
    assert drain().state == "unknown"
    assert next(iter(owner._session_scopes.values())).session is db
    # Only fixture knows there is no borrowed worker.
    db.close()
    owner._session_scopes.clear()


def test_real_watchlist_api_dispatch_keeps_service_commit_and_get_read_only(database):
    from app.db.models import WatchlistGroup
    from app.routers.watchlists import create_watchlist_group, list_watchlist_groups
    from app.watchlists.schemas import WatchlistGroupCreate

    engine, _ = database
    WatchlistGroup.__table__.create(engine)
    dependency = owner.get_draining_db()
    db = next(dependency)
    group = create_watchlist_group(WatchlistGroupCreate(group_name="fixture"), db=db)
    assert group.group_name == "fixture"
    assert next(dependency, None) is None
    statements = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, statement, *args: statements.append(statement))
    dependency = owner.get_draining_db()
    db = next(dependency)
    assert len(list_watchlist_groups(db=db)) == 1
    assert next(dependency, None) is None
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert drain().drained


@pytest.mark.parametrize("fails", [False, True])
def test_dispatch_startup_scope_does_not_take_transaction_control(database, monkeypatch, fails):
    from app import runtime as runtime_module
    from app.dispatch import schedule_runs, service

    monkeypatch.setattr(runtime_module, "SessionLocal", database[1])
    monkeypatch.setattr(runtime_module.settings, "enable_dispatch_scheduler", True)
    monkeypatch.setattr(runtime_module.settings, "dispatch_scheduler_v2_enabled", True)
    def initialize(db):
        assert next(iter(owner._session_scopes.values())).owner == "runtime_startup"
        db.execute(text("INSERT INTO receipt VALUES (11)"))
        db.commit()
        return 1
    def reconcile(*, db):
        db.execute(text("INSERT INTO receipt VALUES (12)"))
        if fails:
            db.rollback()
            raise ValueError("dispatch failure")
        db.commit()
        return {}
    monkeypatch.setattr(schedule_runs, "initialize_next_runs", initialize)
    monkeypatch.setattr(service, "reconcile_schedule_runs", reconcile)
    runtime = coordinator()
    if fails:
        with pytest.raises(ValueError, match="dispatch failure"):
            runtime._reconcile_dispatch_runs()
    else:
        runtime._reconcile_dispatch_runs()
    assert not owner._session_scopes
    with database[0].connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM receipt")).scalar() == (1 if fails else 2)
    owner.begin_session_scope_drain()
    with pytest.raises(owner.SessionAdmissionClosed):
        runtime._reconcile_dispatch_runs()


def test_new_opt_in_runtime_cannot_rearm_terminal_session_owner(monkeypatch):
    from app import runtime as runtime_module

    migration = Mock(side_effect=AssertionError("migration forbidden"))
    monkeypatch.setattr(runtime_module, "run_database_migrations", migration)
    owner.begin_session_scope_drain()
    with pytest.raises(owner.SessionAdmissionClosed):
        asyncio.run(coordinator().start())
    migration.assert_not_called()
