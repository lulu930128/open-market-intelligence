from __future__ import annotations

from datetime import date
from typing import Any

from app.kr_market.errors import KRMarketDataFetchError

from ._http import post as provider_post


KRX_DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_STOCK_MASTER_BLD = "dbms/MDC/STAT/standard/MDCSTAT01901"
KRX_DAILY_PRICE_BLD = "dbms/MDC/STAT/standard/MDCSTAT01501"
KRX_INVESTOR_TRADE_BLD = "dbms/MDC/STAT/standard/MDCSTAT02401"


def _post_payload(
    *,
    resource: str,
    payload_label: str,
    target: str = "all",
    data: dict[str, str],
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = provider_post(
        KRX_DATA_URL,
        provider="krx_data",
        resource=resource,
        target=target,
        data=data,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.krx.co.kr/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError(
            f"KRX {payload_label} returned a non-object JSON payload."
        )
    return payload, response.url


def fetch_krx_stock_master_payload(*, timeout_seconds: int) -> tuple[dict[str, Any], str]:
    return _post_payload(
        resource="symbol_master",
        payload_label="stock master",
        data={
            "bld": KRX_STOCK_MASTER_BLD,
            "mktId": "ALL",
            "share": "1",
            "csvxls_isNo": "false",
        },
        timeout_seconds=timeout_seconds,
    )


def fetch_krx_daily_price_payload(
    *,
    local_code: str | None = None,
    market_id: str = "ALL",
    trade_date: date | None = None,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    params = {
        "bld": KRX_DAILY_PRICE_BLD,
        "mktId": market_id,
        "isuCd": local_code or "",
        "isuCd2": local_code or "",
        "csvxls_isNo": "false",
    }
    if trade_date is not None:
        params["trdDd"] = trade_date.strftime("%Y%m%d")

    return _post_payload(
        resource="daily_price",
        payload_label="daily price",
        target=local_code or "all",
        data=params,
        timeout_seconds=timeout_seconds,
    )


def fetch_krx_investor_trade_payload(
    *,
    local_code: str,
    trade_date: date | None = None,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    params = {
        "bld": KRX_INVESTOR_TRADE_BLD,
        "mktId": "ALL",
        "isuCd": local_code,
        "isuCd2": local_code,
        "csvxls_isNo": "false",
    }
    if trade_date is not None:
        params["trdDd"] = trade_date.strftime("%Y%m%d")

    return _post_payload(
        resource="investor_trading",
        payload_label="investor trading",
        target=local_code,
        data=params,
        timeout_seconds=timeout_seconds,
    )
