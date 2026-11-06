"""Real summary/Gateway/transaction interleavings; provider IO is fixture-only."""
from datetime import datetime, timedelta, timezone
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

from app.db.models import Base, RawFetchResult, SourceRegistry, TaiwanCurrentIndexSnapshot, TaiwanCurrentBreadthSnapshot
from app.db.session import SessionLocal
from app.market import indices, tw_current_market_operations, tw_current_market_platform as platform
from app.market.tw_current_market_repository import TaiwanCurrentMarketRepository
from app.market.tw_current_market_transaction import TaiwanCurrentMarketTransaction
from app.market.tw_intraday_state import attach_current_market_lineage_to_stock_rows
from app.market.providers.tw_current_market import CurrentIndexAdapter, CurrentBreadthAdapter, CurrentMarketProviderPayload
from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor, TaiwanCurrentBreadthAcquisitionExecutor
from app.market.tw_current_market_capabilities import TW_CURRENT_INDEX_CAPABILITY_ID, TW_CURRENT_BREADTH_CAPABILITY_ID, TWSE_MIS_CURRENT_INDEX_DESCRIPTOR, TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR
from test_tw_current_market_platform import NOW, _binding


@pytest.fixture
def wal_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'summary.db'}", poolclass=NullPool,
                          connect_args={"check_same_thread": False, "timeout": 30})
    @event.listens_for(engine, "connect")
    def setup(connection, _):
        connection.execute("PRAGMA busy_timeout=30000")
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def index_port(*, fetched=NOW, price=100, hook=lambda: None, error=None):
    def reader(scope, timeout):
        hook()
        return CurrentMarketProviderPayload(payload=None if error else {
            "as_of": NOW.isoformat(), "trade_date": NOW.date().isoformat(), "close": price,
            "previous_close": 99, "volume": 100, "trade_value": 100000, "transaction_count": 10},
            status="error" if error else "ok", error=error)
    return TaiwanCurrentIndexAcquisitionExecutor((CurrentIndexAdapter(
        _binding("twse_mis", "twse_mis_index_snapshot", TW_CURRENT_INDEX_CAPABILITY_ID), reader, clock=lambda: fetched),))


def breadth_port(hook=lambda: None, *, fetched=NOW, trade_value=1000):
    def reader(scope, timeout):
        hook()
        return CurrentMarketProviderPayload(payload={"market": scope,
            "snapshot_as_of": NOW.isoformat(), "trade_date": NOW.date().isoformat(),
            "universe_count": 1, "advance_count": 1, "decline_count": 0, "unchanged_count": 0,
            "received_unclassified_count": 0, "not_received_count": 0, "trade_value": trade_value}, status="ok")
    return TaiwanCurrentBreadthAcquisitionExecutor((CurrentBreadthAdapter(
        _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID), reader, clock=lambda: fetched),))


def companion_summary(db, rows, at=NOW):
    """A real adapter/transaction/reread receipt for companion membership tests."""
    actual = sum(bool(row.get("has_actual_trade")) for row in rows)
    payload = {"market": "TWSE", "snapshot_as_of": at.isoformat(), "trade_date": at.date().isoformat(),
        "universe_count": len(rows), "advance_count": actual, "decline_count": 0, "unchanged_count": 0,
        "received_unclassified_count": len(rows) - actual, "not_received_count": 0,
        "trade_value": 1000, "component_stock_rows": rows, "observation_received_at": at.isoformat()}
    port = TaiwanCurrentBreadthAcquisitionExecutor((CurrentBreadthAdapter(
        _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        lambda *args: CurrentMarketProviderPayload(payload=payload, status="ok"), clock=lambda: at),))
    result = platform.refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=at,
        descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=port)
    # Use the original canonical repository projection, not a fabricated raw ID.
    return {"indices": [{"market": "TWSE", "breadth": platform.project_taiwan_current_breadth(result)}]}


def _summary_setup(monkeypatch, index, breadth):
    class FixedDateTime(datetime):
        @staticmethod
        def now(tz=None):
            return NOW
    monkeypatch.setattr(indices, "datetime", FixedDateTime)
    monkeypatch.setattr(indices, "INDEX_CONFIGS", [dict(indices.INDEX_CONFIGS[0])])
    monkeypatch.setattr(tw_current_market_operations, "build_current_market_executors", lambda *a, **k: (index, breadth))
    original_index, original_breadth = platform.refresh_taiwan_current_index, platform.refresh_taiwan_current_breadth
    monkeypatch.setattr(platform, "refresh_taiwan_current_index", lambda *a, **k:
        original_index(*a, descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,), **k))
    monkeypatch.setattr(platform, "refresh_taiwan_current_breadth", lambda *a, **k:
        original_breadth(*a, descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), **k))


@pytest.mark.parametrize("slow_phase", ["acquisition", "gateway_reread", "summary_reread"])
def test_slow_acquisition_and_rereads_do_not_block_other_summary(wal_engine, monkeypatch, slow_phase):
    held, release, other_done = Event(), Event(), Event()
    failures, results = [], []
    def pause():
        held.set()
        assert release.wait(10)
    _summary_setup(monkeypatch, index_port(), breadth_port(pause if slow_phase == "acquisition" else lambda: None))
    original_read = TaiwanCurrentMarketRepository.read_market_breadth_candidates
    def read(self, requirement):
        if slow_phase == "gateway_reread" and current_thread().name == "slow" and self._db.info.get("persisted") and not held.is_set():
            pause()
        return original_read(self, requirement)
    monkeypatch.setattr(TaiwanCurrentMarketRepository, "read_market_breadth_candidates", read)
    summary_read = indices._shared_current_market_summary
    def summary(db, **kwargs):
        if slow_phase == "summary_reread" and current_thread().name == "slow":
            pause()
        return summary_read(db, **kwargs)
    monkeypatch.setattr(indices, "_shared_current_market_summary", summary)
    def run(slow):
        try:
            with SessionLocal(bind=wal_engine) as db:
                assert db.autoflush is False
                event.listen(db, "after_commit", lambda session: session.info.update(persisted=True))
                result = (indices.refresh_current_market_breadth_snapshots(db) if slow
                          else indices.refresh_current_market_index_snapshots(db))
                results.append(result)
                if not slow:
                    other_done.set()
        except BaseException as exc:
            failures.append(exc)
    a, b = Thread(target=run, args=(True,), name="slow"), Thread(target=run, args=(False,), name="other")
    a.start()
    try:
        assert held.wait(5)
        b.start()
        assert other_done.wait(5), "other summary blocked by non-persistence work"
    finally:
        release.set()
        a.join(10)
        if b.ident is not None:
            b.join(10)
    assert not a.is_alive() and not b.is_alive() and failures == []
    assert len(results) == 2 and all(r["indices"] for r in results)


@pytest.mark.parametrize("lane", ["index", "breadth"])
def test_newer_finishes_first_with_initial_reads_and_cached_orm(wal_engine, lane):
    model = TaiwanCurrentIndexSnapshot if lane == "index" else TaiwanCurrentBreadthSnapshot
    def refresh(db, fetched, price, hook=lambda: None):
        if lane == "index":
            return platform.refresh_taiwan_current_index(db, index_id="TAIEX", requested_at=NOW + timedelta(minutes=6),
                descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,), acquisition=index_port(fetched=fetched, price=price, hook=hook))
        return platform.refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW + timedelta(minutes=6),
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=breadth_port(hook, fetched=fetched, trade_value=price))
    with SessionLocal(bind=wal_engine) as db:
        refresh(db, NOW, 100)
    held, release = Event(), Event()
    failures, physical = [], []
    def run(old):
        try:
            with SessionLocal(bind=wal_engine) as db:
                cached = db.query(model).one()
                source = db.query(SourceRegistry).one()
                if lane == "index":
                    platform.read_taiwan_current_index(db, index_id="TAIEX", requested_at=NOW + timedelta(minutes=6))
                else:
                    platform.read_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW + timedelta(minutes=6))
                physical.append(db.connection().connection.driver_connection.in_transaction)
                def pause():
                    held.set()
                    assert release.wait(10)
                refresh(db, NOW + timedelta(minutes=5 if old else 6), 90 if old else 110,
                        pause if old else lambda: None)
                if not old and lane == "index":
                    platform.refresh_taiwan_current_index(db, index_id="TAIEX", requested_at=NOW + timedelta(minutes=20),
                        descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,),
                        acquisition=index_port(fetched=NOW + timedelta(minutes=7), error="newer failure"))
                assert cached.id and source.id  # Strong references throughout the callback.
        except BaseException as exc:
            failures.append(exc)
    a = Thread(target=run, args=(True,))
    a.start()
    try:
        assert held.wait(5)
        b = Thread(target=run, args=(False,))
        b.start(); b.join(10)
        assert not b.is_alive()
    finally:
        release.set(); a.join(10)
    assert failures == [] and physical == [False, False]
    with SessionLocal(bind=wal_engine) as db:
        row = db.query(model).one()
        raw = db.get(RawFetchResult, row.raw_result_id)
        assert (row.close_value if lane == "index" else row.trade_value) == 110
        assert raw.fetched_at == (NOW + timedelta(minutes=6)).astimezone(timezone.utc).replace(tzinfo=None)
        source = db.query(SourceRegistry).one()
        assert source.last_success_at == raw.fetched_at
        if lane == "index":
            assert source.last_error_at == (NOW + timedelta(minutes=7)).astimezone(timezone.utc).replace(tzinfo=None)
            assert source.last_error_message == "newer failure"


def test_companion_pairing_requires_canonical_db():
    row_b = {"market": "TWSE", "code": "2330", "as_of": NOW, "current_price": 110,
             "raw_result_id": "raw_fetch_result:22"}
    summary_a = {"indices": [{"market": "TWSE", "breadth": {"provider": "twse_mis",
        "source": "twse_mis_live_breadth", "raw_result_id": "raw_fetch_result:21", "as_of": NOW}}]}
    with pytest.raises(ValueError, match="COMPANION"):
        attach_current_market_lineage_to_stock_rows([row_b], summary=summary_a)


def test_source_health_clocks_and_pending_caller_work_do_not_regress(wal_engine):
    with SessionLocal(bind=wal_engine) as db:
        def refresh(minute, error=None):
            return platform.refresh_taiwan_current_index(db, index_id="TAIEX", requested_at=NOW + timedelta(minutes=20),
                descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,),
                acquisition=index_port(fetched=NOW + timedelta(minutes=minute), price=100 + minute, error=error))
        refresh(6)
        source = db.query(SourceRegistry).one()
        source.endpoint_url = "https://fixture.invalid/caller-edit"
        db.add(SourceRegistry(source_name="caller-pending", source_type="api", category="fixture"))
        refresh(8, "newer failure")
        refresh(7)
        refresh(4, "old failure")
        source = db.query(SourceRegistry).filter_by(source_name="twse_mis_index_snapshot").one()
        assert source.last_success_at == (NOW + timedelta(minutes=7)).astimezone(timezone.utc).replace(tzinfo=None)
        assert source.last_error_at == (NOW + timedelta(minutes=8)).astimezone(timezone.utc).replace(tzinfo=None)
        assert source.last_error_message == "newer failure"
        assert source.endpoint_url == "https://fixture.invalid/caller-edit"
        assert db.query(SourceRegistry).filter_by(source_name="caller-pending").one()
        refresh(9)
        assert source.last_error_at is None and source.last_error_message is None


def test_borrowed_physical_snapshot_fails_closed_without_replay(wal_engine):
    from sqlalchemy.exc import OperationalError
    from app.market_data.gateway import PostAcquisitionError
    with SessionLocal(bind=wal_engine) as seed:
        platform.refresh_taiwan_current_index(seed, index_id="TAIEX", requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,), acquisition=index_port())
    with SessionLocal(bind=wal_engine) as old:
        old.connection().exec_driver_sql("BEGIN")
        platform.read_taiwan_current_index(old, index_id="TAIEX", requested_at=NOW)
        assert old.connection().connection.driver_connection.in_transaction
        with SessionLocal(bind=wal_engine) as new:
            platform.refresh_taiwan_current_index(new, index_id="TAIEX", requested_at=NOW + timedelta(minutes=6),
                descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,), acquisition=index_port(fetched=NOW + timedelta(minutes=6), price=110))
        calls = []
        with pytest.raises(PostAcquisitionError) as failure:
            platform.refresh_taiwan_current_index(old, index_id="TAIEX", requested_at=NOW + timedelta(minutes=6),
                descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,),
                acquisition=index_port(fetched=NOW + timedelta(minutes=5), price=90, hook=lambda: calls.append(1)))
        assert isinstance(failure.value.__cause__, OperationalError) and failure.value.__cause__.orig.sqlite_errorcode == 517
        assert calls == [1] and not old.connection().connection.driver_connection.in_transaction
    with SessionLocal(bind=wal_engine) as check:
        assert check.query(TaiwanCurrentIndexSnapshot).one().close_value == 110
        assert check.query(RawFetchResult).count() == 2


@pytest.mark.parametrize("failure_phase", ["raw_flush", "commit"])
def test_complete_callbacks_are_mutex_protected_and_failure_releases(wal_engine, monkeypatch, failure_phase):
    from app.market_data.gateway import PostAcquisitionError
    held, release, other_contended = Event(), Event(), Event()
    mutex = indices._SUMMARY_REFRESH_LOCK
    class ObservedMutex:
        def __enter__(self):
            if not mutex.acquire(blocking=False):
                if current_thread().name == "other":
                    # Signal only after a real attempt on A's held lock failed.
                    # Acquisition/pre-callback arrival alone cannot prove this.
                    other_contended.set()
                mutex.acquire()
            return self

        def __exit__(self, *_args):
            mutex.release()

    monkeypatch.setattr(indices, "_SUMMARY_REFRESH_LOCK", ObservedMutex())
    active, maxima, outcomes = [], [], []
    original = TaiwanCurrentMarketTransaction._persist
    def tracked(self, *args, **kwargs):
        active.append(current_thread().name)
        maxima.append(len(active))
        try:
            return original(self, *args, **kwargs)
        finally:
            active.remove(current_thread().name)
    monkeypatch.setattr(TaiwanCurrentMarketTransaction, "_persist", tracked)
    _summary_setup(monkeypatch, index_port(), breadth_port())
    def run(failing):
        try:
            with SessionLocal(bind=wal_engine) as db:
                if failing:
                    flush = db.flush
                    def fail():
                        held.set()
                        assert release.wait(10)
                        raise RuntimeError("fixture persistence failure")
                    if failure_phase == "raw_flush":
                        def failing_flush(*args, **kwargs):
                            has_raw = any(isinstance(x, RawFetchResult) for x in db.new)
                            flush(*args, **kwargs)
                            if has_raw:
                                fail()
                        db.flush = failing_flush
                    else:
                        def failing_commit():
                            flush()  # All pending snapshots reached SQLite, still uncommitted.
                            fail()
                        db.commit = failing_commit
                    indices.refresh_current_market_index_snapshots(db)
                else:
                    indices.refresh_current_market_breadth_snapshots(db)
                outcomes.append("success")
        except BaseException as exc:
            outcomes.append(exc)
    a, b = Thread(target=run, args=(True,), name="failing"), Thread(target=run, args=(False,), name="other")
    a.start()
    try:
        assert held.wait(5)
        b.start()
        assert other_contended.wait(5), "second callback never contended on the held summary mutex"
        assert active == ["failing"]
    finally:
        release.set(); a.join(10)
        if b.ident is not None:
            b.join(10)
    assert not a.is_alive() and not b.is_alive() and max(maxima) == 1
    assert len(outcomes) == 2 and "success" in outcomes
    assert any(isinstance(x, PostAcquisitionError) and isinstance(x.__cause__, RuntimeError) for x in outcomes)
    with SessionLocal(bind=wal_engine) as check:
        assert check.query(TaiwanCurrentIndexSnapshot).count() == 0
        assert check.query(TaiwanCurrentBreadthSnapshot).count() == check.query(RawFetchResult).count() == 1
        assert check.query(SourceRegistry).one().source_name == "twse_mis_live_breadth"


@pytest.mark.parametrize("missing_trade_receipt,derived_failure", [(False, False), (True, False), (True, True)])
def test_companion_exact_receipt_survives_cache_replacement_and_preserves_clocks(wal_engine, monkeypatch, missing_trade_receipt, derived_failure):
    import json
    base = NOW.replace(hour=9, minute=30)
    from app.db.models import TaiwanIntradayStockState, TaiwanMarketMinuteState, StockMaster
    from app.market.providers import twse_mis_current_breadth as provider
    from app.market.tw_current_market_repository import read_breadth_price_states
    from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states
    monkeypatch.setattr(provider, "_STOCK_ROWS", {})
    def persist(db, payload, fetched):
        port = TaiwanCurrentBreadthAcquisitionExecutor((CurrentBreadthAdapter(
            _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
            lambda *args: CurrentMarketProviderPayload(payload=payload, status="ok"), clock=lambda: fetched),))
        result = platform.refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=base + timedelta(minutes=4),
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=port)
        return {"indices": [{"market": "TWSE", "breadth": platform.project_taiwan_current_breadth(result)}]}
    message = dict(c="2330", d=base.strftime("%Y%m%d"), t=base.strftime("%H:%M:%S"), z="100", v="10",
                   tv="1", y="99", o="99", h="100", l="99", _omi_received_at=base.isoformat())
    with SessionLocal(bind=wal_engine) as db:
        first = provider._build_payload("TWSE", ["2330"], [message], 0, expected_trade_date=base.date())
        first_summary = persist(db, first, base + timedelta(seconds=1))
        old_raw = first_summary["indices"][0]["breadth"]["raw_result_id"]
        prior = read_breadth_price_states(db, venue="TWSE", requested_at=base + timedelta(seconds=5))
        assert prior["2330"]["lineage"]["raw_receipt_id"] == old_raw
        codes = ["2330"]
        if missing_trade_receipt:
            second = provider._build_payload("TWSE", ["2317"], [{**message, "c": "2317"}], 0, expected_trade_date=base.date())
            second_summary = persist(db, second, base + timedelta(seconds=2))
            good_raw = second_summary["indices"][0]["breadth"]["raw_result_id"]
            prior.update(read_breadth_price_states(db, venue="TWSE", requested_at=base + timedelta(seconds=5)))
            codes.append("2317")
        at = base + timedelta(seconds=10)
        message_a = {**message, "t": at.strftime("%H:%M:%S"), "z": "-", "_omi_received_at": (at + timedelta(seconds=1)).isoformat()}
        payload_a = provider._build_payload("TWSE", codes, [{**message_a, "c": code} for code in codes], 0, prior_states=prior, expected_trade_date=base.date())
        summary_a = persist(db, payload_a, at + timedelta(seconds=11))
        row = payload_a["component_stock_rows"][0]
        assert row["price_source"] == "session_cache" and row["price_lineage"]["raw_receipt_id"] == old_raw
        raw_id = summary_a["indices"][0]["breadth"]["raw_result_id"]
        assert raw_id != old_raw
        stored = db.query(TaiwanCurrentBreadthSnapshot).order_by(TaiwanCurrentBreadthSnapshot.event_at.desc()).first()
        assert json.loads(stored.price_states_json)["2330"]["lineage"]["raw_receipt_id"] == old_raw
        if missing_trade_receipt:
            db.delete(db.get(RawFetchResult, int(old_raw.split(":")[1])))
            db.commit()  # Isolated fixture: A still exists, its referenced trade B does not.
            from app.jobs import scheduler
            from test_taiwan_market_state import market_summary_payload
            from app.market.tw_intraday_discovery import read_tw_intraday_discovery
            for code in codes:
                db.add(StockMaster(stock_id=code, stock_name=code, market="TWSE", instrument_type="stock", is_active=True))
            db.commit()
            payload = market_summary_payload(base.date(), hour=9, minute=30, twse_trade_value=1000, tpex_trade_value=500)
            payload["indices"] = payload["indices"][:1]
            payload["indices"][0]["current_data_core"]["breadth"] = summary_a["indices"][0]["breadth"]
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return at + timedelta(seconds=11)
            monkeypatch.setattr(scheduler, "datetime", Clock)
            monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
            monkeypatch.setattr(scheduler, "is_taiwan_index_live_refresh_window", lambda _: True)
            monkeypatch.setattr(scheduler, "refresh_current_market_breadth_snapshots", lambda **_: payload)
            failure_witness = []
            if derived_failure:
                original_stock_writer = scheduler.persist_taiwan_intraday_stock_states
                def fail_after_stock_flush(db, **kwargs):
                    assert kwargs["commit"] is False
                    original_stock_writer(db, **kwargs)
                    db.flush()
                    counts = (db.query(TaiwanMarketMinuteState).count(), db.query(TaiwanIntradayStockState).count())
                    assert counts == (1, 2)
                    failure_witness.append({"phase": "after_both_derived_writers_flushed", "row_counts": counts})
                    raise RuntimeError("fixture after both derived writers flushed")
                monkeypatch.setattr(scheduler, "persist_taiwan_intraday_stock_states", fail_after_stock_flush)
            scheduler.collect_taiwan_market_breadth_summary()  # Real helper + two derived writers + original commit owner.
            if derived_failure:
                # The collector catches exceptions: an earlier failure must not
                # impersonate rollback of the intended, fully flushed writes.
                assert failure_witness == [{"phase": "after_both_derived_writers_flushed", "row_counts": (1, 2)}]
            with SessionLocal(bind=wal_engine) as check:
                if derived_failure:
                    assert check.query(TaiwanMarketMinuteState).count() == check.query(TaiwanIntradayStockState).count() == 0
                    assert check.get(RawFetchResult, int(raw_id.split(":")[1])) is not None
                    assert check.query(TaiwanCurrentBreadthSnapshot).filter_by(raw_result_id=int(raw_id.split(":")[1])).one()
                    return
                assert check.query(TaiwanMarketMinuteState).count() == 1
                states = {state.stock_id: state for state in check.query(TaiwanIntradayStockState).all()}
                assert set(states) == set(codes)
                assert states["2317"].lineage_complete and states["2317"].decision_usable
                assert set(json.loads(states["2317"].component_raw_result_ids_json)) == {raw_id, good_raw}
                bad = states["2330"]
                assert not bad.lineage_complete and not bad.decision_usable and bad.quality_status == "partial"
                assert bad.current_price == 100 and bad.price_as_of.replace(tzinfo=NOW.tzinfo) == base
                assert json.loads(bad.component_raw_result_ids_json) == [raw_id] and json.loads(bad.samples_json) == []
                assert any(c.get("reason") == "TW_BREADTH_COMPANION_TRADE_RECEIPT_UNVERIFIED" for c in json.loads(bad.component_sources_json))
                result = read_tw_intraday_discovery(check, evaluated_at=at + timedelta(seconds=11))
                assert result.coverage.ranking_eligible_count == 1
                assert "LINEAGE_INCOMPLETE" in result.coverage.exclusion_reasons["2330"]
            return
        payload_b = provider._build_payload("TWSE", ["2330"], [{**message_a, "z": "120"}], 0, prior_states=prior, expected_trade_date=base.date())
        row_b = payload_b["component_stock_rows"][0]  # Real same-event producer B, different receipt content.
        with pytest.raises(ValueError, match="MEMBERSHIP"):
            attach_current_market_lineage_to_stock_rows([row_b], summary=summary_a, db=db)
        matched = attach_current_market_lineage_to_stock_rows(summary=summary_a, db=db)
        explicit = attach_current_market_lineage_to_stock_rows([row], summary=summary_a, db=db)
        assert json.loads(json.dumps(explicit, default=lambda x: x.isoformat())) == matched
        for cache in ([row_b], []):
            monkeypatch.setitem(provider._STOCK_ROWS, "TWSE", cache)
            assert attach_current_market_lineage_to_stock_rows(summary=summary_a, db=db) == matched
        assert matched[0]["raw_result_id"] == raw_id and matched[0]["current_price"] == 100
        assert matched[0]["observation_received_at"] == (at + timedelta(seconds=1)).isoformat()  # Ten seconds before aggregate fetch.
        assert matched[0]["price_as_of"] == base.isoformat() and matched[0]["has_actual_trade"] is True
        assert matched[0]["price_lineage"]["raw_receipt_id"] == old_raw
        assert set(matched[0]["component_raw_result_ids"]) == {old_raw, raw_id}
        carried = next(c for c in matched[0]["component_sources"] if c["raw_result_id"] == old_raw)
        assert carried["event_at"] == base.isoformat()
        assert carried["received_at"] == prior["2330"]["lineage"]["received_at"].isoformat()
        persist_taiwan_intraday_stock_states(db, rows=matched, now=at + timedelta(seconds=10))
        state = db.query(TaiwanIntradayStockState).one()
        assert set(json.loads(state.component_raw_result_ids_json)) == {old_raw, raw_id}
        assert next(c for c in json.loads(state.component_sources_json) if c["raw_result_id"] == old_raw)["event_at"] == base.isoformat()
        assert attach_current_market_lineage_to_stock_rows([], summary=summary_a, db=db) == []
        assert attach_current_market_lineage_to_stock_rows(summary={"indices": []}, db=db) == []


def test_cold_summary_read_is_sql_read_only(wal_engine, monkeypatch):
    _summary_setup(monkeypatch, index_port(), breadth_port())
    with SessionLocal(bind=wal_engine) as seed:
        indices.refresh_current_market_index_snapshots(seed)
    statements = []
    def trace(_c, _cu, sql, _p, _ctx, _many):
        statements.append(sql)
    event.listen(wal_engine, "before_cursor_execute", trace)
    with SessionLocal(bind=wal_engine) as cold:
        payload = indices.get_market_index_summary(cold, requested_at=NOW, allow_universe_fallback=False)
        assert payload["indices"] and not cold.new and not cold.dirty and not cold.deleted
    event.remove(wal_engine, "before_cursor_execute", trace)
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for sql in statements)
