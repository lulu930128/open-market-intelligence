from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.market.providers._http import DEFAULT_HEADERS, get
from app.market.providers.tw_etf_contracts import TaiwanEtfInavRecord


FUH_HWA_PROVIDER = "fuh_hwa_etfs"
FUH_HWA_INAV_URL = "https://www.fhtrust.com.tw/ETF"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfFuhHwaProviderError(RuntimeError):
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
        raise TaiwanEtfFuhHwaProviderError(
            f"Invalid Fuh Hwa ETF numeric value: {normalized}"
        ) from exc


def _card_rows(card: Any) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for row in card.select(".fundCard-state .row"):
        label_node = row.select_one(".fundCard-stateName")
        label = _text(label_node.get_text(" ", strip=True) if label_node else None)
        if label is None:
            continue
        values = [
            value
            for node in row.select(".fundFluctuate")
            if (value := _text(node.get_text(" ", strip=True))) is not None
        ]
        rows[label] = values
    return rows


def parse_fuh_hwa_etf_inav_html(html: str, stock_id: str) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    soup = BeautifulSoup(html or "", "html.parser")
    for card in soup.select('.fundCard[data-type="etfnet"]'):
        code_node = card.select_one(".fundCard-code")
        card_id = _text(code_node.get_text(" ", strip=True) if code_node else None)
        if (card_id or "").upper() != normalized_id:
            continue
        rows = _card_rows(card)
        nav_values = next(
            (values for label, values in rows.items() if "預估淨值" in label),
            [],
        )
        price_values = next(
            (values for label, values in rows.items() if "最新市價" in label),
            [],
        )
        premium_values = next(
            (values for label, values in rows.items() if "折溢" in label),
            [],
        )
        estimated_nav = _decimal(nav_values[0] if nav_values else None)
        if estimated_nav is None or estimated_nav <= 0:
            raise TaiwanEtfFuhHwaProviderError(
                f"Fuh Hwa ETF iNAV for stock_id={normalized_id} had no valid NAV."
            )
        timestamp_node = card.select_one(".fundCard-date")
        timestamp = _text(
            timestamp_node.get_text(" ", strip=True) if timestamp_node else None
        )
        if timestamp is None:
            raise TaiwanEtfFuhHwaProviderError(
                "Fuh Hwa ETF iNAV omitted its source timestamp."
            )
        try:
            observed_at = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S").replace(
                tzinfo=TAIWAN_TZ
            )
        except ValueError as exc:
            raise TaiwanEtfFuhHwaProviderError(
                f"Invalid Fuh Hwa ETF iNAV timestamp: {timestamp}"
            ) from exc
        market_price = _decimal(price_values[0] if price_values else None)
        if market_price is not None and market_price <= 0:
            market_price = None
        premium_discount_pct = _decimal(
            premium_values[0] if premium_values else None
        )
        if premium_discount_pct is None and market_price is not None:
            premium_discount_pct = (market_price - estimated_nav) / estimated_nav * 100
        name_node = card.select_one(".fundCard-fundName")
        return TaiwanEtfInavRecord(
            stock_id=normalized_id,
            fund_short_name=_text(
                name_node.get_text(" ", strip=True) if name_node else None
            ),
            investment_area=None,
            estimated_nav=estimated_nav,
            nav_change=None,
            market_price=market_price,
            price_change=None,
            premium_discount_pct=premium_discount_pct,
            observed_at=observed_at,
        )
    raise TaiwanEtfFuhHwaProviderError(
        f"Fuh Hwa ETF iNAV payload did not contain stock_id={normalized_id}."
    )


def fetch_fuh_hwa_etf_inav(
    stock_id: str,
    *,
    request_get: Callable[..., Any] = get,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    response = request_get(
        FUH_HWA_INAV_URL,
        provider=FUH_HWA_PROVIDER,
        resource="etf_intraday_estimated_nav",
        target=normalized_id,
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": FUH_HWA_INAV_URL,
        },
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_fuh_hwa_etf_inav_html(response.text, normalized_id)


__all__ = [
    "FUH_HWA_INAV_URL",
    "FUH_HWA_PROVIDER",
    "TaiwanEtfFuhHwaProviderError",
    "fetch_fuh_hwa_etf_inav",
    "parse_fuh_hwa_etf_inav_html",
]
