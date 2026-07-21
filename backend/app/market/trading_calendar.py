from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.market.exchange_calendar_cache import cached_market_holiday


TAIWAN_TZ = ZoneInfo(settings.timezone)

# Official exchange closures that are not captured by weekday checks.
# Years not listed fall back to Monday-Friday trading days.
TAIWAN_MARKET_HOLIDAYS: dict[int, dict[date, str]] = {
    2025: {
        date(2025, 1, 1): "New Year's Day",
        date(2025, 1, 27): "Lunar New Year market closure",
        date(2025, 1, 28): "Lunar New Year's Eve",
        date(2025, 1, 29): "Lunar New Year",
        date(2025, 1, 30): "Lunar New Year",
        date(2025, 1, 31): "Lunar New Year",
        date(2025, 2, 28): "Peace Memorial Day",
        date(2025, 4, 3): "Children's Day / Tomb Sweeping Day",
        date(2025, 4, 4): "Children's Day / Tomb Sweeping Day",
        date(2025, 5, 1): "Labor Day",
        date(2025, 5, 30): "Dragon Boat Festival",
        date(2025, 10, 6): "Mid-Autumn Festival",
        date(2025, 10, 10): "National Day",
    },
    2026: {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 2, 12): "Lunar New Year market closure",
        date(2026, 2, 13): "Lunar New Year market closure",
        date(2026, 2, 16): "Lunar New Year",
        date(2026, 2, 17): "Lunar New Year",
        date(2026, 2, 18): "Lunar New Year",
        date(2026, 2, 19): "Lunar New Year",
        date(2026, 2, 20): "Lunar New Year compensatory holiday",
        date(2026, 2, 27): "Peace Memorial Day compensatory holiday",
        date(2026, 4, 3): "Children's Day / Tomb Sweeping Day",
        date(2026, 4, 6): "Children's Day / Tomb Sweeping Day compensatory holiday",
        date(2026, 5, 1): "Labor Day",
        date(2026, 6, 19): "Dragon Boat Festival",
        date(2026, 9, 25): "Mid-Autumn Festival",
        date(2026, 9, 28): "Teacher's Day",
        date(2026, 10, 9): "National Day compensatory holiday",
        date(2026, 10, 26): "Taiwan Retrocession Day compensatory holiday",
        date(2026, 12, 25): "Constitution Day",
    },
}


def taiwan_now(now: datetime | None = None) -> datetime:
    if now is not None:
        return now.astimezone(TAIWAN_TZ)

    return datetime.now(TAIWAN_TZ)


def taiwan_today(now: datetime | None = None) -> date:
    return taiwan_now(now).date()


def taiwan_market_holiday_name(value: date) -> str | None:
    cached = cached_market_holiday("tw", value)
    if cached.covered:
        return cached.name
    return TAIWAN_MARKET_HOLIDAYS.get(value.year, {}).get(value)


def is_taiwan_market_holiday(value: date) -> bool:
    return taiwan_market_holiday_name(value) is not None


def is_taiwan_trading_day(value: date) -> bool:
    return value.weekday() < 5 and not is_taiwan_market_holiday(value)


def previous_taiwan_trading_day(value: date, *, include_value: bool = True) -> date:
    current = value if include_value else value - timedelta(days=1)

    while not is_taiwan_trading_day(current):
        current -= timedelta(days=1)

    return current


def next_taiwan_trading_day(value: date, *, include_value: bool = False) -> date:
    current = value if include_value else value + timedelta(days=1)

    while not is_taiwan_trading_day(current):
        current += timedelta(days=1)

    return current


def latest_released_trading_day(
    *,
    release_time: time,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    local_now = taiwan_now(now)
    target_date = local_now.date()

    if include_today is False:
        return previous_taiwan_trading_day(target_date, include_value=False)

    if include_today is None:
        if not is_taiwan_trading_day(target_date) or local_now.time() < release_time:
            return previous_taiwan_trading_day(target_date, include_value=False)

    return previous_taiwan_trading_day(target_date, include_value=True)


__all__ = [
    "TAIWAN_MARKET_HOLIDAYS",
    "is_taiwan_market_holiday",
    "is_taiwan_trading_day",
    "latest_released_trading_day",
    "next_taiwan_trading_day",
    "previous_taiwan_trading_day",
    "taiwan_market_holiday_name",
    "taiwan_now",
    "taiwan_today",
]
