from __future__ import annotations

import re


US_SYMBOL_TOKEN_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.$-]{0,31}")


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
    return match.group(0) if match else cleaned
