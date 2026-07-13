from __future__ import annotations

from typing import Any

from app.observability.provider_http import ProviderRequestContext
from app.observability.provider_http import get as provider_get


def get(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str,
    timeout_seconds: int,
    **kwargs: Any,
):
    return provider_get(
        ProviderRequestContext(
            market="resource",
            provider=provider,
            resource=resource,
            target=target,
        ),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
