"""Post-close research windows; exchange dates and release clocks stay calendar-owned."""
from datetime import datetime, timedelta

from app.us_market.trading_calendar import (
    US_MARKET_TIMEZONE, US_PRE_MARKET_OPEN_TIME, expected_us_daily_price_date,
    next_us_trading_day, us_daily_price_release_time,
)

INTERVAL_MINUTES = 10
RELEASE_DELAY_MINUTES = 10
CRON_MINUTES = "5-59/10"


def postclose_schedule(now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("Research scheduling requires a timezone-aware timestamp.")
    local = now.astimezone(US_MARKET_TIMEZONE)
    basis = expected_us_daily_price_date(now=now)

    def opens(day):
        return datetime.combine(day, us_daily_price_release_time(day), US_MARKET_TIMEZONE) + timedelta(
            minutes=RELEASE_DELAY_MINUTES)

    opening = opens(basis)
    closing = datetime.combine(basis + timedelta(days=1), US_PRE_MARKET_OPEN_TIME, US_MARKET_TIMEZONE)
    in_window = opening <= local < closing
    following = opens(next_us_trading_day(basis))
    if local < opening:
        next_tick = opening
    elif in_window:
        next_tick = local.replace(second=0, microsecond=0)
        next_tick += timedelta(minutes=(5 - next_tick.minute) % INTERVAL_MINUTES)
        if next_tick < local:
            next_tick += timedelta(minutes=INTERVAL_MINUTES)
        if next_tick >= closing:
            next_tick = following
    else:
        next_tick = following
    return {
        "timezone": str(US_MARKET_TIMEZONE), "interval_minutes": INTERVAL_MINUTES,
        "basis_trade_date": basis.isoformat(), "in_window": in_window,
        "window_opens_at": opening.isoformat(), "window_closes_at": closing.isoformat(),
        "next_check_at": next_tick.isoformat(), "following_window_at": following.isoformat(),
    }
