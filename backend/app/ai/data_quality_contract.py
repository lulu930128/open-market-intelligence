from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import re
from statistics import median
from typing import Any

from app.observability.status_taxonomy import (
    status_dimensions_from_quality_contract,
)
from app.market.trading_calendar import next_taiwan_trading_day


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
    "latest_released",
    "latest_session_close",
    "live",
    "ok",
    "official_close",
    "ready",
    "valid_empty",
}
LIMITED_STATUSES = {
    "cached",
    "delayed",
    "partial",
    "pending",
    "pending_release",
    "provisional",
    "waiting",
}
NEUTRAL_STATUSES = {
    "market_closed_no_live_book",
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
    "end_at",
    "event_at",
    "event_time",
    "latest_data_date",
    "observation_date",
    "quote_time",
    "selected_event_at",
    "start_at",
    "timestamp",
    "trade_date",
}
OBSERVATION_TIMESTAMP_KEYS = {
    "as_of",
    "bar_time",
    "end_at",
    "event_at",
    "event_time",
    "quote_time",
    "selected_event_at",
    "start_at",
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


def _current_session_identity_summary(value: Any) -> dict[str, Any]:
    scopes = {
        str(raw_value or "").strip().lower()
        for _, raw_value in _iter_values(value, keys={"session_scope"})
        if str(raw_value or "").strip()
    }
    if "current_session" not in scopes:
        return {
            "status": "not_applicable",
            "expected_trade_date": None,
            "observed_trade_dates": [],
            "unexpected_trade_dates": [],
            "satisfied": True,
        }

    expected_dates = {
        parsed.date().isoformat()
        for _, raw_value in _iter_values(value, keys={"expected_trade_date"})
        if (parsed := _parse_datetime(raw_value)) is not None
    }
    def collect_observed_dates(item: Any, *, depth: int = 0) -> set[str]:
        if depth > 6:
            return set()
        dates: set[str] = set()
        if isinstance(item, dict):
            for key, child in item.items():
                if key == "observed_trade_dates" and isinstance(child, list):
                    dates.update(
                        parsed.date().isoformat()
                        for raw_date in child[:500]
                        if (parsed := _parse_datetime(raw_date)) is not None
                    )
                elif key in {"points", "bars"} and isinstance(child, list):
                    dates.update(
                        timestamp.date().isoformat()
                        for point in child[:500]
                        if isinstance(point, dict)
                        and (timestamp := _point_time(point)) is not None
                    )
                elif isinstance(child, (dict, list)):
                    dates.update(
                        collect_observed_dates(child, depth=depth + 1)
                    )
        elif isinstance(item, list):
            for child in item[:50]:
                if isinstance(child, (dict, list)):
                    dates.update(
                        collect_observed_dates(child, depth=depth + 1)
                    )
        return dates

    observed_dates = collect_observed_dates(value)
    expected_trade_date = (
        next(iter(expected_dates)) if len(expected_dates) == 1 else None
    )
    unexpected_dates = sorted(
        observed_dates - ({expected_trade_date} if expected_trade_date else set())
    )
    satisfied = bool(expected_trade_date and not unexpected_dates)
    return {
        "status": (
            "matched"
            if satisfied
            else "expected_trade_date_missing"
            if not expected_dates
            else "expected_trade_date_ambiguous"
            if len(expected_dates) > 1
            else "mismatch"
        ),
        "expected_trade_date": expected_trade_date,
        "observed_trade_dates": sorted(observed_dates),
        "unexpected_trade_dates": unexpected_dates,
        "satisfied": satisfied,
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
        "event_at",
        "event_time",
        "end_at",
        "start_at",
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


def _is_expected_market_session_boundary(
    previous: datetime,
    current: datetime,
    *,
    market: str,
) -> bool:
    normalized_market = market.strip().upper()
    return (
        normalized_market in {"TW", "TAIWAN"}
        and current.date() > previous.date()
    )


def _continuity_summary(value: Any, *, market: str) -> dict[str, Any]:
    points = _series_points(value)
    timestamps = [parsed for point in points if (parsed := _point_time(point))]
    expected_seconds = _interval_seconds(value)
    issues: list[str] = []
    gap_count = 0
    duplicate_count = 0
    non_monotonic_count = 0
    recognized_session_gap_count = 0
    overnight_session_gap_count = 0
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
            if _is_expected_market_session_boundary(
                previous,
                current,
                market=market,
            ):
                recognized_session_gap_count += 1
                overnight_session_gap_count += 1
                continue
            elif _is_known_jp_lunch_gap(previous, current, market=market):
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
    declared_point_count = _first_semantic_value(
        value,
        keys={
            "available_bar_count",
            "original_point_count",
            "point_count",
            "source_point_count",
        },
    )
    try:
        declared_point_count = int(declared_point_count)
    except (TypeError, ValueError):
        declared_point_count = None
    if (
        len(timestamps) <= 1
        and points
        and (declared_point_count is None or declared_point_count <= 1)
    ):
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
        "declared_point_count": declared_point_count,
        "timestamp_count": len(timestamps),
        "expected_interval_seconds": expected_seconds,
        "observed_median_interval_seconds": observed_median,
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "gap_count": gap_count,
        "recognized_session_gap_count": recognized_session_gap_count,
        "overnight_session_gap_count": overnight_session_gap_count,
        "market_halt_gap_count": market_halt_gap_count,
        "gap_reason": (
            "market_halt"
            if market_halt_gap_count
            else "session_boundary"
            if overnight_session_gap_count
            else None
        ),
        "market_event_refs": market_event_refs,
        "session_gap_evidence": (
            "market_event"
            if market_halt_gap_count
            else "trading_day_boundary"
            if overnight_session_gap_count
            else
            "closing_auction_or_official_close"
            if market.upper() in {"TW", "TAIWAN"}
            and has_auction_close_evidence
            else None
        ),
        "issues": issues,
    }


def _daily_trading_continuity_summary(
    value: Any,
    *,
    market: str,
) -> dict[str, Any]:
    points = _series_points(value)
    timestamps = [parsed for point in points if (parsed := _point_time(point))]
    duplicate_count = 0
    non_monotonic_count = 0
    gap_count = 0
    missing_trading_day_count = 0
    issues: list[str] = []
    normalized_market = market.strip().upper()
    for previous, current in zip(timestamps, timestamps[1:]):
        previous_date = previous.date()
        current_date = current.date()
        if current_date == previous_date:
            duplicate_count += 1
            continue
        if current_date < previous_date:
            non_monotonic_count += 1
            continue
        if normalized_market in {"TW", "TAIWAN"}:
            expected_next = next_taiwan_trading_day(
                previous_date,
                include_value=False,
            )
            if current_date != expected_next:
                gap_count += 1
                cursor = expected_next
                while cursor < current_date:
                    missing_trading_day_count += 1
                    cursor = next_taiwan_trading_day(
                        cursor,
                        include_value=False,
                    )
    if duplicate_count:
        issues.append("duplicate_trade_date")
    if non_monotonic_count:
        issues.append("unordered_trade_date")
    if gap_count:
        issues.append("missing_trading_day")
    if not timestamps:
        status = "unknown"
    elif duplicate_count:
        status = "duplicate"
    elif non_monotonic_count:
        status = "unordered"
    elif gap_count:
        status = "gap_detected"
    elif len(timestamps) < 2:
        status = "insufficient_history"
        issues.append("insufficient_series_points")
    else:
        status = "continuous"
    return {
        "status": status,
        "point_count_inspected": len(points),
        "timestamp_count": len(timestamps),
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "gap_count": gap_count,
        "missing_trading_day_count": missing_trading_day_count,
        "calendar": (
            "taiwan_trading_calendar"
            if normalized_market in {"TW", "TAIWAN"}
            else None
        ),
        "issues": list(dict.fromkeys(issues)),
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
    if isinstance(payload, dict) and (
        payload.get("empty_result_is_valid") is True
        or _normalized_status(payload.get("status")) == "valid_empty"
        or _normalized_status(_dict(payload.get("freshness")).get("status"))
        == "valid_empty"
    ):
        return False
    if (
        capability_id == "quote.session_close"
        and isinstance(payload, dict)
        and payload.get("available") is False
    ):
        return True
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


def _first_semantic_value(
    payload: Any,
    *,
    keys: set[str],
) -> Any:
    return next(
        (
            raw_value
            for _, raw_value in _iter_values(payload, keys=keys)
            if _has_semantic_value(raw_value)
        ),
        None,
    )


def _canonical_freshness_status(
    *,
    status: str,
    payload: Any,
    realtime: dict[str, Any],
    payload_included: bool,
) -> str:
    explicit = _normalized_status(
        realtime.get("state")
        or _first_semantic_value(
            payload,
            keys={"freshness_status"},
        )
        or status
    )
    aliases = {
        "daily_close": "latest_completed_session",
        "final": "latest_completed_session",
        "final_snapshot": "latest_completed_session",
        "latest_session_close": "latest_completed_session",
        "official_close": "latest_completed_session",
    }
    explicit = aliases.get(explicit, explicit)
    release_status = _normalized_status(
        _first_semantic_value(payload, keys={"release_status"})
    )
    if (
        payload_included
        and release_status in {"pending", "pending_release"}
        and explicit in {"pending", "pending_release", "partial", "unknown"}
    ):
        return "latest_released"
    if explicit == "not_applicable":
        return "latest_completed_session"
    return explicit


def _canonical_release_status(
    *,
    payload: Any,
    payload_included: bool,
    applicability_status: str,
    freshness_status: str,
) -> str:
    if applicability_status == "not_applicable":
        return "not_applicable"
    explicit = _normalized_status(
        _first_semantic_value(
            payload,
            keys={"release_status"},
        )
    )
    if explicit in {"pending", "pending_release"}:
        return "pending_release"
    if explicit not in {"unknown", "missing"}:
        return explicit
    if freshness_status == "pending_release":
        return "pending_release"
    return "released" if payload_included else "unknown"


def _canonical_coverage_status(
    *,
    capability_id: str,
    manifest_item: dict[str, Any],
    payload: Any,
    payload_included: bool,
    continuity: dict[str, Any],
) -> str:
    if (
        capability_id == "market.sample_ranking"
        and isinstance(payload, dict)
        and payload.get("is_full_market") is False
    ):
        return "sample_only"
    explicit = _normalized_status(
        _first_semantic_value(
            payload,
            keys={"coverage_status"},
        )
    )
    manifest_explicit = _normalized_status(manifest_item.get("coverage_status"))
    if capability_id in {"daily.ohlcv", "intraday.bars"}:
        returned_count = manifest_item.get("returned_count")
        if not isinstance(returned_count, int) or isinstance(returned_count, bool):
            returned_count = 0
        canonical_count = manifest_item.get("canonical_available_count")
        if not isinstance(canonical_count, int) or isinstance(canonical_count, bool):
            canonical_count = None

        # Upstream canonical coverage is authoritative.  Projection limits and
        # byte trimming describe only the consumer payload and may not demote
        # otherwise complete evidence.
        canonical_explicit = next(
            (
                value
                for value in (manifest_explicit, explicit)
                if value
                in {
                    "complete",
                    "partial",
                    "missing",
                    "insufficient_history",
                    "valid_empty",
                }
            ),
            None,
        )
        if (
            continuity.get("status") == "insufficient_history"
            and canonical_explicit in {None, "partial"}
        ):
            return "insufficient_history"
        if canonical_explicit is not None:
            return canonical_explicit
        if canonical_count is not None and canonical_count <= 0:
            return "valid_empty" if explicit == "valid_empty" else "missing"
        if canonical_count is None and returned_count <= 0:
            return "valid_empty" if explicit == "valid_empty" else "missing"
        if continuity.get("status") not in {"continuous", "not_applicable"}:
            return "partial"
        return "complete"
    if explicit in {"complete", "partial", "sample_only", "valid_empty"}:
        return explicit
    if isinstance(payload, dict):
        coverage = _dict(payload.get("coverage"))
        if coverage.get("is_full_market") is False:
            return "sample_only"
        if coverage.get("is_full_requested_universe") is False:
            return "partial"
        ratio = coverage.get("coverage_ratio", payload.get("coverage_ratio"))
        try:
            if ratio is not None and float(ratio) < 1:
                return "partial"
        except (TypeError, ValueError):
            pass
    return "complete" if payload_included else "unknown"


def _projection_coverage_status(
    *,
    manifest_item: dict[str, Any],
    payload_included: bool,
) -> str:
    """Describe selection/trimming without changing canonical truth status."""

    if not payload_included:
        return "missing"
    returned_count = manifest_item.get("returned_count")
    canonical_count = manifest_item.get("canonical_available_count")
    if (
        manifest_item.get("truncated") is True
        or isinstance(canonical_count, int)
        and not isinstance(canonical_count, bool)
        and isinstance(returned_count, int)
        and not isinstance(returned_count, bool)
        and returned_count < canonical_count
    ):
        return "truncated"
    return "complete"


def _canonical_reason_codes(
    *,
    issues: list[str],
    applicability_status: str,
    availability_status: str,
    freshness_status: str,
    coverage_status: str,
) -> list[str]:
    values = list(issues)
    if applicability_status == "not_applicable":
        values.append("not_applicable")
    if availability_status in {"missing", "error"}:
        values.append(f"availability_{availability_status}")
    if freshness_status in {"stale", "delayed", "pending_release"}:
        values.append(f"freshness_{freshness_status}")
    if coverage_status in {
        "partial",
        "sample_only",
        "insufficient_history",
        "missing",
    }:
        values.append(f"coverage_{coverage_status}")
    return list(dict.fromkeys(values))


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


def _financial_semantic_quality(
    capability_id: str,
    payload: Any,
) -> dict[str, Any] | None:
    if capability_id != "fundamentals.financials" or not isinstance(payload, dict):
        return None

    financial_contract = _dict(payload.get("financial_contract"))
    quality = _dict(financial_contract.get("quality"))
    normalized = _dict(financial_contract.get("normalized"))
    if not financial_contract or not quality:
        return None

    semantic_validity = _normalized_status(quality.get("semantic_validity"))
    if (
        quality.get("decision_usable") is True
        and normalized.get("status") == "ready"
        and semantic_validity == "valid"
    ):
        return None

    as_reported = _dict(financial_contract.get("as_reported"))
    as_reported_status = _normalized_status(as_reported.get("status"))
    facts_available = bool(
        as_reported_status.startswith("available")
        or as_reported.get("latest")
        or as_reported.get("history")
        or payload.get("latest_financial")
        or payload.get("financial_history")
    )
    issues = [
        str(issue)
        for issue in quality.get("issues") or []
        if str(issue).strip()
    ]
    issues.append("financial_contract_decision_blocked")
    return {
        "source": "payload.semantic_quality",
        "status": "partial" if facts_available else "blocked",
        "status_class": "limited" if facts_available else "blocked",
        "facts_usable": facts_available,
        "decision_usable": False,
        "issues": list(dict.fromkeys(issues)),
    }


def _explicit_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _payload_semantic_quality(
    capability_id: str,
    payload: Any,
) -> dict[str, Any] | None:
    financial = _financial_semantic_quality(capability_id, payload)
    if financial is not None:
        return financial
    if not isinstance(payload, dict):
        return None

    quality = _dict(payload.get("quality"))
    has_typed_top_level_quality = bool(
        _normalized_status(payload.get("freshness_status")) != "unknown"
        or any(
            isinstance(payload.get(key), bool)
            for key in (
                "facts_usable",
                "research_usable",
                "decision_usable",
            )
        )
    )
    if not quality and not has_typed_top_level_quality:
        return None
    explicit_status = _normalized_status(
        quality.get("status")
        or payload.get("freshness_status")
        or payload.get("status")
    )
    facts_usable = _explicit_bool(
        quality.get("facts_usable"),
        payload.get("facts_usable"),
        quality.get("research_usable"),
        payload.get("research_usable"),
    )
    decision_usable = _explicit_bool(
        quality.get("decision_usable"),
        payload.get("decision_usable"),
    )
    issues = [
        str(value)
        for values in (
            quality.get("issues"),
            quality.get("reason_codes"),
            payload.get("reason_codes"),
            payload.get("limitations"),
        )
        if isinstance(values, (list, tuple))
        for value in values
        if str(value).strip()
    ]
    if (
        explicit_status == "unknown"
        and facts_usable is None
        and decision_usable is None
        and not issues
    ):
        return None

    if explicit_status == "unknown":
        explicit_status = "missing" if facts_usable is False else "partial"
    status_class = _status_class(explicit_status)
    if facts_usable is False:
        status_class = "blocked"
    elif decision_usable is False and status_class == "ready":
        status_class = "limited"
    elif (
        facts_usable is True
        and status_class == "blocked"
        and explicit_status == "stale"
    ):
        status_class = "limited"

    return {
        "source": "payload.semantic_quality",
        "status": explicit_status,
        "status_class": status_class,
        "facts_usable": facts_usable,
        "decision_usable": decision_usable,
        "issues": list(dict.fromkeys(issues)),
    }


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
    payload_quality = _dict(payload.get("quality")) if isinstance(payload, dict) else {}
    explicit_payload_status = _normalized_status(
        payload_quality.get("status")
        or (payload.get("status") if isinstance(payload, dict) else None)
    )
    explicitly_unavailable = bool(
        projected_payload_included
        and isinstance(payload, dict)
        and (
            payload.get("available") is False
            or _normalized_status(payload.get("availability_status"))
            in {"missing", "unavailable", "error"}
            or explicit_payload_status in {"missing", "unavailable", "error"}
        )
    )
    semantic_payload_empty = _semantic_payload_empty(
        capability_id,
        payload,
    )
    payload_included = bool(
        projected_payload_included
        and not semantic_payload_empty
        and not explicitly_unavailable
    )
    payload_applicability = _normalized_status(
        _first_semantic_value(payload, keys={"applicability_status"})
    )
    semantic_quality = (
        None
        if payload_applicability == "not_applicable"
        else _payload_semantic_quality(capability_id, payload)
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
        realtime
        and str(realtime.get("policy") or "").strip().lower() == "require_live"
        and realtime.get("policy_satisfied") is False
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
    if semantic_quality is not None:
        candidates.append(semantic_quality)
    status_classes = {candidate["status_class"] for candidate in candidates}
    contradiction_codes: list[str] = []
    if "ready" in status_classes and ({"limited", "blocked"} & status_classes):
        contradiction_codes.append("status_sources_disagree")
    if "neutral" in status_classes and ({"ready", "limited", "blocked"} & status_classes):
        contradiction_codes.append("applicability_sources_disagree")

    temporal = _temporal_summary(payload)
    current_session_identity = _current_session_identity_summary(payload)
    units = _unit_summary(payload)
    continuity = (
        _continuity_summary(payload, market=market)
        if capability_id == "intraday.bars"
        else _daily_trading_continuity_summary(payload, market=market)
        if capability_id == "daily.ohlcv"
        and market.strip().upper() in {"TW", "TAIWAN"}
        else {
            "status": "not_applicable",
            "point_count_inspected": 0,
            "timestamp_count": 0,
            "issues": [],
        }
    )
    coverage_status = _canonical_coverage_status(
        capability_id=capability_id,
        manifest_item=item,
        payload=payload,
        payload_included=payload_included,
        continuity=continuity,
    )
    projection_coverage_status = _projection_coverage_status(
        manifest_item=item,
        payload_included=payload_included,
    )
    if explicitly_unavailable:
        coverage_status = "missing"
    current_session_limited = bool(
        capability_id == "intraday.bars"
        and current_session_identity["status"] != "not_applicable"
        and current_session_identity["satisfied"] is not True
    )
    if current_session_limited and coverage_status == "complete":
        coverage_status = "partial"
    continuity_limited = continuity.get("status") not in {
        "continuous",
        "not_applicable",
    }
    status = canonical_candidate["status"]
    status_class = canonical_candidate["status_class"]
    applicability_status = (
        "not_applicable"
        if status_class == "neutral"
        or _normalized_status(
            _first_semantic_value(payload, keys={"applicability_status"})
        )
        == "not_applicable"
        else "applicable"
    )
    freshness_status = _canonical_freshness_status(
        status=status,
        payload=payload,
        realtime=realtime,
        payload_included=payload_included,
    )
    release_status = _canonical_release_status(
        payload=payload,
        payload_included=payload_included,
        applicability_status=applicability_status,
        freshness_status=freshness_status,
    )
    if explicitly_unavailable and release_status == "unknown":
        release_status = "not_released"
    if applicability_status == "not_applicable":
        status = "not_applicable"
        status_class = "neutral"
    elif (
        payload_included
        and freshness_status == "latest_released"
        and release_status == "pending_release"
    ):
        status = freshness_status
        status_class = "ready"
    if semantic_quality is not None:
        status = str(semantic_quality["status"])
        status_class = str(semantic_quality["status_class"])
        canonical_candidate = semantic_quality
    completeness = (
        "not_applicable"
        if status_class == "neutral"
        else "empty"
        if not payload_included
        else "partial"
        if status_class == "limited"
        or continuity_limited
        or coverage_status not in {"complete", "valid_empty"}
        else "complete"
    )
    decision_usable = bool(
        status_class == "ready"
        and not continuity_limited
        and not current_session_limited
        and coverage_status == "complete"
        and not units["missing_volume_unit"]
    )
    stale_intraday_facts_usable = bool(
        capability_id == "intraday.bars"
        and payload_included
        and status == "stale"
        and temporal.get("latest_date")
        and _has_payload_observation_timestamp(payload)
        and _has_payload_provenance(payload)
        and not continuity_limited
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
    realtime_facts_usable = bool(
        realtime.get("facts_usable")
        if isinstance(realtime.get("facts_usable"), bool)
        else False
    )
    facts_usable = bool(
        payload_included
        and (
            status_class in {"ready", "limited"}
            or realtime_facts_usable
            or stale_intraday_facts_usable
            or stale_quote_facts_usable
        )
    )
    semantic_facts_usable = (
        semantic_quality.get("facts_usable")
        if semantic_quality is not None
        and isinstance(semantic_quality.get("facts_usable"), bool)
        else None
    )
    if semantic_facts_usable is False:
        facts_usable = False
    elif semantic_facts_usable is True:
        facts_usable = bool(
            payload_included
            and coverage_status not in {"missing", "valid_empty"}
            and not units["missing_volume_unit"]
        )
    semantic_decision_usable = (
        semantic_quality.get("decision_usable")
        if semantic_quality is not None
        and isinstance(semantic_quality.get("decision_usable"), bool)
        else None
    )
    if semantic_decision_usable is False:
        decision_usable = False
    elif semantic_decision_usable is True:
        decision_usable = bool(decision_usable and facts_usable)
    intraday_research_usable = bool(
        payload_included
        and (
            realtime.get("intraday_research_usable")
            if isinstance(
                realtime.get("intraday_research_usable"),
                bool,
            )
            else capability_id == "intraday.bars"
            and facts_usable
            and not current_session_limited
            and freshness_status in {"current", "delayed"}
        )
    )
    execution_grade_usable = bool(
        realtime.get("execution_grade_usable")
        if isinstance(realtime.get("execution_grade_usable"), bool)
        else False
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
    if current_session_limited:
        issues.append("CURRENT_SESSION_SERIES_DATE_MISMATCH")
    if coverage_status == "insufficient_history":
        issues.append("insufficient_history")
    if units["missing_volume_unit"]:
        issues.append("volume_unit_missing")
    if realtime_policy_unsatisfied:
        issues.append("live_requirement_not_satisfied")
    if semantic_quality is not None:
        issues.extend(str(value) for value in semantic_quality.get("issues") or [])
    if (
        capability_id == "quote.snapshot"
        and _normalized_status(
            _dict(_dict(payload).get("volume_reconciliation")).get(
                "status"
            )
        )
        == "mismatch"
    ):
        issues.append("volume_reconciliation_mismatch")
    availability_status = (
        "available"
        if payload_included
        else "missing"
        if explicitly_unavailable and explicit_payload_status == "missing"
        else "unavailable"
        if explicitly_unavailable
        else "unavailable"
        if applicability_status == "not_applicable"
        else "missing"
    )
    usability_status = (
        "not_applicable"
        if applicability_status == "not_applicable"
        else "unusable"
        if not facts_usable
        else "limited"
        if not decision_usable
        or coverage_status
        in {"partial", "sample_only", "insufficient_history", "valid_empty"}
        else "usable"
    )
    reason_codes = _canonical_reason_codes(
        issues=issues,
        applicability_status=applicability_status,
        availability_status=availability_status,
        freshness_status=freshness_status,
        coverage_status=coverage_status,
    )
    return {
        "capability": capability_id,
        "domain": item.get("domain"),
        "slot": item.get("slot"),
        "required": bool(item.get("required")),
        "status": status,
        "status_class": status_class,
        "status_authority": "canonical_status_resolver",
        "upstream_status_authority": canonical_candidate["source"],
        "applicability_status": applicability_status,
        "availability_status": availability_status,
        "freshness_status": freshness_status,
        "release_status": release_status,
        "coverage_status": coverage_status,
        "canonical_dataset_coverage": coverage_status,
        "consumer_projection_coverage": projection_coverage_status,
        "usability_status": usability_status,
        "availability": availability_status,
        "freshness": (
            freshness_status
        ),
        "completeness": completeness,
        "release_phase": _release_phase(
            str(realtime.get("state") or status),
            payload,
        ),
        "facts_usable": facts_usable,
        "intraday_research_usable": intraday_research_usable,
        "execution_grade_usable": execution_grade_usable,
        "policy_satisfied": realtime.get("policy_satisfied"),
        "decision_usable": decision_usable,
        "payload_included": payload_included,
        "temporal": temporal,
        "current_session_identity": current_session_identity,
        "units": units,
        "continuity": continuity,
        "status_evidence": candidates,
        "contradictions": contradictions,
        "issues": list(dict.fromkeys(issues)),
        "reason_codes": reason_codes,
        "as_of": _first_semantic_value(
            payload,
            keys={"as_of", "latest_data_date", "trade_date", "date"},
        ),
        "trade_date": _first_semantic_value(
            payload,
            keys={"trade_date", "latest_data_date", "date"},
        ),
        "event_time": _first_semantic_value(
            payload,
            keys={
                "event_at",
                "event_time",
                "provider_event_time",
                "bar_time",
                "end_at",
                "selected_event_at",
            },
        ),
        "release_at": _first_semantic_value(
            payload,
            keys={"release_at", "released_at", "next_release_at"},
        ),
        "fetched_at": _first_semantic_value(payload, keys={"fetched_at"}),
        "computed_at": _first_semantic_value(
            payload,
            keys={"computed_at", "calculated_at", "generated_at"},
        ),
        "served_at": (
            _first_semantic_value(payload, keys={"served_at"})
            or canonical.get("served_at")
            or canonical.get("generated_at")
        ),
        "refresh_possible_now": (
            False
            if applicability_status == "not_applicable"
            else realtime.get("refresh_possible_now")
        ),
        "refresh_allowed": _explicit_bool(
            realtime.get("refresh_allowed"),
            payload_freshness.get("refresh_allowed"),
            payload.get("refresh_allowed") if isinstance(payload, dict) else None,
        ),
        "refresh_requested": _explicit_bool(
            realtime.get("refresh_requested"),
            payload_freshness.get("refresh_requested"),
            payload.get("refresh_requested") if isinstance(payload, dict) else None,
        ),
        "refresh_recommended": (
            False
            if applicability_status == "not_applicable"
            or (
                release_status == "pending_release"
                and freshness_status == "latest_released"
            )
            else bool(
                realtime.get("refresh_recommended")
                or payload_freshness.get("refresh_recommended")
                or (
                    payload.get("refresh_recommended")
                    if isinstance(payload, dict)
                    else False
                )
                or _dict(
                    freshness_by_capability.get(capability_id)
                ).get("refresh_recommended")
                or status == "stale"
                or freshness_status
                in {"missing", "stale", "delayed", "future", "unavailable"}
            )
        ),
        "source_grade": _first_semantic_value(
            payload,
            keys={"source_grade"},
        ),
        "selected_provider": _first_semantic_value(
            payload,
            keys={"selected_provider", "provider"},
        ),
        "selected_source": _first_semantic_value(
            payload,
            keys={"selected_source", "source"},
        ),
        "selection_reason": _first_semantic_value(
            payload,
            keys={"selection_reason"},
        ),
        "fallback_used": bool(
            _first_semantic_value(payload, keys={"fallback_used"})
        ),
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
        quote_payload = _dict(projected_data.get("quote.snapshot"))
        date_relation = _dict(
            quote_payload.get("session_date_relation")
        )
        expected_cross_date_relation = bool(
            date_relation.get("expected") is True
            and date_relation.get("status") == "aligned"
            and date_relation.get("quote_date") == quote_date
            and date_relation.get("completed_daily_date") == daily_date
        )
        if (
            quote_date
            and daily_date
            and quote_date != daily_date
            and not expected_cross_date_relation
        ):
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
    required_capability_rows = {
        capability_id: item
        for capability_id, item in capability_rows.items()
        if item.get("required")
    }
    fusion_issues = _fusion_issues(
        required_capability_rows,
        projected_data=projected_data,
    )
    required_rows = list(required_capability_rows.values())
    supplemental_rows = [
        item for item in capability_rows.values() if not item.get("required")
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
        and item.get("applicability_status") != "not_applicable"
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
            or any(
                item.get("facts_usable")
                or item.get("applicability_status") == "not_applicable"
                for item in required_data_rows
            )
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
    supplemental_issues: list[dict[str, Any]] = []
    for item in required_rows:
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
    for item in supplemental_rows:
        for code in item.get("issues") or []:
            supplemental_issues.append(
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
        "trust_scope": "selected_required_capabilities",
        "response_ready": response_ready,
        "facts_ready": facts_ready,
        "analysis_ready": analysis_ready,
        "decision_ready": decision_ready,
        "blocked_required_capabilities": list(dict.fromkeys(blocked_required)),
        "limited_required_capabilities": list(dict.fromkeys(limited_required)),
        "selected_capability_quality": {
            "scope": "required_capabilities",
            "status": overall_status,
            "trust_level": trust_level,
            "capabilities": [
                str(item.get("capability")) for item in required_rows
            ],
        },
        "supplemental_context_quality": {
            "scope": "optional_capabilities",
            "affects_selected_quality": False,
            "status": (
                "blocked"
                if any(
                    item.get("status_class") == "blocked"
                    for item in supplemental_rows
                )
                else "partial"
                if any(
                    item.get("status_class") == "limited"
                    for item in supplemental_rows
                )
                else "ready"
            ),
            "capabilities": [
                str(item.get("capability")) for item in supplemental_rows
            ],
            "issues": supplemental_issues,
        },
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


def _consumer_capability_status(item: dict[str, Any]) -> dict[str, Any]:
    projection = {
        key: deepcopy(item.get(key))
        for key in (
            "capability",
            "required",
            "applicability_status",
            "availability_status",
            "freshness_status",
            "release_status",
            "coverage_status",
            "usability_status",
            "facts_usable",
            "intraday_research_usable",
            "execution_grade_usable",
            "policy_satisfied",
            "decision_usable",
            "as_of",
            "event_time",
            "fetched_at",
            "trade_date",
            "release_at",
            "computed_at",
            "served_at",
            "refresh_possible_now",
            "refresh_allowed",
            "refresh_requested",
            "refresh_recommended",
            "source_grade",
            "selected_provider",
            "selected_source",
            "selection_reason",
            "fallback_used",
            "reason_codes",
        )
    }
    projection.update(
        {
            "missing_fields": [],
            "coverage_gaps": (
                list(item.get("reason_codes") or [])
                if item.get("coverage_status")
                in {
                    "partial",
                    "sample_only",
                    "insufficient_history",
                    "missing",
                }
                else []
            ),
            "warning_codes": list(item.get("issues") or []),
            "status_authority": "canonical_status_resolver",
            "quality_ref": (
                "evidence.quality.capabilities."
                f"{item.get('capability')}"
            ),
        }
    )
    return projection


def apply_quality_contract(
    canonical: dict[str, Any],
    *,
    quality: dict[str, Any],
) -> dict[str, Any]:
    evidence = _dict(canonical.get("evidence"))
    evidence["quality"] = deepcopy(quality)
    status_dimensions = status_dimensions_from_quality_contract(quality)
    evidence["status_dimensions"] = status_dimensions
    manifest = _dict(evidence.get("manifest"))
    quality_capabilities = _dict(quality.get("capabilities"))
    capability_status = {
        capability_id: _consumer_capability_status(item)
        for capability_id, item in quality_capabilities.items()
        if isinstance(item, dict)
    }
    evidence["capability_status"] = capability_status
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
        for key in (
            "applicability_status",
            "availability_status",
            "freshness_status",
            "release_status",
            "coverage_status",
            "usability_status",
        ):
            item[key] = capability_quality.get(key)
        item["status_authority"] = "canonical_status_resolver"
        item["canonical_status_ref"] = (
            f"evidence.capability_status.{item.get('capability')}"
        )
        item["refresh_recommended"] = bool(
            capability_quality.get("refresh_recommended")
        )
        item["refresh_possible_now"] = capability_quality.get(
            "refresh_possible_now"
        )
        item["refresh_allowed"] = capability_quality.get("refresh_allowed")
        item["refresh_requested"] = capability_quality.get("refresh_requested")
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
        required_items = [item for item in items if item.get("required")]
        selected_items = required_items or items
        slot_status, usability = _slot_status_from_quality(selected_items)
        worst_item = max(
            selected_items,
            key=lambda item: STATUS_CLASS_SEVERITY.get(
                str(item.get("status_class") or "blocked"),
                3,
            ),
        )
        slot["status"] = slot_status
        slot["usability"] = usability
        slot["decision_usable"] = all(
            bool(item.get("decision_usable"))
            for item in selected_items
        )
        slot["quality_ref"] = "evidence.quality"
        slot["canonical_status_refs"] = [
            f"evidence.capability_status.{item.get('capability')}"
            for item in selected_items
        ]
        slot["supplemental_status_refs"] = [
            f"evidence.capability_status.{item.get('capability')}"
            for item in items
            if not item.get("required")
        ]
        slot["freshness"] = {
            **_dict(slot.get("freshness")),
            "status": (
                worst_item.get("freshness")
                if len(selected_items) == 1
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

    freshness_by_capability = _dict(
        evidence.get("freshness_by_capability")
    )
    for capability_id, canonical_status in capability_status.items():
        raw = _dict(freshness_by_capability.get(capability_id))
        raw_status = raw.get("status")
        raw.update(
            {
                "status": canonical_status.get("freshness_status"),
                "applicability_status": canonical_status.get(
                    "applicability_status"
                ),
                "availability_status": canonical_status.get(
                    "availability_status"
                ),
                "release_status": canonical_status.get("release_status"),
                "coverage_status": canonical_status.get("coverage_status"),
                "usability_status": canonical_status.get("usability_status"),
                "refresh_possible_now": canonical_status.get(
                    "refresh_possible_now"
                ),
                "refresh_recommended": canonical_status.get(
                    "refresh_recommended"
                ),
                "status_authority": "canonical_status_resolver",
                "canonical_status_ref": (
                    f"evidence.capability_status.{capability_id}"
                ),
            }
        )
        if raw_status is not None and raw_status != raw.get("status"):
            debug = _dict(raw.get("debug"))
            debug["upstream_status"] = raw_status
            raw["debug"] = debug
        freshness_by_capability[capability_id] = raw
    evidence["freshness_by_capability"] = freshness_by_capability

    freshness_categories: dict[str, list[Any]] = {
        "missing": [],
        "stale": [],
        "pending_release": [],
        "not_applicable": [],
        "valid_empty": [],
        "coverage_gaps": [],
        "facts_unusable": [],
        "decision_unusable": [],
        "warnings": [],
    }
    for capability_id, item in capability_status.items():
        if item.get("required") is not True:
            continue
        applicability = item.get("applicability_status")
        availability = item.get("availability_status")
        freshness_status = item.get("freshness_status")
        release_status = item.get("release_status")
        coverage_status = item.get("coverage_status")
        if applicability == "not_applicable":
            freshness_categories["not_applicable"].append(capability_id)
        elif availability in {"missing", "error"}:
            freshness_categories["missing"].append(capability_id)
        if freshness_status == "stale":
            freshness_categories["stale"].append(capability_id)
        if release_status == "pending_release":
            freshness_categories["pending_release"].append(capability_id)
        if "valid_empty" in set(item.get("reason_codes") or []):
            freshness_categories["valid_empty"].append(capability_id)
        if coverage_status in {
            "partial",
            "sample_only",
            "insufficient_history",
            "missing",
        }:
            freshness_categories["coverage_gaps"].append(
                {
                    "capability": capability_id,
                    "coverage_status": coverage_status,
                }
            )
        if item.get("facts_usable") is False:
            freshness_categories["facts_unusable"].append(capability_id)
        elif item.get("decision_usable") is False:
            freshness_categories["decision_unusable"].append(capability_id)
        for warning in item.get("warning_codes") or []:
            marker = {
                "capability": capability_id,
                "code": warning,
            }
            if marker not in freshness_categories["warnings"]:
                freshness_categories["warnings"].append(marker)

    projected_data = _dict(evidence.get("data"))
    selected_freshness = _dict(projected_data.get("data.freshness"))
    if selected_freshness:
        selected_freshness["categories"] = deepcopy(freshness_categories)
        selected_freshness["missing"] = list(
            freshness_categories["missing"]
        )
        selected_freshness["missing_datasets"] = list(
            freshness_categories["missing"]
        )
        selected_freshness["stale_datasets"] = list(
            freshness_categories["stale"]
        )
        selected_freshness["pending_release"] = list(
            freshness_categories["pending_release"]
        )
        selected_freshness["not_applicable"] = list(
            freshness_categories["not_applicable"]
        )
        selected_freshness["valid_empty"] = list(
            freshness_categories["valid_empty"]
        )
        selected_freshness["coverage_gaps"] = deepcopy(
            freshness_categories["coverage_gaps"]
        )
        selected_freshness["facts_unusable"] = list(
            freshness_categories["facts_unusable"]
        )
        selected_freshness["decision_unusable"] = list(
            freshness_categories["decision_unusable"]
        )
        selected_freshness["refresh_recommended"] = bool(
            freshness_categories["missing"]
            or freshness_categories["stale"]
        )
        temporal_status = (
            "stale"
            if freshness_categories["stale"]
            else "unknown"
            if freshness_categories["missing"]
            else "current"
        )
        availability_status = (
            "missing" if freshness_categories["missing"] else "available"
        )
        completeness_status = (
            "partial"
            if freshness_categories["coverage_gaps"]
            else "complete"
        )
        usability_status = (
            "blocked"
            if freshness_categories["facts_unusable"]
            else "limited"
            if freshness_categories["decision_unusable"]
            else "usable"
        )
        selected_freshness["temporal_status"] = temporal_status
        selected_freshness["temporal_is_current"] = temporal_status == "current"
        selected_freshness["availability_status"] = availability_status
        selected_freshness["completeness_status"] = completeness_status
        selected_freshness["usability_status"] = usability_status
        selected_freshness["is_current"] = not bool(
            freshness_categories["missing"]
            or freshness_categories["stale"]
            or freshness_categories["facts_unusable"]
            or freshness_categories["decision_unusable"]
            or freshness_categories["coverage_gaps"]
        )
        selected_freshness["status"] = (
            "missing"
            if freshness_categories["missing"]
            else "partial"
            if freshness_categories["stale"]
            or freshness_categories["coverage_gaps"]
            or freshness_categories["facts_unusable"]
            or freshness_categories["decision_unusable"]
            else "current"
        )
        selected_freshness["is_current_semantics"] = (
            "selected_required_capabilities_fully_usable_and_current"
        )
        selected_freshness["release_current"] = not bool(
            freshness_categories["pending_release"]
        )
        selected_freshness["served_at"] = (
            canonical.get("served_at") or canonical.get("generated_at")
        )
        selected_freshness["capability_times"] = {
            capability_id: {
                key: item.get(key)
                for key in (
                    "trade_date",
                    "event_time",
                    "release_at",
                    "fetched_at",
                    "computed_at",
                    "served_at",
                )
                if item.get(key) is not None
            }
            for capability_id, item in capability_status.items()
            if item.get("required") is True
        }
        projected_data["data.freshness"] = selected_freshness
        evidence["data"] = projected_data

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
        "trust_scope": "selected_required_capabilities",
        "status": quality.get("status"),
    }
    passport["trust_level"] = trust_level
    passport["trust_score"] = trust_score
    passport["trust_scope"] = "selected_required_capabilities"
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
    passport["status_dimensions"] = deepcopy(status_dimensions)
    evidence["passport"] = passport
    canonical["evidence"] = evidence

    limitations = _dict(canonical.get("limitations"))
    non_missing_capabilities = {
        capability_id
        for capability_id, item in capability_status.items()
        if item.get("applicability_status") == "not_applicable"
        or (
            item.get("release_status") == "pending_release"
            and item.get("freshness_status") == "latest_released"
        )
    }
    non_missing_datasets = {
        str(_dict(freshness_by_capability.get(capability_id)).get("dataset"))
        for capability_id in non_missing_capabilities
        if _dict(freshness_by_capability.get(capability_id)).get("dataset")
    }
    missing = [
        str(value)
        for value in _list(limitations.get("missing"))
        if str(value).strip()
        and str(value) not in non_missing_datasets
        and not (
            str(value).startswith("capability:")
            and str(value).split(":", 1)[1] in non_missing_capabilities
        )
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
