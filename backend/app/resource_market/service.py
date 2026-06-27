from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ResourceOhlcvBar, ResourceQuoteSnapshot
from app.resource_market.contract import (
    list_resource_instruments,
    normalize_resource_symbol,
    resource_provider_contract,
)


def get_resource_provider_contract() -> dict[str, Any]:
    return resource_provider_contract()


def list_supported_resource_instruments(
    *,
    root_folder: str | None = None,
    group: str | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    return [
        instrument.to_dict()
        for instrument in list_resource_instruments(
            root_folder=root_folder,
            group=group,
            symbol=symbol,
        )
    ]


def _split_symbols(symbols: str | None) -> list[str] | None:
    if not symbols:
        return None
    normalized: list[str] = []
    for symbol in symbols.split(","):
        item = normalize_resource_symbol(symbol)
        if item and item not in normalized:
            normalized.append(item)
    return normalized or None


def list_latest_resource_quotes(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    limit: int = 100,
) -> list[ResourceQuoteSnapshot]:
    query = db.query(ResourceQuoteSnapshot)
    if provider:
        query = query.filter(ResourceQuoteSnapshot.provider == provider.strip().lower())
    if symbol_values := _split_symbols(symbols):
        query = query.filter(ResourceQuoteSnapshot.symbol.in_(symbol_values))
    if group:
        query = query.filter(ResourceQuoteSnapshot.group == group.strip().lower())
    return (
        query.order_by(ResourceQuoteSnapshot.fetched_at.desc(), ResourceQuoteSnapshot.symbol.asc())
        .limit(limit)
        .all()
    )


def list_resource_ohlcv_bars(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    interval: str | None = None,
    limit: int = 500,
) -> list[ResourceOhlcvBar]:
    query = db.query(ResourceOhlcvBar)
    if provider:
        query = query.filter(ResourceOhlcvBar.provider == provider.strip().lower())
    if symbol_values := _split_symbols(symbols):
        query = query.filter(ResourceOhlcvBar.symbol.in_(symbol_values))
    if group:
        query = query.filter(ResourceOhlcvBar.group == group.strip().lower())
    if interval:
        query = query.filter(ResourceOhlcvBar.interval == interval.strip())
    return (
        query.order_by(ResourceOhlcvBar.bar_time.desc(), ResourceOhlcvBar.symbol.asc())
        .limit(limit)
        .all()
    )
