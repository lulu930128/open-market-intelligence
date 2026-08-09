from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DispatchSchedule, DispatchScheduleRun, utc_now
from app.dispatch.readiness import evaluate_dispatch_readiness
from app.dispatch.schedule_time import (
    compute_next_run_at,
    ensure_utc,
    scheduled_slot_key,
    utc_db_value,
)


RUN_CONTRACT_VERSION = "omi.dispatch.schedule-run.v2"
TERMINAL_RUN_STATUSES = {"success", "skipped", "error", "cancelled"}


class DispatchScheduleRunNotFoundError(Exception):
    pass


class DispatchScheduleRunValidationError(Exception):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def schedule_snapshot(schedule: DispatchSchedule) -> dict[str, Any]:
    request = _from_json(schedule.request_json)
    recipient_group = schedule.recipient_group
    recipients = _from_json(recipient_group.emails_json) if recipient_group else []
    return {
        "contract_version": RUN_CONTRACT_VERSION,
        "schedule_id": schedule.id,
        "schedule_name": schedule.name,
        "recipient_group": {
            "id": schedule.recipient_group_id,
            "name": recipient_group.name if recipient_group else None,
            "enabled": recipient_group.enabled if recipient_group else False,
            "recipients": recipients if isinstance(recipients, list) else [],
        },
        "timing": {
            "send_time": schedule.send_time,
            "day_of_week": schedule.day_of_week,
            "timezone": schedule.timezone,
            "calendar_mode": schedule.calendar_mode,
            "catchup_mode": schedule.catchup_mode,
            "misfire_policy": schedule.misfire_policy,
            "misfire_grace_minutes": schedule.misfire_grace_minutes,
        },
        "readiness": {
            "profile": schedule.readiness_profile,
            "policy": schedule.readiness_policy,
            "deadline_minutes": schedule.readiness_deadline_minutes,
            "retry_interval_seconds": schedule.readiness_retry_interval_seconds,
        },
        "delivery": {
            "max_retries": schedule.max_retries,
            "retry_interval_seconds": schedule.retry_interval_seconds,
        },
        "template_key": schedule.template_key,
        "scope_type": schedule.scope_type,
        "scope_id": schedule.scope_id,
        "request": request if isinstance(request, dict) else {},
        "captured_at": utc_now(),
    }


def serialize_run(run: DispatchScheduleRun) -> dict[str, Any]:
    snapshot = _from_json(run.schedule_snapshot_json)
    if isinstance(snapshot, dict):
        snapshot = dict(snapshot)
        recipient_group = snapshot.get("recipient_group")
        if isinstance(recipient_group, dict):
            recipient_group = dict(recipient_group)
            recipients = recipient_group.pop("recipients", [])
            recipient_group["recipient_count"] = (
                len(recipients) if isinstance(recipients, list) else 0
            )
            snapshot["recipient_group"] = recipient_group
    readiness = _from_json(run.readiness_json)
    return {
        "id": run.id,
        "run_token": run.run_token,
        "schedule_id": run.schedule_id,
        "schedule_name": run.schedule.name if run.schedule else None,
        "retry_of_run_id": run.retry_of_run_id,
        "trigger_type": run.trigger_type,
        "scheduled_for": run.scheduled_for,
        "scheduled_slot_key": run.scheduled_slot_key,
        "status": run.status,
        "schedule_snapshot": snapshot if isinstance(snapshot, dict) else {},
        "readiness": readiness if isinstance(readiness, dict) else None,
        "readiness_check_count": run.readiness_check_count,
        "delivery_attempt_count": run.delivery_attempt_count,
        "max_delivery_attempts": run.max_delivery_attempts,
        "next_action_at": run.next_action_at,
        "retryable": run.retryable,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "delivery_id": run.delivery_id,
        "job_run_id": run.job_run_id,
        "claimed_at": run.claimed_at,
        "queued_at": run.queued_at,
        "sending_at": run.sending_at,
        "sent_at": run.sent_at,
        "skipped_at": run.skipped_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def get_schedule_run(db: Session, run_id: int) -> DispatchScheduleRun:
    run = db.query(DispatchScheduleRun).filter(DispatchScheduleRun.id == run_id).first()
    if run is None:
        raise DispatchScheduleRunNotFoundError(f"Dispatch schedule run id={run_id} not found.")
    return run


def list_schedule_runs(
    db: Session,
    *,
    schedule_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(DispatchScheduleRun)
    if schedule_id is not None:
        query = query.filter(DispatchScheduleRun.schedule_id == schedule_id)
    rows = (
        query.order_by(DispatchScheduleRun.created_at.desc(), DispatchScheduleRun.id.desc())
        .limit(max(min(int(limit), 200), 1))
        .all()
    )
    return [serialize_run(row) for row in rows]


def compute_schedule_next_run(
    schedule: DispatchSchedule,
    *,
    after: datetime,
    inclusive: bool = False,
) -> datetime | None:
    if not schedule.enabled or schedule.archived_at is not None:
        return None
    return compute_next_run_at(
        send_time=schedule.send_time,
        day_of_week=schedule.day_of_week,
        timezone_name=schedule.timezone,
        calendar_mode=schedule.calendar_mode,
        after=after,
        inclusive=inclusive,
    )


def initialize_next_runs(db: Session, *, now: datetime | None = None) -> int:
    current = ensure_utc(now or utc_now())
    schedules = (
        db.query(DispatchSchedule)
        .filter(
            DispatchSchedule.enabled.is_(True),
            DispatchSchedule.archived_at.is_(None),
            DispatchSchedule.next_run_at.is_(None),
        )
        .all()
    )
    for schedule in schedules:
        try:
            next_run = compute_schedule_next_run(schedule, after=current, inclusive=True)
            schedule.next_run_at = utc_db_value(next_run) if next_run else None
        except Exception as exc:
            schedule.enabled = False
            schedule.next_run_at = None
            schedule.last_status = "error"
            schedule.last_error_at = utc_now()
            schedule.last_error_message = f"Schedule initialization failed: {exc}"
        schedule.updated_at = utc_now()
    if schedules:
        db.commit()
    return len(schedules)


def _latest_due_slot(schedule: DispatchSchedule, *, now: datetime) -> tuple[datetime, datetime]:
    current = ensure_utc(schedule.next_run_at or now)
    if current < now - timedelta(days=370):
        current = compute_schedule_next_run(
            schedule,
            after=now - timedelta(days=370),
            inclusive=True,
        ) or current
    latest = current
    for _ in range(400):
        following = compute_schedule_next_run(schedule, after=latest)
        if following is None or following > now:
            return latest, following or now + timedelta(days=1)
        latest = following
    return latest, compute_schedule_next_run(schedule, after=now) or now + timedelta(days=1)


def _new_run(
    schedule: DispatchSchedule,
    *,
    scheduled_for: datetime,
    trigger_type: str,
    slot_key: str | None,
    retry_of_run_id: int | None = None,
) -> DispatchScheduleRun:
    now = utc_now()
    return DispatchScheduleRun(
        run_token=str(uuid4()),
        schedule_id=schedule.id,
        retry_of_run_id=retry_of_run_id,
        trigger_type=trigger_type,
        scheduled_for=utc_db_value(scheduled_for),
        scheduled_slot_key=slot_key,
        status="claimed",
        schedule_snapshot_json=_to_json(schedule_snapshot(schedule)),
        readiness_check_count=0,
        delivery_attempt_count=0,
        max_delivery_attempts=max(int(schedule.max_retries), 0) + 1,
        next_action_at=utc_db_value(now),
        retryable=False,
        claimed_at=now,
    )


def claim_due_schedule_runs(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    current = ensure_utc(now or utc_now())
    claim_limit = max(int(limit or settings.scheduler_dispatch_claim_limit), 1)
    initialize_next_runs(db, now=current)
    schedules = (
        db.query(DispatchSchedule)
        .filter(
            DispatchSchedule.enabled.is_(True),
            DispatchSchedule.archived_at.is_(None),
            DispatchSchedule.next_run_at.isnot(None),
            DispatchSchedule.next_run_at <= utc_db_value(current),
        )
        .order_by(DispatchSchedule.next_run_at.asc(), DispatchSchedule.id.asc())
        .limit(claim_limit)
        .all()
    )
    claimed: list[int] = []
    skipped: list[int] = []
    conflicts = 0
    errors: list[dict[str, Any]] = []

    for listed_schedule in schedules:
        schedule = db.query(DispatchSchedule).filter(DispatchSchedule.id == listed_schedule.id).first()
        if schedule is None or schedule.next_run_at is None:
            continue
        first_due = ensure_utc(schedule.next_run_at)
        if first_due > current:
            continue

        slots: list[tuple[datetime, datetime]] = []
        try:
            if schedule.catchup_mode == "all_slots":
                candidate = first_due
                while (
                    candidate <= current
                    and len(slots) < claim_limit - len(claimed) - len(skipped)
                ):
                    following = compute_schedule_next_run(schedule, after=candidate)
                    if following is None:
                        break
                    slots.append((candidate, following))
                    candidate = following
            else:
                slots.append(_latest_due_slot(schedule, now=current))
        except Exception as exc:
            schedule.enabled = False
            schedule.next_run_at = None
            schedule.last_status = "error"
            schedule.last_error_at = utc_now()
            schedule.last_error_message = f"Schedule claim failed: {exc}"
            schedule.updated_at = utc_now()
            db.commit()
            errors.append({"schedule_id": schedule.id, "error_message": str(exc)})
            continue

        for slot, following in slots:
            lateness_minutes = max((current - slot).total_seconds() / 60, 0)
            should_skip = (
                schedule.misfire_policy == "skip"
                and lateness_minutes > max(int(schedule.misfire_grace_minutes), 0)
            )
            run = _new_run(
                schedule,
                scheduled_for=slot,
                trigger_type="scheduled",
                slot_key=scheduled_slot_key(slot),
            )
            if should_skip:
                run.status = "skipped"
                run.retryable = False
                run.error_code = "MISFIRE_GRACE_EXCEEDED"
                run.error_message = "Scheduled slot exceeded the configured misfire grace window."
                run.next_action_at = None
                run.skipped_at = utc_now()
                schedule.last_skipped_at = utc_now()
                schedule.last_status = "skipped"
            schedule.next_run_at = utc_db_value(following)
            schedule.updated_at = utc_now()
            db.add(run)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                conflicts += 1
                continue
            db.refresh(run)
            if should_skip:
                skipped.append(run.id)
            else:
                claimed.append(run.id)
            if len(claimed) + len(skipped) >= claim_limit:
                break
        if len(claimed) + len(skipped) >= claim_limit:
            break

    return {
        "status": "success",
        "checked_count": len(schedules),
        "claimed_count": len(claimed),
        "skipped_count": len(skipped),
        "conflict_count": conflicts,
        "error_count": len(errors),
        "claimed_run_ids": claimed,
        "skipped_run_ids": skipped,
        "errors": errors,
    }


def create_manual_run(
    db: Session,
    *,
    schedule: DispatchSchedule,
    trigger_type: str = "manual",
    retry_of_run_id: int | None = None,
    force_immediate: bool = False,
    now: datetime | None = None,
) -> DispatchScheduleRun:
    if schedule.archived_at is not None:
        raise DispatchScheduleRunValidationError("Archived dispatch schedules cannot be run.")
    current = ensure_utc(now or utc_now())
    run = _new_run(
        schedule,
        scheduled_for=current,
        trigger_type=trigger_type,
        slot_key=None,
        retry_of_run_id=retry_of_run_id,
    )
    if force_immediate:
        snapshot = _from_json(run.schedule_snapshot_json)
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        readiness = snapshot.get("readiness")
        readiness = readiness if isinstance(readiness, dict) else {}
        readiness["policy"] = "immediate"
        snapshot["readiness"] = readiness
        snapshot["manual_policy_override"] = "immediate"
        run.schedule_snapshot_json = _to_json(snapshot)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def evaluate_run_readiness(
    db: Session,
    *,
    run_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    run = get_schedule_run(db, run_id)
    if run.status not in {"claimed", "waiting_data"}:
        return {"action": "none", "run": serialize_run(run)}
    snapshot = _from_json(run.schedule_snapshot_json)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    readiness_config = snapshot.get("readiness")
    readiness_config = readiness_config if isinstance(readiness_config, dict) else {}
    result = evaluate_dispatch_readiness(
        db,
        profile=str(readiness_config.get("profile") or "generic"),
        policy=str(readiness_config.get("policy") or "immediate"),
        scheduled_for=ensure_utc(run.scheduled_for),
        deadline_minutes=int(readiness_config.get("deadline_minutes") or 0),
        retry_interval_seconds=int(readiness_config.get("retry_interval_seconds") or 300),
        now=now,
    )
    run.readiness_json = _to_json(result)
    run.readiness_check_count += 1
    current = ensure_utc(now or utc_now())
    policy = str(readiness_config.get("policy") or "immediate")
    deadline = ensure_utc(run.scheduled_for) + timedelta(
        minutes=max(int(readiness_config.get("deadline_minutes") or 0), 0)
    )

    if result.get("ready") is True or policy == "immediate":
        run.status = "claimed"
        run.next_action_at = utc_db_value(current)
        run.retryable = False
        run.error_code = None
        run.error_message = None
        action = "queue"
    elif policy == "wait_until_ready" and result.get("retryable") and current < deadline:
        run.status = "waiting_data"
        run.next_action_at = utc_db_value(
            current + timedelta(seconds=max(int(readiness_config.get("retry_interval_seconds") or 300), 10))
        )
        run.retryable = True
        run.error_code = str(result.get("reason_code") or "READINESS_PENDING")
        run.error_message = str(result.get("reason_message") or "Required data is not ready.")
        action = "wait"
    else:
        run.status = "skipped"
        run.next_action_at = None
        run.retryable = False
        run.error_code = str(result.get("reason_code") or "READINESS_INCOMPLETE")
        run.error_message = str(result.get("reason_message") or "Required data is incomplete.")
        run.skipped_at = utc_now()
        if run.trigger_type == "scheduled":
            run.schedule.last_skipped_at = utc_now()
            run.schedule.last_status = "skipped"
            run.schedule.last_error_at = utc_now()
            run.schedule.last_error_message = run.error_message
        action = "skip"
    run.updated_at = utc_now()
    db.commit()
    db.refresh(run)
    return {"action": action, "run": serialize_run(run)}


def retry_schedule_run(db: Session, *, run_id: int) -> DispatchScheduleRun:
    source = get_schedule_run(db, run_id)
    if source.status not in TERMINAL_RUN_STATUSES or not source.retryable:
        raise DispatchScheduleRunValidationError(
            f"Dispatch schedule run id={run_id} is not retryable."
        )
    return create_manual_run(
        db,
        schedule=source.schedule,
        trigger_type="manual_retry",
        retry_of_run_id=source.id,
    )


__all__ = [
    "DispatchScheduleRunNotFoundError",
    "DispatchScheduleRunValidationError",
    "RUN_CONTRACT_VERSION",
    "TERMINAL_RUN_STATUSES",
    "claim_due_schedule_runs",
    "compute_schedule_next_run",
    "create_manual_run",
    "evaluate_run_readiness",
    "get_schedule_run",
    "initialize_next_runs",
    "list_schedule_runs",
    "retry_schedule_run",
    "schedule_snapshot",
    "serialize_run",
]
