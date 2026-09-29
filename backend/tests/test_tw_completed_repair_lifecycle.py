from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, JobRun, StockMaster, TaiwanIntradayRepairItem as Item, TaiwanIntradaySchedulerState as State
from app.jobs import taiwan_intraday_bar_scheduler as scheduler
from app.jobs import taiwan_intraday_repair as repair
from app.jobs import taiwan_intraday_demand as demand
from app.jobs.service import MARKET_BACKGROUND_MAX_IN_FLIGHT, mark_interrupted_jobs
from app.market.trading_calendar import TAIWAN_TZ

DAY = datetime(2026, 9, 21, 15, tzinfo=TAIWAN_TZ)


@pytest.fixture
def harness(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    ready = set()
    calls = []
    reads = []
    def reread(db, request, now):
        key = (request["trade_date"], request["stock_id"])
        reads.append((key, now))
        return {"reread_trade_date": key[0], "reread_ready": key in ready,
                "current_session_bar_count": 265 if key in ready else 0}
    def enqueue(db, **kw):
        calls.append(kw)
        request = dict(contract_version=demand.VERSION, market="TW", venue="TWSE",
            stock_id=kw["stock_id"], trade_date=kw["trade_date"], dataset="tw.intraday.1m",
            operation="tw.refresh_intraday_bars", interval="1m", consumer=kw["consumer"],
            mode="completed_session_repair", realtime_policy="prefer_live", max_attempts=3,
            max_external_calls=2, expires_at=(kw["requested_at"] + timedelta(seconds=120)).isoformat())
        job = JobRun(job_type=demand.JOB_TYPE, target=demand._target(request), status="queued",
            request_json=json.dumps(request), created_at=kw["requested_at"])
        db.add(job)
        db.commit()
        return job, True
    def add(symbol, kind="stock", active=True, market="TWSE"):
        with factory() as db:
            db.add(StockMaster(stock_id=symbol, market=market, instrument_type=kind, is_active=active))
            db.commit()
    def run(now=DAY, enqueuer=enqueue):
        # Recovery fixtures explicitly hand off residual obligations. Production
        # discovery belongs to normal ingestion, covered by the convergence test.
        with factory() as db:
            target = repair.latest_completed_taiwan_session_date(now)
            for (symbol,) in db.query(StockMaster.stock_id).all():
                if repair._eligible(db, symbol) and db.get(Item, (target, symbol)) is None:
                    db.add(Item(trade_date=target, stock_id=symbol, acquisition_lane="repair",
                        last_reason="EXPLICIT_REPAIR_OBLIGATION", scanned_at=now))
            db.commit()
        return scheduler.audit_completed_taiwan_intraday_coverage(now=now, session_factory=factory, enqueuer=enqueuer)
    monkeypatch.setattr(scheduler, "_reread", reread)
    monkeypatch.setattr(scheduler, "dispatch_due_materializations", lambda *a, **kw: 0)
    monkeypatch.setattr(scheduler.settings, "job_worker_max_concurrency", 3)
    monkeypatch.setattr(scheduler.settings, "scheduler_taiwan_intraday_repair_max_symbols_per_window", 2)
    yield SimpleNamespace(factory=factory, ready=ready, calls=calls, reads=reads, add=add, run=run, enqueue=enqueue)
    engine.dispose()


def test_scan_preserves_all_obligations_after_quota_and_reopening(harness):
    h = harness
    for i in range(70):
        h.add(str(2000 + i))
    for _ in range(3):
        result = h.run()
    assert result["coverage_scan_complete"]
    assert result["pending_repair_count"] == 68 and result["active_repair_count"] == 2
    assert not result["repair_complete"] and len(h.calls) == 2
    h.run(DAY + timedelta(minutes=10))
    assert len(h.calls) == 2
    with h.factory() as db:
        assert db.query(Item).count() == 70
        assert db.query(JobRun).count() == 2  # No checkpoint jobs.


def test_next_day_preopen_retries_interrupted_exact_date(harness):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        assert mark_interrupted_jobs(db) == 1
    result = h.run(datetime(2026, 9, 22, 9, tzinfo=TAIWAN_TZ))
    assert len(h.calls) == 1 and result["pending_repair_count"] == 1
    assert result["active_repair_count"] == 0
    result = h.run(datetime(2026, 9, 22, 9, 5, tzinfo=TAIWAN_TZ))
    assert h.calls[-1]["trade_date"] == "2026-09-21"
    assert len(h.calls) == 2 and result["active_repair_count"] == 1
    assert result["admission_window_start"].startswith("2026-09-22")


def test_restart_with_canonical_evidence_does_not_fetch(harness):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        mark_interrupted_jobs(db)
    h.ready.add(("2026-09-21", "2344"))
    result = h.run(DAY + timedelta(minutes=10))
    assert result["repair_complete"] and result["completed_repair_count"] == 1
    assert len(h.calls) == 1


def test_same_window_restart_uses_remaining_budget(harness):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        mark_interrupted_jobs(db)
    # Reconcile active -> pending before readmission. Simulate an early
    # recheck within the same window; reopening never mints reservations.
    for minute in range(1, 5):
        with h.factory() as db:
            db.query(Item).one().next_check_at = DAY
            db.commit()
        result = h.run(DAY + timedelta(minutes=minute))
        if minute == 1:
            assert len(h.calls) == 1 and result["pending_repair_count"] == 1
        else:
            assert len(h.calls) == 2 and result["admissions_reserved"] == 2
        if minute == 2:
            with h.factory() as db:
                assert mark_interrupted_jobs(db) == 1
    assert result["repair_budget_exhausted"] and result["pending_repair_count"] == 1


def test_persistently_partial_active_items_do_not_starve_unattempted_universe(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(repair.settings, "job_worker_max_concurrency", 2)
    symbols = {str(2000 + i) for i in range(70)}
    for symbol in sorted(symbols):
        h.add(symbol)
    for cycle in range(75):
        result = h.run(DAY + timedelta(minutes=cycle * 6))
        assert result["active_repair_count"] <= MARKET_BACKGROUND_MAX_IN_FLIGHT
        assert result["admissions_reserved"] <= MARKET_BACKGROUND_MAX_IN_FLIGHT
        with h.factory() as db:
            for job in db.query(JobRun).filter(JobRun.status.in_(("queued", "running"))):
                # Acquisition remains partial across every asynchronous episode.
                job.status = "error"
            db.commit()
    assert {call["stock_id"] for call in h.calls} == symbols
    assert len({call["stock_id"] for call in h.calls[:70]}) == 70
    assert result["coverage_scan_complete"] and not result["repair_complete"]
    assert result["completed_repair_count"] == 0


def test_horizon_closes_lifecycle_but_not_coverage(harness):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        mark_interrupted_jobs(db)
    result = h.run(datetime(2026, 9, 28, 9, tzinfo=TAIWAN_TZ))
    result = next(s for s in result["sessions"] if s["trade_date"] == "2026-09-21")
    assert result["trade_date"] == "2026-09-21"
    assert result["unfillable_count"] == 1
    assert result["lifecycle_complete"] and not result["repair_complete"]
    assert sum(c["trade_date"] == "2026-09-21" for c in h.calls) == 1


def test_canonical_eligibility_includes_uppercase_and_aliases(harness):
    h = harness
    h.add("0050", "ETF")
    h.add("0056", "exchange_traded_fund", market="TPEX")
    h.add("2330", " equity ")
    h.add("1111", "unknown")
    h.add("2222", "warrant")
    h.add("3333", "stock", active=False)
    h.add("4444", "index")
    h.add("5555", "stock", market="US")
    h.run()
    with h.factory() as db:
        assert {i.stock_id for i in db.query(Item)} == {"0050", "0056", "2330"}


@pytest.mark.parametrize("status", ["error", "success", "queued"])
def test_terminal_or_active_admissions_cannot_exceed_quota(harness, status):
    h = harness
    for i in range(40):
        h.add(str(2000+i))
    seen = []
    def enqueue(db, **kw):
        seen.append(kw)
        return SimpleNamespace(id=len(seen), status=status), True
    result = h.run(enqueuer=enqueue)
    assert len(seen) == 2 and result["admissions_reserved"] == 2
    assert not result["repair_complete"]


def test_two_target_dates_share_execution_day_quota(harness):
    h = harness
    for i in range(4):
        h.add(str(2000+i))
    h.run()
    with h.factory() as db:
        mark_interrupted_jobs(db)
    result = h.run(datetime(2026, 9, 22, 15, tzinfo=TAIWAN_TZ))
    assert len(h.calls) == 4
    assert {s["trade_date"] for s in result["sessions"]} == {"2026-09-21", "2026-09-22"}
    assert all(s["admissions_reserved"] == 2 for s in result["sessions"])


def test_admission_crash_preserves_reservation_and_pending(harness):
    h = harness
    h.add("2344")
    def crash(db, **kw):
        raise RuntimeError("submit failure")
    result = h.run(enqueuer=crash)
    assert result["pending_repair_count"] == 1
    assert result["admissions_reserved"] == 1
    result = h.run(DAY + timedelta(minutes=10))
    assert result["active_repair_count"] == 1 and result["admissions_reserved"] == 1


def test_active_job_recovers_when_backlog_lost_job_link(harness):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        item = db.query(Item).one()
        item.last_job_id = None
        item.status = "pending"
        db.commit()
    h.run(DAY + timedelta(minutes=10))
    assert len(h.calls) == 1
    with h.factory() as db:
        assert db.query(Item).one().last_job_id is not None


def test_exact_date_mismatch_never_completes(harness, monkeypatch):
    h = harness
    h.add("2344")
    monkeypatch.setattr(scheduler, "_reread", lambda *a: {
        "reread_ready": True, "reread_trade_date": "2026-09-18", "current_session_bar_count": 265})
    assert not h.run()["repair_complete"]


def test_checkpoint_and_single_demand_cannot_generic_retry(harness):
    from app.routers.jobs import _retry_config
    from app.ai.refresh_status import read_refresh_status, AiRefreshJobNotFoundError
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        job = db.query(JobRun).one()
        with pytest.raises(ValueError, match="exact-date"):
            _retry_config(job)
        legacy = JobRun(job_type=demand.JOB_TYPE, target="tw-coverage-audit:2026-09-21", status="success")
        db.add(legacy); db.commit()
        with pytest.raises(ValueError, match="exact-date"):
            _retry_config(legacy)
        with pytest.raises(AiRefreshJobNotFoundError):
            read_refresh_status(db=db, job_id=legacy.id)


def test_migration_imports_legacy_dates_and_removes_job_role(harness):
    h = harness
    with h.factory() as db:
        db.add(JobRun(job_type=demand.JOB_TYPE, target="tw-coverage-audit:2026-09-21",
            status="success", result_json=json.dumps({"audit_complete": True, "missing": 70, "cursor": "9999"})))
        db.commit()
        path = Path(__file__).parents[1] / "alembic/versions/20260922_0089_tw_intraday_repair_backlog.py"
        spec = importlib.util.spec_from_file_location("repair_migration", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        connection = db.connection()
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        db.commit()
        state = json.loads(db.get(State, "tw-coverage-audit:2026-09-21").state_json)
        assert state["scan_cursor"] == "" and not state["coverage_scan_complete"]
        assert db.query(JobRun).one().job_type == "tw.intraday.scheduler_checkpoint"


def test_backlog_replenishes_within_same_execution_day(harness):
    h = harness
    for i in range(4):
        h.add(str(2000+i))
    def finish(db, **kw):
        job, created = h.enqueue(db, **kw)
        h.ready.add((kw["trade_date"], kw["stock_id"]))
        job.status = "success"
        db.commit()
        return job, created
    first = h.run(enqueuer=finish)
    assert first["completed_repair_count"] == first["pending_repair_count"] == 2
    assert not first["repair_complete"]
    next_cycle = h.run(DAY + timedelta(minutes=5), enqueuer=finish)
    assert next_cycle["repair_complete"] and next_cycle["completed_repair_count"] == 4
    assert len(h.calls) == 4


def test_expired_date_with_read_failure_does_not_retry_forever(harness, monkeypatch):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        mark_interrupted_jobs(db)
    def broken(*args):
        raise ValueError("policy unavailable")
    monkeypatch.setattr(scheduler, "_reread", broken)
    result = h.run(datetime(2026, 9, 28, 9, tzinfo=TAIWAN_TZ))
    result = next(s for s in result["sessions"] if s["trade_date"] == "2026-09-21")
    assert result["unfillable_count"] == 1 and result["lifecycle_complete"]
    assert not result["repair_complete"]


def test_migration_creates_missing_tables_and_roundtrips(harness):
    h = harness
    with h.factory() as db:
        path = Path(__file__).parents[1] / "alembic/versions/20260922_0089_tw_intraday_repair_backlog.py"
        spec = importlib.util.spec_from_file_location("repair_migration_fresh", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        connection = db.connection()
        Item.__table__.drop(connection)
        State.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.downgrade()
            module.upgrade()
            path90 = Path(__file__).parents[1] / "alembic/versions/20260922_0090_tw_completed_materialization.py"
            spec90 = importlib.util.spec_from_file_location("completed_migration", path90)
            module90 = importlib.util.module_from_spec(spec90); spec90.loader.exec_module(module90)
            module90.upgrade()
            module90.upgrade()
        db.commit()
        assert db.query(Item).count() == db.query(State).count() == 0


def test_budget_reservation_is_atomic_across_sessions(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    engine = create_engine(f"sqlite:///{(tmp_path / 'budget.db').as_posix()}",
                           connect_args={"timeout": 15})
    State.__table__.create(engine)
    JobRun.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(repair.settings, "scheduler_taiwan_intraday_repair_max_symbols_per_window", 2)
    with factory() as db:
        repair._cycle_budget(db, DAY)
    def reserve(_):
        with factory() as db:
            return repair._reserve(db, DAY)
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(workers.map(reserve, range(8))) == 2
    with factory() as db:
        assert repair._cycle_budget(db, DAY)[1]["reserved"] == 2
    engine.dispose()


def test_budget_seeds_old_episodes_by_execution_day(harness):
    h = harness
    h.add("2344")
    with h.factory() as db:
        h.enqueue(db, stock_id="2344", trade_date="2026-09-18", requested_at=DAY,
                  consumer="completed_session_repair")
        job = db.query(JobRun).one()
        job.created_at = DAY.astimezone(repair.timezone.utc)
        db.commit()
        mark_interrupted_jobs(db)
    result = h.run()
    assert result["admissions_reserved"] == 2
    assert result["repair_budget_exhausted"]


def test_canonical_reads_do_not_hold_sqlite_writer_lock(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'writer.db').as_posix()}",
                           connect_args={"timeout": 0.1})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(StockMaster(stock_id="2344", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
    observed = []
    def reread(db, request, now):
        # A separate market writer must succeed both for a newly attached item
        # during scan and an existing item during backlog reevaluation.
        with engine.begin() as other:
            other.execute(State.__table__.insert().values(key=f"writer:{len(observed)}",
                state_json="{}", revision=0, updated_at=now))
        observed.append(request)
        return {"reread_ready": False, "reread_trade_date": request["trade_date"],
                "current_session_bar_count": 0}
    monkeypatch.setattr(scheduler, "_reread", reread)
    monkeypatch.setattr(scheduler, "dispatch_due_materializations", lambda *a, **kw: 0)
    monkeypatch.setattr(scheduler.settings, "scheduler_taiwan_intraday_repair_max_symbols_per_window", 0)
    scheduler.audit_completed_taiwan_intraday_coverage(now=DAY, session_factory=factory,
        enqueuer=lambda *a, **kw: (None, False))
    assert len(observed) == 2
    engine.dispose()


def test_active_results_are_reconciled_before_unattempted_backlog(harness):
    h = harness
    for i in range(70):
        h.add(str(2000+i))
    h.run()
    for call in h.calls:
        h.ready.add((call["trade_date"], call["stock_id"]))
    result = h.run(DAY + timedelta(minutes=10))
    assert result["completed_repair_count"] == 2
    assert result["active_repair_count"] == 0
    assert result["pending_repair_count"] == 68
    assert len(h.calls) == 2


def test_live_episode_is_not_terminalized_at_horizon_boundary(harness, monkeypatch):
    h = harness
    h.add("2344")
    h.run()
    with h.factory() as db:
        job = db.query(JobRun).one()
        job.status = "running"
        db.commit()
    monkeypatch.setattr(repair, "completed_taiwan_intraday_repair_eligibility", lambda *a, **kw: {"eligible": False})
    result = h.run(DAY + timedelta(minutes=10))
    assert result["active_repair_count"] == 1 and not result["lifecycle_complete"]


def test_full_universe_converges_in_bounded_windows_through_owner_and_disk_restart(tmp_path, monkeypatch):
    """Real backlog/checkpoints/admission; deterministic canonical IO and worker completion."""
    url = f"sqlite:///{(tmp_path / 'resume.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    symbols = [str(2000 + i) for i in range(70)]
    with factory() as db:
        db.add_all(StockMaster(stock_id=s, market="TWSE", instrument_type="stock", is_active=True) for s in symbols)
        db.commit()
    ready = {symbols[0]}  # Already complete evidence must never be acquired again.
    submitted = []
    clock = [DAY]
    def reread(db, request, now):
        complete = request["stock_id"] in ready
        return dict(reread_ready=complete, reread_trade_date=request["trade_date"],
                    current_session_bar_count=265 if complete else 144)
    monkeypatch.setattr(scheduler, "_reread", reread)
    monkeypatch.setattr(demand, "_reread", reread)
    monkeypatch.setattr(demand, "_now", lambda: clock[0])
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: submitted.append(job_id))
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    monkeypatch.setattr(repair.settings, "scheduler_taiwan_intraday_repair_max_symbols_per_window", 3)
    monkeypatch.setattr(repair.settings, "job_worker_max_concurrency", 3)
    attempts = {}
    cursors = []
    retry_after = DAY + timedelta(minutes=12)
    try:
        for tick in range(180):
            clock[0] = DAY + timedelta(minutes=tick)
            result = scheduler.audit_completed_taiwan_intraday_coverage(now=clock[0], session_factory=factory)
            cursors.append(result["scanned_count"])
            assert result["admissions_reserved"] <= 3
            with factory() as db:
                active = db.query(JobRun).filter(JobRun.status.in_(("queued", "running"))).all()
                assert len(active) <= 5  # completed lane 3 + residual lane <= 2
                assert len({job.target for job in active}) == len(active)
                for job_id in submitted:
                    job = db.get(JobRun, job_id)
                    request = demand.materialization_request(job)
                    symbol = request["stock_id"]
                    assert symbol != symbols[0]
                    attempts[symbol] = attempts.get(symbol, 0) + 1
                    if symbol == symbols[1] and attempts[symbol] == 1:
                        demand._finish(db, job, dict(reread_ready=False, current_session_bar_count=144,
                            retry_not_before_at=retry_after.isoformat()), "PROVIDER_BACKOFF")
                    else:
                        if symbol == symbols[1]:
                            assert clock[0] >= retry_after
                        ready.add(symbol)
                        demand._finish(db, job, reread(db, request, clock[0]), "CANONICAL_COVERAGE_READY")
                submitted.clear()
            if tick == 1:
                # Lose all SQLAlchemy runtime state, then resume the same durable owner.
                engine.dispose()
                engine = create_engine(url)
                factory = sessionmaker(engine)
                monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
                with factory() as db:
                    state = json.loads(db.get(State, "tw-coverage-audit:2026-09-21").state_json)
                    assert state["scanned_count"] == 32
                    assert db.query(Item).count() == 70  # membership frozen atomically
            if result["repair_complete"]:
                break
        assert result["repair_complete"], result
        assert result["coverage_scan_complete"] and result["complete_count"] == len(symbols)
        assert result["pending_repair_count"] == result["active_repair_count"] == 0
        assert cursors[0] < cursors[1] < cursors[2]
        assert attempts[symbols[1]] == 2
        assert all(count == 1 for symbol, count in attempts.items() if symbol != symbols[1])
        assert clock[0].date() == DAY.date()  # No daily quota reset needed.
    finally:
        engine.dispose()
