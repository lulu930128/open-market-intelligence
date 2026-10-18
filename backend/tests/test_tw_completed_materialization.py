"""Normal completed-session ingestion, residual handoff and lane isolation."""

from r1d_test_support import isolated_job_lifecycle  # noqa: F401
from datetime import datetime, timedelta
from threading import Event, Lock
from types import SimpleNamespace
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, JobRun, StockMaster, TaiwanIntradayRepairItem as Item, TaiwanIntradaySchedulerState as State
from app.jobs import taiwan_intraday_demand as demand
from app.jobs import taiwan_intraday_bar_scheduler as scheduler
from app.jobs import taiwan_intraday_repair as coordinator
from app.market.trading_calendar import TAIWAN_TZ

DAY = datetime(2026, 9, 22, 15, tzinfo=TAIWAN_TZ)
REAL_REREAD = demand._reread


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'normal.db').as_posix()}"
    engine = create_engine(url)
    # SQLite's legacy transaction mode otherwise commits every schema statement.
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN")
        Base.metadata.create_all(connection)
    factory = sessionmaker(engine)
    ready, submitted = set(), []
    clock = [DAY]
    def reread(db, request, now):
        return dict(reread_ready=request["stock_id"] in ready,
            reread_trade_date=request["trade_date"],
            current_session_bar_count=265 if request["stock_id"] in ready else 144)
    monkeypatch.setattr(scheduler, "_reread", reread)
    monkeypatch.setattr(demand, "_reread", reread)
    monkeypatch.setattr(demand, "_now", lambda: clock[0])
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: submitted.append((job_id, kw)))
    monkeypatch.setattr(coordinator.settings, "scheduler_taiwan_completed_materialization_batch_size", 2)
    def add(symbol, active=True):
        with factory() as db:
            db.add(StockMaster(stock_id=symbol, market="TWSE", instrument_type="stock", is_active=active))
            db.commit()
    def run():
        return scheduler.audit_completed_taiwan_intraday_coverage(now=clock[0], session_factory=factory)
    yield SimpleNamespace(factory=factory, engine=engine, url=url, ready=ready, submitted=submitted,
        clock=clock, reread=reread, add=add, run=run)
    engine.dispose()


def test_frozen_universe_complete_skip_and_no_membership_drift(env):
    h = env
    for s in ("1101", "2303", "2330", "2454", "2603"):
        h.add(s)
    h.ready.add("1101")
    first = h.run()
    assert first["eligible_count"] == 5 and first["scanned_count"] == 2
    assert first["complete_count"] == 1 and first["normal_submitted_count"] == 1
    h.add("9999")
    with h.factory() as db:
        db.query(StockMaster).filter_by(stock_id="2454").one().is_active = False
        db.commit()
    for _ in range(3):
        result = h.run()
    assert result["universe_revision"] == first["universe_revision"]
    assert result["eligible_count"] == 5 and result["scanned_count"] == 5
    assert result["not_applicable_count"] == 1
    with h.factory() as db:
        assert db.get(Item, (DAY.date(), "9999")) is None
        requests = [demand.materialization_request(j) for j in db.query(JobRun)]
        assert all(r["stock_id"] != "1101" and r["max_attempts"] == 1 for r in requests)
        assert all(r["consumer"] == r["mode"] == "completed_session" for r in requests)


def test_terminal_partial_hands_same_row_to_repair_without_normal_retry(env):
    h = env
    h.add("2303")
    first = h.run()
    assert first["admissions_reserved"] == 0
    with h.factory() as db:
        job = db.query(JobRun).one()
        demand._finish(db, job, h.reread(db, demand.materialization_request(job), DAY), "PARTIAL")
        job_id = job.id
    result = h.run()
    assert result["normal_failed_count"] == result["pending_repair_count"] == 1
    for _ in range(3):
        h.run()
    with h.factory() as db:
        item = db.query(Item).one()
        assert item.acquisition_lane == "repair" and item.last_job_id == job_id
        assert item.normal_attempted_at is not None and item.attempt_count == 0
        assert db.query(JobRun).count() == 1
    assert not result["data_complete"] and not result["lifecycle_complete"]


def test_crash_between_attempt_reservation_and_job_is_conservative(env):
    h = env
    h.add("2303")
    with h.factory() as db:
        row, state = coordinator.checkpoint(db, f"{coordinator.AUDIT_PREFIX}{DAY.date()}")
        coordinator._freeze(db, row, state, DAY.date(), DAY)
        item = db.query(Item).one()
        item.normal_attempted_at = DAY
        item.status = "active"
        item.scanned_at = DAY
        db.commit()
    result = h.run()
    assert result["normal_failed_count"] == 1 and not h.submitted
    with h.factory() as db:
        assert db.query(Item).one().acquisition_lane == "repair"


def test_existing_job_reused_across_normal_admission(env):
    h = env
    h.add("2303")
    with h.factory() as db:
        old, _ = demand.enqueue_intraday_materialization_demand(db, stock_id="2303", requested_at=DAY,
            consumer="viewer", max_external_calls=2)
        old_id = old.id
    h.run()
    h.run()
    with h.factory() as db:
        assert db.query(JobRun).count() == 1
        assert db.query(Item).one().last_job_id == old_id
    assert len(h.submitted) == 1


def test_retry_after_is_durable_and_worker_checks_before_io(env, monkeypatch):
    h = env
    h.add("2303"); h.add("2454")
    h.run()
    until = DAY + timedelta(minutes=10)
    with h.factory() as db:
        demand._record_completed_backoff(db, until)
        demand._record_completed_backoff(db, DAY + timedelta(minutes=1))
        assert demand.completed_lane_backoff(db) == until
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars",
        lambda *a, **kw: pytest.fail("provider IO during durable backoff"))
    for job_id, _ in h.submitted:
        demand.run_consumer_demand(job_id)
    h.engine.dispose()
    result = h.run()
    assert result["normal_failed_count"] == 2 and result["admissions_reserved"] == 0
    h.clock[0] += timedelta(minutes=6)
    h.run()
    with h.factory() as db:
        assert db.query(JobRun).count() == 2
        for item in db.query(Item):
            assert item.next_check_at >= until.replace(tzinfo=None)


def test_provider_retry_after_propagates_to_lane(env, monkeypatch):
    h = env
    h.add("2303")
    h.run()
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars", lambda *a, **kw: SimpleNamespace(
        acquisition=SimpleNamespace(external_calls=1, limitations=("PROVIDER_RETRY_AFTER_SECONDS:600",)),
        persistence=SimpleNamespace(observations_written=0, attempted=False, committed=False)))
    demand.run_consumer_demand(h.submitted[0][0])
    with h.factory() as db:
        assert demand.completed_lane_backoff(db) == DAY + timedelta(minutes=10)
        assert db.query(JobRun).one().status == "error"
        assert json.loads(db.query(JobRun).one().result_json)["attempt_count"] == 1


def test_legacy_unattempted_moves_to_normal_but_tried_recovery_is_preserved(env):
    h = env
    for s in ("2303", "2454"):
        h.add(s)
    with h.factory() as db:
        db.add(Item(trade_date=DAY.date(), stock_id="2303", attempt_count=0,
                    last_reason="CANONICAL_COVERAGE_INCOMPLETE"))
        db.add(Item(trade_date=DAY.date(), stock_id="2454", attempt_count=2,
                    next_check_at=DAY + timedelta(minutes=30)))
        db.commit()
    h.run()
    with h.factory() as db:
        assert db.get(Item, (DAY.date(), "2303")).acquisition_lane == "normal"
        assert db.get(Item, (DAY.date(), "2454")).acquisition_lane == "repair"


def test_normal_lane_does_not_acquire_during_regular_session(env):
    h = env
    h.add("2303")
    h.clock[0] = DAY.replace(hour=10)
    h.run()
    assert not h.submitted
    with h.factory() as db:
        with pytest.raises(ValueError, match="SESSION_NOT_COMPLETED"):
            demand.enqueue_intraday_materialization_demand(db, stock_id="2303", requested_at=h.clock[0],
                consumer="completed_session", trade_date=DAY.date().isoformat())


def test_frozen_venue_cannot_silently_change_target(env):
    h = env
    for symbol in ("1101", "2303", "2454"):
        h.add(symbol)
    before = h.run()
    with h.factory() as db:
        db.query(StockMaster).filter_by(stock_id="2454").one().market = "TPEX"
        db.commit()
    after = h.run()
    assert before["universe_revision"] == after["universe_revision"]
    with h.factory() as db:
        item = db.get(Item, (DAY.date(), "2454"))
        assert item.status == "not_applicable" and item.last_reason == "FROZEN_INSTRUMENT_CHANGED"
        assert item.normal_attempted_at is None


def test_empty_master_does_not_freeze_a_false_complete_universe(env):
    h = env
    first = h.run()
    assert first["universe_unavailable"] and not first["lifecycle_complete"]
    h.add("2303")
    assert h.run()["eligible_count"] == 1


def test_restart_audits_terminal_legacy_repair_rows_and_releases_oldest_session(env):
    h = env
    h.add("2330")
    h.ready.add("2330")
    oldest = DAY.date() - timedelta(days=1)
    with h.factory() as db:
        db.add(Item(trade_date=oldest, stock_id="2330", acquisition_lane="repair",
                    status="complete", attempt_count=1, scanned_at=None))
        coordinator.checkpoint(db, f"{coordinator.AUDIT_PREFIX}{oldest}")
    h.engine.dispose()  # A new Session must recover the persisted metadata gap.
    result = h.run()
    old = next(s for s in result["sessions"] if s["trade_date"] == oldest.isoformat())
    assert old["scanned_count"] == 1 and old["lifecycle_complete"]
    assert old["data_complete"] and not h.submitted
    assert len(h.run()["sessions"]) == 1


def test_unscanned_repair_audit_preserves_future_backoff(env):
    h = env
    h.add("2330")
    retry = DAY + timedelta(hours=2)
    with h.factory() as db:
        db.add(Item(trade_date=DAY.date(), stock_id="2330", acquisition_lane="repair",
                    status="pending", attempt_count=2, next_check_at=retry,
                    last_reason="EXISTING_PROVIDER_BACKOFF"))
        db.commit()
    result = h.run()
    with h.factory() as db:
        item = db.get(Item, (DAY.date(), "2330"))
        assert item.scanned_at is not None
        assert item.next_check_at == retry.replace(tzinfo=None)
        assert item.attempt_count == 2 and item.acquisition_lane == "repair"
    assert result["admissions_reserved"] == 0 and not h.submitted


def test_holiday_restart_keeps_september_24_as_completed_session(env):
    h = env
    for symbol in ("2330", "2344"):
        h.add(symbol)
        h.ready.add(symbol)
    h.clock[0] = datetime(2026, 9, 29, 8, 35, tzinfo=TAIWAN_TZ)
    result = h.run()
    assert result["trade_date"] == "2026-09-24"
    assert result["complete_count"] == 2 and result["data_complete"]
    assert not h.submitted
    with h.factory() as db:
        assert db.get(State, "tw-coverage-audit:2026-09-28") is None


def test_september_24_sparse_backlog_terminalizes_after_horizon_across_restart(env):
    h = env
    h.add("1101")
    h.clock[0] = datetime(2026, 9, 30, 8, 35, tzinfo=TAIWAN_TZ)
    old = DAY.date() - timedelta(days=1)
    target = DAY.date() + timedelta(days=2)  # 2026-09-24
    with h.factory() as db:
        # The old terminal row used to pin the historical slot forever.
        db.add(Item(trade_date=old, stock_id="1101", acquisition_lane="repair",
                    status="complete", attempt_count=1))
        coordinator.checkpoint(db, f"{coordinator.AUDIT_PREFIX}{old}")
        db.add(Item(trade_date=target, stock_id="1101", acquisition_lane="repair",
                    status="pending", attempt_count=3, scanned_at=DAY,
                    last_reason="CANONICAL_COVERAGE_INCOMPLETE"))
        coordinator.checkpoint(db, f"{coordinator.AUDIT_PREFIX}{target}")
        demand._record_completed_backoff(db, h.clock[0] + timedelta(hours=1))
    h.run()
    h.engine.dispose()
    result = h.run()
    completed = next(s for s in result["sessions"] if s["trade_date"] == target.isoformat())
    assert completed["lifecycle_complete"] and not completed["data_complete"]
    assert completed["unfillable_count"] == 1 and completed["remaining_count"] == 0
    assert completed["repair_retry_count"] == 3 and not h.submitted


def test_cache_only_reread_cannot_mutate_or_dispatch_normal_lane(env, monkeypatch):
    from sqlalchemy import event
    h = env
    h.add("2303")
    h.run()
    def reject_write(conn, cursor, statement, parameters, context, many):
        assert not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
    event.listen(h.engine, "before_cursor_execute", reject_write)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda *a, **kw: pytest.fail("read dispatched"))
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars", lambda *a, **kw: pytest.fail("read acquired"))
    try:
        with h.factory() as db:
            result = REAL_REREAD(db, {"stock_id": "2303", "trade_date": DAY.date().isoformat()}, DAY)
            assert not result["reread_ready"] and result["current_session_bar_count"] == 0
    finally:
        event.remove(h.engine, "before_cursor_execute", reject_write)


def test_completed_executor_bound_is_independent_of_general_jobs(monkeypatch):
    from threading import BoundedSemaphore
    from app.jobs import service
    release, entered = Event(), Event()
    lock = Lock()
    running = []
    monkeypatch.setattr(service, "_materialization_slots", {
        "market_completed": BoundedSemaphore(3), "market_background": BoundedSemaphore(2)})
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    def task(job_id):
        with lock:
            running.append(job_id)
            if len(running) == 4:
                entered.set()
        assert release.wait(5)
    try:
        for i in range(3):
            service.submit_job_task(task, i, execution_lane="market_completed")
        with pytest.raises(RuntimeError, match="QUEUE_FULL"):
            service.submit_job_task(task, 4, execution_lane="market_completed")
        service.submit_job_task(task, 9)  # General worker remains available.
        assert entered.wait(5)
        assert service._get_executor()._max_workers == 1
        assert service._materialization_executors["market_completed"]._max_workers == 3
    finally:
        release.set()
        service.shutdown_job_executor(wait=True)


def test_large_freeze_batches_commits_and_resumes_fixed_membership(env, monkeypatch):
    from sqlalchemy import event
    h = env
    # This fixture measures work/commit bounds; the separate monotonic fixture
    # proves elapsed-time termination without depending on host speed.
    monkeypatch.setattr(coordinator, "monotonic", lambda: 0.0)
    symbols = [str(10000 + i) for i in range(2048)]
    with h.factory() as db:
        db.add_all(StockMaster(stock_id=s, market="TWSE", instrument_type="stock", is_active=True)
                   for s in symbols)
        db.commit()
    commits, reads = [], []
    event.listen(h.factory, "after_commit", lambda session: commits.append(1))
    original = coordinator._eligible
    def eligible(db, symbol):
        reads.append(symbol)
        return original(db, symbol)
    monkeypatch.setattr(coordinator, "_eligible", eligible)
    result = h.run()
    assert result["reason"] == "freeze_slice" and not result["data_complete"]
    assert len(reads) == coordinator.FREEZE_SLICE_SIZE
    # Initial checkpoint + candidate snapshot + bounded batches, not per member.
    assert len(commits) <= 2 + coordinator.FREEZE_SLICE_SIZE // coordinator.FREEZE_COMMIT_SIZE
    with h.factory() as db:
        state = json.loads(db.get(State, f"{coordinator.AUDIT_PREFIX}{DAY.date()}").state_json)
        assert state["freeze_cursor"] == db.query(Item).count() == len(reads)
        assert "universe_revision" not in state and not db.query(JobRun).count()
    h.add("99999")  # A late member cannot enter the frozen candidate snapshot.
    h.engine.dispose()
    for _ in range(len(symbols) // coordinator.FREEZE_SLICE_SIZE):
        result = h.run()
        if "universe_revision" in result:
            break
    assert result["eligible_count"] == len(symbols)
    assert {i["stock_id"] for i in result["universe"]} == set(symbols)
    assert len(result["universe"]) == len(set(i["stock_id"] for i in result["universe"]))
    assert not result["data_complete"]


def test_freeze_pause_commits_only_finished_batch_and_crash_rolls_back_cursor(env, monkeypatch):
    h = env
    for i in range(40):
        h.add(str(10000 + i))
    pause = Event()
    original = coordinator._eligible
    visits = []
    def eligible(db, symbol):
        visits.append(symbol)
        if len(visits) == 19:
            pause.set()
        return original(db, symbol)
    monkeypatch.setattr(coordinator, "_eligible", eligible)
    result = scheduler.audit_completed_taiwan_intraday_coverage(now=DAY,
        session_factory=h.factory, should_pause=pause.is_set)
    assert result["reason"] == "scheduler_pause" and not h.submitted
    with h.factory() as db:
        state = json.loads(db.get(State, f"{coordinator.AUDIT_PREFIX}{DAY.date()}").state_json)
        assert state["freeze_cursor"] == db.query(Item).count() == 19
        assert "universe_revision" not in state
    pause.clear()
    save = coordinator.save_checkpoint
    def crash(db, row, state, now):
        if state.get("freeze_cursor", 0) > 19:
            raise RuntimeError("disposable crash before commit")
        return save(db, row, state, now)
    monkeypatch.setattr(coordinator, "save_checkpoint", crash)
    with pytest.raises(RuntimeError, match="disposable crash"):
        h.run()
    with h.factory() as db:
        state = json.loads(db.get(State, f"{coordinator.AUDIT_PREFIX}{DAY.date()}").state_json)
        assert state["freeze_cursor"] == db.query(Item).count() == 19
    monkeypatch.setattr(coordinator, "save_checkpoint", save)
    h.engine.dispose()
    assert h.run()["eligible_count"] == 40
    with h.factory() as db:
        assert db.query(Item).count() == 40


def test_shared_time_budget_stops_freeze_before_next_candidate(env, monkeypatch):
    h = env
    for i in range(40):
        h.add(str(10000 + i))
    ticks = [0.0]
    monkeypatch.setattr(coordinator, "monotonic", lambda: ticks[0])
    original = coordinator._eligible
    def slow_read(db, symbol):
        ticks[0] += 1.0
        return original(db, symbol)
    monkeypatch.setattr(coordinator, "_eligible", slow_read)
    result = h.run()
    assert result["reason"] == "slice_budget" and not result["coverage_scan_complete"]
    with h.factory() as db:
        state = json.loads(db.get(State, f"{coordinator.AUDIT_PREFIX}{DAY.date()}").state_json)
        assert state["freeze_cursor"] == db.query(Item).count() == 5
        assert not db.query(JobRun).count()


def test_summary_query_cost_does_not_grow_per_active_job(env):
    from sqlalchemy import event
    h = env
    with h.factory() as db:
        row, state = coordinator.checkpoint(db, f"{coordinator.AUDIT_PREFIX}{DAY.date()}")
        universe = [{"stock_id": str(10000 + i)} for i in range(1000)]
        for member in universe:
            job = JobRun(job_type=demand.JOB_TYPE, target="fixture", status="queued")
            db.add(job)
            db.flush()
            db.add(Item(trade_date=DAY.date(), stock_id=member["stock_id"], status="active",
                        acquisition_lane="repair", scanned_at=DAY, last_job_id=job.id))
        state.update(universe=universe, universe_revision="fixture")
        coordinator.save_checkpoint(db, row, state, DAY)
        statements = []
        def record(conn, cursor, statement, *args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(h.engine, "before_cursor_execute", record)
        try:
            coordinator._summary(db, row, {**state, "universe": universe[:1]}, DAY.date(), DAY)
            small_query_count = len(statements)
            statements.clear()
            result = coordinator._summary(db, row, state, DAY.date(), DAY)
        finally:
            event.remove(h.engine, "before_cursor_execute", record)
        assert result["queued_count"] == 1000 and result["active_count"] == 0
        assert not result["lifecycle_complete"] and not result["data_complete"]
        assert len(statements) <= small_query_count, statements


def test_real_audit_returns_before_executor_reports_quiescence(env, monkeypatch):
    import time
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler as owner_module
    h = env
    for symbol in ("1101", "2303", "2330"):
        h.add(symbol)
    for field in type(owner_module.settings).model_fields:
        if field.startswith("enable_"):
            monkeypatch.setattr(owner_module.settings, field, False)
    monkeypatch.setattr(owner_module.settings, "enable_scheduler", True)
    with monkeypatch.context() as registration:
        registration.setattr(BackgroundScheduler, "add_job", lambda *a, **kw: None)
        owner = owner_module.start_scheduler()
    entered, release, finished = Event(), Event(), Event()
    result = []
    def reread(db, request, now):
        entered.set()
        assert release.wait(5)
        return h.reread(db, request, now)
    monkeypatch.setattr(scheduler, "_reread", reread)
    def work():
        try:
            result.append(scheduler.audit_completed_taiwan_intraday_coverage(now=DAY,
                session_factory=h.factory, should_pause=owner.restart_pause_requested))
        finally:
            finished.set()
    try:
        owner.add_job(work)
        assert entered.wait(3)
        lease = owner.pause_for_restart()
        assert owner.restart_pause_requested()
        assert not finished.is_set() and not owner.restart_quiescent(lease)
        # Pause cannot erase active IO or executor accounting. A refused pause
        # reopens admission without pretending that this long read has exited.
        owner.resume_after_restart_refusal(lease)
        assert not owner.restart_pause_requested()
        lease = owner.pause_for_restart()
        assert not owner.restart_quiescent(lease)
        release.set()
        assert finished.wait(3)
        deadline = time.monotonic() + 2
        while not owner.restart_quiescent(lease) and time.monotonic() < deadline:
            time.sleep(.01)
        assert owner.restart_quiescent(lease)
        assert result[0]["reason"] == "scheduler_pause" and not h.submitted
        with h.factory() as db:
            assert db.query(Item).filter(Item.scanned_at.is_not(None)).count() == 1
            assert db.query(Item).count() == 3 and db.query(JobRun).count() == 0
        owner.resume_after_restart_refusal(lease)
        assert h.run()["scanned_count"] == 3
    finally:
        release.set()
        owner.shutdown(wait=True)


def test_production_registration_passes_owner_pause_to_audit_before_database_open(monkeypatch):
    pause = Event()
    jobs = {}
    class Owner:
        restart_pause_requested = staticmethod(pause.is_set)
        def add_job(self, function, **kwargs):
            jobs[kwargs["id"]] = (function, kwargs)
    monkeypatch.setattr(scheduler.settings, "enable_taiwan_intraday_bar_scheduler", True)
    assert scheduler.add_taiwan_intraday_bar_jobs(Owner())
    audit, options = jobs["taiwan_intraday_completed_coverage"]
    pause.set()
    def no_database():
        pytest.fail("paused audit must not open a database")
    assert audit(now=DAY, session_factory=no_database, **options["kwargs"]) == {
        "status": "skipped", "reason": "scheduler_pause"}

def test_due_dispatch_yields_between_durable_jobs_without_duplicate_admission(monkeypatch):
    # Scheduler work may resume later; a pause is not a cancellation of a
    # previously committed queue/dispatch command.
    pending = [SimpleNamespace(id=n, status="queued") for n in (1, 2, 3)]
    pause = Event()
    submitted = []

    class FakeQuery:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            assert value == 64
            return self

        def all(self):
            return [job for job in pending if job.status == "queued"]

    class FakeDB:
        def query(self, model):
            assert model is JobRun
            return FakeQuery()

    def fake_dispatch(db, job, now):
        assert now == DAY and job.status == "queued"
        submitted.append(job.id)
        job.status = "running"  # stand-in for an already committed admission
        if job.id == 1:
            pause.set()
        return True

    monkeypatch.setattr(demand, "_dispatch", fake_dispatch)
    monkeypatch.setattr(demand, "materialization_request",
        lambda job: {"consumer": "scheduler", "expires_at": (DAY + timedelta(minutes=5)).isoformat()})

    db = FakeDB()
    assert demand.dispatch_due_materializations(db, requested_at=DAY, should_yield=pause.is_set) == 1
    assert submitted == [1]
    assert [job.id for job in pending if job.status == "queued"] == [2, 3]
    assert demand.dispatch_due_materializations(db, requested_at=DAY, should_yield=pause.is_set) == 0

    pause.clear()
    assert demand.dispatch_due_materializations(db, requested_at=DAY, should_yield=pause.is_set) == 2
    assert submitted == [1, 2, 3]


def test_completed_audit_skips_work_after_due_dispatch_requests_pause(monkeypatch):
    pause = Event()
    visited = []

    class Factory:
        def __enter__(self):
            visited.append("session_enter")
            return object()

        def __exit__(self, *_):
            visited.append("session_exit")

    def dispatched(db, *, requested_at, should_yield):
        assert requested_at == DAY and not should_yield()
        pause.set()  # simulate owner cooperative pause after a safe boundary
        visited.append("dispatch")
        assert should_yield()
        return 1

    def audit(*args, **kwargs):
        pytest.fail("audit must not run after the scheduler requests pause")

    monkeypatch.setattr(scheduler, "dispatch_due_materializations", dispatched)
    monkeypatch.setattr(scheduler, "audit_completed_sessions", audit)
    partial = scheduler.audit_completed_taiwan_intraday_coverage(
        now=DAY, session_factory=Factory, should_pause=pause.is_set)
    assert partial == {"status": "partial", "reason": "scheduler_pause",
                       "coverage_scan_complete": False, "lifecycle_complete": False,
                       "data_complete": False, "repair_complete": False}
    assert visited == ["session_enter", "dispatch", "session_exit"]
