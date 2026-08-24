"""Pure US intraday volume normalization and coverage semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_EXTENDED_SESSIONS = frozenset({"pre_market", "after_hours"})


def normalize_yahoo_intraday_volume(
    value: int | None,
    *,
    session: str,
) -> tuple[int | None, str]:
    """Treat Yahoo extended-hours zero fills as unknown, not traded zero."""

    if value is None:
        return None, "not_provided"
    if session in _EXTENDED_SESSIONS and value == 0:
        return None, "provider_unavailable"
    return value, "available"


def summarize_intraday_volume(
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return truthful aggregate coverage without turning partial sums into totals."""

    total_count = len(points)
    available_count = sum(1 for point in points if point.get("volume") is not None)
    unavailable_count = total_count - available_count
    regular_count = sum(
        1
        for point in points
        if point.get("session") == "regular" and point.get("volume") is not None
    )
    extended_count = sum(
        1
        for point in points
        if point.get("session") in _EXTENDED_SESSIONS
        and point.get("volume") is not None
    )
    extended_unavailable_count = sum(
        1
        for point in points
        if point.get("session") in _EXTENDED_SESSIONS
        and point.get("volume") is None
    )

    if total_count == 0:
        status = "not_provided"
    elif available_count == total_count:
        status = "available"
    elif available_count == 0:
        status = "provider_unavailable"
    else:
        status = "partial"

    return {
        "volume_unit": "shares" if available_count else None,
        "volume_semantics": (
            "interval_shares"
            if status == "available"
            else "partial_interval_shares"
            if status == "partial"
            else None
        ),
        "volume_status": status,
        "volume_coverage": {
            "point_count": total_count,
            "available_point_count": available_count,
            "unavailable_point_count": unavailable_count,
            "regular_available_point_count": regular_count,
            "extended_available_point_count": extended_count,
            "extended_unavailable_point_count": extended_unavailable_count,
            "complete": total_count > 0 and unavailable_count == 0,
        },
    }


__all__ = [
    "normalize_yahoo_intraday_volume",
    "summarize_intraday_volume",
]
