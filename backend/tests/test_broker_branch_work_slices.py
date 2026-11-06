"""Same-id slices on real single-worker Futures and disposable source SQLite.

Only upstream IO is simulated. Raw receipts, snapshot quality, transactions,
JobRun pause/rearm and queued daily/EOD entrypoints use their original owners.
"""
import json
import time
from threading import Event

import pytest
from sqlalchemy.orm import Session

from app.db.models import BrokerBranchSnapshotQuality, BrokerBranchTradeDaily, JobRun, RawFetchResult, StockMaster
from app.jobs import backfill_tasks, eod_coverage, resumption, service
from app.market import broker_branch, broker_branch_market_refresh as market
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401
from test_job_cooperative_quiescence import (  # noqa: F401
    ARGS, DAY, TASK, database, make_job, provider_result, snapshot, wait_idle,
)


def seed_universe(database, count):
    symbols = [str(1000 + index) for index in range(count)]
    with Session(database) as db:
        db.query(StockMaster).delete()
        db.add_all(StockMaster(stock_id=value, stock_name=value, market="TWSE",
                               instrument_type="stock", is_active=True) for value in symbols)
        db.commit()
    return symbols


def observe_slices(monkeypatch):
    saved = []
    persist = service._persist_job_pause

    def record(job_id, task, args, lane, checkpoint, **kwargs):
        persist(job_id, task, args, lane, checkpoint, **kwargs)
        if kwargs.get("reason") == "work_slice":
            saved.append((job_id, json.loads(json.dumps(checkpoint))))

    monkeypatch.setattr(service, "_persist_job_pause", record)
    return saved


def test_1314_stocks_same_id_slices_let_tw_eod_pass_older_submitted_daily_futures(database, monkeypatch, record_property):
    symbols = seed_universe(database, 1314)
    entered, release = Event(), Event()
    fetched, order, probes, eod_receipts = [], [], [], []
    saved = observe_slices(monkeypatch)
    progress_values = []
    original_progress = service.update_progress
    # Seed acknowledged JobRuns before blocking upstream IO: first source
    # creation may own SQLite's writer until the stock transaction completes.
    job_id, daily_id, margin_id, long_id, eod_id = [make_job(database) for _ in range(5)]

    def progress(**kwargs):
        if kwargs["job_id"] == job_id:
            progress_values.append(kwargs["current"])
        return original_progress(**kwargs)

    monkeypatch.setattr(service, "update_progress", progress)
    def probe(stock_id):
        probes.append(stock_id)
        return {"trade_date": DAY}
    monkeypatch.setattr(market, "probe_broker_branch_release", probe)

    def fetch(stock_id):
        fetched.append(stock_id)
        if len(fetched) == 1:
            entered.set()
            assert release.wait(10)
        return provider_result(stock_id, empty=int(stock_id) % 7 == 0)

    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    def daily(**kwargs):
        order.append(kwargs["categories"][0])
        return {"status": "completed"}
    monkeypatch.setattr(backfill_tasks, "ensure_daily_metrics", daily)
    def prices(**kwargs):
        order.append("other-long")
        return {"status": "completed"}
    monkeypatch.setattr(backfill_tasks, "backfill_twse_stock_day", prices)

    def reconcile(db, **kwargs):
        order.append("EOD")
        branch = service.get_job(db, job_id)
        descriptor = json.loads(branch.result_json)[resumption.RESUME_KEY]
        eod_receipts.append((len(fetched), branch.id, branch.status, descriptor["checkpoint"],
                             db.query(RawFetchResult).count(),
                             db.query(BrokerBranchSnapshotQuality).count(), time.monotonic() - released_at))
        # Admission priority must not manufacture EOD data/qualification.
        return {"status": "partial", "market": "TW", "postcondition_met": False,
                "reason": "expected_date_not_observed", "stale_count": 1}
    monkeypatch.setattr(eod_coverage, "reconcile_eod_coverage", reconcile)
    older = []
    try:
        service.submit_job_task(TASK, job_id, *ARGS)
        assert entered.wait(5)
        for queued, category in ((daily_id, "daily"), (margin_id, "margin")):
            older.append(queued)
            service.submit_job_task(backfill_tasks.run_market_daily_metrics_job, queued,
                DAY, DAY, [category], 1, True, 0.0, True)
        queued = long_id
        older.append(queued)
        service.submit_job_task(backfill_tasks.run_twse_daily_price_job, queued,
            "2330", DAY, DAY, None, 0.0, True)
        service.submit_job_task(eod_coverage.run_eod_coverage_reconcile_job,
            eod_id, "TW", True, DAY, 2, 60, 0.0, 2, 900)
        # These are already submitted FIFO Futures, not paused descriptors.
        with service._executor_lock:
            assert [t.job_id for t in service._pending_tasks.values()] == [job_id, *older, eod_id]
            assert all(t.started_at is None for t in list(service._pending_tasks.values())[1:])
            assert service._executor._max_workers == 1
    finally:
        released_at = time.monotonic()
        release.set()
        wait_idle(timeout=180)

    assert order == ["EOD", "daily", "margin", "other-long"]
    count, original_id, status, cursor, raw_count, quality_count, wait_seconds = eod_receipts[0]
    assert (count, original_id, status, raw_count, quality_count) == (8, job_id, "paused", 8, 8)
    assert cursor["safe_point"] == "stock_transaction_complete" and cursor["current"] == 8
    assert cursor["total"] == 1314 and cursor["state"]["completed"] == 8
    assert wait_seconds < 5  # Fixture safe-point admission, not a live provider SLO.
    assert fetched == symbols and len(set(fetched)) == 1314
    assert len(probes) == 1  # Slices continue the original date-validated loop.
    assert [item[0] for item in saved] == [job_id] * 164
    assert [item[1]["current"] for item in saved] == list(range(8, 1314, 8))
    assert all(item[1]["total"] == 1314 for item in saved)
    assert progress_values == sorted(progress_values)
    result = snapshot(database, job_id)
    empty_count = sum(int(value) % 7 == 0 for value in symbols)
    assert result["status"] == "success" and result["progress_current"] == 1314
    assert result["result"]["request_count"] == 1315
    assert result["result"]["success_count"] == 1314 - empty_count
    assert result["result"]["no_data_count"] == empty_count
    assert result["result"]["error_count"] == 0
    assert snapshot(database, eod_id)["status"] == "error"
    assert all(snapshot(database, value)["status"] == "success" for value in older)
    with Session(database) as db:
        assert db.query(JobRun).count() == 5
        assert db.query(RawFetchResult).count() == 1314
        quality = db.query(BrokerBranchSnapshotQuality).all()
        assert len(quality) == 1314 and all(row.raw_result_id is not None for row in quality)
        assert db.query(BrokerBranchTradeDaily).count() == 1314 - empty_count
    assert not service._paused_tasks and not service._resuming_jobs
    assert service._enqueue_failures == service._task_failures == 0
    record_property("slice_receipt", json.dumps({"stocks": len(fetched), "work_slices": len(saved),
        "max_workers": 1, "eod_at_stock": count, "eod_wait_seconds": wait_seconds,
        "order": order, "raw_receipts": raw_count, "same_job_id": job_id}))


@pytest.mark.parametrize("seconds_per_stock,runtime_limit,expected_attempts,expected_slices", [
    (61, 7200, 3, [1, 2]),
    (20, 100, 5, [3]),
])
def test_time_slice_and_total_runtime_budget_survive_continuation(
    database, monkeypatch, seconds_per_stock, runtime_limit, expected_attempts, expected_slices,
):
    symbols = seed_universe(database, 10 if runtime_limit == 100 else 3)
    clock = [0.0]
    fetched = []
    saved = observe_slices(monkeypatch)
    monkeypatch.setattr(backfill_tasks, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        clock[0] += seconds_per_stock  # Complete IO first; no forced preemption.
        return provider_result(stock_id)
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    job_id = make_job(database)
    service.submit_job_task(TASK, job_id, DAY, 0.0, 2500, runtime_limit)
    wait_idle(timeout=15)
    assert fetched == symbols[:expected_attempts]
    assert [item[1]["current"] for item in saved] == expected_slices
    result = snapshot(database, job_id)["result"]
    assert result["request_count"] == expected_attempts + 1
    if runtime_limit == 100:
        assert result["reason"] == "max_runtime_reached"


def test_all_failed_prefix_advances_once_and_keeps_original_max_stocks_budget(database, monkeypatch):
    symbols = seed_universe(database, 21)
    fetched = []
    saved = observe_slices(monkeypatch)
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        raise RuntimeError("fixture upstream failure")
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    job_id = make_job(database)
    service.submit_job_task(TASK, job_id, DAY, 0.0, 10, 7200)
    wait_idle(timeout=15)
    assert fetched == symbols[:10]
    assert [item[1]["current"] for item in saved] == [8]
    result = snapshot(database, job_id)["result"]
    assert result["request_count"] == 11 and result["error_count"] == 10
    assert result["reason"] == "batch_limit_reached"
    assert len(result["errors"]) == 10
    with Session(database) as db:
        assert db.query(BrokerBranchTradeDaily).count() == 0


def test_legacy_running_checkpoint_preserves_progress_and_skips_source_success_and_empty(database, monkeypatch):
    symbols = seed_universe(database, 17)
    fetched = []
    saved = observe_slices(monkeypatch)
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        return provider_result(stock_id, empty=stock_id == symbols[0])
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    job_id = make_job(database)
    with Session(database) as db:
        for stock_id in symbols[:5]:
            broker_branch.ensure_broker_branch_daily(db, stock_id=stock_id, trade_date=DAY)
        service.start_job(db, job_id)
        service.update_progress(db, job_id, current=5, total=17)
        started_at = service.get_job(db, job_id).started_at
    # Old release's real stock checkpoint had no slice state.
    service._persist_job_pause(job_id, TASK, ARGS, "default",
        {"safe_point": "stock_transaction_complete", "stock_id": symbols[4],
         "trade_date": DAY.isoformat(), "current": 5, "total": 17})
    with Session(database) as db:
        assert service.mark_interrupted_jobs(db) == 0
        assert service.recover_paused_jobs(db) == 1
    wait_idle(timeout=20)
    assert fetched == symbols
    assert [item[1]["current"] for item in saved] == [13]
    assert all(item[1]["total"] == 17 for item in saved)
    result = snapshot(database, job_id)
    assert result["id"] == job_id and result["status"] == "success"
    assert result["progress_current"] == result["progress_total"] == 17
    assert result["started_at"] == started_at
    with Session(database) as db:
        assert db.query(JobRun).count() == 1
        assert db.query(RawFetchResult).count() == 17


def test_restart_in_second_slice_new_process_keeps_same_job_and_committed_raw_receipts(database, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path

    symbols = seed_universe(database, 17)
    entered, release = Event(), Event()
    fetched = []
    saved = observe_slices(monkeypatch)
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        if stock_id == symbols[9]:
            entered.set()
            assert release.wait(10)
        return provider_result(stock_id, empty=stock_id == symbols[0])
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    job_id = make_job(database)
    try:
        service.submit_job_task(TASK, job_id, *ARGS)
        assert entered.wait(10)
        lease = service.request_job_pause()
        assert not service.jobs_paused(lease)
        with Session(database) as db:
            assert db.query(RawFetchResult).count() == 9
    finally:
        release.set()
        wait_idle(timeout=15)
    assert service.jobs_paused(lease) and fetched == symbols[:10]
    assert [item[1]["current"] for item in saved] == [8]
    with Session(database) as db:
        original = service.get_job(db, job_id)
        assert original.status == "paused" and original.ended_at is None
        cursor = json.loads(original.result_json)[resumption.RESUME_KEY]["checkpoint"]
        assert cursor["current"] == cursor["state"]["completed"] == 10
        assert cursor["total"] == 17
        receipts = [(row.id, row.source_id, row.raw_text, row.content_hash, row.fetched_at)
                    for row in db.query(RawFetchResult).order_by(RawFetchResult.id)]
        assert len(receipts) == 10

    child = '''
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path('backend/tests').resolve()))
import g3_offline_guard
g3_offline_guard.install()
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_job_cooperative_quiescence import service, market, broker_branch, provider_result, DAY, wait_idle
engine = create_engine(sys.argv[1], poolclass=NullPool)
service.SessionLocal = lambda: Session(engine)
service.settings.job_worker_max_concurrency = 1
market.probe_broker_branch_release = lambda _: {'trade_date': DAY}
fetched = []
def fetch(stock_id):
    fetched.append(stock_id)
    return provider_result(stock_id)
broker_branch._fetch_nstock_branch_top15 = fetch
with Session(engine) as db:
    assert service.mark_interrupted_jobs(db) == 0
    assert service.recover_paused_jobs(db) == 1
wait_idle(timeout=15)
with Session(engine) as db:
    job = db.query(service.JobRun).one()
    assert job.id == int(sys.argv[2]) and job.status == 'success'
    assert job.progress_current == job.progress_total == 17
    assert json.loads(job.result_json)['request_count'] == 18
assert not service._paused_tasks and service._enqueue_failures == 0
service.shutdown_job_executor(wait=True)
engine.dispose()
print(json.dumps({'fetched': fetched, 'job_id': int(sys.argv[2])}))
'''
    result = subprocess.run([sys.executable, "-B", "-c", child, str(database.url), str(job_id)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip()) == {"fetched": symbols[10:], "job_id": job_id}
    with Session(database) as db:
        rows = db.query(RawFetchResult).order_by(RawFetchResult.id).all()
        assert len(rows) == 17
        assert [(row.id, row.source_id, row.raw_text, row.content_hash, row.fetched_at)
                for row in rows[:10]] == receipts
        assert db.query(JobRun).count() == 1


def test_restart_retry_of_rolled_back_stock_does_not_regress_displayed_checkpoint(database, monkeypatch):
    from app.jobs import cooperative

    fetched, leases, currents = [], [], []
    checkpoint = cooperative.checkpoint_after_transaction
    def record(db, evidence):
        assert not db.in_transaction()
        currents.append(evidence["current"])
        checkpoint(db, evidence)
    monkeypatch.setattr(cooperative, "checkpoint_after_transaction", record)
    monkeypatch.setattr(market, "probe_broker_branch_release", lambda _: {"trade_date": DAY})
    def fetch(stock_id):
        fetched.append(stock_id)
        if len(fetched) == 1:
            leases.append(service.request_job_pause())
            raise RuntimeError("fixture rolled-back stock")
        return provider_result(stock_id)
    monkeypatch.setattr(broker_branch, "_fetch_nstock_branch_top15", fetch)
    job_id = make_job(database)
    service.submit_job_task(TASK, job_id, *ARGS)
    wait_idle(timeout=10)
    assert snapshot(database, job_id)["progress_current"] == 1
    service.resume_jobs(leases[0])
    wait_idle(timeout=10)
    assert fetched == ["1101", "1101", "2330", "6488"]
    assert currents == sorted(currents)
    assert snapshot(database, job_id)["status"] == "success"
