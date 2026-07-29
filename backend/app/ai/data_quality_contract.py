from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import re
from statistics import median
from typing import Any


QUALITY_VERSION = "omi.data.quality.v1"

READY_STATUSES = {
    "available",
    "current",
    "daily_close",
    "final_snapshot",
    "fresh",
    "healthy",
    "historical",
    "latest_completed_session",
    "latest_session_close",
    "live",
    "ok",
    "ready",
}
LIMITED_STATUSES = {
    "cached",
    "delayed",
    "partial",
    "pending",
    "provisional",
    "waiting",
}
NEUTRAL_STATUSES = {
    "not_applicable",
    "not_requested",
}
STATUS_ALIASES = {
    "closed": "latest_session_close",
    "closed_session": "latest_session_close",
    "degraded": "partial",
    "empty": "missing",
    "expired": "stale",
    "latest_close": "latest_completed_session",
}
STATUS_CLASS_SEVERITY = {
    "neutral": 0,
    "ready": 1,
    "limited": 2,
    "blocked": 3,
}
TIME_KEYS = {
    "as_of",
    "bar_time",
    "date",
    "data_date",
    "event_time",
    "latest_data_date",
    "observation_date",
    "quote_time",
    "timestamp",
    "trade_date",
}
OBSERVATION_TIMESTAMP_KEYS = {
    "as_of",
    "bar_time",
    "event_time",
    "quote_time",
    "timestamp",
}
UNIT_KEYS = {
    "base_volume_unit",
    "currency",
    "price_unit",
    "quote_volume_unit",
    "trade_value_unit",
    "unit",
    "volume_unit",
}
VOLUME_UNIT_KEYS = {
    "base_volume_unit",
    "quote_volume_unit",
    "trade_value_unit",
    "volume_unit",
}
VOLUME_KEYS = {
    "base_volume",
    "current_cumulative_trade_value",
    "one_minute_trade_value_change",
    "previous_minute_cumulative_trade_value",
    "quote_volume",
    "total_volume",
    "total_volume_lots",
    "trade_value",
    "volume",
}
PRICE_KEYS = {
    "current_price",
    "display_price",
    "last_price",
    "latest_price",
    "price",
}
DIAGNOSTIC_SCOPES = {
    "capability_status",
    "data_freshness",
    "source_health",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalized_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    normalized = (
        str(value or "unknown")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    return STATUS_ALIASES.get(normalized, normalized)


def _status_class(value: Any) -> str:
    status = _normalized_status(value)
    if status in READY_STATUSES:
        return "ready"
    if status in LIMITED_STATUSES:
        return "limited"
    if status in NEUTRAL_STATUSES:
        return "neutral"
    return "blocked"


def _iter_values(
    value: Any,
    *,
    keys: set[str],
    depth: int = 0,
) -> list[tuple[str, Any]]:
    if depth > 6:
        return []
    output: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in keys:
                output.append((normalized_key, item))
            if isinstance(item, (dict, list)):
                output.extend(_iter_values(item, keys=keys, depth=depth + 1))
    elif isinstance(value, list):
        for item in value[:500]:
            if isinstance(item, (dict, list)):
                output.extend(_iter_values(item, keys=keys, depth=depth + 1))
    return output


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _temporal_summary(value: Any) -> dict[str, Any]:
    observations: list[dict[str, str]] = []
    for key, raw_value in _iter_values(value, keys=TIME_KEYS):
        parsed = _parse_datetime(raw_value)
        if parsed is None:
            continue
        observations.append(
            {
                "field": key,
                "value": str(raw_value),
                "date": parsed.date().isoformat(),
            }
        )
    dates = sorted({item["date"] for item in observations})
    return {
        "latest_date": dates[-1] if dates else None,
        "dates": dates[-12:],
        "mixed_dates": len(dates) > 1,
        "observations": observations[-20:],
    }


def _unit_summary(value: Any) -> dict[str, Any]:
    declared_unit_values = _iter_values(value, keys=UNIT_KEYS)
    units = {
        str(raw_value).strip()
        for _, raw_value in declared_unit_values
        if str(raw_value or "").strip()
    }
    declared_volume_unit_keys = {
        key
        for key, raw_value in declared_unit_values
        if key in VOLUME_UNIT_KEYS and str(raw_value or "").strip()
    }
    volume_fields = {
        key
        for key, raw_value in _iter_values(value, keys=VOLUME_KEYS)
        if raw_value is not None
    }
    missing_unit_fields: list[str] = []
    share_volume_fields = volume_fields & {
        "base_volume",
        "total_volume",
        "total_volume_lots",
        "volume",
    }
    if share_volume_fields and not (
        {"base_volume_unit", "volume_unit"} & declared_volume_unit_keys
    ):
        missing_unit_fields.extend(sorted(share_volume_fields))
    if "quote_volume" in volume_fields and not (
        {"quote_volume_unit", "volume_unit"} & declared_volume_unit_keys
    ):
        missing_unit_fields.append("quote_volume")
    trade_value_fields = volume_fields & {
        "current_cumulative_trade_value",
        "one_minute_trade_value_change",
        "previous_minute_cumulative_trade_value",
        "trade_value",
    }
    if trade_value_fields and "trade_value_unit" not in declared_volume_unit_keys:
        missing_unit_fields.extend(sorted(trade_value_fields))
    missing_volume_unit = bool(missing_unit_fields)
    return {
        "status": "unknown" if missing_volume_unit else "declared" if units else "not_present",
        "units": sorted(units),
        "volume_fields": sorted(volume_fields),
        "missing_volume_unit": missing_volume_unit,
        "missing_unit_fields": list(dict.fromkeys(missing_unit_fields)),
    }


def _interval_seconds(value: Any) -> float | None:
    interval_values: list[tuple[str, Any]] = []
    for key in (
        "effective_interval",
        "interval",
        "bar_interval",
        "frequency",
        "source_interval",
    ):
        interval_values.extend(_iter_values(value, keys={key}))
    for _, raw_value in interval_values:
        text = str(raw_value or "").strip().lower()
        match = re.fullmatch(r"(\d+)\s*([smhd])", text)
        if not match:
            continue
        amount = int(match.group(1))
        multiplier = {
            "s": 1,
            "m": 60,
            "h": 3_600,
            "d": 86_400,
        }[match.group(2)]
        return float(amount * multiplier)
    return None


def _series_points(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    if isinstance(value, dict):
        for key in ("points", "bars"):
            candidate = value.get(key)
            if isinstance(candidate, list) and candidate and all(
                isinstance(item, dict) for item in candidate
            ):
                return candidate[:500]
        for item in value.values():
            if isinstance(item, (dict, list)):
                candidate = _series_points(item, depth=depth + 1)
                if candidate:
                    return candidate
    elif isinstance(value, list):
        for item in value[:50]:
            candidate = _series_points(item, depth=depth + 1)
            if candidate:
                return candidate
    return []


def _point_time(point: dict[str, Any]) -> datetime | None:
    for key in (
        "bar_time",
        "event_time",
        "quote_time",
        "timestamp",
        "time",
        "datetime",
    ):
        if key in point:
            parsed = _parse_datetime(point.get(key))
            if parsed is not None:
                return parsed
    return None


def _is_known_jp_lunch_gap(
    previous: datetime,
    current: datetime,
    *,
    market: str,
) -> bool:
    if market.upper() != "JP" or previous.date() != current.date():
        return False
    return (
        previous.hour == 11
        and previous.minute >= 25
        and current.hour == 12
        and current.minute <= 35
    )


def _has_taiwan_auction_close_evidence(value: Any, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        for key in (
            "session_phase",
            "market_status",
            "quote_semantics",
            "official_close_status",
            "delivery_status",
        ):
            normalized = (
                str(value.get(key) or "")
                .strip()
                .casefold()
                .replace("-", "_")
            )
            if (
                "closing_auction" in normalized
                or "official_close" in normalized
                or (
                    key == "official_close_status"
                    and normalized
                    in {
                        "confirmed",
                        "confirmed_latest_session",
                        "pending",
                    }
                )
                or normalized in {"closed", "post_close", "post_close_snapshot"}
            ):
                return True
        return any(
            _has_taiwan_auction_close_evidence(child, depth=depth + 1)
            for child in value.values()
            if isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(
            _has_taiwan_auction_close_evidence(child, depth=depth + 1)
            for child in value[-100:]
            if isinstance(child, (dict, list))
        )
    return False


def _is_known_taiwan_closing_auction_gap(
    previous: datetime,
    current: datetime,
    *,
    market: str,
    has_auction_close_evidence: bool,
) -> bool:
    if (
        market.upper() not in {"TW", "TAIWAN"}
        or not has_auction_close_evidence
        or previous.date() != current.date()
    ):
        return False
    previous_minutes = previous.hour * 60 + previous.minute
    current_minutes = current.hour * 60 + current.minute
    return (
        (
            13 * 60 + 24 <= previous_minutes <= 13 * 60 + 25
            and 13 * 60 + 30 <= current_minutes <= 13 * 60 + 31
        )
        or (
            13 * 60 + 30 <= previous_minutes <= 13 * 60 + 31
            and 13 * 60 + 32 <= current_minutes <= 13 * 60 + 34
        )
    )


def _market_session_events(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    if isinstance(value, dict):
        events = value.get("market_events")
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]
        rows: list[dict[str, Any]] = []
        for child in value.values():
            if isinstance(child, (dict, list)):
                rows.extend(_market_session_events(child, depth=depth + 1))
        return rows
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for child in value[-100:]:
            if isinstance(child, (dict, list)):
                rows.extend(_market_session_events(child, depth=depth + 1))
        return rows
    return []


def _market_halt_event_for_gap(
    previous: datetime,
    current: datetime,
    *,
    market: str,
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_market = market.strip().upper()
    for event in events:
        if str(event.get("market") or "").strip().upper() != normalized_market:
            continue
        event_type = str(event.get("event_type") or "").strip().casefold()
        if event_type not in {
            "circuit_breaker",
            "market_halt",
            "trading_halt",
            "inferred_market_halt",
        }:
            continue
        halt_start = _parse_datetime(
            event.get("halt_start_at") or event.get("triggered_at")
        )
        resumed_at = _parse_datetime(
            event.get("continuous_trading_resumed_at")
            or event.get("halt_end_at")
        )
        if halt_start is None or resumed_at is None:
            continue
        if (
            halt_start.date() == previous.date() == current.date()
            and halt_start <= current
            and resumed_at >= previous
        ):
            return event
    return None


def _continuity_summary(value: Any, *, market: str) -> dict[str, Any]:
    points = _series_points(value)
    timestamps = [parsed for point in points if (parsed := _point_time(point))]
    expected_seconds = _interval_seconds(value)
    issues: list[str] = []
    gap_count = 0
    duplicate_count = 0
    non_monotonic_count = 0
    recognized_session_gap_count = 0
    market_halt_gap_count = 0
    market_event_refs: list[str] = []
    observed_seconds: list[float] = []
    has_auction_close_evidence = _has_taiwan_auction_close_evidence(value)
    market_events = _market_session_events(value)
    for previous, current in zip(timestamps, timestamps[1:]):
        delta = (current - previous).total_seconds()
        if delta == 0:
            duplicate_count += 1
            continue
        if delta < 0:
            non_monotonic_count += 1
            continue
        if expected_seconds and delta > expected_seconds * 3:
            if _is_known_jp_lunch_gap(previous, current, market=market):
                recognized_session_gap_count += 1
                continue
            elif _is_known_taiwan_closing_auction_gap(
                previous,
                current,
                market=market,
                has_auction_close_evidence=has_auction_close_evidence,
            ):
                recognized_session_gap_count += 1
                continue
            elif halt_event := _market_halt_event_for_gap(
                previous,
                current,
                market=market,
                events=market_events,
            ):
                recognized_session_gap_count += 1
                market_halt_gap_count += 1
                event_id = str(halt_event.get("event_id") or "").strip()
                if event_id and event_id not in market_event_refs:
                    market_event_refs.append(event_id)
                continue
            else:
                gap_count += 1
        observed_seconds.append(delta)
    observed_median = median(observed_seconds) if observed_seconds else None
    interval_mismatch = bool(
        expected_seconds
        and observed_median
        and (
            observed_median < expected_seconds * 0.5
            or observed_median > expected_seconds * 1.5
        )
    )
    if duplicate_count:
        issues.append("duplicate_timestamp")
    if non_monotonic_count:
        issues.append("non_monotonic_timestamp")
    if gap_count:
        issues.append("missing_interval")
    if interval_mismatch:
        issues.append("interval_mismatch")
    if len(timestamps) <= 1 and points:
        issues.append("insufficient_series_points")
    status = (
        "unknown"
        if not timestamps
        else "partial"
        if issues
        else "continuous_with_market_halt"
        if market_halt_gap_count
        else "continuous"
    )
    return {
        "status": status,
        "point_count_inspected": len(points),
        "timestamp_count": len(timestamps),
        "expected_interval_seconds": expected_seconds,
        "observed_median_interval_seconds": observed_median,
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "gap_count": gap_count,
        "recognized_session_gap_count": recognized_session_gap_count,
        "market_halt_gap_count": market_halt_gap_count,
        "gap_reason": "market_halt" if market_halt_gap_count else None,
        "market_event_refs": market_event_refs,
        "session_gap_evidence": (
            "market_event"
            if market_halt_gap_count
            else
            "closing_auction_or_official_close"
            if market.upper() in {"TW", "TAIWAN"}
            and has_auction_close_evidence
            else None
        ),
        "issues": issues,
    }


def _price_value(value: Any) -> float | None:
    for key, raw_value in _iter_values(value, keys=PRICE_KEYS):
        if key not in PRICE_KEYS:
            continue
        if isinstance(raw_value, bool):
            continue
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            continue
    return None


def _candidate(
    *,
    source: str,
    status: Any,
) -> dict[str, str] | None:
    normalized = _normalized_status(status)
    if normalized == "unknown":
        return None
    return {
        "source": source,
        "status": normalized,
        "status_class": _status_class(normalized),
    }


def _release_phase(status: str, payload: Any) -> str:
    explicit_values = _iter_values(
        payload,
        keys={"release_phase", "session_status", "quote_semantics"},
    )
    phase_aliases = {
        "current_session": "current_session",
        "delayed": "delayed",
        "final": "official_final",
        "final_snapshot": "official_final",
        "official_final": "official_final",
        "previous_session": "previous_or_completed_session",
        "provisional": "provisional",
    }
    for _, raw_value in explicit_values:
        normalized = _normalized_status(raw_value)
        if normalized in phase_aliases:
            return phase_aliases[normalized]
    return {
        "live": "live",
        "delayed": "delayed",
        "provisional": "provisional",
        "final_snapshot": "official_final",
        "daily_close": "official_final",
        "latest_completed_session": "previous_or_completed_session",
        "latest_session_close": "previous_or_completed_session",
    }.get(status, "unknown")


def _has_semantic_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_semantic_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_semantic_value(item) for item in value.values())
    return True


def _semantic_payload_empty(capability_id: str, payload: Any) -> bool:
    if capability_id == "ownership.distribution":
        rows = (
            payload
            if isinstance(payload, list)
            else payload.get("distribution")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(rows, list):
            return True
        ownership_fields = {
            "holding_level",
            "holder_count",
            "share_count",
            "share_ratio",
        }
        return not any(
            isinstance(row, dict)
            and any(
                _has_semantic_value(row.get(field))
                for field in ownership_fields
            )
            for row in rows
        )
    return not _has_semantic_value(payload)


def _has_payload_provenance(payload: Any) -> bool:
    populated_keys = {
        key
        for key, raw_value in _iter_values(
            payload,
            keys={"provider", "source"},
        )
        if str(raw_value or "").strip()
    }
    return {"provider", "source"}.issubset(populated_keys)


def _has_payload_observation_timestamp(payload: Any) -> bool:
    return any(
        _parse_datetime(raw_value) is not None
        for _, raw_value in _iter_values(
            payload,
            keys=OBSERVATION_TIMESTAMP_KEYS,
        )
    )


def _quality_for_capability(
    item: dict[str, Any],
    *,
    canonical: dict[str, Any],
    projected_data: dict[str, Any],
    realtime_assessments: dict[str, dict[str, Any]],
    market: str,
) -> dict[str, Any]:
    capability_id = str(item.get("capability") or "")
    domain = str(item.get("domain") or "")
    slot_name = str(item.get("slot") or "")
    evidence = _dict(canonical.get("evidence"))
    freshness_by_domain = _dict(evidence.get("freshness_by_domain"))
    freshness_by_capability = _dict(evidence.get("freshness_by_capability"))
    slots = _dict(evidence.get("slots"))
    slot = _dict(slots.get(slot_name))
    realtime = _dict(realtime_assessments.get(capability_id))
    payload = projected_data.get(capability_id)
    payload_freshness = (
        _dict(payload.get("freshness"))
        if isinstance(payload, dict)
        else {}
    )
    projected_payload_included = capability_id in projected_data
    semantic_payload_empty = _semantic_payload_empty(
        capability_id,
        payload,
    )
    payload_included = bool(
        projected_payload_included and not semantic_payload_empty
    )

    candidates = [
        candidate
        for candidate in (
            _candidate(
                source="freshness_by_capability",
                status=freshness_by_capability.get(capability_id),
            ),
            _candidate(
                source="payload.freshness",
                status=payload_freshness.get("status"),
            ),
            _candidate(
                source="freshness_by_domain",
                status=freshness_by_domain.get(domain),
            )
            if domain
            else None,
            _candidate(source="slot", status=slot.get("status")),
            _candidate(source="slot.freshness", status=_dict(slot.get("freshness")).get("status")),
            _candidate(source="realtime", status=realtime.get("state")),
            _candidate(source="manifest", status=item.get("status")),
        )
        if candidate is not None
    ]
    if payload_included:
        candidates.append(
            {
                "source": "payload",
                "status": "available",
                "status_class": "ready",
            }
        )
    elif bool(item.get("required")):
        candidates.append(
            {
                "source": "payload",
                "status": "missing",
                "status_class": "blocked",
            }
        )

    candidates_by_source = {
        str(candidate["source"]): candidate for candidate in candidates
    }
    canonical_candidate = next(
        (
            candidates_by_source[source]
            for source in (
                "realtime",
                "freshness_by_capability",
                "payload.freshness",
                "slot.freshness",
                "freshness_by_domain",
                "payload",
                "slot",
                "manifest",
            )
            if source in candidates_by_source
        ),
        {
            "source": "default",
            "status": "unknown",
            "status_class": "blocked",
        },
    )
    realtime_policy_unsatisfied = bool(
        realtime and realtime.get("policy_satisfied") is False
    )
    if realtime_policy_unsatisfied:
        canonical_candidate = {
            "source": "realtime_policy",
            "status": "live_requirement_not_satisfied",
            "status_class": "blocked",
        }
    if not payload_included and canonical_candidate["status_class"] != "neutral":
        canonical_candidate = {
            "source": "payload",
            "status": "missing",
            "status_class": "blocked",
        }
    status_classes = {candidate["status_class"] for candidate in candidates}
    contradiction_codes: list[str] = []
    if "ready" in status_classes and ({"limited", "blocked"} & status_classes):
        contradiction_codes.append("status_sources_disagree")
    if "neutral" in status_classes and ({"ready", "limited", "blocked"} & status_classes):
        contradiction_codes.append("applicability_sources_disagree")

    temporal = _temporal_summary(payload)
    units = _unit_summary(payload)
    continuity = (
        _continuity_summary(payload, market=market)
        if capability_id == "intraday.bars"
        else {
            "status": "not_applicable",
            "point_count_inspected": 0,
            "timestamp_count": 0,
            "issues": [],
        }
    )
    status = canonical_candidate["status"]
    status_class = canonical_candidate["status_class"]
    capability_freshness_status = (
        _normalized_status(freshness_by_capability.get(capability_id))
        if freshness_by_capability.get(capability_id) is not None
        else None
    )
    completeness = (
        "not_applicable"
        if status_class == "neutral"
        else "empty"
        if not payload_included
        else "partial"
        if status_class == "limited" or continuity.get("status") == "partial"
        else "complete"
    )
    decision_usable = bool(
        status_class == "ready"
        and continuity.get("status") != "partial"
        and not units["missing_volume_unit"]
    )
    stale_intraday_facts_usable = bool(
        capability_id == "intraday.bars"
        and payload_included
        and status == "stale"
        and temporal.get("latest_date")
        and _has_payload_observation_timestamp(payload)
        and _has_payload_provenance(payload)
        and continuity.get("status") != "partial"
        and not units["missing_volume_unit"]
    )
    stale_quote_facts_usable = bool(
        capability_id == "quote.snapshot"
        and payload_included
        and status == "stale"
        and temporal.get("latest_date")
        and _has_payload_observation_timestamp(payload)
        and _has_payload_provenance(payload)
        and _price_value(payload) is not None
    )
    facts_usable = bool(
        payload_included
        and (
            status_class in {"ready", "limited"}
            or stale_intraday_facts_usable
            or stale_quote_facts_usable
        )
    )
    contradictions = [
        {
            "code": code,
            "resolved_by": canonical_candidate["source"],
            "affects_facts": False,
            "affects_decision": False,
            "visibility": "debug",
        }
        for code in contradiction_codes
    ]
    issues: list[str] = []
    if semantic_payload_empty:
        issues.append("semantic_payload_empty")
    issues.extend(str(value) for value in continuity.get("issues") or [])
    if units["missing_volume_unit"]:
        issues.append("volume_unit_missing")
    if realtime_policy_unsatisfied:
        issues.append("live_requirement_not_satisfied")
    return {
        "capability": capability_id,
        "domain": item.get("domain"),
        "slot": item.get("slot"),
        "required": bool(item.get("required")),
        "status": status,
        "status_class": status_class,
        "status_authority": canonical_candidate["source"],
        "availability": (
            "not_applicable"
            if status_class == "neutral"
            else "available"
            if payload_included
            else "missing"
        ),
        "freshness": (
            realtime.get("state")
            or capability_freshness_status
            or payload_freshness.get("status")
            or _dict(slot.get("freshness")).get("status")
            or freshness_by_domain.get(domain)
            or status
        ),
        "completeness": completeness,
        "release_phase": _release_phase(
            str(realtime.get("state") or status),
            payload,
        ),
        "facts_usable": facts_usable,
        "decision_usable": decision_usable,
        "payload_included": payload_included,
        "temporal": temporal,
        "units": units,
        "continuity": continuity,
        "status_evidence": candidates,
        "contradictions": contradictions,
        "issues": list(dict.fromkeys(issues)),
    }


def _fusion_issues(
    capabilities: dict[str, dict[str, Any]],
    *,
    projected_data: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    quote = capabilities.get("quote.snapshot")
    technical = capabilities.get("technical.structure")
    if quote and technical:
        quote_date = _dict(quote.get("temporal")).get("latest_date")
        technical_date = _dict(technical.get("temporal")).get("latest_date")
        quote_price = _price_value(projected_data.get("quote.snapshot"))
        technical_price = _price_value(projected_data.get("technical.structure"))
        if (
            quote_date
            and technical_date
            and quote_date != technical_date
            and quote_price is not None
            and technical_price is not None
            and quote_price != technical_price
        ):
            technical["decision_usable"] = False
            technical["issues"] = list(
                dict.fromkeys(
                    [
                        *technical.get("issues", []),
                        "price_basis_date_mismatch",
                    ]
                )
            )
            issues.append(
                {
                    "code": "price_basis_date_mismatch",
                    "severity": "blocked",
                    "capabilities": [
                        "quote.snapshot",
                        "technical.structure",
                    ],
                    "detail": (
                        f"quote={quote_price}@{quote_date}; "
                        f"technical={technical_price}@{technical_date}"
                    ),
                }
            )

    daily = capabilities.get("daily.ohlcv")
    if quote and daily:
        quote_date = _dict(quote.get("temporal")).get("latest_date")
        daily_date = _dict(daily.get("temporal")).get("latest_date")
        if quote_date and daily_date and quote_date != daily_date:
            daily["decision_usable"] = False
            daily["issues"] = list(
                dict.fromkeys(
                    [
                        *daily.get("issues", []),
                        "quote_daily_date_mismatch",
                    ]
                )
            )
            issues.append(
                {
                    "code": "quote_daily_date_mismatch",
                    "severity": "blocked",
                    "capabilities": [
                        "quote.snapshot",
                        "daily.ohlcv",
                    ],
                    "detail": f"quote_date={quote_date}; daily_date={daily_date}",
                }
            )

    quote_date = _dict(quote.get("temporal")).get("latest_date") if quote else None
    for capability_id in ("chips.institutional", "chips.margin"):
        item = capabilities.get(capability_id)
        if not item or not quote_date:
            continue
        item_date = _dict(item.get("temporal")).get("latest_date")
        if item_date and item_date != quote_date:
            item["decision_usable"] = False
            item["issues"] = list(
                dict.fromkeys(
                    [
                        *item.get("issues", []),
                        "previous_session_context_only",
                    ]
                )
            )
            issues.append(
                {
                    "code": "previous_session_context_only",
                    "severity": "limited",
                    "capabilities": ["quote.snapshot", capability_id],
                    "detail": f"quote_date={quote_date}; {capability_id}={item_date}",
                }
            )

    cross_market = capabilities.get("cross_market.overnight")
    if cross_market and _dict(cross_market.get("temporal")).get("mixed_dates"):
        cross_market["decision_usable"] = False
        cross_market["issues"] = list(
            dict.fromkeys(
                [
                    *cross_market.get("issues", []),
                    "mixed_component_dates",
                ]
            )
        )
        issues.append(
            {
                "code": "mixed_component_dates",
                "severity": "limited",
                "capabilities": ["cross_market.overnight"],
                "detail": ",".join(
                    _dict(cross_market.get("temporal")).get("dates") or []
                ),
            }
        )

    breadth = capabilities.get("market.breadth")
    market_volume = capabilities.get("market.volume_state")
    if breadth and market_volume:
        breadth_date = _dict(breadth.get("temporal")).get("latest_date")
        volume_date = _dict(market_volume.get("temporal")).get("latest_date")
        if breadth_date and volume_date and breadth_date != volume_date:
            market_volume["decision_usable"] = False
            market_volume["issues"] = list(
                dict.fromkeys(
                    [
                        *market_volume.get("issues", []),
                        "market_state_date_mismatch",
                    ]
                )
            )
            issues.append(
                {
                    "code": "market_state_date_mismatch",
                    "severity": "blocked",
                    "capabilities": [
                        "market.breadth",
                        "market.volume_state",
                    ],
                    "detail": (
                        f"breadth_date={breadth_date}; "
                        f"market_volume_date={volume_date}"
                    ),
                }
            )
    return issues


def build_quality_contract(
    *,
    canonical: dict[str, Any],
    selection: dict[str, Any],
    manifest: dict[str, Any],
    projected_data: dict[str, Any],
    realtime_assessments: dict[str, dict[str, Any]],
    scope_type: str,
) -> dict[str, Any]:
    target = _dict(canonical.get("target"))
    market = str(target.get("market") or "")
    capability_rows = {
        str(item.get("capability")): _quality_for_capability(
            item,
            canonical=canonical,
            projected_data=projected_data,
            realtime_assessments=realtime_assessments,
            market=market,
        )
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict) and item.get("capability")
    }
    fusion_issues = _fusion_issues(
        capability_rows,
        projected_data=projected_data,
    )
    required_rows = [
        item for item in capability_rows.values() if item.get("required")
    ]
    required_data_rows = [
        item
        for item in required_rows
        if item.get("capability") != "target.identity"
    ]
    unmet_required_capabilities = [
        str(item.get("capability"))
        for item in selection.get("unmet_required_capabilities") or []
        if isinstance(item, dict) and str(item.get("capability") or "").strip()
    ]
    blocked_required = [
        str(item["capability"])
        for item in required_rows
        if not item.get("facts_usable")
    ]
    blocked_required.extend(unmet_required_capabilities)
    limited_required = [
        str(item["capability"])
        for item in required_rows
        if item.get("status_class") == "limited"
        or (
            item.get("facts_usable")
            and not item.get("decision_usable")
        )
    ]
    response_ready = bool(
        canonical.get("ok") is not False
        and canonical.get("request_status") == "completed"
    )
    facts_ready = bool(
        response_ready
        and (
            scope_type in DIAGNOSTIC_SCOPES
            and any(item.get("payload_included") for item in required_data_rows)
            or any(item.get("facts_usable") for item in required_data_rows)
        )
    )
    output = str(selection.get("output") or "decision_with_evidence")
    upstream_readiness = _dict(_dict(canonical.get("status")).get("readiness"))
    decision_required = bool(upstream_readiness.get("decision_required"))
    analysis_ready = bool(
        facts_ready
        and scope_type not in DIAGNOSTIC_SCOPES
        and not blocked_required
    )
    decision_ready = bool(
        analysis_ready
        and output != "evidence_only"
        and decision_required
        and upstream_readiness.get("decision_ready")
        and not limited_required
        and not fusion_issues
    )
    overall_status = (
        "blocked"
        if blocked_required
        else "partial"
        if limited_required or fusion_issues
        else "ready"
    )
    trust_level = (
        "low"
        if overall_status == "blocked"
        else "medium"
        if overall_status == "partial"
        else "high"
    )
    issues = list(fusion_issues)
    for capability_id in unmet_required_capabilities:
        issues.append(
            {
                "code": "required_capability_unsupported",
                "severity": "blocked",
                "capabilities": [capability_id],
            }
        )
    for item in capability_rows.values():
        for code in item.get("issues") or []:
            issues.append(
                {
                    "code": str(code),
                    "severity": (
                        "blocked"
                        if item.get("status_class") == "blocked"
                        else "limited"
                    ),
                    "capabilities": [str(item.get("capability"))],
                }
            )
    deduped_issues: list[dict[str, Any]] = []
    seen_issue_keys: set[tuple[str, tuple[str, ...]]] = set()
    for issue in issues:
        key = (
            str(issue.get("code") or ""),
            tuple(str(value) for value in issue.get("capabilities") or []),
        )
        if key in seen_issue_keys:
            continue
        seen_issue_keys.add(key)
        deduped_issues.append(issue)
    return {
        "version": QUALITY_VERSION,
        "scope_type": scope_type,
        "output": output,
        "status": overall_status,
        "trust_level": trust_level,
        "trust_scope": "decision_readiness",
        "response_ready": response_ready,
        "facts_ready": facts_ready,
        "analysis_ready": analysis_ready,
        "decision_ready": decision_ready,
        "blocked_required_capabilities": list(dict.fromkeys(blocked_required)),
        "limited_required_capabilities": list(dict.fromkeys(limited_required)),
        "capabilities": capability_rows,
        "fusion": {
            "status": "blocked" if any(
                issue.get("severity") == "blocked" for issue in fusion_issues
            ) else "partial" if fusion_issues else "ready",
            "issues": fusion_issues,
        },
        "issues": deduped_issues,
        "upstream_readiness": deepcopy(upstream_readiness),
    }


def _slot_status_from_quality(items: list[dict[str, Any]]) -> tuple[str, str]:
    if not items:
        return "not_requested", "not_requested"
    worst = max(
        items,
        key=lambda item: STATUS_CLASS_SEVERITY.get(
            str(item.get("status_class") or "blocked"),
            3,
        ),
    )
    status_class = str(worst.get("status_class") or "blocked")
    if status_class == "ready":
        return "ready", "usable"
    if status_class == "limited":
        return "partial", "limited"
    if status_class == "neutral":
        return str(worst.get("status") or "not_applicable"), "not_applicable"
    return (
        "missing"
        if worst.get("availability") == "missing"
        else "blocked",
        "unusable",
    )


def apply_quality_contract(
    canonical: dict[str, Any],
    *,
    quality: dict[str, Any],
) -> dict[str, Any]:
    evidence = _dict(canonical.get("evidence"))
    evidence["quality"] = deepcopy(quality)
    manifest = _dict(evidence.get("manifest"))
    quality_capabilities = _dict(quality.get("capabilities"))
    for item in _list(manifest.get("capabilities")):
        if not isinstance(item, dict):
            continue
        capability_quality = _dict(
            quality_capabilities.get(str(item.get("capability") or ""))
        )
        if not capability_quality:
            continue
        item["status"] = capability_quality.get("status")
        item["status_class"] = capability_quality.get("status_class")
        item["decision_usable"] = capability_quality.get("decision_usable")
        item["facts_usable"] = capability_quality.get("facts_usable")
        item["quality_ref"] = (
            f"evidence.quality.capabilities.{item.get('capability')}"
        )
    manifest["ready_count"] = sum(
        item.get("status_class") == "ready"
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict)
    )
    manifest["limited_count"] = sum(
        item.get("status_class") == "limited"
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict)
    )
    manifest["blocked_count"] = sum(
        item.get("status_class") == "blocked"
        for item in _list(manifest.get("capabilities"))
        if isinstance(item, dict)
    )
    slots = _dict(evidence.get("slots"))
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for item in quality_capabilities.values():
        if not isinstance(item, dict) or not item.get("slot"):
            continue
        by_slot.setdefault(str(item["slot"]), []).append(item)
    for slot_name, items in by_slot.items():
        slot = _dict(slots.get(slot_name))
        slot_status, usability = _slot_status_from_quality(items)
        worst_item = max(
            items,
            key=lambda item: STATUS_CLASS_SEVERITY.get(
                str(item.get("status_class") or "blocked"),
                3,
            ),
        )
        slot["status"] = slot_status
        slot["usability"] = usability
        slot["decision_usable"] = all(
            bool(item.get("decision_usable"))
            for item in items
            if item.get("required")
        )
        slot["quality_ref"] = "evidence.quality"
        slot["freshness"] = {
            **_dict(slot.get("freshness")),
            "status": (
                worst_item.get("freshness")
                if len(items) == 1
                else quality.get("status")
            ),
        }
        slots[slot_name] = slot
    data_quality_slot = _dict(slots.get("data_quality"))
    data_quality_slot.update(
        {
            "status": (
                "ready"
                if quality.get("status") == "ready"
                else "partial"
                if quality.get("status") == "partial"
                else "blocked"
            ),
            "usability": (
                "usable"
                if quality.get("status") == "ready"
                else "limited"
                if quality.get("status") == "partial"
                else "unusable"
            ),
            "decision_usable": bool(quality.get("decision_ready")),
            "quality_ref": "evidence.quality",
        }
    )
    slots["data_quality"] = data_quality_slot
    evidence["slots"] = slots

    status = _dict(canonical.get("status"))
    previous_readiness = _dict(status.get("readiness"))
    decision_required = bool(previous_readiness.get("decision_required"))
    readiness = {
        **previous_readiness,
        "response_ready": bool(quality.get("response_ready")),
        "facts_ready": bool(quality.get("facts_ready")),
        "analysis_ready": bool(quality.get("analysis_ready")),
        "answer_ready": bool(quality.get("response_ready")),
        "decision_ready": bool(quality.get("decision_ready")),
        "answer_kind": (
            "evidence_only"
            if quality.get("output") == "evidence_only"
            else "decision"
            if decision_required
            else "factual_summary"
        ),
        "decision_blocked": bool(
            decision_required and not quality.get("decision_ready")
        ),
        "evidence_status": quality.get("status"),
        "trust_level": quality.get("trust_level"),
        "blocked_sections": (
            list(
                dict.fromkeys(
                    [
                        *previous_readiness.get("blocked_sections", []),
                        *(
                            ["decision"]
                            if not quality.get("decision_ready")
                            else []
                        ),
                    ]
                )
            )
        ),
    }
    status["readiness"] = readiness
    canonical["status"] = status

    passport = _dict(evidence.get("passport"))
    upstream_source_trust = {
        key: deepcopy(passport.get(key))
        for key in (
            "trust_level",
            "trust_score",
            "summary",
            "reasons",
            "source_breakdown",
        )
        if passport.get(key) is not None
    }
    trust_level = str(quality.get("trust_level") or "low")
    trust_score = {
        "high": 90,
        "medium": 65,
        "low": 30,
    }.get(trust_level, 30)
    selected_domains: dict[str, dict[str, Any]] = {}
    for capability_id, item in _dict(quality.get("capabilities")).items():
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        if not domain:
            continue
        current = selected_domains.get(domain)
        severity = STATUS_CLASS_SEVERITY.get(
            str(item.get("status_class") or "blocked"),
            3,
        )
        if current is None or severity > int(current["_severity"]):
            selected_domains[domain] = {
                "_severity": severity,
                "status": item.get("status"),
                "status_class": item.get("status_class"),
                "facts_usable": bool(item.get("facts_usable")),
                "decision_usable": bool(item.get("decision_usable")),
                "capability": capability_id,
            }
    for item in selected_domains.values():
        item.pop("_severity", None)

    passport["upstream_source_trust"] = upstream_source_trust
    passport["source_trust"] = {
        "trust_level": trust_level,
        "trust_score": trust_score,
        "trust_scope": "selected_capabilities",
        "status": quality.get("status"),
    }
    passport["trust_level"] = trust_level
    passport["trust_score"] = trust_score
    passport["trust_scope"] = "selected_capabilities"
    passport["summary"] = (
        "Trust is derived from the selected capability quality contract."
    )
    passport["reasons"] = list(
        dict.fromkeys(
            str(_dict(issue).get("code"))
            for issue in _list(quality.get("issues"))
            if str(_dict(issue).get("code") or "").strip()
        )
    )
    passport["missing"] = [
        f"capability:{capability_id}"
        for capability_id in quality.get("blocked_required_capabilities") or []
    ]
    passport["warnings"] = [
        f"capability:{capability_id}"
        for capability_id in quality.get("limited_required_capabilities") or []
    ]
    passport["domains"] = selected_domains
    passport["decision_readiness"] = {
        "status": quality.get("status"),
        "trust_level": quality.get("trust_level"),
        "blocked_capabilities": quality.get(
            "blocked_required_capabilities",
            [],
        ),
        "limited_capabilities": quality.get(
            "limited_required_capabilities",
            [],
        ),
        "decision_ready": bool(quality.get("decision_ready")),
        "quality_ref": "evidence.quality",
    }
    evidence["passport"] = passport
    canonical["evidence"] = evidence

    limitations = _dict(canonical.get("limitations"))
    missing = [
        str(value)
        for value in _list(limitations.get("missing"))
        if str(value).strip()
    ]
    for capability_id in quality.get("blocked_required_capabilities") or []:
        marker = f"capability:{capability_id}"
        if marker not in missing:
            missing.append(marker)
    warnings = [
        str(value)
        for value in _list(limitations.get("warnings"))
        if str(value).strip()
    ]
    capability_quality = _dict(quality.get("capabilities"))
    for capability_id in quality.get("limited_required_capabilities") or []:
        item = _dict(capability_quality.get(capability_id))
        marker = f"capability:{capability_id}"
        if marker not in warnings:
            warnings.append(marker)
        if item.get("status") == "stale":
            temporal = _dict(item.get("temporal"))
            observations = _list(temporal.get("observations"))
            latest_observation = (
                _dict(observations[-1]).get("value")
                if observations
                else None
            )
            observed_at = latest_observation or temporal.get("latest_date")
            if observed_at:
                stale_marker = (
                    f"capability:{capability_id}:stale_observed_at={observed_at}"
                )
                if stale_marker not in warnings:
                    warnings.append(stale_marker)
    for issue in quality.get("issues") or []:
        code = str(_dict(issue).get("code") or "").strip()
        if not code or code in {
            "status_sources_disagree",
            "applicability_sources_disagree",
        }:
            continue
        warning = f"data_quality:{code}"
        if warning not in warnings:
            warnings.append(warning)
    limitations["missing"] = missing
    limitations["warnings"] = warnings
    canonical["limitations"] = limitations

    decision = _dict(canonical.get("decision"))
    answer = _dict(canonical.get("answer"))
    if quality.get("status") == "blocked" and answer:
        answer["confidence"] = "low"
        answer["quality_status"] = "blocked"
        canonical["answer"] = answer
    if (
        decision_required
        and quality.get("output") != "evidence_only"
        and not quality.get("decision_ready")
    ):
        decision.update(
            {
                "action_plan": [],
                "scenarios": [],
                "price_levels": {},
                "position": {},
                "blocked_sections": list(
                    dict.fromkeys(
                        [
                            *decision.get("blocked_sections", []),
                            "decision",
                            "price_levels",
                            "position",
                        ]
                    )
                ),
            }
        )
        answer = _dict(canonical.get("answer"))
        answer.update(
            {
                "headline": "資料品質不足，暫不形成交易決策",
                "text": "目前 evidence 未通過資料品質與一致性檢查；請先補齊或確認資料缺口。",
                "detail": "目前 evidence 未通過資料品質與一致性檢查；請先補齊或確認資料缺口。",
                "summary": [
                    *[
                        f"缺少或不可用：{capability_id}"
                        for capability_id in quality.get(
                            "blocked_required_capabilities",
                            [],
                        )[:3]
                    ],
                    *[
                        f"受限：{capability_id}"
                        for capability_id in quality.get(
                            "limited_required_capabilities",
                            [],
                        )[:3]
                    ],
                ][:4],
                "stance": "insufficient_data",
                "confidence": "low",
                "source": "omi.data.quality.v1",
            }
        )
        canonical["answer"] = answer
    canonical["decision"] = decision
    return canonical


__all__ = [
    "QUALITY_VERSION",
    "apply_quality_contract",
    "build_quality_contract",
]
