"""Pure temporal identity for evidence projection; no market or freshness policy."""

from datetime import datetime, timezone
from typing import Any


POINT_TIME_FIELDS = (
    "end_at", "event_at", "bar_time", "event_time", "start_at", "time", "date", "trade_date",
)


def parse_projection_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def series_point_time(point: Any) -> Any:
    """Return the original valid timestamp using one shared field precedence."""
    if isinstance(point, dict):
        for field in POINT_TIME_FIELDS:
            value = point.get(field)
            if parse_projection_time(value) is not None:
                return value
    return None


def series_point_sort_key(point: Any) -> datetime:
    return parse_projection_time(series_point_time(point)) or datetime.min.replace(tzinfo=timezone.utc)


def daily_latest_point_mismatch(value: dict[str, Any], point: dict[str, Any]) -> bool:
    """Compare supplied identities only, never infer an expected market session.

    selected_event_at identifies the selected lineage event, which can differ
    from a bar's end. Date metadata is comparable only to an explicit row date;
    converting an arbitrary timestamp to an exchange date belongs to its owner.
    """
    selected = parse_projection_time(value.get("selected_event_at"))
    event = parse_projection_time(point.get("event_at")) or parse_projection_time(series_point_time(point))
    if selected is not None and event is not None and selected != event:
        return True
    row_date = parse_projection_time(point.get("trade_date") or point.get("date"))
    if row_date is not None:
        for field in ("latest_trade_date", "latest_data_date"):
            latest_date = parse_projection_time(value.get(field))
            if latest_date is not None and row_date.date() != latest_date.date():
                return True
    return False
