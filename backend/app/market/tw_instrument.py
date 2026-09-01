"""Canonical Taiwan instrument identity resolution.

This module is the only Taiwan Bar/Technical owner allowed to translate a
product-facing instrument id into the shared :class:`InstrumentKey` contract.
It performs no provider selection, acquisition, or persistence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.stocks.instruments import normalize_taiwan_instrument_type


_INDEX_IDENTITIES: dict[str, tuple[str, str]] = {
    "TAIEX": ("TAIEX", "TWSE"),
    "TPEX": ("TPEX", "TPEX"),
}

_MASTER_INSTRUMENT_TYPES = {
    "stock": InstrumentType.STOCK,
    "etf": InstrumentType.ETF,
}


class TaiwanInstrumentResolutionError(ValueError):
    """Raised when a Taiwan id cannot be mapped to canonical identity."""


def normalize_taiwan_instrument_id(instrument_id: str) -> str:
    normalized = str(instrument_id or "").strip().upper()
    if not normalized:
        raise TaiwanInstrumentResolutionError("instrument_id must not be empty")
    return normalized


def resolve_taiwan_instrument(
    db: Session,
    instrument_id: str,
) -> InstrumentKey:
    """Resolve STOCK, ETF, TAIEX, or TPEX to one shared InstrumentKey.

    Index identity is market-owned. Stock and ETF identity is read only from
    canonical ``StockMaster`` metadata; unknown, warrant, derivative, and
    malformed master classifications fail closed.
    """

    normalized = normalize_taiwan_instrument_id(instrument_id)
    index_identity = _INDEX_IDENTITIES.get(normalized)
    if index_identity is not None:
        symbol, venue = index_identity
        return InstrumentKey(
            market=Market.TW,
            symbol=symbol,
            instrument_type=InstrumentType.INDEX,
            venue=venue,
        )

    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized)
        .one_or_none()
    )
    if stock is None:
        raise TaiwanInstrumentResolutionError(
            f"Taiwan instrument is not registered: {normalized}"
        )

    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise TaiwanInstrumentResolutionError(
            f"Taiwan instrument requires TWSE/TPEX venue: {normalized}"
        )

    master_type = normalize_taiwan_instrument_type(
        stock.instrument_type,
        stock_id=stock.stock_id,
    )
    instrument_type = _MASTER_INSTRUMENT_TYPES.get(master_type)
    if instrument_type is None:
        raise TaiwanInstrumentResolutionError(
            "Taiwan Bar/Technical supports only canonical STOCK/ETF master "
            f"metadata: {normalized} type={master_type}"
        )

    return InstrumentKey(
        market=Market.TW,
        symbol=normalized,
        instrument_type=instrument_type,
        venue=venue,
    )


__all__ = [
    "TaiwanInstrumentResolutionError",
    "normalize_taiwan_instrument_id",
    "resolve_taiwan_instrument",
]
