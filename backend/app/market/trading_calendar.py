from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.market.exchange_calendar_cache import cached_market_holiday
from app.market_data.contracts import MarketSession


TAIWAN_TZ = ZoneInfo(settings.timezone)
TAIWAN_PRESENTATION_ROLLOVER_TIME = time(hour=8)
TAIWAN_PREOPEN_TIME = time(hour=8, minute=30)
TAIWAN_SESSION_OPEN_TIME = time(hour=9)
TAIWAN_CLOSING_AUCTION_TIME = time(hour=13, minute=25)
TAIWAN_SESSION_CLOSE_TIME = time(hour=13, minute=30)
TAIWAN_CLOSE_RESOLUTION_TIME = time(hour=13, minute=33)

TAIWAN_SESSION_PHASE_ALIASES = {
    "pre_market": "preopen",
    "preopen_auction": "preopen",
    "open": "regular",
    "regular_live": "regular",
    "daily_close": "post_close",
    "latest_session_close": "post_close",
    "post_close_snapshot": "post_close",
}

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


@dataclass(frozen=True, slots=True)
class TaiwanEmergencyMarketClosure:
    """Market-owned overlay for closures announced outside the annual schedule."""

    name: str
    reason_code: str
    source: str


# Annual schedule caches can prove that a date was absent from the published
# schedule, but that negative knowledge must not suppress a later emergency
# closure.  These overlays therefore have higher precedence than the verified
# annual cache and remain distinct from scheduled holidays.
TAIWAN_EMERGENCY_MARKET_CLOSURES: dict[date, TaiwanEmergencyMarketClosure] = {
    date(2026, 7, 10): TaiwanEmergencyMarketClosure(
        name="Typhoon emergency market closure",
        reason_code="TW_TYPHOON_EMERGENCY_CLOSURE",
        source="Taiwan exchange emergency closure notice",
    ),
}


def taiwan_now(now: datetime | None = None) -> datetime:
    if now is not None:
        return now.astimezone(TAIWAN_TZ)

    return datetime.now(TAIWAN_TZ)


def taiwan_today(now: datetime | None = None) -> date:
    return taiwan_now(now).date()


def taiwan_market_holiday_name(value: date) -> str | None:
    emergency_closure = TAIWAN_EMERGENCY_MARKET_CLOSURES.get(value)
    if emergency_closure is not None:
        return emergency_closure.name
    cached = cached_market_holiday("tw", value)
    if cached.covered:
        return cached.name
    return TAIWAN_MARKET_HOLIDAYS.get(value.year, {}).get(value)


def is_taiwan_market_holiday(value: date) -> bool:
    return taiwan_market_holiday_name(value) is not None


def is_taiwan_trading_day(value: date) -> bool:
    return value.weekday() < 5 and not is_taiwan_market_holiday(value)


def taiwan_market_session_phase(now: datetime) -> str:
    local_now = taiwan_now(now)
    if not is_taiwan_trading_day(local_now.date()):
        return "market_closed"
    current_time = local_now.time()
    if current_time < TAIWAN_PREOPEN_TIME:
        return "preopen_pending"
    if current_time < TAIWAN_SESSION_OPEN_TIME:
        return "preopen"
    if current_time < TAIWAN_CLOSING_AUCTION_TIME:
        return "regular"
    if current_time <= TAIWAN_SESSION_CLOSE_TIME:
        return "closing_auction"
    if current_time < TAIWAN_CLOSE_RESOLUTION_TIME:
        return "close_resolution"
    return "post_close"


def taiwan_presentation_session(now: datetime | None = None) -> dict[str, object]:
    """Resolve the date shown by OMI without claiming a market observation.

    The presentation day rolls at 08:00 Asia/Taipei on an authoritative Taiwan
    trading day.  This deliberately precedes the exchange's 08:30 preopen
    window and must not be interpreted as quote/provider availability.
    """

    local_now = taiwan_now(now)
    current_date = local_now.date()
    current_time = local_now.time()
    is_trading_day = is_taiwan_trading_day(current_date)

    if not is_trading_day:
        trade_date = previous_taiwan_trading_day(current_date, include_value=False)
        next_transition_date = next_taiwan_trading_day(
            current_date,
            include_value=False,
        )
        state = "previous_session"
    elif current_time < TAIWAN_PRESENTATION_ROLLOVER_TIME:
        trade_date = previous_taiwan_trading_day(current_date, include_value=False)
        next_transition_date = current_date
        state = "previous_session"
    elif current_time < TAIWAN_PREOPEN_TIME:
        trade_date = current_date
        next_transition_date = current_date
        state = "today_pending"
    elif current_time < TAIWAN_CLOSE_RESOLUTION_TIME:
        trade_date = current_date
        next_transition_date = current_date
        state = "observing"
    else:
        trade_date = current_date
        next_transition_date = next_taiwan_trading_day(
            current_date,
            include_value=False,
        )
        state = "completed"

    if state == "previous_session":
        transition_time = TAIWAN_PRESENTATION_ROLLOVER_TIME
    elif state == "today_pending":
        transition_time = TAIWAN_PREOPEN_TIME
    elif state == "observing":
        transition_time = TAIWAN_CLOSE_RESOLUTION_TIME
    else:
        transition_time = TAIWAN_PRESENTATION_ROLLOVER_TIME

    next_transition_at = datetime.combine(
        next_transition_date,
        transition_time,
        tzinfo=TAIWAN_TZ,
    )
    return {
        "trade_date": trade_date,
        "state": state,
        "is_current_trading_day": bool(
            is_trading_day and trade_date == current_date
        ),
        "rollover_time": TAIWAN_PRESENTATION_ROLLOVER_TIME.strftime("%H:%M"),
        "next_transition_at": next_transition_at,
    }


def normalize_taiwan_session_phase(value: object) -> str:
    normalized = str(value or "unknown").strip().casefold().replace("-", "_")
    return TAIWAN_SESSION_PHASE_ALIASES.get(normalized, normalized)


def taiwan_market_session_from_phase(value: object) -> MarketSession:
    """Map the market-owned Taiwan phase taxonomy to the shared session enum."""

    normalized = normalize_taiwan_session_phase(value)
    return {
        "preopen_pending": MarketSession.PRE_OPEN,
        "preopen": MarketSession.OPENING_AUCTION,
        "regular": MarketSession.CONTINUOUS,
        "closing_auction": MarketSession.CLOSING_AUCTION,
        "close_resolution": MarketSession.CLOSE_RESOLUTION,
        "post_close": MarketSession.POST_CLOSE,
        "market_closed": MarketSession.CLOSED,
    }.get(normalized, MarketSession.UNKNOWN)


def taiwan_market_session(now: datetime) -> MarketSession:
    """Resolve the shared session enum through the authoritative Taiwan clock."""

    return taiwan_market_session_from_phase(taiwan_market_session_phase(now))


def taiwan_session_is_auction(value: object) -> bool:
    normalized = normalize_taiwan_session_phase(value)
    return normalized in {
        "preopen",
        "closing_auction",
        "disposition_batch_auction",
        "batch_auction",
    }


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
    "TAIWAN_CLOSE_RESOLUTION_TIME",
    "TAIWAN_EMERGENCY_MARKET_CLOSURES",
    "TAIWAN_MARKET_HOLIDAYS",
    "TAIWAN_PRESENTATION_ROLLOVER_TIME",
    "TaiwanEmergencyMarketClosure",
    "is_taiwan_market_holiday",
    "is_taiwan_trading_day",
    "latest_released_trading_day",
    "next_taiwan_trading_day",
    "normalize_taiwan_session_phase",
    "previous_taiwan_trading_day",
    "taiwan_market_session",
    "taiwan_market_session_from_phase",
    "taiwan_market_session_phase",
    "taiwan_market_holiday_name",
    "taiwan_now",
    "taiwan_presentation_session",
    "taiwan_session_is_auction",
    "taiwan_today",
]
