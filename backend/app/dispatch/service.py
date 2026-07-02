from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import DispatchDelivery, DispatchRecipientGroup, DispatchSchedule, utc_now
from app.dispatch import templates
from app.dispatch.mail_sender import SmtpMailSender
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
    recipient_group: DispatchRecipientGroup,
) -> DispatchDelivery:
    if not recipient_group.enabled:
        raise DispatchValidationError(f"Recipient group is disabled: {recipient_group.name}")
    recipients = normalize_emails(_from_json(recipient_group.emails_json) or [])
    delivery = DispatchDelivery(
        recipient_group_id=recipient_group.id,
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


def send_delivery(db: Session, delivery_id: int) -> dict[str, Any]:
    delivery = get_delivery(db, delivery_id)
    recipients = _from_json(delivery.recipients_json)
    recipient_list = recipients if isinstance(recipients, list) else []
    delivery.status = "sending"
    delivery.updated_at = utc_now()
    db.commit()

    try:
        result = SmtpMailSender.from_settings().send(
            recipients=recipient_list,
            subject=delivery.subject,
            body_text=delivery.body_text or "",
            body_html=delivery.body_html or "",
        )
    except Exception as exc:
        delivery.status = "error"
        delivery.error_message = str(exc)
        delivery.result_json = _to_json({"status": "error", "error_message": str(exc)})
        delivery.updated_at = utc_now()
        db.commit()
        raise

    delivery.status = "success"
    delivery.error_message = None
    delivery.sent_at = utc_now()
    delivery.result_json = _to_json({"status": "success", **result})
    delivery.updated_at = utc_now()
    db.commit()
    db.refresh(delivery)
    return serialize_delivery(delivery)


def list_schedules(db: Session, *, enabled: bool | None = None) -> list[dict[str, Any]]:
    query = db.query(DispatchSchedule)
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
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return serialize_schedule(schedule)


def update_schedule(
    db: Session,
    schedule_id: int,
    payload: DispatchScheduleUpdate,
) -> dict[str, Any]:
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

    request_data = _from_json(schedule.request_json) or {}
    for field in PREVIEW_REQUEST_FIELDS:
        if field in update_data:
            request_data[field] = update_data[field]

    request = _schedule_request_from_data(request_data)
    schedule.template_key = request.template_key
    schedule.scope_type = request.scope_type
    schedule.scope_id = None if request.scope_id is None else str(request.scope_id)
    schedule.request_json = _to_json(_preview_request_dict(request)) or "{}"
    schedule.updated_at = utc_now()
    db.commit()
    db.refresh(schedule)
    return serialize_schedule(schedule)


def delete_schedule(db: Session, schedule_id: int) -> dict[str, Any]:
    schedule = get_schedule(db=db, schedule_id=schedule_id)
    db.delete(schedule)
    db.commit()
    return {"id": schedule_id, "deleted": True}


def run_schedule_now(db: Session, schedule_id: int) -> dict[str, Any]:
    schedule = get_schedule(db=db, schedule_id=schedule_id)
    return _trigger_schedule(db=db, schedule=schedule, run_key=f"manual:{utc_now().isoformat()}")


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
