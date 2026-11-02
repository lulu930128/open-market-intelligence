"""US market-owned cached valuation projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.market_data.contracts import Market
from app.market_data.valuation import ValuationPriceEvidence
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_market_state import USInstrumentIdentityUnavailableError
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


def read_us_valuation_price(
    db: Session,
    *,
    symbol: str,
    requested_at: datetime,
) -> ValuationPriceEvidence:
    with db.no_autoflush:
        try:
            read = USDailyOhlcvPlatform(db).read(symbol=symbol, bars=1, now=requested_at)
        except USInstrumentIdentityUnavailableError:
            return ValuationPriceEvidence(market=Market.US, symbol=symbol,
                currency="USD", source_kind="missing", resolved_status="missing",
                limitations=("US_INSTRUMENT_IDENTITY_UNAVAILABLE",))
    resolved = read.result.resolved
    row = resolved.bars[-1] if resolved.bars and read.temporal_postcondition_satisfied else None
    price = row.close_price if row is not None else None
    return ValuationPriceEvidence(
        market=Market.US,
        symbol=symbol,
        price=Decimal(str(price)) if price is not None else None,
        currency="USD",
        as_of=row.end_at.astimezone(US_MARKET_TIMEZONE).date() if row is not None else None,
        provider=row.lineage.provider if row is not None else None,
        source=row.lineage.source if row is not None else None,
        source_kind="canonical_completed_daily_close" if row is not None else "missing",
        facts_usable=price is not None,
        research_usable=price is not None,
        resolved_status=resolved.health.status.value,
        limitations=tuple(dict.fromkeys((*read.projection.get("limitations", ()),
            "PRICE_BASIS_RAW", "CORPORATE_ACTION_POSITION_ALIGNMENT_UNVERIFIED"))),
    )


__all__ = ["read_us_valuation_price"]
