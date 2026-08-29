"""US-owned instrument identity and completed-session state ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import USStockMaster
from app.market_data.contracts import (
    CanonicalModel,
    InstrumentKey,
    InstrumentType,
    Market,
)
from app.us_market.symbols import US_INDEX_SYMBOLS, normalize_us_symbol
from app.us_market.trading_calendar import (
    expected_us_daily_price_date,
    us_daily_price_finalization_time,
)


_INDEX_VENUES = {
    "^DJI": "DJI_INDEX",
    "^GSPC": "SP_INDEX",
    "^IXIC": "NASDAQ_INDEX",
    "^NDX": "NASDAQ_INDEX",
    "^SOX": "NASDAQ_INDEX",
    "^VIX": "CBOE_INDEX",
}


class USInstrumentIdentity(CanonicalModel):
    contract_version: str = "omi.market.us_instrument_identity.v1"
    instrument: InstrumentKey
    identity_source: Literal["market_index_registry", "us_stock_master"]
    volume_applicability: Literal["required", "not_applicable"]


class USCompletedDailyState(CanonicalModel):
    contract_version: str = "omi.market.us_completed_daily_state.v1"
    expected_trade_date: date
    release_at: datetime
    eligible: bool
    reason_code: str


def resolve_us_instrument_identity(db: Session, symbol: str) -> USInstrumentIdentity:
    normalized = normalize_us_symbol(symbol)
    if not normalized:
        raise ValueError("symbol must identify a US instrument")
    if normalized in US_INDEX_SYMBOLS:
        return USInstrumentIdentity(
            instrument=InstrumentKey(
                market=Market.US,
                symbol=normalized,
                instrument_type=InstrumentType.INDEX,
                venue=_INDEX_VENUES.get(normalized, "US_INDEX"),
            ),
            identity_source="market_index_registry",
            volume_applicability="not_applicable",
        )
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized)
        .first()
    )
    venue = str(getattr(stock, "exchange", None) or "").strip().upper()
    if stock is None or not venue:
        raise LookupError(f"US instrument identity is unavailable: {normalized}")
    return USInstrumentIdentity(
        instrument=InstrumentKey(
            market=Market.US,
            symbol=normalized,
            instrument_type=(
                InstrumentType.ETF if stock.is_etf is True else InstrumentType.STOCK
            ),
            venue=venue,
        ),
        identity_source="us_stock_master",
        volume_applicability="required",
    )


def expected_us_completed_daily_state(*, now: datetime) -> USCompletedDailyState:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    expected = expected_us_daily_price_date(now=now)
    return USCompletedDailyState(
        expected_trade_date=expected,
        release_at=us_daily_price_finalization_time(expected),
        eligible=True,
        reason_code="LATEST_RELEASED_COMPLETED_SESSION",
    )


__all__ = [
    "USCompletedDailyState",
    "USInstrumentIdentity",
    "expected_us_completed_daily_state",
    "resolve_us_instrument_identity",
]
