"""Isolated scheduler clocks: no providers, SQL reads, sleeps or runtime changes."""
from datetime import date, datetime, timezone
import json
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs import scheduler
from app.market import indices, tw_current_market_operations, tw_current_market_platform
from app.market_data.integration_contracts import PersistenceSummary


@pytest.mark.parametrize("lane,failure", [("index", None), ("breadth", None),
    ("index", "acquisition"), ("index", "candidate_persist"), ("index", "callback")])
def test_scheduler_phase_log_preserves_owner_result_and_failure(monkeypatch, caplog, lane, failure):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    db = Session(engine)
    clock = [0.0]
    sentinel = ValueError("fixture original error")
    rolled_back = []
    payload = {"indices": [{}, {}]}

    def step(seconds, value):
        clock[0] += seconds
        return value

    class Mutex:
        locked = False

        def __enter__(self):
            self.locked = True
            step(.125, None)

        def __exit__(self, *args):
            self.locked = False

    mutex = Mutex()

    def acquire(*args, **kwargs):
        step(2, None)
        if failure == "acquisition":
            raise sentinel
        return SimpleNamespace(receipts=(object(),), observations=(object(),),
            summary=SimpleNamespace(external_calls=1, status=SimpleNamespace(value="completed")))

    port = SimpleNamespace(acquire_market_index_observations=acquire,
        acquire_market_breadth_observations=acquire)

    def persist_callback(*args, **kwargs):
        assert mutex.locked
        step(.2, None)
        if failure == "callback":
            raise sentinel
        return PersistenceSummary(attempted=True, committed=True)

    from app.market.tw_current_market_transaction import TaiwanCurrentMarketTransaction
    monkeypatch.setattr(TaiwanCurrentMarketTransaction, "persist_market_index_acquisition", persist_callback)
    monkeypatch.setattr(TaiwanCurrentMarketTransaction, "persist_market_breadth_acquisition", persist_callback)

    def refresh(db, *, acquisition, transaction_port, **kwargs):
        method = ("acquire_market_index_observations" if "index_id" in kwargs
            else "acquire_market_breadth_observations")
        assert not mutex.locked
        acquired = getattr(acquisition, method)()
        callback = "persist_market_index_acquisition" if "index_id" in kwargs else "persist_market_breadth_acquisition"
        getattr(transaction_port, callback)(None, acquired)
        return SimpleNamespace(limitations=())

    def build(db, *, index_id, **kwargs):
        observation = SimpleNamespace(lineage=SimpleNamespace(provider="fixture"),
            instrument=SimpleNamespace(symbol=index_id), interval="1m",
            start_at=datetime(2026, 11, 4, 1, tzinfo=timezone.utc))
        candidate = SimpleNamespace(observation=observation)
        return step(.5, SimpleNamespace(candidates=(candidate, candidate)))

    class Writer:
        def __init__(self, db):
            pass

        def persist_materialized_bars(self, candidates):
            step(.75, None)
            if failure == "candidate_persist":
                raise sentinel
            return PersistenceSummary(attempted=True, committed=True,
                observations_written=1, observations_unchanged=1)

    monkeypatch.setattr(indices, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scheduler, "monotonic", lambda: clock[0])
    monkeypatch.setattr(indices, "_SUMMARY_REFRESH_LOCK", mutex)
    monkeypatch.setattr(tw_current_market_operations, "build_current_market_executors",
        lambda *a, **k: step(.25, (port, port)))
    monkeypatch.setattr(tw_current_market_platform, "refresh_taiwan_current_index", refresh)
    monkeypatch.setattr(tw_current_market_platform, "refresh_taiwan_current_breadth", refresh)
    monkeypatch.setattr(indices, "_shared_current_market_summary", lambda *a, **k: step(1, payload))
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "is_taiwan_index_live_refresh_window", lambda _: True)
    monkeypatch.setattr(scheduler, "taiwan_presentation_session", lambda _: {"trade_date": date(2026, 11, 4)})
    monkeypatch.setattr(scheduler, "materialize_index_minute_candidates", build)
    monkeypatch.setattr(scheduler, "TaiwanBarMaterializationTransaction", Writer)
    monkeypatch.setattr(scheduler, "persist_taiwan_market_minute_state", lambda *a, **k: step(.25, {"inserted_count": 2}))
    monkeypatch.setattr(scheduler, "attach_current_market_lineage_to_stock_rows", lambda *a, **k: [])
    monkeypatch.setattr(scheduler, "persist_taiwan_intraday_stock_states", lambda *a, **k: step(.5, {"inserted_count": 3}))
    monkeypatch.setattr(db, "rollback", lambda: rolled_back.append(True))
    try:
        with caplog.at_level(logging.WARNING):
            getattr(scheduler, f"collect_taiwan_market_{lane}_summary")()
        records = [r for r in caplog.records if r.msg == "Taiwan summary invocation timing=%s"]
        assert len(records) == 1
        trace = json.loads(records[0].args[0])
        assert trace["lane"] == lane and trace["pid"] > 0 and len(trace["run_id"]) == 32
        assert trace["started_at"] and trace["finished_at"] and not mutex.locked
        calls = 0 if failure == "acquisition" else 1 if failure == "callback" else 2
        assert trace["phases"].get("summary_mutex_wait", {}).get("calls", 0) == calls
        assert trace["phases"].get("summary_mutex_wait", {}).get("wall_ms", 0) == calls * 125
        assert trace["phases"].get("canonical_persistence_callback", {}).get("calls", 0) == calls
        assert trace["phases"]["executor_build"]["wall_ms"] == 250
        if failure:
            phase = "index_acquisition_TAIEX" if failure == "acquisition" else "canonical_persistence_callback" if failure == "callback" else "candidate_persist_TAIEX"
            assert trace["status"] == "error" and trace["failed_phase"] == phase
            assert rolled_back == [True]
            assert any(r.exc_info and r.exc_info[1] is sentinel for r in caplog.records)
        else:
            assert trace["status"] == "success" and not rolled_back
            assert trace["phases"]["current_summary_reread"]["wall_ms"] == 1000
            assert trace["phases"]["minute_state_persist"]["wall_ms"] == 250
            if lane == "index":
                assert trace["wall_ms"] == 8650
                assert trace["phases"]["index_acquisition_TAIEX"]["wall_ms"] == 2000
                assert trace["counts"]["TAIEX"] == {"candidates": 2, "distinct_bar_keys": 1, "written": 1, "unchanged": 1}
                assert trace["counts"]["minute_rows"] == 2
            else:
                assert trace["counts"]["stock_state_rows"] == 3
                assert "derived_state_commit" in trace["phases"]
        assert "tw_summary_phase_timing" not in db.info
        assert "phases" not in payload
        if failure not in {"acquisition", "callback"}:
            assert payload["acquisition_policy"] == "prefer_live"
    finally:
        db.close()
        engine.dispose()
