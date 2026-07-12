from __future__ import annotations

from ._http import get as provider_get


JPX_LISTED_ISSUES_URL = (
    "https://www.jpx.co.jp/english/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_e.xls"
)


def fetch_jpx_listed_issues_workbook(
    *,
    timeout_seconds: int,
) -> tuple[bytes, str]:
    response = provider_get(
        JPX_LISTED_ISSUES_URL,
        provider="jpx_listed_issues",
        resource="symbol_master",
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/vnd.ms-excel,application/octet-stream,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    return response.content, response.url
