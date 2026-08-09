from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    DispatchDelivery,
    DispatchSchedule,
    DispatchScheduleRun,
    JobRun,
)
from app.dispatch import schedule_runs, service
from app.dispatch.schemas import DispatchRecipientGroupCreate, DispatchScheduleCreate
from app.jobs import service as job_service


UTC = timezone.utc


def _queued_manual_run(db: Session) -> DispatchScheduleRun:
    group = service.create_recipient_group(
        db,
        DispatchRecipientGroupCreate(name="recovery recipients", emails=["recover@example.com"]),
    )
    created = service.create_schedule(
        db,
        DispatchScheduleCreate(
            name="recovery schedule",
            recipient_group_id=group["id"],
            template_key="market_overview",
            scope_type="market",
            scope_id="tw",
        ),
    )
    schedule = db.get(DispatchSchedule, created["id"])
    assert schedule is not None
    run = schedule_runs.create_manual_run(
        db,
        schedule=schedule,
        now=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
    )
    with patch.object(job_service, "submit_job_task"):
        result = service.process_schedule_run(db, run_id=run.id)
    queued = schedule_runs.get_schedule_run(db, result["run"]["id"])
    assert queued.status == "queued"
    return queued


def test_reconciliation_reuses_delivery_after_worker_handoff_interruption() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        run = _queued_manual_run(db)
        assert run.job_run_id is not None
        first_job_id = run.job_run_id
        job_service.fail_job(db, first_job_id, error_message="interrupted")
        run = schedule_runs.get_schedule_run(db, run.id)
        run.updated_at = (now - timedelta(minutes=10)).replace(tzinfo=None)
        db.commit()

        with patch.object(job_service, "submit_job_task") as submit:
            result = service.reconcile_schedule_runs(db, now=now)

        db.refresh(run)
        delivery_count = db.query(DispatchDelivery).count()
        job_count = db.query(JobRun).count()

        assert result["recovered_count"] == 1
        assert delivery_count == 1
        assert job_count == 2
        assert run.status == "queued"
        assert run.job_run_id != first_job_id
        submit.assert_called_once()
    engine.dispose()


def test_reconciliation_marks_stale_sending_result_unknown_without_retry() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        run = _queued_manual_run(db)
        delivery = db.get(DispatchDelivery, run.delivery_id)
        assert delivery is not None
        run.status = "sending"
        run.sending_at = (now - timedelta(minutes=10)).replace(tzinfo=None)
        run.updated_at = (now - timedelta(minutes=10)).replace(tzinfo=None)
        delivery.status = "sending"
        delivery.updated_at = (now - timedelta(minutes=10)).replace(tzinfo=None)
        db.commit()

        with patch.object(job_service, "submit_job_task") as submit:
            result = service.reconcile_schedule_runs(db, now=now)

        db.refresh(run)
        db.refresh(delivery)

        assert result["unknown_count"] == 1
        assert run.status == "error"
        assert run.error_code == "DELIVERY_RESULT_UNKNOWN_AFTER_RESTART"
        assert run.retryable is False
        assert delivery.status == "unknown"
        assert db.query(DispatchDelivery).count() == 1
        submit.assert_not_called()
    engine.dispose()
