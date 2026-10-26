"""Offline regression for the production daily/margin and Radar loops."""
from datetime import date
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models as m
from app.jobs import backfill_tasks, service
from app.jobs import resumption
from app.jobs.cooperative import JobPaused, JobStopToken, checkpoint_after_transaction, current_job_stop
from app.market import backfill, daily_metrics_backfill as daily
from app.watchlists import radar_automation as radar
from app.utils.backfill_checkpoint import validate_period_state
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401
from test_job_period_checkpoints import database, price_provider  # noqa: F401
from test_job_cooperative_quiescence import make_job, snapshot, wait_idle


def setup_daily(monkeypatch):
    days = [date(2026, 1, 2), date(2026, 1, 5)]
    monkeypatch.setattr(daily, "_list_metric_sources", lambda db, **_: db.query(m.SourceRegistry).filter(m.SourceRegistry.id == 1).all())
    monkeypatch.setattr(daily, "_market_trade_dates", lambda db, start_date, end_date: [d for d in days if start_date <= d <= end_date])
    monkeypatch.setattr(daily, "_latest_market_trade_date", lambda **_: days[-1])
    monkeypatch.setattr(daily, "_default_start_date", lambda db, **_: days[-1] if db.query(m.RawFetchResult).count() else days[0])
    monkeypatch.setattr(daily, "_source_has_date_rows", lambda **_: False)
    return days


@pytest.mark.parametrize("identity", [[], ["bad", "2026-01-05", [], []], ["2026-01-02", "2026-01-05", None, []]])
def test_malformed_daily_context_preserves_durable_pause(database, monkeypatch, identity):
    days = setup_daily(monkeypatch)
    calls = []
    def refresh(db, source_id, trade_date):
        calls.append(trade_date)
        db.add(m.RawFetchResult(source_id=source_id, url=str(trade_date), method="GET", raw_text="fixture"))
        db.commit()
        service.request_job_pause()
        return {"fetch_status": "success", "parse_status": "success", "inserted_count": 1}
    monkeypatch.setattr(daily, "refresh_source", refresh)
    job_id = make_job(database)
    service.submit_job_task(backfill_tasks.run_market_daily_metrics_job, job_id,
                            None, days[-1], ["margin_trading"], 30, False, 0.0, False)
    wait_idle()
    with Session(database) as db:
        job = service.get_job(db, job_id)
        result = json.loads(job.result_json)
        result[resumption.RESUME_KEY]["checkpoint"]["state"]["identity"] = identity
        saved = job.result_json = json.dumps(result)
        db.commit()
        with pytest.raises(ValueError, match="JOB_RESUME_PERIOD_IDENTITY_INVALID"):
            service.read_paused_job_obligations(db)
        db.refresh(job)
        assert job.status == "paused" and job.result_json == saved
    assert calls == days[:1]


@pytest.mark.parametrize("mode", ["latest", "explicit", "source_removed", "uncommitted"])
def test_daily_margin_committed_source_date_resume(database, monkeypatch, mode):
    days = setup_daily(monkeypatch)
    fetched = []
    def refresh(db, source_id, trade_date):
        fetched.append(trade_date)
        db.add(m.RawFetchResult(source_id=source_id, url=trade_date.isoformat(), method="GET", raw_text="fixture"))
        if mode != "uncommitted":
            db.commit()
        service.request_job_pause()
        return {"fetch_status": "success", "parse_status": "success", "inserted_count": 1}
    monkeypatch.setattr(daily, "refresh_source", refresh)
    job_id = make_job(database)
    service.submit_job_task(backfill_tasks.run_market_daily_metrics_job, job_id,
                            None if mode == "latest" else days[0], days[-1], ["margin_trading"], 30, False, 0.0, False)
    wait_idle()
    if mode == "uncommitted":
        assert snapshot(database, job_id)["status"] == "error"
        with Session(database) as db:
            assert db.query(m.RawFetchResult).count() == 0
        return
    assert snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        descriptor = service.read_paused_job_obligations(db)[job_id]
        assert db.query(m.RawFetchResult).count() == 1
        state = descriptor["checkpoint"]["state"]
        state["totals"]["metric_inserted_count"] = 999
        state["deltas"][0]["metric_inserted_count"] = 999
        with pytest.raises(ValueError, match="STATE_INVALID"):
            validate_period_state(state)
    if mode == "source_removed":
        monkeypatch.setattr(daily, "_list_metric_sources", lambda **_: [])
    def resumed(db, source_id, trade_date):
        fetched.append(trade_date)
        db.add(m.RawFetchResult(source_id=source_id, url=trade_date.isoformat(), method="GET", raw_text="fixture"))
        db.commit()
        return {"fetch_status": "success", "parse_status": "success", "inserted_count": 1}
    monkeypatch.setattr(daily, "refresh_source", resumed)
    service.resume_jobs(service._admission_pause)
    wait_idle()
    if mode == "source_removed":
        assert fetched == days[:1]
        assert snapshot(database, job_id)["status"] == "paused"
        assert service.observe_job_quiescence()["unresolved_enqueues"] > 0
    else:
        assert fetched == days
        assert snapshot(database, job_id)["result"]["inserted_count"] == 2


@pytest.mark.parametrize("empty_after_pause", [False, True])
@pytest.mark.parametrize("created,evaluated", [(0, 0), (3, 2)])
def test_snapshot_scope_resume_skips_committed_group(database, monkeypatch, empty_after_pause, created, evaluated):
    day = date(2026, 1, 2)
    monkeypatch.setattr(radar, "_resolve_group_ids", lambda **_: [1, 2])
    monkeypatch.setattr(radar.radar_service, "get_watchlist_group_radar_bundle", lambda **_: ({}, []))
    monkeypatch.setattr(radar.radar_outcome_service, "watchlist_radar_snapshot_date", lambda _: day)
    monkeypatch.setattr(radar.radar_active_v2_service, "build_radar_v2_active_projection_from_db", lambda **_: {})
    monkeypatch.setattr(radar, "get_watchlist_radar_daily_coverage", lambda **_: {"complete": True, "reconciliation_complete": True})
    groups = []
    def persist(db, group_id, **_):
        groups.append(group_id)
        db.add(m.RawFetchResult(source_id=1, url=str(group_id), method="GET", raw_text="fixture"))
        db.commit()
        if len(groups) == 1:
            service.request_job_pause()
        return {"evaluation_created_count": created, "evaluation_ids": [group_id], "rule_version": "fixture", "snapshot_date": day.isoformat()}
    monkeypatch.setattr(radar.radar_active_v2_service, "persist_radar_v2_active", persist)
    def outcomes(db, **_):
        db.execute(text("SELECT 1"))  # Original owner's trailing read, not a write.
        return {"evaluated_count": evaluated, "error_count": 0, "errors": []}
    monkeypatch.setattr(radar.radar_shadow_v2_service, "evaluate_pending_radar_v2_outcomes", outcomes)
    job_id = make_job(database)
    service.submit_job_task(backfill_tasks.run_watchlist_radar_auto_snapshot_job, job_id,
                            [1, 2], "action", True, True, 30, 100, False, 30, day, 10, True)
    wait_idle()
    assert groups == [1] and snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        state = service.read_paused_job_obligations(db)[job_id]["checkpoint"]["state"]
        assert state["totals"]["radar_active_persisted_count"] == created
        assert state["totals"]["radar_evaluated_count"] == evaluated
        state["totals"]["radar_active_persisted_count"] += 1
        state["deltas"][0]["radar_active_persisted_count"] += 1
        with pytest.raises(ValueError, match="STATE_INVALID"):
            validate_period_state(state)
    if empty_after_pause:
        monkeypatch.setattr(radar, "_resolve_group_ids", lambda **_: [])
    service.resume_jobs(service._admission_pause)
    wait_idle()
    saved = snapshot(database, job_id)
    if empty_after_pause:
        assert groups == [1] and saved["status"] == "paused"
        assert service.observe_job_quiescence()["unresolved_enqueues"] > 0
    else:
        assert groups == [1, 2] and saved["status"] == "success"
        assert saved["result"]["saved_count"] == 2
        assert saved["result"]["active_persisted_count"] == 2 * created
        assert saved["result"]["evaluated_count"] == 2 * evaluated


@pytest.mark.parametrize("venue", ["twse", "tpex"])
def test_price_release_universe_becomes_empty_is_not_completed(database, monkeypatch, venue):
    price_provider(monkeypatch, venue, lambda _: service.request_job_pause())
    task = getattr(backfill_tasks, f"run_{venue}_daily_price_job")
    job_id = make_job(database)
    service.submit_job_task(task, job_id, "2330", date(2026, 1, 1), date(2026, 2, 28),
                            1 if venue == "twse" else 2, 0.0, False)
    wait_idle()
    monkeypatch.setattr(backfill, "expected_daily_price_date", lambda: date(2025, 12, 31))
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    assert service.observe_job_quiescence()["unresolved_enqueues"] > 0


@pytest.mark.parametrize("commit", [True, False])
def test_outcome_checkpoint_is_only_after_original_commit(monkeypatch, commit):
    import test_watchlist_radar_outcome_v2 as fixture
    from app.watchlists import radar_outcome_v2_service as owner
    case = fixture.WatchlistRadarOutcomeV2PersistenceTests()
    case.setUp()
    monkeypatch.setattr(owner, "_corporate_action_context", lambda **_: ("checked_clear", [], []))
    token = JobStopToken()
    token.requested.set()
    context = current_job_stop.set(token)
    try:
        with Session(case.engine) as db:
            evaluation_id = case._evaluation(db)
            case._add_daily_bars(db, count=5)
            db.commit()
            checkpoints = []
            def checkpoint(value):
                assert not db.in_transaction()
                checkpoints.append(value)
                checkpoint_after_transaction(db, value)
            if commit:
                with pytest.raises(JobPaused):
                    owner.evaluate_radar_outcome_v2(db=db, evaluation_id=evaluation_id, checkpoint=checkpoint)
            else:
                owner.evaluate_radar_outcome_v2(db=db, evaluation_id=evaluation_id, commit=False, checkpoint=checkpoint)
                db.rollback()
            assert bool(checkpoints) == commit
        with Session(case.engine) as db:
            assert db.query(m.RadarOutcomePath).count() == (3 if commit else 0)
    finally:
        current_job_stop.reset(context)
        case.doCleanups()
