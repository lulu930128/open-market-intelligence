from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import requests
from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MarketChipDaily, MarketIndexDailyStat
from app.market.indices import ensure_market_index_daily_stat_coverage
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
TAIFEX_FUT_CONTRACTS_DATE_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
TPEX_3INSTI_SUMMARY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary"
MARKET_CHIP_RELEASE_TIME = time(hour=18, minute=30)
HTTP_TIMEOUT_SECONDS = 20
REQUEST_HEADERS = {
    "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
    "Accept": "application/json,text/html,text/plain,*/*",
}
SUPPORTED_MARKET_CHIP_INDEX_IDS = {"TAIEX", "TPEX"}


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


def _fetch_json(url: str, *, params: dict[str, Any] | None = None) -> HttpPayload:
    try:
        response = requests.get(
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
        response = requests.get(
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


def _format_twse_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _format_taifex_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")


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

    if "合計" in compact or compact in {"總計", "三大法人"}:
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
) -> MarketIndexDailyStat | None:
    return (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date == trade_date)
        .first()
    )


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
    else:
        raise ValueError(f"Unsupported market chip index_id: {index_id}")

    return values, sources, warnings


def _non_empty_payload(values: dict[str, Any]) -> bool:
    return any(
        values.get(key) is not None
        for key in (
            "foreign_futures_net_oi",
            "retail_futures_net_oi",
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
                "close_value": index_stat.close_value,
                "price_change": index_stat.price_change,
                "price_change_pct": _price_change_pct(
                    index_stat.close_value,
                    index_stat.price_change,
                ),
                "trade_value": index_stat.trade_value,
            }
        )
        if index_stat.source_url:
            sources.append(
                _source_ref(
                    name=index_stat.source,
                    url=index_stat.source_url,
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
    if existing is not None and not force:
        return existing

    payload = fetch_market_chip_daily(
        db=db,
        index_id=normalized_index_id,
        trade_date=target_trade_date,
    )
    return upsert_market_chip_daily(db=db, payload=payload)


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


def market_chip_daily_to_dict(row: MarketChipDaily) -> dict[str, Any]:
    source_details = _load_source_details(row)
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
        "total_institutional_net_value": row.total_institutional_net_value,
        "foreign_investor_net_value": row.foreign_investor_net_value,
        "investment_trust_net_value": row.investment_trust_net_value,
        "dealer_net_value": row.dealer_net_value,
        "dealer_self_net_value": row.dealer_self_net_value,
        "dealer_hedge_net_value": row.dealer_hedge_net_value,
        "government_bank_net_value": row.government_bank_net_value,
        "margin_balance_change_value": row.margin_balance_change_value,
        "margin_balance_change_shares": row.margin_balance_change_shares,
        "short_balance_change_shares": row.short_balance_change_shares,
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
