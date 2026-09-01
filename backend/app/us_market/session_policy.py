"""US-owned temporal bucket policy shared by providers and market services."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.market_data.contracts import MarketSession
from app.us_market.trading_calendar import (
    us_post_market_close_time,
    us_session_close_time,
)


US_EASTERN = ZoneInfo("America/New_York")


def us_session_for_timestamp(value: datetime) -> MarketSession:
    """Map an aware timestamp to the US temporal bucket vocabulary.

    ``CLOSING_AUCTION`` means only that the timestamp falls in the bounded
    close window.  It does not prove an exchange auction, official event, or
    close authority; Market Truth applies that independent evidence policy.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session timestamp must be timezone-aware")
    local = value.astimezone(US_EASTERN)
    wall = local.timetz().replace(tzinfo=None)
    session_close = us_session_close_time(local.date())
    post_market_close = us_post_market_close_time(local.date())
    closing_auction_end = (
        datetime.combine(local.date(), session_close) + timedelta(minutes=1)
    ).time()
    if time(4, 0) <= wall < time(9, 30):
        return MarketSession.PRE_OPEN
    if time(9, 30) <= wall < session_close:
        return MarketSession.CONTINUOUS
    if session_close <= wall < closing_auction_end:
        return MarketSession.CLOSING_AUCTION
    if closing_auction_end <= wall < post_market_close:
        return MarketSession.POST_CLOSE
    return MarketSession.CLOSED


__all__ = ["US_EASTERN", "us_session_for_timestamp"]
