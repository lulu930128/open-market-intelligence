"""Durable observation ordering using production Sessions and file-backed WAL."""

from dataclasses import replace
from datetime import timedelta
import json
import math
import sqlite3
from threading import Event, Thread

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.db.models import MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult, USIntradayObservationState
from app.db.session import SessionLocal
from app.us_market.intraday_transaction import USIntradayBarTransaction
from test_us_intraday_receipt_ordering import START, _batch, _persist, _state, db_engine


def _watermarks(engine):
    with SessionLocal(bind=engine) as db:
        return [(s.bar_id, s.observed_fetched_at, s.observed_content_hash)
                for s in db.query(USIntradayObservationState).order_by(USIntradayObservationState.bar_id)]


def _four_tables(engine):
    with SessionLocal(bind=engine) as db:
        return {model.__tablename__: list(db.execute(select(model.__table__).order_by(
            *model.__table__.primary_key.columns)).mappings()) for model in (
                RawFetchResult, MarketIntradayBar, MarketIntradayBarLineage, USIntradayObservationState)}


def test_t1_cached_identity_map_rereads_t3_noop_before_late_t2(db_engine):
    _persist(db_engine, _batch(1, "100"))
    with SessionLocal(bind=db_engine) as old:
        # Retain strong references to all stale ORM instances, including state.
        cached_bar = old.query(MarketIntradayBar).one()
        cached_lineage = old.query(MarketIntradayBarLineage).one()
        cached_state = old.query(USIntradayObservationState).one()
        assert not old.connection().connection.driver_connection.in_transaction
        original_lineage_time = cached_lineage.fetched_at
        _persist(db_engine, _batch(3, "100"))  # Independent committed Session.
        assert cached_state.observed_fetched_at == original_lineage_time
        result = USIntradayBarTransaction(old).persist_bar_acquisition(*_batch(2, "90"))
        assert result.observations_unchanged == 1 and result.observations_written == 0
        assert cached_bar.close_price == 100 and cached_lineage.fetched_at == original_lineage_time
        assert cached_state.observed_fetched_at == _batch(3, "100")[1].receipts[0].fetched_at.replace(tzinfo=None)
    assert _state(db_engine)[0] == 100


@pytest.mark.parametrize("same_payload", [False, True])
def test_noop_watermark_survives_reopen_and_raw_gc(db_engine, same_payload, monkeypatch):
    original = _batch(1, "100")
    _persist(db_engine, original)
    canonical = _state(db_engine)
    invalidations = []
    monkeypatch.setattr("app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache", invalidations.append)
    latest = _batch(3, "100", payload=original[1].receipts[0].raw_text if same_payload else None)
    result = _persist(db_engine, latest)
    assert result.observations_written == 0 and result.observations_unchanged == 1
    assert invalidations == [] and _state(db_engine) == canonical
    assert _watermarks(db_engine)[0][1:] == (
        latest[1].receipts[0].fetched_at.replace(tzinfo=None), latest[1].receipts[0].content_hash)
    with SessionLocal(bind=db_engine) as db:
        # Only noncanonical no-op raw is removed. The state has no raw FK.
        db.query(RawFetchResult).filter(RawFetchResult.id != canonical[-1]).delete()
        db.commit()
    db_engine.dispose()  # Reopen connections and Sessions, not process-local state.
    _persist(db_engine, _batch(2, "90"))
    assert _state(db_engine) == canonical


def test_equal_time_uses_latest_observed_hash_not_materialized_hash(db_engine):
    original, latest = _batch(1, "100"), _batch(3, "100")
    _persist(db_engine, original)
    _persist(db_engine, latest)
    before = _watermarks(db_engine), _state(db_engine)
    assert _persist(db_engine, latest).observations_unchanged == 1
    old_hash_at_latest_time = _batch(3, "100", payload=original[1].receipts[0].raw_text)
    with pytest.raises(ValueError, match="US_INTRADAY_RECEIPT_TIME_CONFLICT"):
        _persist(db_engine, old_hash_at_latest_time)
    assert (_watermarks(db_engine), _state(db_engine)) == before


def test_legacy_exact_replay_does_not_invent_watermark(db_engine):
    original = _batch(1, "100")
    _persist(db_engine, original)
    with SessionLocal(bind=db_engine) as db:
        db.query(USIntradayObservationState).delete()
        db.commit()
    statements = []
    def record(_c, _cu, sql, _p, _ctx, _many):
        statements.append(sql)
    event.listen(db_engine, "before_cursor_execute", record)
    _persist(db_engine, original)
    event.remove(db_engine, "before_cursor_execute", record)
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    assert _watermarks(db_engine) == []
    _persist(db_engine, _batch(3, "100"))
    _persist(db_engine, _batch(2, "90"))
    assert _state(db_engine)[0] == 100


def test_effective_precedence_retains_newer_stored_lineage(db_engine):
    _persist(db_engine, _batch(3, "100"))
    with SessionLocal(bind=db_engine) as db:
        state = db.query(USIntradayObservationState).one()
        state.observed_fetched_at = _batch(1, "90")[1].receipts[0].fetched_at
        state.observed_content_hash = _batch(1, "90")[1].receipts[0].content_hash
        db.commit()
    before = _state(db_engine)
    _persist(db_engine, _batch(2, "90"))
    assert _state(db_engine) == before
    _persist(db_engine, _batch(4, "110"))
    assert _state(db_engine)[0] == 110
    assert _watermarks(db_engine)[0][1] == _batch(4, "110")[1].receipts[0].fetched_at.replace(tzinfo=None)


def _many_batch(tick, count):
    requirement, acquisition = _batch(tick, "100")
    bar = acquisition.observations[0]
    bars = tuple(bar.model_copy(update={"start_at": START + timedelta(minutes=i),
        "end_at": START + timedelta(minutes=i + 1)}) for i in range(count))
    return requirement, replace(acquisition, observations=bars)


@pytest.mark.parametrize("count", [260, 390, 1000])
def test_batch_watermark_queries_and_writes_are_bounded(db_engine, monkeypatch, count):
    reports = []
    for phase in ("first_materialization", "newer_noop", "exact_replay"):
        first, replay = phase == "first_materialization", phase == "exact_replay"
        batch = _many_batch(1 if first else 3, count)
        statements, flushes, commits = [], [], []
        def record(_c, _cu, sql, params, _ctx, many):
            statements.append((sql, len(params) if many else 1))
        event.listen(db_engine, "before_cursor_execute", record)
        with SessionLocal(bind=db_engine) as db:
            flush, commit = db.flush, db.commit
            def tracked_flush(*args, **kwargs):
                flushes.append(1)
                return flush(*args, **kwargs)
            def tracked_commit():
                commits.append(1)
                return commit()
            monkeypatch.setattr(db, "flush", tracked_flush)
            monkeypatch.setattr(db, "commit", tracked_commit)
            result = USIntradayBarTransaction(db).persist_bar_acquisition(*batch)
        event.remove(db_engine, "before_cursor_execute", record)
        state_reads = [sql for sql, _ in statements if sql.startswith("SELECT") and "FROM us_intraday_observation_state" in sql]
        state_writes = [(sql, n) for sql, n in statements if sql.startswith("UPDATE us_intraday_observation_state")]
        state_inserts = [(sql, n) for sql, n in statements if sql.startswith("INSERT INTO us_intraday_observation_state")]
        dml = [sql for sql, _ in statements if sql.startswith(("UPDATE", "INSERT", "DELETE"))]
        assert len(state_reads) == (0 if first else math.ceil(count / 500))
        assert all(sql.count("?") <= 500 for sql in state_reads)
        assert len(flushes) <= 5 and len(commits) == 1
        assert sum(s.startswith("SELECT") for s, _ in statements) == (3 if first else 4 + math.ceil(count / 500))
        assert result.observations_written == (count if first else 0)
        assert result.observations_unchanged == (0 if first else count)
        if first:
            assert len(state_inserts) == 1 and state_inserts[0][1] == count
        elif replay:
            assert dml == []
        else:
            assert len(state_writes) == 1 and state_writes[0][1] == count
        reports.append(dict(bars=count, phase=phase, exact_replay=replay, selects=sum(s.startswith("SELECT") for s, _ in statements),
            state_selects=len(state_reads), state_update_batches=len(state_writes), state_insert_batches=len(state_inserts), dml_statements=len(dml),
            flushes=len(flushes), commits=len(commits)))
    print("SQL_COUNTS=" + json.dumps(reports, sort_keys=True))


def test_state_flush_failure_rolls_back_entire_acquisition(db_engine, monkeypatch):
    _persist(db_engine, _batch(1, "100"))
    before = _four_tables(db_engine)
    with SessionLocal(bind=db_engine) as db:
        flush = db.flush
        def fail_after_state_dml(*args, **kwargs):
            changed = any(isinstance(s, USIntradayObservationState) for s in db.dirty)
            flush(*args, **kwargs)
            if changed:
                assert db.query(USIntradayObservationState).one().observed_fetched_at == _batch(3, "110")[1].receipts[0].fetched_at
                raise RuntimeError("after real state flush")
        monkeypatch.setattr(db, "flush", fail_after_state_dml)
        with pytest.raises(RuntimeError, match="after real state flush"):
            USIntradayBarTransaction(db).persist_bar_acquisition(*_batch(3, "110"))
    assert _four_tables(db_engine) == before


def test_later_key_time_conflict_rolls_back_raw_and_earlier_bar_mutation(db_engine):
    _persist(db_engine, _many_batch(1, 2))
    requirement, later = _many_batch(3, 2)
    _persist(db_engine, (requirement, replace(later, observations=(later.observations[1],))))
    before = _four_tables(db_engine)
    requirement, conflicting = _batch(3, "110", payload='{"conflict":"latest-observed"}')
    first = conflicting.observations[0]
    second = first.model_copy(update={"start_at": START + timedelta(minutes=1),
                                      "end_at": START + timedelta(minutes=2)})
    with pytest.raises(ValueError, match="US_INTRADAY_RECEIPT_TIME_CONFLICT"):
        _persist(db_engine, (requirement, replace(conflicting, observations=(first, second))))
    assert _four_tables(db_engine) == before


@pytest.mark.parametrize("first_tick", [2, 3])
@pytest.mark.parametrize("first_insert", [False, True])
def test_wal_two_sessions_order_completion_with_state(db_engine, first_tick, first_insert):
    if not first_insert:
        _persist(db_engine, _batch(1, "100"))
    batches = {2: _batch(2, "90"), 3: _batch(3, "100")}
    holder_ready, contender_entered, release_holder = Event(), Event(), Event()
    results, failures = [], []
    def observe_begin(_conn, _cur, sql, _params, _ctx, _many):
        if sql == "BEGIN IMMEDIATE" and holder_ready.is_set():
            contender_entered.set()
    event.listen(db_engine, "before_cursor_execute", observe_begin)
    def run(tick, holder):
        try:
            with SessionLocal(bind=db_engine) as db:
                if holder:
                    commit = db.commit
                    def held_commit():
                        holder_ready.set()
                        assert release_holder.wait(10)
                        commit()
                    db.commit = held_commit
                results.append(USIntradayBarTransaction(db).persist_bar_acquisition(*batches[tick]))
        except BaseException as exc:
            failures.append(exc)
    first = Thread(target=run, args=(first_tick, True))
    second = Thread(target=run, args=(5 - first_tick, False))
    first.start()
    try:
        assert holder_ready.wait(10)
        second.start()
        assert contender_entered.wait(10)
    finally:
        release_holder.set()
        first.join(10)
        if second.ident is not None:
            second.join(10)
        event.remove(db_engine, "before_cursor_execute", observe_begin)
    assert not first.is_alive() and not second.is_alive() and failures == []
    assert len(results) == 2 and all(r.committed for r in results)
    assert _state(db_engine)[0] == 100
    assert _watermarks(db_engine)[0][1:] == (batches[3][1].receipts[0].fetched_at.replace(tzinfo=None),
                                           batches[3][1].receipts[0].content_hash)
    with SessionLocal(bind=db_engine) as db:
        assert db.query(MarketIntradayBar).count() == db.query(USIntradayObservationState).count() == 1


def test_owned_517_fault_recovery_rereads_committed_watermark(db_engine, monkeypatch):
    """Fault injection at precommit, not a claim that IMMEDIATE naturally gets 517."""
    _persist(db_engine, _batch(1, "100"))
    with SessionLocal(bind=db_engine) as db:
        flush, rollback = db.flush, db.rollback
        failed, attempts = [], []
        owner = USIntradayBarTransaction(db)
        attempt = owner._persist_bar_acquisition_attempt
        def track(requirement, acquisition, *, retry_snapshot):
            attempts.append(acquisition)
            return attempt(requirement, acquisition, retry_snapshot=retry_snapshot)
        def fail_after_state(*args, **kwargs):
            changed = any(isinstance(s, USIntradayObservationState) for s in db.dirty)
            flush(*args, **kwargs)
            if changed and not failed:
                failed.append(True)
                cause = sqlite3.OperationalError("injected precommit snapshot conflict")
                cause.sqlite_errorcode = 517
                raise OperationalError("fixture", {}, cause)
        def rollback_then_newer():
            rollback()
            _persist(db_engine, _batch(3, "100"))
        monkeypatch.setattr(owner, "_persist_bar_acquisition_attempt", track)
        monkeypatch.setattr(db, "flush", fail_after_state)
        monkeypatch.setattr(db, "rollback", rollback_then_newer)
        result = owner.persist_bar_acquisition(*_batch(2, "90"))
    assert len(attempts) == 2 and attempts[0] is attempts[1]
    assert result.observations_written == 0 and result.observations_unchanged == 1
    assert _state(db_engine)[0] == 100
    assert _watermarks(db_engine)[0][1] == _batch(3, "100")[1].receipts[0].fetched_at.replace(tzinfo=None)
