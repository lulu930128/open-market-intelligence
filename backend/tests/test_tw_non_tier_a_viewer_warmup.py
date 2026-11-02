"""Viewer command to real canonical persistence, with offline provider fixtures."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, JobRun, StockMaster, MarketIntradayBar, MarketIntradayBarLineage
from app.jobs import taiwan_bar_bootstrap as bootstrap, taiwan_intraday_demand as demand
from app.market.trading_calendar import TAIWAN_TZ
from app.market.providers.tw_intraday_bars import IntradayProviderPayload, NStockIntradayAdapter, YahooIntradayAdapter
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market import source_health, tw_intraday_universe as universe
import test_tw_intraday_consumer_demand as demand_contracts


NOW = datetime(2026, 9, 16, 10, 0, tzinfo=TAIWAN_TZ)


@pytest.mark.parametrize("contract", [
    demand_contracts.test_same_job_three_heartbeat_attempts_and_cooldown,
    demand_contracts.test_heartbeat_only_dispatches_due_retry_for_existing_valid_lease,
    demand_contracts.test_expired_status_is_read_only_and_has_no_next_dispatch,
])
def test_existing_viewer_lifecycle_contracts_in_memory(monkeypatch, contract):
    """Reuse established assertions without their file-backed SQLite fixture."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[JobRun.__table__, StockMaster.__table__])
    factory = sessionmaker(engine)
    env = SimpleNamespace(engine=engine, factory=factory, dispatches=[], clock=[NOW])
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: env.dispatches.append(job_id))
    monkeypatch.setattr(demand, "_now", lambda: env.clock[0])
    try:
        with factory() as db:
            db.add(StockMaster(stock_id="2330", stock_name="fixture", market="TWSE", instrument_type="stock", is_active=True))
            db.commit()
        contract(env, monkeypatch)
    finally:
        engine.dispose()


@pytest.mark.parametrize("code,venue", [("2317", "TWSE"), ("6488", "TPEX"), ("8299", "TPEX")])
@pytest.mark.parametrize("coverage", ["missing", "partial", "ready"])
def test_viewer_command_non_tier_a_materializes_only_real_supplied_bars(monkeypatch, code, venue, coverage):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    dispatches, calls = [], []
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: dispatches.append(job_id))
    monkeypatch.setattr(demand, "_now", lambda: NOW)
    tier_a = [str(7000 + index) for index in range(32)]
    monkeypatch.setattr(universe, "_configured_symbols", lambda: tier_a + [code])
    monkeypatch.setattr(universe, "_lease_symbols", lambda: [])
    assert universe.settings.scheduler_taiwan_intraday_bar_max_symbols == 32
    count = {"missing": 0, "partial": 2, "ready": 60}[coverage]
    points = [{"交易日": "20260916", "交易時間": (NOW.replace(hour=9) + timedelta(minutes=i)).strftime("%H%M%S"),
               "開盤價": "100", "最高價": "101", "最低價": "99", "收盤價": "100", "成交量": "1"}
              for i in range(count)]
    def nstock_fetch(*args):
        calls.append(("nstock", args))
        return IntradayProviderPayload(raw_text=json.dumps({"data": [{"參考價": "100", "總成交量": str(count), "分K": points}]}),
            status="available", url="https://fixture.invalid/nstock", status_code=200)
    def yahoo_fetch(*args):
        calls.append(("yahoo", args))
        return IntradayProviderPayload(raw_text=None, status="failed", url="https://fixture.invalid/yahoo", status_code=429, retry_after_seconds=600)
    nstock, yahoo = NStockIntradayAdapter(nstock_fetch, clock=lambda: NOW), YahooIntradayAdapter(yahoo_fetch, clock=lambda: NOW)
    monkeypatch.setattr(demand, "TaiwanIntradayAcquisitionExecutor", lambda **kw: TaiwanIntradayAcquisitionExecutor(nstock=nstock, yahoo=yahoo, **kw))
    try:
        with factory() as db:
            db.add_all([StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE", instrument_type="stock", is_active=True)
                        for symbol in tier_a])
            db.add(StockMaster(stock_id=code, stock_name=code, market=venue, instrument_type="stock", is_active=True))
            db.commit()
            plan = universe.resolve_taiwan_intraday_target_universe(db)
            assert code not in plan["symbols"]
            assert {"stock_id": code, "reason": "scheduler_hard_cap", "origins": ["configured"]} in plan["skipped_targets"]
            job, created = bootstrap.enqueue_taiwan_intraday_viewer_warmup(db, code, NOW)
            assert created and job is not None
            job_id = job.id
            request = demand.consumer_request(job)
            assert request["stock_id"] == code and request["consumer"] == "viewer"
            assert request["max_external_calls"] == 6
        assert dispatches == [job_id]
        demand.run_consumer_demand(job_id)
        with factory() as db:
            job = db.get(JobRun, job_id)
            result = json.loads(job.result_json)
            assert db.query(MarketIntradayBar).count() == count
            assert db.query(MarketIntradayBarLineage).count() == count
            assert result["current_session_bar_count"] == count
            assert result["bars_written_count"] == count
            assert result["reread_ready"] is (coverage == "ready")
            assert result["external_call_budget_used"] <= 2
            assert result["attempt_count"] == 1
            assert len(calls) <= 2
            reread = demand._reread(db, request, NOW)
            assert reread["current_session_bar_count"] == count
            assert reread["snapshot_revision"] == result["snapshot_revision"]
            health = source_health.build_taiwan_source_health(db, stock_id=code, dataset="market_intraday_bar_1m", now=NOW)
            entry = health["entries"][0]
            assert entry["row_count"] == count
            selection = entry["health_dimensions"]["acquisition_selection"]
            assert selection["status"] == "not_selected"
            assert selection["reason"] == "scheduler_hard_cap"
            assert selection["continuous_live_guaranteed"] is False
            if coverage == "ready":
                assert job.status == "success"
                assert bootstrap.enqueue_taiwan_intraday_viewer_warmup(db, code, NOW) == (None, False)
        assert dispatches == [job_id]
    finally:
        engine.dispose()
