"""JP session boundaries with the exchange's effective-date close change."""

from datetime import date, datetime, time
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE


def jp_close_time(day: date) -> time:
    return time(15, 30) if day >= date(2024, 11, 5) else time(15)


def jp_session_phase(timestamp: datetime) -> str:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("JP session timestamp must be timezone-aware")
    local = timestamp.astimezone(JP_MARKET_TIMEZONE)
    clock = local.time().replace(tzinfo=None)
    if clock < time(9):
        return "pre_market"
    if time(11, 30) < clock < time(12, 30):
        return "lunch_break"
    if clock > jp_close_time(local.date()):
        return "post_close"
    if local.date() >= date(2024, 11, 5) and clock >= time(15, 25):
        return "closing_auction"
    return "regular"


def is_expected_jp_bar_gap(previous: datetime, current: datetime) -> bool:
    """Recognize exact 1m session boundaries without hiding missing regular bars."""
    if previous.tzinfo is None or current.tzinfo is None:
        return False
    previous = previous.astimezone(JP_MARKET_TIMEZONE)
    current = current.astimezone(JP_MARKET_TIMEZONE)
    if previous.date() != current.date():
        return False
    before = previous.time().replace(tzinfo=None)
    after = current.time().replace(tzinfo=None)
    if before in {time(11, 29), time(11, 30)} and after == time(12, 30):
        return True
    return (previous.date() >= date(2024, 11, 5)
            and before == time(15, 24) and after == time(15, 30))
