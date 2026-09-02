"""Pure US provider-payload to Canonical Observation adapters."""

from app.us_market.market_data.adapters.alphavantage import (
    adapt_alphavantage_daily_payload,
)
from app.us_market.market_data.adapters.alpaca import adapt_alpaca_stock_bars_payload
from app.us_market.market_data.adapters.massive import (
    adapt_massive_index_aggregates_payload,
    adapt_massive_index_snapshot_payload,
)
from app.us_market.market_data.adapters.twelve_data import (
    adapt_twelve_data_intraday_payload,
    adapt_twelve_data_quote_payload,
)
from app.us_market.market_data.adapters.yahoo import adapt_yahoo_chart_payload

__all__ = [
    "adapt_alphavantage_daily_payload",
    "adapt_alpaca_stock_bars_payload",
    "adapt_massive_index_aggregates_payload",
    "adapt_massive_index_snapshot_payload",
    "adapt_twelve_data_intraday_payload",
    "adapt_twelve_data_quote_payload",
    "adapt_yahoo_chart_payload",
]
