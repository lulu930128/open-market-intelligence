from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import make_msgid, parseaddr
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    DispatchDelivery,
    DispatchRecipientGroup,
    DispatchSchedule,
    DispatchScheduleRun,
    utc_now,
)
from app.dispatch import templates
from app.dispatch.mail_sender import SmtpMailSender
from app.dispatch.schedule_time import utc_db_value
from app.dispatch.schemas import (
    DispatchPreviewRequest,
    DispatchRecipientGroupCreate,
    DispatchRecipientGroupUpdate,
    DispatchScheduleCreate,
    DispatchScheduleUpdate,
    DispatchSendRequest,
)
from app.jobs import service as job_service


class DispatchError(Exception):
    pass


class DispatchRecipientGroupNotFoundError(DispatchError):
    pass


class DispatchDeliveryNotFoundError(DispatchError):
    pass


class DispatchValidationError(DispatchError):
    pass


class DispatchScheduleNotFoundError(DispatchError):
    pass


PREVIEW_REQUEST_FIELDS = (
    "template_key",
    "scope_type",
    "scope_id",
    "strategy_profile",
    "rank_by",
    "sort_order",
    "include_radar",
    "radar_group_id",
    "radar_mode",
    "content_depth",
    "radar_limit",
)
WEEKDAY_INDEXES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
DAY_OF_WEEK_ALIASES = {
    "*": "daily",
    "all": "daily",
    "everyday": "daily",
    "daily": "daily",
    "weekday": "mon-fri",
    "weekdays": "mon-fri",
    "workday": "mon-fri",
    "workdays": "mon-fri",
    "weekend": "sat,sun",
    "weekends": "sat,sun",
}


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _preview_request_dict(payload: DispatchPreviewRequest) -> dict[str, Any]:
    return {field: getattr(payload, field) for field in PREVIEW_REQUEST_FIELDS}


def _preview_request_from_data(data: dict[str, Any]) -> DispatchPreviewRequest:
    return DispatchPreviewRequest(
        **{field: data.get(field) for field in PREVIEW_REQUEST_FIELDS if field in data}
    )


def _normalize_send_time(value: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":", maxsplit=1)
    if len(parts) != 2:
        raise DispatchValidationError("send_time must use HH:MM format.")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise DispatchValidationError("send_time must use HH:MM format.") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise DispatchValidationError("send_time must be within a 24-hour clock.")

    return f"{hour:02d}:{minute:02d}"


def _weekday_token_range(token: str) -> set[int]:
    if "-" not in token:
        if token not in WEEKDAY_INDEXES:
            raise DispatchValidationError(f"Unsupported day_of_week token: {token}")
        return {WEEKDAY_INDEXES[token]}

    start, end = token.split("-", maxsplit=1)
    if start not in WEEKDAY_INDEXES or end not in WEEKDAY_INDEXES:
        raise DispatchValidationError(f"Unsupported day_of_week range: {token}")

    start_index = WEEKDAY_INDEXES[start]
    end_index = WEEKDAY_INDEXES[end]
    if start_index <= end_index:
        return set(range(start_index, end_index + 1))

    return {*range(start_index, 7), *range(0, end_index + 1)}


def _normalize_day_of_week(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    text = DAY_OF_WEEK_ALIASES.get(text, text)
    if not text:
        raise DispatchValidationError("day_of_week is required.")
    if text == "daily":
        return text

    tokens = [token for token in text.split(",") if token]
    if not tokens:
        raise DispatchValidationError("day_of_week is required.")

    for token in tokens:
        _weekday_token_range(token)

    return ",".join(tokens)


def _weekday_matches(day_of_week: str, weekday: int) -> bool:
    normalized = _normalize_day_of_week(day_of_week)
    if normalized == "daily":
        return True

    return any(weekday in _weekday_token_range(token) for token in normalized.split(","))


def _normalize_timezone(value: str | None) -> str:
    timezone_name = str(value or settings.timezone).strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DispatchValidationError(f"Unsupported timezone: {timezone_name}") from exc
    return timezone_name


def _local_now_for_schedule(schedule: DispatchSchedule, now: datetime | None = None) -> datetime:
    timezone_value = ZoneInfo(schedule.timezone or settings.timezone)
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("UTC"))
    return current.astimezone(timezone_value)


def _run_key_for_schedule(schedule: DispatchSchedule, now: datetime) -> str:
    local_now = _local_now_for_schedule(schedule, now)
    return f"{local_now.date().isoformat()} {schedule.send_time} {schedule.timezone}"


def _schedule_is_due(schedule: DispatchSchedule, now: datetime | None = None) -> tuple[bool, str | None]:
    if not schedule.enabled:
        return False, None

    local_now = _local_now_for_schedule(schedule, now)
    send_time = _normalize_send_time(schedule.send_time)
    if local_now.strftime("%H:%M") != send_time:
        return False, None

    if not _weekday_matches(schedule.day_of_week, local_now.weekday()):
        return False, None

    run_key = _run_key_for_schedule(schedule, local_now)
    if schedule.last_run_key == run_key:
        return False, run_key

    return True, run_key


def _validate_preview_request(payload: DispatchPreviewRequest) -> None:
    if payload.template_key == "market_overview":
        market = _normalize_market_scope(payload.scope_id)
        if payload.include_radar:
            if market != "tw":
                raise DispatchValidationError(
                    "Market overview radar dispatch currently supports Taiwan watchlists only."
                )
            if payload.radar_group_id is None:
                raise DispatchValidationError(
                    "radar_group_id is required when include_radar is true."
                )
        return

    if payload.template_key == "watchlist_brief":
        if payload.scope_type != "watchlist":
            raise DispatchValidationError("scope_type must be watchlist for watchlist dispatch previews.")
        if payload.scope_id is None:
            raise DispatchValidationError("scope_id is required for watchlist dispatch previews.")
        return

    raise DispatchValidationError(f"Unsupported dispatch template: {payload.template_key}")


def normalize_emails(emails: list[str]) -> list[str]:
    normalized: list[str] = []
    invalid: list[str] = []
    for raw in emails:
        text = str(raw or "").strip()
        if not text:
            continue
        _name, address = parseaddr(text)
        address = address.strip().lower()
        if "@" not in address or "." not in address.rsplit("@", maxsplit=1)[-1]:
            invalid.append(text)
            continue
        if address not in normalized:
            normalized.append(address)

    if invalid:
        raise DispatchValidationError(f"Invalid email address: {', '.join(invalid[:3])}")
    if not normalized:
        raise DispatchValidationError("At least one recipient email is required.")
    return normalized


def serialize_recipient_group(group: DispatchRecipientGroup) -> dict[str, Any]:
    emails = _from_json(group.emails_json)
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "emails": emails if isinstance(emails, list) else [],
        "enabled": group.enabled,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def serialize_delivery(delivery: DispatchDelivery) -> dict[str, Any]:
    recipients = _from_json(delivery.recipients_json)
    preview = _from_json(delivery.preview_json)
    request = _from_json(delivery.request_json)
    result = _from_json(delivery.result_json)
    return {
        "id": delivery.id,
        "job_run_id": delivery.job_run_id,
        "recipient_group_id": delivery.recipient_group_id,
        "recipient_group_name": delivery.recipient_group.name if delivery.recipient_group else None,
        "template_key": delivery.template_key,
        "scope_type": delivery.scope_type,
        "scope_id": delivery.scope_id,
        "subject": delivery.subject,
        "status": delivery.status,
        "recipient_count": delivery.recipient_count,
        "recipients": recipients if isinstance(recipients, list) else [],
        "body_text": delivery.body_text or "",
        "body_html": delivery.body_html or "",
        "preview": preview if isinstance(preview, dict) else {},
        "request": request if isinstance(request, dict) else {},
        "result": result if isinstance(result, dict) else None,
        "error_message": delivery.error_message,
        "message_id": delivery.message_id,
        "sent_at": delivery.sent_at,
        "created_at": delivery.created_at,
        "updated_at": delivery.updated_at,
    }


def serialize_schedule(schedule: DispatchSchedule) -> dict[str, Any]:
    request = _from_json(schedule.request_json)
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "recipient_group_id": schedule.recipient_group_id,
        "recipient_group_name": schedule.recipient_group.name if schedule.recipient_group else None,
        "enabled": schedule.enabled,
        "send_time": schedule.send_time,
        "day_of_week": schedule.day_of_week,
        "timezone": schedule.timezone,
        "template_key": schedule.template_key,
        "scope_type": schedule.scope_type,
        "scope_id": schedule.scope_id,
        "request": request if isinstance(request, dict) else {},
        "next_run_at": schedule.next_run_at,
        "calendar_mode": schedule.calendar_mode,
        "catchup_mode": schedule.catchup_mode,
        "misfire_policy": schedule.misfire_policy,
        "misfire_grace_minutes": schedule.misfire_grace_minutes,
        "max_retries": schedule.max_retries,
        "retry_interval_seconds": schedule.retry_interval_seconds,
        "readiness_profile": schedule.readiness_profile,
        "readiness_policy": schedule.readiness_policy,
        "readiness_deadline_minutes": schedule.readiness_deadline_minutes,
        "readiness_retry_interval_seconds": schedule.readiness_retry_interval_seconds,
        "last_queued_at": schedule.last_queued_at,
        "last_sent_at": schedule.last_sent_at,
        "last_skipped_at": schedule.last_skipped_at,
        "last_status": schedule.last_status,
        "archived_at": schedule.archived_at,
        "last_run_key": schedule.last_run_key,
        "last_run_at": schedule.last_run_at,
        "last_success_at": schedule.last_success_at,
        "last_error_at": schedule.last_error_at,
        "last_error_message": schedule.last_error_message,
        "last_delivery_id": schedule.last_delivery_id,
        "last_job_run_id": schedule.last_job_run_id,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def list_recipient_groups(db: Session, *, enabled: bool | None = None) -> list[dict[str, Any]]:
    query = db.query(DispatchRecipientGroup)
    if enabled is not None:
        query = query.filter(DispatchRecipientGroup.enabled.is_(enabled))
    groups = query.order_by(DispatchRecipientGroup.name.asc(), DispatchRecipientGroup.id.asc()).all()
    return [serialize_recipient_group(group) for group in groups]


def get_recipient_group(db: Session, group_id: int) -> DispatchRecipientGroup:
    group = db.query(DispatchRecipientGroup).filter(DispatchRecipientGroup.id == group_id).first()
    if group is None:
        raise DispatchRecipientGroupNotFoundError(f"Recipient group id={group_id} not found.")
    return group


def create_recipient_group(db: Session, payload: DispatchRecipientGroupCreate) -> dict[str, Any]:
    group = DispatchRecipientGroup(
        name=payload.name.strip(),
        description=payload.description,
        emails_json=_to_json(normalize_emails(payload.emails)) or "[]",
        enabled=payload.enabled,
    )
    db.add(group)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DispatchValidationError(f"Recipient group name already exists: {payload.name}") from exc
    db.refresh(group)
    return serialize_recipient_group(group)


def update_recipient_group(
    db: Session,
    group_id: int,
    payload: DispatchRecipientGroupUpdate,
) -> dict[str, Any]:
    group = get_recipient_group(db, group_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        group.name = str(update_data["name"]).strip()
    if "description" in update_data:
        group.description = update_data["description"]
    if "emails" in update_data and update_data["emails"] is not None:
        group.emails_json = _to_json(normalize_emails(update_data["emails"])) or "[]"
    if "enabled" in update_data and update_data["enabled"] is not None:
        group.enabled = bool(update_data["enabled"])
    group.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DispatchValidationError(f"Recipient group name already exists: {group.name}") from exc
    db.refresh(group)
    return serialize_recipient_group(group)


def delete_recipient_group(db: Session, group_id: int) -> dict[str, Any]:
    group = get_recipient_group(db, group_id)
    (
        db.query(DispatchDelivery)
        .filter(DispatchDelivery.recipient_group_id == group_id)
        .update({DispatchDelivery.recipient_group_id: None}, synchronize_session=False)
    )
    (
        db.query(DispatchSchedule)
        .filter(DispatchSchedule.recipient_group_id == group_id)
        .update(
            {
                DispatchSchedule.recipient_group_id: None,
                DispatchSchedule.enabled: False,
                DispatchSchedule.next_run_at: None,
                DispatchSchedule.last_status: "error",
                DispatchSchedule.last_error_message: "Recipient group was deleted.",
                DispatchSchedule.updated_at: utc_now(),
            },
            synchronize_session=False,
        )
    )
    db.delete(group)
    db.commit()
    return {"id": group_id, "deleted": True}


def _normalize_market_scope(scope_id: str | int | None) -> str:
    raw = str(scope_id or "tw").strip().lower()
    aliases = {
        "tw": "tw",
        "taiwan": "tw",
        "台股": "tw",
        "us": "us",
        "usa": "us",
        "united_states": "us",
        "美股": "us",
    }
    market = aliases.get(raw)
    if market is None:
        raise DispatchValidationError(f"Unsupported market dispatch scope: {scope_id}")
    return market


def build_preview(db: Session, payload: DispatchPreviewRequest) -> dict[str, Any]:
    _validate_preview_request(payload)

    if payload.template_key == "market_overview":
        market = _normalize_market_scope(payload.scope_id)
        return templates.build_market_overview_preview(
            db,
            market=market,
            include_radar=payload.include_radar,
            radar_group_id=payload.radar_group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=payload.radar_mode,
            content_depth=payload.content_depth,
            radar_limit=payload.radar_limit,
        )

    if payload.template_key == "watchlist_brief":
        return templates.build_watchlist_brief_preview(
            db,
            group_id=int(payload.scope_id),
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=payload.radar_mode,
            content_depth=payload.content_depth,
            radar_limit=payload.radar_limit,
        )

    raise DispatchValidationError(f"Unsupported dispatch template: {payload.template_key}")


def queue_delivery(db: Session, payload: DispatchSendRequest) -> dict[str, Any]:
    from app.dispatch.tasks import run_dispatch_delivery_job

    recipient_group = get_recipient_group(db=db, group_id=payload.recipient_group_id)
    preview = build_preview(db=db, payload=payload)
    delivery = create_delivery(
        db=db,
        payload=payload,
        preview=preview,
        recipient_group=recipient_group,
    )
    job, _created = job_service.enqueue_job(
        db=db,
        job_type="dispatch.mail_delivery",
        target=str(delivery.id),
        request={"delivery_id": delivery.id, **payload.model_dump()},
        progress_total=1,
        message="Queued mail dispatch.",
        task=run_dispatch_delivery_job,
        task_args=(delivery.id,),
        dedupe_active=False,
    )
    delivery_read = attach_job_to_delivery(
        db=db,
        delivery_id=delivery.id,
        job_run_id=job.id,
    )
    return {
        "job": job_service.serialize_job(job),
        "delivery": delivery_read,
    }


def create_delivery(
    db: Session,
    *,
    payload: DispatchSendRequest,
    preview: dict[str, Any],
    recipient_group: DispatchRecipientGroup | None,
    recipients_override: list[str] | None = None,
    commit: bool = True,
) -> DispatchDelivery:
    if recipient_group is not None and not recipient_group.enabled and recipients_override is None:
        raise DispatchValidationError(f"Recipient group is disabled: {recipient_group.name}")
    recipients = normalize_emails(
        recipients_override
        if recipients_override is not None
        else _from_json(recipient_group.emails_json if recipient_group else None) or []
    )
    delivery = DispatchDelivery(
        recipient_group_id=recipient_group.id if recipient_group else None,
        template_key=str(preview["template_key"]),
        scope_type=str(preview["scope_type"]),
        scope_id=preview.get("scope_id"),
        subject=str(preview["subject"]),
        status="queued",
        recipient_count=len(recipients),
        recipients_json=_to_json(recipients),
        body_text=str(preview["body_text"]),
        body_html=str(preview["body_html"]),
        preview_json=_to_json(preview),
        request_json=_to_json(payload.model_dump()),
    )
    db.add(delivery)
    db.flush()
    delivery.message_id = make_msgid(
        idstring=f"omi-dispatch-{delivery.id}",
        domain="omi.local",
    )
    if commit:
        db.commit()
        db.refresh(delivery)
    return delivery


def get_delivery(db: Session, delivery_id: int) -> DispatchDelivery:
    delivery = db.query(DispatchDelivery).filter(DispatchDelivery.id == delivery_id).first()
    if delivery is None:
        raise DispatchDeliveryNotFoundError(f"Dispatch delivery id={delivery_id} not found.")
    return delivery


def list_deliveries(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        db.query(DispatchDelivery)
        .order_by(DispatchDelivery.created_at.desc(), DispatchDelivery.id.desc())
        .limit(max(min(limit, 100), 1))
        .all()
    )
    return [serialize_delivery(row) for row in rows]


def attach_job_to_delivery(db: Session, *, delivery_id: int, job_run_id: int) -> dict[str, Any]:
    delivery = get_delivery(db, delivery_id)
    delivery.job_run_id = job_run_id
    delivery.updated_at = utc_now()
    db.commit()
    db.refresh(delivery)
    return serialize_delivery(delivery)


def send_delivery(
    db: Session,
    delivery_id: int,
    *,
    schedule_run_id: int | None = None,
) -> dict[str, Any]:
    delivery = get_delivery(db, delivery_id)
    if delivery.status == "success":
        return serialize_delivery(delivery)
    run = (
        db.query(DispatchScheduleRun)
        .filter(DispatchScheduleRun.id == schedule_run_id)
        .first()
        if schedule_run_id is not None
        else db.query(DispatchScheduleRun)
        .filter(DispatchScheduleRun.delivery_id == delivery_id)
        .first()
    )
    recipients = _from_json(delivery.recipients_json)
    recipient_list = recipients if isinstance(recipients, list) else []

    try:
        sender = SmtpMailSender.from_settings()
    except Exception as exc:
        delivery.status = "error"
        delivery.error_message = str(exc)
        delivery.result_json = _to_json(
            {
                "status": "error",
                "error_code": "SMTP_CONFIGURATION_ERROR",
                "error_message": str(exc),
            }
        )
        delivery.updated_at = utc_now()
        if run is not None:
            run.status = "error"
            run.retryable = False
            run.error_code = "SMTP_CONFIGURATION_ERROR"
            run.error_message = str(exc)
            run.next_action_at = None
            run.updated_at = utc_now()
            if run.trigger_type == "scheduled":
                run.schedule.last_status = "error"
                run.schedule.last_error_at = utc_now()
                run.schedule.last_error_message = str(exc)
        db.commit()
        raise

    if delivery.message_id is None:
        delivery.message_id = make_msgid(
            idstring=f"omi-dispatch-{delivery.id}",
            domain="omi.local",
        )
    delivery.status = "sending"
    delivery.updated_at = utc_now()
    if run is not None:
        run.status = "sending"
        run.sending_at = utc_now()
        run.retryable = False
        run.error_code = None
        run.error_message = None
        run.updated_at = utc_now()
    db.commit()

    try:
        result = sender.send(
            recipients=recipient_list,
            subject=delivery.subject,
            body_text=delivery.body_text or "",
            body_html=delivery.body_html or "",
            message_id=delivery.message_id,
        )
    except Exception as exc:
        delivery.status = "unknown"
        delivery.error_message = str(exc)
        delivery.result_json = _to_json(
            {
                "status": "unknown",
                "error_code": "DELIVERY_RESULT_UNKNOWN",
                "error_message": str(exc),
                "message_id": delivery.message_id,
            }
        )
        delivery.updated_at = utc_now()
        if run is not None:
            run.status = "error"
            run.retryable = False
            run.error_code = "DELIVERY_RESULT_UNKNOWN"
            run.error_message = str(exc)
            run.next_action_at = None
            run.updated_at = utc_now()
            if run.trigger_type == "scheduled":
                run.schedule.last_status = "error"
                run.schedule.last_error_at = utc_now()
                run.schedule.last_error_message = (
                    "SMTP delivery result is unknown; automatic retry is disabled."
                )
        db.commit()
        raise

    delivery.status = "success"
    delivery.error_message = None
    delivery.sent_at = utc_now()
    delivery.result_json = _to_json(
        {"status": "success", "message_id": delivery.message_id, **result}
    )
    delivery.updated_at = utc_now()
    if run is not None:
        run.status = "success"
        run.retryable = False
        run.error_code = None
        run.error_message = None
        run.next_action_at = None
        run.sent_at = delivery.sent_at
        run.updated_at = utc_now()
        if run.trigger_type == "scheduled":
            run.schedule.last_status = "success"
            run.schedule.last_sent_at = delivery.sent_at
            run.schedule.last_success_at = delivery.sent_at
            run.schedule.last_error_at = None
            run.schedule.last_error_message = None
            run.schedule.updated_at = utc_now()
    db.commit()
    db.refresh(delivery)
    return serialize_delivery(delivery)


def list_schedules(db: Session, *, enabled: bool | None = None) -> list[dict[str, Any]]:
    query = db.query(DispatchSchedule).filter(DispatchSchedule.archived_at.is_(None))
    if enabled is not None:
        query = query.filter(DispatchSchedule.enabled.is_(enabled))
    rows = query.order_by(
        DispatchSchedule.enabled.desc(),
        DispatchSchedule.send_time.asc(),
        DispatchSchedule.id.asc(),
    ).all()
    return [serialize_schedule(row) for row in rows]


def get_schedule(db: Session, schedule_id: int) -> DispatchSchedule:
    schedule = db.query(DispatchSchedule).filter(DispatchSchedule.id == schedule_id).first()
    if schedule is None:
        raise DispatchScheduleNotFoundError(f"Dispatch schedule id={schedule_id} not found.")
    return schedule


def _schedule_request_from_data(data: dict[str, Any]) -> DispatchPreviewRequest:
    request = _preview_request_from_data(data)
    _validate_preview_request(request)
    return request


def _schedule_request_from_schedule(schedule: DispatchSchedule) -> DispatchSendRequest:
    if schedule.recipient_group_id is None:
        raise DispatchValidationError(f"Dispatch schedule id={schedule.id} has no recipient group.")

    request = _schedule_request_from_data(_from_json(schedule.request_json) or {})
    return DispatchSendRequest(
        **_preview_request_dict(request),
        recipient_group_id=schedule.recipient_group_id,
    )


def create_schedule(db: Session, payload: DispatchScheduleCreate) -> dict[str, Any]:
    from app.dispatch import schedule_runs

    get_recipient_group(db=db, group_id=payload.recipient_group_id)
    send_time = _normalize_send_time(payload.send_time)
    day_of_week = _normalize_day_of_week(payload.day_of_week)
    timezone_name = _normalize_timezone(payload.timezone)
    request = _schedule_request_from_data(_preview_request_dict(payload))
    schedule = DispatchSchedule(
        name=payload.name.strip(),
        description=payload.description,
        recipient_group_id=payload.recipient_group_id,
        enabled=payload.enabled,
        send_time=send_time,
        day_of_week=day_of_week,
        timezone=timezone_name,
        template_key=request.template_key,
        scope_type=request.scope_type,
        scope_id=None if request.scope_id is None else str(request.scope_id),
        request_json=_to_json(_preview_request_dict(request)) or "{}",
        calendar_mode=payload.calendar_mode,
        catchup_mode=payload.catchup_mode,
        misfire_policy=payload.misfire_policy,
        misfire_grace_minutes=payload.misfire_grace_minutes,
        max_retries=payload.max_retries,
        retry_interval_seconds=payload.retry_interval_seconds,
        readiness_profile=payload.readiness_profile,
        readiness_policy=payload.readiness_policy,
        readiness_deadline_minutes=payload.readiness_deadline_minutes,
        readiness_retry_interval_seconds=payload.readiness_retry_interval_seconds,
        last_status="never_run",
    )
    db.add(schedule)
    db.flush()
    next_run = schedule_runs.compute_schedule_next_run(
        schedule,
        after=utc_now(),
        inclusive=True,
    )
    schedule.next_run_at = utc_db_value(next_run) if next_run else None
    db.commit()
    db.refresh(schedule)
    return serialize_schedule(schedule)


def update_schedule(
    db: Session,
    schedule_id: int,
    payload: DispatchScheduleUpdate,
) -> dict[str, Any]:
    from app.dispatch import schedule_runs

    schedule = get_schedule(db=db, schedule_id=schedule_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        schedule.name = str(update_data["name"]).strip()
    if "description" in update_data:
        schedule.description = update_data["description"]
    if "recipient_group_id" in update_data and update_data["recipient_group_id"] is not None:
        get_recipient_group(db=db, group_id=int(update_data["recipient_group_id"]))
        schedule.recipient_group_id = int(update_data["recipient_group_id"])
    if "enabled" in update_data and update_data["enabled"] is not None:
        schedule.enabled = bool(update_data["enabled"])
    if "send_time" in update_data and update_data["send_time"] is not None:
        schedule.send_time = _normalize_send_time(str(update_data["send_time"]))
    if "day_of_week" in update_data and update_data["day_of_week"] is not None:
        schedule.day_of_week = _normalize_day_of_week(str(update_data["day_of_week"]))
    if "timezone" in update_data and update_data["timezone"] is not None:
        schedule.timezone = _normalize_timezone(str(update_data["timezone"]))
    for field in (
        "calendar_mode",
        "catchup_mode",
        "misfire_policy",
        "misfire_grace_minutes",
        "max_retries",
        "retry_interval_seconds",
        "readiness_profile",
        "readiness_policy",
        "readiness_deadline_minutes",
        "readiness_retry_interval_seconds",
    ):
        if field in update_data and update_data[field] is not None:
            setattr(schedule, field, update_data[field])

    request_data = _from_json(schedule.request_json) or {}
    for field in PREVIEW_REQUEST_FIELDS:
        if field in update_data:
            request_data[field] = update_data[field]

    request = _schedule_request_from_data(request_data)
    schedule.template_key = request.template_key
    schedule.scope_type = request.scope_type
    schedule.scope_id = None if request.scope_id is None else str(request.scope_id)
    schedule.request_json = _to_json(_preview_request_dict(request)) or "{}"
    if {
        "enabled",
        "send_time",
        "day_of_week",
        "timezone",
        "calendar_mode",
    }.intersection(update_data):
        next_run = schedule_runs.compute_schedule_next_run(
            schedule,
            after=utc_now(),
            inclusive=True,
        )
        schedule.next_run_at = utc_db_value(next_run) if next_run else None
    schedule.updated_at = utc_now()
    db.commit()
    db.refresh(schedule)
    return serialize_schedule(schedule)


def delete_schedule(db: Session, schedule_id: int) -> dict[str, Any]:
    schedule = get_schedule(db=db, schedule_id=schedule_id)
    schedule.enabled = False
    schedule.next_run_at = None
    schedule.archived_at = utc_now()
    schedule.updated_at = utc_now()
    db.commit()
    return {"id": schedule_id, "deleted": True}


def _send_request_from_run_snapshot(snapshot: dict[str, Any]) -> DispatchSendRequest:
    request_data = snapshot.get("request")
    request_data = request_data if isinstance(request_data, dict) else {}
    request = _schedule_request_from_data(request_data)
    recipient_group = snapshot.get("recipient_group")
    recipient_group = recipient_group if isinstance(recipient_group, dict) else {}
    group_id = recipient_group.get("id")
    if group_id is None:
        raise DispatchValidationError("The schedule run snapshot has no recipient group.")
    return DispatchSendRequest(
        **_preview_request_dict(request),
        recipient_group_id=int(group_id),
    )


def _mark_run_queue_error(
    db: Session,
    *,
    run_id: int,
    exc: Exception,
) -> None:
    from app.dispatch import schedule_runs

    db.rollback()
    run = schedule_runs.get_schedule_run(db, run_id)
    run.delivery_attempt_count += 1
    retryable = (
        isinstance(exc, (ConnectionError, TimeoutError))
        and run.delivery_attempt_count < run.max_delivery_attempts
    )
    run.status = "retry_wait" if retryable else "error"
    run.retryable = retryable
    run.error_code = "DELIVERY_QUEUE_TRANSIENT" if retryable else "DELIVERY_QUEUE_FAILED"
    run.error_message = str(exc)
    run.next_action_at = (
        utc_db_value(
            utc_now()
            + timedelta(
                seconds=max(int(run.schedule.retry_interval_seconds), 10)
            )
        )
        if retryable
        else None
    )
    if run.trigger_type == "scheduled":
        run.schedule.last_status = run.status
        run.schedule.last_error_at = utc_now()
        run.schedule.last_error_message = str(exc)
    run.updated_at = utc_now()
    db.commit()


def queue_schedule_run(
    db: Session,
    *,
    run_id: int,
    submit_task: bool = True,
) -> dict[str, Any]:
    from app.dispatch import schedule_runs
    from app.dispatch.tasks import run_dispatch_schedule_run_job

    run = schedule_runs.get_schedule_run(db, run_id)
    if run.status not in {"claimed", "retry_wait"}:
        raise DispatchValidationError(
            f"Dispatch schedule run id={run_id} cannot be queued from status={run.status}."
        )
    snapshot = _from_json(run.schedule_snapshot_json)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    payload = _send_request_from_run_snapshot(snapshot)
    recipient_snapshot = snapshot.get("recipient_group")
    recipient_snapshot = recipient_snapshot if isinstance(recipient_snapshot, dict) else {}
    recipients = recipient_snapshot.get("recipients")
    recipient_list = recipients if isinstance(recipients, list) else []
    recipient_group = (
        db.query(DispatchRecipientGroup)
        .filter(DispatchRecipientGroup.id == payload.recipient_group_id)
        .first()
    )

    try:
        preview = build_preview(db=db, payload=payload)
        delivery = create_delivery(
            db=db,
            payload=payload,
            preview=preview,
            recipient_group=recipient_group,
            recipients_override=recipient_list,
            commit=False,
        )
        job = job_service.create_job_record(
            db=db,
            job_type="dispatch.mail_delivery",
            target=str(delivery.id),
            request={"delivery_id": delivery.id, "schedule_run_id": run.id},
            progress_total=1,
            message="Queued scheduled mail dispatch.",
        )
        db.flush()
        delivery.job_run_id = job.id
        run.delivery_id = delivery.id
        run.job_run_id = job.id
        run.delivery_attempt_count += 1
        run.status = "queued"
        run.queued_at = utc_now()
        run.next_action_at = None
        run.retryable = False
        run.error_code = None
        run.error_message = None
        run.updated_at = utc_now()
        if run.trigger_type == "scheduled":
            schedule = run.schedule
            schedule.last_run_key = run.scheduled_slot_key
            schedule.last_run_at = utc_now()
            schedule.last_queued_at = utc_now()
            schedule.last_status = "queued"
            schedule.last_error_at = None
            schedule.last_error_message = None
            schedule.last_delivery_id = delivery.id
            schedule.last_job_run_id = job.id
            schedule.updated_at = utc_now()
        db.commit()
        db.refresh(delivery)
        db.refresh(job)
        db.refresh(run)
    except Exception as exc:
        _mark_run_queue_error(db, run_id=run_id, exc=exc)
        raise

    if submit_task:
        try:
            job_service.submit_job_task(
                run_dispatch_schedule_run_job,
                job.id,
                run.id,
                delivery.id,
            )
        except Exception as exc:
            job_service.fail_job(db, job.id, error_message=f"Failed to submit job: {exc}")
            run = schedule_runs.get_schedule_run(db, run.id)
            can_retry = run.delivery_attempt_count < run.max_delivery_attempts
            run.status = "retry_wait" if can_retry else "error"
            run.retryable = can_retry
            run.error_code = "JOB_SUBMIT_FAILED" if can_retry else "DELIVERY_RETRY_EXHAUSTED"
            run.error_message = str(exc)
            run.next_action_at = (
                utc_db_value(
                    utc_now()
                    + timedelta(
                        seconds=max(int(run.schedule.retry_interval_seconds), 10)
                    )
                )
                if can_retry
                else None
            )
            run.updated_at = utc_now()
            db.commit()

    return {
        "status": run.status,
        "run": schedule_runs.serialize_run(run),
        "schedule": serialize_schedule(run.schedule),
        "job": job_service.serialize_job(job),
        "delivery": serialize_delivery(delivery),
    }


def process_schedule_run(
    db: Session,
    *,
    run_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    from app.dispatch import schedule_runs

    readiness = schedule_runs.evaluate_run_readiness(db, run_id=run_id, now=now)
    if readiness["action"] == "queue":
        return queue_schedule_run(db, run_id=run_id)
    return {
        "status": readiness["run"]["status"],
        "run": readiness["run"],
    }


def _resubmit_queued_schedule_run(db: Session, *, run: DispatchScheduleRun) -> dict[str, Any]:
    from app.dispatch import schedule_runs
    from app.dispatch.tasks import run_dispatch_schedule_run_job

    if run.delivery is None or run.delivery.status not in {"queued", "error"}:
        raise DispatchValidationError(
            f"Dispatch schedule run id={run.id} has no safely resubmittable delivery."
        )
    if run.delivery_attempt_count >= run.max_delivery_attempts:
        run.status = "error"
        run.retryable = False
        run.error_code = "DELIVERY_RETRY_EXHAUSTED"
        run.error_message = "The configured delivery retry limit was exhausted before SMTP started."
        run.next_action_at = None
        run.updated_at = utc_now()
        db.commit()
        raise DispatchValidationError(run.error_message)
    delivery = run.delivery
    job = job_service.create_job_record(
        db=db,
        job_type="dispatch.mail_delivery",
        target=str(delivery.id),
        request={"delivery_id": delivery.id, "schedule_run_id": run.id, "resubmitted": True},
        progress_total=1,
        message="Requeued scheduled mail dispatch after interrupted handoff.",
    )
    db.flush()
    delivery.status = "queued"
    delivery.error_message = None
    delivery.job_run_id = job.id
    delivery.updated_at = utc_now()
    run.job_run_id = job.id
    run.delivery_attempt_count += 1
    run.status = "queued"
    run.queued_at = utc_now()
    run.next_action_at = None
    run.retryable = False
    run.error_code = None
    run.error_message = None
    run.updated_at = utc_now()
    if run.trigger_type == "scheduled":
        run.schedule.last_status = "queued"
        run.schedule.last_queued_at = utc_now()
        run.schedule.last_job_run_id = job.id
        run.schedule.updated_at = utc_now()
    db.commit()
    db.refresh(job)
    try:
        job_service.submit_job_task(
            run_dispatch_schedule_run_job,
            job.id,
            run.id,
            delivery.id,
        )
    except Exception as exc:
        job_service.fail_job(db, job.id, error_message=f"Failed to submit job: {exc}")
        run = schedule_runs.get_schedule_run(db, run.id)
        can_retry = run.delivery_attempt_count < run.max_delivery_attempts
        run.status = "retry_wait" if can_retry else "error"
        run.retryable = can_retry
        run.error_code = "JOB_SUBMIT_FAILED" if can_retry else "DELIVERY_RETRY_EXHAUSTED"
        run.error_message = str(exc)
        run.next_action_at = (
            utc_db_value(
                utc_now() + timedelta(seconds=max(int(run.schedule.retry_interval_seconds), 10))
            )
            if can_retry
            else None
        )
        run.updated_at = utc_now()
        db.commit()
    return {
        "status": run.status,
        "run": schedule_runs.serialize_run(run),
        "job": job_service.serialize_job(job),
        "delivery": serialize_delivery(delivery),
    }


def reconcile_schedule_runs(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    from app.dispatch import schedule_runs

    current = now or utc_now()
    current_db = utc_db_value(current)
    stale_before = utc_db_value(
        current - timedelta(minutes=max(int(settings.scheduler_dispatch_stale_claim_minutes), 1))
    )
    reconcile_limit = max(int(limit or settings.scheduler_dispatch_claim_limit), 1)
    actionable = (
        db.query(DispatchScheduleRun)
        .filter(
            DispatchScheduleRun.status.in_({"claimed", "waiting_data", "retry_wait"}),
            DispatchScheduleRun.next_action_at.isnot(None),
            DispatchScheduleRun.next_action_at <= current_db,
        )
        .order_by(DispatchScheduleRun.next_action_at.asc(), DispatchScheduleRun.id.asc())
        .limit(reconcile_limit)
        .all()
    )
    stale = (
        db.query(DispatchScheduleRun)
        .filter(
            DispatchScheduleRun.status.in_({"queued", "sending"}),
            DispatchScheduleRun.updated_at <= stale_before,
        )
        .order_by(DispatchScheduleRun.updated_at.asc(), DispatchScheduleRun.id.asc())
        .limit(reconcile_limit)
        .all()
    )
    processed: list[int] = []
    recovered: list[int] = []
    unknown: list[int] = []
    errors: list[dict[str, Any]] = []

    for run in stale:
        if run.status == "sending":
            run.status = "error"
            run.retryable = False
            run.error_code = "DELIVERY_RESULT_UNKNOWN_AFTER_RESTART"
            run.error_message = (
                "The process stopped while SMTP delivery was in progress; automatic retry is disabled."
            )
            run.next_action_at = None
            if run.delivery is not None:
                run.delivery.status = "unknown"
                run.delivery.error_message = run.error_message
                run.delivery.updated_at = utc_now()
            if run.trigger_type == "scheduled":
                run.schedule.last_status = "error"
                run.schedule.last_error_at = utc_now()
                run.schedule.last_error_message = run.error_message
            run.updated_at = utc_now()
            db.commit()
            unknown.append(run.id)
            continue

        job = run.job_run
        if run.delivery is not None and run.delivery.status == "success":
            run.status = "success"
            run.sent_at = run.delivery.sent_at
            run.retryable = False
            run.error_code = None
            run.error_message = None
            run.updated_at = utc_now()
            if run.trigger_type == "scheduled":
                run.schedule.last_status = "success"
                run.schedule.last_sent_at = run.delivery.sent_at
                run.schedule.last_success_at = run.delivery.sent_at
            db.commit()
            recovered.append(run.id)
        elif job is None or job.status == "error":
            run.status = "retry_wait"
            run.retryable = True
            run.error_code = "JOB_INTERRUPTED_BEFORE_SMTP"
            run.error_message = "The queued worker was interrupted before SMTP delivery started."
            run.next_action_at = current_db
            run.updated_at = utc_now()
            db.commit()
            actionable.append(run)

    seen: set[int] = set()
    for listed_run in actionable:
        if listed_run.id in seen:
            continue
        seen.add(listed_run.id)
        try:
            run = schedule_runs.get_schedule_run(db, listed_run.id)
            if run.status == "retry_wait" and run.delivery_id is not None:
                _resubmit_queued_schedule_run(db, run=run)
                recovered.append(run.id)
            else:
                if run.status == "retry_wait":
                    run.status = "claimed"
                    run.next_action_at = current_db
                    run.updated_at = utc_now()
                    db.commit()
                process_schedule_run(db, run_id=run.id, now=current)
                processed.append(run.id)
        except Exception as exc:
            errors.append({"run_id": listed_run.id, "error_message": str(exc)})

    return {
        "status": "success" if not errors else "partial_success",
        "processed_count": len(processed),
        "recovered_count": len(recovered),
        "unknown_count": len(unknown),
        "error_count": len(errors),
        "processed_run_ids": processed,
        "recovered_run_ids": recovered,
        "unknown_run_ids": unknown,
        "errors": errors,
    }


def run_schedule_now(db: Session, schedule_id: int) -> dict[str, Any]:
    if not settings.dispatch_scheduler_v2_enabled:
        schedule = get_schedule(db=db, schedule_id=schedule_id)
        return _trigger_schedule(db=db, schedule=schedule, run_key=f"manual:{utc_now().isoformat()}")

    from app.dispatch import schedule_runs

    schedule = get_schedule(db=db, schedule_id=schedule_id)
    run = schedule_runs.create_manual_run(
        db,
        schedule=schedule,
        force_immediate=True,
    )
    return process_schedule_run(db, run_id=run.id)


def _mark_schedule_error(
    db: Session,
    *,
    schedule_id: int,
    run_key: str | None,
    error_message: str,
) -> None:
    schedule = get_schedule(db=db, schedule_id=schedule_id)
    now = utc_now()
    schedule.last_run_key = run_key
    schedule.last_run_at = now
    schedule.last_error_at = now
    schedule.last_error_message = error_message
    schedule.updated_at = now
    db.commit()


def _trigger_schedule(
    db: Session,
    *,
    schedule: DispatchSchedule,
    run_key: str | None,
) -> dict[str, Any]:
    try:
        payload = _schedule_request_from_schedule(schedule)
        result = queue_delivery(db=db, payload=payload)
        now = utc_now()
        schedule.last_run_key = run_key
        schedule.last_run_at = now
        schedule.last_success_at = now
        schedule.last_error_at = None
        schedule.last_error_message = None
        schedule.last_delivery_id = int(result["delivery"]["id"])
        schedule.last_job_run_id = int(result["job"]["id"])
        schedule.updated_at = now
        db.commit()
        db.refresh(schedule)
        return {
            "status": "queued",
            "schedule": serialize_schedule(schedule),
            **result,
        }
    except Exception as exc:
        db.rollback()
        _mark_schedule_error(
            db=db,
            schedule_id=schedule.id,
            run_key=run_key,
            error_message=str(exc),
        )
        raise


def enqueue_due_schedules(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    if settings.dispatch_scheduler_v2_enabled:
        from app.dispatch import schedule_runs

        claim = schedule_runs.claim_due_schedule_runs(db, now=now)
        queued: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = list(claim.get("errors") or [])
        for run_id in claim["claimed_run_ids"]:
            try:
                result = process_schedule_run(db, run_id=run_id, now=now)
                if result["status"] in {"queued", "retry_wait"} and result.get("delivery"):
                    queued.append(
                        {
                            "schedule_id": result["run"]["schedule_id"],
                            "run_id": run_id,
                            "run_key": result["run"].get("scheduled_slot_key"),
                            "delivery_id": result["delivery"]["id"],
                            "job_run_id": result["job"]["id"],
                        }
                    )
                elif result["status"] == "waiting_data":
                    waiting.append(
                        {
                            "schedule_id": result["run"]["schedule_id"],
                            "run_id": run_id,
                        }
                    )
            except Exception as exc:
                errors.append({"run_id": run_id, "error_message": str(exc)})
        return {
            "status": "success" if not errors else "partial_success",
            "checked_count": claim["checked_count"],
            "queued_count": len(queued),
            "waiting_count": len(waiting),
            "skipped_count": claim["skipped_count"],
            "error_count": len(errors),
            "conflict_count": claim["conflict_count"],
            "queued": queued,
            "waiting": waiting,
            "errors": errors,
        }

    schedules = db.query(DispatchSchedule).filter(DispatchSchedule.enabled.is_(True)).all()
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for schedule in schedules:
        due, run_key = _schedule_is_due(schedule, now)
        if not due:
            skipped.append({"schedule_id": schedule.id, "run_key": run_key, "reason": "not_due"})
            continue

        try:
            result = _trigger_schedule(db=db, schedule=schedule, run_key=run_key)
            queued.append(
                {
                    "schedule_id": schedule.id,
                    "run_key": run_key,
                    "delivery_id": result["delivery"]["id"],
                    "job_run_id": result["job"]["id"],
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "schedule_id": schedule.id,
                    "run_key": run_key,
                    "error_message": str(exc),
                }
            )

    return {
        "status": "success" if not errors else "partial_success",
        "checked_count": len(schedules),
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "queued": queued,
        "errors": errors,
    }
