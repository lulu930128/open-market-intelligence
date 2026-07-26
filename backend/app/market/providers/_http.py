from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from app.observability.provider_http import ProviderRequestContext
from app.observability.provider_http import get as provider_get
from app.observability.provider_http import post as provider_post


DEFAULT_HEADERS = {
    "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
    "Accept": "application/json,text/plain,*/*",
}
ResponseGetter = Callable[..., requests.Response]


def get(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int = 20,
    **kwargs: Any,
) -> requests.Response:
    return provider_get(
        ProviderRequestContext(
            market="tw",
            provider=provider,
            resource=resource,
            target=target,
        ),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def post(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int = 20,
    **kwargs: Any,
) -> requests.Response:
    return provider_post(
        ProviderRequestContext(
            market="tw",
            provider=provider,
            resource=resource,
            target=target,
        ),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def json_from_response(response: requests.Response) -> Any:
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.json()


def get_json(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int = 20,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    response = get(
        url,
        provider=provider,
        resource=resource,
        target=target,
        timeout_seconds=timeout_seconds,
        headers=headers or DEFAULT_HEADERS,
        **kwargs,
    )
    return json_from_response(response)
