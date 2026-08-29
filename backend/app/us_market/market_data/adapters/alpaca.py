"""Alpaca historical bars pure canonical adapter entrypoint."""

from app.us_market.providers.canonical import (
    canonical_alpaca_stock_bars_payload as adapt_alpaca_stock_bars_payload,
)

__all__ = ["adapt_alpaca_stock_bars_payload"]
