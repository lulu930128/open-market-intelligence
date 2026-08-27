"""Japan market-owned cached valuation projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.jp_market.service import _latest_distinct_jp_daily_rows
from app.market_data.contracts import Market
from app.market_data.valuation import ValuationPriceEvidence


def read_jp_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    del requested_at
    rows = _latest_distinct_jp_daily_rows(db=db, symbol=symbol, limit=1)
    row = rows[0] if rows else None
    price = (
        row.adjusted_close
        if row is not None and row.adjusted_close is not None
        else row.close_price
        if row is not None
        else None
    )
    return ValuationPriceEvidence(
        market=Market.JP,
        symbol=symbol,
        price=Decimal(str(price)) if price is not None else None,
        currency=row.currency if row is not None else "JPY",
        as_of=row.trade_date if row is not None else None,
        provider=row.provider if row is not None else None,
        source="jp_daily_price" if row is not None else None,
        source_kind="completed_daily_close_compatibility" if row is not None else "missing",
        facts_usable=price is not None,
        research_usable=price is not None,
        resolved_status="selected" if price is not None else "missing",
        limitations=("REGIONAL_DAILY_LINEAGE_NOT_YET_SHARED_CORE",) if row is not None else (),
    )


__all__ = ["read_jp_valuation_price"]
