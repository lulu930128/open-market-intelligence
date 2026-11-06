"""Single default worker and the real durable JobService; no provider IO."""
import json
import time
from threading import Event

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import eod_coverage, resumption, service
from app.jobs import taiwan_historical_input_repair as historical
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401
from test_job_cooperative_quiescence import database, wait_idle, snapshot, DAY  # noqa: F401


def test_120_historical_repairs_do_not_fill_default_fifo_ahead_of_tw_eod(database, monkeypatch):
    first, release = Event(), Event()
    visited, observed = [], []

    def step(db, job_id):
        visited.append(job_id)
        if len(visited) == 1:
            first.set()
            assert release.wait(15)
        return {"status": "partial", "next_action": "NEXT_PRODUCER_VISIT_CONTINUES_SAME_JOB"}

    def reconcile(db, **kwargs):
        observed.append(len(visited))
        return {"status": "partial", "market": "TW", "postcondition_met": False,
                "reason": "expected_date_not_observed", "stale_count": 1}

    monkeypatch.setattr(historical, "repair_taiwan_historical_input_job_step", step)
    monkeypatch.setattr(eod_coverage, "reconcile_eod_coverage", reconcile)
    ids = []
    try:
        for index in range(120):
            with Session(database) as db:
                job, created = service.enqueue_job(db, job_type=historical.JOB_TYPE,
                    target=f"{index}:daily:gap", request={"index": index},
                    task=historical.run_taiwan_historical_input_repair_job, dedupe_active=True)
                ids.append(job.id)
                assert created
            if index == 0:
                assert first.wait(5)
        with Session(database) as db:
            paused = db.query(JobRun).filter(JobRun.status == "paused").all()
            paused_count = len(paused)
            for job in paused:
                descriptor = json.loads(job.result_json)[resumption.RESUME_KEY]
                assert descriptor["checkpoint"] == {"safe_point": "not_started"}
            duplicate, created = service.enqueue_job(db, job_type=historical.JOB_TYPE,
                target="119:daily:gap", request={"index": 119},
                task=historical.run_taiwan_historical_input_repair_job, dedupe_active=True)
            assert not created and duplicate.id == ids[-1]
            eod, created = eod_coverage.enqueue_eod_coverage_reconcile(db, market="TW",
                expected_trade_date=DAY, max_symbols=2, max_runtime_seconds=60, sleep_seconds=0)
            assert created
            same, created = eod_coverage.enqueue_eod_coverage_reconcile(db, market="TW",
                expected_trade_date=DAY)
            assert not created and same.id == eod.id
        assert service.observe_job_quiescence()["default_executor_max_workers"] == 1
        pending_count = len(service._pending_tasks)
    finally:
        release.set()
        wait_idle(timeout=30)
    assert observed == [1]
    assert paused_count == 119
    assert pending_count == 2  # One repair plus original EOD Future.
    assert visited == ids  # No cancellation, repeated repair or omitted obligation.
    assert not service._paused_tasks
    assert snapshot(database, eod.id)["status"] == "error"  # Stale stays partial/error.
    assert service._enqueue_failures == 0
    with Session(database) as db:
        assert db.query(JobRun).count() == 121


def test_restart_rearms_tw_eod_before_120_history_obligations_without_losing_state(database, monkeypatch):
    visited = []
    monkeypatch.setattr(historical, "repair_taiwan_historical_input_job_step",
                        lambda db, job_id: visited.append(job_id) or {"status": "partial"})
    monkeypatch.setattr(eod_coverage, "reconcile_eod_coverage",
                        lambda db, **kw: visited.append("EOD") or
                        {"status": "success", "market": "TW", "postcondition_met": True})
    ids = []
    with Session(database) as db:
        for index in range(120):
            job = service.create_job(db, job_type=historical.JOB_TYPE, target=str(index), request={"index": index})
            ids.append(job.id)
            # Simulate an already committed attempt budget on the SAME JobRun.
            job.result_json = json.dumps({"attempts": {"2026-10:daily_backfill": {"count": 2}}})
            db.commit()
            service._persist_job_pause(job.id, historical.run_taiwan_historical_input_repair_job,
                                       (), "default", {"safe_point": "not_started"})
        eod = service.create_job(db, job_type="market_data.eod_coverage_reconcile", target="TW:full_market_stock_universe")
        service._persist_job_pause(eod.id, eod_coverage.run_eod_coverage_reconcile_job,
            ("TW", True, DAY, 2, 60, 0.0, 2, 900, False), "default", {"safe_point": "not_started"})
        db.expire_all()  # Pause dispositions were committed by independent owner Sessions.
        obligations = service.read_paused_job_obligations(db)
        assert service.resume_job_obligations(obligations) == 121
    wait_idle(timeout=30)
    assert visited == ["EOD", *ids]
    assert not service._paused_tasks
    assert service._enqueue_failures == 0
    with Session(database) as db:
        assert db.query(JobRun).count() == 121


def test_deferred_history_continuation_retains_original_result_and_retry_budget(database, monkeypatch):
    first, release = Event(), Event()
    observed = []

    def step(db, job_id):
        observed.append(json.loads(service.get_job(db, job_id).result_json or "{}"))
        if len(observed) == 1:
            first.set()
            assert release.wait(10)
        return {"status": "partial"}

    monkeypatch.setattr(historical, "repair_taiwan_historical_input_job_step", step)
    try:
        with Session(database) as db:
            service.enqueue_job(db, job_type=historical.JOB_TYPE, target="first",
                task=historical.run_taiwan_historical_input_repair_job)
            assert first.wait(5)
            job = service.create_job(db, job_type=historical.JOB_TYPE, target="existing")
            original = {"attempts": {"2026-10:daily_backfill": {"count": 2, "retry_at": "2099-01-01"}}}
            job.status, job.result_json = "success", json.dumps(original)
            db.commit()
            assert service.continue_job(db, job_id=job.id, task=historical.run_taiwan_historical_input_repair_job)
            db.refresh(job)
            assert job.status == "paused"
            assert job.message == "Waiting for default executor capacity; durable continuation pending."
            saved = json.loads(job.result_json)[resumption.RESUME_KEY]
            assert saved["previous_result"] == original
    finally:
        release.set()
        wait_idle(timeout=20)
    assert observed == [{}, original]
    assert not service._paused_tasks


def test_completion_before_deferred_pause_commit_keeps_rearm_wakeup(database, monkeypatch):
    first, release = Event(), Event()
    visited = []

    def step(db, job_id):
        visited.append(job_id)
        if len(visited) == 1:
            first.set()
            assert release.wait(10)
        return {"status": "partial"}

    monkeypatch.setattr(historical, "repair_taiwan_historical_input_job_step", step)
    persist = service._persist_job_pause
    def racing_pause(*args, **kwargs):
        release.set()
        # Execution finishes before the deferred obligation is published.
        deadline = time.monotonic() + 5
        while service._pending_tasks:
            assert time.monotonic() < deadline
            time.sleep(.005)
        persist(*args, **kwargs)
    monkeypatch.setattr(service, "_persist_job_pause", racing_pause)
    try:
        ids = []
        for index in range(2):
            with Session(database) as db:
                job, _ = service.enqueue_job(db, job_type=historical.JOB_TYPE, target=str(index),
                    task=historical.run_taiwan_historical_input_repair_job)
                ids.append(job.id)
            if index == 0:
                assert first.wait(5)
    finally:
        release.set()
        wait_idle(timeout=10)
    assert visited == ids
    assert not service._paused_tasks
