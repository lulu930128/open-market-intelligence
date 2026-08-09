from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope
from app.db.models import SourceHealthSnapshot
from app.observability.provider_health import (
    ERROR_STATUSES,
    list_provider_events,
    source_health_snapshot_to_dict,
)


SOURCE_HEALTH_CURRENT_TTL = timedelta(hours=1)
SOURCE_HEALTH_EXPIRED_TTL = timedelta(hours=24)
PROBLEM_STATUSES = {
    "missing",
    "empty",
    "stale",
    "delayed",
    "disabled",
    *ERROR_STATUSES,
}


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _snapshot_freshness(
    *,
    checked_at: datetime | None,
    generated_at: datetime,
) -> dict[str, Any]:
    normalized_checked_at = _utc_datetime(checked_at)
    normalized_generated_at = _utc_datetime(generated_at) or datetime.now(
        timezone.utc
    )
    if normalized_checked_at is None:
        return {
            "status": "missing",
            "checked_at": None,
            "age_seconds": None,
            "current_ttl_seconds": int(
                SOURCE_HEALTH_CURRENT_TTL.total_seconds()
            ),
            "expired_ttl_seconds": int(
                SOURCE_HEALTH_EXPIRED_TTL.total_seconds()
            ),
            "is_current": False,
            "is_expired": False,
        }
    age = max(normalized_generated_at - normalized_checked_at, timedelta())
    status = (
        "current"
        if age <= SOURCE_HEALTH_CURRENT_TTL
        else "stale"
        if age <= SOURCE_HEALTH_EXPIRED_TTL
        else "expired"
    )
    return {
        "status": status,
        "checked_at": normalized_checked_at.isoformat(),
        "age_seconds": int(age.total_seconds()),
        "current_ttl_seconds": int(
            SOURCE_HEALTH_CURRENT_TTL.total_seconds()
        ),
        "expired_ttl_seconds": int(
            SOURCE_HEALTH_EXPIRED_TTL.total_seconds()
        ),
        "is_current": status == "current",
        "is_expired": status == "expired",
    }


def _row_dict(
    row: SourceHealthSnapshot,
    *,
    generated_at: datetime,
    event_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = source_health_snapshot_to_dict(
        row,
        now=generated_at,
        stale_after_seconds=int(SOURCE_HEALTH_CURRENT_TTL.total_seconds()),
    )
    row_freshness = _snapshot_freshness(
        checked_at=row.checked_at,
        generated_at=generated_at,
    )
    output["storage"] = "persisted_source_health_snapshot"
    output["row_snapshot_freshness"] = row_freshness
    output["snapshot_lifecycle"] = (
        "historical_expired"
        if row_freshness["status"] == "expired"
        else "active_canonical_scope"
        if str(row.target or "all") == "all"
        else "active_target_specific"
    )
    output["event_diagnostics"] = event_diagnostics or {
        "last_success_at": None,
        "last_error_at": None,
        "last_event_duration_ms": None,
        "fallback": {
            "observed": False,
            "reason": "not_observed_in_bounded_event_scan",
        },
    }
    return output


def _event_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(event.get("market") or "").lower(),
        str(event.get("resource") or ""),
        str(event.get("target") or "all"),
        str(event.get("provider") or "all").lower(),
    )


def _snapshot_key(row: SourceHealthSnapshot) -> tuple[str, str, str, str]:
    return (
        str(row.market or "").lower(),
        str(row.resource or ""),
        str(row.target or "all"),
        str(row.provider or "all").lower(),
    )


def _bounded_event_diagnostics(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for event in events:
        key = _event_key(event)
        current = output.setdefault(
            key,
            {
                "last_success_at": None,
                "last_error_at": None,
                "last_event_duration_ms": None,
                "fallback": {
                    "observed": False,
                    "reason": "not_observed_in_bounded_event_scan",
                },
            },
        )
        event_time = event.get("event_time")
        status = str(event.get("status") or "").lower()
        if current["last_event_duration_ms"] is None:
            current["last_event_duration_ms"] = event.get("duration_ms")
        if (
            current["last_success_at"] is None
            and status in {"success", "ok", "completed"}
        ):
            current["last_success_at"] = event_time
        if current["last_error_at"] is None and status in ERROR_STATUSES:
            current["last_error_at"] = event_time
        if (
            not current["fallback"]["observed"]
            and str(event.get("event_type") or "").lower() == "fallback"
        ):
            detail = (
                event.get("detail")
                if isinstance(event.get("detail"), dict)
                else {}
            )
            current["fallback"] = {
                "observed": True,
                "event_at": event_time,
                "primary_provider": (
                    detail.get("primary_provider")
                    or event.get("provider")
                ),
                "fallback_provider": detail.get("fallback_provider"),
                "switch_reason": (
                    detail.get("switch_reason")
                    or event.get("error_message")
                    or event.get("message")
                ),
                "operation": detail.get("operation"),
            }
    return output


def read_unified_source_health_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None,
    now: Any,
) -> dict[str, Any]:
    params = market_data_params if isinstance(market_data_params, dict) else {}
    generated_at = now()
    if not isinstance(generated_at, datetime):
        generated_at = datetime.now(timezone.utc)
    requested_market = str(params.get("market") or "").strip().lower() or None
    requested_resource = str(params.get("resource") or "").strip() or None
    requested_target = str(params.get("symbol") or params.get("target") or "").strip() or None
    requested_provider = str(params.get("provider") or "").strip().lower() or None
    problems_only = params.get("problems_only") is True
    include_healthy_requested = params.get("include_healthy") is not False
    include_healthy = include_healthy_requested and not problems_only
    raw_status_filter = params.get("status_filter")
    if isinstance(raw_status_filter, str):
        requested_statuses = tuple(
            dict.fromkeys(
                part.strip().lower()
                for part in raw_status_filter.split(",")
                if part.strip()
            )
        )
    elif isinstance(raw_status_filter, (list, tuple, set)):
        requested_statuses = tuple(
            dict.fromkeys(
                str(value).strip().lower()
                for value in raw_status_filter
                if str(value).strip()
            )
        )
    else:
        requested_statuses = ()
    row_limit = bounded_int_param(
        params,
        ("limit", "health_limit"),
        default=200,
        minimum=1,
        maximum=500,
    )
    event_scan_limit = bounded_int_param(
        params,
        ("event_scan_limit",),
        default=max(100, min(row_limit * 5, 1_000)),
        minimum=1,
        maximum=5_000,
    )
    level = payload_level(params)

    latest_checked = (
        db.query(
            SourceHealthSnapshot.market.label("market"),
            SourceHealthSnapshot.resource.label("resource"),
            SourceHealthSnapshot.target.label("target"),
            SourceHealthSnapshot.provider.label("provider"),
            func.max(SourceHealthSnapshot.checked_at).label("checked_at"),
        )
        .group_by(
            SourceHealthSnapshot.market,
            SourceHealthSnapshot.resource,
            SourceHealthSnapshot.target,
            SourceHealthSnapshot.provider,
        )
        .subquery()
    )
    snapshot = aliased(SourceHealthSnapshot)
    base_query = db.query(snapshot).join(
        latest_checked,
        and_(
            snapshot.market == latest_checked.c.market,
            snapshot.resource == latest_checked.c.resource,
            snapshot.target == latest_checked.c.target,
            snapshot.provider == latest_checked.c.provider,
            snapshot.checked_at == latest_checked.c.checked_at,
        ),
    )
    if requested_market:
        base_query = base_query.filter(
            func.lower(snapshot.market) == requested_market
        )
    if requested_resource:
        base_query = base_query.filter(snapshot.resource == requested_resource)
    if requested_target:
        base_query = base_query.filter(snapshot.target == requested_target)
    if requested_provider:
        base_query = base_query.filter(
            func.lower(snapshot.provider) == requested_provider
        )
    total_status_count_rows = (
        base_query.order_by(None)
        .with_entities(snapshot.status, func.count())
        .group_by(snapshot.status)
        .all()
    )
    total_market_count_rows = (
        base_query.order_by(None)
        .with_entities(snapshot.market, func.count())
        .group_by(snapshot.market)
        .all()
    )
    total_status_counts = {
        str(status or "unknown"): int(count or 0)
        for status, count in total_status_count_rows
    }
    total_market_counts = {
        str(market or "unknown"): int(count or 0)
        for market, count in total_market_count_rows
    }
    total_entry_count = sum(total_status_counts.values())
    total_problem_count = sum(
        count
        for status, count in total_status_counts.items()
        if status in PROBLEM_STATUSES
    )
    query = base_query
    if requested_statuses:
        query = query.filter(func.lower(snapshot.status).in_(requested_statuses))
    if problems_only or not include_healthy:
        query = query.filter(func.lower(snapshot.status).in_(PROBLEM_STATUSES))
    matched_status_count_rows = (
        query.order_by(None)
        .with_entities(snapshot.status, func.count())
        .group_by(snapshot.status)
        .all()
    )
    matched_market_count_rows = (
        query.order_by(None)
        .with_entities(snapshot.market, func.count())
        .group_by(snapshot.market)
        .all()
    )
    matched_status_counts = {
        str(status or "unknown"): int(count or 0)
        for status, count in matched_status_count_rows
    }
    matched_market_counts = {
        str(market or "unknown"): int(count or 0)
        for market, count in matched_market_count_rows
    }
    matched_entry_count = sum(matched_status_counts.values())
    matched_problem_count = sum(
        count
        for status, count in matched_status_counts.items()
        if status in PROBLEM_STATUSES
    )
    checked_at_range = query.order_by(None).with_entities(
        func.min(snapshot.checked_at),
        func.max(snapshot.checked_at),
    ).one()
    oldest_checked_at, latest_checked_at = checked_at_range
    current_threshold = generated_at - SOURCE_HEALTH_CURRENT_TTL
    expired_threshold = generated_at - SOURCE_HEALTH_EXPIRED_TTL
    current_snapshot_count = query.filter(
        snapshot.checked_at >= current_threshold
    ).count()
    expired_snapshot_count = query.filter(
        snapshot.checked_at < expired_threshold
    ).count()
    stale_snapshot_count = max(
        matched_entry_count
        - current_snapshot_count
        - expired_snapshot_count,
        0,
    )
    rows = (
        query.order_by(
            snapshot.market.asc(),
            snapshot.resource.asc(),
            snapshot.target.asc(),
        )
        .limit(row_limit)
        .all()
    )
    recent_events = list_provider_events(
        db,
        market=requested_market,
        provider=requested_provider,
        resource=requested_resource,
        target=requested_target,
        limit=event_scan_limit,
    )
    event_diagnostics = _bounded_event_diagnostics(recent_events)
    entries = [
        _row_dict(
            row,
            generated_at=generated_at,
            event_diagnostics=event_diagnostics.get(_snapshot_key(row)),
        )
        for row in rows
    ]

    returned_status_counts: dict[str, int] = {}
    returned_market_counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get("status") or "unknown")
        market = str(entry.get("market") or "unknown")
        returned_status_counts[status] = (
            returned_status_counts.get(status, 0) + 1
        )
        returned_market_counts[market] = (
            returned_market_counts.get(market, 0) + 1
        )
    returned_problem_count = sum(
        count
        for status, count in returned_status_counts.items()
        if status in PROBLEM_STATUSES
    )
    recent_error_count = sum(
        int(entry.get("recent_error_count") or 0)
        for entry in entries
    )
    consecutive_error_count = sum(
        int(entry.get("consecutive_error_count") or 0)
        for entry in entries
    )
    fallback_observed_count = sum(
        bool(
            ((entry.get("event_diagnostics") or {}).get("fallback") or {}).get(
                "observed"
            )
        )
        for entry in entries
    )
    age_bucket_count = sum(
        count > 0
        for count in (
            current_snapshot_count,
            stale_snapshot_count,
            expired_snapshot_count,
        )
    )
    aggregate_status = (
        "missing"
        if matched_entry_count == 0
        else "mixed"
        if age_bucket_count > 1
        else "current"
        if current_snapshot_count
        else "stale"
        if stale_snapshot_count
        else "expired"
    )
    newest_freshness = _snapshot_freshness(
        checked_at=latest_checked_at,
        generated_at=generated_at,
    )
    oldest_freshness = _snapshot_freshness(
        checked_at=oldest_checked_at,
        generated_at=generated_at,
    )
    freshness = {
        "status": aggregate_status,
        "is_current": aggregate_status == "current",
        "is_complete": matched_entry_count == len(entries),
        "oldest_checked_at": _json_value(oldest_checked_at),
        "newest_checked_at": _json_value(latest_checked_at),
        "oldest_age_seconds": oldest_freshness.get("age_seconds"),
        "newest_age_seconds": newest_freshness.get("age_seconds"),
        "mixed_snapshot_ages": age_bucket_count > 1,
        "current_entry_count": current_snapshot_count,
        "stale_entry_count": stale_snapshot_count,
        "expired_entry_count": expired_snapshot_count,
        "current_ttl_seconds": int(SOURCE_HEALTH_CURRENT_TTL.total_seconds()),
        "expired_ttl_seconds": int(SOURCE_HEALTH_EXPIRED_TTL.total_seconds()),
    }
    missing = [] if entries else ["source_health_snapshot"]
    warnings: list[str] = []
    if not entries:
        warnings.append("No persisted source-health snapshots match the requested filters.")
    if matched_problem_count:
        warnings.append(
            "Unified source health contains "
            f"{matched_problem_count} matched non-current or failed entries."
        )
    if freshness["status"] == "mixed":
        warnings.append(
            "Source-health snapshots have mixed ages; inspect each row's "
            "row_snapshot_freshness before using the aggregate."
        )
    elif freshness["status"] == "stale":
        warnings.append(
            "Source-health snapshot is stale; checked_at is older than one hour."
        )
    elif freshness["status"] == "expired":
        warnings.append(
            "Source-health snapshot is expired; checked_at is older than 24 hours."
        )

    target = {
        "type": "source_health",
        "id": requested_market or "all",
        "label": f"{requested_market.upper()} source health" if requested_market else "All market source health",
        "market": requested_market or "all",
    }
    status = (
        "missing"
        if not entries
        else str(freshness["status"])
        if freshness["status"] in {"stale", "expired"}
        else "partial"
        if matched_problem_count or freshness["status"] == "mixed"
        else "ready"
    )
    slots = {
        "health_entries": slot_envelope(
            status=status,
            capability="unified_source_health_snapshots",
            payload_ref="data.entries",
            payload_level=level,
            priority="core",
            as_of=_json_value(latest_checked_at),
            missing=missing,
        ),
        "provider_events": slot_envelope(
            status="not_requested",
            capability="provider_event_details",
            payload_level=level,
            next_fill="Use the dedicated bounded provider-events endpoint when event-level diagnostics are required.",
        ),
        "data_quality": slot_envelope(
            status=status,
            capability="health_snapshot_coverage",
            payload_ref="data.summary",
            payload_level=level,
            priority="core",
            missing=missing,
            warnings=warnings,
        ),
    }
    envelope = {
        "kind": "unified_source_health_context",
        "generated_at": generated_at,
        "as_of": _json_value(latest_checked_at),
        "scope": {"target": target},
        "data": {
            "filters": {
                "market": requested_market,
                "resource": requested_resource,
                "target": requested_target,
                "provider": requested_provider,
                "problems_only": problems_only,
                "include_healthy_requested": include_healthy_requested,
                "include_healthy": include_healthy,
                "status_filter": list(requested_statuses),
                "limit": row_limit,
                "event_scan_limit": event_scan_limit,
            },
            "summary": {
                "entry_count": matched_entry_count,
                "total_entry_count": total_entry_count,
                "matched_entry_count": matched_entry_count,
                "returned_entry_count": len(entries),
                "problem_count": matched_problem_count,
                "total_problem_count": total_problem_count,
                "matched_problem_count": matched_problem_count,
                "returned_problem_count": returned_problem_count,
                "status_counts": matched_status_counts,
                "total_status_counts": total_status_counts,
                "returned_status_counts": returned_status_counts,
                "market_counts": matched_market_counts,
                "total_market_counts": total_market_counts,
                "returned_market_counts": returned_market_counts,
                "recent_error_count": recent_error_count,
                "consecutive_error_count": consecutive_error_count,
                "fallback_observed_count": fallback_observed_count,
                "event_scan_count": len(recent_events),
                "event_scan_truncated": len(recent_events) >= event_scan_limit,
            },
            "entries": entries,
            "returned_count": len(entries),
            "truncated": matched_entry_count > len(entries),
            "is_partial": matched_entry_count > len(entries),
            "freshness": freshness,
            "compact": {
                "kind": "unified_source_health_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "resources": {
                    "entry_count": matched_entry_count,
                    "total_entry_count": total_entry_count,
                    "matched_entry_count": matched_entry_count,
                    "returned_entry_count": len(entries),
                    "problem_count": matched_problem_count,
                    "total_problem_count": total_problem_count,
                    "matched_problem_count": matched_problem_count,
                    "returned_problem_count": returned_problem_count,
                    "status_counts": matched_status_counts,
                    "total_status_counts": total_status_counts,
                    "market_counts": matched_market_counts,
                    "total_market_counts": total_market_counts,
                },
                "freshness_by_domain": {
                    "source_health": freshness["status"]
                },
                "freshness": freshness,
                "slots": slots,
            },
            "slots": slots,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [{"type": "table", "name": "source_health_snapshot"}],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={
            **freshness,
            "missing": missing,
        },
    )
    return envelope
