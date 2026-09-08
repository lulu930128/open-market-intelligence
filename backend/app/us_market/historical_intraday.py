"""US session validation and bounded coverage for completed intraday evidence."""

from datetime import date, datetime, time, timedelta

from app.us_market.trading_calendar import (
    US_MARKET_TIMEZONE, is_us_trading_day, us_session_close_time,
)

US_INTRADAY_HISTORY_DAYS = 35

def completed_intraday_window(
    trade_date: date | str, *, now: datetime, session_scope: str = "regular",
) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    day = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("trade_date must be an ISO date")
    if session_scope not in {"regular", "extended", "all"}:
        raise ValueError("unsupported US session scope")
    if not is_us_trading_day(day):
        raise ValueError("US_INTRADAY_NO_TRADING_SESSION")
    start = datetime.combine(day, time(9, 30) if session_scope == "regular" else time(4), US_MARKET_TIMEZONE)
    end = datetime.combine(day, us_session_close_time(day) if session_scope == "regular" else time(20), US_MARKET_TIMEZONE)
    if now < end:
        raise ValueError("US_INTRADAY_SESSION_NOT_COMPLETED")
    if (now.astimezone(US_MARKET_TIMEZONE).date() - day).days > US_INTRADAY_HISTORY_DAYS:
        raise ValueError("US_INTRADAY_HISTORY_OUTSIDE_BOUNDED_HORIZON")
    return start, end


def regular_intraday_coverage(times: list[datetime], *, trade_date: date) -> dict:
    start = datetime.combine(trade_date, time(9, 30), US_MARKET_TIMEZONE)
    end = datetime.combine(trade_date, us_session_close_time(trade_date), US_MARKET_TIMEZONE)
    expected = {start + timedelta(minutes=i) for i in range(int((end - start).total_seconds() // 60))}
    observed = [value.astimezone(US_MARKET_TIMEZONE) for value in times if start <= value < end]
    unique = set(observed)
    missing = sorted(expected - unique)
    duplicates = len(observed) - len(unique)
    non_monotonic = sum(right < left for left, right in zip(observed, observed[1:]))
    off_grid = len(unique - expected)
    gap_count = sum(index == 0 or value - missing[index - 1] != timedelta(minutes=1) for index, value in enumerate(missing))
    return {
        "expected_point_count": len(expected), "point_count": len(observed),
        "missing_slot_count": len(missing), "duplicate_count": duplicates,
        "non_monotonic_count": non_monotonic, "off_grid_count": off_grid,
        "gap_count": gap_count,
        "first_bar_time": min(observed).isoformat() if observed else None,
        "last_bar_time": max(observed).isoformat() if observed else None,
        "coverage_status": "complete" if not (missing or duplicates or non_monotonic or off_grid) else "partial" if observed else "missing",
    }
