"""3406 scope/admission regression using disposable SQLite and no provider IO."""
import json
from datetime import datetime, timedelta

from app.db.models import JobRun, StockMaster, WatchlistGroup, WatchlistItem
from app.jobs import taiwan_intraday_bar_scheduler as scheduler
from app.jobs import taiwan_intraday_demand as demand
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_universe import resolve_taiwan_tier_a_target_plan
from test_taiwan_intraday_bar_scheduler import _scheduler_db


def test_3406_outside_cap_has_no_job_then_explicit_tier_a_admission_recovers(monkeypatch):
    engine, factory = _scheduler_db()
    now = datetime(2026, 10, 20, 9, 15, tzinfo=TAIWAN_TZ)
    monkeypatch.setattr(demand, "_now", lambda: now)
    monkeypatch.setattr(demand, "_reread", lambda db, request, at: {
        "reread_ready": False, "reread_trade_date": request["trade_date"],
        "current_session_bar_count": 0})
    dispatched = []
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw:
                        dispatched.append(job_id))
    try:
        with factory() as db:
            db.add_all([StockMaster(stock_id=code, market="TWSE", instrument_type="stock",
                                   is_active=True) for code in ("2330", "2317", "3406")])
            group = WatchlistGroup(group_name="fixture", is_active=True)
            db.add(group)
            db.flush()
            db.add_all([WatchlistItem(group_id=group.id, stock_id=code, enabled=True,
                                     priority=priority) for code, priority in (("2317", 10), ("3406", 200))])
            db.commit()
            plan = resolve_taiwan_tier_a_target_plan(db, max_symbols=2,
                configured_symbols=["2330"], lease_symbols=[])
            assert plan["symbols"] == ["2330", "2317"]
            assert {"stock_id": "3406", "reason": "scheduler_hard_cap",
                    "origins": ["watchlist"]} in plan["skipped_targets"]
            scheduler._submit_batch(db, plan["symbols"], now=now, origin="scheduler",
                                    enqueuer=demand.enqueue_intraday_materialization_demand)
            assert db.query(JobRun).filter(JobRun.target.like("%:3406:%")).count() == 0
            # Fixture-only explicit priority selection does not increase the cap.
            plan = resolve_taiwan_tier_a_target_plan(db, max_symbols=2,
                configured_symbols=["3406"], lease_symbols=[])
            assert plan["symbols"][0] == "3406" and len(plan["symbols"]) == 2
            def closed(*args, **kwargs):
                raise demand.jobs.JobAdmissionClosed("fixture pause")
            monkeypatch.setattr(demand.jobs, "submit_job_task", closed)
            job, created = demand.enqueue_intraday_materialization_demand(db,
                stock_id="3406", requested_at=now, consumer="scheduler",
                timeout_seconds=120, max_external_calls=2)
            assert created and demand.is_restart_handoff(job)
            job_id = job.id
            budget = json.loads(job.result_json)["external_call_budget_used"]
            assert budget == 0 and job.status == "queued"
            monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw:
                                dispatched.append(job_id))
            assert demand.dispatch_due_materializations(db, requested_at=now + timedelta(seconds=15)) == 1
            db.refresh(job)
            assert job.id == job_id and job.status == "running"
            assert json.loads(job.result_json)["external_call_budget_used"] == budget
            assert demand.dispatch_due_materializations(db, requested_at=now + timedelta(seconds=16)) == 0
            assert dispatched.count(job_id) == 1
    finally:
        engine.dispose()
