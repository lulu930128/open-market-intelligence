from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope
from app.db.models import SourceHealthSnapshot


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: SourceHealthSnapshot) -> dict[str, Any]:
    fields = (
        "market",
        "resource",
        "target",
        "provider",
        "status",
        "ok",
        "required",
        "data_quality",
        "latest_data_date",
        "latest_data_key",
        "latest_observed_at",
        "expected_data_date",
        "release_status",
        "reason",
        "latest_event_status",
        "latest_event_severity",
        "latest_event_at",
        "checked_at",
    )
    return {field: _json_value(getattr(row, field, None)) for field in fields}


def read_unified_source_health_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None,
    now: Any,
) -> dict[str, Any]:
    params = market_data_params if isinstance(market_data_params, dict) else {}
    requested_market = str(params.get("market") or "").strip().lower() or None
    requested_resource = str(params.get("resource") or "").strip() or None
    requested_target = str(params.get("symbol") or params.get("target") or "").strip() or None
    row_limit = bounded_int_param(
        params,
        ("limit", "health_limit"),
        default=200,
        minimum=1,
        maximum=500,
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
    query = db.query(snapshot).join(
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
        query = query.filter(func.lower(snapshot.market) == requested_market)
    if requested_resource:
        query = query.filter(snapshot.resource == requested_resource)
    if requested_target:
        query = query.filter(snapshot.target == requested_target)
    rows = query.order_by(snapshot.market.asc(), snapshot.resource.asc(), snapshot.target.asc()).limit(row_limit).all()
    entries = [_row_dict(row) for row in rows]

    counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get("status") or "unknown")
        market = str(entry.get("market") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        market_counts[market] = market_counts.get(market, 0) + 1
    problem_statuses = {"missing", "empty", "stale", "delayed", "error", "blocked", "disabled"}
    problem_count = sum(count for status, count in counts.items() if status in problem_statuses)
    latest_checked_at = max(
        (row.checked_at for row in rows if isinstance(row.checked_at, datetime)),
        default=None,
    )
    missing = [] if entries else ["source_health_snapshot"]
    warnings: list[str] = []
    if not entries:
        warnings.append("No persisted source-health snapshots match the requested filters.")
    if problem_count:
        warnings.append(f"Unified source health contains {problem_count} non-current or failed entries.")

    target = {
        "type": "source_health",
        "id": requested_market or "all",
        "label": f"{requested_market.upper()} source health" if requested_market else "All market source health",
        "market": requested_market or "all",
    }
    status = "missing" if not entries else "partial" if problem_count else "ready"
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
        "generated_at": now(),
        "as_of": _json_value(latest_checked_at),
        "scope": {"target": target},
        "data": {
            "filters": {
                "market": requested_market,
                "resource": requested_resource,
                "target": requested_target,
                "limit": row_limit,
            },
            "summary": {
                "entry_count": len(entries),
                "problem_count": problem_count,
                "status_counts": counts,
                "market_counts": market_counts,
            },
            "entries": entries,
            "compact": {
                "kind": "unified_source_health_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "resources": {
                    "entry_count": len(entries),
                    "problem_count": problem_count,
                    "status_counts": counts,
                    "market_counts": market_counts,
                },
                "freshness_by_domain": {"source_health": status},
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
        freshness={"is_current": bool(entries) and problem_count == 0, "missing": missing},
    )
    return envelope
