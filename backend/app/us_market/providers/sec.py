from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from app.us_market.errors import USMarketDataFetchError

from ._http import get as provider_get
from .sec_policy import DEFAULT_SEC_REQUEST_POLICY


PROVIDER_NAME = "sec_edgar"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_DOCUMENT_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{issuer_cik}/{accession_compact}/{document_name}"
)
SEC_FORM13F_DATASETS_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
)


def _json_object(
    url: str,
    *,
    resource: str,
    target: str = "all",
    sec_user_agent: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = DEFAULT_SEC_REQUEST_POLICY.execute(
        lambda: provider_get(
            url,
            provider=PROVIDER_NAME,
            resource=resource,
            target=target,
            headers={"User-Agent": sec_user_agent},
            timeout_seconds=timeout_seconds,
        )
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


def fetch_sec_submissions_payload(
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

    url = SEC_SUBMISSIONS_URL_TEMPLATE.format(cik=padded_cik)
    payload = _json_object(
        url,
        resource="sec_submissions",
        target=padded_cik,
        sec_user_agent=sec_user_agent,
        timeout_seconds=timeout_seconds,
    )
    return payload, url


def fetch_sec_ownership_xml(
    *,
    issuer_cik: str,
    accession_number: str,
    primary_document: str,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[bytes, str]:
    try:
        cik_value = int(str(issuer_cik).strip().replace(",", ""))
    except (TypeError, ValueError):
        cik_value = 0
    accession_compact = str(accession_number or "").strip().replace("-", "")
    document_name = PurePosixPath(str(primary_document or "").strip()).name
    if cik_value <= 0 or not accession_compact.isdigit() or not document_name:
        raise USMarketDataFetchError("Invalid SEC ownership document identity.")

    url = SEC_ARCHIVES_DOCUMENT_URL_TEMPLATE.format(
        issuer_cik=cik_value,
        accession_compact=accession_compact,
        document_name=document_name,
    )
    response = DEFAULT_SEC_REQUEST_POLICY.execute(
        lambda: provider_get(
            url,
            provider=PROVIDER_NAME,
            resource="sec_insider_transactions",
            target=f"{cik_value}:{accession_number}",
            headers={"User-Agent": sec_user_agent},
            timeout_seconds=timeout_seconds,
        )
    )
    payload = bytes(response.content)
    if not payload.strip():
        raise USMarketDataFetchError(f"SEC ownership document was empty: {url}")
    return payload, url


def open_sec_dataset_stream(
    *,
    url: str,
    resource: str,
    target: str,
    sec_user_agent: str,
    timeout_seconds: int,
):
    parsed = urlsplit(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname not in {"www.sec.gov", "sec.gov"}:
        raise USMarketDataFetchError("SEC dataset URL must use https://www.sec.gov.")
    return DEFAULT_SEC_REQUEST_POLICY.execute(
        lambda: provider_get(
            url,
            provider=PROVIDER_NAME,
            resource=resource,
            target=target,
            headers={"User-Agent": sec_user_agent},
            timeout_seconds=timeout_seconds,
            stream=True,
        )
    )


def fetch_sec_13f_dataset_manifest_html(
    *,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[str, str]:
    response = DEFAULT_SEC_REQUEST_POLICY.execute(
        lambda: provider_get(
            SEC_FORM13F_DATASETS_PAGE_URL,
            provider=PROVIDER_NAME,
            resource="sec_13f_manifest",
            target="all",
            headers={"User-Agent": sec_user_agent},
            timeout_seconds=timeout_seconds,
        )
    )
    payload = bytes(response.content)
    if not payload.strip():
        raise USMarketDataFetchError("SEC Form 13F data-set manifest page was empty.")
    if len(payload) > 2 * 1024 * 1024:
        raise USMarketDataFetchError("SEC Form 13F data-set manifest page exceeded 2 MiB.")
    return payload.decode("utf-8", errors="replace"), SEC_FORM13F_DATASETS_PAGE_URL
