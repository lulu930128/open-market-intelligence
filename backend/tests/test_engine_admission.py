"""Canonical Engine fence with disposable databases only; no production imports."""
import asyncio
import time
from threading import Event, Thread

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.admission import EngineAdmission, EngineAdmissionClosed
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


def engine_owner(tmp_path, **kwargs):
    engine = create_engine("sqlite:///" + (tmp_path / "fence.sqlite").as_posix(),
                           connect_args={"check_same_thread": False}, **kwargs)
    return engine, EngineAdmission(engine)


def drain(owner, seconds=0):
    return asyncio.run(owner.drain(deadline=time.monotonic() + seconds))


@pytest.mark.parametrize("pool", [None, NullPool])
@pytest.mark.parametrize("kind", ["session", "connection", "raw"])
def test_actual_borrowed_connection_blocks_drain_and_new_io(tmp_path, pool, kind):
    engine, owner = engine_owner(tmp_path, **({"poolclass": pool} if pool else {}))
    db = Session(engine) if kind == "session" else engine.connect() if kind == "connection" else engine.raw_connection()
    try:
        if kind != "raw":
            db.execute(text("CREATE TABLE IF NOT EXISTS receipt (value INTEGER)"))
            db.execute(text("INSERT INTO receipt VALUES (7)"))
        result = drain(owner)
        assert result.state == "timeout" and result.active_connections == 1
        with pytest.raises(EngineAdmissionClosed):
            engine.connect()
        # Existing owner completes under original transaction ownership.
        db.rollback()
    finally:
        db.close()
    assert drain(owner, 1).drained
    assert not drain(owner).all_writers_drained
    # Closed Session reuse cannot reopen this Engine after the fence.
    with pytest.raises(EngineAdmissionClosed):
        with Session(engine) as late:
            late.execute(text("SELECT 1"))
    engine.dispose()


@pytest.mark.parametrize("escape", ["detach", "invalidate"])
def test_driver_escape_released_only_after_actual_driver_close(tmp_path, escape):
    engine, owner = engine_owner(tmp_path)
    connection = engine.connect()
    getattr(connection, escape)()
    connection.close()
    result = drain(owner)
    assert result.drained and result.unknown_connections == 0
    engine.dispose()


def test_constructor_reservation_survives_closure(tmp_path, monkeypatch):
    engine, owner = engine_owner(tmp_path, poolclass=NullPool)
    entered, release, acquired, finish = (Event() for _ in range(4))
    original = engine.dialect.connect
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine.dialect, "connect", delayed)
    errors = []
    def work():
        try:
            with engine.connect() as db:
                acquired.set()
                assert finish.wait(3)
                assert db.execute(text("SELECT 1")).scalar() == 1
        except BaseException as exc:
            errors.append(exc)
    thread = Thread(target=work)
    thread.start()
    try:
        assert entered.wait(2)
        assert drain(owner).pending_constructors == 1
        release.set()
        assert acquired.wait(2)
        assert not drain(owner).drained
    finally:
        release.set(); finish.set(); thread.join(4)
    assert not thread.is_alive() and not errors
    assert drain(owner, 1).drained
    engine.dispose()


def test_preflight_does_not_close_admission(tmp_path):
    engine, owner = engine_owner(tmp_path)
    result = owner.status(deadline=time.monotonic())
    assert result.state == "accepting" and not result.admission_closed
    with engine.connect() as db:
        assert db.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()


def test_normal_reconnect_resolves_closed_previous_handle(tmp_path):
    engine, owner = engine_owner(tmp_path)
    with engine.connect() as db:
        db.invalidate()
        # Availability before drain is unchanged; uncertainty is retained.
        assert db.execute(text("SELECT 1")).scalar() == 1
    result = drain(owner)
    assert result.drained and result.unknown_connections == 0
    engine.dispose()


def test_late_old_driver_close_cannot_release_reused_pool_record(tmp_path):
    engine, owner = engine_owner(tmp_path)
    record = object()
    old = owner._connect(engine.dialect, record, [":memory:"], {})
    owner._uncertain(old, record)
    replacement = owner._connect(engine.dialect, record, [":memory:"], {})
    try:
        owner.begin_drain()
        assert owner.status(deadline=time.monotonic()).unknown_connections == 1
        old.close()
        result = owner.status(deadline=time.monotonic())
        assert result.active_connections == 1 and result.unknown_connections == 0
        assert result.state == "timeout" and not result.drained
        # Repeated late close is also bound to the old physical token.
        old.close()
        assert owner.status(deadline=time.monotonic()).active_connections == 1
        assert replacement.execute("SELECT 1").fetchone() == (1,)
    finally:
        old.close()
        replacement.close()
        engine.dispose()
    assert owner.status(deadline=time.monotonic() + 1).drained


def test_runtime_preflight_is_observation_and_late_exit_cannot_upgrade_drain(tmp_path, monkeypatch):
    from app.db import session
    from app.runtime import RuntimeCoordinator, RuntimeDrainError
    engine, owner = engine_owner(tmp_path)
    monkeypatch.setattr(session, "engine_admission", owner)
    runtime = RuntimeCoordinator(drain_engine_connections=True)
    assert not runtime.restart_preflight()["all_writers_drained"]
    assert not owner.status(deadline=time.monotonic()).admission_closed
    borrowed = engine.connect()
    try:
        with pytest.raises(RuntimeDrainError) as error:
            asyncio.run(runtime.stop(timeout_seconds=0))
        receipt = error.value.result
        assert receipt.engine_connections.state == "timeout"
        assert not receipt.all_writers_drained
    finally:
        borrowed.close()
    assert owner.status(deadline=time.monotonic() + 1).drained
    assert runtime.drain_result is receipt and receipt.state == "INCOMPLETE"
    assert runtime.restart_preflight()["registered_drain_state"] == "INCOMPLETE"
    engine.dispose()
