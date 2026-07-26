from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.jp_market.errors import JPMarketDataFetchError
from app.observability.provider_http import ProviderHttpError

from ._http import get as provider_get
from ._http import post as provider_post


JQUANTS_AUTH_USER_PATH = "/token/auth_user"
JQUANTS_AUTH_REFRESH_PATH = "/token/auth_refresh"
JQUANTS_STATEMENTS_PATH = "/fins/statements"
JQUANTS_SUMMARY_PATH = "/fins/summary"
JQUANTS_MARGIN_INTEREST_PATH = "/markets/margin-interest"
JQUANTS_INVESTOR_TYPES_PATH = "/equities/investor-types"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in {"N/A", "NULL", "-"}:
        return None

    return cleaned


def _base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _url(base_url: str, path: str) -> str:
    return f"{_base_url(base_url)}{path}"


def _request(
    operation: str,
    method: str,
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    try:
        request = provider_post if method == "POST" else provider_get
        return request(
            url,
            provider=provider,
            resource=resource,
            target=target,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )
    except ProviderHttpError as exc:
        if exc.http_status_code is not None:
            raise JPMarketDataFetchError(
                f"J-Quants {operation} failed: HTTP {exc.http_status_code}."
            ) from exc
        raise


def fetch_jquants_refresh_token(
    *,
    base_url: str,
    mail_address: str,
    password: str,
    timeout_seconds: int = 30,
) -> str:
    response = _request(
        "auth_user",
        "POST",
        _url(base_url, JQUANTS_AUTH_USER_PATH),
        provider="jquants",
        resource="auth",
        json={"mailaddress": mail_address, "password": password},
        timeout_seconds=timeout_seconds,
    )

    payload = response.json()
    refresh_token = _clean_text(payload.get("refreshToken"))
    if refresh_token is None:
        raise JPMarketDataFetchError("J-Quants auth_user did not return refreshToken.")

    return refresh_token


def fetch_jquants_id_token(
    *,
    base_url: str,
    refresh_token: str,
    timeout_seconds: int = 30,
) -> str:
    response = _request(
        "auth_refresh",
        "POST",
        _url(base_url, JQUANTS_AUTH_REFRESH_PATH),
        provider="jquants",
        resource="auth",
        params={"refreshtoken": refresh_token},
        timeout_seconds=timeout_seconds,
    )

    payload = response.json()
    id_token = _clean_text(payload.get("idToken"))
    if id_token is None:
        raise JPMarketDataFetchError("J-Quants auth_refresh did not return idToken.")

    return id_token


def fetch_jquants_statements_payload(
    *,
    base_url: str,
    id_token: str,
    local_code: str,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    url = _url(base_url, JQUANTS_STATEMENTS_PATH)
    response = _request(
        "statements",
        "GET",
        url,
        provider="jquants_statements",
        resource="fundamentals",
        target=local_code,
        params={"code": local_code},
        headers={"Authorization": f"Bearer {id_token}"},
        timeout_seconds=timeout_seconds,
    )

    return response.json(), response.url

def fetch_jquants_summary_payload(
    *,
    base_url: str,
    api_key: str,
    local_code: str,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    url = _url(base_url, JQUANTS_SUMMARY_PATH)
    response = _request(
        "summary",
        "GET",
        url,
        provider="jquants_summary",
        resource="fundamentals",
        target=local_code,
        params={"code": local_code},
        headers={"x-api-key": api_key},
        timeout_seconds=timeout_seconds,
    )

    return response.json(), response.url


def fetch_jquants_margin_interest_payload(
    *,
    base_url: str,
    api_key: str,
    local_code: str,
    from_date: date | None = None,
    to_date: date | None = None,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    params: dict[str, str] = {"code": local_code}
    if from_date is not None:
        params["from"] = from_date.isoformat()
    if to_date is not None:
        params["to"] = to_date.isoformat()

    url = _url(base_url, JQUANTS_MARGIN_INTEREST_PATH)
    response = _request(
        "margin-interest",
        "GET",
        url,
        provider="jquants_margin_interest",
        resource="margin_interest",
        target=local_code,
        params=params,
        headers={"x-api-key": api_key},
        timeout_seconds=timeout_seconds,
    )

    return response.json(), response.url


def fetch_jquants_investor_types_payload(
    *,
    base_url: str,
    api_key: str,
    section: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    params: dict[str, str] = {}
    if section:
        params["section"] = section
    if from_date is not None:
        params["from"] = from_date.isoformat()
    if to_date is not None:
        params["to"] = to_date.isoformat()

    url = _url(base_url, JQUANTS_INVESTOR_TYPES_PATH)
    response = _request(
        "investor-types",
        "GET",
        url,
        provider="jquants_investor_types",
        resource="investor_types",
        target=section or "all",
        params=params,
        headers={"x-api-key": api_key},
        timeout_seconds=timeout_seconds,
    )

    return response.json(), response.url
