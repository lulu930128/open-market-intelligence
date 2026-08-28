from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import requests
from bs4 import BeautifulSoup
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    MarginTradingDaily,
    MarketChipDaily,
    SourceRegistry,
)
from app.market.indices import ensure_market_index_daily_stat_coverage
from app.market.official_index_platform import read_taiwan_official_index
from app.market_data.contracts import MarketIndexObservation
from app.market.providers import http_get, http_post
from app.market.trading_calendar import latest_released_trading_day
from app.parsers.twse_common import (
    list_row_to_dict,
    normalize_text,
    parse_date,
    parse_float,
    parse_int,
    sum_nullable,
)


TWSE_BFI82U_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TWSE_MARGIN_TRADING_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TAIFEX_FUT_CONTRACTS_DATE_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
TAIFEX_PUT_CALL_RATIO_URL = "https://www.taifex.com.tw/cht/3/pcRatio"
TPEX_3INSTI_SUMMARY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary"
TPEX_MARGIN_BALANCE_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
MARKET_FUTURES_RELEASE_TIME = time(hour=15, minute=0)
MARKET_INSTITUTIONAL_RELEASE_TIME = time(hour=15, minute=10)
MARKET_CHIP_RELEASE_TIME = MARKET_INSTITUTIONAL_RELEASE_TIME
MARKET_MARGIN_RELEASE_TIME = time(hour=21, minute=10)
HTTP_TIMEOUT_SECONDS = 20
REQUEST_HEADERS = {
    "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
    "Accept": "application/json,text/html,text/plain,*/*",
}
SUPPORTED_MARKET_CHIP_INDEX_IDS = {"TAIEX", "TPEX"}
MARGIN_DAILY_SOURCE_NAMES = {
    "TAIEX": "TWSE Margin Trading MI_MARGN",
    "TPEX": "TPEx Margin Trading Balance",
}
MarketChipProgressCallback = Callable[[int | None, int | None, str | None], None]


class MarketChipFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpPayload:
    url: str
    status_code: int
    content_type: str | None
    payload: Any


def expected_market_chip_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=MARKET_CHIP_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def expected_market_margin_chip_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=MARKET_MARGIN_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def normalize_market_chip_index_ids(index_ids: Iterable[str] | None = None) -> list[str]:
    if index_ids is None:
        return sorted(SUPPORTED_MARKET_CHIP_INDEX_IDS)

    normalized: list[str] = []
    seen: set[str] = set()
    unsupported: list[str] = []

    for raw_index_id in index_ids:
        index_id = str(raw_index_id).strip().upper()

        if not index_id:
            continue

        if index_id not in SUPPORTED_MARKET_CHIP_INDEX_IDS:
            unsupported.append(index_id)
            continue

        if index_id in seen:
            continue

        normalized.append(index_id)
        seen.add(index_id)

    if unsupported:
        raise ValueError(
            "Unsupported market chip index_id: " + ", ".join(sorted(set(unsupported)))
        )

    return normalized or sorted(SUPPORTED_MARKET_CHIP_INDEX_IDS)


def _fetch_json(url: str, *, params: dict[str, Any] | None = None) -> HttpPayload:
    try:
        response = http_get(
            url,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        payload = response.json()
    except requests.RequestException as exc:
        raise MarketChipFetchError(f"Market chip JSON source unavailable: {exc}") from exc
    except ValueError as exc:
        raise MarketChipFetchError("Market chip JSON source returned invalid JSON.") from exc

    return HttpPayload(
        url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        payload=payload,
    )


def _fetch_text(url: str, *, params: dict[str, Any] | None = None) -> HttpPayload:
    try:
        response = http_get(
            url,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
    except requests.RequestException as exc:
        raise MarketChipFetchError(f"Market chip HTML source unavailable: {exc}") from exc

    return HttpPayload(
        url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        payload=response.text,
    )


def _post_text(url: str, *, data: dict[str, Any]) -> HttpPayload:
    try:
        response = http_post(
            url,
            data=data,
            headers=REQUEST_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
    except requests.RequestException as exc:
        raise MarketChipFetchError(f"Market chip HTML source unavailable: {exc}") from exc

    return HttpPayload(
        url=response.url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        payload=response.text,
    )


def _format_twse_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _format_taifex_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")


def _format_roc_slash_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def _as_signed_int(value: int | None) -> int | None:
    return value if value is None else int(value)


def _first_present(row: dict[str, Any], keys: Iterable[str]) -> Any:
    normalized = {normalize_text(key) or key: value for key, value in row.items()}

    for key in keys:
        normalized_key = normalize_text(key) or key
        value = normalized.get(normalized_key)
        if normalize_text(value) is not None:
            return value

    return None


def _row_to_dict(fields: list[Any], row: Any) -> dict[str, Any] | None:
    if isinstance(row, dict):
        return {normalize_text(str(key)) or str(key): value for key, value in row.items()}

    if isinstance(row, list):
        return list_row_to_dict(fields, row)

    return None


def _institution_category(name: str | None) -> str | None:
    text = normalize_text(name)
    if not text:
        return None

    compact = text.replace(" ", "")

    if (
        ("三大法人" in compact and "合計" in compact)
        or compact in {"合計", "總計", "三大法人"}
    ):
        return "total"
    if "外資自營商" in compact and "不含" not in compact:
        return "foreign_dealer"
    if "外資" in compact or "陸資" in compact:
        return "foreign_investor"
    if "投信" in compact:
        return "investment_trust"
    if "自營商" in compact and "避險" in compact:
        return "dealer_hedge"
    if "自營商" in compact and "自行" in compact:
        return "dealer_self"
    if "自營商" in compact:
        return "dealer"

    return None


def _net_value_from_row(row: dict[str, Any]) -> int | None:
    return parse_int(
        _first_present(
            row,
            (
                "買賣超金額",
                "買賣差額",
                "買賣超",
                "NetAmount",
                "Net",
                "Difference",
            ),
        )
    )


def _delta_units(
    *,
    current: int | None,
    previous: int | None,
    multiplier: int = 1,
) -> int | None:
    if current is None or previous is None:
        return None
    return (current - previous) * multiplier


def _payload_date(payload: Any, fallback: date) -> date:
    if isinstance(payload, dict):
        for key in ("date", "Date", "trade_date", "title", "stat"):
            parsed = parse_date(payload.get(key))
            if parsed is not None:
                return parsed

    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            for key in ("Date", "date", "資料日期"):
                parsed = parse_date(row.get(key))
                if parsed is not None:
                    return parsed

    return fallback


def _first_table_with_rows(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        tables = payload.get("tables") or payload.get("Tables") or []
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, dict):
                    continue
                rows = table.get("data") or table.get("Data")
                fields = table.get("fields") or table.get("Field")
                if isinstance(rows, list) and rows and isinstance(fields, list):
                    return table

        rows = payload.get("data") or payload.get("Data")
        fields = payload.get("fields") or payload.get("Field")
        if isinstance(rows, list) and rows and isinstance(fields, list):
            return payload

    return None


def _field_index(fields: list[Any], names: Iterable[str], fallback: int) -> int:
    normalized_fields = [normalize_text(field) or str(field) for field in fields]
    normalized_names = {normalize_text(name) or name for name in names}

    for index, field in enumerate(normalized_fields):
        if field in normalized_names:
            return index

    return fallback


def _is_margin_released_for_trade_date(trade_date: date) -> bool:
    return trade_date <= expected_market_margin_chip_date()


def parse_institutional_amount_summary(payload: Any, *, fallback_trade_date: date) -> dict[str, Any]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("Data") or []
        fields = payload.get("fields") or payload.get("Field") or []
    elif isinstance(payload, list):
        rows = payload
        fields = []
    else:
        rows = []
        fields = []

    values: dict[str, int | None] = {
        "foreign_investor_net_value": None,
        "foreign_dealer_net_value": None,
        "investment_trust_net_value": None,
        "dealer_self_net_value": None,
        "dealer_hedge_net_value": None,
        "dealer_net_value": None,
        "total_institutional_net_value": None,
    }

    for row in rows:
        row_dict = _row_to_dict(fields, row)
        if row_dict is None:
            continue

        name = _first_present(
            row_dict,
            (
                "單位名稱",
                "類別",
                "法人名稱",
                "InstitutionalInvestors",
                "institutional_investors",
                "Investor",
                "name",
            ),
        )
        category = _institution_category(normalize_text(name))
        if category is None:
            continue

        key = (
            "total_institutional_net_value"
            if category == "total"
            else f"{category}_net_value"
        )
        values[key] = _net_value_from_row(row_dict)

    foreign_investor = values.get("foreign_investor_net_value")
    foreign_dealer = values.get("foreign_dealer_net_value")
    dealer_self = values.get("dealer_self_net_value")
    dealer_hedge = values.get("dealer_hedge_net_value")
    dealer_direct = values.get("dealer_net_value")

    foreign_total = sum_nullable(foreign_investor, foreign_dealer)
    if foreign_total is not None:
        values["foreign_investor_net_value"] = foreign_total

    dealer_total = sum_nullable(dealer_self, dealer_hedge)
    if dealer_total is not None:
        values["dealer_net_value"] = dealer_total
    elif dealer_direct is not None:
        values["dealer_net_value"] = dealer_direct

    if values.get("total_institutional_net_value") is None:
        values["total_institutional_net_value"] = sum_nullable(
            values.get("foreign_investor_net_value"),
            values.get("investment_trust_net_value"),
            values.get("dealer_net_value"),
        )

    return {
        "trade_date": _payload_date(payload, fallback_trade_date),
        **values,
    }


def parse_twse_margin_summary(payload: Any, *, fallback_trade_date: date) -> dict[str, Any]:
    table = _first_table_with_rows(payload)
    if table is None:
        raise ValueError("TWSE margin summary payload does not contain a data table.")

    rows = table.get("data") or table.get("Data") or []
    values: dict[str, int | None] = {
        "margin_balance_change_value": None,
        "margin_balance_change_shares": None,
        "short_balance_change_shares": None,
    }

    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue

        label = normalize_text(row[0]) or ""
        previous_balance = parse_int(row[4])
        today_balance = parse_int(row[5])

        if "融資" in label and "金額" in label:
            values["margin_balance_change_value"] = _delta_units(
                current=today_balance,
                previous=previous_balance,
                multiplier=1000,
            )
        elif "融資" in label:
            values["margin_balance_change_shares"] = _delta_units(
                current=today_balance,
                previous=previous_balance,
                multiplier=1000,
            )
        elif "融券" in label:
            values["short_balance_change_shares"] = _delta_units(
                current=today_balance,
                previous=previous_balance,
                multiplier=1000,
            )

    return {
        "trade_date": _payload_date(payload, fallback_trade_date),
        **values,
    }


def parse_tpex_margin_summary(payload: Any, *, fallback_trade_date: date) -> dict[str, Any]:
    table = _first_table_with_rows(payload)
    if table is None:
        raise ValueError("TPEx margin payload does not contain a data table.")

    rows = table.get("data") or table.get("Data") or []
    fields = table.get("fields") or table.get("Field") or []
    margin_previous_index = _field_index(fields, ("前資餘額(張)", "前資餘額"), 2)
    margin_today_index = _field_index(fields, ("資餘額", "今日資餘額"), 6)
    short_previous_index = _field_index(fields, ("前券餘額(張)", "前券餘額"), 10)
    short_today_index = _field_index(fields, ("券餘額", "今日券餘額"), 14)
    margin_previous_total = 0
    margin_today_total = 0
    short_previous_total = 0
    short_today_total = 0
    parsed_count = 0

    for row in rows:
        if not isinstance(row, list):
            continue

        margin_previous = parse_int(
            row[margin_previous_index] if margin_previous_index < len(row) else None
        )
        margin_today = parse_int(
            row[margin_today_index] if margin_today_index < len(row) else None
        )
        short_previous = parse_int(
            row[short_previous_index] if short_previous_index < len(row) else None
        )
        short_today = parse_int(
            row[short_today_index] if short_today_index < len(row) else None
        )

        if (
            margin_previous is None
            or margin_today is None
            or short_previous is None
            or short_today is None
        ):
            continue

        margin_previous_total += margin_previous
        margin_today_total += margin_today
        short_previous_total += short_previous
        short_today_total += short_today
        parsed_count += 1

    if parsed_count == 0:
        raise ValueError("TPEx margin payload did not contain usable balance rows.")

    return {
        "trade_date": _payload_date(payload, fallback_trade_date),
        "margin_balance_change_value": None,
        "margin_balance_change_shares": (margin_today_total - margin_previous_total) * 1000,
        "short_balance_change_shares": (short_today_total - short_previous_total) * 1000,
    }


def _html_cells(row) -> list[str]:
    return [
        normalize_text(cell.get_text(" ", strip=True)) or ""
        for cell in row.find_all(["td", "th"])
    ]


def _values_to_futures_row(values: list[str]) -> dict[str, int | None]:
    if len(values) < 12:
        return {}

    return {
        "trading_long_lots": parse_int(values[0]),
        "trading_long_value": parse_int(values[1]),
        "trading_short_lots": parse_int(values[2]),
        "trading_short_value": parse_int(values[3]),
        "trading_net_lots": parse_int(values[4]),
        "trading_net_value": parse_int(values[5]),
        "open_interest_long_lots": parse_int(values[6]),
        "open_interest_long_value": parse_int(values[7]),
        "open_interest_short_lots": parse_int(values[8]),
        "open_interest_short_value": parse_int(values[9]),
        "open_interest_net_lots": parse_int(values[10]),
        "open_interest_net_value": parse_int(values[11]),
    }


def parse_taifex_futures_institutional_html(raw_html: str) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html or "", "lxml")
    identity_names = {"自營商", "投信", "外資"}
    current_product: str | None = None
    rows: dict[str, dict[str, dict[str, int | None]]] = {}
    trade_date: date | None = None

    page_text = soup.get_text(" ", strip=True)
    date_text_match = re.search(r"\d{3,4}[/-]\d{1,2}[/-]\d{1,2}", page_text)
    date_match = parse_date(date_text_match.group(0)) if date_text_match else None
    if date_match is not None:
        trade_date = date_match

    for table_row in soup.find_all("tr"):
        cells = [cell for cell in _html_cells(table_row) if cell]
        if not cells:
            continue

        product: str | None = None
        identity: str | None = None
        values: list[str] = []

        if len(cells) >= 15 and parse_int(cells[0]) is not None:
            product = cells[1]
            identity = cells[2]
            values = cells[3:]
        elif len(cells) >= 13 and cells[0] in identity_names:
            product = current_product
            identity = cells[0]
            values = cells[1:]

        if not product or identity not in identity_names:
            continue

        current_product = product
        parsed = _values_to_futures_row(values)
        if not parsed:
            continue

        rows.setdefault(product, {})[identity] = parsed

    return {
        "trade_date": trade_date,
        "products": rows,
    }


def parse_taifex_put_call_ratio_html(
    raw_html: str,
    *,
    target_trade_date: date | None = None,
) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html or "", "lxml")
    parsed_rows: list[dict[str, Any]] = []

    for table_row in soup.find_all("tr"):
        cells = [cell for cell in _html_cells(table_row) if cell]
        if len(cells) < 7:
            continue

        trade_date = parse_date(cells[0])
        if trade_date is None:
            continue

        values = {
            "trade_date": trade_date,
            "put_volume": parse_int(cells[1]),
            "call_volume": parse_int(cells[2]),
            "put_call_volume_ratio_pct": parse_float(cells[3]),
            "put_open_interest": parse_int(cells[4]),
            "call_open_interest": parse_int(cells[5]),
            "put_call_open_interest_ratio_pct": parse_float(cells[6]),
        }
        if any(values[field] is None for field in values if field != "trade_date"):
            continue
        parsed_rows.append(values)

    if target_trade_date is not None:
        for row in parsed_rows:
            if row["trade_date"] == target_trade_date:
                return row

    if parsed_rows:
        return max(parsed_rows, key=lambda row: row["trade_date"])

    raise ValueError("TAIFEX Put/Call Ratio page did not contain a usable data row.")


def _required_sum(values: Iterable[int | None]) -> int | None:
    items = list(values)
    if not items or any(value is None for value in items):
        return None
    return sum(int(value) for value in items)


def _open_interest_net(
    products: dict[str, dict[str, dict[str, int | None]]],
    product_name: str,
    identity: str,
) -> int | None:
    return (
        products.get(product_name, {})
        .get(identity, {})
        .get("open_interest_net_lots")
    )


def extract_index_futures_position_summary(payload: dict[str, Any]) -> dict[str, Any]:
    products = payload.get("products") if isinstance(payload, dict) else {}
    if not isinstance(products, dict):
        products = {}

    foreign_tx = _open_interest_net(products, "臺股期貨", "外資")
    mini_institutional_net = _required_sum(
        (
            _open_interest_net(products, "小型臺指期貨", "自營商"),
            _open_interest_net(products, "小型臺指期貨", "投信"),
            _open_interest_net(products, "小型臺指期貨", "外資"),
        )
    )

    retail_mini = None
    if mini_institutional_net is not None:
        retail_mini = -mini_institutional_net

    return {
        "trade_date": payload.get("trade_date"),
        "foreign_futures_net_oi": _as_signed_int(foreign_tx),
        "retail_futures_net_oi": _as_signed_int(retail_mini),
    }


def _price_change_pct(close_value: float | None, price_change: float | None) -> float | None:
    if close_value is None or price_change is None:
        return None

    previous_close = close_value - price_change
    if previous_close == 0:
        return None

    return (price_change / previous_close) * 100


def _latest_market_index_stat(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
) -> MarketIndexObservation | None:
    return read_taiwan_official_index(
        db,
        index_id=index_id,
        trade_date=trade_date,
    ).resolved.market_index


def _previous_market_chip(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
) -> MarketChipDaily | None:
    return (
        db.query(MarketChipDaily)
        .filter(MarketChipDaily.index_id == index_id)
        .filter(MarketChipDaily.trade_date < trade_date)
        .order_by(MarketChipDaily.trade_date.desc())
        .first()
    )


def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _source_ref(
    *,
    name: str,
    url: str,
    reliability_level: str = "official",
    status_code: int | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "url": url,
        "reliability_level": reliability_level,
        "status_code": status_code,
        "content_type": content_type,
    }


def _fetch_taiwan_market_chip_sources(
    *,
    index_id: str,
    trade_date: date,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    values: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if index_id == "TAIEX":
        try:
            twse_result = _fetch_json(
                TWSE_BFI82U_URL,
                params={
                    "response": "json",
                    "dayDate": _format_twse_date(trade_date),
                    "type": "day",
                },
            )
            institutional = parse_institutional_amount_summary(
                twse_result.payload,
                fallback_trade_date=trade_date,
            )
            values.update(
                {
                    key: institutional.get(key)
                    for key in (
                        "total_institutional_net_value",
                        "foreign_investor_net_value",
                        "investment_trust_net_value",
                        "dealer_net_value",
                        "dealer_self_net_value",
                        "dealer_hedge_net_value",
                    )
                }
            )
            sources.append(
                _source_ref(
                    name="TWSE BFI82U institutional trading amount",
                    url=twse_result.url,
                    status_code=twse_result.status_code,
                    content_type=twse_result.content_type,
                )
            )
        except (MarketChipFetchError, ValueError) as exc:
            warnings.append(
                {
                    "source": "TWSE BFI82U institutional trading amount",
                    "message": str(exc),
                }
            )

        try:
            taifex_result = _fetch_text(
                TAIFEX_FUT_CONTRACTS_DATE_URL,
                params={
                    "doQuery": "1",
                    "queryDate": _format_taifex_date(trade_date),
                    "queryType": "1",
                },
            )
            futures_payload = parse_taifex_futures_institutional_html(
                str(taifex_result.payload)
            )
            futures_summary = extract_index_futures_position_summary(futures_payload)
            futures_trade_date = futures_summary.pop("trade_date", None)
            if futures_trade_date is not None and futures_trade_date != trade_date:
                warnings.append(
                    {
                        "source": "TAIFEX futures institutional open interest",
                        "message": (
                            f"TAIFEX returned trade_date={futures_trade_date}; "
                            f"requested {trade_date}."
                        ),
                    }
                )
            values.update(futures_summary)
            sources.append(
                _source_ref(
                    name="TAIFEX futures institutional open interest",
                    url=taifex_result.url,
                    status_code=taifex_result.status_code,
                    content_type=taifex_result.content_type,
                )
            )
        except (MarketChipFetchError, ValueError) as exc:
            warnings.append(
                {
                    "source": "TAIFEX futures institutional open interest",
                    "message": str(exc),
                }
            )

        try:
            formatted_trade_date = _format_taifex_date(trade_date)
            put_call_result = _post_text(
                TAIFEX_PUT_CALL_RATIO_URL,
                data={
                    "queryStartDate": formatted_trade_date,
                    "queryEndDate": formatted_trade_date,
                },
            )
            put_call_summary = parse_taifex_put_call_ratio_html(
                str(put_call_result.payload),
                target_trade_date=trade_date,
            )
            put_call_trade_date = put_call_summary.pop("trade_date", None)
            if put_call_trade_date != trade_date:
                raise ValueError(
                    f"TAIFEX returned trade_date={put_call_trade_date}; requested {trade_date}."
                )
            values.update(put_call_summary)
            sources.append(
                _source_ref(
                    name="TAIFEX Put/Call Ratio",
                    url=put_call_result.url,
                    status_code=put_call_result.status_code,
                    content_type=put_call_result.content_type,
                )
            )
        except (MarketChipFetchError, ValueError) as exc:
            warnings.append(
                {
                    "source": "TAIFEX Put/Call Ratio",
                    "message": str(exc),
                }
            )

        if _is_margin_released_for_trade_date(trade_date):
            try:
                margin_result = _fetch_json(
                    TWSE_MARGIN_TRADING_URL,
                    params={
                        "response": "json",
                        "date": _format_twse_date(trade_date),
                        "selectType": "MS",
                    },
                )
                margin_summary = parse_twse_margin_summary(
                    margin_result.payload,
                    fallback_trade_date=trade_date,
                )
                margin_trade_date = margin_summary.pop("trade_date", None)
                if margin_trade_date is not None and margin_trade_date != trade_date:
                    warnings.append(
                        {
                            "source": "TWSE MI_MARGN margin summary",
                            "message": (
                                f"TWSE returned trade_date={margin_trade_date}; "
                                f"requested {trade_date}."
                            ),
                        }
                    )
                values.update(margin_summary)
                sources.append(
                    _source_ref(
                        name="TWSE MI_MARGN margin summary",
                        url=margin_result.url,
                        status_code=margin_result.status_code,
                        content_type=margin_result.content_type,
                    )
                )
            except (MarketChipFetchError, ValueError) as exc:
                warnings.append(
                    {
                        "source": "TWSE MI_MARGN margin summary",
                        "message": str(exc),
                    }
                )
    elif index_id == "TPEX":
        tpex_result = _fetch_json(TPEX_3INSTI_SUMMARY_URL)
        institutional = parse_institutional_amount_summary(
            tpex_result.payload,
            fallback_trade_date=trade_date,
        )
        source_trade_date = institutional.get("trade_date")
        if source_trade_date != trade_date:
            warnings.append(
                {
                    "source": "TPEX tpex_3insti_summary",
                    "message": (
                        f"TPEx OpenAPI returned trade_date={source_trade_date}; "
                        f"requested {trade_date}."
                    ),
                }
            )
        values.update(
            {
                key: institutional.get(key)
                for key in (
                    "total_institutional_net_value",
                    "foreign_investor_net_value",
                    "investment_trust_net_value",
                    "dealer_net_value",
                    "dealer_self_net_value",
                    "dealer_hedge_net_value",
                )
            }
        )
        sources.append(
            _source_ref(
                name="TPEx OpenAPI tpex_3insti_summary",
                url=tpex_result.url,
                status_code=tpex_result.status_code,
                content_type=tpex_result.content_type,
            )
        )

        if _is_margin_released_for_trade_date(trade_date):
            try:
                margin_result = _fetch_json(
                    TPEX_MARGIN_BALANCE_URL,
                    params={
                        "date": _format_roc_slash_date(trade_date),
                        "response": "json",
                    },
                )
                margin_summary = parse_tpex_margin_summary(
                    margin_result.payload,
                    fallback_trade_date=trade_date,
                )
                margin_trade_date = margin_summary.pop("trade_date", None)
                if margin_trade_date is not None and margin_trade_date != trade_date:
                    warnings.append(
                        {
                            "source": "TPEx margin balance",
                            "message": (
                                f"TPEx returned trade_date={margin_trade_date}; "
                                f"requested {trade_date}."
                            ),
                        }
                    )
                values.update(margin_summary)
                sources.append(
                    _source_ref(
                        name="TPEx margin balance",
                        url=margin_result.url,
                        status_code=margin_result.status_code,
                        content_type=margin_result.content_type,
                    )
                )
            except (MarketChipFetchError, ValueError) as exc:
                warnings.append(
                    {
                        "source": "TPEx margin balance",
                        "message": str(exc),
                    }
                )
    else:
        raise ValueError(f"Unsupported market chip index_id: {index_id}")

    return values, sources, warnings


def _non_empty_payload(values: dict[str, Any]) -> bool:
    return any(
        values.get(key) is not None
        for key in (
            "foreign_futures_net_oi",
            "retail_futures_net_oi",
            "put_call_volume_ratio_pct",
            "put_call_open_interest_ratio_pct",
            "total_institutional_net_value",
            "foreign_investor_net_value",
            "investment_trust_net_value",
            "dealer_net_value",
        )
    )


def fetch_market_chip_daily(
    db: Session,
    *,
    index_id: str = "TAIEX",
    trade_date: date,
) -> dict[str, Any]:
    normalized_index_id = index_id.upper()
    if normalized_index_id not in SUPPORTED_MARKET_CHIP_INDEX_IDS:
        raise ValueError(f"Unsupported market chip index_id: {index_id}")

    market = "TPEX" if normalized_index_id == "TPEX" else "TWSE"
    warnings: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []

    try:
        ensure_market_index_daily_stat_coverage(
            db=db,
            index_id=normalized_index_id,
            market=market,
            from_date=trade_date,
            to_date=trade_date,
        )
    except Exception as exc:
        warnings.append(
            {
                "source": "market_index_daily_stat",
                "message": f"Index daily statistics refresh failed: {exc}",
            }
        )

    index_stat = _latest_market_index_stat(
        db=db,
        index_id=normalized_index_id,
        trade_date=trade_date,
    )
    if index_stat is not None:
        values.update(
            {
                "close_value": float(index_stat.close_value),
                "price_change": index_stat.price_change,
                "price_change_pct": _price_change_pct(
                    float(index_stat.close_value),
                    float(index_stat.price_change),
                ),
                "trade_value": (
                    int(index_stat.trade_value)
                    if index_stat.trade_value is not None
                    else None
                ),
            }
        )
        sources.append(
            _source_ref(
                name=index_stat.lineage.source,
                url="canonical://tw.market_index.daily",
            )
        )

    source_values, source_refs, source_warnings = _fetch_taiwan_market_chip_sources(
        index_id=normalized_index_id,
        trade_date=trade_date,
    )
    values.update(source_values)
    sources.extend(source_refs)
    warnings.extend(source_warnings)

    if not _non_empty_payload(values):
        raise MarketChipFetchError(
            f"No market chip data was parsed for index_id={normalized_index_id} trade_date={trade_date}."
        )

    return {
        "index_id": normalized_index_id,
        "market": market,
        "trade_date": trade_date,
        **values,
        "source_details": {
            "sources": sources,
            "warnings": warnings,
            "derived_fields": [
                {
                    "field": "retail_futures_net_oi",
                    "method": "negative of TAIFEX mini TAIEX futures institutional open-interest net lots",
                    "reliability_level": "derived",
                },
                {
                    "field": "foreign_futures_net_oi_change",
                    "method": "current foreign_futures_net_oi minus previous stored trading day",
                    "reliability_level": "derived",
                },
                {
                    "field": "retail_futures_net_oi_change",
                    "method": "current retail_futures_net_oi minus previous stored trading day",
                    "reliability_level": "derived",
                },
                {
                    "field": "margin_balance_change_value",
                    "method": (
                        "TWSE MI_MARGN margin amount current balance minus previous "
                        "balance, converted from thousand TWD to TWD"
                    ),
                    "reliability_level": "official_derived",
                },
                {
                    "field": "margin_balance_change_shares",
                    "method": "official margin balance current units minus previous units, converted to shares",
                    "reliability_level": "official_derived",
                },
                {
                    "field": "short_balance_change_shares",
                    "method": "official short balance current units minus previous units, converted to shares",
                    "reliability_level": "official_derived",
                },
            ],
        },
    }


def _source_details_json(source_details: dict[str, Any] | None) -> str | None:
    if not source_details:
        return None
    return json.dumps(source_details, ensure_ascii=False, sort_keys=True)


def _load_source_details(row: MarketChipDaily) -> dict[str, Any] | None:
    if not row.source_details_json:
        return None
    try:
        payload = json.loads(row.source_details_json)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def upsert_market_chip_daily(
    db: Session,
    *,
    payload: dict[str, Any],
) -> MarketChipDaily:
    index_id = str(payload["index_id"]).upper()
    trade_date = payload["trade_date"]
    previous = _previous_market_chip(
        db=db,
        index_id=index_id,
        trade_date=trade_date,
    )

    values = {
        "market": payload["market"],
        "close_value": payload.get("close_value"),
        "price_change": payload.get("price_change"),
        "price_change_pct": payload.get("price_change_pct"),
        "trade_value": payload.get("trade_value"),
        "foreign_futures_net_oi": payload.get("foreign_futures_net_oi"),
        "foreign_futures_net_oi_change": _delta(
            payload.get("foreign_futures_net_oi"),
            None if previous is None else previous.foreign_futures_net_oi,
        ),
        "retail_futures_net_oi": payload.get("retail_futures_net_oi"),
        "retail_futures_net_oi_change": _delta(
            payload.get("retail_futures_net_oi"),
            None if previous is None else previous.retail_futures_net_oi,
        ),
        "put_volume": payload.get("put_volume"),
        "call_volume": payload.get("call_volume"),
        "put_call_volume_ratio_pct": payload.get("put_call_volume_ratio_pct"),
        "put_open_interest": payload.get("put_open_interest"),
        "call_open_interest": payload.get("call_open_interest"),
        "put_call_open_interest_ratio_pct": payload.get(
            "put_call_open_interest_ratio_pct"
        ),
        "total_institutional_net_value": payload.get("total_institutional_net_value"),
        "foreign_investor_net_value": payload.get("foreign_investor_net_value"),
        "investment_trust_net_value": payload.get("investment_trust_net_value"),
        "dealer_net_value": payload.get("dealer_net_value"),
        "dealer_self_net_value": payload.get("dealer_self_net_value"),
        "dealer_hedge_net_value": payload.get("dealer_hedge_net_value"),
        "government_bank_net_value": payload.get("government_bank_net_value"),
        "margin_balance_change_value": payload.get("margin_balance_change_value"),
        "margin_balance_change_shares": payload.get("margin_balance_change_shares"),
        "short_balance_change_shares": payload.get("short_balance_change_shares"),
        "source_grade": "mixed",
        "source_details_json": _source_details_json(payload.get("source_details")),
    }

    existing = (
        db.query(MarketChipDaily)
        .filter(MarketChipDaily.index_id == index_id)
        .filter(MarketChipDaily.trade_date == trade_date)
        .first()
    )

    if existing is None:
        existing = MarketChipDaily(
            index_id=index_id,
            trade_date=trade_date,
            **values,
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)

    db.commit()
    db.refresh(existing)
    return existing


def _margin_fields_expected_for_index(index_id: str) -> tuple[str, ...]:
    normalized_index_id = index_id.upper()
    if normalized_index_id == "TPEX":
        return ("margin_balance_change_shares", "short_balance_change_shares")
    return (
        "margin_balance_change_value",
        "margin_balance_change_shares",
        "short_balance_change_shares",
    )


def _margin_values_from_row(row: MarketChipDaily) -> dict[str, int | None]:
    return {
        "margin_balance_change_value": row.margin_balance_change_value,
        "margin_balance_change_shares": row.margin_balance_change_shares,
        "short_balance_change_shares": row.short_balance_change_shares,
    }


def _margin_source_from_row(row: MarketChipDaily) -> str:
    source_details = _load_source_details(row) or {}
    sources = source_details.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name") or "")
            if "margin" in name.lower() or "融資" in name:
                return name
    return "market_chip_daily"


def _stored_margin_daily_aggregate(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
) -> dict[str, Any] | None:
    source_name = MARGIN_DAILY_SOURCE_NAMES.get(index_id.upper())
    if source_name is None:
        return None

    margin_usable = and_(
        MarginTradingDaily.margin_previous_balance.is_not(None),
        MarginTradingDaily.margin_today_balance.is_not(None),
    )
    short_usable = and_(
        MarginTradingDaily.short_previous_balance.is_not(None),
        MarginTradingDaily.short_today_balance.is_not(None),
    )
    fully_usable = and_(margin_usable, short_usable)
    result = (
        db.query(
            func.count(MarginTradingDaily.id).label("total_count"),
            func.sum(case((fully_usable, 1), else_=0)).label("coverage_count"),
            func.sum(
                case(
                    (
                        margin_usable,
                        MarginTradingDaily.margin_today_balance
                        - MarginTradingDaily.margin_previous_balance,
                    ),
                    else_=None,
                )
            ).label("margin_change_lots"),
            func.sum(
                case(
                    (
                        short_usable,
                        MarginTradingDaily.short_today_balance
                        - MarginTradingDaily.short_previous_balance,
                    ),
                    else_=None,
                )
            ).label("short_change_lots"),
        )
        .join(SourceRegistry, SourceRegistry.id == MarginTradingDaily.source_id)
        .filter(SourceRegistry.source_name == source_name)
        .filter(MarginTradingDaily.trade_date == trade_date)
        .one()
    )
    total_count = int(result.total_count or 0)
    if total_count == 0:
        return None

    coverage_count = int(result.coverage_count or 0)
    margin_change_lots = result.margin_change_lots
    short_change_lots = result.short_change_lots
    return {
        "values": {
            "margin_balance_change_value": None,
            "margin_balance_change_shares": (
                int(margin_change_lots) * 1000
                if margin_change_lots is not None
                else None
            ),
            "short_balance_change_shares": (
                int(short_change_lots) * 1000
                if short_change_lots is not None
                else None
            ),
        },
        "source": "margin_trading_daily",
        "coverage_count": coverage_count,
        "total_count": total_count,
    }


def _latest_populated_margin_row(
    db: Session,
    *,
    index_id: str,
    on_or_before: date,
) -> MarketChipDaily | None:
    return (
        db.query(MarketChipDaily)
        .filter(MarketChipDaily.index_id == index_id.upper())
        .filter(MarketChipDaily.trade_date <= on_or_before)
        .filter(
            or_(
                MarketChipDaily.margin_balance_change_value.is_not(None),
                MarketChipDaily.margin_balance_change_shares.is_not(None),
                MarketChipDaily.short_balance_change_shares.is_not(None),
            )
        )
        .order_by(MarketChipDaily.trade_date.desc())
        .first()
    )


def _resolve_market_chip_margin(
    row: MarketChipDaily,
    *,
    db: Session | None,
    now: datetime | None,
) -> tuple[dict[str, int | None], dict[str, Any]]:
    index_id = row.index_id.upper()
    expected_date = expected_market_margin_chip_date(now=now)
    pending_trade_date = row.trade_date if row.trade_date > expected_date else None
    expected_fields = _margin_fields_expected_for_index(index_id)
    exact_row: MarketChipDaily | None = row if row.trade_date == expected_date else None

    if exact_row is None and db is not None:
        exact_row = (
            db.query(MarketChipDaily)
            .filter(MarketChipDaily.index_id == index_id)
            .filter(MarketChipDaily.trade_date == expected_date)
            .first()
        )

    values = (
        _margin_values_from_row(exact_row)
        if exact_row is not None
        else {
            "margin_balance_change_value": None,
            "margin_balance_change_shares": None,
            "short_balance_change_shares": None,
        }
    )
    source_parts: list[str] = []
    if exact_row is not None and any(value is not None for value in values.values()):
        source_parts.append(_margin_source_from_row(exact_row))

    aggregate = (
        _stored_margin_daily_aggregate(
            db,
            index_id=index_id,
            trade_date=expected_date,
        )
        if db is not None
        else None
    )
    coverage_count = None
    total_count = None
    if aggregate is not None:
        aggregate_values = aggregate["values"]
        for field in (
            "margin_balance_change_shares",
            "short_balance_change_shares",
        ):
            if values.get(field) is None:
                values[field] = aggregate_values.get(field)
        coverage_count = aggregate.get("coverage_count")
        total_count = aggregate.get("total_count")
        if any(value is not None for value in aggregate_values.values()):
            source_parts.append(str(aggregate["source"]))

    available_fields = [field for field in expected_fields if values.get(field) is not None]
    data_date: date | None = expected_date if available_fields else None
    warnings: list[str] = []

    if len(available_fields) == len(expected_fields):
        status = "ready"
        reason = (
            "margin_for_current_chip_date_pending_release"
            if pending_trade_date is not None
            else None
        )
    elif available_fields:
        status = "partial"
        reason = "released_margin_data_incomplete"
        warnings.append("Released margin data is incomplete.")
    else:
        older_row = (
            _latest_populated_margin_row(
                db,
                index_id=index_id,
                on_or_before=expected_date,
            )
            if db is not None
            else None
        )
        if older_row is not None:
            values = _margin_values_from_row(older_row)
            data_date = older_row.trade_date
            source_parts = [_margin_source_from_row(older_row)]
            status = "stale"
            reason = "expected_margin_data_unavailable"
            warnings.append(
                "Latest released margin data is unavailable; showing an older snapshot."
            )
        else:
            status = "missing"
            reason = "released_margin_data_unavailable"
            warnings.append("Latest released margin data is unavailable.")

    source = "+".join(dict.fromkeys(source_parts)) or None
    return values, {
        "resource": "market_chip_margin_daily",
        "status": status,
        "data_date": data_date,
        "expected_data_date": expected_date,
        "pending_trade_date": pending_trade_date,
        "source": source,
        "reason": reason,
        "coverage_count": coverage_count,
        "total_count": total_count,
        "warnings": warnings,
    }


def _stored_market_chip_margin_status(
    row: MarketChipDaily,
) -> tuple[dict[str, int | None], dict[str, Any]]:
    values = _margin_values_from_row(row)
    expected_fields = _margin_fields_expected_for_index(row.index_id)
    available_fields = [field for field in expected_fields if values.get(field) is not None]
    if len(available_fields) == len(expected_fields):
        status = "ready"
        reason = None
        warnings: list[str] = []
    elif available_fields:
        status = "partial"
        reason = "stored_margin_data_incomplete"
        warnings = ["Stored margin data is incomplete."]
    else:
        status = "missing"
        reason = "stored_margin_data_unavailable"
        warnings = ["Stored margin data is unavailable."]

    return values, {
        "resource": "market_chip_margin_daily",
        "status": status,
        "data_date": row.trade_date if available_fields else None,
        "expected_data_date": row.trade_date,
        "pending_trade_date": None,
        "source": _margin_source_from_row(row) if available_fields else None,
        "reason": reason,
        "coverage_count": None,
        "total_count": None,
        "warnings": warnings,
    }


def _has_missing_released_margin_fields(row: MarketChipDaily) -> bool:
    if row.trade_date > expected_market_margin_chip_date():
        return False

    return any(
        getattr(row, field) is None
        for field in _margin_fields_expected_for_index(row.index_id)
    )


def _has_missing_released_options_fields(row: MarketChipDaily) -> bool:
    if row.index_id.upper() != "TAIEX" or row.trade_date > expected_market_chip_date():
        return False

    return any(
        getattr(row, field) is None
        for field in (
            "put_volume",
            "call_volume",
            "put_call_volume_ratio_pct",
            "put_open_interest",
            "call_open_interest",
            "put_call_open_interest_ratio_pct",
        )
    )


def ensure_market_chip_daily(
    db: Session,
    *,
    index_id: str = "TAIEX",
    trade_date: date | None = None,
    include_today: bool | None = None,
    force: bool = False,
) -> MarketChipDaily:
    normalized_index_id = index_id.upper()
    target_trade_date = trade_date or expected_market_chip_date(
        include_today=include_today
    )

    existing = (
        db.query(MarketChipDaily)
        .filter(MarketChipDaily.index_id == normalized_index_id)
        .filter(MarketChipDaily.trade_date == target_trade_date)
        .first()
    )
    if (
        existing is not None
        and not force
        and not _has_missing_released_margin_fields(existing)
        and not _has_missing_released_options_fields(existing)
    ):
        return existing

    payload = fetch_market_chip_daily(
        db=db,
        index_id=normalized_index_id,
        trade_date=target_trade_date,
    )
    return upsert_market_chip_daily(db=db, payload=payload)


def refresh_market_chip_daily(
    db: Session,
    *,
    index_ids: Iterable[str] | None = None,
    trade_date: date | None = None,
    include_today: bool | None = None,
    force: bool = False,
    progress: MarketChipProgressCallback | None = None,
) -> dict[str, Any]:
    target_trade_date = trade_date or expected_market_chip_date(
        include_today=include_today
    )
    normalized_index_ids = normalize_market_chip_index_ids(index_ids)
    total = len(normalized_index_ids)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if progress is not None:
        progress(0, total, f"Refreshing market chip daily for {target_trade_date}.")

    for current, index_id in enumerate(normalized_index_ids, start=1):
        if progress is not None:
            progress(
                current - 1,
                total,
                f"Refreshing market chip daily {index_id}.",
            )

        try:
            row = ensure_market_chip_daily(
                db=db,
                index_id=index_id,
                trade_date=target_trade_date,
                include_today=include_today,
                force=force,
            )
            results.append(
                {
                    "index_id": row.index_id,
                    "market": row.market,
                    "trade_date": row.trade_date.isoformat(),
                    "status": "success",
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
            )
        except (MarketChipFetchError, ValueError) as exc:
            errors.append(
                {
                    "index_id": index_id,
                    "trade_date": target_trade_date.isoformat(),
                    "status": "error",
                    "error_message": str(exc),
                }
            )
        finally:
            if progress is not None:
                progress(current, total, f"Refreshed {current}/{total} market chip rows.")

    success_count = len(results)
    error_count = len(errors)
    result_status = (
        "success"
        if error_count == 0
        else "partial_success"
        if success_count > 0
        else "error"
    )

    return {
        "status": result_status,
        "message": (
            f"Market chip daily refresh completed for {target_trade_date}."
            if error_count == 0
            else f"Market chip daily refresh completed with {error_count} source errors."
        ),
        "trade_date": target_trade_date.isoformat(),
        "requested_count": total,
        "success_count": success_count,
        "error_count": error_count,
        "force": force,
        "results": results,
        "errors": errors,
    }


def get_latest_market_chip_daily(
    db: Session,
    *,
    index_id: str = "TAIEX",
) -> MarketChipDaily | None:
    return (
        db.query(MarketChipDaily)
        .filter(MarketChipDaily.index_id == index_id.upper())
        .order_by(MarketChipDaily.trade_date.desc())
        .first()
    )


def list_market_chip_daily(
    db: Session,
    *,
    index_id: str = "TAIEX",
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 120,
) -> list[MarketChipDaily]:
    query = db.query(MarketChipDaily).filter(MarketChipDaily.index_id == index_id.upper())

    if from_date is not None:
        query = query.filter(MarketChipDaily.trade_date >= from_date)
    if to_date is not None:
        query = query.filter(MarketChipDaily.trade_date <= to_date)

    rows = query.order_by(MarketChipDaily.trade_date.desc()).limit(limit).all()
    rows.reverse()
    return rows


def market_chip_daily_to_dict(
    row: MarketChipDaily,
    *,
    db: Session | None = None,
    now: datetime | None = None,
    resolve_expected_margin: bool = False,
) -> dict[str, Any]:
    source_details = _load_source_details(row)
    if resolve_expected_margin:
        margin_values, margin_status = _resolve_market_chip_margin(
            row,
            db=db,
            now=now,
        )
    else:
        margin_values, margin_status = _stored_market_chip_margin_status(row)
    government_bank_status = {
        "resource": "government_bank_net_value",
        "status": "ready" if row.government_bank_net_value is not None else "not_available",
        "data_date": row.trade_date if row.government_bank_net_value is not None else None,
        "expected_data_date": None,
        "pending_trade_date": None,
        "source": "market_chip_daily" if row.government_bank_net_value is not None else None,
        "reason": (
            None
            if row.government_bank_net_value is not None
            else "government_bank_provider_not_configured"
        ),
        "coverage_count": None,
        "total_count": None,
        "warnings": [],
    }
    return {
        "id": row.id,
        "index_id": row.index_id,
        "market": row.market,
        "trade_date": row.trade_date,
        "close_value": row.close_value,
        "price_change": row.price_change,
        "price_change_pct": row.price_change_pct,
        "trade_value": row.trade_value,
        "foreign_futures_net_oi": row.foreign_futures_net_oi,
        "foreign_futures_net_oi_change": row.foreign_futures_net_oi_change,
        "retail_futures_net_oi": row.retail_futures_net_oi,
        "retail_futures_net_oi_change": row.retail_futures_net_oi_change,
        "put_volume": row.put_volume,
        "call_volume": row.call_volume,
        "put_call_volume_ratio_pct": row.put_call_volume_ratio_pct,
        "put_open_interest": row.put_open_interest,
        "call_open_interest": row.call_open_interest,
        "put_call_open_interest_ratio_pct": row.put_call_open_interest_ratio_pct,
        "total_institutional_net_value": row.total_institutional_net_value,
        "foreign_investor_net_value": row.foreign_investor_net_value,
        "investment_trust_net_value": row.investment_trust_net_value,
        "dealer_net_value": row.dealer_net_value,
        "dealer_self_net_value": row.dealer_self_net_value,
        "dealer_hedge_net_value": row.dealer_hedge_net_value,
        "government_bank_net_value": row.government_bank_net_value,
        "margin_balance_change_value": margin_values["margin_balance_change_value"],
        "margin_balance_change_shares": margin_values[
            "margin_balance_change_shares"
        ],
        "short_balance_change_shares": margin_values[
            "short_balance_change_shares"
        ],
        "margin_status": margin_status,
        "government_bank_status": government_bank_status,
        "source_grade": row.source_grade,
        "source_details": source_details,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def latest_market_chip_trade_date(
    db: Session,
    *,
    index_id: str = "TAIEX",
) -> date | None:
    return (
        db.query(func.max(MarketChipDaily.trade_date))
        .filter(MarketChipDaily.index_id == index_id.upper())
        .scalar()
    )
