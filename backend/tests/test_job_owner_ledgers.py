"""Original-owner continuation tests on disposable SQLite and real Futures."""
import json
import time
from datetime import date, datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.db.models import JobRun, RawFetchResult, MarketDatasetCoverageCheckpoint
from app.jobs import service, backfill_tasks, eod_coverage as eod_job, taiwan_bar_bootstrap as bootstrap
from app.jobs import taiwan_intraday_demand as demand
from app.jobs.owner_continuation import LEDGER_KEY
from app.market_data import eod_coverage as eod
from app.us_market import ohlc_priority as priority
from app.utils.owner_checkpoint import validate_owner_state
from r1d_test_support import isolated_job_lifecycle  # noqa: F401
from test_job_cooperative_quiescence import database, make_job, snapshot, wait_idle  # noqa: F401
from test_us_ohlc_priority import _platform_result
from test_tw_materialization_convergence import env, NOW  # noqa: F401

ACTUAL_SUBMIT = service.submit_job_task

DAY = date(2026, 10, 16)


class EodPort:
    def __init__(self, callback=None, *, symbols=("A", "B", "C", "D", "E", "F"), partial=False):
        self.symbols = symbols
        self.callback = callback
        self.calls = []
        self.release = DAY
        self.partial = partial

    def expected_trade_date(self, **_):
        return self.release

    def compute_coverage(self, db, *, expected_trade_date):
        current = frozenset(row.url[4:] for row in db.query(RawFetchResult).all() if row.url.startswith("eod:"))
        members = tuple(eod.UniverseMember(s, "NYSE") for s in self.symbols)
        return eod.CoverageComputation(market="US", dataset_id=eod.US_DATASET_ID,
            scope_key=eod.US_SCOPE_KEY, universe_source="fixture", expected_trade_date=expected_trade_date,
            latest_data_date=expected_trade_date if current else None, universe_hash=eod._universe_hash(members),
            members=members, current_symbols=current, partial_symbols=frozenset(),
            stale_symbols=frozenset(), missing_symbols=frozenset(self.symbols) - current)

    def refresh_symbol(self, db, *, symbol, expected_trade_date, max_external_calls):
        self.calls.append((symbol, max_external_calls))
        if self.callback:
            self.callback(db, symbol)
        if not self.partial:
            db.add(RawFetchResult(source_id=1, url="eod:" + symbol, method="GET", raw_text="fixture"))
            db.commit()
        return {"external_call_count": 1}

    def publish_distribution(self, db, **_):
        return {"status": "fixture", "completed_symbols": len(self.calls)}


def wire_eod(monkeypatch, port, order=("F", "D", "B")):
    monkeypatch.setattr(eod_job, "US_FULL_MARKET_EOD_LIFECYCLE", port)
    monkeypatch.setattr(eod_job.settings, "enable_market_refresh_priority", True)
    monkeypatch.setattr(eod_job, "active_market_refresh_priorities", lambda *a, **k: order)


def submit_eod(database, *, symbols=4, runtime=60, errors=5):
    job_id = make_job(database)
    service.submit_job_task(eod_job.run_eod_coverage_reconcile_job, job_id,
        "US", True, DAY, symbols, runtime, 0.0, errors, 60)
    return job_id


def saved_state(database, job_id):
    with Session(database) as db:
        return service.read_paused_job_obligations(db)[job_id]["checkpoint"]["state"]


@pytest.mark.parametrize("failed", [False, True])
def test_eod_frozen_priority_exact_completed_set_and_quota(database, monkeypatch, failed):
    def first(db, symbol):
        if len(port.calls) == 1:
            service.request_job_pause()
            if failed:
                # A dirty provider scope must roll back before checkpoint.
                db.add(RawFetchResult(source_id=1, url="uncommitted", method="GET", raw_text="fixture"))
                raise RuntimeError("partial provider consumption")
    port = EodPort(first, partial=True)
    wire_eod(monkeypatch, port)
    job_id = submit_eod(database)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    state = saved_state(database, job_id)
    assert state["items"] == ["F", "D", "B", "A"]
    assert state["totals"]["calls"] == (2 if failed else 1)
    with Session(database) as db:
        assert not db.query(RawFetchResult).filter_by(url="uncommitted").first()
        row = db.query(MarketDatasetCoverageCheckpoint).one()
        assert row.cursor_symbol == "F" and row.attempted_count == 1
    # New priorities cannot reorder/replay this Job's frozen work.
    wire_eod(monkeypatch, port, order=("A", "C", "E"))
    port.callback = None
    service._paused_tasks.clear()
    service.resume_jobs(service._admission_pause)
    with Session(database) as db:
        service.recover_paused_jobs(db)
    wait_idle()
    assert [s for s, _ in port.calls] == (["F", "D", "B"] if failed else ["F", "D", "B", "A"])
    assert port.calls[-1][1] == 1
    result = snapshot(database, job_id)["result"]
    assert result["attempted_count"] == len(port.calls)
    assert result["error_count"] == int(failed)


@pytest.mark.parametrize("change", ["release", "universe", "runtime", "backoff"])
def test_eod_resume_guards_and_consumed_runtime(database, monkeypatch, change):
    clock = [0.0]
    monkeypatch.setattr(eod, "monotonic", lambda: clock[0])
    def first(db, symbol):
        clock[0] = 60.0 if change == "runtime" else 1.0
        service.request_job_pause()
        if change == "backoff":
            raise RuntimeError("provider failed")
    port = EodPort(first)
    wire_eod(monkeypatch, port)
    job_id = submit_eod(database, errors=1 if change == "backoff" else 5)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    if change == "release":
        port.release += timedelta(days=3)
    if change == "universe":
        port.symbols += ("G",)
    port.callback = None
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert len(port.calls) == 1
    assert snapshot(database, job_id)["status"] == ("paused" if change in {"release", "universe"} else "error" if change == "backoff" else "success")
    if change == "runtime":
        assert snapshot(database, job_id)["result"]["status"] == "partial"


def test_eod_drain_waits_for_provider_and_commit(database, monkeypatch):
    entered, release = Event(), Event()
    def first(db, symbol):
        if len(port.calls) == 1:
            entered.set()
            assert release.wait(5)
    port = EodPort(first)
    wire_eod(monkeypatch, port)
    job_id = submit_eod(database)
    assert entered.wait(5)
    service.request_job_pause()
    try:
        assert service.observe_job_quiescence()["unfinished_future_count"] > 0
        with Session(database) as db:
            ledger = json.loads(db.get(JobRun, job_id).result_json)[LEDGER_KEY]
            assert ledger["inflight"]["item"] == "F" and ledger["totals"]["calls"] == 2
    finally:
        release.set()
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"


def wire_priority(monkeypatch, database, callback=None, *, symbols=("A", "B", "C", "D"), critical=("A",)):
    calls = []
    monkeypatch.setattr(priority, "SessionLocal", lambda: Session(database))
    monkeypatch.setattr(priority, "list_us_priority_ohlc_symbols", lambda _: symbols)
    monkeypatch.setattr(priority, "list_us_priority_ohlc_critical_symbols", lambda _: critical)
    monkeypatch.setattr(priority, "build_us_daily_operation_rollout_state", lambda **_: None)
    monkeypatch.setattr(priority, "expected_us_completed_daily_state", lambda **_: SimpleNamespace(expected_trade_date=DAY))
    class Platform:
        def __init__(self, db, **_):
            self.db = db
        def read(self, **_):
            self.db.execute(text("SELECT 1"))
            return _platform_result(satisfied=False)
        def ensure_history_coverage(self, symbol, max_provider_calls, **_):
            calls.append((symbol, max_provider_calls))
            if callback:
                callback(self.db, symbol)
            self.db.commit()
            return _platform_result(satisfied=True, attempts=1)
    monkeypatch.setattr(priority, "USDailyOhlcvPlatform", Platform)
    return calls


def submit_priority(database, *, max_symbols=3, cursor="B", calls=3):
    job_id = make_job(database)
    service.submit_job_task(backfill_tasks.run_us_priority_ohlc_reconcile_job, job_id,
        60, cursor, max_symbols, calls, 2, None, None, DAY.isoformat())
    return job_id


@pytest.mark.parametrize("critical", [("A",), ("A", "B", "C")])
def test_priority_preserves_critical_rotation_and_remaining_calls(database, monkeypatch, critical):
    def pause(db, symbol):
        if len(calls) == 1:
            service.request_job_pause()
    calls = wire_priority(monkeypatch, database, pause, critical=critical)
    job_id = submit_priority(database)
    wait_idle()
    state = saved_state(database, job_id)
    assert state["totals"]["calls"] == 1 and state["totals"]["checked"] == 1
    expected = ["A", "C", "D"] if len(critical) == 1 else ["C", "D", "A"]
    assert state["items"] == expected
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert [x for x, _ in calls] == expected
    assert calls[-1][1] == 1
    result = snapshot(database, job_id)["result"]
    assert result["checked_count"] == result["satisfied_count"] == result["repaired_count"] == 3
    assert result["external_call_count"] == 3 and result["unresolved_count"] == 1


def test_priority_unknown_provider_consumption_keeps_reservation(database, monkeypatch):
    def failed(db, symbol):
        service.request_job_pause()
        raise RuntimeError("one of two calls may have completed")
    calls = wire_priority(monkeypatch, database, failed)
    job_id = submit_priority(database)
    wait_idle()
    state = saved_state(database, job_id)
    assert state["totals"]["calls"] == 2
    assert state["results"][0]["outcome"]["usage_unknown"] is True
    service.resume_jobs(service._admission_pause)
    wait_idle()
    result = snapshot(database, job_id)["result"]
    assert len(calls) == 1
    assert result["status"] == "partial" and result["external_call_count"] is None
    assert result["external_call_budget_used"] == 2 and result["stopped_reason"] == "provider_usage_unknown"


@pytest.mark.parametrize("change", ["release", "universe", "critical"])
def test_priority_changed_context_retains_obligation(database, monkeypatch, change):
    calls = wire_priority(monkeypatch, database, lambda *a: service.request_job_pause())
    job_id = submit_priority(database)
    wait_idle()
    if change == "release":
        monkeypatch.setattr(priority, "expected_us_completed_daily_state", lambda **_: SimpleNamespace(expected_trade_date=DAY + timedelta(days=3)))
    elif change == "universe":
        monkeypatch.setattr(priority, "list_us_priority_ohlc_symbols", lambda _: ("A", "B", "C", "D", "E"))
    else:
        monkeypatch.setattr(priority, "list_us_priority_ohlc_critical_symbols", lambda _: ("A", "B"))
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert len(calls) == 1 and snapshot(database, job_id)["status"] == "paused"


def test_parent_resume_skips_admitted_child_and_does_not_claim_completion(database, monkeypatch):
    monkeypatch.setattr(bootstrap, "resolve_taiwan_tier_a_target_plan", lambda *a, **k: {"symbols": ["2330", "1101"]})
    admitted = []
    def enqueue(db, stock_id, **kwargs):
        admitted.append(stock_id)
        child = service.create_job(db, job_type="fixture-child", target=stock_id)
        if len(admitted) == 1:
            service.request_job_pause()
        return child, True
    monkeypatch.setattr(bootstrap, "enqueue_intraday_materialization_demand", enqueue)
    job_id = make_job(database)
    service.submit_job_task(bootstrap.run_taiwan_intraday_bar_bootstrap_job, job_id, ("2330", "1101"), 2)
    wait_idle()
    state = saved_state(database, job_id)
    assert len(state["results"]) == 1 and state["totals"]["admitted"] == 1
    service.resume_jobs(service._admission_pause)
    wait_idle()
    result = snapshot(database, job_id)
    assert admitted == ["2330", "1101"]
    assert result["status"] == "error" and result["result"]["postcondition_met"] is False
    assert result["result"]["admitted_count"] == 2 and result["result"]["children_completed_count"] == 0
    assert len(result["result"][LEDGER_KEY]["results"]) == 2


@pytest.mark.parametrize("mutation", ["calls", "completed", "inflight"])
def test_malformed_owner_ledger_rejected_before_claim(database, monkeypatch, mutation):
    wire_priority(monkeypatch, database, lambda *a: service.request_job_pause())
    job_id = submit_priority(database)
    wait_idle()
    state = saved_state(database, job_id)
    if mutation == "calls":
        state["totals"]["calls"] = 0
    elif mutation == "completed":
        state["results"][0]["item"] = "D"
    else:
        state["inflight"] = {"item": "C", "calls": 1}
    with pytest.raises(ValueError, match="JOB_OWNER"):
        validate_owner_state(state, safe=True)


@pytest.mark.parametrize("owner", ["eod", "priority"])
def test_new_python_process_resumes_only_remaining_work(database, monkeypatch, owner):
    import subprocess
    import sys
    from pathlib import Path
    if owner == "eod":
        port = EodPort(lambda *a: service.request_job_pause())
        wire_eod(monkeypatch, port)
        job_id = submit_eod(database)
    else:
        wire_priority(monkeypatch, database, lambda *a: service.request_job_pause())
        job_id = submit_priority(database)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    child = '''
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path('backend/tests').resolve()))
import g3_offline_guard
g3_offline_guard.install()
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_job_owner_ledgers import service, EodPort, wire_eod, wire_priority, wait_idle, JobRun
engine = create_engine(sys.argv[1])
service.SessionLocal = lambda: Session(engine)
service.settings.job_worker_max_concurrency = 1
patch = pytest.MonkeyPatch()
if sys.argv[2] == 'eod':
    port = EodPort()
    wire_eod(patch, port, order=('A','C','E'))
    calls = port.calls
else:
    calls = wire_priority(patch, engine)
with Session(engine) as db:
    assert service.recover_paused_jobs(db) == 1
wait_idle()
with Session(engine) as db:
    job = db.get(JobRun, int(sys.argv[3]))
    assert job.status == 'success', job.error_message
    result = json.loads(job.result_json)
    assert result['attempted_count' if sys.argv[2] == 'eod' else 'external_call_count'] == (4 if sys.argv[2] == 'eod' else 3)
service.shutdown_job_executor(wait=True)
print(json.dumps(calls))
engine.dispose()
'''
    result = subprocess.run([sys.executable, "-B", "-c", child, str(database.url), owner, str(job_id)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads(result.stdout.strip())
    assert [x for x, _ in calls] == (["D", "B", "A"] if owner == "eod" else ["C", "D"])
    assert calls[-1][1] == 1


def test_priority_pause_waits_for_real_chart_session_close(database, monkeypatch):
    closing, release = Event(), Event()
    calls = wire_priority(monkeypatch, database, lambda *a: service.request_job_pause())
    class ChartSession(Session):
        def close(self):
            if calls:
                closing.set()
                assert release.wait(5)
            super().close()
    monkeypatch.setattr(priority, "SessionLocal", lambda: ChartSession(database))
    job_id = submit_priority(database)
    assert closing.wait(5)
    try:
        assert snapshot(database, job_id)["status"] == "running"
        assert service.observe_job_quiescence()["unfinished_future_count"] == 1
    finally:
        release.set()
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"


def test_eod_commit_outcome_unknown_never_publishes_pause(database, monkeypatch):
    port = EodPort(lambda *a: service.request_job_pause(), partial=True)
    wire_eod(monkeypatch, port)
    original = eod._update_repair_state
    def uncertain(*args, **kwargs):
        original(*args, **kwargs)
        if kwargs.get("attempted_delta"):
            raise RuntimeError("commit acknowledgement lost")
    monkeypatch.setattr(eod, "_update_repair_state", uncertain)
    job_id = submit_eod(database)
    wait_idle()
    assert len(port.calls) == 1 and snapshot(database, job_id)["status"] == "running"
    assert service.observe_job_quiescence()["unresolved_enqueues"] > 0


def test_unstarted_child_handoff_preserves_episode_and_cas(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *a: {"reread_ready": False, "current_session_bar_count": 0})
    with env.factory() as db:
        job, _ = demand.enqueue_intraday_materialization_demand(db, stock_id="2330", requested_at=NOW, consumer="operator")
        job_id, request = job.id, job.request_json
        result = json.loads(job.result_json)
        result.update(attempt_count=1, external_call_budget_used=1, external_call_count=None,
            next_retry_at=(NOW + timedelta(seconds=15)).isoformat())
        job.result_json = json.dumps(result)
        db.commit()
    demand.requeue_unstarted_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert demand.is_restart_handoff(job) and job.request_json == request
        assert json.loads(job.result_json) == {**result, demand.RESTART_HANDOFF_KEY: True}
        assert service.mark_interrupted_jobs(db) == 0
        assert demand.dispatch_due_materializations(db, requested_at=NOW) == 0
        assert demand.dispatch_due_materializations(db, requested_at=NOW + timedelta(seconds=16)) == 1
    with env.factory() as db:
        assert demand.dispatch_due_materializations(db, requested_at=NOW + timedelta(seconds=16)) == 0
        job = db.get(JobRun, job_id)
        assert job.request_json == request and json.loads(job.result_json)["external_call_budget_used"] == 1


def test_jobservice_returns_unstarted_child_to_original_owner(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *a: {"reread_ready": False, "current_session_bar_count": 0})
    with env.factory() as db:
        job, _ = demand.enqueue_intraday_materialization_demand(db, stock_id="2330", requested_at=NOW, consumer="operator")
        job_id = job.id
        original = job.result_json
    entered, release = Event(), Event()
    def blocker(_):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    ACTUAL_SUBMIT(blocker, 999)
    assert entered.wait(5)
    ACTUAL_SUBMIT(demand.run_consumer_demand, job_id)
    service.request_job_pause()
    release.set()
    wait_idle()
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert demand.is_restart_handoff(job)
        result = json.loads(job.result_json)
        result.pop(demand.RESTART_HANDOFF_KEY)
        assert result == json.loads(original)
    assert service.observe_job_quiescence()["unresolved_enqueues"] == 0


def test_started_child_deadline_is_not_thread_or_session_completion(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *a: {"reread_ready": False, "current_session_bar_count": 0})
    with env.factory() as db:
        job, _ = demand.enqueue_intraday_materialization_demand(db, stock_id="2330", requested_at=NOW, consumer="operator")
        job_id = job.id
    entered, release, closing, close_release = Event(), Event(), Event(), Event()
    bounds = []
    def acquire(db, **kwargs):
        bounds.append(kwargs["acquisition_bounds"])
        entered.set()
        assert release.wait(5)
        raise TimeoutError("fixture acquisition deadline")
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars", acquire)
    class DemandSession(Session):
        def close(self):
            closing.set()
            assert close_release.wait(5)
            super().close()
    monkeypatch.setattr(service, "SessionLocal", lambda: DemandSession(env.factory.kw["bind"]))
    ACTUAL_SUBMIT(demand.run_consumer_demand, job_id)
    assert entered.wait(5)
    try:
        service.request_job_pause()
        assert bounds[0].timeout_seconds == 40
        assert service.observe_job_quiescence()["unfinished_future_count"] == 1
        with env.factory() as db:
            result = json.loads(db.get(JobRun, job_id).result_json)
            assert result["external_call_budget_used"] == 2 and result["attempt_count"] == 1
        release.set()
        assert closing.wait(5)
        assert service.observe_job_quiescence()["unfinished_future_count"] == 1
    finally:
        release.set()
        close_release.set()
    wait_idle()
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == "error" and result["external_call_count"] is None
        assert result["external_call_budget_used"] == 2


@pytest.mark.parametrize("offset", [0, 4])
def test_eod_fifth_background_slot_and_cursor_rotation_survive_pause(database, monkeypatch, offset):
    port = EodPort(lambda *a: service.request_job_pause(), partial=True)
    wire_eod(monkeypatch, port)
    with Session(database) as db:
        row = eod.persist_eod_coverage(db, port.compute_coverage(db, expected_trade_date=DAY))
        row.cursor_symbol = "B"
        row.attempted_count = offset
        db.commit()
    job_id = submit_eod(database, symbols=6)
    wait_idle()
    expected = ["F", "D", "B", "C", "E", "A"] if offset == 0 else ["C", "F", "D", "B", "E", "A"]
    assert saved_state(database, job_id)["items"] == expected
    port.callback = None
    wire_eod(monkeypatch, port, order=("A",))
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert [s for s, _ in port.calls] == expected
    with Session(database) as db:
        row = db.query(MarketDatasetCoverageCheckpoint).one()
        assert row.attempted_count == offset + 6 and row.cursor_symbol == expected[-1]


def test_eod_rate_limit_keeps_original_retry_after_resume(database, monkeypatch):
    from app.observability.provider_http import ProviderHttpError, ProviderHttpFailure, ProviderRequestContext
    def limited(db, symbol):
        service.request_job_pause()
        failure = ProviderHttpFailure(context=ProviderRequestContext(market="us", provider="yahoo_chart",
            resource="daily_price", target=symbol), status="rate_limited", source_url="https://fixture.invalid",
            http_status_code=429, rate_limited=True, retry_after_seconds=120, error_message="HTTP 429")
        raise ProviderHttpError("HTTP 429", failure=failure)
    port = EodPort(limited)
    wire_eod(monkeypatch, port)
    job_id = submit_eod(database)
    wait_idle()
    state = saved_state(database, job_id)
    assert state["totals"]["calls"] == 2
    retry = state["context"]["next_retry_at"]
    assert datetime.fromisoformat(retry) > datetime.now(timezone.utc)
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert len(port.calls) == 1
    result = snapshot(database, job_id)["result"]
    assert result["checkpoint"]["repair_status"] == "rate_limited"
    assert result["external_call_count"] is None and result["external_call_budget_used"] == 2
    assert datetime.fromisoformat(result["checkpoint"]["next_retry_at"]).replace(tzinfo=None) == datetime.fromisoformat(retry).replace(tzinfo=None)


def test_child_submit_fence_handoff_and_expiry_do_not_reset_budget(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *a: {"reread_ready": False, "current_session_bar_count": 0})
    def fenced(*a, **k):
        raise service.JobAdmissionClosed("fixture pause")
    monkeypatch.setattr(service, "submit_job_task", fenced)
    with env.factory() as db:
        job, _ = demand.enqueue_intraday_materialization_demand(db, stock_id="2330", requested_at=NOW, consumer="operator")
        assert demand.is_restart_handoff(job)
        job_id = job.id
        original_request = job.request_json
        assert demand.dispatch_due_materializations(db, requested_at=NOW + timedelta(seconds=181)) == 0
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == "error" and job.request_json == original_request
        assert json.loads(job.result_json)["external_call_budget_used"] == 0


@pytest.mark.parametrize("fault", ["close", "persistence"])
def test_priority_unknown_scope_outcome_retains_inflight_and_blocks_drain(database, monkeypatch, fault):
    from sqlalchemy.exc import OperationalError
    def fail(db, symbol):
        service.request_job_pause()
        if fault == "persistence":
            raise OperationalError("fixture commit", None, RuntimeError("unknown"))
    calls = wire_priority(monkeypatch, database, fail)
    if fault == "close":
        class BrokenClose(Session):
            def close(self):
                super().close()
                if calls:
                    raise RuntimeError("close acknowledgement unknown")
        monkeypatch.setattr(priority, "SessionLocal", lambda: BrokenClose(database))
    job_id = submit_priority(database)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "running"
    assert service.observe_job_quiescence()["unresolved_enqueues"] > 0
    with Session(database) as db:
        state = json.loads(db.get(JobRun, job_id).result_json)[LEDGER_KEY]
        assert state["inflight"]["calls"] == 2 and not state["results"]


@pytest.mark.parametrize("failure", ["db", "rollback"])
def test_eod_market_port_persistence_unknown_escapes_provider_handler(monkeypatch, failure):
    from app.us_market import full_market_eod
    from app.utils.owner_checkpoint import OwnerOutcomeUnknown
    from sqlalchemy.exc import OperationalError
    def refresh(**kwargs):
        raise OperationalError("fixture commit", None, RuntimeError("unknown"))
    class FakeSession:
        def rollback(self):
            if failure == "rollback":
                raise RuntimeError("rollback outcome unknown")
    monkeypatch.setattr(full_market_eod, "USDailyOhlcvPlatform", lambda db: SimpleNamespace(refresh=refresh))
    with pytest.raises(OwnerOutcomeUnknown, match="US_EOD_PROVIDER_.*UNKNOWN"):
        full_market_eod.US_FULL_MARKET_EOD_LIFECYCLE.refresh_symbol(FakeSession(),
            symbol="A", expected_trade_date=DAY, max_external_calls=1)
