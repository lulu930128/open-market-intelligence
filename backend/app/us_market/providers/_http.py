from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from app.observability.provider_http import ProviderRequestContext
from app.observability.provider_http import get as provider_get
from app.observability.provider_http import post as provider_post


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
        ProviderRequestContext(
            market="us",
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
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    return provider_post(
        ProviderRequestContext(
            market="us",
            provider=provider,
            resource=resource,
            target=target,
        ),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def redact_url_params(
    url: str,
    names: tuple[str, ...] = ("apikey", "api_key"),
) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url

    redacted_names = {name.lower() for name in names}
    changed = False
    query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in redacted_names:
            query_pairs.append((key, "REDACTED"))
            changed = True
            continue
        query_pairs.append((key, value))

    if not changed:
        return url

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_pairs),
            parts.fragment,
        )
    )
