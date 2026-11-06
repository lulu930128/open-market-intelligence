"""Stored-version ordering; real SQLite snapshots, with no provider IO."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
from threading import Event, Thread

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Query
from sqlalchemy.pool import NullPool

from app.db.models import Base, MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult, SourceRegistry, USIntradayObservationState
from app.db.session import SessionLocal
from app.market_data.contracts import AuthorityClass, BarFinalization, BarObservation, MarketSession, SourceLineage
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import BarCapabilityRequest, DataRequirementV2, FreshnessRequirement, InstrumentTarget
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.us_market.intraday_transaction import USIntradayBarTransaction
from app.us_market.market_data.descriptors import MASSIVE_INDEX_INTRADAY_RESOURCE_ID
from test_us_massive_persistence import _bounds, _instrument, _receipt, _summary


START = datetime(2026, 9, 1, 19, 58, tzinfo=timezone.utc)


@pytest.fixture
def db_engine(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'receipt-order.db'}",
        connect_args={"check_same_thread": False, "timeout": 30}, poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA busy_timeout=30000")

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    Base.metadata.create_all(engine, tables=[
        SourceRegistry.__table__, RawFetchResult.__table__,
        MarketIntradayBar.__table__, MarketIntradayBarLineage.__table__,
        USIntradayObservationState.__table__,
    ])
    yield engine
    engine.dispose()


def _batch(tick, price, finalization=BarFinalization.FINAL, *, payload=None):
    fetched = START + timedelta(minutes=2, seconds=tick)
    receipt = _receipt(
        resource_id=MASSIVE_INDEX_INTRADAY_RESOURCE_ID,
        source="massive.indices.aggregates.1m", parser_version="massive.indices.aggregates.v2",
        raw_text=payload or f'{{"tick":{tick},"price":{price}}}', fetched_at=fetched,
    )
    bar = BarObservation(
        instrument=_instrument(), interval="1m", start_at=START, end_at=START + timedelta(minutes=1),
        lineage=SourceLineage(provider=receipt.provider, source=receipt.source,
            authority=AuthorityClass.VENDOR, raw_contract_version=receipt.parser_version,
            event_at=START, fetched_at=fetched, content_hash=receipt.content_hash),
        open_price=Decimal(price), high_price=Decimal(price), low_price=Decimal(price), close_price=Decimal(price),
        volume=None, volume_status="not_applicable", price_basis="raw", finalization=finalization,
    )
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=bar.instrument),
        request=BarCapabilityRequest(capability_id="intraday.bars", interval="1m",
            start_at=START, end_at=START + timedelta(minutes=2), max_bars=2),
        purpose=DataPurpose.RESEARCH, realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CONTINUOUS, requested_at=fetched,
        freshness=FreshnessRequirement(max_age_seconds=180), bounds=_bounds(),
    )
    return requirement, BarAcquisitionResult(summary=_summary(MASSIVE_INDEX_INTRADAY_RESOURCE_ID),
        observations=(bar,), receipts=(receipt,))


def _persist(engine, batch):
    with SessionLocal(bind=engine) as db:
        assert db.autoflush is False
        return USIntradayBarTransaction(db).persist_bar_acquisition(*batch)


def _state(engine):
    with SessionLocal(bind=engine) as db:
        row = db.query(MarketIntradayBar).one()
        lineage = db.query(MarketIntradayBarLineage).one()
        raw = db.get(RawFetchResult, lineage.raw_result_id)
        return (row.close_price, lineage.finalization, lineage.fetched_at,
            raw.content_hash, row.updated_at, lineage.updated_at, lineage.raw_result_id)


@pytest.mark.parametrize("older_first", [False, True])
@pytest.mark.parametrize("same_price", [False, True])
def test_receipt_arrival_order(db_engine, older_first, same_price):
    old = _batch(1, "100" if same_price else "90", BarFinalization.PROVISIONAL)
    new = _batch(3, "100", BarFinalization.CORRECTED)
    for batch in ((old, new) if older_first else (new, old)):
        _persist(db_engine, batch)
    state = _state(db_engine)
    assert state[:4] == (100, "corrected", new[1].receipts[0].fetched_at.replace(tzinfo=None), new[1].receipts[0].content_hash)


def test_legal_finalization_correction_and_exact_replay_noop(db_engine, monkeypatch):
    invalidations = []
    monkeypatch.setattr("app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache", invalidations.append)
    for batch in (_batch(1, "100", BarFinalization.PROVISIONAL), _batch(2, "100"),
                  _batch(3, "110", BarFinalization.CORRECTED)):
        assert _persist(db_engine, batch).observations_written == 1
    before = _state(db_engine)
    statements = []

    def record(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)

    event.listen(db_engine, "before_cursor_execute", record)
    replay = _persist(db_engine, batch)
    event.remove(db_engine, "before_cursor_execute", record)
    assert replay.observations_unchanged == 1 and replay.observations_written == 0
    assert _state(db_engine) == before
    assert invalidations == ["^GSPC"] * 3
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in statements)
    assert "BEGIN IMMEDIATE" in statements  # A no-op still reserves the writer.


@pytest.mark.parametrize("same_payload", [False, True])
def test_newer_identical_values_keep_immutable_provenance(db_engine, same_payload):
    original = _batch(1, "100")
    _persist(db_engine, original)
    before = _state(db_engine)
    newer = _batch(3, "100", payload=original[1].receipts[0].raw_text if same_payload else None)
    result = _persist(db_engine, newer)
    assert result.observations_unchanged == 1 and result.observations_written == 0
    assert _state(db_engine) == before
    with SessionLocal(bind=db_engine) as db:
        assert db.query(RawFetchResult).count() == (1 if same_payload else 2)


@pytest.mark.parametrize("same_price", [False, True])
def test_same_time_different_payload_conflicts_and_rolls_back(db_engine, same_price):
    _persist(db_engine, _batch(3, "100"))
    before = _state(db_engine)
    incoming = _batch(3, "100" if same_price else "90", payload='{"different":"receipt"}')
    with pytest.raises(ValueError, match="US_INTRADAY_RECEIPT_TIME_CONFLICT"):
        _persist(db_engine, incoming)
    assert _state(db_engine) == before
    with SessionLocal(bind=db_engine) as db:
        assert db.query(RawFetchResult).count() == 1


def test_duplicate_storage_key_rejected_atomically(db_engine):
    requirement, acquisition = _batch(1, "100")
    other = acquisition.observations[0].model_copy(update={
        key: Decimal("99") for key in ("open_price", "high_price", "low_price", "close_price")
    })
    with pytest.raises(ValueError, match="duplicate canonical observation identity"):
        _persist(db_engine, (requirement, replace(acquisition, observations=(*acquisition.observations, other))))
    with SessionLocal(bind=db_engine) as db:
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 0
        assert db.query(RawFetchResult).count() == 0


def test_late_invalid_batch_preserves_prior_commit(db_engine):
    _persist(db_engine, _batch(1, "100"))
    before = _state(db_engine)
    requirement, acquisition = _batch(3, "110")
    invalid = acquisition.observations[0].model_copy(update={"volume_status": "observed"})
    with pytest.raises(ValueError, match="US index intraday volume"):
        _persist(db_engine, (requirement, replace(acquisition, observations=(*acquisition.observations, invalid))))
    assert _state(db_engine) == before
    with SessionLocal(bind=db_engine) as db:
        assert db.query(RawFetchResult).count() == 1


def test_later_tie_conflict_rolls_back_earlier_pending_correction(db_engine, monkeypatch):
    _persist(db_engine, _batch(1, "100"))
    requirement, second = _batch(3, "120")
    second_bar = second.observations[0].model_copy(update={
        "start_at": START + timedelta(minutes=1), "end_at": START + timedelta(minutes=2),
    })
    _persist(db_engine, (requirement, replace(second, observations=(second_bar,))))
    requirement, incoming = _batch(3, "110")
    later = incoming.observations[0].model_copy(update={
        "start_at": second_bar.start_at, "end_at": second_bar.end_at,
    })
    invalidations = []
    monkeypatch.setattr("app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache", invalidations.append)
    with SessionLocal(bind=db_engine) as db:
        rollback = db.rollback
        pending_prices = []

        def record_rollback():
            pending_prices.extend(row.close_price for row in db.dirty if isinstance(row, MarketIntradayBar))
            rollback()

        monkeypatch.setattr(db, "rollback", record_rollback)
        with pytest.raises(ValueError, match="US_INTRADAY_RECEIPT_TIME_CONFLICT"):
            USIntradayBarTransaction(db).persist_bar_acquisition(
                requirement, replace(incoming, observations=(*incoming.observations, later)),
            )
        assert pending_prices == [110]
        assert not db.in_transaction()
    with SessionLocal(bind=db_engine) as check:
        assert [row.close_price for row in check.query(MarketIntradayBar).order_by(MarketIntradayBar.bar_time)] == [100, 120]
        assert check.query(RawFetchResult).count() == 2
    assert invalidations == []


def test_preloaded_identity_map_is_refreshed_before_precedence(db_engine):
    _persist(db_engine, _batch(1, "100"))
    with SessionLocal(bind=db_engine) as older:
        held_bar = older.query(MarketIntradayBar).one()
        held_lineage = older.query(MarketIntradayBarLineage).one()
        _persist(db_engine, _batch(3, "110", BarFinalization.CORRECTED))
        result = USIntradayBarTransaction(older).persist_bar_acquisition(*_batch(2, "90"))
        assert result.observations_unchanged == 1 and result.observations_written == 0
        assert held_bar.close_price == 110 and held_lineage.finalization == "corrected"
    assert _state(db_engine)[:2] == (110, "corrected")


@pytest.mark.parametrize("pause_entity,old_price,unrelated_commits", [
    (MarketIntradayBarLineage, "100", 0), (MarketIntradayBar, "90", 0),
    (MarketIntradayBarLineage, "100", 1),
])
def test_borrowed_read_transactions_stale_snapshot_cannot_publish(db_engine, monkeypatch, pause_entity, old_price, unrelated_commits):
    unrelated_table = Table("unrelated_fixture", MetaData(), Column("id", Integer, primary_key=True))
    if unrelated_commits:
        unrelated_table.create(db_engine)
    _persist(db_engine, _batch(0, "100", BarFinalization.PROVISIONAL))
    initial_state = _state(db_engine)
    older, newer = _batch(2, old_price), _batch(3, "110", BarFinalization.CORRECTED)
    # Pre-existing receipts: no new-raw flush can accidentally serialize the test.
    with SessionLocal(bind=db_engine) as setup:
        owner = USIntradayBarTransaction(setup)
        for batch in (older, newer):
            owner._raw.source_and_raw(batch[1].receipts[0])
        setup.commit()
    barriers = [(Event(), Event()) for _ in range(max(1, unrelated_commits))]
    outcomes, closed_transactions = [], []
    old_db = SessionLocal(bind=db_engine)
    old_owner = USIntradayBarTransaction(old_db)
    persist_attempt = old_owner._persist_bar_acquisition_attempt
    attempts = []

    def record_attempt(requirement, acquisition, *, retry_snapshot):
        assert acquisition is older[1]
        attempts.append(retry_snapshot)
        return persist_attempt(requirement, acquisition, retry_snapshot=retry_snapshot)

    monkeypatch.setattr(old_owner, "_persist_bar_acquisition_attempt", record_attempt)
    original_all = Query.all
    reads = []

    def pause_after_read(query):
        result = original_all(query)
        if query.session is old_db and query.column_descriptions[0].get("entity") is pause_entity and len(reads) < len(barriers):
            assert result
            paused, resume = barriers[len(reads)]
            reads.append(True)
            paused.set()
            assert resume.wait(10), "new transaction did not finish"
        return result

    monkeypatch.setattr(Query, "all", pause_after_read)

    def run_old():
        try:
            # An inherited physical read snapshot is not reset to get writer
            # admission. Its unknown prior work makes automatic replay unsafe.
            old_db.connection().exec_driver_sql("BEGIN")
            outcomes.append(old_owner.persist_bar_acquisition(*older))
        except Exception as exc:
            outcomes.append(exc)
        finally:
            closed_transactions.append(not old_db.in_transaction())
            old_db.close()

    thread = Thread(target=run_old)
    thread.start()
    try:
        for index, (paused, resume) in enumerate(barriers):
            assert paused.wait(10), "old transaction did not reach snapshot read"
            if unrelated_commits:
                with SessionLocal(bind=db_engine) as other_writer:
                    other_writer.execute(unrelated_table.insert().values(id=index + 1))
                    other_writer.commit()
            else:
                result = _persist(db_engine, newer)
                assert result.receipts_written == 0 and result.observations_written == 1
            resume.set()
    finally:
        for _paused, resume in barriers:
            resume.set()
        thread.join(10)
    assert not thread.is_alive()
    assert closed_transactions == [True], "owner did not commit/rollback"
    state = _state(db_engine)  # Third independent Session, after both workers finish.
    print(f"interleaving unrelated_commits={unrelated_commits} pause={pause_entity.__name__} attempts={attempts} outcome={type(outcomes[0]).__name__} stored={state[:4]}")
    assert attempts == [True]  # Borrowed transaction fails closed, without replay.
    if unrelated_commits:
        with SessionLocal(bind=db_engine) as check:
            assert check.execute(unrelated_table.select().order_by(unrelated_table.c.id)).all() == [(i + 1,) for i in range(unrelated_commits)]
            assert check.query(RawFetchResult).count() == 3
            assert check.query(MarketIntradayBar).count() == check.query(MarketIntradayBarLineage).count() == 1
        assert state == initial_state
    else:
        assert state[:4] == (110, "corrected", newer[1].receipts[0].fetched_at.replace(tzinfo=None), newer[1].receipts[0].content_hash)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], OperationalError)
    assert outcomes[0].orig.sqlite_errorcode == 517


@pytest.mark.parametrize("failure", ["busy_5", "other_sql", "commit_517", "post_commit_517", "rollback_failure"])
def test_snapshot_recovery_never_retries_other_or_unknown_outcomes(db_engine, monkeypatch, failure):
    _persist(db_engine, _batch(1, "100"))
    batch = _batch(3, "110")
    code = 5 if failure == "busy_5" else 1 if failure == "other_sql" else 517
    cause = sqlite3.OperationalError("fixture persistence failure")
    cause.sqlite_errorcode = code
    error = OperationalError("fixture", {}, cause)
    with SessionLocal(bind=db_engine) as db:
        owner = USIntradayBarTransaction(db)
        attempt = owner._persist_bar_acquisition_attempt
        attempts = []

        def record_attempt(requirement, acquisition, *, retry_snapshot):
            attempts.append(retry_snapshot)
            return attempt(requirement, acquisition, retry_snapshot=retry_snapshot)

        monkeypatch.setattr(owner, "_persist_bar_acquisition_attempt", record_attempt)
        real_commit, real_rollback = db.commit, db.rollback

        def fail(*_args, **_kwargs):
            raise error

        if failure in {"commit_517", "post_commit_517"}:
            def commit_failure():
                if failure == "post_commit_517":
                    real_commit()
                raise error
            monkeypatch.setattr(db, "commit", commit_failure)
        else:
            monkeypatch.setattr(db, "flush", fail)
        if failure == "rollback_failure":
            def rollback_failure():
                raise RuntimeError("fixture rollback outcome unknown")
            monkeypatch.setattr(db, "rollback", rollback_failure)
        expected = RuntimeError if failure == "rollback_failure" else OperationalError
        with pytest.raises(expected):
            owner.persist_bar_acquisition(*batch)
        assert attempts == [True]
        if failure == "rollback_failure":
            real_rollback()  # Test cleanup only; never authorizes another attempt.
    assert _state(db_engine)[0] == (110 if failure == "post_commit_517" else 100)


def test_platform_recovery_reuses_one_acquisition_and_fresh_attempt_state(db_engine, monkeypatch):
    from app.db.models import USStockMaster
    from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
    from app.us_market.intraday_platform import USIntradayMarketPlatform
    from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
    from test_us_intraday_shared_core import _yahoo_payload

    Base.metadata.create_all(db_engine)
    with SessionLocal(bind=db_engine) as seed:
        seed.add(USStockMaster(symbol="AAPL", security_name="Apple Inc.", exchange="NASDAQ", asset_type="stock"))
        seed.commit()
    now = datetime(2026, 8, 28, 14, 32, tzinfo=timezone.utc)
    fetches, attempts, flushed_source = [], [], []

    def fetch(_route, _requirement):
        fetches.append(True)
        return _yahoo_payload(now), "https://fixture.invalid/bars"

    with SessionLocal(bind=db_engine) as db:
        owner = USIntradayBarTransaction(db)
        persist_attempt, flush = owner._persist_bar_acquisition_attempt, db.flush

        def record_attempt(requirement, acquisition, *, retry_snapshot):
            attempts.append(acquisition)
            return persist_attempt(requirement, acquisition, retry_snapshot=retry_snapshot)

        def fail_first_raw_flush(*args, **kwargs):
            if not flushed_source and any(isinstance(row, RawFetchResult) for row in db.new):
                flushed_source.append(db.query(SourceRegistry).count())
                cause = sqlite3.OperationalError("fixture snapshot upgrade")
                cause.sqlite_errorcode = 517
                raise OperationalError("fixture", {}, cause)
            return flush(*args, **kwargs)

        monkeypatch.setattr(owner, "_persist_bar_acquisition_attempt", record_attempt)
        monkeypatch.setattr(db, "flush", fail_first_raw_flush)
        platform = USIntradayMarketPlatform(
            db, bar_transaction=owner, bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
            acquisition=USIntradayAcquisitionExecutor(fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: now),
        )
        result = platform.refresh_intraday_bars(symbol="AAPL", bars=100, now=now, max_provider_calls=1)
        assert fetches == [True] and flushed_source == [1]
        assert len(attempts) == 2 and attempts[0] is attempts[1]
        assert result.result.acquisition.external_calls == 1
        assert result.result.persistence.committed is True
        assert result.result.persistence.receipts_written == result.result.persistence.observations_written == 1
        assert len(result.result.resolved.bars) == 1
        assert db.query(SourceRegistry).count() == db.query(RawFetchResult).count() == 1
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 1


def test_latest_observed_noop_watermark_counterexample(db_engine):
    _persist(db_engine, _batch(1, "100"))
    before = _state(db_engine)
    result = _persist(db_engine, _batch(3, "100"))
    assert result.observations_unchanged == 1 and _state(db_engine) == before
    _persist(db_engine, _batch(2, "90"))
    assert _state(db_engine)[0] == 100
