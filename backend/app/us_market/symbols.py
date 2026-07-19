from __future__ import annotations

import re


US_SYMBOL_TOKEN_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.$-]{0,31}")
US_SYMBOL_ALIASES = {
    "DJI": "^DJI",
    "IXIC": "^IXIC",
    "NASDAQ": "^IXIC",
    "NDX": "^NDX",
    "SOX": "^SOX",
    "SPX": "^GSPC",
    "VIX": "^VIX",
}
US_INDEX_SYMBOLS = frozenset(US_SYMBOL_ALIASES.values())


def normalize_us_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    match = US_SYMBOL_TOKEN_PATTERN.match(cleaned)
    normalized = match.group(0) if match else cleaned
    return US_SYMBOL_ALIASES.get(normalized, normalized)


def us_symbol_storage_candidates(value: str | None) -> tuple[str, ...]:
    """Return the canonical symbol followed by legacy aliases stored before normalization."""
    normalized = normalize_us_symbol(value)
    if not normalized:
        return ()

    aliases = [
        alias
        for alias, canonical in US_SYMBOL_ALIASES.items()
        if canonical == normalized and alias != normalized
    ]
    return tuple(dict.fromkeys((normalized, *aliases)))


def us_instrument_type(value: str | None) -> str:
    return "index" if normalize_us_symbol(value) in US_INDEX_SYMBOLS else "stock"
