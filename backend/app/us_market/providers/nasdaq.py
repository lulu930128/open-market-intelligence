from __future__ import annotations

from ._http import get as provider_get


PROVIDER_NAME = "nasdaq_trader"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def fetch_symbol_directory_payloads(
    *,
    timeout_seconds: int,
) -> tuple[str, str]:
    nasdaq_response = provider_get(
        NASDAQ_LISTED_URL,
        provider=PROVIDER_NAME,
        resource="symbol_master",
        timeout_seconds=timeout_seconds,
    )
    other_response = provider_get(
        NASDAQ_OTHER_LISTED_URL,
        provider=PROVIDER_NAME,
        resource="symbol_master",
        timeout_seconds=timeout_seconds,
    )
    return nasdaq_response.text, other_response.text
