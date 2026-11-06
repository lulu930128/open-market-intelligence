"""G1b offline regression: trigger phases and safe post-acquisition stages."""

from datetime import datetime, timezone
import json
import math
import sqlite3
from threading import Lock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Base, MarketIntradayBar, RawFetchResult
from app.db.session import SessionLocal
from app.jobs import us_intraday_materializer_scheduler as scheduler
from app.market_data.contracts import EvidenceFreshness
from app.market_data.gateway import MarketDataGateway, PostAcquisitionError
from app.market_data.integration_contracts import AcquisitionStatus, AcquisitionSummary, PersistenceSummary
from app.market_data.policies import RealtimePolicy
from app.us_market import intraday_materializer as materializer
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from test_market_data_gateway import (
    FakeAcquisition, FakeReader, FakeTransaction, _attempt, _bar, _batch,
    _descriptor, _receipt, _requirement,
)
from test_us_intraday_materializer import _FakeScheduler
from test_us_intraday_shared_core import _yahoo_payload


NOW = datetime(2026, 8, 28, 15, tzinfo=timezone.utc)
STAGES = ("persistence", "validation", "reread_resolve")
SECRET = "secret SQL SELECT payload https://fixture.invalid/?token=secret"


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(materializer, "_LAST_RUNS", {})
    monkeypatch.setattr(materializer, "_RUN_COUNTERS", {})
    monkeypatch.setattr(scheduler, "_INDEX_BATCH_OFFSETS", {"quote.snapshot": 0, "intraday.bars": 0})
    monkeypatch.setattr(scheduler, "_EOD_SCHEDULER", None)


@pytest.mark.parametrize("count,q_batch,b_batch,q_cycle,b_cycle,q_interval,b_interval,start", [
    (6, 2, 2, 60, 120, 20, 40, 100),
    (6, 1, 1, 60, 120, 10, 20, 85),
    (6, 3, 2, 60, 120, 30, 40, 85),
    (6, 3, 3, 60, 120, 30, 60, 105),
    (5, 2, 2, 60, 120, 20, 40, 100),
    (6, 2, 2, 63, 126, 21, 42, 103.5),
    (1, 2, 2, 60, 120, 60, 120, 120),
])
@pytest.mark.parametrize("quote_enabled", [True, False])
def test_index_trigger_phase_and_recurring_budget(
    monkeypatch, count, q_batch, b_batch, q_cycle, b_cycle,
    q_interval, b_interval, start, quote_enabled,
):
    class Clock:
        @staticmethod
        def now(_tz):
            return NOW

    monkeypatch.setattr(scheduler, "datetime", Clock)
    config = {
        "enable_us_intraday_materializer": False,
        "enable_us_intraday_reconciliation": False,
        "enable_us_index_quote_materializer": quote_enabled,
        "enable_us_index_intraday_materializer": True,
        "enable_us_quote_retention_scheduler": False,
        "enable_us_source_health_snapshot_scheduler": False,
        "scheduler_us_index_quote_symbols": ",".join(("^GSPC", "^SOX", "^DJI", "^IXIC", "^NDX", "^VIX")[:count]),
        "scheduler_us_index_quote_max_symbols": count,
        "scheduler_us_index_quote_batch_size": q_batch,
        "scheduler_us_index_intraday_batch_size": b_batch,
        "scheduler_us_quote_materializer_interval_seconds": q_cycle,
        "scheduler_us_index_intraday_materializer_interval_seconds": b_cycle,
    }
    for key, value in config.items():
        monkeypatch.setattr(settings, key, value)
    fake = _FakeScheduler()
    assert scheduler.add_us_intraday_materializer_jobs(fake)
    assert len(fake.jobs) == (2 if quote_enabled else 1)
    bars = fake.jobs[-1]
    delay = (bars["next_run_time"] - NOW).total_seconds()
    assert delay == (start if quote_enabled else 85)
    assert bars["seconds"] == b_interval
    assert bars["function"] is scheduler.collect_us_index_intraday_bars
    assert all(job["coalesce"] and job["max_instances"] == 1 for job in fake.jobs)
    assert all(getattr(settings, key) == value for key, value in config.items())
    if quote_enabled:
        quote = fake.jobs[0]
        assert quote["seconds"] == q_interval
        assert (quote["next_run_time"] - NOW).total_seconds() == 30
        # Enumerate a full relative phase cycle, with quotes on both sides.
        horizon = math.lcm(q_interval, b_interval) * 2
        quote_times = range(30, int(delay + horizon + q_interval + 1), q_interval)
        gaps = [min(abs(delay + n * b_interval - q) for q in quote_times)
                for n in range(horizon // b_interval + 1)]
        assert min(gaps) == math.gcd(q_interval, b_interval) / 2
        assert delay >= 85


@pytest.mark.parametrize("route_gate", [True, False])
@pytest.mark.parametrize("stage", STAGES)
def test_tw_gateway_labels_real_failure_boundary_without_changing_accounting(stage, route_gate):
    events = []

    class Reader(FakeReader):
        def read_bar_candidates(self, requirement):
            if self.calls and stage == "reread_resolve":
                raise ValueError(SECRET)
            return super().read_bar_candidates(requirement)

    class Transaction(FakeTransaction):
        def persist_bar_acquisition(self, requirement, acquired):
            if stage == "persistence":
                self.rolled_back = True
                raise ValueError(SECRET)
            if stage == "validation":
                return PersistenceSummary(attempted=True, committed=False)
            return super().persist_bar_acquisition(requirement, acquired)

    reader = Reader([_batch(freshness=EvidenceFreshness.STALE)], events)
    transaction = Transaction(events=events)
    acquisition = FakeAcquisition(
        AcquisitionSummary(attempted=True, status=AcquisitionStatus.COMPLETED,
                           providers_attempted=("twse_openapi",),
                           resource_attempts=(_attempt(),), external_calls=1),
        observations=(_bar(cache_hit=False),), receipts=(_receipt(),), events=events,
    )
    with pytest.raises(PostAcquisitionError) as caught:
        MarketDataGateway().resolve_bars(
            _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1), reader=reader,
            descriptors=(_descriptor(),), acquisition_port=acquisition,
            transaction_port=transaction, route_resolution_gate=route_gate,
        )
    assert caught.value.stage == stage
    assert isinstance(caught.value.__cause__, ValueError)
    assert caught.value.acquisition.external_calls == 1
    diagnostic = caught.value.diagnostics()
    assert diagnostic["stage"] == stage
    assert diagnostic["persistence_committed"] is (
        None if stage == "persistence" else stage == "reread_resolve")
    assert diagnostic["provider"] == "twse_openapi"
    assert diagnostic["receipt_count"] == diagnostic["observation_count"] == 1
    assert diagnostic["receipt_fetched_at"] and diagnostic["requested_at"]
    assert diagnostic["causes"][0]["type"] == "ValueError"
    assert "secret" not in json.dumps(diagnostic).lower()
    assert acquisition.calls == 1
    assert transaction.rolled_back is (stage == "persistence")
    assert reader.calls == 1  # Failed reread also cannot produce new evidence.


@pytest.mark.parametrize("stage", STAGES)
def test_us_gateway_to_materializer_keeps_stage_calls_rollback_next_symbol_and_lock(stage, monkeypatch, caplog):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls, rollbacks = [], []
    lane_lock = Lock()

    def fetch(route, requirement):
        symbol = requirement.target.instrument.symbol
        calls.append(symbol)
        payload = _yahoo_payload(NOW, age_seconds=30)
        payload["chart"]["result"][0]["meta"]["symbol"] = symbol
        return payload, "https://fixture.invalid/?token=secret"

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if (stage == "persistence" and calls[-1:] == ["^DJI"]
                and statement.startswith(f"INSERT INTO {MarketIntradayBar.__tablename__} ")):
            raise ValueError(SECRET)

    event.listen(engine, "before_cursor_execute", fail_insert)

    def session_factory():
        db = Session(engine)
        rollback = db.rollback

        def record_rollback():
            rollbacks.append(calls[-1] if calls else None)
            return rollback()

        monkeypatch.setattr(db, "rollback", record_rollback)
        return db

    def platform_factory(db):
        gateway = MarketDataGateway()
        validate = gateway._validate_persistence_result

        def validation(acquired, persisted):
            if stage == "validation" and calls[-1:] == ["^DJI"]:
                raise ValueError(SECRET)
            return validate(acquired, persisted)

        monkeypatch.setattr(gateway, "_validate_persistence_result", validation)
        platform = USIntradayMarketPlatform(
            db, gateway=gateway,
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: NOW),
            bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
            quote_cache_invalidator=lambda _symbol: None,
        )
        read = platform._bar_reader.read_bar_candidates

        def reread(requirement):
            if (stage == "reread_resolve" and calls[-1:] == ["^DJI"]
                    and requirement.target.instrument.symbol == "^DJI"):
                raise ValueError(SECRET)
            return read(requirement)

        monkeypatch.setattr(platform._bar_reader, "read_bar_candidates", reread)
        return platform

    try:
        result = materializer.materialize_us_intraday_capability(
            "intraday.bars", configured_symbols="^DJI,^IXIC", max_symbols=2,
            lane_id="index_current", instrument_type="index", max_external_calls=2,
            max_provider_calls=1, now=NOW, run_lock=lane_lock,
            session_factory=session_factory, platform_factory=platform_factory,
        )
        assert calls == ["^DJI", "^IXIC"]
        assert result["status"] == "partial", json.dumps(result["results"])
        assert result["failed_count"] == result["succeeded_count"] == 1
        assert result["external_call_count"] == result["observed_external_call_count"] == 2
        assert "^DJI" in rollbacks and not lane_lock.locked()
        summary = materializer.us_intraday_materializer_runtime_summary()
        diagnostic = summary["runs_by_lane"]["index_current"]["intraday.bars"]["symbol_runs"][0]
        assert diagnostic["failure_stage"] == "post_acquisition"
        assert diagnostic["post_acquisition_stage"] == stage
        assert diagnostic["error_type"] == "ValueError"
        assert diagnostic["external_calls"] == 1
        assert diagnostic.get("persisted") is (None if stage == "persistence" else True)
        detail = result["results"][0]["post_acquisition_diagnostics"]
        assert detail["stage"] == stage and detail["symbol"] == "^DJI"
        assert detail["provider"] == YAHOO_INTRADAY_DESCRIPTOR.provider_key
        assert detail["resource_id"] == YAHOO_INTRADAY_RESOURCE_ID
        assert detail["receipt_count"] == 1 and detail["observation_count"] > 0
        assert detail["persistence_committed"] is (None if stage == "persistence" else True)
        assert detail["causes"][0]["frames"][-1]["function"] == {
            "persistence": "fail_insert", "validation": "validation", "reread_resolve": "reread"}[stage]
        assert "secret" not in json.dumps(detail).lower()
        assert SECRET not in caplog.text
        assert "secret" not in json.dumps(summary).lower()
        assert f"stage={stage}" in caplog.text
        with Session(engine) as db:
            # Only a failed transaction is rolled back; later errors must not
            # pretend that an already committed acquisition was undone.
            assert db.query(MarketIntradayBar).count() == (1 if stage == "persistence" else 2)
            assert db.query(MarketIntradayBar).filter_by(symbol="^IXIC").count() == 1
            assert db.query(MarketIntradayBar).filter_by(symbol="^DJI").count() == (
                0 if stage == "persistence" else 1)
            assert db.query(RawFetchResult).count() == (1 if stage == "persistence" else 2)
    finally:
        engine.dispose()


@pytest.mark.parametrize("stage", [None, "raw SQL secret", {"token": "secret"}, ["secret"], *STAGES])
def test_stage_projection_is_allowlisted_and_legacy_callers_remain_valid(stage):
    error = PostAcquisitionError(SECRET, acquisition=AcquisitionSummary(
        attempted=True, status=AcquisitionStatus.COMPLETED, external_calls=1), stage=stage)
    expected = stage if isinstance(stage, str) and stage in STAGES else None
    assert error.stage == expected
    for reason in ("post_acquisition_exception", "pre_acquisition_exception", None):
        diagnostic = materializer._symbol_run_diagnostics([{
            "symbol": "^DJI", "reason": reason, "post_acquisition_stage": stage,
            "error_type": "ValueError", "message": SECRET, "raw": SECRET,
        }])[0]
        assert diagnostic.get("post_acquisition_stage") == (
            expected if reason == "post_acquisition_exception" else None)
        assert "secret" not in json.dumps(diagnostic).lower()


@pytest.mark.parametrize("failure", ["schema", "snapshot", "reread"])
def test_real_sqlite_failure_reaches_materializer_with_dbapi_diagnostics(
    failure, tmp_path, monkeypatch, caplog,
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'diagnostics.db'}", poolclass=NullPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("CREATE TABLE unrelated (value INTEGER)")
    Base.metadata.create_all(engine)
    fetches, conflicts, rollbacks = [], [], []

    def fetch(_route, _requirement):
        fetches.append(True)
        payload = _yahoo_payload(NOW, age_seconds=30)
        payload["chart"]["result"][0]["meta"]["symbol"] = "^DJI"
        return payload, "https://fixture.invalid/?token=secret"

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def missing_table(conn, cursor, statement, parameters, context, executemany):
        if failure == "schema" and statement.startswith("INSERT INTO market_intraday_bar "):
            statement = statement.replace("INSERT INTO market_intraday_bar ", "INSERT INTO missing_r03_table ", 1)
        return statement, parameters

    @event.listens_for(engine, "after_cursor_execute")
    def snapshot_conflict(conn, cursor, statement, parameters, context, executemany):
        if failure == "snapshot" and statement.startswith("SELECT ") and "FROM source_registry" in statement:
            # The borrowed physical read is pinned. An unrelated writer
            # invalidates it; the owner must fail without replaying caller work.
            with engine.begin() as other:
                other.exec_driver_sql("INSERT INTO unrelated VALUES (1)")
            conflicts.append(True)

    def session_factory():
        db = SessionLocal(bind=engine)
        assert db.autoflush is False
        if failure == "snapshot":
            # Keep the real 517 diagnostic fixture in the existing caller
            # physical-read branch. Fresh writer admission now uses IMMEDIATE.
            event.listen(db, "after_begin", lambda _s, _t, conn: conn.exec_driver_sql("BEGIN"))
        rollback = db.rollback

        def record_rollback():
            rollbacks.append(True)
            return rollback()

        monkeypatch.setattr(db, "rollback", record_rollback)
        return db

    def platform_factory(db):
        platform = USIntradayMarketPlatform(
            db, acquisition=USIntradayAcquisitionExecutor(
                fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: NOW),
            bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
            quote_cache_invalidator=lambda _symbol: None,
        )
        read = platform._bar_reader.read_bar_candidates

        def reread(requirement):
            if failure == "reread" and fetches:
                db.connection().exec_driver_sql("SELECT * FROM missing_r03_table WHERE value = ?", (SECRET,))
            return read(requirement)

        monkeypatch.setattr(platform._bar_reader, "read_bar_candidates", reread)
        return platform

    try:
        result = materializer.materialize_us_intraday_capability(
            "intraday.bars", configured_symbols="^DJI", max_symbols=1,
            lane_id="index_current", instrument_type="index", max_external_calls=1,
            max_provider_calls=1, now=NOW, run_lock=Lock(),
            session_factory=session_factory, platform_factory=platform_factory,
        )
        assert fetches == [True] and rollbacks
        assert len(conflicts) == (1 if failure == "snapshot" else 0)
        assert result["failed_count"] == 1
        assert result["external_call_count"] == result["observed_external_call_count"] == 1
        detail = result["results"][0]["post_acquisition_diagnostics"]
        assert detail["stage"] == ("reread_resolve" if failure == "reread" else "persistence")
        assert detail["persistence_committed"] is (True if failure == "reread" else None)
        assert bool(detail["raw_result_ids"]) is (failure == "reread")
        cause = detail["causes"][0]
        assert cause["type"] == "OperationalError" and cause["module"] == "sqlalchemy.exc"
        assert cause["dbapi"] == {
            "origin": "orig", "type": "OperationalError", "module": "sqlite3",
            "sqlite_errorcode": 517 if failure == "snapshot" else 1,
            "sqlite_errorname": "SQLITE_BUSY_SNAPSHOT" if failure == "snapshot" else "SQLITE_ERROR",
            "message": "database is locked" if failure == "snapshot" else "no such table: missing_r03_table",
        }
        if failure != "reread":
            assert any(frame["file"] == "intraday_transaction.py" for frame in cause["app_frames"])
        assert all(set(frame) == {"file", "function", "line"} for frame in cause["app_frames"])
        assert all("/" not in frame["file"] and "\\" not in frame["file"] for frame in cause["app_frames"])
        diagnostic_text = json.dumps(detail)
        for forbidden in ("secret", "[SQL:", "[parameters:", "INSERT INTO", "SELECT *", '"chart"'):
            assert forbidden not in diagnostic_text and forbidden not in caplog.text
        assert '"sqlite_errorcode":' in caplog.text
        with SessionLocal(bind=engine) as check:
            assert check.query(MarketIntradayBar).count() == (1 if failure == "reread" else 0)
            assert check.query(RawFetchResult).count() == (1 if failure == "reread" else 0)
    finally:
        engine.dispose()


def test_dbapi_orig_diagnostics_remain_bounded_when_cause_is_different_or_cyclic():
    original = sqlite3.OperationalError("x" * 1000 + "\ntrailing")
    wrapper = OperationalError("SELECT secret", {"secret": SECRET}, original)
    unrelated = ValueError(SECRET)
    wrapper.__cause__ = unrelated
    unrelated.__cause__ = wrapper
    error = PostAcquisitionError(SECRET, acquisition=AcquisitionSummary(
        attempted=True, status=AcquisitionStatus.COMPLETED, external_calls=1))
    error.__cause__ = wrapper
    detail = error.diagnostics()
    assert len(detail["causes"]) == 2  # Cycle does not duplicate exceptions.
    dbapi = detail["causes"][0]["dbapi"]
    assert dbapi["origin"] == "orig" and dbapi["module"] == "sqlite3"
    assert dbapi["sqlite_errorcode"] is None and dbapi["sqlite_errorname"] is None
    assert len(dbapi["message"]) <= 240
    assert "message" not in detail["causes"][1] and "dbapi" not in detail["causes"][1]
    assert "secret" not in json.dumps(detail)
