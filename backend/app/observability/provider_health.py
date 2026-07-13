from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, load_only

from app.db.models import ProviderEvent, SourceHealthSnapshot, utc_now


ERROR_STATUSES = {"error", "failed", "timeout", "rate_limited", "blocked", "partial_success"}
DEFAULT_RECENT_WINDOW_HOURS = 24
DEFAULT_SOURCE_HEALTH_SNAPSHOT_STALE_SECONDS = 24 * 60 * 60
PROVIDER_EVENT_READ_COLUMNS = (
    ProviderEvent.id,
    ProviderEvent.market,
    ProviderEvent.provider,
    ProviderEvent.resource,
    ProviderEvent.target,
    ProviderEvent.status,
    ProviderEvent.severity,
    ProviderEvent.event_type,
    ProviderEvent.event_time,
    ProviderEvent.observed_at,
    ProviderEvent.http_status_code,
    ProviderEvent.rate_limited,
    ProviderEvent.retry_after_seconds,
    ProviderEvent.duration_ms,
    ProviderEvent.source_url,
    ProviderEvent.message,
    ProviderEvent.error_message,
    ProviderEvent.job_run_id,
    ProviderEvent.fetch_log_id,
    ProviderEvent.raw_result_id,
    ProviderEvent.created_at,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_key(value: Any, *, default: str = "all") -> str:
    text = str(value or "").strip()
    return text or default


def _normalized_market(value: Any) -> str:
    return _normalized_key(value, default="unknown").lower()


def _normalized_provider(value: Any) -> str:
    return _normalized_key(value, default="all").lower()


def _provider_candidates(value: Any) -> tuple[str, ...]:
    normalized = _normalized_provider(value)
    if normalized == "all":
        return ("all",)
    candidates = tuple(
        dict.fromkeys(
            part.strip()
            for part in re.split(r"[+,]", normalized)
            if part.strip()
        )
    )
    return candidates or (normalized,)


def _normalized_status(value: Any) -> str:
    return _normalized_key(value, default="unknown").lower()


def _severity_for(status: str, severity: str | None = None) -> str:
    if severity:
        return severity.strip().lower()
    if status in ERROR_STATUSES:
        return "error"
    if status in {"warning", "stale", "empty"}:
        return "warning"
    return "info"


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _event_message(event: ProviderEvent | None) -> str | None:
    if event is None:
        return None
    return event.error_message or event.message


def provider_event_to_dict(event: ProviderEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "market": event.market,
        "provider": event.provider,
        "resource": event.resource,
        "target": event.target,
        "status": event.status,
        "severity": event.severity,
        "event_type": event.event_type,
        "event_time": event.event_time.isoformat() if event.event_time else None,
        "observed_at": event.observed_at.isoformat() if event.observed_at else None,
        "http_status_code": event.http_status_code,
        "rate_limited": event.rate_limited,
        "retry_after_seconds": event.retry_after_seconds,
        "duration_ms": event.duration_ms,
        "source_url": event.source_url,
        "message": event.message,
        "error_message": event.error_message,
        "job_run_id": event.job_run_id,
        "fetch_log_id": event.fetch_log_id,
        "raw_result_id": event.raw_result_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def source_health_snapshot_to_dict(
    snapshot: SourceHealthSnapshot,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_SOURCE_HEALTH_SNAPSHOT_STALE_SECONDS,
) -> dict[str, Any]:
    current = _utc_datetime(now or _now())
    checked_at = _utc_datetime(snapshot.checked_at)
    snapshot_age_seconds = max(int((current - checked_at).total_seconds()), 0)
    return {
        "id": snapshot.id,
        "market": snapshot.market,
        "resource": snapshot.resource,
        "target": snapshot.target,
        "provider": snapshot.provider,
        "status": snapshot.status,
        "ok": snapshot.ok,
        "row_count": snapshot.row_count,
        "required": snapshot.required,
        "data_quality": snapshot.data_quality,
        "latest_data_date": snapshot.latest_data_date.isoformat() if snapshot.latest_data_date else None,
        "latest_data_key": snapshot.latest_data_key,
        "latest_observed_at": snapshot.latest_observed_at.isoformat() if snapshot.latest_observed_at else None,
        "expected_data_date": snapshot.expected_data_date.isoformat() if snapshot.expected_data_date else None,
        "freshness_lag_days": snapshot.freshness_lag_days,
        "release_status": snapshot.release_status,
        "reason": snapshot.reason,
        "latest_event_id": snapshot.latest_event_id,
        "latest_event_at": snapshot.latest_event_at.isoformat() if snapshot.latest_event_at else None,
        "latest_event_status": snapshot.latest_event_status,
        "latest_event_severity": snapshot.latest_event_severity,
        "latest_event_message": snapshot.latest_event_message,
        "recent_event_count": snapshot.recent_event_count,
        "recent_error_count": snapshot.recent_error_count,
        "consecutive_error_count": snapshot.consecutive_error_count,
        "checked_at": snapshot.checked_at.isoformat() if snapshot.checked_at else None,
        "snapshot_age_seconds": snapshot_age_seconds,
        "snapshot_is_stale": snapshot_age_seconds > max(stale_after_seconds, 0),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
    }


def record_provider_event(
    db: Session,
    *,
    market: str,
    provider: str,
    resource: str,
    target: str = "all",
    status: str,
    severity: str | None = None,
    event_type: str = "fetch",
    event_time: datetime | None = None,
    observed_at: datetime | None = None,
    http_status_code: int | None = None,
    rate_limited: bool = False,
    retry_after_seconds: int | None = None,
    duration_ms: int | None = None,
    source_url: str | None = None,
    message: str | None = None,
    error_message: str | None = None,
    detail: dict[str, Any] | None = None,
    job_run_id: int | None = None,
    fetch_log_id: int | None = None,
    raw_result_id: int | None = None,
    commit: bool = True,
) -> ProviderEvent:
    normalized_status = _normalized_status(status)
    event = ProviderEvent(
        market=_normalized_market(market),
        provider=_normalized_provider(provider),
        resource=_normalized_key(resource, default="unknown"),
        target=_normalized_key(target, default="all"),
        status=normalized_status,
        severity=_severity_for(normalized_status, severity),
        event_type=_normalized_key(event_type, default="fetch").lower(),
        event_time=event_time or _now(),
        observed_at=observed_at or _now(),
        http_status_code=http_status_code,
        rate_limited=rate_limited,
        retry_after_seconds=retry_after_seconds,
        duration_ms=duration_ms,
        source_url=source_url,
        message=message,
        error_message=error_message,
        detail_json=_json_dumps(detail),
        job_run_id=job_run_id,
        fetch_log_id=fetch_log_id,
        raw_result_id=raw_result_id,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def _event_query(
    db: Session,
    *,
    market: str | None = None,
    provider: str | None = None,
    resource: str | None = None,
    target: str | None = None,
    status: str | None = None,
):
    query = db.query(ProviderEvent)
    if market:
        query = query.filter(ProviderEvent.market == _normalized_market(market))
    if provider:
        query = query.filter(ProviderEvent.provider == _normalized_provider(provider))
    if resource:
        query = query.filter(ProviderEvent.resource == resource)
    if target:
        query = query.filter(ProviderEvent.target == _normalized_key(target))
    if status:
        query = query.filter(ProviderEvent.status == _normalized_status(status))
    return query


def list_provider_events(
    db: Session,
    *,
    market: str | None = None,
    provider: str | None = None,
    resource: str | None = None,
    target: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    events = (
        _event_query(
            db,
            market=market,
            provider=provider,
            resource=resource,
            target=target,
            status=status,
        )
        .options(load_only(*PROVIDER_EVENT_READ_COLUMNS))
        .order_by(ProviderEvent.event_time.desc(), ProviderEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [provider_event_to_dict(event) for event in events]


def _matching_events_query(
    db: Session,
    *,
    market: str,
    provider: str,
    resource: str,
    target: str,
):
    provider_candidates = _provider_candidates(provider)
    provider_filter = True if provider_candidates == ("all",) else or_(
        ProviderEvent.provider.in_(provider_candidates),
        ProviderEvent.provider == "all",
    )
    return (
        db.query(ProviderEvent)
        .filter(ProviderEvent.market == _normalized_market(market))
        .filter(ProviderEvent.resource == resource)
        .filter(or_(ProviderEvent.target == target, ProviderEvent.target == "all"))
        .filter(provider_filter)
    )


def provider_event_summary(
    db: Session,
    *,
    market: str,
    provider: str,
    resource: str,
    target: str,
    recent_window_hours: int = DEFAULT_RECENT_WINDOW_HOURS,
) -> dict[str, Any]:
    query = _matching_events_query(
        db,
        market=market,
        provider=provider,
        resource=resource,
        target=target,
    )
    latest_event = (
        query.options(load_only(*PROVIDER_EVENT_READ_COLUMNS))
        .order_by(ProviderEvent.event_time.desc(), ProviderEvent.id.desc())
        .first()
    )
    since = _now() - timedelta(hours=max(1, recent_window_hours))
    recent_event_count, recent_error_count = (
        query.filter(ProviderEvent.event_time >= since)
        .with_entities(
            func.count(ProviderEvent.id),
            func.coalesce(
                func.sum(
                    case(
                        (ProviderEvent.status.in_(ERROR_STATUSES), 1),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .one()
    )
    ordered_events = (
        query.options(load_only(ProviderEvent.status))
        .order_by(ProviderEvent.event_time.desc(), ProviderEvent.id.desc())
        .limit(25)
        .all()
    )
    consecutive_error_count = 0
    for event in ordered_events:
        if event.status not in ERROR_STATUSES:
            break
        consecutive_error_count += 1

    return {
        "latest_event": provider_event_to_dict(latest_event) if latest_event else None,
        "recent_event_count": recent_event_count,
        "recent_error_count": recent_error_count,
        "consecutive_error_count": consecutive_error_count,
    }


def enrich_source_health_entries(
    db: Session,
    *,
    market: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for entry in entries:
        provider = _normalized_provider(entry.get("provider"))
        target = _normalized_key(entry.get("target"))
        resource = _normalized_key(entry.get("resource"), default="unknown")
        summary = provider_event_summary(
            db,
            market=market,
            provider=provider,
            resource=resource,
            target=target,
        )
        latest_event = summary.get("latest_event") if isinstance(summary.get("latest_event"), dict) else None
        enriched_entry = dict(entry)
        enriched_entry.update(
            {
                "latest_event_id": latest_event.get("id") if latest_event else None,
                "latest_event_at": latest_event.get("event_time") if latest_event else None,
                "latest_event_status": latest_event.get("status") if latest_event else None,
                "latest_event_severity": latest_event.get("severity") if latest_event else None,
                "latest_event_message": (
                    latest_event.get("error_message") or latest_event.get("message")
                    if latest_event
                    else None
                ),
                "recent_event_count": int(summary["recent_event_count"] or 0),
                "recent_error_count": int(summary["recent_error_count"] or 0),
                "consecutive_error_count": summary["consecutive_error_count"],
            }
        )
        enriched.append(enriched_entry)
    return enriched


def _snapshot_values(
    *,
    market: str,
    entry: dict[str, Any],
    checked_at: datetime,
) -> dict[str, Any]:
    return {
        "market": _normalized_market(market),
        "resource": _normalized_key(entry.get("resource"), default="unknown"),
        "target": _normalized_key(entry.get("target")),
        "provider": _normalized_provider(entry.get("provider")),
        "status": _normalized_status(entry.get("status")),
        "ok": bool(entry.get("ok")),
        "row_count": int(entry.get("row_count") or 0),
        "required": bool(entry.get("required", True)),
        "data_quality": _normalized_key(entry.get("data_quality"), default="unknown"),
        "latest_data_date": _parse_date(entry.get("latest_data_date")),
        "latest_data_key": entry.get("latest_data_key"),
        "latest_observed_at": _parse_datetime(entry.get("latest_fetched_at"))
        or _parse_datetime(entry.get("latest_updated_at")),
        "expected_data_date": _parse_date(entry.get("expected_data_date")),
        "freshness_lag_days": entry.get("freshness_lag_days"),
        "release_status": entry.get("release_status"),
        "reason": entry.get("reason"),
        "latest_event_id": entry.get("latest_event_id"),
        "latest_event_at": _parse_datetime(entry.get("latest_event_at")),
        "latest_event_status": entry.get("latest_event_status"),
        "latest_event_severity": entry.get("latest_event_severity"),
        "latest_event_message": entry.get("latest_event_message"),
        "recent_event_count": int(entry.get("recent_event_count") or 0),
        "recent_error_count": int(entry.get("recent_error_count") or 0),
        "consecutive_error_count": int(entry.get("consecutive_error_count") or 0),
        "snapshot_json": _json_dumps(entry),
        "checked_at": checked_at,
        "updated_at": checked_at,
    }


def sync_source_health_snapshots(
    db: Session,
    *,
    market: str,
    entries: list[dict[str, Any]],
    checked_at: datetime | None = None,
    commit: bool = True,
) -> list[SourceHealthSnapshot]:
    checked_at = checked_at or utc_now()
    snapshots: list[SourceHealthSnapshot] = []
    for entry in entries:
        values = _snapshot_values(market=market, entry=entry, checked_at=checked_at)
        snapshot = (
            db.query(SourceHealthSnapshot)
            .filter(SourceHealthSnapshot.market == values["market"])
            .filter(SourceHealthSnapshot.resource == values["resource"])
            .filter(SourceHealthSnapshot.target == values["target"])
            .filter(SourceHealthSnapshot.provider == values["provider"])
            .first()
        )
        if snapshot is None:
            snapshot = SourceHealthSnapshot(created_at=checked_at, **values)
            db.add(snapshot)
        else:
            for key, value in values.items():
                setattr(snapshot, key, value)
        snapshots.append(snapshot)

    if commit:
        db.commit()
        for snapshot in snapshots:
            db.refresh(snapshot)
    else:
        db.flush()
    return snapshots


def list_source_health_snapshots(
    db: Session,
    *,
    market: str | None = None,
    provider: str | None = None,
    resource: str | None = None,
    target: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    query = db.query(SourceHealthSnapshot)
    if market:
        query = query.filter(SourceHealthSnapshot.market == _normalized_market(market))
    if provider:
        query = query.filter(SourceHealthSnapshot.provider == _normalized_provider(provider))
    if resource:
        query = query.filter(SourceHealthSnapshot.resource == resource)
    if target:
        query = query.filter(SourceHealthSnapshot.target == _normalized_key(target))
    if status:
        query = query.filter(SourceHealthSnapshot.status == _normalized_status(status))
    snapshots = (
        query.order_by(SourceHealthSnapshot.checked_at.desc(), SourceHealthSnapshot.id.desc())
        .limit(limit)
        .all()
    )
    now = _now()
    return [source_health_snapshot_to_dict(snapshot, now=now) for snapshot in snapshots]


__all__ = [
    "DEFAULT_SOURCE_HEALTH_SNAPSHOT_STALE_SECONDS",
    "enrich_source_health_entries",
    "list_provider_events",
    "list_source_health_snapshots",
    "provider_event_summary",
    "provider_event_to_dict",
    "record_provider_event",
    "source_health_snapshot_to_dict",
    "sync_source_health_snapshots",
]
