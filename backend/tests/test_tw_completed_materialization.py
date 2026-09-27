"""Normal completed-session ingestion, residual handoff and lane isolation."""
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
