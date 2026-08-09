from __future__ import annotations


TAIWAN_INSTRUMENT_STOCK = "stock"
TAIWAN_INSTRUMENT_ETF = "etf"
TAIWAN_INSTRUMENT_INDEX = "index"
TAIWAN_INSTRUMENT_WARRANT = "warrant"
TAIWAN_INSTRUMENT_UNKNOWN = "unknown"


_ALIASES = {
    "common_stock": TAIWAN_INSTRUMENT_STOCK,
    "equity": TAIWAN_INSTRUMENT_STOCK,
    "exchange_traded_fund": TAIWAN_INSTRUMENT_ETF,
    "fund": TAIWAN_INSTRUMENT_ETF,
}
_KNOWN_TYPES = {
    TAIWAN_INSTRUMENT_STOCK,
    TAIWAN_INSTRUMENT_ETF,
    TAIWAN_INSTRUMENT_INDEX,
    TAIWAN_INSTRUMENT_WARRANT,
    "futures",
    "option",
    TAIWAN_INSTRUMENT_UNKNOWN,
}


def normalize_taiwan_instrument_type(
    value: object,
    *,
    stock_id: str | None = None,
) -> str:
    """Return the canonical lowercase Taiwan instrument identifier.

    The stock-id fallback only repairs missing legacy values. An explicit type is
    never reclassified from the symbol prefix alone.
    """

    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    normalized = _ALIASES.get(normalized, normalized)
    if normalized in _KNOWN_TYPES:
        return normalized
    if not normalized and str(stock_id or "").strip().startswith("00"):
        return TAIWAN_INSTRUMENT_ETF
    return normalized or TAIWAN_INSTRUMENT_UNKNOWN


def is_taiwan_etf(value: object, *, stock_id: str | None = None) -> bool:
    return (
        normalize_taiwan_instrument_type(value, stock_id=stock_id)
        == TAIWAN_INSTRUMENT_ETF
    )
