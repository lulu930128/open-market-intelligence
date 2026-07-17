from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


JP_MARKET_TIMEZONE = ZoneInfo("Asia/Tokyo")
JP_SESSION_OPEN_TIME = time(hour=9, minute=0)
JP_LUNCH_START_TIME = time(hour=11, minute=30)
JP_LUNCH_END_TIME = time(hour=12, minute=30)
JP_SESSION_CLOSE_TIME = time(hour=15, minute=30)
JP_DAILY_PRICE_RELEASE_TIME = time(hour=16, minute=10)

# JPX publishes the current and following year's market holidays. These years
# were checked against the JPX market-holiday table when this calendar was added.
JPX_VERIFIED_CALENDAR_YEARS = frozenset({2025, 2026, 2027})
JPX_CALENDAR_SOURCE = "JPX market holidays and Japan National Holidays Act rules"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def _vernal_equinox_day(year: int) -> int:
    # Cabinet Office equinox dates are announced annually. This approximation is
    # valid for the product's supported modern-year range (1980-2099).
    return int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)


def _autumnal_equinox_day(year: int) -> int:
    return int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)


def jp_national_holiday_names(year: int) -> dict[date, str]:
    holidays: dict[date, str] = {
        date(year, 1, 1): "New Year's Day",
        _nth_weekday(year, 1, weekday=0, n=2): "Coming of Age Day",
        date(year, 2, 11): "National Foundation Day",
        date(year, 3, _vernal_equinox_day(year)): "Vernal Equinox",
        date(year, 4, 29): "Showa Day",
        date(year, 5, 3): "Constitution Memorial Day",
        date(year, 5, 4): "Greenery Day",
        date(year, 5, 5): "Children's Day",
        _nth_weekday(year, 7, weekday=0, n=3): "Marine Day",
        _nth_weekday(year, 9, weekday=0, n=3): "Respect for the Aged Day",
        date(year, 9, _autumnal_equinox_day(year)): "Autumnal Equinox",
        _nth_weekday(year, 10, weekday=0, n=2): "Sports Day",
        date(year, 11, 3): "Culture Day",
        date(year, 11, 23): "Labor Thanksgiving Day",
    }

    if year >= 2016:
        holidays[date(year, 8, 11)] = "Mountain Day"
    if year >= 2020:
        holidays[date(year, 2, 23)] = "Emperor's Birthday"

    # A weekday between two national holidays is also a holiday. This covers,
    # for example, September 22, 2026.
    current = date(year, 1, 2)
    last = date(year, 12, 30)
    citizen_holidays: dict[date, str] = {}
    while current <= last:
        if (
            current.weekday() < 5
            and current not in holidays
            and current - timedelta(days=1) in holidays
            and current + timedelta(days=1) in holidays
        ):
            citizen_holidays[current] = "Citizen's Holiday"
        current += timedelta(days=1)
    holidays.update(citizen_holidays)

    # A Sunday holiday is observed on the next day that is not already a
    # national holiday. Modern Japanese rules can carry the observed date past
    # a sequence such as Golden Week.
    observed_holidays: dict[date, str] = {}
    for holiday, name in sorted(holidays.items()):
        if holiday.weekday() != 6:
            continue
        observed = holiday + timedelta(days=1)
        while observed in holidays or observed in observed_holidays:
            observed += timedelta(days=1)
        observed_holidays[observed] = f"{name} observed"
    holidays.update(observed_holidays)
    return holidays


def jp_market_holiday_names(year: int) -> dict[date, str]:
    holidays = jp_national_holiday_names(year)
    holidays.setdefault(date(year, 1, 2), "Market Holiday")
    holidays.setdefault(date(year, 1, 3), "Market Holiday")
    holidays.setdefault(date(year, 12, 31), "Market Holiday")
    return holidays


def jp_market_holiday_name(value: date) -> str | None:
    return jp_market_holiday_names(value.year).get(value)


def is_jp_trading_day(value: date) -> bool:
    return value.weekday() < 5 and jp_market_holiday_name(value) is None


def previous_jp_trading_day(value: date, *, include_value: bool = True) -> date:
    current = value if include_value else value - timedelta(days=1)
    while not is_jp_trading_day(current):
        current -= timedelta(days=1)
    return current


def next_jp_trading_day(value: date, *, include_value: bool = False) -> date:
    current = value if include_value else value + timedelta(days=1)
    while not is_jp_trading_day(current):
        current += timedelta(days=1)
    return current


def _as_tokyo_datetime(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(JP_MARKET_TIMEZONE)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JP_MARKET_TIMEZONE)


def expected_jp_daily_price_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    local_now = _as_tokyo_datetime(now)
    current_date = local_now.date()

    if include_today is False:
        return previous_jp_trading_day(current_date, include_value=False)

    if include_today is None and (
        not is_jp_trading_day(current_date)
        or local_now.time() < JP_DAILY_PRICE_RELEASE_TIME
    ):
        return previous_jp_trading_day(current_date, include_value=False)

    return previous_jp_trading_day(current_date, include_value=True)


def jp_calendar_limit(year: int) -> str | None:
    if year in JPX_VERIFIED_CALENDAR_YEARS:
        return None
    return (
        "National-holiday rules are calculated outside the JPX-verified "
        "2025-2027 range; emergency exchange closures require a calendar update."
    )


__all__ = [
    "JPX_CALENDAR_SOURCE",
    "JPX_VERIFIED_CALENDAR_YEARS",
    "JP_DAILY_PRICE_RELEASE_TIME",
    "JP_LUNCH_END_TIME",
    "JP_LUNCH_START_TIME",
    "JP_MARKET_TIMEZONE",
    "JP_SESSION_CLOSE_TIME",
    "JP_SESSION_OPEN_TIME",
    "expected_jp_daily_price_date",
    "is_jp_trading_day",
    "jp_calendar_limit",
    "jp_market_holiday_name",
    "jp_market_holiday_names",
    "jp_national_holiday_names",
    "next_jp_trading_day",
    "previous_jp_trading_day",
]
