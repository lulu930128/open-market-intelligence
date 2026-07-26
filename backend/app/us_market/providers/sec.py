from __future__ import annotations

from typing import Any

from app.us_market.errors import USMarketDataFetchError

from ._http import get as provider_get


PROVIDER_NAME = "sec_edgar"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _json_object(
    url: str,
    *,
    resource: str,
    target: str = "all",
    sec_user_agent: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = provider_get(
        url,
        provider=PROVIDER_NAME,
        resource=resource,
        target=target,
        headers={"User-Agent": sec_user_agent},
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise USMarketDataFetchError(f"Expected JSON object from {url}.")
    return payload


def fetch_sec_company_tickers_exchange_payload(
    *,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    payload = _json_object(
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
        resource="symbol_master",
        sec_user_agent=sec_user_agent,
        timeout_seconds=timeout_seconds,
    )
    return payload, SEC_COMPANY_TICKERS_EXCHANGE_URL


def fetch_sec_companyfacts_payload(
    *,
    cik: str,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    try:
        cik_value = int(str(cik).strip().replace(",", ""))
    except (TypeError, ValueError):
        cik_value = 0

    padded_cik = f"{cik_value:010d}"
    if padded_cik == "0000000000":
        raise USMarketDataFetchError(f"Invalid CIK value: {cik}")

    url = SEC_COMPANY_FACTS_URL_TEMPLATE.format(cik=padded_cik)
    payload = _json_object(
        url,
        resource="sec_facts",
        target=padded_cik,
        sec_user_agent=sec_user_agent,
        timeout_seconds=timeout_seconds,
    )
    return payload, url
