from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, DispatchSchedule, DispatchScheduleRun
from app.dispatch import schedule_runs, service
from app.dispatch.schemas import DispatchRecipientGroupCreate, DispatchScheduleCreate


UTC = timezone.utc


def _create_schedule(db: Session, **overrides):
    group = service.create_recipient_group(
        db,
        DispatchRecipientGroupCreate(
            name=f"recipients-{overrides.get('name', 'schedule')}",
            emails=["dispatch@example.com"],
        ),
    )
    values = {
        "name": "schedule",
        "recipient_group_id": group["id"],
        "send_time": "08:55",
        "day_of_week": "daily",
        "timezone": "Asia/Taipei",
        "calendar_mode": "calendar_days",
        "template_key": "market_overview",
        "scope_type": "market",
        "scope_id": "tw",
    }
    values.update(overrides)
    return service.create_schedule(db, DispatchScheduleCreate(**values))


def test_concurrent_claim_creates_only_one_run_for_a_slot() -> None:
    database_path = Path.cwd() / ".tmp" / f"dispatch-claim-{uuid4().hex}.db"
    try:
        engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"timeout": 10},
        )
        Base.metadata.create_all(engine)
        due_at = datetime(2026, 7, 1, 0, 55, tzinfo=UTC)
        with Session(engine) as db:
            schedule_read = _create_schedule(db)
            schedule = db.get(DispatchSchedule, schedule_read["id"])
            assert schedule is not None
            schedule.next_run_at = due_at.replace(tzinfo=None)
            db.commit()

        barrier = Barrier(2)

        def claim() -> dict:
            with Session(engine) as db:
                barrier.wait(timeout=5)
                return schedule_runs.claim_due_schedule_runs(db, now=due_at, limit=10)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: claim(), range(2)))

        with Session(engine) as db:
            runs = db.query(DispatchScheduleRun).all()
        engine.dispose()

        assert len(runs) == 1
        assert runs[0].scheduled_slot_key == "2026-07-01T00:55:00Z"
        assert sum(result["claimed_count"] for result in results) == 1
    finally:
        database_path.unlink(missing_ok=True)


def test_latest_only_coalesces_missed_slots_and_advances_to_future() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 10, 1, 0, tzinfo=UTC)
    with Session(engine) as db:
        schedule_read = _create_schedule(db, name="coalesced")
        schedule = db.get(DispatchSchedule, schedule_read["id"])
        assert schedule is not None
        schedule.next_run_at = datetime(2026, 7, 1, 0, 55)
        db.commit()

        result = schedule_runs.claim_due_schedule_runs(db, now=now, limit=10)
        db.refresh(schedule)
        runs = db.query(DispatchScheduleRun).all()

        assert result["claimed_count"] == 1
        assert len(runs) == 1
        assert runs[0].scheduled_slot_key == "2026-07-10T00:55:00Z"
        assert schedule.next_run_at == datetime(2026, 7, 11, 0, 55)
    engine.dispose()


def test_misfire_skip_is_visible_and_not_retryable() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    due_at = datetime(2026, 7, 1, 0, 55, tzinfo=UTC)
    with Session(engine) as db:
        schedule_read = _create_schedule(
            db,
            name="skip",
            misfire_policy="skip",
            misfire_grace_minutes=1,
        )
        schedule = db.get(DispatchSchedule, schedule_read["id"])
        assert schedule is not None
        schedule.next_run_at = due_at.replace(tzinfo=None)
        db.commit()

        result = schedule_runs.claim_due_schedule_runs(
            db,
            now=datetime(2026, 7, 1, 1, 5, tzinfo=UTC),
        )
        run = db.query(DispatchScheduleRun).one()

        assert result["skipped_count"] == 1
        assert run.status == "skipped"
        assert run.error_code == "MISFIRE_GRACE_EXCEEDED"
        assert run.retryable is False
    engine.dispose()


def test_manual_run_does_not_consume_next_scheduled_slot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        schedule_read = _create_schedule(db, name="manual")
        schedule = db.get(DispatchSchedule, schedule_read["id"])
        assert schedule is not None
        original_next_run_at = schedule.next_run_at

        run = schedule_runs.create_manual_run(
            db,
            schedule=schedule,
            now=datetime(2026, 7, 1, 0, 30, tzinfo=UTC),
        )
        db.refresh(schedule)
        serialized = schedule_runs.serialize_run(run)

        assert run.trigger_type == "manual"
        assert run.scheduled_slot_key is None
        assert schedule.next_run_at == original_next_run_at
        assert schedule.last_status == "never_run"
        assert "recipients" not in serialized["schedule_snapshot"]["recipient_group"]
        assert serialized["schedule_snapshot"]["recipient_group"]["recipient_count"] == 1
    engine.dispose()


def test_invalid_legacy_schedule_is_disabled_without_blocking_initialization() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        schedule_read = _create_schedule(db, name="invalid-timezone")
        schedule = db.get(DispatchSchedule, schedule_read["id"])
        assert schedule is not None
        schedule.timezone = "Invalid/Timezone"
        schedule.next_run_at = None
        db.commit()

        initialized = schedule_runs.initialize_next_runs(
            db,
            now=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
        db.refresh(schedule)

        assert initialized == 1
        assert schedule.enabled is False
        assert schedule.last_status == "error"
        assert "initialization failed" in (schedule.last_error_message or "").lower()
    engine.dispose()
