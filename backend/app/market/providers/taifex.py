from __future__ import annotations

from typing import Any

from ._http import get, json_from_response, post


PROVIDER = "taifex"
OPENAPI_BASE_URL = "https://openapi.taifex.com.tw/v1"
OPENAPI_DATASETS = {
    "DailyMarketReportFut": "futures_daily_report",
    "DailyMarketReportOpt": "options_daily_report",
    "DailyOptionsDelta": "options_daily_delta",
    "OpenInterestOfLargeTradersFutures": "futures_large_traders",
    "OpenInterestOfLargeTradersOptions": "options_large_traders",
}


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


def post_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    data = kwargs.get("data") if isinstance(kwargs.get("data"), dict) else {}
    target = str(data.get("queryStartDate") or data.get("queryEndDate") or "TXO")
    return post(
        url,
        provider=PROVIDER,
        resource="options_put_call_ratio",
        target=target,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def fetch_openapi_rows(
    dataset: str,
    *,
    target: str,
    timeout_seconds: int = 20,
) -> list[dict[str, Any]]:
    resource = OPENAPI_DATASETS.get(dataset)
    if resource is None:
        raise ValueError(f"Unsupported TAIFEX OpenAPI dataset: {dataset}")

    response = get(
        f"{OPENAPI_BASE_URL}/{dataset}",
        provider=PROVIDER,
        resource=resource,
        target=target,
        timeout_seconds=timeout_seconds,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json",
        },
    )
    payload = json_from_response(response)
    if not isinstance(payload, list):
        raise ValueError(f"TAIFEX OpenAPI {dataset} returned a non-list payload.")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(
                f"TAIFEX OpenAPI {dataset} row {index} is not an object."
            )
        rows.append(item)
    return rows


__all__ = [
    "OPENAPI_BASE_URL",
    "OPENAPI_DATASETS",
    "PROVIDER",
    "fetch_openapi_rows",
    "get_response",
    "post_response",
]
