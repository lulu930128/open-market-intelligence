from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope


@dataclass(frozen=True)
class MacroContextDependencies:
    us_market_service: Any
    now: Any


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _freshness_threshold_days(frequency: str | None) -> int:
    normalized = (frequency or "").strip().lower()
    if "daily" in normalized:
        return 10
    if "week" in normalized:
        return 21
    if "quarter" in normalized:
        return 150
    return 50


def read_us_macro_context(
    db: Session,
    *,
    series_id: str,
    market_data_params: dict[str, Any] | None,
    dependencies: MacroContextDependencies,
) -> dict[str, Any]:
    normalized_series_id = str(series_id or "").strip().upper()
    if not normalized_series_id or not re.fullmatch(r"[A-Z0-9._-]{1,80}", normalized_series_id):
        raise ValueError("US macro target.id must be a valid FRED series id.")
    row_limit = bounded_int_param(
        market_data_params,
        ("limit", "observations", "bars"),
        default=120,
        minimum=1,
        maximum=240,
    )
    level = payload_level(market_data_params)
    rows = dependencies.us_market_service.list_macro_series_observations(
        db,
        series_id=normalized_series_id,
        limit=row_limit,
    )
    observations = [
        {
            "provider": row.provider,
            "series_id": row.series_id,
            "series_name": row.series_name,
            "observation_date": _json_value(row.observation_date),
            "value": row.value,
            "unit": row.unit,
            "frequency": row.frequency,
            "source_url": row.source_url,
            "fetched_at": _json_value(row.fetched_at),
        }
        for row in reversed(rows)
    ]
    latest = rows[0] if rows else None
    now_value = dependencies.now()
    now_date = now_value.date() if isinstance(now_value, datetime) else datetime.now(timezone.utc).date()
    age_days = (now_date - latest.observation_date).days if latest else None
    threshold_days = _freshness_threshold_days(latest.frequency if latest else None)
    is_current = bool(latest and age_days is not None and age_days <= threshold_days)
    missing = [] if latest else [f"macro_series.{normalized_series_id}"]
    warnings = [
        "FRED macro observations have their own release cadence and must not be treated as realtime market signals.",
        "External FRED refresh requires FRED_API_KEY and remains behind the bounded refresh/tool policy.",
    ]
    if latest and not is_current:
        warnings.append(
            f"Macro cache may be stale for its reported frequency: age_days={age_days}, threshold_days={threshold_days}."
        )

    target = {
        "type": "us_macro",
        "id": normalized_series_id,
        "label": latest.series_name if latest and latest.series_name else normalized_series_id,
        "market": "US",
    }
    observation_status = "ready" if latest and is_current else "stale" if latest else "missing"
    slots = {
        "identity": slot_envelope(
            status="ready",
            capability="macro_series_identity",
            payload_ref="data.series",
            payload_level=level,
            priority="core",
        ),
        "observations": slot_envelope(
            status=observation_status,
            capability="macro_series_observations",
            payload_ref="data.observations",
            payload_level=level,
            priority="core",
            as_of=_json_value(latest.observation_date) if latest else None,
            missing=missing,
        ),
        "release_calendar": slot_envelope(
            status="partial" if latest else "planned",
            capability="macro_release_calendar",
            payload_ref="data.series.frequency",
            payload_level=level,
            next_fill="Add a bounded official release-calendar provider before treating expected release times as authoritative.",
        ),
        "data_quality": slot_envelope(
            status=observation_status,
            capability="macro_freshness",
            payload_ref="data.freshness",
            payload_level=level,
            priority="core",
            missing=missing,
            warnings=warnings,
        ),
    }
    envelope = {
        "kind": "us_macro_context",
        "generated_at": now_value,
        "as_of": _json_value(latest.observation_date) if latest else None,
        "scope": {"target": target},
        "data": {
            "series": {
                "series_id": normalized_series_id,
                "series_name": latest.series_name if latest else None,
                "unit": latest.unit if latest else None,
                "frequency": latest.frequency if latest else None,
                "provider": latest.provider if latest else "fred",
            },
            "observations": observations,
            "freshness": {
                "status": observation_status,
                "is_current": is_current,
                "age_days": age_days,
                "threshold_days": threshold_days,
                "latest_observation_date": _json_value(latest.observation_date) if latest else None,
                "latest_fetched_at": _json_value(latest.fetched_at) if latest else None,
            },
            "compact": {
                "kind": "us_macro_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "resources": {
                    "observation_rows": len(observations),
                    "latest_value": latest.value if latest else None,
                    "unit": latest.unit if latest else None,
                    "frequency": latest.frequency if latest else None,
                },
                "freshness_by_domain": {"observations": observation_status},
                "slots": slots,
            },
            "slots": slots,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "macro_series_observation"},
            {"type": "official", "name": "fred", "provider": "fred"},
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={"is_current": is_current, "missing": missing},
    )
    return envelope
