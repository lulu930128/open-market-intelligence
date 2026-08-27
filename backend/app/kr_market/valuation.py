"""Korea market-owned cached valuation projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.kr_market.service import _latest_kr_daily_row
from app.market_data.contracts import Market
from app.market_data.valuation import ValuationPriceEvidence


def read_kr_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    del requested_at
    row = _latest_kr_daily_row(db, symbol=symbol)
    price = (
        row.adjusted_close
        if row is not None and row.adjusted_close is not None
        else row.close_price
        if row is not None
        else None
    )
    return ValuationPriceEvidence(
        market=Market.KR,
        symbol=symbol,
        price=Decimal(str(price)) if price is not None else None,
        currency=row.currency if row is not None else "KRW",
        as_of=row.trade_date if row is not None else None,
        provider=row.provider if row is not None else None,
        source="kr_daily_price" if row is not None else None,
        source_kind="completed_daily_close_compatibility" if row is not None else "missing",
        facts_usable=price is not None,
        research_usable=price is not None,
        resolved_status="selected" if price is not None else "missing",
        limitations=("REGIONAL_DAILY_LINEAGE_NOT_YET_SHARED_CORE",) if row is not None else (),
    )


__all__ = ["read_kr_valuation_price"]
