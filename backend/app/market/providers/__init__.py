from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from . import nstock, taifex, tpex, twse, twse_mis, yahoo


def fetch_json(
    url: str,
    *,
    timeout_seconds: int = 20,
    request=None,
) -> Any:
    host = urlsplit(url).hostname or ""
    if host.endswith("tpex.org.tw"):
        return tpex.fetch_json(url, timeout_seconds=timeout_seconds, request=request)
    if host == "mis.twse.com.tw":
        response = twse_mis.get_response(url, timeout_seconds=timeout_seconds)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.json()
    if host.endswith("twse.com.tw"):
        return twse.fetch_json(url, timeout_seconds=timeout_seconds, request=request)
    raise ValueError(f"Unsupported Taiwan index provider URL: {url}")


def http_get(url: str, *args: Any, **kwargs: Any):
    if args:
        raise TypeError("Taiwan provider compatibility GET accepts keyword arguments only.")
    timeout_seconds = kwargs.pop("timeout", 20)
    host = urlsplit(url).hostname or ""
    if host == "query1.finance.yahoo.com":
        return yahoo.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    if host == "mis.twse.com.tw":
        return twse_mis.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    if host.endswith("nstock.tw"):
        return nstock.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    if host.endswith("taifex.com.tw"):
        return taifex.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    if host.endswith("tpex.org.tw"):
        return tpex.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    if host.endswith("twse.com.tw"):
        return twse.get_response(url, timeout_seconds=timeout_seconds, **kwargs)
    raise ValueError(f"Unsupported Taiwan index provider URL: {url}")


def http_post(url: str, *args: Any, **kwargs: Any):
    if args:
        raise TypeError("Taiwan provider compatibility POST accepts keyword arguments only.")
    timeout_seconds = kwargs.pop("timeout", 20)
    host = urlsplit(url).hostname or ""
    if host.endswith("taifex.com.tw"):
        return taifex.post_response(url, timeout_seconds=timeout_seconds, **kwargs)
    raise ValueError(f"Unsupported Taiwan index provider POST URL: {url}")


__all__ = [
    "fetch_json",
    "http_get",
    "http_post",
    "nstock",
    "taifex",
    "tpex",
    "twse",
    "twse_mis",
    "yahoo",
]
