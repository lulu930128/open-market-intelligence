"""Research calendar dispatch; market calendar owners retain all session rules."""
from datetime import date, datetime
from typing import Literal

ResearchMarket = Literal["TW", "US"]


def market_timezone(market: ResearchMarket):
    if market == "US":
        from app.us_market.trading_calendar import US_MARKET_TIMEZONE
        return US_MARKET_TIMEZONE
    from app.market.trading_calendar import TAIWAN_TZ
    return TAIWAN_TZ


def frozen_sessions(market: ResearchMarket, effective_at: datetime, count: int):
    anchor = effective_at.astimezone(market_timezone(market)).date()
    if market == "TW":
        from app.market.trading_calendar import has_taiwan_calendar_year
        from app.watchlists.radar_outcome_v2_service import trading_dates_after
        dates = tuple(trading_dates_after(anchor, count))
        return dates, all(has_taiwan_calendar_year(d.year) for d in (anchor, *dates))
    from app.us_market.trading_calendar import next_us_trading_day
    from app.market.calendar_status import build_us_calendar_status
    dates = []
    current = anchor
    for _ in range(count):
        current = next_us_trading_day(current)
        dates.append(current)
    years = build_us_calendar_status(effective_at).get("calendar_verified_years", [])
    return tuple(dates), all(d.year in years for d in (anchor, *dates))


def session_close(market: ResearchMarket, day: date) -> datetime:
    if market == "US":
        from app.us_market.trading_calendar import us_session_close_time
        clock = us_session_close_time(day)
    else:
        from app.market.trading_calendar import TAIWAN_SESSION_CLOSE_TIME
        clock = TAIWAN_SESSION_CLOSE_TIME
    return datetime.combine(day, clock, market_timezone(market))
