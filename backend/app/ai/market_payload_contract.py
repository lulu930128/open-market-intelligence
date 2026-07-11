from __future__ import annotations

from typing import Any


COMPACT_INTRADAY_BAR_LIMIT = 80
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
) -> dict[str, Any]:
    slot: dict[str, Any] = {
        "status": status,
        "capability": capability,
        "priority": priority,
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
