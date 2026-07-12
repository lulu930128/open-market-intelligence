from __future__ import annotations

from typing import Any

import requests

from app.observability.provider_http import (
    ProviderRequestContext,
    get as provider_get,
    post as provider_post,
)


def _context(
    *,
    provider: str,
    resource: str,
    target: str = "all",
) -> ProviderRequestContext:
    return ProviderRequestContext(
        market="kr",
        provider=provider,
        resource=resource,
        target=target,
    )


def get(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    return provider_get(
        _context(provider=provider, resource=resource, target=target),
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
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    return provider_post(
        _context(provider=provider, resource=resource, target=target),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
