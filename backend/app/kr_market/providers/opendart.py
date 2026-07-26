from __future__ import annotations

from typing import Any

from app.kr_market.errors import KRMarketDataFetchError

from ._http import get as provider_get


OPENDART_SINGLE_ACCOUNT_ALL_PATH = "/fnlttSinglAcntAll.json"


def fetch_opendart_financial_statement_payload(
    *,
    base_url: str,
    api_key: str,
    corp_code: str,
    fiscal_year: int,
    report_code: str,
    fs_div: str = "CFS",
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    response = provider_get(
        f"{base_url.rstrip('/')}{OPENDART_SINGLE_ACCOUNT_ALL_PATH}",
        provider="opendart_fnltt_singl_acnt_all",
        resource="financials",
        target=corp_code,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(fiscal_year),
            "reprt_code": report_code,
            "fs_div": fs_div,
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("OpenDART financial statement returned a non-object JSON payload.")
    return payload, response.url
