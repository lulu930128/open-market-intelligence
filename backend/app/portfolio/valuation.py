"""Portfolio-plane dispatcher over market-owned valuation readers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.jp_market.valuation import read_jp_valuation_price
from app.kr_market.valuation import read_kr_valuation_price
from app.market.portfolio_valuation import read_taiwan_valuation_price
from app.market_data.valuation import ValuationPriceEvidence
from app.us_market.valuation import read_us_valuation_price


_READERS = {
    "tw": read_taiwan_valuation_price,
    "us": read_us_valuation_price,
    "jp": read_jp_valuation_price,
    "kr": read_kr_valuation_price,
}


def read_portfolio_market_valuation(
    db: Session,
    *,
    market: str,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    normalized_market = str(market or "").strip().casefold()
    reader = _READERS.get(normalized_market)
    if reader is None:
        raise ValueError("portfolio valuation market must be one of: tw, us, jp, kr")
    return reader(
        db,
        symbol=str(symbol or "").strip().upper(),
        requested_at=requested_at,
    )


__all__ = ["read_portfolio_market_valuation"]
