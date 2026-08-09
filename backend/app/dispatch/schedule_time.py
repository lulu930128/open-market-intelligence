from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.market.trading_calendar import is_taiwan_trading_day


UTC = timezone.utc
WEEKDAY_INDEXES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
DAY_OF_WEEK_ALIASES = {
    "*": "daily",
    "all": "daily",
    "everyday": "daily",
    "daily": "daily",
    "weekday": "mon-fri",
    "weekdays": "mon-fri",
    "workday": "mon-fri",
    "workdays": "mon-fri",
    "weekend": "sat,sun",
    "weekends": "sat,sun",
}


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_db_value(value: datetime) -> datetime:
    """Return a naive UTC value for SQLite DateTime comparisons."""
    return ensure_utc(value).replace(tzinfo=None)


def normalize_send_time(value: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError("send_time must use HH:MM format.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError("send_time must use HH:MM format.") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("send_time must be within a 24-hour clock.")
    return f"{hour:02d}:{minute:02d}"


def _weekday_token_range(token: str) -> set[int]:
    if "-" not in token:
        if token not in WEEKDAY_INDEXES:
            raise ValueError(f"Unsupported day_of_week token: {token}")
        return {WEEKDAY_INDEXES[token]}
    start, end = token.split("-", maxsplit=1)
    if start not in WEEKDAY_INDEXES or end not in WEEKDAY_INDEXES:
        raise ValueError(f"Unsupported day_of_week range: {token}")
    start_index = WEEKDAY_INDEXES[start]
    end_index = WEEKDAY_INDEXES[end]
    if start_index <= end_index:
        return set(range(start_index, end_index + 1))
    return {*range(start_index, 7), *range(0, end_index + 1)}


def normalize_day_of_week(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    text = DAY_OF_WEEK_ALIASES.get(text, text)
    if not text:
        raise ValueError("day_of_week is required.")
    if text == "daily":
        return text
    tokens = [token for token in text.split(",") if token]
    if not tokens:
        raise ValueError("day_of_week is required.")
    for token in tokens:
        _weekday_token_range(token)
    return ",".join(tokens)


def normalize_timezone(value: str) -> str:
    timezone_name = str(value or "").strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unsupported timezone: {timezone_name}") from exc
    return timezone_name


def weekday_matches(day_of_week: str, weekday: int) -> bool:
    normalized = normalize_day_of_week(day_of_week)
    if normalized == "daily":
        return True
    return any(weekday in _weekday_token_range(token) for token in normalized.split(","))


def _valid_schedule_date(
    *,
    local_date,
    calendar_mode: str,
    day_of_week: str,
) -> bool:
    normalized_mode = str(calendar_mode or "weekdays").strip().lower()
    if normalized_mode == "calendar_days":
        return True
    if normalized_mode == "weekdays":
        return weekday_matches(day_of_week, local_date.weekday())
    if normalized_mode == "tw_trading_days":
        return is_taiwan_trading_day(local_date) and weekday_matches(
            day_of_week,
            local_date.weekday(),
        )
    raise ValueError(f"Unsupported calendar_mode: {calendar_mode}")


def _resolve_local_datetime(
    *,
    local_date,
    send_time: str,
    timezone_value: ZoneInfo,
) -> datetime:
    hour, minute = (int(part) for part in normalize_send_time(send_time).split(":"))
    naive_candidate = datetime.combine(local_date, time(hour=hour, minute=minute))

    for offset_minutes in range(181):
        candidate_naive = naive_candidate + timedelta(minutes=offset_minutes)
        candidate = candidate_naive.replace(tzinfo=timezone_value, fold=0)
        round_trip = candidate.astimezone(UTC).astimezone(timezone_value)
        if round_trip.replace(tzinfo=None) == candidate_naive:
            return candidate

    raise ValueError(
        f"Unable to resolve a valid local schedule time near {naive_candidate.isoformat()}."
    )


def compute_next_run_at(
    *,
    send_time: str,
    day_of_week: str,
    timezone_name: str,
    calendar_mode: str,
    after: datetime,
    inclusive: bool = False,
    max_days: int = 370,
) -> datetime:
    current_utc = ensure_utc(after)
    timezone_value = ZoneInfo(normalize_timezone(timezone_name))
    local_after = current_utc.astimezone(timezone_value)

    for offset_days in range(max(max_days, 1)):
        local_date = local_after.date() + timedelta(days=offset_days)
        if not _valid_schedule_date(
            local_date=local_date,
            calendar_mode=calendar_mode,
            day_of_week=day_of_week,
        ):
            continue
        candidate = _resolve_local_datetime(
            local_date=local_date,
            send_time=send_time,
            timezone_value=timezone_value,
        )
        candidate_utc = candidate.astimezone(UTC)
        if candidate_utc > current_utc or (inclusive and candidate_utc == current_utc):
            return candidate_utc

    raise ValueError("Unable to find a valid schedule date within the bounded search window.")


def scheduled_slot_key(value: datetime) -> str:
    normalized = ensure_utc(value)
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
