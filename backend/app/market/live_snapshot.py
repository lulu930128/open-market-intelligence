from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


LIVE_MAX_AGE_SECONDS = 180
DELAYED_MAX_AGE_SECONDS = 600
DEFAULT_LIVE_PHASES = frozenset({"regular", "regular_live", "closing_auction"})


def _parse_datetime(value: Any, *, timezone_name: str) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text or len(text) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(ZoneInfo(timezone_name))


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def market_status_from_session(calendar_status: dict[str, Any]) -> str:
    phase = str(calendar_status.get("phase") or "unknown")
    if not calendar_status.get("is_trading_day"):
        return "closed_holiday" if calendar_status.get("reason") == "holiday" else "closed"
    return {
        "preopen_pending": "preopen",
        "pre_market_pending": "preopen",
        "preopen": "preopen",
        "pre_market": "preopen",
        "regular": "open",
        "regular_live": "open",
        "lunch_break": "lunch_break",
        "closing_auction": "closing_auction",
        "after_hours": "after_hours",
        "post_close": "latest_session_close",
        "post_close_snapshot": "latest_session_close",
        "market_closed": "closed",
    }.get(phase, phase)


def classify_market_snapshot(
    *,
    calendar_status: dict[str, Any],
    quote_time: Any,
    live_max_age_seconds: int = LIVE_MAX_AGE_SECONDS,
    delayed_max_age_seconds: int = DELAYED_MAX_AGE_SECONDS,
    live_phases: Iterable[str] = DEFAULT_LIVE_PHASES,
) -> dict[str, Any]:
    timezone_name = str(calendar_status.get("timezone") or "UTC")
    checked_at = _parse_datetime(
        calendar_status.get("checked_at"),
        timezone_name=timezone_name,
    ) or datetime.now(ZoneInfo(timezone_name))
    quote_at = _parse_datetime(quote_time, timezone_name=timezone_name)
    quote_date = quote_at.date() if quote_at is not None else _parse_date(quote_time)
    current_date = _parse_date(calendar_status.get("date")) or checked_at.date()
    previous_trading_day = _parse_date(calendar_status.get("previous_trading_day"))
    phase = str(calendar_status.get("phase") or "unknown")
    is_trading_day = calendar_status.get("is_trading_day") is True
    is_live_phase = phase in set(live_phases)
    market_status = market_status_from_session(calendar_status)
    age_seconds = (
        max(int((checked_at - quote_at).total_seconds()), 0)
        if quote_at is not None
        else None
    )

    if quote_date is None:
        status = "missing"
        semantics = "unavailable"
        is_stale = True
        is_latest_session = False
    elif is_trading_day and is_live_phase:
        is_current_session = quote_date == current_date
        if not is_current_session:
            status = "stale"
        elif age_seconds is not None and age_seconds <= live_max_age_seconds:
            status = "live"
        elif age_seconds is not None and age_seconds <= delayed_max_age_seconds:
            status = "delayed"
        else:
            status = "stale"
        semantics = "current_session" if is_current_session else "previous_session"
        is_stale = status == "stale"
        is_latest_session = is_current_session and status in {"live", "delayed"}
    else:
        expected_session_date = (
            current_date
            if is_trading_day
            and phase
            in {"lunch_break", "post_close", "post_close_snapshot", "after_hours"}
            else previous_trading_day
        )
        is_latest_session = bool(expected_session_date and quote_date == expected_session_date)
        status = "latest_completed_session" if is_latest_session else "stale"
        semantics = "latest_completed_session" if is_latest_session else "previous_session"
        is_stale = not is_latest_session

    is_live = status == "live"
    session = calendar_status.get("session") if isinstance(calendar_status.get("session"), dict) else {}
    return {
        "status": status,
        "quote_semantics": semantics,
        "is_live": is_live,
        "is_realtime": is_live,
        "is_stale": is_stale,
        "is_latest_session_quote": is_latest_session,
        "age_seconds": age_seconds,
        "market_status": market_status,
        "current_session_phase": phase,
        "last_quote_session": quote_date.isoformat() if quote_date else None,
        "expected_trade_date": (
            current_date.isoformat()
            if is_trading_day and is_live_phase
            else previous_trading_day.isoformat()
            if previous_trading_day
            else None
        ),
        "timezone": timezone_name,
        "session_start": session.get("open_time"),
        "session_end": session.get("close_time"),
        "holiday_name": calendar_status.get("holiday_name"),
        "next_open_date": calendar_status.get("next_trading_day"),
    }


__all__ = [
    "DELAYED_MAX_AGE_SECONDS",
    "LIVE_MAX_AGE_SECONDS",
    "classify_market_snapshot",
    "market_status_from_session",
]
