"""Japan market-owned cached valuation projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import settings
from app.jp_market.service import _latest_distinct_jp_daily_rows
from app.market_data.contracts import Market
from app.market_data.valuation import ValuationPriceEvidence


def read_jp_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    if settings.jp_canonical_daily_mode == "on":
        from app.jp_market.daily_projection import read_daily_rows
        rows = read_daily_rows(db, symbol=symbol, limit=1, requested_at=requested_at)
        row = rows[0] if rows else None
        return ValuationPriceEvidence(
            market=Market.JP, symbol=symbol,
            price=Decimal(str(row.close_price)) if row else None, currency="JPY",
            as_of=row.trade_date if row else None, provider=row.provider if row else None,
            source="jp.daily.ohlcv", source_kind="canonical_completed_daily_close" if row else "missing",
            facts_usable=bool(row and row.facts_usable), research_usable=bool(row and row.research_usable),
            resolved_status=row.resolved_status if row else "missing", limitations=row.limitations if row else (),
        )
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
