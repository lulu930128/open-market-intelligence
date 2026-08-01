from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.market.exchange_calendar_cache import cached_market_holiday


US_MARKET_TIMEZONE = ZoneInfo("America/New_York")
US_PRE_MARKET_OPEN_TIME = time(hour=4, minute=0)
US_SESSION_OPEN_TIME = time(hour=9, minute=30)
US_SESSION_CLOSE_TIME = time(hour=16, minute=0)
US_POST_MARKET_CLOSE_TIME = time(hour=20, minute=0)
# Daily chart providers can still expose a mutating current-session candle at
# the exact closing boundary. Keep the daily release target behind a small,
# explicit settlement buffer so refresh/read paths only promote completed bars.
US_DAILY_PRICE_RELEASE_TIME = time(hour=16, minute=5)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    value = date(year, month, day)

    if value.weekday() == 5:
        return value - timedelta(days=1)

    if value.weekday() == 6:
        return value + timedelta(days=1)

    return value


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)

    while current.weekday() != weekday:
        current += timedelta(days=1)

    return current + timedelta(days=7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)

    while current.weekday() != weekday:
        current -= timedelta(days=1)

    return current


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1

    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    return set(us_market_holiday_names(year))


def us_market_holiday_names(year: int) -> dict[date, str]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1): "New Year's Day",
        _nth_weekday(year, 1, weekday=0, n=3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, weekday=0, n=3): "Washington's Birthday",
        _easter_sunday(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, weekday=0): "Memorial Day",
        _observed_fixed_holiday(year, 7, 4): "Independence Day",
        _nth_weekday(year, 9, weekday=0, n=1): "Labor Day",
        _nth_weekday(year, 11, weekday=3, n=4): "Thanksgiving Day",
        _observed_fixed_holiday(year, 12, 25): "Christmas Day",
    }

    if year >= 2022:
        holidays[_observed_fixed_holiday(year, 6, 19)] = "Juneteenth National Independence Day"

    return holidays


def us_market_holiday_name(value: date) -> str | None:
    cached = cached_market_holiday("us", value)
    if cached.covered:
        return cached.name
    return us_market_holiday_names(value.year).get(value)


def is_us_trading_day(value: date) -> bool:
    return value.weekday() < 5 and us_market_holiday_name(value) is None


def previous_us_trading_day(value: date, *, include_value: bool = True) -> date:
    current = value if include_value else value - timedelta(days=1)

    while not is_us_trading_day(current):
        current -= timedelta(days=1)

    return current


def next_us_trading_day(value: date, *, include_value: bool = False) -> date:
    current = value if include_value else value + timedelta(days=1)

    while not is_us_trading_day(current):
        current += timedelta(days=1)

    return current


def _as_new_york_datetime(value: datetime | None = None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(US_MARKET_TIMEZONE)


def us_daily_price_finalization_time(trade_date: date) -> datetime:
    return datetime.combine(
        trade_date,
        US_DAILY_PRICE_RELEASE_TIME,
        tzinfo=US_MARKET_TIMEZONE,
    ).astimezone(timezone.utc)


def is_us_daily_price_finalized(
    *,
    trade_date: date,
    fetched_at: datetime | None,
) -> bool:
    if fetched_at is None:
        return False

    normalized_fetched_at = fetched_at
    if normalized_fetched_at.tzinfo is None:
        normalized_fetched_at = normalized_fetched_at.replace(tzinfo=timezone.utc)

    return normalized_fetched_at.astimezone(
        timezone.utc
    ) >= us_daily_price_finalization_time(trade_date)


def expected_us_daily_price_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    local_now = _as_new_york_datetime(now)
    target_date = local_now.date()

    if include_today is False:
        return previous_us_trading_day(target_date, include_value=False)

    if include_today is None:
        if (
            not is_us_trading_day(target_date)
            or local_now.time() < US_DAILY_PRICE_RELEASE_TIME
        ):
            return previous_us_trading_day(target_date, include_value=False)

    return previous_us_trading_day(target_date, include_value=True)


__all__ = [
    "US_DAILY_PRICE_RELEASE_TIME",
    "US_MARKET_TIMEZONE",
    "US_POST_MARKET_CLOSE_TIME",
    "US_PRE_MARKET_OPEN_TIME",
    "US_SESSION_CLOSE_TIME",
    "US_SESSION_OPEN_TIME",
    "expected_us_daily_price_date",
    "is_us_daily_price_finalized",
    "is_us_trading_day",
    "next_us_trading_day",
    "previous_us_trading_day",
    "us_daily_price_finalization_time",
    "us_market_holiday_name",
    "us_market_holiday_names",
    "us_market_holidays",
]
