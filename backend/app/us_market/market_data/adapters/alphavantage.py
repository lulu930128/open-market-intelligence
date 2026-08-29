"""Alpha Vantage pure canonical adapter entrypoint."""

from app.us_market.providers.canonical import (
    canonical_alphavantage_daily_payload as adapt_alphavantage_daily_payload,
)

__all__ = ["adapt_alphavantage_daily_payload"]
