from __future__ import annotations

from datetime import date
from typing import Any

from app.kr_market.errors import KRMarketDataFetchError

from ._http import get as provider_get


NAVER_SISE_INDEX_URL = "https://api.finance.naver.com/siseJson.naver"
NAVER_SISE_INDEX_TIME_URL = "https://finance.naver.com/sise/sise_index_time.naver"
NAVER_INDEX_REALTIME_URL = "https://polling.finance.naver.com/api/realtime"


def fetch_naver_index_chart_payload(
    *,
    provider_symbol: str,
    start_date: date,
    end_date: date,
    timeout_seconds: int,
) -> tuple[str, str]:
    response = provider_get(
        NAVER_SISE_INDEX_URL,
        provider="naver_sise_index",
        resource="index_daily_price",
        target=provider_symbol,
        params={
            "symbol": provider_symbol,
            "requestType": "1",
            "startTime": start_date.strftime("%Y%m%d"),
            "endTime": end_date.strftime("%Y%m%d"),
            "timeframe": "day",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/plain,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    response.encoding = response.encoding or "utf-8"
    return response.text, response.url


def fetch_naver_index_intraday_page_payload(
    *,
    provider_symbol: str,
    thistime: str,
    page: int,
    timeout_seconds: int,
) -> tuple[str, str]:
    response = provider_get(
        NAVER_SISE_INDEX_TIME_URL,
        provider="naver_sise_index",
        resource="index_intraday",
        target=provider_symbol,
        params={
            "code": provider_symbol,
            "thistime": thistime,
            "page": page,
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/html,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    response.encoding = response.encoding or "euc-kr"
    return response.text, response.url


def fetch_naver_index_realtime_payload(
    *,
    provider_symbol: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = provider_get(
        NAVER_INDEX_REALTIME_URL,
        provider="naver_sise_index",
        resource="index_quote",
        target=provider_symbol,
        params={"query": f"SERVICE_INDEX:{provider_symbol}"},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("Naver realtime index returned a non-object JSON payload.")
    return payload, response.url
