from __future__ import annotations

import re
from typing import Any


KR_SYMBOL_TOKEN_PATTERN = re.compile(r"^[0-9A-Z][0-9A-Z.\-]{0,31}")


def _clean_symbol_code(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in {"N/A", "NULL", "NONE", "-", "--"}:
        return None

    if re.fullmatch(r"\d+\.0", cleaned):
        cleaned = cleaned[:-2]

    return cleaned.strip().upper()


def normalize_kr_local_code(value: Any) -> str:
    cleaned = _clean_symbol_code(value) or ""
    if re.fullmatch(r"\d{1,6}", cleaned):
        return cleaned.zfill(6)
    return cleaned


def normalize_kr_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    if " " in cleaned:
        cleaned = cleaned.split(" ", maxsplit=1)[0].strip()

    match = KR_SYMBOL_TOKEN_PATTERN.match(cleaned)
    normalized = match.group(0) if match else cleaned

    if "." in normalized:
        local, suffix = normalized.split(".", maxsplit=1)
        local = normalize_kr_local_code(local)
        return f"{local}.{suffix}"

    local_code = normalize_kr_local_code(normalized)
    if local_code:
        return f"{local_code}.KS"

    return normalized


def local_code_from_symbol(symbol: str) -> str:
    normalized_symbol = normalize_kr_symbol(symbol)
    return normalized_symbol.split(".", maxsplit=1)[0]
