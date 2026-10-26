"""A refused production prepare must leave the service able to accept work."""
import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db import admission
from app.db.admission import EngineAdmission, SqliteAdmission, EngineAdmissionClosed
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


def test_refused_prepare_keeps_existing_and_new_database_work_available(tmp_path, monkeypatch):
    from app import runtime as runtime_module
    from app.runtime import RuntimeCoordinator
    owner = SqliteAdmission()
    monkeypatch.setattr(admission, "sqlite_admission", owner)
    monkeypatch.setattr(runtime_module, "sqlite_admission", owner)
    engine = create_engine("sqlite:///" + (tmp_path / "work.sqlite").as_posix(), poolclass=NullPool)
    fence = EngineAdmission(engine)
    runtime = RuntimeCoordinator(drain_owned_sessions=True, drain_engine_connections=True)
    runtime.started = True

    async def forbidden_stop(**kwargs):
        pytest.fail("Preflight must not enter irreversible drain")
    monkeypatch.setattr(runtime, "stop", forbidden_stop)
    with engine.connect() as existing:
        existing.execute(text("SELECT 1"))
        before = owner.observation()
        result = asyncio.run(runtime.prepare_owned_restart(timeout_seconds=1))
        assert result["state"] == "OWNED_BOOTSTRAP_REQUIRED"
        assert owner.observation() == before
        assert existing.execute(text("SELECT 2")).scalar() == 2
    with engine.connect() as new:
        assert new.execute(text("SELECT 3")).scalar() == 3
    assert runtime.started and runtime._stop_task is None and runtime.drain_result is None
    assert not owner.observation()["admission_closed"]
    assert fence.status(deadline=time.monotonic()).state == "accepting"
    engine.dispose()


def test_raw_and_independent_engine_share_the_same_driver_fence(tmp_path, monkeypatch):
    owner = SqliteAdmission()
    monkeypatch.setattr(admission, "sqlite_admission", owner)
    engine = create_engine("sqlite:///" + (tmp_path / "migration.sqlite").as_posix(), poolclass=NullPool)
    admission.attach_sqlite_admission(engine)
    raw = owner.connect(str(tmp_path / "maintenance.sqlite"))
    connection = engine.connect()
    assert owner.observation()["active_connections"] == 2
    owner.begin_drain()
    with pytest.raises(EngineAdmissionClosed):
        owner.connect(":memory:")
    with pytest.raises(EngineAdmissionClosed):
        engine.connect()
    raw.close()
    assert owner.observation()["active_connections"] == 1
    connection.close()
    assert owner.observation()["active_connections"] == 0
    engine.dispose()


def test_escaped_driver_remains_active_after_pool_checkin(tmp_path, monkeypatch):
    owner = SqliteAdmission()
    monkeypatch.setattr(admission, "sqlite_admission", owner)
    engine = create_engine("sqlite:///" + (tmp_path / "pool.sqlite").as_posix())
    EngineAdmission(engine)
    with engine.connect() as connection:
        escaped = connection.connection.driver_connection
    assert owner.observation()["active_connections"] == 1
    owner.begin_drain()
    assert escaped.execute("SELECT 1").fetchone() == (1,)
    engine.dispose()
    assert owner.observation()["active_connections"] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        escaped.execute("SELECT 1")


def test_application_import_uses_the_captured_bytes(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "owned_backend_entry.py"
    spec = importlib.util.spec_from_file_location("owned_entry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    app = tmp_path / "backend/app"
    app.mkdir(parents=True)
    sample = app / "sample.py"
    sample.write_text("VALUE = 'captured'\n", encoding="utf-8")
    snapshot = module.ApplicationSource()
    sample.write_text("raise RuntimeError('late disk code')\n", encoding="utf-8")
    captured_spec = snapshot.find_spec("app.sample")
    loaded = importlib.util.module_from_spec(captured_spec)
    snapshot.exec_module(loaded)
    assert loaded.VALUE == "captured"
    assert len(snapshot.release_id) == 64
    (app / "late.py").write_text("VALUE = 'late'\n", encoding="utf-8")
    with pytest.raises(ImportError):
        snapshot.find_spec("app.late")


@pytest.mark.parametrize("fault", ["file_reparse", "parent_reparse", "stat_denied", "attributes_missing"])
def test_application_snapshot_rejects_unverified_windows_paths(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace
    import stat

    path = Path(__file__).resolve().parents[1] / "owned_backend_entry.py"
    spec = importlib.util.spec_from_file_location("owned_entry_guard_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    app = tmp_path / "backend/app"
    app.mkdir(parents=True)
    sample = app / "sample.py"
    sample.write_text("VALUE = 'unread'\n", encoding="utf-8")
    original = Path.lstat
    target = app if fault == "parent_reparse" else sample

    def guarded_stat(candidate, *args, **kwargs):
        value = original(candidate, *args, **kwargs)
        if candidate != target:
            return value
        if fault == "stat_denied":
            raise PermissionError("fixture denied")
        if fault == "attributes_missing":
            return SimpleNamespace(st_mode=value.st_mode)
        return SimpleNamespace(st_mode=value.st_mode,
                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)

    monkeypatch.setattr(Path, "lstat", guarded_stat)
    with pytest.raises((RuntimeError, PermissionError, AttributeError)):
        module.ApplicationSource()


@pytest.fixture
def restart_runtime(tmp_path, monkeypatch):
    """Isolated owner process state; never configures or stops the live Backend."""
    import sys
    from types import SimpleNamespace
    from app import runtime as module
    from app.db import session
    from app import runtime_admission
    from app.crypto_market import auto_refresh, ws_runtime, realtime_persistence
    from app.market.providers import fugle_realtime_runtime
    path = tmp_path / "restart.sqlite"
    with sqlite3.connect(path) as setup:
        setup.execute("CREATE TABLE retained(value INTEGER)")
    setup.close()
    engine = create_engine("sqlite:///" + path.as_posix(), poolclass=NullPool)
    owner = SqliteAdmission()
    monkeypatch.setattr(admission, "sqlite_admission", owner)
    monkeypatch.setattr(module, "sqlite_admission", owner)
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(session, "engine_admission", EngineAdmission(engine))
    for name, value in {"_session_scope_closed": False, "_session_scope_pause": None,
                        "_session_scopes": {}, "_session_scope_last_exit": None}.items():
        monkeypatch.setattr(session, name, value)
    detached = runtime_admission.DetachedAdmission()
    monkeypatch.setattr(module, "detached_admission", detached)
    monkeypatch.setattr(runtime_admission, "detached_admission", detached)
    monkeypatch.setattr(auto_refresh, "crypto_auto_refresh_manager", auto_refresh.CryptoAutoRefreshManager())
    monkeypatch.setattr(ws_runtime, "crypto_realtime_collector_manager", ws_runtime.CryptoRealtimeCollectorManager())
    monkeypatch.setattr(realtime_persistence, "crypto_realtime_persistence_manager", realtime_persistence.CryptoRealtimePersistenceManager(enabled=False))
    monkeypatch.setattr(fugle_realtime_runtime, "_FUGLE_RUNTIME", None)
    monkeypatch.setitem(sys.modules, "_omi_owned_release", SimpleNamespace(verified=True))
    runtime = module.RuntimeCoordinator(drain_owned_sessions=True, drain_engine_connections=True)
    runtime.started = True
    yield runtime, owner, engine, path
    if runtime._restart_guard is not None:
        runtime._restart_guard.release()
    engine.dispose()


@pytest.mark.parametrize("historical_failures", [0, 1])
def test_external_writer_refusal_rearms_every_owner(restart_runtime, monkeypatch, historical_failures):
    from app.jobs import service
    monkeypatch.setattr(service, "_enqueue_failures", historical_failures)
    runtime, owner, engine, path = restart_runtime
    external = sqlite3.connect(path, timeout=0, isolation_level=None)
    external.execute("BEGIN IMMEDIATE")

    async def check():
        result = await runtime.prepare_owned_restart(timeout_seconds=1)
        assert result == {"state": "PREFLIGHT_REARMED", "stage": "SQLITE_EXTERNAL_WRITER_EXCLUSION",
                          "terminal_drain_started": False}
        assert runtime.started and runtime._stop_task is None and runtime.http_admission.accepting
        assert not runtime._restart_undo
        from app.db import session
        from app.jobs import service, us_intraday_materializer_scheduler as publisher
        from app.crypto_market.auto_refresh import crypto_auto_refresh_manager
        from app.crypto_market.ws_runtime import crypto_realtime_collector_manager
        from app.crypto_market.realtime_persistence import crypto_realtime_persistence_manager
        session.require_session_scope_admission()
        service.require_job_admission()
        publisher.require_intraday_publisher_admission()
        for manager in (crypto_auto_refresh_manager, crypto_realtime_collector_manager, crypto_realtime_persistence_manager):
            assert manager.restart_admission.accepting
        # Read remains accepted while the independent writer holds its lock.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 7")).scalar() == 7
    try:
        asyncio.run(check())
    finally:
        external.rollback()
        external.close()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO retained VALUES (1)"))
    assert owner.observation()["active_connections"] == 0


@pytest.mark.parametrize("historical_failures", [0, 1])
def test_prepare_lock_survives_commit_until_lifespan_drain(restart_runtime, monkeypatch, historical_failures):
    from app.jobs import service
    monkeypatch.setattr(service, "_enqueue_failures", historical_failures)
    runtime, owner, engine, path = restart_runtime

    async def check():
        result = await runtime.prepare_owned_restart(timeout_seconds=1)
        assert result["state"] == "WRITERS_PREPARED"
        assert runtime._stop_task is None and runtime.started
        external = sqlite3.connect(path, timeout=0, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                external.execute("BEGIN IMMEDIATE")
            assert runtime.abort_owned_restart()
            external.execute("BEGIN IMMEDIATE")
            external.rollback()
            assert (await runtime.prepare_owned_restart(timeout_seconds=1))["state"] == "WRITERS_PREPARED"
            runtime.commit_owned_restart()
            result = await runtime.stop(timeout_seconds=1)
            assert result.all_writers_drained and result.unknown_writers == ()
            assert result.jobs.unresolved_enqueues == historical_failures
            assert runtime._restart_guard.held
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                external.execute("BEGIN IMMEDIATE")
            assert not runtime.abort_owned_restart()
        finally:
            external.close()
    asyncio.run(check())


@pytest.mark.parametrize("blocker", ["session", "physical_sqlite"])
def test_history_does_not_bypass_active_session_or_sqlite_writer(restart_runtime, monkeypatch, blocker):
    from contextlib import ExitStack
    from sqlalchemy.orm import Session
    from app.db import session as session_owner
    from app.jobs import service

    runtime, owner, engine, path = restart_runtime
    monkeypatch.setattr(service, "_enqueue_failures", 1)
    with ExitStack() as stack:
        if blocker == "session":
            db = stack.enter_context(session_owner.owned_session(
                "api_request", session_factory=lambda: Session(engine)))
            db.execute(text("INSERT INTO retained VALUES (1)"))
            expected = "SESSION_QUIESCENCE"
        else:
            db = owner.connect(path)
            stack.callback(db.close)
            db.execute("INSERT INTO retained VALUES (1)")
            expected = "SQLITE_PHYSICAL_CONNECTION_QUIESCENCE"
        stack.callback(db.rollback)

        async def refuse():
            result = await runtime.prepare_owned_restart(timeout_seconds=.05)
            assert result == {"state": "PREFLIGHT_REARMED", "stage": expected,
                              "terminal_drain_started": False}
            assert runtime.owned_restart_rearmed() and runtime._stop_task is None

        asyncio.run(refuse())
        assert service._enqueue_failures == 1
        # Refusal must not close/rollback the actual writer to fabricate idle.
        transaction_open = db.in_transaction() if blocker == "session" else db.in_transaction
        assert transaction_open
        statement = "SELECT COUNT(*) FROM retained"
        assert (db.execute(text(statement)).scalar() if blocker == "session"
                else db.execute(statement).fetchone()[0]) == 1

    async def after_writer_exit():
        result = await runtime.prepare_owned_restart(timeout_seconds=1)
        try:
            assert result["state"] == "WRITERS_PREPARED"
            assert service._enqueue_failures == 1
        finally:
            assert runtime.abort_owned_restart()

    asyncio.run(after_writer_exit())


@pytest.mark.parametrize("ownership", ["active_transport", "unknown_start"])
def test_history_does_not_bypass_unfinished_provider_thread(restart_runtime, monkeypatch, ownership):
    from threading import Event, Thread
    from app.jobs import service
    from app import runtime_admission

    runtime, _, _, _ = restart_runtime
    monkeypatch.setattr(service, "_enqueue_failures", 1)
    entered, release, completed = Event(), Event(), Event()
    def transport():
        entered.set()
        assert release.wait(3)
        completed.set()
    worker = runtime_admission.OwnedWorkThread(target=transport)
    if ownership == "unknown_start":
        # start() may fail after native dispatch; absence of a live Thread is
        # not completion proof. Preserve the original owner's reservation.
        with monkeypatch.context() as start_failure:
            start_failure.setattr(Thread, "start", lambda _: (_ for _ in ()).throw(RuntimeError("unknown dispatch")))
            with pytest.raises(RuntimeError, match="unknown dispatch"):
                worker.start()
    else:
        worker.start()
        assert entered.wait(2)
    async def refuse():
        result = await runtime.prepare_owned_restart(timeout_seconds=.05)
        assert result == {"state": "PREFLIGHT_REARMED", "stage": "DETACHED_WORKER_QUIESCENCE",
                          "terminal_drain_started": False}
        assert runtime._stop_task is None and runtime.owned_restart_rearmed()
        assert runtime_admission.detached_admission.observation()["retained_worker_count"] == 1
        assert service._enqueue_failures == 1 and not completed.is_set()
    try:
        asyncio.run(refuse())
    finally:
        release.set()
        if ownership == "active_transport":
            worker.join(2)
            assert completed.is_set() and not worker.is_alive()
    # An unknown reservation is deliberately never cleared, even in this test;
    # fixture isolation disposes the entire owner after the assertion.
    if ownership == "unknown_start":
        assert runtime_admission.detached_admission.observation()["retained_worker_count"] == 1


def test_history_does_not_bypass_unknown_session_close(restart_runtime, monkeypatch):
    from sqlalchemy.orm import Session
    from app.db import session as session_owner
    from app.jobs import service

    runtime, _, engine, _ = restart_runtime
    monkeypatch.setattr(service, "_enqueue_failures", 1)
    class UnacknowledgedClose(Session):
        def close(self):
            super().close()
            raise RuntimeError("fixture close acknowledgement unknown")
    with pytest.raises(RuntimeError, match="acknowledgement unknown"):
        with session_owner.owned_session("api_request", session_factory=lambda: UnacknowledgedClose(engine)) as db:
            db.execute(text("INSERT INTO retained VALUES (1)"))
            db.commit()
    async def refuse():
        result = await runtime.prepare_owned_restart(timeout_seconds=.05)
        assert result == {"state": "PREFLIGHT_REARMED", "stage": "SESSION_QUIESCENCE",
                          "terminal_drain_started": False}
        assert runtime._stop_task is None and runtime.owned_restart_rearmed()
        assert session_owner.session_scope_drain_status(deadline=time.monotonic()).close_failures == 1
        assert service._enqueue_failures == 1
    asyncio.run(refuse())


def test_prepared_owner_loss_expiry_rearms_without_stop(restart_runtime):
    runtime, owner, engine, _ = restart_runtime

    async def check():
        assert (await runtime.prepare_owned_restart(timeout_seconds=1))["state"] == "WRITERS_PREPARED"
        await runtime._restart_expiry
        assert runtime._restart_guard is None and runtime.http_admission.accepting
        assert runtime._stop_task is None and runtime.started
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 11")).scalar() == 11
    asyncio.run(check())


@pytest.mark.parametrize('late_stop', ['normal', 'lease-expired', 'wrong-uuid', 'expired-deadline'])
def test_production_transport_drains_real_runtime_through_uvicorn_lifespan(restart_runtime, monkeypatch, late_stop):
    """Production PREPARE/STOP branch, temporary DB, real owners, no sockets/app.main.

    This is in-process drain evidence; retained OS exits are tested separately.
    """
    import io
    import json
    import os
    import queue
    import sys
    import uuid
    from contextlib import asynccontextmanager
    from starlette.applications import Starlette
    from app import owned_uvicorn

    runtime, owner, engine, _ = restart_runtime
    frames = queue.Queue()
    observed = []
    request_id = str(uuid.uuid4())
    first_stop = None
    prepared_count = 0
    created = owned_uvicorn.creation(os.getpid())
    boot = dict(scope="PRODUCTION", instance=str(uuid.uuid4()), nonce="a" * 64,
                launcher_pid=str(os.getpid()), launcher_created=created,
                runner_pid=str(os.getpid()), runner_created=created,
                host="127.0.0.1", port="65431", release_id="isolated-application-snapshot")
    for key in ("launcher_pid", "launcher_created", "host", "port"):
        env = "OMI_RUNTIME_" + key.upper() if key.startswith("launcher") else "OMI_BACKEND_" + key.upper()
        monkeypatch.setenv(env, boot[key])
    monkeypatch.setattr(sys.modules["_omi_owned_release"], "release_id", boot["release_id"], raising=False)

    class Input:
        def readline(self, size):
            return frames.get(timeout=10)

    class NoSocketServer(owned_uvicorn.uvicorn.Server):
        async def serve(self, sockets=None):
            return await super().serve(sockets=[])

    @asynccontextmanager
    async def lifespan(app):
        yield
        observed.append("lifespan-drain")
        result = await runtime.stop(timeout_seconds=1)
        assert result.all_writers_drained and runtime._restart_guard.held
        observed.append("drain-complete")

    app = Starlette(lifespan=lifespan)
    app.state.runtime = runtime
    emit = owned_uvicorn.emit

    def capture(value):
        nonlocal first_stop, prepared_count
        observed.append(value["state"])
        emitted = emit(value)
        if value["state"] == "READY":
            command = dict(value, action="PREPARE", request_id=request_id,
                           deadline=str(int(time.time() * 1000) + 14000))
            frames.put(json.dumps(command) + "\n")
        elif value["state"] == "WRITERS_PREPARED":
            prepared_count += 1
            assert runtime._stop_task is None and runtime._restart_guard.held
            command = dict(value, action="STOP")
            if late_stop != 'normal' and prepared_count == 1:
                first_stop = command
                async def after_expiry():
                    await runtime._restart_expiry  # Real 5s production lease, no test shortcut.
                    assert runtime.owned_restart_rearmed() and runtime._stop_task is None
                    late = dict(command)
                    if late_stop == 'wrong-uuid':
                        late['request_id'] = str(uuid.uuid4())
                    elif late_stop == 'expired-deadline':
                        late['deadline'] = str(int(time.time() * 1000) - 1)
                    frames.put(json.dumps(late) + '\n')
                asyncio.create_task(after_expiry())
            else:
                frames.put(json.dumps(command) + "\n")
        elif value['state'] == 'REJECTED':
            assert late_stop in {'wrong-uuid', 'expired-deadline'}
            assert runtime._stop_task is None and not runtime._restart_committed
            frames.put(json.dumps(first_stop) + '\n')
        elif value['state'] == 'PREFLIGHT_REARMED':
            assert value['request_id'] == request_id and value['deadline'] == first_stop['deadline']
            assert value['rearmed'] == 'true' and runtime.owned_restart_rearmed()
            assert runtime._stop_task is None and runtime.http_admission.accepting
            # A separate explicit operation with fresh guard; never reuse STOP.
            fresh = dict(value, action='PREPARE', request_id=str(uuid.uuid4()))
            frames.put(json.dumps(fresh) + '\n')
        return emitted

    monkeypatch.setattr(sys, "stdin", Input())
    monkeypatch.setattr(owned_uvicorn, "_control_stdout", io.StringIO())
    monkeypatch.setattr(owned_uvicorn, "emit", capture)
    monkeypatch.setattr(owned_uvicorn.uvicorn, "Server", NoSocketServer)

    async def check():
        return await asyncio.wait_for(owned_uvicorn.serve_owned(app, boot=boot), 14)

    try:
        assert asyncio.run(check()) == 0
    finally:
        frames.put("")
    prefix = ['READY', 'WRITERS_PREPARED']
    if late_stop in {'wrong-uuid', 'expired-deadline'}:
        prefix += ['REJECTED']
    if late_stop != 'normal':
        prefix += ['PREFLIGHT_REARMED', 'WRITERS_PREPARED']
    assert observed == prefix + ["STOP_ACCEPTED", "lifespan-drain", "drain-complete", "LIFESPAN_COMPLETE"]
    assert owner.observation()["active_connections"] == 0


def test_lazy_detached_worker_retained_until_actual_exit(monkeypatch):
    from threading import Event
    from app import runtime_admission
    owner = runtime_admission.DetachedAdmission()
    monkeypatch.setattr(runtime_admission, "detached_admission", owner)
    release = Event()
    thread = runtime_admission.OwnedWorkThread(target=release.wait)
    thread.start()
    try:
        thread.join(.01)
        with pytest.raises(RuntimeError, match="once"):
            thread.start()
        assert owner.pause_if_idle() is None
    finally:
        release.set()
        thread.join(1)
    lease = owner.pause_if_idle()
    assert lease is not None
    owner.resume(lease)


def test_asgi_admission_waits_for_response_background_and_rearms():
    from types import SimpleNamespace
    from app.runtime_admission import AsyncAdmission, RuntimeAdmissionMiddleware

    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        runtime = SimpleNamespace(http_admission=AsyncAdmission(), http_ownership_unknown=False)
        scope = {"type": "http", "path": "/api/market/indices", "app": SimpleNamespace(state=SimpleNamespace(runtime=runtime))}
        sent = []
        async def send(message):
            sent.append(message)
        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})
            entered.set()
            await release.wait()  # Streaming/background lifetime, after headers.
        middleware = RuntimeAdmissionMiddleware(application)
        active = asyncio.create_task(middleware(scope, None, send))
        await entered.wait()
        lease = runtime.http_admission.pause()
        assert not runtime.http_admission.idle(lease)
        await middleware(scope, None, send)
        assert sent[-2]["status"] == 503
        release.set()
        await active
        assert runtime.http_admission.idle(lease)
        runtime.http_admission.resume(lease)
        await middleware(scope, None, send)
        assert sent[-1]["status"] == 200
    asyncio.run(check())


def test_cancelled_http_caller_retains_actual_scope_until_background_exit(restart_runtime):
    from types import SimpleNamespace
    from app.runtime_admission import RuntimeAdmissionMiddleware
    runtime, _, _, _ = restart_runtime

    async def check():
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def application(scope, receive, send):
            entered.set()
            await release.wait()  # Admitted background task still owns work.
            finished.set()
        middleware = RuntimeAdmissionMiddleware(application)
        scope = {'type': 'http', 'path': '/api/test', 'app': SimpleNamespace(state=SimpleNamespace(runtime=runtime))}
        caller = asyncio.create_task(middleware(scope, None, None))
        await entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        result = await runtime.prepare_owned_restart(timeout_seconds=.05)
        assert result['state'] == 'PREFLIGHT_REARMED' and result['stage'] == 'HTTP_QUIESCENCE'
        assert not finished.is_set() and not runtime.http_ownership_unknown
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        assert (await runtime.prepare_owned_restart(timeout_seconds=1))['state'] == 'WRITERS_PREPARED'
        assert runtime.abort_owned_restart()
    asyncio.run(check())


def test_cancelled_inner_http_scope_and_failed_rearm_remain_unknown(restart_runtime, monkeypatch):
    from types import SimpleNamespace
    from app.runtime_admission import RuntimeAdmissionMiddleware
    runtime, _, _, _ = restart_runtime

    async def check():
        async def cancelled(scope, receive, send):
            raise asyncio.CancelledError()
        scope = {'type': 'http', 'path': '/api/test', 'app': SimpleNamespace(state=SimpleNamespace(runtime=runtime))}
        with pytest.raises(asyncio.CancelledError):
            await RuntimeAdmissionMiddleware(cancelled)(scope, None, None)
        assert runtime.http_ownership_unknown
        assert (await runtime.prepare_owned_restart(timeout_seconds=1))['state'] == 'ALL_WRITERS_DRAIN_UNAVAILABLE'
        assert not runtime.owned_restart_rearmed()
    asyncio.run(check())


def test_missing_guard_never_substitutes_for_failed_owner_undo(restart_runtime):
    runtime, _, _, _ = restart_runtime

    async def check():
        assert (await runtime.prepare_owned_restart(timeout_seconds=1))['state'] == 'WRITERS_PREPARED'
        def unknown_owner():
            raise RuntimeError('TEST_OWNER_REARM_UNKNOWN')
        runtime._restart_undo.append(unknown_owner)
        assert not runtime.abort_owned_restart()
        assert runtime._restart_guard is None and not runtime.owned_restart_rearmed()
        with pytest.raises(RuntimeError, match='PREPARE_AUTHORITY_EXPIRED'):
            runtime.commit_owned_restart()
        assert not runtime.owned_restart_rearmed() and runtime._stop_task is None
        runtime._restart_undo.pop()
        assert runtime.abort_owned_restart()
    asyncio.run(check())


def test_readonly_revision_requires_existing_database(tmp_path):
    from app.db.migrations import get_database_revision
    path = tmp_path / "schema.sqlite"
    url = "sqlite:///" + path.as_posix()
    with pytest.raises(RuntimeError, match="existing"):
        get_database_revision(url, existing_only=True)
    assert not path.exists()
    with sqlite3.connect(path) as setup:
        setup.execute("CREATE TABLE alembic_version(version_num TEXT)")
        setup.execute("INSERT INTO alembic_version VALUES ('fixture_revision')")
    setup.close()
    before = path.read_bytes()
    assert get_database_revision(url, existing_only=True) == "fixture_revision"
    assert path.read_bytes() == before


def test_native_lock_excludes_an_independent_process(tmp_path):
    import subprocess
    import sys
    from sqlalchemy.engine import make_url
    from app.db.quiescence import SQLiteWriterLease
    path = tmp_path / "external.sqlite"
    sqlite3.connect(path).close()
    lease = SQLiteWriterLease.acquire(make_url("sqlite:///" + path.as_posix()))
    code = "import sqlite3,sys\nc=sqlite3.connect(sys.argv[1],timeout=0,isolation_level=None)\ntry:\n c.execute('BEGIN IMMEDIATE')\n print('acquired')\nexcept sqlite3.OperationalError:\n print('blocked')\nfinally:\n c.close()"
    try:
        result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(path)], capture_output=True, text=True, timeout=5, check=True)
        assert result.stdout.strip() == "blocked"
    finally:
        lease.release()
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(path)], capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout.strip() == "acquired"


def test_broken_control_reader_does_not_raise_into_serving_task(monkeypatch):
    from app import owned_uvicorn
    class ClosedReader:
        def write(self, value):
            raise BrokenPipeError()
    monkeypatch.setattr(owned_uvicorn, "_control_stdout", ClosedReader())
    assert owned_uvicorn.emit({"state": "WRITERS_PREPARED"}) is False


def test_production_scheduler_pause_waits_active_work_and_resumes(monkeypatch):
    from threading import Event
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler as module
    from app.runtime import RuntimeCoordinator
    for field in type(module.settings).model_fields:
        if field.startswith("enable_"):
            monkeypatch.setattr(module.settings, field, False)
    monkeypatch.setattr(module.settings, "enable_scheduler", True)
    # Keep production factory/type/dispatch; don't schedule market acquisition.
    with monkeypatch.context() as registration:
        registration.setattr(BackgroundScheduler, "add_job", lambda *a, **k: None)
        owner = module.start_scheduler()
    entered, release, after = Event(), Event(), Event()
    def work():
        entered.set()
        release.wait(3)
    try:
        owner.add_job(work, id='fixture_restart_busy_job')
        assert entered.wait(2)
        lease = owner.pause_for_restart()
        assert not owner.restart_quiescent(lease)
        observer = RuntimeCoordinator(schema_lock=object(), background_lock=object())
        observer.scheduler = owner
        busy = observer._scheduler_inflight_evidence()
        assert busy['state'] == 'OBSERVED' and busy['active_instances'] == 1
        assert ('default', 'fixture_restart_busy_job', 1) in busy['jobs']
        assert busy['omitted_job_ids'] == 0
        owner.add_job(after.set)
        release.set()
        deadline = time.monotonic() + 2
        while not owner.restart_quiescent(lease) and time.monotonic() < deadline:
            time.sleep(.01)
        assert owner.restart_quiescent(lease) and not after.is_set()
        quiet = observer._scheduler_inflight_evidence()
        assert quiet['state'] == 'OBSERVED' and quiet['active_instances'] == 0
        assert quiet['jobs'] == []
        owner.resume_after_restart_refusal(lease)
        assert after.wait(2)
    finally:
        release.set()
        owner.shutdown(wait=True)

def test_preflight_scheduler_timeout_preserves_busy_job_and_rearms(restart_runtime, monkeypatch, caplog):
    """Real APScheduler executor stays active until its callback returns."""
    from threading import Event
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler as scheduler_module

    for field in type(scheduler_module.settings).model_fields:
        if field.startswith("enable_"):
            monkeypatch.setattr(scheduler_module.settings, field, False)
    monkeypatch.setattr(scheduler_module.settings, "enable_scheduler", True)
    with monkeypatch.context() as registration:
        registration.setattr(BackgroundScheduler, "add_job", lambda *a, **kw: None)
        owner = scheduler_module.start_scheduler()

    runtime, _, _, _ = restart_runtime
    entered, release = Event(), Event()

    def blocking_callback():
        entered.set()
        release.wait(4)

    try:
        owner.add_job(blocking_callback, id="fixture_retained_scheduler_callback")
        assert entered.wait(2)
        runtime.scheduler = owner
        with caplog.at_level("WARNING", logger="app.runtime"):
            receipt = asyncio.run(runtime.prepare_owned_restart(timeout_seconds=0.25))
        assert receipt == {
            "state": "PREFLIGHT_REARMED",
            "stage": "SCHEDULER_QUIESCENCE",
            "terminal_drain_started": False,
        }
        assert "fixture_retained_scheduler_callback" in caplog.text
        assert "OMI_RESTART_SCHEDULER_QUIESCENCE" in caplog.text
        assert "last_false_remaining_ms=" in caplog.text
        assert "'reason': 'ACTIVE_INSTANCES'" in caplog.text
        assert "'zero_instance_keys': 0" in caplog.text
        assert runtime.http_admission.accepting and runtime._stop_task is None
        assert runtime._restart_guard is None and not runtime._restart_undo
        assert not owner.restart_pause_requested()
    finally:
        release.set()
        owner.shutdown(wait=True)


def test_scheduler_timeout_observation_is_bounded_and_redacted():
    from threading import RLock
    from types import SimpleNamespace
    from app.runtime import RuntimeCoordinator

    held = object()
    owner = SimpleNamespace(
        _omi_admission_lock=RLock(),
        _omi_pause=held,
        state=2,
        _executors_lock=RLock(),
        _executors={"default": SimpleNamespace(
            _lock=RLock(), _instances={
                "fixture_safe": 1,
                "bad job id with secrets": 1,
                "fixture_other": 2,
                "fixture_zero": 0,
            },
        )},
    )
    runtime = RuntimeCoordinator(schema_lock=object(), background_lock=object())
    runtime.scheduler = owner
    observed = runtime._scheduler_inflight_evidence(max_jobs=1, expected_lease=held)
    assert observed["state"] == "OBSERVED"
    assert observed["reason"] == "ACTIVE_INSTANCES"
    assert observed["lease_matches"] is True and observed["scheduler_state"] == 2
    assert observed["active_instances"] == 4
    assert observed["raw_instance_keys"] == 4
    assert observed["zero_instance_keys"] == 1
    assert observed["invalid_instance_keys"] == 0
    assert len(observed["jobs"]) == 1 and observed["omitted_job_ids"] == 2
    assert observed["jobs"][0] == ("default", "fixture_safe", 1)
    assert "bad job id with secrets" not in repr(observed)
    mismatch = runtime._scheduler_inflight_evidence(expected_lease=object())
    assert mismatch["lease_matches"] is False and mismatch["reason"] == "LEASE_MISMATCH"

    owner._omi_pause = None
    assert runtime._scheduler_inflight_evidence()["state"] == "NOT_PAUSED"


def _empty_owned_scheduler_for_restart(monkeypatch):
    """The real owned APScheduler, with all market job registration disabled."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler as scheduler_module

    for name in type(scheduler_module.settings).model_fields:
        if name.startswith("enable_"):
            monkeypatch.setattr(scheduler_module.settings, name, False)
    monkeypatch.setattr(scheduler_module.settings, "enable_scheduler", True)
    with monkeypatch.context() as registration:
        registration.setattr(BackgroundScheduler, "add_job", lambda *args, **kwargs: None)
        return scheduler_module.start_scheduler()


def test_owned_scheduler_zero_key_is_idle_but_invalid_counters_remain_blocking(monkeypatch):
    from app.runtime import RuntimeCoordinator

    owner = _empty_owned_scheduler_for_restart(monkeypatch)
    with owner._executors_lock:
        executor = owner._executors["default"]
    lease = None
    try:
        lease = owner.pause_for_restart()
        with executor._lock:
            executor._instances["fixture_completed_callback"] = 0

        assert owner.restart_quiescent(lease)
        # Do not "fix" executor private state by clearing its accounting.
        assert executor._instances["fixture_completed_callback"] == 0
        observer = RuntimeCoordinator(schema_lock=object(), background_lock=object())
        observer.scheduler = owner
        evidence = observer._scheduler_inflight_evidence(expected_lease=lease)
        assert evidence["state"] == "OBSERVED"
        assert evidence["reason"] == "ZERO_KEYS_ONLY"
        assert evidence["lease_matches"] is True
        assert evidence["active_instances"] == 0
        assert evidence["raw_instance_keys"] == evidence["zero_instance_keys"] == 1
        assert evidence["invalid_instance_keys"] == 0

        assert not owner.restart_quiescent(object())
        assert observer._scheduler_inflight_evidence(expected_lease=object())["reason"] == "LEASE_MISMATCH"
        for count in (1, -1, True, "1", None):
            with executor._lock:
                executor._instances["fixture_completed_callback"] = count
            assert not owner.restart_quiescent(lease), repr(count)
            if type(count) is not int or count < 0:
                evidence = observer._scheduler_inflight_evidence(expected_lease=lease)
                assert evidence["state"] == "UNVERIFIED"
                assert evidence["reason"] == "INVALID_INSTANCE_COUNT"
                assert evidence["invalid_instance_keys"] == 1

        with executor._lock:
            executor._instances.pop("fixture_completed_callback")
        assert owner.restart_quiescent(lease)
        owner.resume_after_restart_refusal(lease)
        assert not owner.restart_quiescent(lease)
    finally:
        with executor._lock:
            executor._instances.pop("fixture_completed_callback", None)
        if owner._omi_pause is not None:
            owner.resume_after_restart_refusal(owner._omi_pause)
        owner.shutdown(wait=True)


def test_production_prepare_zero_count_key_still_runs_all_later_writer_gates(
    restart_runtime, monkeypatch
):
    """A zero key cannot force a false scheduler timeout or skip SQLite fencing."""
    owner = _empty_owned_scheduler_for_restart(monkeypatch)
    runtime, _, _, _ = restart_runtime
    runtime.scheduler = owner
    with owner._executors_lock:
        executor = owner._executors["default"]
    with executor._lock:
        executor._instances["fixture_zero_after_fast_future"] = 0

    async def prepare_and_rearm():
        # PREPARE and its expiry task belong to the same running event loop.
        try:
            outcome = await runtime.prepare_owned_restart(timeout_seconds=1.5)
            assert outcome["state"] == "WRITERS_PREPARED"
            assert runtime._restart_guard is not None and runtime._restart_guard.held
            assert owner.restart_pause_requested()
            assert runtime.abort_owned_restart()
            assert not owner.restart_pause_requested()
        finally:
            if runtime._restart_guard is not None or runtime._restart_undo:
                runtime.abort_owned_restart()

    try:
        asyncio.run(prepare_and_rearm())
        # APScheduler-owned counter remains untouched by the OMI owner.
        assert executor._instances["fixture_zero_after_fast_future"] == 0
    finally:
        with executor._lock:
            executor._instances.pop("fixture_zero_after_fast_future", None)
        if owner._omi_pause is not None:
            owner.resume_after_restart_refusal(owner._omi_pause)
        owner.shutdown(wait=True)


def test_prepare_historical_enqueue_uncertainty_retains_diagnostics_and_runs_writer_gates(
    restart_runtime, monkeypatch, caplog
):
    """Historical durable uncertainty is not an executing writer."""
    from app.jobs import service as job_service

    runtime, _, _, _ = restart_runtime
    monkeypatch.setattr(job_service, "_enqueue_failures", 1)

    async def check():
        start = time.monotonic()
        with caplog.at_level("WARNING", logger="app.runtime"):
            result = await runtime.prepare_owned_restart(timeout_seconds=2)
        elapsed = time.monotonic() - start
        try:
            assert result["state"] == "WRITERS_PREPARED"
            assert elapsed < 1.5
            assert runtime._stop_task is None and runtime._restart_guard.held
            assert job_service._enqueue_failures == 1
            observed = job_service.observe_job_quiescence()
            assert observed["execution_quiescent"] and observed["reconciliation_required"]
        finally:
            assert runtime.abort_owned_restart()
        assert runtime.http_admission.accepting and runtime.owned_restart_rearmed()

    asyncio.run(check())
    assert "OMI_RESTART_JOB_RECONCILIATION_PENDING" in caplog.text
    assert "unresolved_enqueues=1" in caplog.text


@pytest.mark.parametrize("lane", ["default", "market_background"])
@pytest.mark.parametrize("historical_failures", [0, 1])
def test_prepare_job_quiescence_waits_for_real_future_without_forcing_stop(
    restart_runtime, monkeypatch, caplog, lane, historical_failures
):
    """Active JobService Future remains owned on a bounded refused PREPARE."""
    from threading import Event
    from app.jobs import service as job_service
    monkeypatch.setattr(job_service, "_enqueue_failures", historical_failures)

    runtime, _, _, _ = restart_runtime
    entered, release = Event(), Event()

    def work(job_id):
        assert job_id == 3
        entered.set()
        assert release.wait(3)

    job_service.submit_job_task(work, 3, execution_lane=lane)
    assert entered.wait(2)

    async def check():
        with caplog.at_level("WARNING", logger="app.runtime"):
            result = await runtime.prepare_owned_restart(timeout_seconds=0.25)
        assert result == {
            "state": "PREFLIGHT_REARMED",
            "stage": "JOB_QUIESCENCE",
            "terminal_drain_started": False,
        }
        assert runtime.http_admission.accepting and runtime.owned_restart_rearmed()
        assert runtime._stop_task is None and runtime._restart_guard is None
        assert job_service.job_drain_status().pending_by_lane == {lane: 1}

    try:
        asyncio.run(check())
        assert "OMI_RESTART_JOB_QUIESCENCE" in caplog.text
        assert "PENDING_FUTURES" in caplog.text
        assert f"'{lane}': 1" in caplog.text
        assert "'job_id': 3" in caplog.text
        assert "'state': 'running'" in caplog.text
        assert "last_false_evidence=" in caplog.text
    finally:
        release.set()

    async def prepare_after_completion():
        deadline = time.monotonic() + 2
        while job_service.job_drain_status().pending_by_lane:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.002)
        prepared = await runtime.prepare_owned_restart(timeout_seconds=1)
        assert prepared["state"] == "WRITERS_PREPARED"
        assert runtime.abort_owned_restart()

    asyncio.run(prepare_after_completion())
