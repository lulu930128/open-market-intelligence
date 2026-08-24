"""Stable cache-only read seams for resolved US market evidence."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import USStockMaster
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.market_data_canary import (
    US_CANARY_MAX_BARS,
    build_cached_daily_resolved_canary,
)
from app.us_market.price_store import (
    list_us_ohlc_source_rows,
    list_us_ohlc_source_rows_for_symbols,
)
from app.us_market.sources import normalize_us_symbol
from app.us_market.symbols import us_instrument_type
from app.us_market.trading_calendar import (
    expected_us_daily_price_date,
    is_us_daily_price_finalized,
)

US_RESOLVED_DAILY_MAX_BARS = US_CANARY_MAX_BARS


def _latest_rows_per_provider(rows: list[Any], *, bars: int) -> list[Any]:
    provider_rows: dict[str, list[Any]] = {}
    for row in rows:
        provider = str(getattr(row, "provider", "") or "").strip().lower()
        if not provider:
            continue
        provider_rows.setdefault(provider, []).append(row)
    selected: list[Any] = []
    for items in provider_rows.values():
        selected.extend(
            sorted(items, key=lambda row: row.trade_date)[-bars:]
        )
    return sorted(selected, key=lambda row: row.trade_date)


def read_resolved_us_daily_bars(
    db: Session,
    *,
    symbol: str,
    instrument_type: InstrumentType,
    venue: str,
    expected_trade_date: date,
    now: datetime,
    bars: int,
) -> dict[str, Any]:
    """Resolve finalized cached daily rows without provider IO or persistence."""

    if bars < 1 or bars > US_CANARY_MAX_BARS:
        raise ValueError(f"bars must be between 1 and {US_CANARY_MAX_BARS}")
    normalized_venue = str(venue).strip().upper()
    if not normalized_venue:
        return {}
    from_date = expected_trade_date - timedelta(days=max(14, bars * 3))
    rows = list_us_ohlc_source_rows(
        db=db,
        symbol=symbol,
        from_date=from_date,
        to_date=expected_trade_date,
    )
    finalized_rows = _latest_rows_per_provider(
        [
            row
            for row in rows
            if is_us_daily_price_finalized(
                trade_date=row.trade_date,
                fetched_at=row.fetched_at,
            )
        ],
        bars=bars,
    )
    return build_cached_daily_resolved_canary(
        instrument=InstrumentKey(
            market=Market.US,
            symbol=symbol,
            instrument_type=instrument_type,
            venue=normalized_venue,
        ),
        rows=finalized_rows,
        expected_trade_date=expected_trade_date,
        now=now,
        max_bars=bars,
    )


def read_resolved_us_daily_bars_for_symbol(
    db: Session,
    *,
    symbol: str,
    bars: int,
    now: datetime | None = None,
    expected_trade_date: date | None = None,
) -> dict[str, Any]:
    """Resolve cached daily bars after loading canonical instrument identity."""

    normalized_symbol = normalize_us_symbol(symbol)
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )
    venue = str(getattr(stock, "exchange", None) or "").strip().upper()
    if not venue:
        return {}
    if us_instrument_type(normalized_symbol) == "index":
        instrument_type = InstrumentType.INDEX
    elif stock is not None and stock.is_etf is True:
        instrument_type = InstrumentType.ETF
    else:
        instrument_type = InstrumentType.STOCK
    return read_resolved_us_daily_bars(
        db=db,
        symbol=normalized_symbol,
        instrument_type=instrument_type,
        venue=venue,
        expected_trade_date=(
            expected_trade_date
            or expected_us_daily_price_date(now=resolved_now)
        ),
        now=resolved_now,
        bars=bars,
    )


def read_resolved_us_daily_bars_for_symbols(
    db: Session,
    *,
    symbols: list[str],
    bars: int,
    now: datetime | None = None,
    expected_trade_date: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve a bounded symbol set with one instrument query and one row query."""

    if bars < 1 or bars > US_CANARY_MAX_BARS:
        raise ValueError(f"bars must be between 1 and {US_CANARY_MAX_BARS}")
    normalized_symbols = list(
        dict.fromkeys(
            normalized
            for symbol in symbols
            if (normalized := normalize_us_symbol(symbol))
        )
    )
    if len(normalized_symbols) > 500:
        raise ValueError("symbols must contain at most 500 canonical symbols")
    if not normalized_symbols:
        return {}
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    resolved_expected_date = (
        expected_trade_date or expected_us_daily_price_date(now=resolved_now)
    )
    stocks = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(normalized_symbols))
        .all()
    )
    stocks_by_symbol = {stock.symbol: stock for stock in stocks}
    from_date = resolved_expected_date - timedelta(days=max(14, bars * 3))
    rows_by_symbol = list_us_ohlc_source_rows_for_symbols(
        db=db,
        symbols=normalized_symbols,
        from_date=from_date,
        to_date=resolved_expected_date,
    )
    results: dict[str, dict[str, Any]] = {}
    for symbol in normalized_symbols:
        stock = stocks_by_symbol.get(symbol)
        venue = str(getattr(stock, "exchange", None) or "").strip().upper()
        if not venue:
            results[symbol] = {}
            continue
        if us_instrument_type(symbol) == "index":
            instrument_type = InstrumentType.INDEX
        elif stock is not None and stock.is_etf is True:
            instrument_type = InstrumentType.ETF
        else:
            instrument_type = InstrumentType.STOCK
        finalized_rows = _latest_rows_per_provider(
            [
                row
                for row in rows_by_symbol.get(symbol, [])
                if is_us_daily_price_finalized(
                    trade_date=row.trade_date,
                    fetched_at=row.fetched_at,
                )
            ],
            bars=bars,
        )
        results[symbol] = build_cached_daily_resolved_canary(
            instrument=InstrumentKey(
                market=Market.US,
                symbol=symbol,
                instrument_type=instrument_type,
                venue=venue,
            ),
            rows=finalized_rows,
            expected_trade_date=resolved_expected_date,
            now=resolved_now,
            max_bars=bars,
        )
    return results


__all__ = [
    "US_RESOLVED_DAILY_MAX_BARS",
    "read_resolved_us_daily_bars",
    "read_resolved_us_daily_bars_for_symbol",
    "read_resolved_us_daily_bars_for_symbols",
]
