from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.market.providers._http import DEFAULT_HEADERS, get
from app.market.providers.tw_etf_contracts import (
    TaiwanEtfInavRecord,
    TaiwanEtfPcfRecord,
)


CATHAY_PROVIDER = "cathay_etfs"
CATHAY_ETF_LIST_URL = "https://cwapi.cathaysite.com.tw/api/ETF/GetETFList"
CATHAY_INAV_URL = "https://cwapi.cathaysite.com.tw/api/ETF/GetEtfNavPri"
CATHAY_INAV_PAGE_URL = "https://www.cathaysite.com.tw/ETF"
CATHAY_PCF_PAGE_URL = "https://www.cathaysite.com.tw/ETF/purchase"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfCathayProviderError(RuntimeError):
    pass


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized.casefold() in {"null", "none", "undefined", "-", "--"}:
        return None
    return normalized


def _decimal(value: object) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return Decimal(
            normalized.replace("NT$", "").replace(",", "").replace("%", "").strip()
        )
    except InvalidOperation as exc:
        raise TaiwanEtfCathayProviderError(
            f"Invalid Cathay ETF numeric value: {normalized}"
        ) from exc


def _integer(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed != parsed.to_integral_value():
        raise TaiwanEtfCathayProviderError(
            f"Invalid Cathay ETF integer value: {value}"
        )
    return int(parsed)


def _date(value: object, *, required: bool = False) -> date | None:
    normalized = _text(value)
    if normalized is None:
        if required:
            raise TaiwanEtfCathayProviderError(
                "Cathay ETF PCF omitted a required date."
            )
        return None
    for date_format in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise TaiwanEtfCathayProviderError(
        f"Invalid Cathay ETF date value: {normalized}"
    )


def _result(payload: object, *, operation: str) -> object:
    if not isinstance(payload, dict):
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF {operation} response was not an object."
        )
    if payload.get("success") is not True or str(payload.get("returnCode")) != "2000":
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF {operation} failed: {_text(payload.get('returnMessage')) or 'unknown error'}."
        )
    return payload.get("result")


def parse_cathay_etf_list_payload(
    payload: object,
    stock_id: str,
) -> tuple[str, str | None]:
    normalized_id = stock_id.strip().upper()
    result = _result(payload, operation="fund lookup")
    if not isinstance(result, list):
        raise TaiwanEtfCathayProviderError(
            "Cathay ETF fund lookup result was not a list."
        )
    matches = [
        row
        for row in result
        if isinstance(row, dict)
        and str(row.get("stockCode") or "").strip().upper() == normalized_id
    ]
    if len(matches) != 1:
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF fund lookup returned {len(matches)} exact matches for stock_id={normalized_id}."
        )
    fund_code = _text(matches[0].get("fundCode"))
    if fund_code is None:
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF fund lookup omitted fundCode for stock_id={normalized_id}."
        )
    return fund_code, _text(
        matches[0].get("stockShortNameFix") or matches[0].get("fundSName")
    )


def parse_cathay_etf_inav_payload(
    payload: object,
    stock_id: str,
    *,
    fund_short_name: str | None = None,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    result = _result(payload, operation="iNAV")
    if not isinstance(result, dict):
        raise TaiwanEtfCathayProviderError("Cathay ETF iNAV result was not an object.")
    estimated_nav = _decimal(result.get("預估淨值"))
    if estimated_nav is None or estimated_nav <= 0:
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF iNAV for stock_id={normalized_id} had no valid NAV."
        )
    observed_text = _text(result.get("時間"))
    if observed_text is None:
        raise TaiwanEtfCathayProviderError("Cathay ETF iNAV omitted its source timestamp.")
    try:
        observed_at = datetime.strptime(observed_text, "%Y/%m/%d %H:%M:%S").replace(
            tzinfo=TAIWAN_TZ
        )
    except ValueError as exc:
        raise TaiwanEtfCathayProviderError(
            f"Invalid Cathay ETF iNAV timestamp: {observed_text}"
        ) from exc
    market_price = _decimal(result.get("最新市價"))
    if market_price is not None and market_price <= 0:
        market_price = None
    premium_discount_pct = None
    if market_price is not None:
        premium_discount_pct = (market_price - estimated_nav) / estimated_nav * 100
    return TaiwanEtfInavRecord(
        stock_id=normalized_id,
        fund_short_name=fund_short_name,
        investment_area=None,
        estimated_nav=estimated_nav,
        nav_change=_decimal(result.get("淨值漲跌")),
        market_price=market_price,
        price_change=_decimal(result.get("市價漲跌")),
        premium_discount_pct=premium_discount_pct,
        observed_at=observed_at,
    )


def parse_cathay_etf_pcf_html(
    html: str,
    stock_id: str,
    *,
    fund_code: str,
    fund_short_name: str | None = None,
    target_date: date | None = None,
) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    soup = BeautifulSoup(html or "", "html.parser")
    title = _text(soup.title.get_text(" ", strip=True) if soup.title else None)
    if title is None or re.match(rf"^{re.escape(normalized_id)}(?:\s|$)", title) is None:
        returned_id = title.split(" ", 1)[0] if title else "missing"
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF PCF returned stock_id={returned_id} "
            f"for requested stock_id={normalized_id}."
        )

    values: dict[str, str] = {}
    dated_labels: dict[str, date] = {}
    for row in soup.select("div.li"):
        label_node = row.select_one("h3.table-subtitle")
        value_node = row.select_one("p")
        label = _text(
            label_node.get_text(" ", strip=True) if label_node is not None else None
        )
        value = _text(
            value_node.get_text(" ", strip=True) if value_node is not None else None
        )
        if label is None or value is None:
            continue
        date_match = re.match(r"^(\d{4}/\d{2}/\d{2})\s+(.+)$", label)
        if date_match is not None:
            parsed_date = _date(date_match.group(1), required=True)
            assert parsed_date is not None
            label = date_match.group(2)
            dated_labels[label] = parsed_date
        values[label] = value

    required_labels = {
        "基金淨資產價值(元)",
        "預收申購總價金(元)",
        "已發行受益權單位總數",
        "與前日已發行單位差異數",
        "每受益權單位淨資產價值(元)",
        "每現金申購/買回基數之受益權單位數",
        "每現金申購/買回基數估計現金差額(元)",
    }
    missing_labels = sorted(required_labels.difference(values))
    if missing_labels:
        raise TaiwanEtfCathayProviderError(
            "Cathay ETF PCF omitted required fields: " + ", ".join(missing_labels)
        )

    effective_dates: set[date] = set()
    for node in soup.select("input[value], option[value]"):
        date_value = _text(node.get("value"))
        if date_value is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value) is None:
            continue
        parsed = _date(date_value, required=True)
        assert parsed is not None
        effective_dates.add(parsed)
    if len(effective_dates) != 1:
        raise TaiwanEtfCathayProviderError(
            "Cathay ETF PCF effective date was missing or ambiguous."
        )
    effective_date = next(iter(effective_dates))
    if target_date is not None and effective_date != target_date:
        raise TaiwanEtfCathayProviderError(
            f"Cathay ETF PCF returned effective_date={effective_date.isoformat()} "
            f"for requested target_date={target_date.isoformat()}."
        )

    nav_label = "每受益權單位淨資產價值(元)"
    reference_date = dated_labels.get(nav_label)
    if reference_date is None:
        raise TaiwanEtfCathayProviderError(
            "Cathay ETF PCF unit NAV omitted its reference date."
        )
    title_name = _text(re.sub(rf"^{re.escape(normalized_id)}\s*", "", title))
    if title_name:
        title_name = _text(title_name.split("－", 1)[0])

    return TaiwanEtfPcfRecord(
        stock_id=normalized_id,
        fund_id=_text(fund_code),
        fund_name=fund_short_name or title_name,
        full_name=None,
        name_en=None,
        reference_date=reference_date,
        effective_date=effective_date,
        total_net_assets=_decimal(values["基金淨資產價值(元)"]),
        issued_units=_integer(values["已發行受益權單位總數"]),
        unit_nav=_decimal(values[nav_label]),
        creation_unit=_integer(values["每現金申購/買回基數之受益權單位數"]),
        estimated_creation_value=_decimal(values["預收申購總價金(元)"]),
        estimated_cash_component=_decimal(
            values["每現金申購/買回基數估計現金差額(元)"]
        ),
        unit_change=_integer(values["與前日已發行單位差異數"]),
        actual_cash_component=None,
        redemption_method="cash",
        source_updated_at=None,
        components=(),
    )


def fetch_cathay_etf_pcf(
    stock_id: str,
    *,
    target_date: date | None = None,
    request_get: Callable[..., Any] = get,
) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    lookup_headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json,text/plain,*/*",
        "Referer": CATHAY_PCF_PAGE_URL,
    }
    lookup_response = request_get(
        CATHAY_ETF_LIST_URL,
        provider=CATHAY_PROVIDER,
        resource="etf_pcf",
        target=normalized_id,
        timeout_seconds=20,
        headers=lookup_headers,
        params={"Keyword": normalized_id, "CurrentPage": 1, "PerPageCount": 10},
    )
    lookup_response.raise_for_status()
    fund_code, fund_short_name = parse_cathay_etf_list_payload(
        lookup_response.json(), normalized_id
    )
    pcf_response = request_get(
        CATHAY_PCF_PAGE_URL,
        provider=CATHAY_PROVIDER,
        resource="etf_pcf",
        target=normalized_id,
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": CATHAY_PCF_PAGE_URL,
        },
        params={"code": fund_code, "name": fund_short_name or normalized_id},
    )
    pcf_response.raise_for_status()
    if hasattr(pcf_response, "encoding"):
        pcf_response.encoding = "utf-8"
    html = pcf_response.text
    return parse_cathay_etf_pcf_html(
        html,
        normalized_id,
        fund_code=fund_code,
        fund_short_name=fund_short_name,
        target_date=target_date,
    )


def fetch_cathay_etf_inav(
    stock_id: str,
    *,
    request_get: Callable[..., Any] = get,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json,text/plain,*/*",
        "Referer": CATHAY_INAV_PAGE_URL,
    }
    lookup_response = request_get(
        CATHAY_ETF_LIST_URL,
        provider=CATHAY_PROVIDER,
        resource="etf_intraday_estimated_nav",
        target=normalized_id,
        timeout_seconds=20,
        headers=headers,
        params={"Keyword": normalized_id, "CurrentPage": 1, "PerPageCount": 10},
    )
    lookup_response.raise_for_status()
    fund_code, fund_short_name = parse_cathay_etf_list_payload(
        lookup_response.json(), normalized_id
    )
    inav_response = request_get(
        CATHAY_INAV_URL,
        provider=CATHAY_PROVIDER,
        resource="etf_intraday_estimated_nav",
        target=normalized_id,
        timeout_seconds=20,
        headers=headers,
        params={"FundCode": fund_code},
    )
    inav_response.raise_for_status()
    return parse_cathay_etf_inav_payload(
        inav_response.json(),
        normalized_id,
        fund_short_name=fund_short_name,
    )


__all__ = [
    "CATHAY_ETF_LIST_URL",
    "CATHAY_INAV_PAGE_URL",
    "CATHAY_INAV_URL",
    "CATHAY_PCF_PAGE_URL",
    "CATHAY_PROVIDER",
    "TaiwanEtfCathayProviderError",
    "fetch_cathay_etf_pcf",
    "fetch_cathay_etf_inav",
    "parse_cathay_etf_pcf_html",
    "parse_cathay_etf_inav_payload",
    "parse_cathay_etf_list_payload",
]
