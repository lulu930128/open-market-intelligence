from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any


SourceHealthStatus = tuple[str, bool, str, str]


def generated_at() -> datetime:
    return datetime.now(timezone.utc)


def freshness_lag_days(expected: date | None, latest: date | None) -> int | None:
    if expected is None or latest is None:
        return None
    return max((expected - latest).days, 0)


def daily_row_status(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
    empty_reason: str,
    current_reason: str,
    available_reason: str,
) -> SourceHealthStatus:
    if row_count <= 0:
        return "empty", False, "empty", empty_reason

    if freshness_required and expected_data_date is not None and latest_data_date is not None:
        if latest_data_date < expected_data_date:
            return (
                "stale",
                False,
                "stale",
                f"Latest data date {latest_data_date.isoformat()} is behind expected "
                f"{expected_data_date.isoformat()}.",
            )
        return "current", True, "ok", current_reason

    return "available", True, "ok", available_reason


def source_health_entry_value(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def summarize_source_health(
    entries: Iterable[Any],
    *,
    counted_statuses: Iterable[str],
    error_statuses: Iterable[str] | None = None,
    count_recent_errors: bool = False,
) -> dict[str, int]:
    rows = list(entries)
    summary = {
        "entry_count": len(rows),
        "ok_count": sum(1 for entry in rows if bool(source_health_entry_value(entry, "ok"))),
    }
    normalized_error_statuses = set(error_statuses or {"error"})

    for status in counted_statuses:
        normalized_status = str(status).strip().lower()
        if not normalized_status:
            continue
        key = f"{normalized_status}_count"
        if normalized_status == "error":
            summary[key] = sum(
                1
                for entry in rows
                if str(source_health_entry_value(entry, "status", "")).lower()
                in normalized_error_statuses
                or (
                    count_recent_errors
                    and int(source_health_entry_value(entry, "recent_error_count", 0) or 0) > 0
                )
            )
            continue
        summary[key] = sum(
            1
            for entry in rows
            if str(source_health_entry_value(entry, "status", "")).lower() == normalized_status
        )

    return summary


__all__ = [
    "SourceHealthStatus",
    "daily_row_status",
    "freshness_lag_days",
    "generated_at",
    "source_health_entry_value",
    "summarize_source_health",
]
