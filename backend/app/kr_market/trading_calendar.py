from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


KR_MARKET_TIMEZONE = ZoneInfo("Asia/Seoul")
KR_DAILY_PRICE_RELEASE_TIME = time(hour=16, minute=10)
KR_MARKET_FIXED_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (3, 1): "Independence Movement Day",
    (5, 5): "Children's Day",
    (6, 6): "Memorial Day",
    (8, 15): "Liberation Day",
    (10, 3): "National Foundation Day",
    (10, 9): "Hangul Day",
    (12, 25): "Christmas Day",
}


def kr_market_holiday_name(value: date) -> str | None:
    if value.month == 12 and value.day == 31:
        return "Year-end market close"

    return KR_MARKET_FIXED_HOLIDAYS.get((value.month, value.day))


def is_kr_trading_day(value: date) -> bool:
    if value.weekday() >= 5:
        return False
    return kr_market_holiday_name(value) is None


def previous_kr_trading_day(value: date, *, include_value: bool = False) -> date:
    current = value if include_value else value - timedelta(days=1)
    while not is_kr_trading_day(current):
        current -= timedelta(days=1)
    return current


def next_kr_trading_day(value: date, *, include_value: bool = False) -> date:
    current = value if include_value else value + timedelta(days=1)
    while not is_kr_trading_day(current):
        current += timedelta(days=1)
    return current


def expected_kr_daily_price_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    local_now = now.astimezone(KR_MARKET_TIMEZONE) if now and now.tzinfo else None
    if local_now is None:
        local_now = (now or datetime.now(KR_MARKET_TIMEZONE)).replace(tzinfo=KR_MARKET_TIMEZONE)

    current_date = local_now.date()
    if include_today is not None:
        return previous_kr_trading_day(current_date, include_value=include_today)

    if is_kr_trading_day(current_date) and local_now.time() >= KR_DAILY_PRICE_RELEASE_TIME:
        return current_date

    return previous_kr_trading_day(current_date, include_value=False)


__all__ = [
    "KR_DAILY_PRICE_RELEASE_TIME",
    "KR_MARKET_TIMEZONE",
    "expected_kr_daily_price_date",
    "is_kr_trading_day",
    "kr_market_holiday_name",
    "next_kr_trading_day",
    "previous_kr_trading_day",
]
