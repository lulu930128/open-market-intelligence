"""KR regular-session daily evidence validation shared by writer and reader."""

from datetime import datetime, time

from app.kr_market.trading_calendar import KR_DAILY_PRICE_RELEASE_TIME, KR_MARKET_TIMEZONE, is_kr_trading_day
from app.market_data.contracts import BarFinalization, BarObservation


def validate_completed_daily_bar(bar: BarObservation) -> None:
    trade_date = bar.end_at.astimezone(KR_MARKET_TIMEZONE).date()
    if (bar.interval != "1d" or bar.finalization != BarFinalization.FINAL
        or bar.start_at != datetime.combine(trade_date, time(9), KR_MARKET_TIMEZONE)
        or bar.end_at != datetime.combine(trade_date, time(15, 30), KR_MARKET_TIMEZONE)
        or not is_kr_trading_day(trade_date)):
        raise ValueError("KR_DAILY_SESSION_INVALID")
    if (bar.lineage.event_at != bar.end_at
        or bar.lineage.fetched_at < datetime.combine(trade_date, KR_DAILY_PRICE_RELEASE_TIME, KR_MARKET_TIMEZONE)):
        raise ValueError("KR_DAILY_RELEASE_INVALID")
