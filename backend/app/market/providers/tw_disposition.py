from __future__ import annotations

from datetime import date
import re
from typing import Any

from ._http import get_json


TWSE_PROVIDER = "twse_openapi"
TPEX_PROVIDER = "tpex_openapi"
RESOURCE = "disposition_securities"

TWSE_DISPOSITION_URL = "https://openapi.twse.com.tw/v1/announcement/punish"
TPEX_DISPOSITION_URL = (
    "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"
)

_DATE_TOKEN = re.compile(
    r"(?<!\d)(\d{3}/\d{1,2}/\d{1,2}|\d{4}/\d{1,2}/\d{1,2}|\d{7}|\d{8})(?!\d)"
)
_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_market_date(value: Any) -> date | None:
    text = str(value or "").strip().replace("-", "/")
    try:
        if "/" in text:
            parts = [int(part) for part in text.split("/")]
            if len(parts) != 3:
                return None
            year, month, day = parts
            if year < 1911:
                year += 1911
            return date(year, month, day)
        if text.isdigit() and len(text) == 7:
            return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
        if text.isdigit() and len(text) == 8:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return None


def _parse_period(value: Any) -> tuple[date | None, date | None]:
    tokens = _DATE_TOKEN.findall(str(value or ""))
    parsed = [item for token in tokens if (item := _parse_market_date(token))]
    if len(parsed) < 2:
        return None, None
    return parsed[0], parsed[1]


def _chinese_number(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text == "十":
        return 10
    if "十" in text:
        tens, ones = text.split("十", 1)
        tens_value = _CHINESE_DIGITS.get(tens, 1 if not tens else -1)
        ones_value = _CHINESE_DIGITS.get(ones, 0 if not ones else -1)
        if tens_value >= 0 and ones_value >= 0:
            return tens_value * 10 + ones_value
        return None
    return _CHINESE_DIGITS.get(text)


def _matching_interval_minutes(value: Any) -> int | None:
    text = str(value or "")
    arabic = re.search(r"(?:約)?每\s*(\d{1,2})\s*分鐘", text)
    if arabic:
        return int(arabic.group(1))
    chinese = re.search(r"(?:約)?每\s*([一二三四五六七八九十]+)\s*分鐘", text)
    return _chinese_number(chinese.group(1)) if chinese else None


def _normalized_entry(
    *,
    provider: str,
    market: str,
    source_url: str,
    announced_date: date | None,
    stock_id: Any,
    stock_name: Any,
    period: Any,
    reason: Any,
    measure: Any,
    detail: Any,
) -> dict[str, Any] | None:
    normalized_stock_id = str(stock_id or "").strip()
    start_date, end_date = _parse_period(period)
    if not normalized_stock_id or start_date is None or end_date is None:
        return None
    detail_text = str(detail or "").strip()
    return {
        "provider": provider,
        "market": market,
        "source_url": source_url,
        "announced_date": announced_date,
        "stock_id": normalized_stock_id,
        "stock_name": str(stock_name or "").strip() or None,
        "start_date": start_date,
        "end_date": end_date,
        "matching_interval_minutes": _matching_interval_minutes(detail_text),
        "reason": str(reason or "").strip() or None,
        "measure": str(measure or "").strip() or None,
        "requires_full_precollection": "收取全部" in detail_text,
        "margin_trading_suspended": "暫停融資融券" in detail_text,
        "detail": detail_text or None,
    }


def parse_twse_dispositions(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("TWSE disposition API returned a non-list JSON payload.")
    entries: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        entry = _normalized_entry(
            provider=TWSE_PROVIDER,
            market="TWSE",
            source_url=TWSE_DISPOSITION_URL,
            announced_date=_parse_market_date(row.get("Date")),
            stock_id=row.get("Code"),
            stock_name=row.get("Name"),
            period=row.get("DispositionPeriod"),
            reason=row.get("ReasonsOfDisposition"),
            measure=row.get("DispositionMeasures"),
            detail=row.get("Detail"),
        )
        if entry is not None:
            entries.append(entry)
    if payload and not entries:
        raise ValueError("TWSE disposition API returned no usable rows.")
    return entries


def parse_tpex_dispositions(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("TPEx disposition API returned a non-list JSON payload.")
    entries: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        entry = _normalized_entry(
            provider=TPEX_PROVIDER,
            market="TPEX",
            source_url=TPEX_DISPOSITION_URL,
            announced_date=_parse_market_date(row.get("Date")),
            stock_id=row.get("SecuritiesCompanyCode"),
            stock_name=row.get("CompanyName"),
            period=row.get("DispositionPeriod"),
            reason=row.get("DispositionReasons"),
            measure="處置有價證券",
            detail=row.get("DisposalCondition"),
        )
        if entry is not None:
            entries.append(entry)
    if payload and not entries:
        raise ValueError("TPEx disposition API returned no usable rows.")
    return entries


def fetch_twse_dispositions(*, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    payload = get_json(
        TWSE_DISPOSITION_URL,
        provider=TWSE_PROVIDER,
        resource=RESOURCE,
        target="TWSE",
        timeout_seconds=timeout_seconds,
    )
    return parse_twse_dispositions(payload)


def fetch_tpex_dispositions(*, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    payload = get_json(
        TPEX_DISPOSITION_URL,
        provider=TPEX_PROVIDER,
        resource=RESOURCE,
        target="TPEX",
        timeout_seconds=timeout_seconds,
    )
    return parse_tpex_dispositions(payload)


__all__ = [
    "TPEX_DISPOSITION_URL",
    "TPEX_PROVIDER",
    "TWSE_DISPOSITION_URL",
    "TWSE_PROVIDER",
    "fetch_tpex_dispositions",
    "fetch_twse_dispositions",
    "parse_tpex_dispositions",
    "parse_twse_dispositions",
]
