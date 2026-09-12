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
JQUANTS_DAILY_BARS_PATH = "/equities/bars/daily"


def fetch_jquants_daily_payload(
    *, base_url: str, api_key: str, local_code: str,
    from_date: date, to_date: date, timeout_seconds: int = 30,
    pagination_key: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Fetch exactly one bounded V2 page; never hide incomplete pagination."""
    if not api_key or not api_key.strip():
        raise JPMarketDataFetchError("J-Quants API key is not configured.")
    if not local_code or len(local_code) not in (4, 5) or not local_code.isalnum():
        raise ValueError("J-Quants daily requires a four- or five-character issue code")
    if from_date > to_date or (to_date - from_date).days >= 3650:
        raise ValueError("J-Quants daily range must be ordered and bounded to 3650 days")
    if not 1 <= timeout_seconds <= 30:
        raise ValueError("J-Quants daily timeout must be between 1 and 30 seconds")
    params = {"code": local_code, "from": from_date.isoformat(), "to": to_date.isoformat()}
    if pagination_key:
        params["pagination_key"] = pagination_key
    response = _request(
        "daily-bars", "GET", _url(base_url, JQUANTS_DAILY_BARS_PATH),
        provider="jquants", resource="daily.ohlcv", target=local_code,
        params=params, headers={"x-api-key": api_key}, timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise JPMarketDataFetchError("J-Quants daily returned an invalid data envelope.")
    if len(payload["data"]) > 5000:
        raise JPMarketDataFetchError("J-Quants daily page exceeded the 5000-row bound.")
    return payload, response.url


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
