from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from app.http_client import get as http_get


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
JPX_LISTED_ISSUES_URL = "https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xls"
JP_SYMBOL_TOKEN_PATTERN = re.compile(r"^[0-9A-Z][0-9A-Z.\-]{0,31}")
YAHOO_INSTRUMENT_TYPES = {
    "EQUITY": "stock",
    "ETF": "ETF",
    "INDEX": "index",
    "MUTUALFUND": "fund",
    "REIT": "REIT",
}


class JPMarketDataFetchError(Exception):
    pass


@dataclass(frozen=True)
class JPStockRecord:
    symbol: str
    local_code: str | None
    security_name: str | None
    exchange: str | None
    market_segment: str | None
    sector_33_code: str | None
    sector_33_name: str | None
    sector_17_code: str | None
    sector_17_name: str | None
    size_code: str | None
    size_name: str | None
    asset_type: str
    listing_source: str
    currency: str
    exchange_timezone_name: str | None


@dataclass(frozen=True)
class JPDailyPriceRecord:
    provider: str
    symbol: str
    trade_date: date
    currency: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    adjusted_close: float | None
    trade_volume: int | None
    source_url: str | None
    raw_payload_hash: str | None


def normalize_jp_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    match = JP_SYMBOL_TOKEN_PATTERN.match(cleaned)
    normalized = match.group(0) if match else cleaned

    if "." in normalized:
        return normalized

    if re.fullmatch(r"[0-9A-Z]{4}", normalized):
        return f"{normalized}.T"

    return normalized


def local_code_from_symbol(symbol: str) -> str:
    normalized_symbol = normalize_jp_symbol(symbol)
    return normalized_symbol.split(".", maxsplit=1)[0]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in {"N/A", "NULL", "-"}:
        return None

    return cleaned


def _parse_int(value: Any) -> int | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return int(float(cleaned.replace(",", "")))
    except ValueError:
        return None


def _clean_code(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    if re.fullmatch(r"\d+\.0", cleaned):
        cleaned = cleaned[:-2]

    return cleaned


def _parse_float(value: Any) -> float | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def _list_value(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _payload_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _chart_result(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("chart", {}).get("error")
    if error:
        raise JPMarketDataFetchError(str(error))

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise JPMarketDataFetchError("Yahoo chart payload does not contain chart result data.")

    return result


def _row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]

    return None


def _asset_type_from_jpx_segment(market_segment: str | None) -> str:
    segment = (market_segment or "").lower()
    if "reit" in segment:
        return "REIT"
    if "etf" in segment or "etn" in segment:
        return "ETF"
    if "infrastructure" in segment:
        return "fund"
    if "preferred" in segment:
        return "preferred_stock"
    return "stock"


def _record_from_jpx_row(row: dict[str, Any]) -> JPStockRecord | None:
    code = _clean_code(_row_value(row, "Local Code", "Code", "Issue Code"))
    if code is None:
        return None

    name = _clean_text(_row_value(row, "Name (English)", "Company Name", "Issue Name", "Name"))
    market_segment = _clean_text(_row_value(row, "Section/Products", "Market Segment"))
    symbol = normalize_jp_symbol(code)

    return JPStockRecord(
        symbol=symbol,
        local_code=local_code_from_symbol(symbol),
        security_name=name,
        exchange="Tokyo Stock Exchange",
        market_segment=market_segment,
        sector_33_code=_clean_code(_row_value(row, "33 Sector(Code)", "33 Sector Code")),
        sector_33_name=_clean_text(_row_value(row, "33 Sector(name)", "33 Sector Name")),
        sector_17_code=_clean_code(_row_value(row, "17 Sector(Code)", "17 Sector Code")),
        sector_17_name=_clean_text(_row_value(row, "17 Sector(name)", "17 Sector Name")),
        size_code=_clean_code(_row_value(row, "Size Code (New Index Series)", "Size Code")),
        size_name=_clean_text(_row_value(row, "Size (New Index Series)", "Size")),
        asset_type=_asset_type_from_jpx_segment(market_segment),
        listing_source="jpx_listed_issues",
        currency="JPY",
        exchange_timezone_name="Asia/Tokyo",
    )


def parse_jpx_listed_issue_rows(rows: list[dict[str, Any]]) -> list[JPStockRecord]:
    records: list[JPStockRecord] = []
    seen_symbols: set[str] = set()

    for row in rows:
        record = _record_from_jpx_row(row)
        if record is None or record.symbol in seen_symbols:
            continue

        seen_symbols.add(record.symbol)
        records.append(record)

    return records


def parse_jpx_listed_issues_workbook(content: bytes) -> list[JPStockRecord]:
    try:
        import xlrd
    except ImportError as exc:
        raise JPMarketDataFetchError(
            "xlrd is required to parse JPX listed issues .xls files. Install backend requirements."
        ) from exc

    try:
        workbook = xlrd.open_workbook(file_contents=content)
    except Exception as exc:
        raise JPMarketDataFetchError("JPX listed issues workbook could not be opened.") from exc

    if workbook.nsheets < 1:
        raise JPMarketDataFetchError("JPX listed issues workbook does not contain sheets.")

    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 2:
        return []

    headers = [_clean_text(sheet.cell_value(0, col_index)) or "" for col_index in range(sheet.ncols)]
    rows: list[dict[str, Any]] = []

    for row_index in range(1, sheet.nrows):
        row: dict[str, Any] = {}
        for col_index, header in enumerate(headers):
            if not header:
                continue
            row[header] = sheet.cell_value(row_index, col_index)
        rows.append(row)

    return parse_jpx_listed_issue_rows(rows)


def fetch_jpx_listed_issues_workbook(
    *,
    timeout_seconds: int,
) -> tuple[bytes, str]:
    response = http_get(
        JPX_LISTED_ISSUES_URL,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/vnd.ms-excel,application/octet-stream,*/*",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.content, response.url


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_jp_symbol(symbol)
    response = http_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise JPMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")

    return payload, response.url


def parse_yahoo_stock_record(
    payload: dict[str, Any],
    *,
    symbol: str,
) -> JPStockRecord:
    normalized_symbol = normalize_jp_symbol(symbol)
    result = _chart_result(payload)
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        raise JPMarketDataFetchError("Yahoo chart payload does not contain symbol metadata.")

    discovered_symbol = normalize_jp_symbol(meta.get("symbol") or normalized_symbol)
    if normalized_symbol and discovered_symbol != normalized_symbol:
        raise JPMarketDataFetchError(
            f"Yahoo chart symbol mismatch. requested={normalized_symbol} discovered={discovered_symbol}."
        )

    instrument_type = (_clean_text(meta.get("instrumentType")) or "").upper()
    quote_type = (_clean_text(meta.get("quoteType")) or "").upper()
    asset_type = (
        YAHOO_INSTRUMENT_TYPES.get(instrument_type)
        or YAHOO_INSTRUMENT_TYPES.get(quote_type)
        or "unknown"
    )
    exchange = (
        _clean_text(meta.get("fullExchangeName"))
        or _clean_text(meta.get("exchangeName"))
        or "Tokyo Stock Exchange"
    )
    currency = _clean_text(meta.get("currency")) or "JPY"

    return JPStockRecord(
        symbol=discovered_symbol,
        local_code=local_code_from_symbol(discovered_symbol),
        security_name=(
            _clean_text(meta.get("longName"))
            or _clean_text(meta.get("shortName"))
            or _clean_text(meta.get("regularMarketName"))
            or discovered_symbol
        ),
        exchange=exchange,
        market_segment=None,
        sector_33_code=None,
        sector_33_name=None,
        sector_17_code=None,
        sector_17_name=None,
        size_code=None,
        size_name=None,
        asset_type=asset_type,
        listing_source="discovered_yahoo_chart",
        currency=currency,
        exchange_timezone_name=_clean_text(meta.get("exchangeTimezoneName")),
    )


def parse_yahoo_daily_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "yahoo_chart",
    source_url: str | None = None,
) -> list[JPDailyPriceRecord]:
    normalized_symbol = normalize_jp_symbol(symbol)
    result = _chart_result(payload)
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0]
    adjusted_values = (indicators.get("adjclose") or [{}])[0]
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    tz = timezone(timedelta(seconds=offset))
    currency = _clean_text(meta.get("currency")) or "JPY"

    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    adjusted_closes = adjusted_values.get("adjclose") or []
    payload_hash = _payload_hash(payload)
    records: list[JPDailyPriceRecord] = []

    for index, timestamp in enumerate(timestamps):
        close_price = _parse_float(_list_value(closes, index))
        adjusted_close = _parse_float(_list_value(adjusted_closes, index))
        if close_price is None and adjusted_close is None:
            continue

        records.append(
            JPDailyPriceRecord(
                provider=provider,
                symbol=normalized_symbol,
                trade_date=datetime.fromtimestamp(int(timestamp), tz=tz).date(),
                currency=currency,
                open_price=_parse_float(_list_value(opens, index)),
                high_price=_parse_float(_list_value(highs, index)),
                low_price=_parse_float(_list_value(lows, index)),
                close_price=close_price,
                adjusted_close=adjusted_close,
                trade_volume=_parse_int(_list_value(volumes, index)),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda item: item.trade_date)
