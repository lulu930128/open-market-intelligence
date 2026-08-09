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


FUBON_PROVIDER = "fubon_etfs"
FUBON_PCF_URL_TEMPLATE = (
    "https://websys.fsit.com.tw/FubonETF/Trade/Pcf.aspx?lan=EN&stkId={stock_id}"
)
FUBON_INAV_URL = "https://websys.fsit.com.tw/FubonETF/Trade/Estimate.aspx"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfFubonProviderError(RuntimeError):
    pass


def _text(value: object) -> str | None:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if not normalized or normalized.lower() in {"null", "none", "undefined", "-", "--"}:
        return None
    return normalized


def _decimal(value: object) -> Decimal | None:
    normalized = _text(value)
    if normalized is None:
        return None
    cleaned = (
        normalized.replace("NT$", "")
        .replace(",", "")
        .replace("%", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise TaiwanEtfFubonProviderError(
            f"Invalid Fubon ETF numeric value: {normalized}"
        ) from exc


def _integer(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed != parsed.to_integral_value():
        raise TaiwanEtfFubonProviderError(
            f"Invalid Fubon ETF integer value: {value}"
        )
    return int(parsed)


def _date(value: object, *, required: bool = False) -> date | None:
    normalized = _text(value)
    if normalized is None:
        if required:
            raise TaiwanEtfFubonProviderError("Fubon ETF payload omitted a required date.")
        return None
    try:
        return datetime.strptime(normalized, "%Y/%m/%d").date()
    except ValueError as exc:
        raise TaiwanEtfFubonProviderError(
            f"Invalid Fubon ETF date value: {normalized}"
        ) from exc


def _datetime(value: object) -> datetime:
    normalized = _text(value)
    if normalized is None:
        raise TaiwanEtfFubonProviderError(
            "Fubon ETF iNAV omitted its source timestamp."
        )
    match = re.search(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}", normalized)
    if match is None:
        raise TaiwanEtfFubonProviderError(
            f"Invalid Fubon ETF iNAV timestamp: {normalized}"
        )
    return datetime.strptime(match.group(0), "%Y/%m/%d %H:%M:%S").replace(
        tzinfo=TAIWAN_TZ
    )


def _decode_html(content: bytes) -> str:
    for encoding in ("utf-8-sig", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TaiwanEtfFubonProviderError(
        "Fubon ETF response encoding was not recognized."
    )


def _fund_label(value: str, stock_id: str) -> str | None:
    normalized = _text(value)
    if normalized is None:
        return None
    without_id = re.sub(rf"^{re.escape(stock_id)}\s*", "", normalized).strip()
    return _text(without_id.split("(", 1)[0])


def _pcf_effective_date(soup: BeautifulSoup) -> date:
    heading = next(
        (
            node
            for node in soup.find_all("h6")
            if _text(node.get_text(" ", strip=True)) == "Portfolio Composition File"
        ),
        None,
    )
    section = heading.find_parent("ul") if heading is not None else None
    if section is None:
        raise TaiwanEtfFubonProviderError(
            "Fubon ETF PCF effective-date section was not found."
        )
    for node in section.find_all("li"):
        value = _text(node.get_text(" ", strip=True))
        if value and re.fullmatch(r"\d{4}/\d{2}/\d{2}", value):
            parsed = _date(value, required=True)
            assert parsed is not None
            return parsed
    raise TaiwanEtfFubonProviderError("Fubon ETF PCF effective date was not found.")


def parse_fubon_etf_pcf_html(html: str, stock_id: str) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    soup = BeautifulSoup(html or "", "html.parser")
    stock_input = soup.select_one("#mainContent_subMainContent_hidStkId")
    payload_id = _text(stock_input.get("value")) if stock_input is not None else None
    if (payload_id or "").upper() != normalized_id:
        raise TaiwanEtfFubonProviderError(
            f"Fubon ETF PCF returned stock_id={payload_id or 'missing'} "
            f"for requested stock_id={normalized_id}."
        )

    reference_input = soup.select_one("#mainContent_subMainContent_sDate")
    reference_date = _date(
        reference_input.get("value") if reference_input is not None else None
    )
    values: dict[str, str] = {}
    for item in soup.select(".fund_box_2 li"):
        paragraphs = item.find_all("p")
        if len(paragraphs) < 2:
            continue
        label = _text(paragraphs[0].get_text(" ", strip=True))
        value = _text(paragraphs[1].get_text(" ", strip=True))
        if label and value:
            values[label] = value

    required_labels = {
        "Net Asset Value(NAV)",
        "Total Units Outstanding",
        "NAV Per Unit",
        "Creation/Redemption Unit",
        "Price per creation basket",
    }
    missing_labels = sorted(required_labels.difference(values))
    if missing_labels:
        raise TaiwanEtfFubonProviderError(
            "Fubon ETF PCF omitted required fields: " + ", ".join(missing_labels)
        )

    fund_heading = soup.select_one("h6.top.blue3.mb25")
    fund_label = _fund_label(
        fund_heading.get_text(" ", strip=True) if fund_heading is not None else "",
        normalized_id,
    )
    return TaiwanEtfPcfRecord(
        stock_id=normalized_id,
        fund_id=normalized_id,
        fund_name=fund_label,
        full_name=None,
        name_en=fund_label,
        reference_date=reference_date,
        effective_date=_pcf_effective_date(soup),
        total_net_assets=_decimal(values["Net Asset Value(NAV)"]),
        issued_units=_integer(values["Total Units Outstanding"]),
        unit_nav=_decimal(values["NAV Per Unit"]),
        creation_unit=_integer(values["Creation/Redemption Unit"]),
        estimated_creation_value=_decimal(values["Price per creation basket"]),
        estimated_cash_component=_decimal(values.get("Cash Component Per Basket")),
        unit_change=_integer(values.get("Net Unit Change")),
        actual_cash_component=None,
        redemption_method="unknown",
        source_updated_at=None,
        components=(),
    )


def _card_name(card: Any) -> tuple[str, str | None] | None:
    name_node = card.select_one(".card_name")
    text = _text(name_node.get_text(" ", strip=True) if name_node is not None else None)
    if text is None:
        return None
    match = re.match(r"^(?P<stock_id>\d{4,6}[A-Z]?)\s+(?P<name>.+)$", text)
    if match is None:
        return None
    stock_id = match.group("stock_id").upper()
    return stock_id, _fund_label(match.group("name"), stock_id)


def _row_value(row: Any, selector: str) -> Decimal | None:
    node = row.select_one(selector)
    return _decimal(node.get_text(" ", strip=True) if node is not None else None)


def _row_change(row: Any) -> Decimal | None:
    cell = row.select_one("td.card_price4")
    if cell is None:
        return None
    for node in cell.find_all("span"):
        value = _text(node.get_text(" ", strip=True))
        if value is None or value == "漲跌" or "%" in value:
            continue
        try:
            return _decimal(value)
        except TaiwanEtfFubonProviderError:
            continue
    return None


def parse_fubon_etf_inav_html(html: str, stock_id: str) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    soup = BeautifulSoup(html or "", "html.parser")
    for card in soup.select("div.con_c1_cardbox1"):
        parsed_name = _card_name(card)
        if parsed_name is None or parsed_name[0] != normalized_id:
            continue
        rows: dict[str, Any] = {}
        for row in card.select("table.w674 > tr"):
            label = row.select_one("td.card_price")
            label_text = _text(label.get_text(" ", strip=True) if label is not None else None)
            if label_text:
                rows[label_text] = row
        nav_row = rows.get("淨值")
        price_row = rows.get("市價")
        if nav_row is None or price_row is None:
            raise TaiwanEtfFubonProviderError(
                f"Fubon ETF iNAV record for stock_id={normalized_id} omitted price rows."
            )
        estimated_nav = _row_value(nav_row, "td.card_price3 span.spacer12")
        if estimated_nav is None or estimated_nav <= 0:
            raise TaiwanEtfFubonProviderError(
                f"Fubon ETF iNAV record for stock_id={normalized_id} had no valid NAV."
            )
        market_price = _row_value(price_row, "td.card_price3 span.spacer12")
        if market_price is not None and market_price <= 0:
            market_price = None
        premium_node = card.select_one("div.card_price5 span")
        observed_node = card.select_one("div.card_time") or card.select_one(
            "div.card_time_m"
        )
        return TaiwanEtfInavRecord(
            stock_id=normalized_id,
            fund_short_name=parsed_name[1],
            investment_area=None,
            estimated_nav=estimated_nav,
            nav_change=_row_change(nav_row),
            market_price=market_price,
            price_change=_row_change(price_row),
            premium_discount_pct=_decimal(
                premium_node.get_text(" ", strip=True)
                if premium_node is not None
                else None
            ),
            observed_at=_datetime(
                observed_node.get_text(" ", strip=True)
                if observed_node is not None
                else None
            ),
        )
    raise TaiwanEtfFubonProviderError(
        f"Fubon ETF iNAV payload did not contain stock_id={normalized_id}."
    )


def fetch_fubon_etf_pcf(
    stock_id: str,
    *,
    target_date: date | None = None,
    request_get: Callable[..., Any] = get,
) -> TaiwanEtfPcfRecord:
    normalized_id = stock_id.strip().upper()
    source_url = FUBON_PCF_URL_TEMPLATE.format(stock_id=normalized_id)
    response = request_get(
        source_url,
        provider=FUBON_PROVIDER,
        resource="etf_pcf",
        target=normalized_id,
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": FUBON_INAV_URL,
        },
    )
    response.raise_for_status()
    record = parse_fubon_etf_pcf_html(_decode_html(response.content), normalized_id)
    if target_date is not None and record.effective_date != target_date:
        raise TaiwanEtfFubonProviderError(
            f"Fubon ETF PCF returned effective_date={record.effective_date.isoformat()} "
            f"for target_date={target_date.isoformat()}."
        )
    return record


def fetch_fubon_etf_inav(
    stock_id: str,
    *,
    request_get: Callable[..., Any] = get,
) -> TaiwanEtfInavRecord:
    normalized_id = stock_id.strip().upper()
    response = request_get(
        FUBON_INAV_URL,
        provider=FUBON_PROVIDER,
        resource="etf_intraday_estimated_nav",
        target=normalized_id,
        timeout_seconds=20,
        headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": FUBON_INAV_URL,
        },
    )
    response.raise_for_status()
    return parse_fubon_etf_inav_html(_decode_html(response.content), normalized_id)


__all__ = [
    "FUBON_INAV_URL",
    "FUBON_PCF_URL_TEMPLATE",
    "FUBON_PROVIDER",
    "TaiwanEtfFubonProviderError",
    "fetch_fubon_etf_inav",
    "fetch_fubon_etf_pcf",
    "parse_fubon_etf_inav_html",
    "parse_fubon_etf_pcf_html",
]
