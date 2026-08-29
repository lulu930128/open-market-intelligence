"""Compatibility names backed by the canonical Gateway-first US daily platform."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.market_data.contracts import InstrumentType
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.sources import normalize_us_symbol


US_RESOLVED_DAILY_MAX_BARS = 5000


def _read(
    db: Session,
    *,
    symbol: str,
    bars: int,
    now: datetime,
    expected_trade_date: date | None,
) -> dict[str, Any]:
    if bars < 1 or bars > US_RESOLVED_DAILY_MAX_BARS:
        raise ValueError(
            f"bars must be between 1 and {US_RESOLVED_DAILY_MAX_BARS}"
        )
    return USDailyOhlcvPlatform(db).read(
        symbol=normalize_us_symbol(symbol),
        bars=bars,
        now=now,
        to_date=expected_trade_date,
    ).projection


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
    """Read canonical resolved bars; identity arguments are compatibility assertions."""

    if not str(venue or "").strip():
        raise ValueError("venue must be non-empty")
    result = _read(
        db,
        symbol=symbol,
        bars=bars,
        now=now,
        expected_trade_date=expected_trade_date,
    )
    projected_type = (
        result.get("bars", [{}])[-1].get("instrument_type")
        if result.get("bars")
        else None
    )
    if projected_type is not None and projected_type != instrument_type.value:
        raise ValueError("compatibility instrument_type disagrees with canonical identity")
    return result


def read_resolved_us_daily_bars_for_symbol(
    db: Session,
    *,
    symbol: str,
    bars: int,
    now: datetime | None = None,
    expected_trade_date: date | None = None,
) -> dict[str, Any]:
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return _read(
        db,
        symbol=symbol,
        bars=bars,
        now=resolved_now,
        expected_trade_date=expected_trade_date,
    )


def read_resolved_us_daily_bars_for_symbols(
    db: Session,
    *,
    symbols: list[str],
    bars: int,
    now: datetime | None = None,
    expected_trade_date: date | None = None,
) -> dict[str, dict[str, Any]]:
    normalized = tuple(
        dict.fromkeys(
            value
            for symbol in symbols
            if (value := normalize_us_symbol(symbol))
        )
    )
    if len(normalized) > 500:
        raise ValueError("symbols must contain at most 500 canonical symbols")
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return {
        symbol: _read(
            db,
            symbol=symbol,
            bars=bars,
            now=resolved_now,
            expected_trade_date=expected_trade_date,
        )
        for symbol in normalized
    }


__all__ = [
    "US_RESOLVED_DAILY_MAX_BARS",
    "read_resolved_us_daily_bars",
    "read_resolved_us_daily_bars_for_symbol",
    "read_resolved_us_daily_bars_for_symbols",
]
