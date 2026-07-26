from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from ._http import get


PROVIDER = "nstock"


def _resource(url: str) -> str:
    path = urlsplit(url).path
    if "minute-stock-data" in path:
        return "stock_intraday"
    if "branch-top15" in path:
        return "broker_branch"
    if "stock_info" in path:
        return "institutional_holding_ratio"
    return "market_data"


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    params = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {}
    query = parse_qs(urlsplit(url).query)
    target = str(params.get("stock_id") or (query.get("stock_id") or ["all"])[0])
    return get(
        url,
        provider=PROVIDER,
        resource=_resource(url),
        target=target,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
