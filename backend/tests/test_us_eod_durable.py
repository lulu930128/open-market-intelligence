"""G2 isolated SQLite / fixture evidence; no runtime or live provider acceptance."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.market_data.provider_catalog import ProviderResourceRouteV2
from app.jobs import service as jobs
from app.jobs import us_intraday_materializer_scheduler as scheduler
from app.us_market import intraday_materializer as owner
from app.us_market import intraday_read_model_cache as cache
from test_us_intraday_convergence import DAY, AFTER_HOURS, platform_fixture
from test_us_intraday_shared_core import _db


MISSING = {"status": "missing", "coverage": {"point_count": 0}, "postcondition_satisfied": False}


def fixture_route(index=0):
    # Synthetic identities test accounting independently of the market catalog.
    return ProviderResourceRouteV2(
        provider_key=f"fixture_{index}", resource_id=f"fixture_{index}.bars",
        market="US", capability_id="intraday.bars", authority="vendor", priority=100,
        fetch_allowed=True, subscription_allowed=False, timeout_seconds=15,
        max_external_calls=1, max_subscriptions=0, max_symbols=1, max_range_days=1)


def admission_worker(url, now=AFTER_HOURS):
    engine = create_engine(url, connect_args={"timeout": 10})
    try:
        with Session(engine) as db:
            return owner._eod_admit(db, symbol="SSO", trade_date=DAY, now=now,
                                    evidence=MISSING, allow_call=True,
                                    planned_resource=fixture_route(int((now-AFTER_HOURS).total_seconds()//900)))
    finally:
        engine.dispose()


def crash_reserved_worker(url):
    engine = create_engine(url)
    with Session(engine) as db, owner._eod_worker_lease(db) as acquired:
        assert acquired
        owner._eod_admit(db, symbol="SSO", trade_date=DAY, now=AFTER_HOURS,
                         evidence=MISSING, allow_call=True, recover_orphan=True, planned_resource=fixture_route())
        os._exit(17)  # only this isolated test child; OS must release its lock


def finish_worker(args):
    url, item = args
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            try:
                owner._eod_finish(db, {**item, "reason": "provider_error"}, now=AFTER_HOURS)
                return "finished"
            except RuntimeError as exc:
                return str(exc)
    finally:
        engine.dispose()


@pytest.fixture
def ledger(tmp_path):
    url = "sqlite:///" + (tmp_path / "ledger.sqlite").as_posix()
    engine = create_engine(url)
    JobRun.__table__.create(engine)
    yield url, engine
    engine.dispose()


@pytest.mark.parametrize("executor", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_cross_worker_atomic_admission(ledger, executor):
    url, engine = ledger
    options = {"mp_context": multiprocessing.get_context("spawn")} if executor is ProcessPoolExecutor else {}
    with executor(max_workers=3, **options) as pool:
        rows = list(pool.map(admission_worker, [url] * 6))
    assert sum(r["acquisition_attempted"] for r in rows) == 1
    with Session(engine) as db:
        job = db.query(JobRun).one()
        assert job.status == "running"
        assert len(json.loads(job.request_json)["attempts"]) == 1


def test_restart_unknown_reservation_and_three_attempt_limit(ledger):
    url, engine = ledger
    first = admission_worker(url)
    assert first["next_retry_at"] == (AFTER_HOURS + timedelta(minutes=15)).isoformat()
    # Simulate a dead worker followed by the existing lifecycle recovery owner.
    with Session(engine) as db:
        assert jobs.mark_interrupted_jobs(db) == 1
    assert admission_worker(url, AFTER_HOURS + timedelta(minutes=1))["reason"] == "cooldown"
    for minute in (15, 30):
        item = admission_worker(url, AFTER_HOURS + timedelta(minutes=minute))
        with Session(engine) as db:
            owner._eod_finish(db, {**item, "reason": "provider_error"}, now=AFTER_HOURS + timedelta(minutes=minute))
    final = admission_worker(url, AFTER_HOURS + timedelta(hours=1))
    assert final["reason"] == "retry_budget_exhausted"
    with Session(engine) as db:
        attempts = json.loads(db.query(JobRun).one().request_json)["attempts"]
        assert len(attempts) == 3 and attempts[0]["outcome"] == "unknown"


def test_active_reservation_never_expires_into_parallel_io(ledger):
    url, _ = ledger
    admission_worker(url)
    assert admission_worker(url, AFTER_HOURS + timedelta(hours=8))["reason"] == "active_or_interrupted_reservation"


def test_crashed_worker_recovery_without_runtime_restart_and_fencing(ledger):
    url, engine = ledger
    process = multiprocessing.get_context("spawn").Process(target=crash_reserved_worker, args=(url,))
    process.start()
    process.join(30)
    assert process.exitcode == 17
    with Session(engine) as db, owner._eod_worker_lease(db) as acquired:
        assert acquired
        old = json.loads(db.query(JobRun).one().result_json)
        early = owner._eod_admit(db, symbol="SSO", trade_date=DAY, now=AFTER_HOURS + timedelta(minutes=1),
                                 evidence=MISSING, allow_call=True, recover_orphan=True, planned_resource=fixture_route())
        assert early["reason"] == "cooldown" and early["attempt_count"] == 1
        new = owner._eod_admit(db, symbol="SSO", trade_date=DAY, now=AFTER_HOURS + timedelta(minutes=15),
                               evidence=MISSING, allow_call=True, recover_orphan=True, planned_resource=fixture_route(1))
        assert new["attempt_count"] == 2
        with pytest.raises(RuntimeError, match="RESERVATION_LOST"):
            owner._eod_finish(db, old, now=AFTER_HOURS)
        assert db.query(JobRun).one().status == "running"


def test_live_worker_os_lease_prevents_reclaim(ledger):
    _, engine = ledger
    with Session(engine) as first, Session(engine) as second:
        with owner._eod_worker_lease(first) as acquired:
            assert acquired
            with owner._eod_worker_lease(second) as competing:
                assert competing is False


def test_index_check_and_reservation_share_writer_transaction(ledger):
    _, engine = ledger
    from sqlalchemy import event
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cu, statement, *_args: statements.append(statement))
    with Session(engine) as db:
        owner._eod_admit(db, symbol="SSO", trade_date=DAY, now=AFTER_HOURS, evidence=MISSING, allow_call=True, planned_resource=fixture_route())
    begin = next(i for i, s in enumerate(statements) if s == "BEGIN IMMEDIATE")
    verify = next(i for i, s in enumerate(statements) if "SELECT sql FROM sqlite_master" in s)
    insert = next(i for i, s in enumerate(statements) if s.startswith("INSERT INTO job_run"))
    assert begin < verify < insert


def test_two_process_finish_race_and_wrong_reservation_token(ledger):
    url, engine = ledger
    item = admission_worker(url)
    with Session(engine) as db, pytest.raises(RuntimeError, match="RESERVATION_LOST"):
        owner._eod_finish(db, {**item, "reservation_id": "old-worker"}, now=AFTER_HOURS)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(finish_worker, [(url, item)] * 2))
    assert sorted(results) == ["US_EOD_RESERVATION_LOST", "finished"]


def test_migration_up_down_and_missing_index_fails_closed(ledger):
    url, engine = ledger
    path = Path(__file__).parents[1] / "alembic/versions/20261009_0092_us_eod_obligation.py"
    spec = importlib.util.spec_from_file_location("g2_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    with pytest.raises(RuntimeError, match="MIGRATION_REQUIRED"):
        admission_worker(url)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    admission_worker(url)
    with engine.begin() as connection:
        with pytest.raises(Exception):
            connection.execute(text("INSERT INTO job_run (job_type, target, status, progress_current, progress_total, created_at, updated_at) SELECT job_type, target, 'error', 0, 1, created_at, updated_at FROM job_run"))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    assert not any(i["name"] == "uq_job_run_us_eod_obligation" for i in inspect(engine).get_indexes("job_run"))
    with Session(engine) as db:
        assert db.query(JobRun).count() == 1  # rollback removes index, never evidence


@pytest.mark.parametrize("count", [236, 390])
def test_partial_and_full_commit_invalidates_before_publish(count):
    from app.us_market.market_truth import read_us_market_truth_bundle
    db = _db()
    before = read_us_market_truth_bundle(db, symbol="AAPL", evaluated_at=AFTER_HOURS).snapshot.component_revisions.intraday_revision
    platform = platform_fixture(db, {"AAPL": count}, [])
    key = (1, "AAPL", "regular", "1m", "closed")
    cache.set_us_intraday_read_cache(key, {"revision": "old"})
    published = []
    def publish(result):
        assert cache.get_us_intraday_read_cache(key) is None
        published.extend(result["results"])
        raise RuntimeError("fixture publisher failed")
    result = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: db, platform_factory=lambda _: platform, publish=publish)
    item = result["results"][0]
    assert item["coverage"]["point_count"] == count
    assert item["postcondition_satisfied"] is (count == 390)
    assert item["consumer_cache_publish_error"] == "RuntimeError"
    assert len(published) == 1 and cache.get_us_intraday_read_cache(key) is None
    assert db.query(JobRun).one().status == ("success" if count == 390 else "error")
    db.rollback()
    after = read_us_market_truth_bundle(db, symbol="AAPL", evaluated_at=AFTER_HOURS).snapshot.component_revisions.intraday_revision
    assert before != after


def test_post_commit_failure_still_invalidates_publishes_and_rereads():
    db = _db()
    platform = platform_fixture(db, {"AAPL": 236}, [])
    refresh = platform.refresh_intraday_bars
    def post_commit_failure(**kwargs):
        refresh(**kwargs)
        raise RuntimeError("fixture failure after commit")
    platform.refresh_intraday_bars = post_commit_failure
    published = []
    def publish(result):
        published.extend(result["results"])
        return {"consumer_cache_publish_scheduled_count": 1}
    result = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: db, platform_factory=lambda _: platform, publish=publish)
    item = result["results"][0]
    assert item["coverage"]["point_count"] == 236
    assert item["status"] == "partial" and item["reason"] == "provider_error"
    assert item["consumer_cache_invalidated"] and len(published) == 1


def test_empty_or_unusable_success_is_not_complete():
    db = _db()
    platform = SimpleNamespace(
        read_intraday_bars_for_trade_date=lambda **_: SimpleNamespace(result=SimpleNamespace(
            resolved=SimpleNamespace(bars=(), health=SimpleNamespace(facts_usable=False)))),
        refresh_intraday_bars=lambda **_: SimpleNamespace(result=SimpleNamespace()),
    )
    result = owner.reconcile_us_intraday_session(
        configured_symbols="AAPL", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: db, platform_factory=lambda _: platform)
    assert result["results"][0]["status"] == "missing"
    assert not result["results"][0]["postcondition_satisfied"]
    assert db.query(JobRun).one().status == "error"


def test_retention_expiry_is_bounded_durable_and_never_complete(ledger):
    url, engine = ledger
    admission_worker(url)
    expired = owner.expire_us_intraday_obligations(
        configured_symbols="SSO", now=AFTER_HOURS + timedelta(days=6),
        session_factory=lambda: Session(engine))
    assert len(expired) == 1 and expired[0]["unfillable_reason"] == "retention_expired"
    assert expired[0]["next_retry_at"] is None and not expired[0]["postcondition_satisfied"]
    with Session(engine) as db:
        request = json.loads(db.query(JobRun).one().request_json)
        assert len(request["attempts"]) == 1  # never refunds unknown IO
    assert owner.expire_us_intraday_obligations(
        configured_symbols="SSO", now=AFTER_HOURS + timedelta(days=7),
        session_factory=lambda: Session(engine)) == []


def test_missing_migration_owner_has_no_provider_io(ledger):
    _, engine = ledger
    with engine.begin() as db:
        db.execute(text("DROP INDEX uq_job_run_us_eod_obligation"))
    def forbidden(**kwargs):
        raise AssertionError("provider called without durable admission")
    platform = SimpleNamespace(
        read_intraday_bars_for_trade_date=lambda **_: SimpleNamespace(result=SimpleNamespace(
            resolved=SimpleNamespace(bars=(), health=SimpleNamespace(facts_usable=False)))),
        refresh_intraday_bars=forbidden)
    result = owner.reconcile_us_intraday_session(
        configured_symbols="SSO", trade_date=DAY, now=AFTER_HOURS,
        session_factory=lambda: Session(engine), platform_factory=lambda _: platform)
    assert result["reserved_external_call_count"] == 0
    assert result["results"][0]["error_code"] == "US_EOD_DURABLE_ADMISSION_MIGRATION_REQUIRED"


def test_inflight_old_projection_cannot_repopulate_invalidated_cache():
    key = (1, "SSO", "regular", "1m", "closed")
    generation = cache.us_intraday_cache_generation("SSO")
    cache.invalidate_us_intraday_read_cache("SSO")
    cache.set_us_intraday_read_cache(key, {"revision": "old"}, expected_generation=generation)
    assert cache.get_us_intraday_read_cache(key) is None
    cache.set_us_intraday_read_cache(key, {"revision": "new"}, expected_generation=cache.us_intraday_cache_generation("SSO"))
    assert cache.get_us_intraday_read_cache(key)["revision"] == "new"


def test_symbol_fences_do_not_suppress_unrelated_aapl_publish():
    key = (1, "AAPL", "regular", "1m", "closed")
    generation = cache.us_intraday_cache_generation("AAPL")
    cache.invalidate_us_intraday_read_cache("SSO")
    cache.set_us_intraday_read_cache(key, {"revision": "aapl"}, expected_generation=generation)
    assert cache.get_us_intraday_read_cache(key)["revision"] == "aapl"


@pytest.mark.parametrize("now,latest", [
    (datetime(2026, 7, 6, 14, tzinfo=timezone.utc), "2026-07-02"),
    (datetime(2026, 11, 27, 18, 5, tzinfo=timezone.utc), "2026-11-27"),
    (datetime(2026, 11, 27, 18, 4, tzinfo=timezone.utc), "2026-11-25"),
    (datetime(2026, 3, 9, 19, tzinfo=timezone.utc), "2026-03-06"),
    (datetime(2026, 3, 9, 20, 5, tzinfo=timezone.utc), "2026-03-09"),
])
def test_scheduler_calendar_backlog_and_shared_budget(monkeypatch, now, latest):
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", True)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO,AAPL")
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return {"reserved_external_call_count": kwargs["max_external_calls"], "results": []}
    monkeypatch.setattr(scheduler, "_load_eod_durable_snapshot", lambda **_: None)
    monkeypatch.setattr(scheduler, "expire_us_intraday_obligations", lambda **_: [])
    monkeypatch.setattr(scheduler, "reconcile_us_intraday_session", run)
    result = scheduler.reconcile_us_completed_intraday_bars(now=now)
    assert result["trade_dates"][0] == latest
    assert len(calls) <= 6
    assert sum(c["max_external_calls"] for c in calls) == 2
    assert all(c["max_symbols"] == 2 and c["configured_symbols"] == "SSO,AAPL" for c in calls)
    assert all(0 <= (now.astimezone(owner.US_MARKET_TIMEZONE).date() - c["trade_date"]).days <= 5 for c in calls)


def test_effective_health_is_memory_only_and_disabled_callback_no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only health or disabled scheduler attempted IO")
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", False)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO,AMD,AAPL")
    monkeypatch.setattr(scheduler, "SessionLocal", forbidden)
    monkeypatch.setattr(scheduler, "reconcile_us_intraday_session", forbidden)
    monkeypatch.setattr(scheduler, "_EOD_SCHEDULER", SimpleNamespace(get_job=lambda _: object()))
    assert scheduler.reconcile_us_completed_intraday_bars()["reason"] == "disabled"
    from app.routers.system import health_check
    diagnostic = health_check()["runtime"]["us_intraday_reconciliation"]
    assert diagnostic["enabled"] is False and diagnostic["scheduler_registered"] is True
    assert diagnostic["symbols"] == []
    assert not diagnostic["universe"]["scope_valid"]
    assert diagnostic["configuration_source"] == "effective_process_settings"
    assert diagnostic["last_decision"]["reason"] == "disabled"


def test_three_symbol_configuration_fails_closed_instead_of_starving_amd(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", True)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO,AAPL,AMD")
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid configuration must not open DB or reserve")
    monkeypatch.setattr(scheduler, "expire_us_intraday_obligations", forbidden)
    monkeypatch.setattr(scheduler, "reconcile_us_intraday_session", forbidden)
    result = scheduler.reconcile_us_completed_intraday_bars(now=AFTER_HOURS)
    assert result["reason"] == "invalid_configuration"
    assert result["universe"]["configured_symbol_sample"] == ["SSO", "AAPL", "AMD"]
    assert scheduler.us_eod_runtime_summary()["configuration_status"] == "invalid_configuration"
    with pytest.raises(ValueError, match="INVALID_EXPLICIT_SCOPE"):
        owner.reconcile_us_intraday_session(
            configured_symbols="SSO,AAPL,AMD", trade_date=DAY, now=AFTER_HOURS, session_factory=forbidden)


def test_restart_loads_bounded_persisted_diagnostics_then_health_never_opens_db(ledger, monkeypatch):
    url, engine = ledger
    item = admission_worker(url)
    with Session(engine) as db:
        owner._eod_finish(db, {**item, "reason": "provider_error"}, now=AFTER_HOURS)
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", True)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO")
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(scheduler, "_EOD_LAST_DECISION", {})
    monkeypatch.setattr(scheduler, "_EOD_DURABLE_SNAPSHOT", {})
    class Scheduler:
        def __init__(self): self.jobs = {}
        def add_job(self, fn, **kwargs): self.jobs[kwargs["id"]] = fn
        def get_job(self, key): return self.jobs.get(key)
    scheduler.add_us_intraday_materializer_jobs(Scheduler())
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: pytest.fail("GET opened DB"))
    health = scheduler.us_eod_runtime_summary()
    assert health["scheduler_registered"]
    assert health["last_decision"] == {} and health["last_decision_in_process_only"]
    persisted = health["persisted_jobs_snapshot"]
    assert persisted["snapshot_available"] and persisted["job_run_count"] == 1
    assert persisted["jobs"][0]["attempt_count"] == 1
    assert persisted["jobs"][0]["next_retry_at"] == item["next_retry_at"]
    assert persisted["jobs"][0]["last_recorded_result"]["status"] == "missing"


def test_wrong_partial_predicate_fails_closed(ledger):
    url, engine = ledger
    with engine.begin() as db:
        db.execute(text("DROP INDEX uq_job_run_us_eod_obligation"))
        db.execute(text("CREATE UNIQUE INDEX uq_job_run_us_eod_obligation ON job_run(job_type,target) WHERE job_type = 'us.intraday_eod_obligation' AND status = 'running'"))
    with pytest.raises(RuntimeError, match="MIGRATION_REQUIRED"):
        admission_worker(url)


@pytest.mark.parametrize("finalization,usable,complete", [
    ("corrected", True, True), ("final", False, False), ("provisional", True, False),
])
def test_complete_requires_final_or_corrected_and_facts_usable(ledger, finalization, usable, complete):
    from app.market_data.contracts import BarFinalization
    _, engine = ledger
    start = datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)
    bars = tuple(SimpleNamespace(start_at=start + timedelta(minutes=i), finalization=BarFinalization(finalization)) for i in range(390))
    def forbidden(**kwargs): pytest.fail("zero call budget acquired provider")
    platform = SimpleNamespace(
        read_intraday_bars_for_trade_date=lambda **_: SimpleNamespace(result=SimpleNamespace(
            resolved=SimpleNamespace(bars=bars, health=SimpleNamespace(facts_usable=usable)))),
        refresh_intraday_bars=forbidden,
    )
    result = owner.reconcile_us_intraday_session(
        configured_symbols="SSO", trade_date=DAY, now=AFTER_HOURS, max_external_calls=0,
        session_factory=lambda: Session(engine), platform_factory=lambda _: platform)
    assert result["results"][0]["postcondition_satisfied"] is complete
    with Session(engine) as db:
        assert (db.query(JobRun).one().status == "success") is complete


def test_durable_five_day_backlog_advances_after_latest_budget_exhausted(ledger, monkeypatch):
    _, engine = ledger
    calls = []
    missing = SimpleNamespace(result=SimpleNamespace(resolved=SimpleNamespace(
        bars=(), health=SimpleNamespace(facts_usable=False))))
    def acquire(**kwargs):
        kwargs["before_acquire"](fixture_route(len(kwargs["excluded_providers"])))
        calls.append((kwargs["symbol"], kwargs["trade_date"]))
        return SimpleNamespace(result=SimpleNamespace())
    platform = SimpleNamespace(read_intraday_bars_for_trade_date=lambda **_: missing,
                               refresh_intraday_bars=acquire)
    reconcile = owner.reconcile_us_intraday_session
    expire = owner.expire_us_intraday_obligations
    monkeypatch.setattr(scheduler.settings, "enable_us_intraday_reconciliation", True)
    monkeypatch.setattr(scheduler.settings, "scheduler_us_intraday_reconciliation_symbols", "SSO,AMD")
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(scheduler, "expire_us_intraday_obligations", lambda **kw: expire(
        **kw, session_factory=lambda: Session(engine)))
    monkeypatch.setattr(scheduler, "reconcile_us_intraday_session", lambda **kw: reconcile(
        **kw, session_factory=lambda: Session(engine), platform_factory=lambda _: platform))
    for minute in (0, 15, 30, 45):
        # All persistent reads use fresh Sessions, as after a coordinator restart.
        result = scheduler.reconcile_us_completed_intraday_bars(now=AFTER_HOURS + timedelta(minutes=minute))
        assert result["reserved_external_call_count"] == 2
    assert len(calls) == 8
    assert all(day == DAY for _, day in calls[:6])
    assert all(day == DAY - timedelta(days=1) for _, day in calls[6:])
    assert result["reason_counts"]["retry_budget_exhausted"] == 2
    assert result["trade_dates"] == ["2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05"]
    with Session(engine) as db:
        assert db.query(JobRun).count() == 8
