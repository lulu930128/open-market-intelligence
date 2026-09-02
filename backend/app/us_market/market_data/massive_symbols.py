"""Canonical OMI US index symbols mapped to Massive's provider namespace."""

from __future__ import annotations

from app.us_market.symbols import normalize_us_symbol


MASSIVE_INDEX_SYMBOLS: dict[str, str] = {
    "^GSPC": "I:SPX",
    "^DJI": "I:DJI",
    "^IXIC": "I:COMP",
    "^NDX": "I:NDX",
    "^SOX": "I:SOX",
    "^VIX": "I:VIX",
}


def massive_index_provider_symbol(symbol: str) -> str:
    canonical = normalize_us_symbol(symbol)
    try:
        return MASSIVE_INDEX_SYMBOLS[canonical]
    except KeyError as exc:
        raise ValueError(f"unsupported Massive US index symbol: {canonical or symbol}") from exc


def massive_index_canonical_symbol(provider_symbol: str) -> str:
    normalized = str(provider_symbol).strip().upper()
    for canonical, candidate in MASSIVE_INDEX_SYMBOLS.items():
        if candidate == normalized:
            return canonical
    raise ValueError(f"unregistered Massive index ticker: {normalized or provider_symbol}")


__all__ = [
    "MASSIVE_INDEX_SYMBOLS",
    "massive_index_canonical_symbol",
    "massive_index_provider_symbol",
]
