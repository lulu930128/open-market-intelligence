"""Korea market-owned cached valuation projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from app.config import settings

from app.kr_market.service import _latest_kr_daily_row
from app.market_data.contracts import Market
from app.market_data.valuation import ValuationPriceEvidence


def read_kr_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    if settings.kr_canonical_daily_enabled:
        from app.kr_market.daily_ohlcv_platform import KRDailyOhlcvPlatform
        result = KRDailyOhlcvPlatform(db).read(symbol=symbol, bars=1, now=requested_at)
        selected = result.result.resolved.bars
        bar = selected[-1] if selected else None
        return ValuationPriceEvidence(market=Market.KR, symbol=result.identity.instrument.symbol,
            price=bar.close_price if bar else None, currency=result.identity.currency,
            as_of=bar.end_at if bar else None, provider=bar.lineage.provider if bar else None,
            source=bar.lineage.source if bar else None, source_kind="canonical_daily_close" if bar else "missing",
            facts_usable=result.projection["facts_usable"], research_usable=result.projection["decision_usable"],
            resolved_status=result.projection["freshness_status"], limitations=tuple(result.projection["limitations"]))
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
