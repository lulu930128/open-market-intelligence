"""Real WAL contention at the US persistence owner; no provider IO or sleeps."""

import json
from threading import Event, Thread
from time import monotonic

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.db.models import Base, MarketIntradayBar, MarketIntradayBarLineage, SourceRegistry
from app.db.session import SessionLocal
from app.market_data.contracts import BarFinalization
from app.us_market.intraday_transaction import USIntradayBarTransaction
from test_us_intraday_receipt_ordering import db_engine, _batch, _persist, _state


@pytest.mark.parametrize("committed", [False, True])
def test_deferred_read_upgrade_distinguishes_active_writer_from_stale_snapshot(db_engine, committed):
    _persist(db_engine, _batch(0, "100"))
    with SessionLocal(bind=db_engine) as reader, SessionLocal(bind=db_engine) as writer:
        reader.connection().exec_driver_sql("BEGIN")
        assert reader.query(MarketIntradayBar).one().close_price == 100
        writer.query(MarketIntradayBar).one().close_price = 110
        writer.flush()
        if committed:
            writer.commit()
        started = monotonic()
        with pytest.raises(OperationalError) as caught:
            reader.query(MarketIntradayBar).update({MarketIntradayBar.close_price: 90})
        elapsed = monotonic() - started
        assert caught.value.orig.sqlite_errorcode == (517 if committed else 5)
        print(json.dumps({"probe": "deferred_upgrade", "other_committed": committed,
            "sqlite_errorcode": caught.value.orig.sqlite_errorcode,
            "failure_seconds": elapsed, "configured_busy_timeout_ms": 30000}))
        reader.rollback()
        if not committed:
            writer.commit()
    assert _state(db_engine)[0] == 110


@pytest.mark.parametrize("cached_raw", [False, True])
def test_active_writer_admission_waits_then_reads_new_version(db_engine, cached_raw):
    _persist(db_engine, _batch(0, "100", BarFinalization.PROVISIONAL))
    old, new = _batch(2, "90"), _batch(3, "110", BarFinalization.CORRECTED)
    if cached_raw:
        with SessionLocal(bind=db_engine) as seed:
            USIntradayBarTransaction(seed)._raw.source_and_raw(old[1].receipts[0])
            seed.commit()
    held, release, entered, finished = Event(), Event(), Event(), Event()
    outcomes, times, first_dml = {}, {}, []

    def holder():
        with SessionLocal(bind=db_engine) as db:
            commit = db.commit

            def hold_before_commit():
                times["holder_ready"] = monotonic()
                held.set()
                assert release.wait(10), "test did not release known writer"
                commit()
                times["holder_committed"] = monotonic()

            db.commit = hold_before_commit
            try:
                outcomes["holder"] = USIntradayBarTransaction(db).persist_bar_acquisition(*new)
            except Exception as exc:
                outcomes["holder"] = exc

    def contender():
        with SessionLocal(bind=db_engine) as db:
            connection = db.connection()

            def record(_conn, _cursor, statement, _params, _ctx, _many):
                if statement.startswith("BEGIN"):
                    times["begin_entered"] = monotonic()
                    entered.set()
                if statement.startswith(("INSERT", "UPDATE", "DELETE")):
                    first_dml.append(statement.split(" (")[0].split(" SET")[0])

            event.listen(connection, "before_cursor_execute", record)
            event.listen(connection, "after_cursor_execute", lambda _c, _u, sql, *_args:
                times.update(admitted=monotonic()) if sql.startswith("BEGIN") else None)
            try:
                outcomes["contender"] = USIntradayBarTransaction(db).persist_bar_acquisition(*old)
            except Exception as exc:
                outcomes["contender"] = exc
            finally:
                times["contender_finished"] = monotonic()
                finished.set()

    holder_thread = Thread(target=holder)
    contender_thread = Thread(target=contender)
    holder_thread.start()
    try:
        assert held.wait(10)
        contender_thread.start()
        assert entered.wait(10)
        # Observe while the known holder is still uncommitted. This bounded
        # Event wait measures early failure vs waiting; correctness uses the
        # committed result/order, not a fragile wall-clock speed threshold.
        completed_while_held = finished.wait(0.2)
    finally:
        times["holder_release"] = monotonic()
        release.set()
        holder_thread.join(10)
        if contender_thread.ident is not None:
            contender_thread.join(10)
    assert not holder_thread.is_alive() and not contender_thread.is_alive()
    outcome = outcomes["contender"]
    print(json.dumps({"probe": "owner_admission", "cached_raw": cached_raw,
        "completed_while_held": completed_while_held,
        "sqlite_errorcode": getattr(getattr(outcome, "orig", None), "sqlite_errorcode", None),
        "first_dml": first_dml[:1],
        "known_holder_seconds": times["holder_release"] - times["holder_ready"],
        "begin_to_result_seconds": times["contender_finished"] - times["begin_entered"],
        "admitted_to_result_seconds": times["contender_finished"] - times["admitted"]}))
    assert outcomes["holder"].committed
    assert not isinstance(outcome, Exception), repr(outcome)
    assert outcome.committed and outcome.observations_written == 0 and outcome.observations_unchanged == 1
    assert not completed_while_held
    assert times["contender_finished"] >= times["holder_committed"]
    assert _state(db_engine)[:4] == (
        110, "corrected", new[1].receipts[0].fetched_at.replace(tzinfo=None), new[1].receipts[0].content_hash)


@pytest.mark.parametrize("physical_write", [False, True])
def test_admission_preserves_pending_caller_work_and_refreshes_stale_orm(db_engine, physical_write):
    _persist(db_engine, _batch(0, "100"))
    with SessionLocal(bind=db_engine) as caller:
        held_bar = caller.query(MarketIntradayBar).one()
        held_lineage = caller.query(MarketIntradayBarLineage).one()
        _persist(db_engine, _batch(3, "110", BarFinalization.CORRECTED))
        source = caller.query(SourceRegistry).one()
        source.reliability_level = "caller-note"
        pending = SourceRegistry(source_name="pending-caller", source_type="api", category="fixture")
        caller.add(pending)
        if physical_write:
            caller.flush()
        connection = caller.connection()
        assert connection.connection.driver_connection.in_transaction is physical_write
        boundaries = []
        event.listen(connection, "before_cursor_execute", lambda _c, _u, sql, *_args: boundaries.append(sql)
            if sql.startswith(("BEGIN", "ROLLBACK")) else None)
        result = USIntradayBarTransaction(caller).persist_bar_acquisition(*_batch(2, "90"))
        assert result.committed and result.observations_unchanged == 1
        assert held_bar.close_price == 110 and held_lineage.finalization == "corrected"
        assert pending.id is not None and source.reliability_level == "caller-note"
        assert boundaries == ([] if physical_write else ["BEGIN IMMEDIATE"])
    with SessionLocal(bind=db_engine) as check:
        assert check.query(SourceRegistry).filter_by(source_name="pending-caller").count() == 1
        assert check.query(SourceRegistry).filter_by(reliability_level="caller-note").count() == 1


def test_existing_read_with_pending_work_cannot_silently_drop_it_on_snapshot_retry(db_engine):
    _persist(db_engine, _batch(0, "100"))
    with SessionLocal(bind=db_engine) as caller:
        caller.connection().exec_driver_sql("BEGIN")
        assert caller.query(MarketIntradayBar).one().close_price == 100
        caller.add(SourceRegistry(source_name="pending-caller", source_type="api", category="fixture"))
        _persist(db_engine, _batch(3, "110", BarFinalization.CORRECTED))
        # The existing transaction is atomic, so failure rolls it all back.
        # Returning success after replaying only the acquisition would silently
        # lose the caller's pending work. That outcome is not recoverable here.
        try:
            outcome = USIntradayBarTransaction(caller).persist_bar_acquisition(*_batch(2, "90"))
        except OperationalError as exc:
            outcome = exc
        transaction_closed = not caller.in_transaction()
    with SessionLocal(bind=db_engine) as check:
        pending_count = check.query(SourceRegistry).filter_by(source_name="pending-caller").count()
    print(json.dumps({"probe": "caller_pending_replay", "returned_committed": getattr(outcome, "committed", None),
        "sqlite_errorcode": getattr(getattr(outcome, "orig", None), "sqlite_errorcode", None),
        "pending_rows": pending_count}))
    assert isinstance(outcome, OperationalError), "success must not hide rolled-back caller work"
    assert outcome.orig.sqlite_errorcode == 517 and transaction_closed
    assert _state(db_engine)[:2] == (110, "corrected")


def _native_snapshot_error(engine):
    """Capture a real 517 to inject into failure handling, not fake a write race.

    An already-active WAL writer cannot naturally get a stale-read upgrade.
    Injection tests the retry contract without claiming otherwise.
    """
    with SessionLocal(bind=engine) as reader, SessionLocal(bind=engine) as other:
        reader.connection().exec_driver_sql("BEGIN")
        reader.query(SourceRegistry).one()
        other.query(SourceRegistry).one().reliability_level = "fixture-517"
        other.commit()
        with pytest.raises(OperationalError) as caught:
            reader.query(SourceRegistry).update({SourceRegistry.reliability_level: "stale"})
        reader.rollback()
        assert caught.value.orig.sqlite_errorcode == 517
        return caught.value


def test_flushed_caller_work_cannot_be_omitted_by_snapshot_replay(db_engine, monkeypatch):
    _persist(db_engine, _batch(0, "100"))
    snapshot_error = _native_snapshot_error(db_engine)
    with SessionLocal(bind=db_engine) as caller:
        caller.add(SourceRegistry(source_name="flushed-caller", source_type="api", category="fixture"))
        caller.flush()
        assert not caller.new and not caller.dirty and not caller.deleted
        assert caller.connection().connection.driver_connection.in_transaction
        owner = USIntradayBarTransaction(caller)
        flush = caller.flush
        failures = []

        def fail_once(*args, **kwargs):
            if not failures:
                failures.append(True)
                raise snapshot_error
            return flush(*args, **kwargs)

        monkeypatch.setattr(caller, "flush", fail_once)
        try:
            outcome = owner.persist_bar_acquisition(*_batch(2, "90"))
        except OperationalError as exc:
            outcome = exc
    with SessionLocal(bind=db_engine) as check:
        count = check.query(SourceRegistry).filter_by(source_name="flushed-caller").count()
    print(json.dumps({"probe": "flushed_caller_replay", "fault_injection": "captured_native_517",
        "returned_committed": getattr(outcome, "committed", None), "caller_rows": count}))
    assert isinstance(outcome, OperationalError), "success must not hide rolled-back flushed caller DML"
    assert outcome.orig.sqlite_errorcode == 517
    assert _state(db_engine)[0] == 100


@pytest.mark.parametrize("failure_count", [1, 2])
def test_owned_snapshot_recovery_remains_bounded(db_engine, monkeypatch, failure_count):
    _persist(db_engine, _batch(0, "100"))
    snapshot_error = _native_snapshot_error(db_engine)
    with SessionLocal(bind=db_engine) as db:
        owner = USIntradayBarTransaction(db)
        attempts, failures = [], []
        attempt, flush = owner._persist_bar_acquisition_attempt, db.flush
        acquisition = _batch(2, "110")

        def record_attempt(requirement, acquired, **kwargs):
            assert acquired is acquisition[1]
            attempts.append(kwargs["retry_snapshot"])
            return attempt(requirement, acquired, **kwargs)

        def fail_flush(*args, **kwargs):
            if len(failures) < failure_count:
                failures.append(True)
                raise snapshot_error
            return flush(*args, **kwargs)

        monkeypatch.setattr(owner, "_persist_bar_acquisition_attempt", record_attempt)
        monkeypatch.setattr(db, "flush", fail_flush)
        if failure_count == 1:
            assert owner.persist_bar_acquisition(*acquisition).committed
        else:
            with pytest.raises(OperationalError):
                owner.persist_bar_acquisition(*acquisition)
        assert attempts == [True, False]
        assert not db.in_transaction()
    assert _state(db_engine)[0] == (110 if failure_count == 1 else 100)


def test_immediate_admission_timeout_fails_once_before_any_persistence_read(db_engine, monkeypatch):
    _persist(db_engine, _batch(0, "100"))
    with SessionLocal(bind=db_engine) as holder, SessionLocal(bind=db_engine) as contender:
        holder.query(MarketIntradayBar).one().close_price = 110
        holder.flush()
        connection = contender.connection()
        # Fixture-only shorter timeout makes the exhaustion case bounded.
        # Production remains 30000 ms; no global/session config is changed.
        connection.exec_driver_sql("PRAGMA busy_timeout=80")
        statements, attempts, rollbacks = [], [], []
        event.listen(connection, "before_cursor_execute", lambda _c, _u, sql, *_args: statements.append(sql))
        owner = USIntradayBarTransaction(contender)
        attempt, rollback = owner._persist_bar_acquisition_attempt, contender.rollback

        def record_attempt(*args, **kwargs):
            attempts.append(True)
            return attempt(*args, **kwargs)

        def record_rollback():
            rollbacks.append(True)
            return rollback()

        monkeypatch.setattr(owner, "_persist_bar_acquisition_attempt", record_attempt)
        monkeypatch.setattr(contender, "rollback", record_rollback)
        started = monotonic()
        with pytest.raises(OperationalError) as caught:
            owner.persist_bar_acquisition(*_batch(2, "90"))
        print(json.dumps({"probe": "admission_timeout", "sqlite_errorcode": caught.value.orig.sqlite_errorcode,
            "elapsed_seconds": monotonic() - started, "fixture_busy_timeout_ms": 80}))
        assert caught.value.orig.sqlite_errorcode == 5
        assert statements == ["BEGIN IMMEDIATE"]
        assert attempts == rollbacks == [True] and not contender.in_transaction()
        holder.commit()
    assert _state(db_engine)[0] == 110


def test_real_platform_acquires_before_physical_write_admission(db_engine):
    from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
    from app.us_market.intraday_platform import USIntradayMarketPlatform
    from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
    from test_us_intraday_shared_core import _yahoo_payload
    from test_us_g1b_scheduler_gateway import NOW

    Base.metadata.create_all(db_engine)
    fetches, admissions = [], []
    with SessionLocal(bind=db_engine) as db:
        def fetch(_route, _requirement):
            fetches.append(True)
            assert db.in_transaction()  # Normal reader has SQLAlchemy autobegin.
            assert not db.connection().connection.driver_connection.in_transaction
            assert not admissions
            # Independent writer can commit during fixture IO: reservation is
            # not held across the provider/acquisition phase.
            with SessionLocal(bind=db_engine) as other:
                other.add(SourceRegistry(source_name="during-acquisition", source_type="api", category="fixture"))
                other.commit()
            payload = _yahoo_payload(NOW, age_seconds=30)
            payload["chart"]["result"][0]["meta"]["symbol"] = "^DJI"
            return payload, "https://fixture.invalid/bars"

        connection = db.connection()
        event.listen(connection, "before_cursor_execute", lambda _c, _u, sql, *_args:
            admissions.append(sql) if sql.startswith("BEGIN") else None)
        platform = USIntradayMarketPlatform(db,
            acquisition=USIntradayAcquisitionExecutor(fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: NOW),
            bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,))
        result = platform.refresh_intraday_bars(symbol="^DJI", bars=100, now=NOW, max_provider_calls=1)
        assert fetches == [True] and admissions == ["BEGIN IMMEDIATE"]
        assert result.result.acquisition.external_calls == 1 and result.result.persistence.committed
        assert result.result.persistence.observations_written == 1
        assert db.query(SourceRegistry).filter_by(source_name="during-acquisition").count() == 1
