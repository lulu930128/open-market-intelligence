from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


COMPACT_INTRADAY_BAR_LIMIT = 80
INTRADAY_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h")
PAYLOAD_LEVELS = {"summary", "compact", "standard", "full"}
PAYLOAD_LEVEL_INTRADAY_LIMITS = {
    "summary": 1,
    "compact": COMPACT_INTRADAY_BAR_LIMIT,
    "standard": 160,
    "full": 500,
}


def market_data_params(params: dict[str, Any] | None) -> dict[str, Any]:
    return params if isinstance(params, dict) else {}


def payload_level(params: dict[str, Any] | None) -> str:
    data_params = market_data_params(params)
    raw_level = (
        data_params.get("payload_level")
        or data_params.get("detail_level")
        or data_params.get("detail")
        or "compact"
    )
    level = str(raw_level).strip().lower()
    return level if level in PAYLOAD_LEVELS else "compact"


def bounded_int_param(
    params: dict[str, Any] | None,
    keys: tuple[str, ...],
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    data_params = market_data_params(params)
    for key in keys:
        if key not in data_params:
            continue
        try:
            value = int(data_params[key])
        except (TypeError, ValueError):
            continue
        return max(minimum, min(maximum, value))
    return default


def intraday_point_limit(params: dict[str, Any] | None) -> int:
    level = payload_level(params)
    default = PAYLOAD_LEVEL_INTRADAY_LIMITS[level]
    return bounded_int_param(
        params,
        ("intraday_limit", "intraday_bar_limit", "point_limit"),
        default=default,
        minimum=1,
        maximum=PAYLOAD_LEVEL_INTRADAY_LIMITS["full"],
    )


def requested_intraday_interval(
    params: dict[str, Any] | None,
    *,
    default: str | None = None,
) -> str | None:
    data_params = market_data_params(params)
    for key in ("intraday_interval", "interval"):
        if key not in data_params:
            continue
        value = str(data_params.get(key) or "").strip().lower()
        return value if value in INTRADAY_INTERVALS else default

    # Compatibility only: older callers used timeframe for both daily and
    # intraday shape. Daily values remain daily; only interval-shaped values
    # are accepted here.
    timeframe = str(data_params.get("timeframe") or "").strip().lower()
    if timeframe in INTRADAY_INTERVALS:
        return timeframe
    return default


def annotate_intraday_bar_contract(
    points: list[dict[str, Any]],
    *,
    interval: str,
    now: datetime | None = None,
    default_ohlc_semantics: str = "interval_ohlc",
    default_volume_status: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized = str(interval or "1m").strip().lower()
    if normalized.endswith("m") and normalized[:-1].isdigit():
        interval_seconds = int(normalized[:-1]) * 60
    elif normalized.endswith("h") and normalized[:-1].isdigit():
        interval_seconds = int(normalized[:-1]) * 3600
    else:
        interval_seconds = 60
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    annotated: list[dict[str, Any]] = []
    for raw_point in points:
        point = dict(raw_point)
        raw_time = point.get("time") or point.get("bar_time")
        try:
            point_time = datetime.fromisoformat(
                str(raw_time).replace("Z", "+00:00")
            )
            if point_time.tzinfo is None:
                point_time = point_time.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            point_time = None
        existing_bar_close = point.get("bar_close_time")
        try:
            bar_close_time = (
                datetime.fromisoformat(
                    str(existing_bar_close).replace("Z", "+00:00")
                )
                if existing_bar_close
                else None
            )
        except (TypeError, ValueError):
            bar_close_time = None
        if bar_close_time is None:
            bar_close_time = (
                point_time + timedelta(seconds=interval_seconds)
                if point_time is not None
                else None
            )
        local_checked_at = (
            checked_at.astimezone(point_time.tzinfo)
            if point_time is not None and point_time.tzinfo is not None
            else checked_at
        )
        is_partial = (
            bool(point.get("is_partial"))
            if isinstance(point.get("is_partial"), bool)
            else bool(
                point_time is not None
                and bar_close_time is not None
                and point_time.date() == local_checked_at.date()
                and local_checked_at < bar_close_time
            )
        )
        volume = (
            point.get("volume")
            if point.get("volume") is not None
            else point.get("cumulative_volume")
        )
        point.update(
            {
                "bar_close_time": (
                    bar_close_time.isoformat()
                    if bar_close_time is not None
                    else None
                ),
                "elapsed_seconds": (
                    point.get("elapsed_seconds")
                    if point.get("elapsed_seconds") is not None
                    else
                    max(
                        int(
                            (
                                local_checked_at
                                - point_time.astimezone(local_checked_at.tzinfo)
                            ).total_seconds()
                        ),
                        0,
                    )
                    if point_time is not None
                    else None
                ),
                "is_partial": is_partial,
                "finalized": (
                    bool(point.get("finalized"))
                    if isinstance(point.get("finalized"), bool)
                    else not is_partial
                    if point_time is not None
                    else False
                ),
                "volume_status": (
                    str(point.get("volume_status"))
                    if point.get("volume_status")
                    else default_volume_status
                    or ("available" if volume is not None else "not_provided")
                ),
                "bar_ohlc_semantics": (
                    point.get("bar_ohlc_semantics")
                    or default_ohlc_semantics
                ),
            }
        )
        annotated.append(point)
    return annotated, {
        "partial_bar_count": sum(
            1 for point in annotated if point.get("is_partial") is True
        ),
        "indicator_eligible_point_count": sum(
            1
            for point in annotated
            if point.get("finalized") is True
            and point.get("bar_ohlc_semantics") == "interval_ohlc"
        ),
        "partial_bar_policy": "exclude_partial_bars_from_indicators",
        "ohlc_analysis_policy": "confirmed_interval_ohlc_only",
    }


def has_payload_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(has_payload_value(item) for item in value.values())
    if isinstance(value, list):
        return any(has_payload_value(item) for item in value)
    return True


def slot_envelope(
    *,
    status: str,
    capability: str,
    payload_ref: str | None = None,
    payload_level: str | None = None,
    priority: str = "support",
    as_of: str | None = None,
    missing: list[str] | None = None,
    warnings: list[str] | None = None,
    next_fill: str | None = None,
    availability: str | None = None,
    freshness_status: str | None = None,
    usability: str | None = None,
) -> dict[str, Any]:
    derived_availability = availability or (
        "missing"
        if status == "missing"
        else "not_requested"
        if status == "not_requested"
        else "not_applicable"
        if status == "not_applicable"
        else "available"
    )
    derived_freshness = freshness_status or (
        "stale"
        if status == "stale"
        else "not_requested"
        if status == "not_requested"
        else "not_applicable"
        if status == "not_applicable"
        else "missing"
        if status == "missing"
        else "unknown"
    )
    derived_usability = usability or (
        "not_requested"
        if derived_availability == "not_requested"
        else "not_applicable"
        if derived_availability == "not_applicable"
        else "unavailable"
        if derived_availability == "missing" or status in {"missing", "failed", "error"}
        else "blocked"
        if status == "blocked"
        else "limited"
        if derived_freshness == "stale" or status == "partial"
        else "usable"
    )
    slot: dict[str, Any] = {
        "status": status,
        "capability": capability,
        "priority": priority,
        "availability": derived_availability,
        "freshness": {"status": derived_freshness},
        "usability": derived_usability,
    }
    if payload_ref:
        slot["payload_ref"] = payload_ref
    if payload_level:
        slot["payload_level"] = payload_level
    if as_of:
        slot["as_of"] = as_of
    compact_missing = list(dict.fromkeys(missing or []))
    compact_warnings = list(dict.fromkeys(warnings or []))
    if compact_missing:
        slot["missing"] = compact_missing
    if compact_warnings:
        slot["warnings"] = compact_warnings
    if next_fill:
        slot["next_fill"] = next_fill
    return slot


def payload_slot_status(
    payload: Any,
    *,
    missing: list[str] | None = None,
    partial_if_missing: bool = True,
    not_applicable: bool = False,
) -> str:
    if not_applicable:
        return "not_applicable"
    if not has_payload_value(payload):
        return "missing"
    if partial_if_missing and missing:
        return "partial"
    return "ready"
