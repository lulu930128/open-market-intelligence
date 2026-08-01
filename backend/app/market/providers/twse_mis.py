from __future__ import annotations

from typing import Any

from ._http import DEFAULT_HEADERS, ResponseGetter, get, json_from_response


PROVIDER = "twse_mis"
STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
REFERER_URL = "https://mis.twse.com.tw/stock/fibest.jsp?lang=zh_tw"


def _headers() -> dict[str, str]:
    return {**DEFAULT_HEADERS, "Referer": REFERER_URL}


def _fetch_payload(
    *,
    channel: str,
    resource: str,
    target: str,
    timeout_seconds: int,
    request: ResponseGetter | None = None,
) -> Any:
    params = {
        "ex_ch": channel,
        "json": "1",
        "delay": "0",
    }
    if request is not None:
        response = request(
            STOCK_INFO_URL,
            params=params,
            headers=_headers(),
            timeout=timeout_seconds,
        )
        return json_from_response(response)

    response = get(
        STOCK_INFO_URL,
        provider=PROVIDER,
        resource=resource,
        target=target,
        params=params,
        headers=_headers(),
        timeout_seconds=timeout_seconds,
    )
    return json_from_response(response)


def fetch_stock_messages(
    codes: list[str],
    *,
    exchange: str = "tse",
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> list[dict]:
    normalized_exchange = str(exchange or "").strip().lower()
    if normalized_exchange not in {"tse", "otc"}:
        raise ValueError("TWSE MIS exchange must be tse or otc.")
    payload = _fetch_payload(
        channel="|".join(
            f"{normalized_exchange}_{code}.tw" for code in codes
        ),
        resource="stock_quote_batch",
        target=f"count:{len(codes)}",
        timeout_seconds=timeout_seconds,
        request=request,
    )
    if not isinstance(payload, dict) or str(payload.get("rtcode") or "") not in {"", "0000"}:
        raise ValueError("TWSE MIS live stock quote payload is unavailable.")
    messages = payload.get("msgArray") or []
    return [message for message in messages if isinstance(message, dict)]


def fetch_index_message(
    channel: str,
    *,
    target: str,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> dict | None:
    payload = _fetch_payload(
        channel=channel,
        resource="index_snapshot",
        target=target,
        timeout_seconds=timeout_seconds,
        request=request,
    )
    if not isinstance(payload, dict):
        return None
    message = (payload.get("msgArray") or [None])[0]
    return message if isinstance(message, dict) else None


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    params = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {}
    channel = str(params.get("ex_ch") or "")
    resource = str(
        kwargs.pop("omi_resource", None)
        or ("stock_quote_batch" if "|" in channel else "index_snapshot")
    )
    target = str(
        kwargs.pop("omi_target", None)
        or (f"count:{channel.count('|') + 1}" if "|" in channel else channel or "all")
    )
    return get(
        url,
        provider=PROVIDER,
        resource=resource,
        target=target,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
