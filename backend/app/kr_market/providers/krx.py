from __future__ import annotations

from datetime import date
from typing import Any

from bs4 import BeautifulSoup
import requests

from app.kr_market.errors import KRMarketDataFetchError

from ._http import get as provider_get
from ._http import post as provider_post


KRX_DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_STOCK_MASTER_BLD = "dbms/MDC/STAT/standard/MDCSTAT01901"
KRX_DAILY_PRICE_BLD = "dbms/MDC/STAT/standard/MDCSTAT01501"
KRX_INVESTOR_TRADE_BLD = "dbms/MDC/STAT/standard/MDCSTAT02401"
KRX_MARKET_HOLIDAY_PAGE_URL = (
    "https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp"
)
KRX_MARKET_HOLIDAY_OTP_URL = "https://open.krx.co.kr/contents/COM/GenerateOTP.jspx"
KRX_MARKET_HOLIDAY_DATA_URL = (
    "https://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx"
)
KRX_MARKET_HOLIDAY_BLD = "MKD/01/0110/01100305/mkd01100305_01"
KRX_MARKET_HOLIDAY_PAGE_PATH = "/contents/MKD/01/0110/01100305/MKD01100305.jsp"


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


def parse_krx_market_holidays(
    payload: Any,
    *,
    year: int,
) -> dict[date, str]:
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError(
            "KRX market calendar returned a non-object JSON payload."
        )
    rows = payload.get("block1")
    if not isinstance(rows, list):
        raise KRMarketDataFetchError(
            "KRX market calendar payload is missing block1 rows."
        )

    holidays: dict[date, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = str(row.get("calnd_dd") or row.get("calnd_dd_dy") or "").strip()
        try:
            holiday_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if holiday_date.year != year:
            continue
        name = str(row.get("holdy_nm") or "").strip() or "KRX Market Holiday"
        holidays[holiday_date] = name

    if len(holidays) < 8:
        raise KRMarketDataFetchError(
            f"KRX market calendar returned too few usable rows for {year}: {len(holidays)}."
        )
    return holidays


def fetch_krx_market_holidays(
    *,
    year: int,
    timeout_seconds: int,
) -> tuple[dict[date, str], str]:
    session = requests.Session()
    headers = {
        "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Referer": KRX_MARKET_HOLIDAY_PAGE_URL,
    }
    page_response = provider_get(
        KRX_MARKET_HOLIDAY_PAGE_URL,
        provider="krx_calendar",
        resource="exchange_calendar",
        target="KRX",
        headers=headers,
        timeout_seconds=timeout_seconds,
        request_callable=session.request,
    )
    soup = BeautifulSoup(page_response.text, "lxml")
    available_years = {
        int(option.get("value"))
        for option in soup.select('select[name="search_bas_yy"] option[value]')
        if str(option.get("value") or "").isdigit()
    }
    if year not in available_years:
        raise KRMarketDataFetchError(
            f"KRX market calendar page does not offer year {year}."
        )

    otp_response = provider_get(
        KRX_MARKET_HOLIDAY_OTP_URL,
        provider="krx_calendar",
        resource="exchange_calendar_otp",
        target="KRX",
        params={"name": "form", "bld": KRX_MARKET_HOLIDAY_BLD},
        headers=headers,
        timeout_seconds=timeout_seconds,
        request_callable=session.request,
    )
    otp_code = otp_response.text.strip()
    if len(otp_code) < 20:
        raise KRMarketDataFetchError("KRX market calendar returned an invalid OTP code.")

    data_response = provider_post(
        KRX_MARKET_HOLIDAY_DATA_URL,
        provider="krx_calendar",
        resource="exchange_calendar",
        target="KRX",
        data={
            "search_bas_yy": str(year),
            "gridTp": "KRX",
            "pagePath": KRX_MARKET_HOLIDAY_PAGE_PATH,
            "code": otp_code,
        },
        headers=headers,
        timeout_seconds=timeout_seconds,
        request_callable=session.request,
    )
    try:
        payload = data_response.json()
    except requests.JSONDecodeError as exc:
        raise KRMarketDataFetchError(
            "KRX market calendar returned malformed JSON."
        ) from exc
    return parse_krx_market_holidays(payload, year=year), data_response.url
