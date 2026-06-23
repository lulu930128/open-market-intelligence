from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DispatchDelivery, DispatchRecipientGroup, utc_now
from app.dispatch import templates
from app.dispatch.mail_sender import SmtpMailSender
from app.dispatch.schemas import (
    DispatchPreviewRequest,
    DispatchRecipientGroupCreate,
    DispatchRecipientGroupUpdate,
    DispatchSendRequest,
)


class DispatchError(Exception):
    pass


class DispatchRecipientGroupNotFoundError(DispatchError):
    pass


class DispatchDeliveryNotFoundError(DispatchError):
    pass


class DispatchValidationError(DispatchError):
    pass


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
    if payload.template_key == "market_overview":
        return templates.build_market_overview_preview(
            db,
            market=_normalize_market_scope(payload.scope_id),
        )

    if payload.template_key == "watchlist_brief":
        if payload.scope_type != "watchlist":
            raise DispatchValidationError("scope_type must be watchlist for watchlist dispatch previews.")
        if payload.scope_id is None:
            raise DispatchValidationError("scope_id is required for watchlist dispatch previews.")
        return templates.build_watchlist_brief_preview(
            db,
            group_id=int(payload.scope_id),
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=payload.radar_mode,
        )

    raise DispatchValidationError(f"Unsupported dispatch template: {payload.template_key}")


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
