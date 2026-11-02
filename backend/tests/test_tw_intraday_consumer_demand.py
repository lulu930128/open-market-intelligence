from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, create_mock_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, JobRun, StockMaster
from app.jobs import taiwan_intraday_demand as subject
from app.market.trading_calendar import TAIWAN_TZ


NOW = datetime(2026, 9, 16, 10, 0, tzinfo=TAIWAN_TZ)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'demand.db'}", connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([StockMaster(stock_id=code, stock_name=code, market="TWSE", instrument_type="stock", is_active=True)
                    for code in ("2330", "2317")])
        db.commit()
    dispatches = []
    clock = [NOW]
    monkeypatch.setattr(subject.jobs, "SessionLocal", factory)
    monkeypatch.setattr(subject.jobs, "submit_job_task", lambda task, job_id, **kw: dispatches.append(job_id))
    monkeypatch.setattr(subject, "_now", lambda: clock[0])
    yield SimpleNamespace(engine=engine, factory=factory, dispatches=dispatches, clock=clock)
    engine.dispose()


def enqueue(db, **kwargs):
    return subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="viewer", **kwargs)


def reread_stub(monkeypatch, *, ready=False, count=0, trade_date=None):
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        day = trade_date or NOW.date()
        bucket = SimpleNamespace(expected_by_trading_policy=True, bucket_start=NOW - timedelta(minutes=1),
            bucket_end=NOW, status=SimpleNamespace(value="observed_trade" if ready else "missing_evidence"))
        return SimpleNamespace(history=SimpleNamespace(requested_coverage_satisfied=ready),
            bucket_coverage=(bucket,), session_resolution=(SimpleNamespace(trade_date=day,
                market_semantics_usable=True, conflict_bucket_count=0),), current_session_coverage=SimpleNamespace(
            trade_date=trade_date or NOW.date(), snapshot_bar_count=count,
            expected_to=NOW,
            snapshot_phase=SimpleNamespace(value="ready" if ready else "warming"), snapshot_revision="a" * 64,
        ))
    monkeypatch.setattr(subject, "TaiwanBarService", lambda db: SimpleNamespace(read_current_session_bars=read))
    return calls


def test_two_connections_race_share_one_job_and_dispatch(env, monkeypatch):
    barrier = Barrier(2)
    original = subject.jobs.create_job_record
    def create(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(subject.jobs, "create_job_record", create)
    def call(consumer):
        with env.factory() as db:
            job, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer=consumer)
            return job.id, created
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(call, ("viewer", "ai")))
    assert results[0][0] == results[1][0]
    assert sum(created for _, created in results) == 1
    assert env.dispatches == [results[0][0]]
    with env.factory() as db:
        assert db.query(JobRun).count() == 1


def test_fail_closed_without_exact_unique_index(env):
    with env.factory() as db:
        db.execute(text(f"DROP INDEX {subject.INDEX_NAME}"))
        db.commit()
        with pytest.raises(RuntimeError, match="SCHEMA_NOT_READY"):
            enqueue(db)
        assert db.query(JobRun).count() == 0
    assert not env.dispatches


@pytest.mark.parametrize("code", ["", "9999", "2330,2317", "TW", "0050"])
def test_invalid_or_nonordinary_symbol_never_enqueues(env, code):
    with env.factory() as db, pytest.raises(ValueError, match="ordinary stock"):
        subject.enqueue_consumer_demand(db, stock_id=code, requested_at=NOW, consumer="ai")
    assert not env.dispatches


def test_premarket_current_date_skips_but_completed_date_can_repair(env):
    with env.factory() as db:
        assert subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW.replace(hour=8), consumer="ai") == (None, False)
        job, created = enqueue(db, trade_date="2026-09-15")
        assert created and subject.materialization_request(job)["mode"] == "completed_session_repair"
        with pytest.raises(ValueError, match="INVALID_TRADE_DATE"):
            enqueue(db, trade_date="2026-09-17")
    assert len(env.dispatches) == 1


@pytest.mark.parametrize("qualified", [True, False])
def test_completed_date_uses_dated_owner_and_keeps_sparse_unknown_minutes(env, monkeypatch, qualified):
    target = NOW.date()
    after_close = NOW.replace(hour=16)
    calls = []
    def dated(**kwargs):
        calls.append(kwargs)
        assert kwargs["from_time"].date() == kwargs["to_time"].date() == target
        assert kwargs["requested_at"] == after_close and kwargs["interval"] == "1m"
        return SimpleNamespace(bars=tuple(SimpleNamespace(start_at=NOW) for _ in range(214)),
            bucket_coverage=tuple(SimpleNamespace(expected_by_trading_policy=True,
                bucket_start=NOW, bucket_end=NOW + timedelta(minutes=1), status=SimpleNamespace(value=
                    "observed_trade" if i < 214 else "verified_no_trade" if qualified else "missing_evidence")) for i in range(265)),
            session_resolution=(SimpleNamespace(trade_date=target, market_semantics_usable=True,
                coverage_status=SimpleNamespace(value="ready" if qualified else "partial")),),
            identity=SimpleNamespace(series_revision="dated-canonical"))
    monkeypatch.setattr(subject, "taiwan_presentation_session", lambda now: {"trade_date": target})
    monkeypatch.setattr(subject, "TaiwanBarService", lambda db: SimpleNamespace(read_bars=dated,
        read_current_session_bars=lambda **kw: pytest.fail("completed repair used current baseline")))
    with env.factory() as db:
        result = subject._reread(db, {"stock_id": "2330", "trade_date": str(target),
            "mode": "completed_session_repair"}, after_close)
    assert result["reread_ready"] is qualified
    assert result["current_session_bar_count"] == 214  # No synthetic 51 bars.
    assert result["target_expected_bucket_count"] == 265
    assert result["target_covered_bucket_count"] == (265 if qualified else 214)
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["stable", "progress", "provider_failure", "backoff"])
def test_completed_successful_acquisition_without_progress_waits_for_original_repair(env, monkeypatch, outcome):
    now = NOW.replace(hour=16)
    env.clock[0] = now
    reads = []
    def reread(*args):
        reads.append(1)
        changed = outcome == "progress" and len(reads) >= 3
        return dict(reread_ready=False, reread_trade_date=str(now.date()),
            current_session_bar_count=215 if changed else 214,
            target_covered_bucket_count=215 if changed else 214, target_expected_bucket_count=265,
            snapshot_revision="changed-canonical" if changed else "unchanged-canonical")
    monkeypatch.setattr(subject, "_reread", reread)
    calls = []
    def acquire(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(acquisition=SimpleNamespace(status="failed" if outcome == "provider_failure" else "completed",
            external_calls=2, limitations=("PROVIDER_RETRY_AFTER_SECONDS:600",) if outcome == "backoff" else ()),
            persistence=SimpleNamespace(attempted=True, committed=True, observations_written=0))
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", acquire)
    with env.factory() as db:
        job, _ = subject.enqueue_intraday_materialization_demand(db, stock_id="2330", requested_at=now,
            consumer="completed_session_repair", trade_date=str(now.date()), max_external_calls=6)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == ("error" if outcome in {"stable", "backoff"} else "queued")
        result = json.loads(job.result_json)
        if outcome == "stable":
            assert result["reason_code"] == "COMPLETED_SESSION_COVERAGE_INCOMPLETE"
            assert result["completed_no_progress"]
        else:
            assert not result.get("completed_no_progress")
        assert result["attempt_count"] == 1
        assert result["external_call_budget_used"] == 2
        same, created = subject.enqueue_intraday_materialization_demand(db, stock_id="2330",
            requested_at=now + timedelta(seconds=30), consumer="completed_session_repair",
            trade_date=str(now.date()), max_external_calls=6)
        assert same.id == job_id and not created
    assert len(calls) == 1


def test_same_job_three_heartbeat_attempts_and_cooldown(env, monkeypatch):
    reads = reread_stub(monkeypatch)
    acquired = []
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", lambda *args, **kw: acquired.append(kw) or SimpleNamespace(persistence=SimpleNamespace(attempted=True, committed=True)))
    with env.factory() as db:
        job, created = enqueue(db)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    for delay, attempt in ((15, 2), (30, 3)):
        with env.factory() as db:
            job = db.get(JobRun, job_id)
            assert job.status == "queued"
            progress = json.loads(job.result_json)
            due = datetime.fromisoformat(progress["next_retry_at"])
            same, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=due - timedelta(seconds=1), consumer="viewer")
            assert same.id == job_id and not created
            assert len(env.dispatches) == attempt - 1
            env.clock[0] = due
            same, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=due, consumer="viewer")
            assert same.id == job_id and not created
        subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == "error"
        assert json.loads(job.result_json)["attempt_count"] == 3
        assert json.loads(job.result_json)["external_call_budget_used"] == 6
        assert json.loads(job.result_json)["external_call_count"] is None
        same, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=env.clock[0] + timedelta(seconds=1), consumer="viewer")
        assert same.id == job_id and not created
        assert db.query(JobRun).count() == 1
    assert len(acquired) == len(env.dispatches) == 3
    assert len(reads) == 12  # admission, each worker pre/post read, and heartbeat revalidation
    assert all(call["bypass_snapshot_cache"] for call in reads)


@pytest.mark.parametrize("same_date", [True, False])
def test_only_ready_same_session_reread_completes(env, monkeypatch, same_date):
    reread_stub(monkeypatch, ready=True, count=50, trade_date=NOW.date() if same_date else NOW.date() - timedelta(days=1))
    calls = []
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", lambda *a, **kw: calls.append(kw) or SimpleNamespace(persistence=SimpleNamespace(attempted=True, committed=True)))
    with env.factory() as db:
        job, _ = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai", timeout_seconds=9, max_external_calls=1)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == ("success" if same_date else "error")
        assert json.loads(job.result_json)["current_session_bar_count"] == (50 if same_date else 0)
    assert len(calls) == (0 if same_date else 1)
    if calls:
        assert calls[0]["acquisition_bounds"].timeout_seconds <= 9
        assert calls[0]["acquisition_bounds"].max_external_calls == 1


def test_mcp_expired_queue_never_acquires(env, monkeypatch):
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", lambda *a, **k: pytest.fail("expired caller cannot fetch"))
    with env.factory() as db:
        job, _ = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai", timeout_seconds=5)
        job_id = job.id
    env.clock[0] = NOW + timedelta(seconds=6)
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        assert db.get(JobRun, job_id).status == "error"


@pytest.mark.parametrize("failure, error_type, subphase", [
    (RuntimeError("MARKET_MATERIALIZATION_QUEUE_FULL"), "RuntimeError", "queue_full"),
    (RuntimeError("private failure C:/private/token=SECRET"), "RuntimeError", "submit"),
    (ValueError("private invalid lane"), "ValueError", "submit"),
    (OSError("private OS failure"), "Exception", "submit"),
    (RuntimeError("MARKET_MATERIALIZATION_QUEUE_FULL token=SECRET"), "RuntimeError", "submit"),
])
def test_submit_failure_is_terminal_not_orphaned(env, monkeypatch, caplog, failure, error_type, subphase):
    from app.ai.refresh_status import read_refresh_status
    from app.ai.schemas import AiRefreshStatusRead
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(subject.jobs, "submit_job_task", fail)
    # Existing canonical data makes public status partial even on a dispatch
    # fault. That must not hide the execution failure or imply provider IO.
    reread_stub(monkeypatch, count=12)
    diagnostic = {"reason_code": "TW_INTRADAY_DEMAND_SUBMIT_FAILED", "stage": "dispatch",
        "subphase": subphase, "error_type": error_type, "attempt_count": 0}
    with env.factory() as db:
        job, _ = enqueue(db)
        assert job.status == "error"
        assert job.error_message == "TW_INTRADAY_DEMAND_SUBMIT_FAILED"
        result = json.loads(job.result_json)
        assert result["status"] == "partial" and result["reread_ready"] is False
        assert result["last_failure"] == diagnostic
        assert result["attempt_count"] == result["external_call_count"] == result["external_call_budget_used"] == 0
        assert result["provider_failure_count"] == result["bars_written_count"] == 0
        db.execute(text("PRAGMA query_only=ON"))
        public = read_refresh_status(db=db, job_id=job.id)
        AiRefreshStatusRead.model_validate(public)
        assert public["status"] == "partial"
        assert public["error"]["code"] == "TW_INTRADAY_DEMAND_SUBMIT_FAILED"
        assert public["error"]["diagnostic"] == public["materialization"]["last_failure"] == diagnostic
        assert str(job.id) in caplog.text
        serialized = json.dumps(public, default=str) + job.result_json + caplog.text
        assert all(secret not in serialized for secret in ("SECRET", "C:/private", "private invalid", "private OS"))


def test_submit_admission_closed_returns_unstarted_claim_without_consuming_budget(env, monkeypatch):
    def closed(*args, **kwargs):
        raise subject.jobs.JobAdmissionClosed("private owner fence")
    monkeypatch.setattr(subject.jobs, "submit_job_task", closed)
    with env.factory() as db:
        job, _ = enqueue(db)
        result = json.loads(job.result_json)
        assert job.status == "queued" and subject.is_restart_handoff(job)
        assert result["external_call_count"] == result["external_call_budget_used"] == result["attempt_count"] == 0
        assert "last_failure" not in result and "reason_code" not in result
        assert subject.materialization_request(job)["max_external_calls"] == 6


def test_dispatch_diagnostic_projection_drops_unallowlisted_fields():
    value = {"reason_code": "TW_INTRADAY_DEMAND_SUBMIT_FAILED", "stage": "dispatch",
        "error_type": "private exception", "subphase": "private stage", "attempt_count": True,
        "message": "SECRET", "path": "C:/private"}
    assert subject.safe_demand_failure(value) == {"reason_code": value["reason_code"],
        "stage": "dispatch", "error_type": None, "subphase": None, "attempt_count": None}


def test_migration_upgrade_downgrade_preserve_legacy_rows(env):
    path = Path(__file__).parents[1] / "alembic/versions/20260920_0088_tw_intraday_active_demand.py"
    spec = importlib.util.spec_from_file_location("demand_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with env.factory() as db:
        for _ in range(2):
            db.add(JobRun(job_type=subject.JOB_TYPE, target="tw_intraday:legacy", status="queued"))
            db.add(JobRun(job_type="ai.tool_refresh", target="2330", status="running"))
        db.commit()
    with env.engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        # Fresh baseline metadata already has the index; upgrade remains safe.
        migration.upgrade()
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
        assert conn.execute(text("SELECT count(*) FROM job_run")).scalar() == 4
        migration.downgrade()
        assert conn.execute(text("SELECT count(*) FROM job_run")).scalar() == 4


def test_non_sqlite_metadata_does_not_constrain_all_legacy_jobs():
    statements = []
    engine = create_mock_engine(
        "postgresql://", lambda statement, *args, **kwargs: statements.append(str(statement)),
    )
    JobRun.__table__.create(engine)
    assert not any(subject.INDEX_NAME in statement for statement in statements)


def test_canonical_ai_dispatch_respects_budget_without_outer_job(env, monkeypatch):
    from app.ai import agentic_execution
    monkeypatch.setattr(agentic_execution.agentic_common, "_now", lambda: NOW)
    monkeypatch.setattr(agentic_execution, "request_market_refresh_priority", lambda *a, **k: pytest.fail("intraday must not enqueue an unrelated EOD job"))
    monkeypatch.setattr(agentic_execution, "_execute_tool_with_deadline", lambda **k: pytest.fail("canonical demand must not enter the generic detached worker"))
    plan = {"tool_plan": [{"tool": "tw.refresh_intraday_bars", "args": {"stock_id": "2330"}}]}
    with env.factory() as db:
        runs, _ = agentic_execution.execute_tool_plan(db=db, plan=plan, budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 7}, can_external_fetch=True)
        assert runs[0]["operation_status"] == "pending"
        job = db.get(JobRun, runs[0]["job"]["job_id"])
        request = subject.consumer_request(job)
        assert request["max_external_calls"] == 1
        assert request["max_attempts"] == 1
        assert 0 < (datetime.fromisoformat(request["expires_at"]) - NOW).total_seconds() <= 7
        assert job.job_type == subject.JOB_TYPE
        assert db.query(JobRun).count() == 1
        assert runs[0]["job"]["poll_url"].startswith("/api/ai/refresh-status/")


def test_denied_external_fetch_does_not_enqueue(env):
    from app.ai import agentic_execution
    with env.factory() as db:
        runs, _ = agentic_execution.execute_tool_plan(db=db, plan={"tool_plan": [{"tool": "tw.refresh_intraday_bars", "args": {"stock_id": "2330"}}]}, budget={"max_calls": 1, "max_external_fetches": 2, "max_total_seconds": 10}, can_external_fetch=False)
        assert runs[0]["status"] == "blocked"
        assert db.query(JobRun).count() == 0


def test_status_redacts_and_pins_cache_only_resume(env, monkeypatch):
    from app.ai import ask_execution, refresh_status
    from app.ai.schemas import AiAskRequest, AiRefreshStatusRead
    calls = reread_stub(monkeypatch, ready=True, count=30)
    with env.factory() as db:
        job, _ = enqueue(db)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        request = json.loads(job.request_json)
        request.update(api_key="SECRET", provider_set=["PRIVATE"])
        job.request_json = json.dumps(request)
        job.error_message = "INTERNAL"
        db.commit()
        # A status read may not perform any database write, even to terminalize.
        db.execute(text("PRAGMA query_only=ON"))
        result = refresh_status.read_refresh_status(db=db, job_id=job_id)
        AiRefreshStatusRead.model_validate(result)
        assert result["target"] == {"type": "tw_stock", "id": "2330"}
        assert result["operation"] == "tw.refresh_intraday_bars"
        assert result["result_summary"]["current_session_bar_count"] == 30
        assert result["date_range"] == {"from": "2026-09-16", "to": "2026-09-16"}
        serialized = json.dumps(result, default=str)
        assert all(secret not in serialized for secret in ("SECRET", "PRIVATE", "INTERNAL", "tw-demand:"))
        resume = result["resume"]["arguments"]
        assert resume["realtime_policy"] == "cache_only"
        assert resume["allow_external_fetch"] is False
        params = ask_execution._tw_market_data_params(AiAskRequest.model_validate(resume))
        assert params["trade_date"] == "2026-09-16"
        assert params["include_intraday"] is True
    assert len(calls) == 1


@pytest.mark.parametrize("corruption", ["target", "symbols", "version"])
def test_status_rejects_nonconsumer_or_malformed_bootstrap(env, corruption):
    from app.ai import refresh_status
    with env.factory() as db:
        job, _ = enqueue(db)
        if corruption == "target":
            job.target = "tw_intraday:legacy-private"
        else:
            request = json.loads(job.request_json)
            request["symbols" if corruption == "symbols" else "contract_version"] = ["2330", "2317"]
            job.request_json = json.dumps(request)
        db.commit()
        with pytest.raises(refresh_status.AiRefreshJobNotFoundError):
            refresh_status.read_refresh_status(db=db, job_id=job.id)


def test_final_reread_is_mandatory_after_provider_and_persistence(env, monkeypatch):
    state = {"materialized": False, "reads": 0}
    def read(**kwargs):
        state["reads"] += 1
        return SimpleNamespace(history=SimpleNamespace(requested_coverage_satisfied=state["materialized"]),
            bucket_coverage=(SimpleNamespace(expected_by_trading_policy=True, bucket_start=NOW-timedelta(minutes=1),
                bucket_end=NOW,status=SimpleNamespace(value="observed_trade" if state["materialized"] else "missing_evidence")),),
            session_resolution=(SimpleNamespace(trade_date=NOW.date(),market_semantics_usable=True,conflict_bucket_count=0),),
            current_session_coverage=SimpleNamespace(expected_to=NOW,
            trade_date=NOW.date(), snapshot_bar_count=20 if state["materialized"] else 0,
            snapshot_phase=SimpleNamespace(value="ready" if state["materialized"] else "warming"), snapshot_revision="a" * 64,
        ))
    def refresh(*a, **kw):
        state["materialized"] = True
        return SimpleNamespace(persistence=SimpleNamespace(attempted=True, committed=True))
    monkeypatch.setattr(subject, "TaiwanBarService", lambda db: SimpleNamespace(read_current_session_bars=read))
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", refresh)
    with env.factory() as db:
        job, _ = enqueue(db)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == "success"
        assert json.loads(job.result_json)["attempt_count"] == 1
    assert state["reads"] == 3


@pytest.mark.parametrize("failure", ["timeout", "reject"])
def test_acquisition_failure_never_claims_completion(env, monkeypatch, failure):
    reread_stub(monkeypatch)
    def refresh(*a, **k):
        if failure == "timeout":
            raise TimeoutError("provider private error")
        return SimpleNamespace(persistence=SimpleNamespace(attempted=True, committed=False))
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", refresh)
    with env.factory() as db:
        job, _ = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai")
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == "error"
        result = json.loads(job.result_json)
        assert result["reread_ready"] is False
        assert result["next_retry_at"] is None
        assert "private" not in (job.error_message or "")


def test_demands_do_not_collide_across_stock_or_trade_date(env):
    with env.factory() as db:
        first, _ = enqueue(db)
        second, _ = subject.enqueue_consumer_demand(db, stock_id="2317", requested_at=NOW, consumer="viewer")
        next_day, _ = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW + timedelta(days=1), consumer="viewer")
        assert len({first.id, second.id, next_day.id}) == 3


def test_heartbeat_only_dispatches_due_retry_for_existing_valid_lease(env, monkeypatch):
    from app.market import tw_realtime_lease_platform as leases
    from app.market.schemas import TaiwanRealtimeQuoteLeaseRead
    from app.market_data.research_lease import ViewerLeaseState
    state = ViewerLeaseState(lease_id="active", stock_id="2330", provider="fixture", owner_kind="frontend_viewer", status="live", fallback_source="cache", message="fixture")
    coordinator = SimpleNamespace(heartbeat=lambda key: state if key == "active" else None)
    calls = []
    def warmup(*args):
        calls.append(args)
        return SimpleNamespace(id=42), False
    with env.factory() as db:
        returned = leases.heartbeat_taiwan_realtime_quote_lease(db, "active", coordinator=coordinator, requested_at=NOW, baseline_warmup_enqueuer=warmup)
        assert TaiwanRealtimeQuoteLeaseRead.model_validate(returned.model_dump()).materialization_job_id == 42
        assert leases.heartbeat_taiwan_realtime_quote_lease(db, "released", coordinator=coordinator, requested_at=NOW, baseline_warmup_enqueuer=warmup) is None
    assert len(calls) == 1


def test_two_connections_cannot_dispatch_same_retry(env, monkeypatch):
    reread_stub(monkeypatch)
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", lambda *a, **k: SimpleNamespace(persistence=SimpleNamespace(attempted=True, committed=True)))
    with env.factory() as db:
        job, _ = enqueue(db)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    original = subject._dispatch
    barrier = Barrier(2)
    def dispatch(*a):
        barrier.wait(timeout=10)
        return original(*a)
    monkeypatch.setattr(subject, "_dispatch", dispatch)
    def heartbeat(_):
        with env.factory() as db:
            job, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW + timedelta(seconds=15), consumer="viewer")
            assert job.id == job_id and not created
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(heartbeat, range(2)))
    assert env.dispatches == [job_id, job_id]


def test_fast_terminal_race_revalidates_evidence(env, monkeypatch):
    reread_stub(monkeypatch, ready=True, count=50)
    original = subject.jobs.create_job_record
    def create(db, job_type, **kwargs):
        with env.factory() as other:
            winner = original(other, job_type, **kwargs)
            winner.status = "success"
            winner.result_json = json.dumps({"status": "success"})
            other.commit()
        return original(db, job_type, **kwargs)
    monkeypatch.setattr(subject.jobs, "create_job_record", create)
    with env.factory() as db:
        job, created = enqueue(db)
        assert not created and job.status == "success"
        assert db.query(JobRun).count() == 1
    assert not env.dispatches


def test_provider_backoff_outlives_episode_without_unbounded_retry(env, monkeypatch):
    reread_stub(monkeypatch)
    monkeypatch.setattr(subject, "refresh_taiwan_intraday_bars", lambda *a, **k: SimpleNamespace(
        acquisition=SimpleNamespace(external_calls=1, limitations=("PROVIDER_RETRY_AFTER_SECONDS:600",)),
        persistence=SimpleNamespace(attempted=True, committed=True, observations_written=0),
    ))
    with env.factory() as db:
        job, _ = enqueue(db)
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        assert job.status == "error"
        result = json.loads(job.result_json)
        assert result["reason_code"] == "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF"
        assert result["external_call_count"] == 1
        assert result["external_call_budget_used"] == 2
        same, created = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW + timedelta(seconds=181), consumer="viewer")
        assert same.id == job_id and not created
    assert len(env.dispatches) == 1


def test_late_provider_callback_is_rejected_before_persistence(monkeypatch):
    from app.market import tw_intraday_acquisition as acquisition
    from app.market.tw_intraday_capabilities import NSTOCK_INTRADAY_DESCRIPTOR
    from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
    from app.market_data.contracts import InstrumentKey, InstrumentType, Market
    from app.market_data.policies import RealtimePolicy
    from app.market_data.provider_catalog import plan_data_acquisition_v2
    requirement = build_taiwan_intraday_requirement(
        instrument=InstrumentKey(market=Market.TW, symbol="2330", instrument_type=InstrumentType.STOCK, venue="TWSE"),
        interval="1m", range_value="1d", policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW, acquiring=True,
    )
    plan = plan_data_acquisition_v2(requirement, (NSTOCK_INTRADAY_DESCRIPTOR,))
    ticks = iter((10, 14))
    monkeypatch.setattr(acquisition, "monotonic", lambda: next(ticks))
    routes = []
    def read(req, route):
        routes.append(route)
        return object()
    executor = acquisition.TaiwanIntradayAcquisitionExecutor(nstock=SimpleNamespace(acquire_route=read), clock=lambda: NOW, deadline_monotonic=13)
    with pytest.raises(TimeoutError, match="DEADLINE"):
        executor.acquire_bar_observations(requirement, plan)
    assert routes[0].timeout_seconds == 3


def test_exact_date_continuation_uses_canonical_history_window():
    from app.ai.market_context import taiwan_stock
    captured = []
    def reader(**kwargs):
        captured.append(kwargs)
        raise RuntimeError("empty offline fixture")
    # Exercise the same cache-only facade the status resume selects after rollover.
    taiwan_stock._compact_intraday_bars(
        dependencies=SimpleNamespace(read_taiwan_bars=reader), db=object(), stock_id="2330", include_intraday=True,
        market_data_params={"trade_date": "2026-09-15", "include_intraday": True, "intraday_interval": "1m"},
        calendar_status={"checked_at": NOW.isoformat()},
    )
    assert len(captured) == 1
    assert captured[0]["session_scope"] == "history"
    assert captured[0]["from_time"].date().isoformat() == "2026-09-15"
    assert captured[0]["to_time"].date().isoformat() == "2026-09-15"


def test_real_canonical_persistence_and_reread_keep_partial_truth(env, monkeypatch):
    from app.db.models import MarketIntradayBar, MarketIntradayBarLineage
    from app.market.providers.tw_intraday_bars import IntradayProviderPayload, NStockIntradayAdapter, YahooIntradayAdapter
    from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
    Base.metadata.create_all(env.engine)
    points = [{"交易日": "20260916", "交易時間": clock, "開盤價": "100", "最高價": "101", "最低價": "99", "收盤價": "100", "成交量": "1"}
              for clock in ("095800", "095900")]
    nstock = NStockIntradayAdapter(lambda *a: IntradayProviderPayload(
        raw_text=json.dumps({"data": [{"參考價": "100", "總成交量": "2", "分K": points}]}),
        status="available", url="https://fixture.invalid/nstock", status_code=200,
    ), clock=lambda: NOW)
    yahoo = YahooIntradayAdapter(lambda *a: IntradayProviderPayload(
        raw_text=None, status="failed", url="https://fixture.invalid/yahoo", status_code=429, retry_after_seconds=600,
    ), clock=lambda: NOW)
    monkeypatch.setattr(subject, "TaiwanIntradayAcquisitionExecutor", lambda **kw: TaiwanIntradayAcquisitionExecutor(nstock=nstock, yahoo=yahoo, **kw))
    with env.factory() as db:
        job, _ = subject.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai")
        job_id = job.id
    subject.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert db.query(MarketIntradayBar).count() == 2
        assert db.query(MarketIntradayBarLineage).count() == 2
        assert result["current_session_bar_count"] == 2
        assert result["reread_count"] == 3
        assert result["bars_written_count"] == 2
        assert result["external_call_count"] in {1, 2}
        assert result["snapshot_revision"]
        # Two rows satisfy materialization, but cannot claim a complete prefix.
        assert result["reread_ready"] is False
        assert result["status"] == "partial"
        assert result["snapshot_revision"] == subject._reread(db, subject.consumer_request(job), NOW)["snapshot_revision"]


@pytest.mark.parametrize("stock_id", ["2409", "3481"])
@pytest.mark.parametrize("complete", [True, False])
def test_explicit_non_tier_a_demand_converges_only_with_real_provider_minutes(env, monkeypatch, stock_id, complete):
    from app.db.models import MarketIntradayBar, MarketIntradayBarLineage
    from app.market.providers.tw_intraday_bars import IntradayProviderPayload, NStockIntradayAdapter
    from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
    calls = []
    opening = NOW.replace(hour=9)
    points = [{"交易日": NOW.strftime("%Y%m%d"), "交易時間": (opening + timedelta(minutes=i)).strftime("%H%M%S"),
        "開盤價": "100", "最高價": "101", "最低價": "99", "收盤價": "100", "成交量": "1"}
        for i in range(0 if complete else 1, 60)]
    def reader(symbol, timeout):
        calls.append(symbol)
        return IntradayProviderPayload(raw_text=json.dumps({"data": [{"股票代號": symbol, "分K": points}]}),
            status="available", url="https://fixture.invalid/nstock", status_code=200)
    nstock = NStockIntradayAdapter(reader, clock=lambda: NOW)
    monkeypatch.setattr(subject, "TaiwanIntradayAcquisitionExecutor", lambda **kw:
        TaiwanIntradayAcquisitionExecutor(nstock=nstock, **kw))
    with env.factory() as db:
        db.add(StockMaster(stock_id=stock_id, stock_name=stock_id, market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
        job, _ = subject.enqueue_consumer_demand(db, stock_id=stock_id, requested_at=NOW,
            consumer="ai", max_external_calls=1)
        job_id = job.id
        assert not calls  # Admission/coverage reads do not fetch.
    subject.run_consumer_demand(job_id)
    assert calls == [stock_id]
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == ("success" if complete else "error")
        assert result["reread_ready"] is complete
        assert result["target_expected_bucket_count"] == 60
        assert result["target_covered_bucket_count"] == len(points)
        assert result["external_call_count"] == result["external_call_budget_used"] == 1
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == len(points)
        db.execute(text("PRAGMA query_only=ON"))
        assert subject._reread(db, subject.consumer_request(job), NOW)["reread_ready"] is complete
        assert calls == [stock_id]


def test_http_429_retry_after_survives_canonical_adapter():
    from app.market.providers.tw_intraday_bars import NStockIntradayAdapter
    from app.market.tw_intraday_capabilities import NSTOCK_INTRADAY_DESCRIPTOR
    from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
    from app.market_data.contracts import InstrumentKey, InstrumentType, Market
    from app.market_data.policies import RealtimePolicy
    from app.market_data.provider_catalog import plan_data_acquisition_v2
    from app.observability.provider_http import ProviderHttpError, ProviderHttpFailure, ProviderRequestContext
    requirement = build_taiwan_intraday_requirement(
        instrument=InstrumentKey(market=Market.TW, symbol="2330", instrument_type=InstrumentType.STOCK, venue="TWSE"),
        interval="1m", range_value="1d", policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW, acquiring=True,
    )
    def limited(*a):
        raise ProviderHttpError("HTTP 429", failure=ProviderHttpFailure(
            context=ProviderRequestContext(market="tw", provider="nstock", resource="stock_intraday", target="2330"),
            status="rate_limited", source_url="https://fixture.invalid", error_message="HTTP 429",
            http_status_code=429, rate_limited=True, retry_after_seconds=600,
        ))
    plan = plan_data_acquisition_v2(requirement, (NSTOCK_INTRADAY_DESCRIPTOR,))
    result = NStockIntradayAdapter(limited, clock=lambda: NOW).acquire_route(requirement, plan.routes[0])
    assert result.receipts[0].status_code == 429
    assert "PROVIDER_RETRY_AFTER_SECONDS:600" in result.summary.limitations
    assert result.summary.external_calls == 1


def test_expired_status_is_read_only_and_has_no_next_dispatch(env, monkeypatch):
    from app.ai import refresh_status
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(seconds=181)).astimezone(tz)
    monkeypatch.setattr(refresh_status, "datetime", FrozenDateTime)
    with env.factory() as db:
        job, _ = enqueue(db)
        job.status = "queued"
        job.result_json = json.dumps({"next_retry_at": (NOW + timedelta(seconds=15)).isoformat()})
        db.commit()
        db.execute(text("PRAGMA query_only=ON"))
        result = refresh_status.read_refresh_status(db=db, job_id=job.id)
        assert result["status"] == "expired"
        assert result["next_retry_at"] is None
        assert result["retryable"] is False
        assert job.status == "queued"
    assert len(env.dispatches) == 1
