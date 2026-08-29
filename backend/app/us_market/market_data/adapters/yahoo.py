"""Yahoo Chart pure canonical adapter entrypoint."""

from app.us_market.providers.canonical import (
    canonical_yahoo_chart_payload as adapt_yahoo_chart_payload,
)

__all__ = ["adapt_yahoo_chart_payload"]
