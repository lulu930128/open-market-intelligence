from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import StockMaster


TAIWAN_STOCK_MARKETS = ("TWSE", "TPEX")
TAIWAN_STOCK_INSTRUMENT_TYPE = "stock"


def normalize_taiwan_markets(markets: Iterable[str] | None) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            str(market or "").strip().upper()
            for market in (markets or TAIWAN_STOCK_MARKETS)
            if str(market or "").strip()
        )
    )
    unsupported = sorted(set(normalized) - set(TAIWAN_STOCK_MARKETS))
    if unsupported:
        raise ValueError(
            "Taiwan stock universe only supports markets: "
            + ", ".join(TAIWAN_STOCK_MARKETS)
        )
    return normalized


def list_taiwan_stock_universe(
    db: Session,
    *,
    markets: Iterable[str] | None = None,
    stock_ids: Iterable[str] | None = None,
    exclude_stock_ids: Iterable[str] | None = None,
) -> list[StockMaster]:
    """Return active TWSE/TPEx ordinary stocks in stable stock-id order."""

    normalized_markets = normalize_taiwan_markets(markets)
    included = tuple(
        dict.fromkeys(
            str(stock_id or "").strip()
            for stock_id in (stock_ids or ())
            if str(stock_id or "").strip()
        )
    )
    excluded = tuple(
        dict.fromkeys(
            str(stock_id or "").strip()
            for stock_id in (exclude_stock_ids or ())
            if str(stock_id or "").strip()
        )
    )

    query = (
        db.query(StockMaster)
        .filter(StockMaster.is_active.is_(True))
        .filter(func.upper(StockMaster.market).in_(normalized_markets))
        .filter(
            func.lower(StockMaster.instrument_type)
            == TAIWAN_STOCK_INSTRUMENT_TYPE
        )
    )
    if included:
        query = query.filter(StockMaster.stock_id.in_(included))
    if excluded:
        query = query.filter(StockMaster.stock_id.notin_(excluded))
    return query.order_by(StockMaster.stock_id.asc()).all()


def list_taiwan_stock_ids(
    db: Session,
    *,
    markets: Iterable[str] | None = None,
    stock_ids: Iterable[str] | None = None,
    exclude_stock_ids: Iterable[str] | None = None,
) -> list[str]:
    return [
        row.stock_id
        for row in list_taiwan_stock_universe(
            db,
            markets=markets,
            stock_ids=stock_ids,
            exclude_stock_ids=exclude_stock_ids,
        )
    ]
