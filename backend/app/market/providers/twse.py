from __future__ import annotations

from datetime import date
from typing import Any

from ._http import DEFAULT_HEADERS, ResponseGetter, get, get_json, json_from_response


OPENAPI_PROVIDER = "twse_openapi"
RWD_PROVIDER = "twse_rwd"
INDEX_5S_PROVIDER = "twse_index_5s"
INDEX_DAILY_OHLC_PROVIDER = "twse_index_daily_ohlc"

HOLIDAY_SCHEDULE_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
INDEX_LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
DAILY_QUOTES_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
RWD_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
INDEX_5S_URL = "https://www.twse.com.tw/exchangeReport/MI_5MINS_INDEX"
INDEX_DAILY_OHLC_URL = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
MARKET_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
MARKET_DAILY_HISTORY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
COMPANY_BASIC_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"


def _parse_twse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        if len(text) == 7 and text.isdigit():
            return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return None


def parse_twse_holiday_schedule(payload: Any) -> dict[date, str]:
    if not isinstance(payload, list):
        raise ValueError("TWSE holiday schedule returned a non-list JSON payload.")

    holidays: dict[date, str] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        holiday_date = _parse_twse_date(row.get("Date"))
        if holiday_date is None:
            continue
        name = str(row.get("Name") or "").strip()
        description = str(row.get("Description") or "").strip()
        combined = f"{name} {description}"
        if "開始交易" in combined or "最後交易" in combined:
            continue
        if not name:
            name = "市場休市"
        holidays[holiday_date] = name

    if len(holidays) < 8:
        raise ValueError(
            f"TWSE holiday schedule returned too few usable rows: {len(holidays)}."
        )
    return holidays


def fetch_twse_holiday_schedule(
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> tuple[dict[date, str], str]:
    payload = fetch_json(
        HOLIDAY_SCHEDULE_URL,
        timeout_seconds=timeout_seconds,
        request=request,
    )
    return parse_twse_holiday_schedule(payload), HOLIDAY_SCHEDULE_URL


def _request_contract(url: str) -> tuple[str, str, str]:
    if "holidaySchedule" in url:
        return OPENAPI_PROVIDER, "exchange_calendar", "TWSE"
    if "/rwd/" in url:
        if "/fund/BFI82U" in url:
            resource = "institutional_summary"
        elif "/marginTrading/MI_MARGN" in url:
            resource = "margin_balance"
        else:
            resource = "market_breadth" if "/MI_INDEX" in url else "market_daily_history"
        return RWD_PROVIDER, resource, "TAIEX"
    if "MI_5MINS_HIST" in url:
        return INDEX_DAILY_OHLC_PROVIDER, "index_daily_ohlc", "TAIEX"
    if "MI_5MINS_INDEX" in url:
        return INDEX_5S_PROVIDER, "index_intraday", "TAIEX"
    if "STOCK_DAY_ALL" in url:
        return OPENAPI_PROVIDER, "daily_quotes", "TWSE"
    if "t187ap03_L" in url:
        return OPENAPI_PROVIDER, "company_shares", "TWSE"
    if "/FMTQIK" in url:
        return OPENAPI_PROVIDER, "market_daily", "TAIEX"
    return OPENAPI_PROVIDER, "index_list", "TWSE"


def fetch_json(
    url: str,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    if request is not None:
        response = request(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)
    provider, resource, target = _request_contract(url)
    return get_json(
        url,
        provider=provider,
        resource=resource,
        target=target,
        timeout_seconds=timeout_seconds,
    )


def fetch_index_5s_payload(
    trade_date: date,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    params = {
        "response": "json",
        "date": trade_date.strftime("%Y%m%d"),
    }
    if request is not None:
        response = request(
            INDEX_5S_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)

    response = get(
        INDEX_5S_URL,
        provider=INDEX_5S_PROVIDER,
        resource="index_intraday",
        target="TAIEX",
        params=params,
        headers=DEFAULT_HEADERS,
        timeout_seconds=timeout_seconds,
    )
    return json_from_response(response)


def fetch_index_daily_ohlc_payload(
    trade_date: date,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    params = {
        "response": "json",
        "date": trade_date.strftime("%Y%m%d"),
    }
    if request is not None:
        response = request(
            INDEX_DAILY_OHLC_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)

    response = get(
        INDEX_DAILY_OHLC_URL,
        provider=INDEX_DAILY_OHLC_PROVIDER,
        resource="index_daily_ohlc",
        target="TAIEX",
        params=params,
        headers=DEFAULT_HEADERS,
        timeout_seconds=timeout_seconds,
    )
    return json_from_response(response)


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    provider, resource, target = _request_contract(url)
    return get(
        url,
        provider=provider,
        resource=resource,
        target=target,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )
