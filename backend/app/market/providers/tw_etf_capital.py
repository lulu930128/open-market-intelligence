from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.market.providers._http import DEFAULT_HEADERS, post
from app.market.providers.tw_etf_contracts import TaiwanEtfInavRecord


CAPITAL_PROVIDER = "capital_etfs"
CAPITAL_INAV_URL = "https://www.capitalfund.com.tw/CFWeb/api/etf/nav"
CAPITAL_INAV_PAGE_URL = "https://www.capitalfund.com.tw/etf/transaction/networth"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfCapitalProviderError(RuntimeError):
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
        return Decimal(normalized.replace(",", "").replace("%", ""))
    except InvalidOperation as exc:
        raise TaiwanEtfCapitalProviderError(
            f"Invalid Capital ETF numeric value: {normalized}"
        ) from exc


def parse_capital_etf_inav_payload(payload: object, stock_id: str) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise TaiwanEtfCapitalProviderError("Capital ETF iNAV response was not successful.")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TaiwanEtfCapitalProviderError("Capital ETF iNAV data was not a list.")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("stocNo") or "").strip().upper() == normalized_id
    ]
    if len(matches) != 1:
        raise TaiwanEtfCapitalProviderError(
            f"Capital ETF iNAV returned {len(matches)} exact matches for stock_id={normalized_id}."
        )
    row = matches[0]
    estimated_nav = _decimal(row.get("nav"))
    if estimated_nav is None or estimated_nav <= 0:
        raise TaiwanEtfCapitalProviderError(
            f"Capital ETF iNAV for stock_id={normalized_id} had no valid NAV."
        )
    timestamp = f"{_text(row.get('date1')) or ''} {_text(row.get('time1')) or ''}".strip()
    try:
        observed_at = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S").replace(
            tzinfo=TAIWAN_TZ
        )
    except ValueError as exc:
        raise TaiwanEtfCapitalProviderError(
            f"Invalid Capital ETF iNAV timestamp: {timestamp or 'missing'}"
        ) from exc
    market_price = _decimal(row.get("price"))
    if market_price is not None and market_price <= 0:
        market_price = None
    return TaiwanEtfInavRecord(
        stock_id=normalized_id,
        fund_short_name=_text(row.get("stocSname") or row.get("fundName")),
        investment_area=None,
        estimated_nav=estimated_nav,
        nav_change=_decimal(row.get("navChange")),
        market_price=market_price,
        price_change=_decimal(row.get("priceChange")),
        premium_discount_pct=_decimal(row.get("diffRatio")),
        observed_at=observed_at,
    )


def fetch_capital_etf_inav(
    stock_id: str,
    *,
    request_post: Callable[..., Any] = post,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    response = request_post(
        CAPITAL_INAV_URL,
        provider=CAPITAL_PROVIDER,
        resource="etf_intraday_estimated_nav",
        target=normalized_id,
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Content-Type": "application/json",
            "Referer": CAPITAL_INAV_PAGE_URL,
        },
        json=None,
    )
    response.raise_for_status()
    return parse_capital_etf_inav_payload(response.json(), normalized_id)


__all__ = [
    "CAPITAL_INAV_PAGE_URL",
    "CAPITAL_INAV_URL",
    "CAPITAL_PROVIDER",
    "TaiwanEtfCapitalProviderError",
    "fetch_capital_etf_inav",
    "parse_capital_etf_inav_payload",
]
