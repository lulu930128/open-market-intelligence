"""G1b offline regression: trigger phases and safe post-acquisition stages."""

from datetime import datetime, timezone
import json
import math
from threading import Lock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base, MarketIntradayBar, RawFetchResult
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
        assert "persisted" not in diagnostic
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
