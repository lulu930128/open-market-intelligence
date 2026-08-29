from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from app.us_market.trading_calendar import is_us_trading_day


MAX_OUTWARD_MISSING_TRADE_DATES = 20


def us_trading_dates_between(start_date: date, end_date: date) -> tuple[date, ...]:
    if end_date < start_date:
        return ()

    current = start_date
    dates: list[date] = []
    while current <= end_date:
        if is_us_trading_day(current):
            dates.append(current)
        current += timedelta(days=1)
    return tuple(dates)


def build_us_daily_continuity(
    *,
    available_dates: Iterable[date],
    expected_data_date: date,
    available_bar_count: int,
    requested_bar_count: int,
    history_fetch_scope: str = "unknown",
    missing_sample_limit: int = MAX_OUTWARD_MISSING_TRADE_DATES,
) -> dict:
    normalized_dates = tuple(
        sorted({value for value in available_dates if value <= expected_data_date})
    )
    latest_data_date = normalized_dates[-1] if normalized_dates else None
    first_data_date = normalized_dates[0] if normalized_dates else None
    expected_dates = (
        us_trading_dates_between(first_data_date, expected_data_date)
        if first_data_date is not None
        else ()
    )
    available_date_set = set(normalized_dates)
    missing_dates = tuple(
        trade_date
        for trade_date in expected_dates
        if trade_date not in available_date_set
    )

    contiguous_through_date = None
    for trade_date in expected_dates:
        if trade_date not in available_date_set:
            break
        contiguous_through_date = trade_date

    continuity_status = (
        "missing"
        if not normalized_dates
        else "partial"
        if missing_dates
        else "complete"
    )
    normalized_history_fetch_scope = str(history_fetch_scope or "unknown").strip().lower()
    history_status = (
        "missing"
        if available_bar_count <= 0
        else "complete"
        if available_bar_count >= requested_bar_count
        else "best_available"
        if normalized_history_fetch_scope == "full"
        else "insufficient_history"
    )
    coverage_status = (
        "complete"
        if continuity_status == "complete" and history_status == "complete"
        else "best_available"
        if continuity_status == "complete" and history_status == "best_available"
        else "missing"
        if continuity_status == "missing" and history_status == "missing"
        else "partial"
    )
    sample_limit = max(int(missing_sample_limit), 0)
    missing_sample = missing_dates[-sample_limit:] if sample_limit else ()

    return {
        "coverage_status": coverage_status,
        "continuity_status": continuity_status,
        "history_status": history_status,
        "history_fetch_scope": normalized_history_fetch_scope,
        "first_data_date": first_data_date,
        "latest_finalized_data_date": latest_data_date,
        "continuity_start_date": first_data_date,
        "contiguous_through_date": contiguous_through_date,
        "latest_expected_date_present": expected_data_date in available_date_set,
        "missing_trade_date_count": len(missing_dates),
        "missing_trade_dates": list(missing_sample),
        "missing_trade_dates_truncated": len(missing_dates) > len(missing_sample),
        "requested_bar_count": requested_bar_count,
        "available_bar_count": available_bar_count,
    }


__all__ = [
    "MAX_OUTWARD_MISSING_TRADE_DATES",
    "build_us_daily_continuity",
    "us_trading_dates_between",
]
