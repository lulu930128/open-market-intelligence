from __future__ import annotations

import re


JP_SYMBOL_TOKEN_PATTERN = re.compile(r"^[0-9A-Z][0-9A-Z.\-]{0,31}")


def normalize_jp_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    match = JP_SYMBOL_TOKEN_PATTERN.match(cleaned)
    normalized = match.group(0) if match else cleaned

    if "." in normalized:
        return normalized

    if re.fullmatch(r"[0-9A-Z]{4}", normalized):
        return f"{normalized}.T"

    return normalized


def local_code_from_symbol(symbol: str) -> str:
    normalized_symbol = normalize_jp_symbol(symbol)
    return normalized_symbol.split(".", maxsplit=1)[0]
