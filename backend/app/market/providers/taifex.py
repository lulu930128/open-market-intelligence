from __future__ import annotations

from typing import Any

from ._http import get


PROVIDER = "taifex"


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    params = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {}
    target = str(params.get("queryDate") or params.get("dateaddcnt") or "TXF")
    return get(
        url,
        provider=PROVIDER,
        resource="futures_institutional_contracts",
        target=target,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
