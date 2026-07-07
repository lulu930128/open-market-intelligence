from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from app.http_client import get as http_get
from app.us_market.trading_calendar import (
    US_POST_MARKET_CLOSE_TIME,
    US_PRE_MARKET_OPEN_TIME,
    US_SESSION_CLOSE_TIME,
    US_SESSION_OPEN_TIME,
)


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ALPHAVANTAGE_QUERY_URL = "https://www.alphavantage.co/query"
FINRA_SHORT_VOLUME_URL_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
FRED_SERIES_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


OTHER_EXCHANGE_CODES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}

YAHOO_EXCHANGE_CODES = {
    "ASE": "NYSE American",
    "BTS": "Cboe BZX",
    "NCM": "NASDAQ",
    "NGM": "NASDAQ",
    "NMS": "NASDAQ",
    "NASDAQ CAPITAL MARKET": "NASDAQ",
    "NASDAQ GLOBAL MARKET": "NASDAQ",
    "NASDAQ GLOBAL SELECT": "NASDAQ",
    "NASDAQCM": "NASDAQ",
    "NASDAQGM": "NASDAQ",
    "NASDAQGS": "NASDAQ",
    "NYQ": "NYSE",
    "PCX": "NYSE Arca",
}

YAHOO_INSTRUMENT_TYPES = {
    "EQUITY": "stock",
    "ETF": "ETF",
    "INDEX": "index",
    "MUTUALFUND": "fund",
}


class USMarketDataFetchError(Exception):
    pass


@dataclass(frozen=True)
class USSymbolRecord:
    symbol: str
    security_name: str | None
    exchange: str | None
    asset_type: str
    listing_source: str
    market_category: str | None = None
    financial_status: str | None = None
    cqs_symbol: str | None = None
    nasdaq_symbol: str | None = None
    cik: str | None = None
    sec_company_name: str | None = None
    is_etf: bool | None = None
    is_test_issue: bool = False
    round_lot_size: int | None = None


@dataclass(frozen=True)
class USDailyPriceRecord:
    provider: str
    symbol: str
    trade_date: date
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    adjusted_close: float | None
    trade_volume: int | None
    dividend_amount: float | None
    split_coefficient: float | None
    source_url: str | None
    raw_payload_hash: str | None


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


US_PRE_MARKET_OPEN_MINUTES = _minutes(US_PRE_MARKET_OPEN_TIME)
US_SESSION_OPEN_MINUTES = _minutes(US_SESSION_OPEN_TIME)
US_SESSION_CLOSE_MINUTES = _minutes(US_SESSION_CLOSE_TIME)
US_POST_MARKET_CLOSE_MINUTES = _minutes(US_POST_MARKET_CLOSE_TIME)


def _us_intraday_session(value: datetime) -> str:
    minutes = value.hour * 60 + value.minute
    if US_PRE_MARKET_OPEN_MINUTES <= minutes < US_SESSION_OPEN_MINUTES:
        return "pre_market"
    if US_SESSION_OPEN_MINUTES <= minutes <= US_SESSION_CLOSE_MINUTES:
        return "regular"
    if US_SESSION_CLOSE_MINUTES < minutes <= US_POST_MARKET_CLOSE_MINUTES:
        return "after_hours"
    return "off_session"


def _filter_intraday_session_points(points: list[dict], session_scope: str) -> list[dict]:
    if session_scope == "all":
        return points
    if session_scope == "extended":
        return [point for point in points if point.get("session") in {"pre_market", "after_hours"}]
    return [point for point in points if point.get("session") == "regular"]


@dataclass(frozen=True)
class USSecFactRecord:
    fact_key: str
    cik: str
    symbol: str | None
    entity_name: str | None
    taxonomy: str
    tag: str
    label: str | None
    description: str | None
    unit: str
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed_date: date | None
    period_start_date: date | None
    period_end_date: date | None
    accession_number: str | None
    frame: str | None
    value_numeric: float | None
    value_text: str | None
    source_url: str | None


@dataclass(frozen=True)
class USCompanyProfileRecord:
    provider: str
    symbol: str
    company_name: str | None
    description: str | None
    exchange: str | None
    sector: str | None
    industry: str | None
    country: str | None
    currency: str | None
    market_cap: int | None
    ebitda: int | None
    pe_ratio: float | None
    peg_ratio: float | None
    beta: float | None
    dividend_yield: float | None
    eps: float | None
    revenue_ttm: int | None
    profit_margin: float | None
    fiscal_year_end: str | None
    latest_quarter: date | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class USCorporateActionRecord:
    provider: str
    symbol: str
    action_type: str
    event_date: date
    declaration_date: date | None
    record_date: date | None
    payment_date: date | None
    amount: float | None
    split_from: float | None
    split_to: float | None
    split_ratio: float | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class USShortVolumeRecord:
    provider: str
    symbol: str
    trade_date: date
    market_center: str
    short_volume: int | None
    short_exempt_volume: int | None
    total_volume: int | None
    short_ratio: float | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class MacroSeriesObservationRecord:
    provider: str
    series_id: str
    series_name: str | None
    observation_date: date
    value: float | None
    unit: str | None
    frequency: str | None
    source_url: str | None
    raw_payload_hash: str | None


US_SYMBOL_TOKEN_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.$-]{0,31}")


def normalize_us_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    match = US_SYMBOL_TOKEN_PATTERN.match(cleaned)
    return match.group(0) if match else cleaned


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in {"N/A", "NULL"}:
        return None

    return cleaned


def _parse_bool(value: Any) -> bool | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    if cleaned.upper() == "Y":
        return True

    if cleaned.upper() == "N":
        return False

    return None


def _parse_int(value: Any) -> int | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return int(cleaned.replace(",", ""))
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def _parse_compact_date(value: Any) -> date | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    try:
        return datetime.strptime(cleaned, "%Y%m%d").date()
    except ValueError:
        return _parse_date(cleaned)


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_url_params(url: str, names: tuple[str, ...] = ("apikey", "api_key")) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url

    redacted_names = {name.lower() for name in names}
    changed = False
    query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in redacted_names:
            query_pairs.append((key, "REDACTED"))
            changed = True
            continue

        query_pairs.append((key, value))

    if not changed:
        return url

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_pairs),
            parts.fragment,
        )
    )


def _alphavantage_payload_or_raise(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError("Alpha Vantage returned a non-object JSON payload.")

    error_message = payload.get("Error Message") or payload.get("Note") or payload.get("Information")
    if error_message:
        raise USMarketDataFetchError(str(error_message))

    return payload


def _list_value(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None

    return values[index]


def _iter_pipe_rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    rows: list[dict[str, str]] = []

    for row in reader:
        first_value = next(iter(row.values()), "")
        if first_value.startswith("File Creation Time"):
            continue
        rows.append(row)

    return rows


def parse_nasdaq_listed_symbols(text: str) -> list[USSymbolRecord]:
    records: list[USSymbolRecord] = []

    for row in _iter_pipe_rows(text):
        symbol = normalize_us_symbol(row.get("Symbol"))
        if not symbol:
            continue

        is_etf = _parse_bool(row.get("ETF"))
        is_test_issue = _parse_bool(row.get("Test Issue")) is True
        records.append(
            USSymbolRecord(
                symbol=symbol,
                security_name=_clean_text(row.get("Security Name")),
                exchange="NASDAQ",
                asset_type="ETF" if is_etf else "stock",
                listing_source="nasdaq_trader",
                market_category=_clean_text(row.get("Market Category")),
                financial_status=_clean_text(row.get("Financial Status")),
                is_etf=is_etf,
                is_test_issue=is_test_issue,
                round_lot_size=_parse_int(row.get("Round Lot Size")),
            )
        )

    return records


def parse_other_listed_symbols(text: str) -> list[USSymbolRecord]:
    records: list[USSymbolRecord] = []

    for row in _iter_pipe_rows(text):
        symbol = normalize_us_symbol(row.get("ACT Symbol"))
        if not symbol:
            continue

        exchange_code = _clean_text(row.get("Exchange"))
        is_etf = _parse_bool(row.get("ETF"))
        is_test_issue = _parse_bool(row.get("Test Issue")) is True
        records.append(
            USSymbolRecord(
                symbol=symbol,
                security_name=_clean_text(row.get("Security Name")),
                exchange=OTHER_EXCHANGE_CODES.get(exchange_code or "", exchange_code),
                asset_type="ETF" if is_etf else "stock",
                listing_source="nasdaq_trader",
                cqs_symbol=normalize_us_symbol(row.get("CQS Symbol")) or None,
                nasdaq_symbol=normalize_us_symbol(row.get("NASDAQ Symbol")) or None,
                is_etf=is_etf,
                is_test_issue=is_test_issue,
                round_lot_size=_parse_int(row.get("Round Lot Size")),
            )
        )

    return records


def parse_sec_company_tickers_exchange(payload: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    mapping: dict[str, dict[str, str | None]] = {}

    fields = payload.get("fields")
    data = payload.get("data")

    if isinstance(fields, list) and isinstance(data, list):
        for row in data:
            if not isinstance(row, list):
                continue

            item = {str(field): row[index] if index < len(row) else None for index, field in enumerate(fields)}
            ticker = normalize_us_symbol(_clean_text(item.get("ticker")))
            if not ticker:
                continue

            cik_value = _parse_int(item.get("cik"))
            mapping[ticker] = {
                "cik": f"{cik_value:010d}" if cik_value is not None else None,
                "sec_company_name": _clean_text(item.get("name")),
                "sec_exchange": _clean_text(item.get("exchange")),
            }

        return mapping

    for value in payload.values():
        if not isinstance(value, dict):
            continue

        ticker = normalize_us_symbol(_clean_text(value.get("ticker")))
        if not ticker:
            continue

        cik_value = _parse_int(value.get("cik_str"))
        mapping[ticker] = {
            "cik": f"{cik_value:010d}" if cik_value is not None else None,
            "sec_company_name": _clean_text(value.get("title")),
            "sec_exchange": None,
        }

    return mapping


def merge_sec_company_data(
    records: list[USSymbolRecord],
    sec_mapping: dict[str, dict[str, str | None]],
) -> list[USSymbolRecord]:
    merged: list[USSymbolRecord] = []

    for record in records:
        sec_item = sec_mapping.get(record.symbol)
        if sec_item is None:
            merged.append(record)
            continue

        merged.append(
            USSymbolRecord(
                symbol=record.symbol,
                security_name=record.security_name,
                exchange=record.exchange or sec_item.get("sec_exchange"),
                asset_type=record.asset_type,
                listing_source=record.listing_source,
                market_category=record.market_category,
                financial_status=record.financial_status,
                cqs_symbol=record.cqs_symbol,
                nasdaq_symbol=record.nasdaq_symbol,
                cik=sec_item.get("cik"),
                sec_company_name=sec_item.get("sec_company_name"),
                is_etf=record.is_etf,
                is_test_issue=record.is_test_issue,
                round_lot_size=record.round_lot_size,
            )
        )

    return merged


def parse_symbol_directories(
    *,
    nasdaq_listed_text: str,
    other_listed_text: str,
    sec_company_payload: dict[str, Any] | None = None,
) -> list[USSymbolRecord]:
    records_by_symbol = {
        record.symbol: record
        for record in [
            *parse_nasdaq_listed_symbols(nasdaq_listed_text),
            *parse_other_listed_symbols(other_listed_text),
        ]
    }
    records = list(records_by_symbol.values())

    if sec_company_payload is None:
        return sorted(records, key=lambda item: item.symbol)

    sec_mapping = parse_sec_company_tickers_exchange(sec_company_payload)
    return sorted(merge_sec_company_data(records, sec_mapping), key=lambda item: item.symbol)


def _get_json(url: str, *, timeout_seconds: int, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = http_get(url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError(f"Expected JSON object from {url}.")

    return payload


def _get_text(url: str, *, timeout_seconds: int, headers: dict[str, str] | None = None) -> str:
    response = http_get(url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def fetch_sec_company_tickers_exchange_payload(
    *,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    payload = _get_json(
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
        headers={"User-Agent": sec_user_agent},
        timeout_seconds=timeout_seconds,
    )
    return payload, SEC_COMPANY_TICKERS_EXCHANGE_URL


def fetch_symbol_directories(
    *,
    include_sec_company_data: bool,
    sec_user_agent: str,
    timeout_seconds: int,
) -> list[USSymbolRecord]:
    nasdaq_text = _get_text(NASDAQ_LISTED_URL, timeout_seconds=timeout_seconds)
    other_text = _get_text(NASDAQ_OTHER_LISTED_URL, timeout_seconds=timeout_seconds)
    sec_payload = None

    if include_sec_company_data:
        sec_payload, _source_url = fetch_sec_company_tickers_exchange_payload(
            sec_user_agent=sec_user_agent,
            timeout_seconds=timeout_seconds,
        )

    return parse_symbol_directories(
        nasdaq_listed_text=nasdaq_text,
        other_listed_text=other_text,
        sec_company_payload=sec_payload,
    )


def fetch_alphavantage_daily_payload(
    *,
    symbol: str,
    api_key: str,
    outputsize: str,
    adjusted: bool,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    function_name = "TIME_SERIES_DAILY_ADJUSTED" if adjusted else "TIME_SERIES_DAILY"
    response = http_get(
        ALPHAVANTAGE_QUERY_URL,
        params={
            "function": function_name,
            "symbol": normalize_us_symbol(symbol),
            "outputsize": outputsize,
            "apikey": api_key,
        },
        timeout=timeout_seconds,
    )
    payload = _alphavantage_payload_or_raise(response)
    return payload, _redact_url_params(response.url)


def fetch_alphavantage_overview_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = http_get(
        ALPHAVANTAGE_QUERY_URL,
        params={
            "function": "OVERVIEW",
            "symbol": normalize_us_symbol(symbol),
            "apikey": api_key,
        },
        timeout=timeout_seconds,
    )
    payload = _alphavantage_payload_or_raise(response)
    return payload, _redact_url_params(response.url)


def fetch_alphavantage_dividends_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = http_get(
        ALPHAVANTAGE_QUERY_URL,
        params={
            "function": "DIVIDENDS",
            "symbol": normalize_us_symbol(symbol),
            "apikey": api_key,
        },
        timeout=timeout_seconds,
    )
    payload = _alphavantage_payload_or_raise(response)
    return payload, _redact_url_params(response.url)


def fetch_alphavantage_splits_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = http_get(
        ALPHAVANTAGE_QUERY_URL,
        params={
            "function": "SPLITS",
            "symbol": normalize_us_symbol(symbol),
            "apikey": api_key,
        },
        timeout=timeout_seconds,
    )
    payload = _alphavantage_payload_or_raise(response)
    return payload, _redact_url_params(response.url)


def fetch_finra_short_volume_payload(
    *,
    trade_date: date,
    timeout_seconds: int,
) -> tuple[str, str]:
    url = FINRA_SHORT_VOLUME_URL_TEMPLATE.format(date=trade_date.strftime("%Y%m%d"))
    return _get_text(url, timeout_seconds=timeout_seconds), url


def fetch_fred_series_observations_payload(
    *,
    series_id: str,
    api_key: str,
    timeout_seconds: int,
    observation_start: date | None = None,
    observation_end: date | None = None,
) -> tuple[dict[str, Any], str]:
    params: dict[str, str] = {
        "series_id": series_id.strip().upper(),
        "api_key": api_key,
        "file_type": "json",
    }
    if observation_start is not None:
        params["observation_start"] = observation_start.isoformat()
    if observation_end is not None:
        params["observation_end"] = observation_end.isoformat()

    response = http_get(
        FRED_SERIES_OBSERVATIONS_URL,
        params=params,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError("FRED returned a non-object JSON payload.")

    if "error_code" in payload:
        raise USMarketDataFetchError(str(payload.get("error_message") or payload["error_code"]))

    return payload, _redact_url_params(response.url)


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
    include_prepost: bool = False,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_us_symbol(symbol)
    response = http_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "true" if include_prepost else "false",
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
        raise USMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")

    return payload, response.url


def parse_alphavantage_daily_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "alphavantage",
    source_url: str | None = None,
) -> list[USDailyPriceRecord]:
    series_key = next(
        (key for key in payload if key.startswith("Time Series (Daily)")),
        None,
    )
    if series_key is None or not isinstance(payload.get(series_key), dict):
        raise USMarketDataFetchError("Alpha Vantage payload does not contain daily time series data.")

    payload_hash = _payload_hash(payload)
    normalized_symbol = normalize_us_symbol(symbol)
    records: list[USDailyPriceRecord] = []

    for date_text, values in payload[series_key].items():
        if not isinstance(values, dict):
            continue

        trade_date = _parse_date(date_text)
        if trade_date is None:
            continue

        records.append(
            USDailyPriceRecord(
                provider=provider,
                symbol=normalized_symbol,
                trade_date=trade_date,
                open_price=_parse_float(values.get("1. open")),
                high_price=_parse_float(values.get("2. high")),
                low_price=_parse_float(values.get("3. low")),
                close_price=_parse_float(values.get("4. close")),
                adjusted_close=_parse_float(values.get("5. adjusted close")),
                trade_volume=_parse_int(values.get("6. volume") or values.get("5. volume")),
                dividend_amount=_parse_float(values.get("7. dividend amount")),
                split_coefficient=_parse_float(values.get("8. split coefficient")),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda item: item.trade_date)


def parse_yahoo_daily_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "yahoo_chart",
    source_url: str | None = None,
) -> list[USDailyPriceRecord]:
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise USMarketDataFetchError("Yahoo chart payload does not contain chart result data.")

    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0]
    adjusted_values = (indicators.get("adjclose") or [{}])[0]
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    tz = timezone(timedelta(seconds=offset))

    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    adjusted_closes = adjusted_values.get("adjclose") or []
    payload_hash = _payload_hash(payload)
    normalized_symbol = normalize_us_symbol(symbol)
    records: list[USDailyPriceRecord] = []

    for index, timestamp in enumerate(timestamps):
        close_price = _parse_float(_list_value(closes, index))
        adjusted_close = _parse_float(_list_value(adjusted_closes, index))
        if close_price is None and adjusted_close is None:
            continue

        trade_date = datetime.fromtimestamp(int(timestamp), tz=tz).date()
        records.append(
            USDailyPriceRecord(
                provider=provider,
                symbol=normalized_symbol,
                trade_date=trade_date,
                open_price=_parse_float(_list_value(opens, index)),
                high_price=_parse_float(_list_value(highs, index)),
                low_price=_parse_float(_list_value(lows, index)),
                close_price=close_price,
                adjusted_close=adjusted_close,
                trade_volume=_parse_int(_list_value(volumes, index)),
                dividend_amount=None,
                split_coefficient=None,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda item: item.trade_date)


def parse_yahoo_symbol_record(
    payload: dict[str, Any],
    *,
    symbol: str,
) -> USSymbolRecord:
    normalized_symbol = normalize_us_symbol(symbol)
    error = payload.get("chart", {}).get("error")
    if error:
        raise USMarketDataFetchError(str(error))

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise USMarketDataFetchError("Yahoo chart payload does not contain chart result data.")

    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        raise USMarketDataFetchError("Yahoo chart payload does not contain symbol metadata.")

    discovered_symbol = normalize_us_symbol(meta.get("symbol") or normalized_symbol)
    if not discovered_symbol:
        raise USMarketDataFetchError("Yahoo chart payload does not contain a symbol.")

    if normalized_symbol and discovered_symbol != normalized_symbol:
        raise USMarketDataFetchError(
            f"Yahoo chart symbol mismatch. requested={normalized_symbol} discovered={discovered_symbol}."
        )

    instrument_type = (_clean_text(meta.get("instrumentType")) or "").upper()
    quote_type = (_clean_text(meta.get("quoteType")) or "").upper()
    asset_type = (
        YAHOO_INSTRUMENT_TYPES.get(instrument_type)
        or YAHOO_INSTRUMENT_TYPES.get(quote_type)
        or "unknown"
    )
    full_exchange = _clean_text(meta.get("fullExchangeName"))
    exchange_code = _clean_text(meta.get("exchangeName"))
    exchange = (
        YAHOO_EXCHANGE_CODES.get((full_exchange or "").upper())
        or full_exchange
        or YAHOO_EXCHANGE_CODES.get(exchange_code or "")
        or YAHOO_EXCHANGE_CODES.get((exchange_code or "").upper())
        or exchange_code
    )
    is_etf = asset_type == "ETF"

    return USSymbolRecord(
        symbol=discovered_symbol,
        security_name=(
            _clean_text(meta.get("longName"))
            or _clean_text(meta.get("shortName"))
            or _clean_text(meta.get("regularMarketName"))
            or discovered_symbol
        ),
        exchange=exchange,
        asset_type=asset_type,
        listing_source="discovered_yahoo_chart",
        is_etf=is_etf,
        is_test_issue=False,
    )


def parse_yahoo_intraday_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    source_url: str | None = None,
    session_scope: str = "regular",
) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)
    if session_scope not in {"regular", "extended", "all"}:
        raise ValueError("session_scope must be one of: regular, extended, all.")

    result = (payload.get("chart", {}).get("result") or [None])[0]

    if not isinstance(result, dict):
        return {
            "stock_id": normalized_symbol,
            "symbol": normalized_symbol,
            "source": "yahoo_finance_chart",
            "session_scope": session_scope,
            "session_phase": None,
            "has_extended_hours": False,
            "regular_point_count": 0,
            "extended_point_count": 0,
            "previous_close": None,
            "previous_close_source": None,
            "previous_close_trade_date": None,
            "previous_close_provider": None,
            "regular_session_close": None,
            "regular_session_close_time": None,
            "point_count": 0,
            "points": [],
            "source_url": source_url,
            "warnings": ["Yahoo chart payload did not contain result data."],
        }

    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0]
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    tz = timezone(timedelta(seconds=offset))

    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    all_points: list[dict] = []

    for index, timestamp in enumerate(timestamps):
        price = _parse_float(_list_value(closes, index))
        if price is None:
            continue

        point_time = datetime.fromtimestamp(int(timestamp), tz=tz)
        all_points.append(
            {
                "time": point_time.isoformat(),
                "session": _us_intraday_session(point_time),
                "price": price,
                "volume": _parse_int(_list_value(volumes, index)),
                "open": _parse_float(_list_value(opens, index)),
                "high": _parse_float(_list_value(highs, index)),
                "low": _parse_float(_list_value(lows, index)),
            }
        )

    points = _filter_intraday_session_points(all_points, session_scope)
    regular_point_count = sum(1 for point in all_points if point.get("session") == "regular")
    extended_point_count = sum(
        1
        for point in all_points
        if point.get("session") in {"pre_market", "after_hours"}
    )
    latest_session = points[-1].get("session") if points else None
    regular_points = [point for point in all_points if point.get("session") == "regular"]
    latest_regular_point = regular_points[-1] if regular_points else None
    warnings: list[str] = []
    if session_scope != "regular" and extended_point_count == 0:
        warnings.append("Yahoo chart did not return extended-hours points for this request.")

    previous_close = (
        _parse_float(meta.get("chartPreviousClose"))
        or _parse_float(meta.get("previousClose"))
        or _parse_float(meta.get("regularMarketPreviousClose"))
    )

    return {
        "stock_id": normalized_symbol,
        "symbol": normalized_symbol,
        "source": "yahoo_finance_chart",
        "session_scope": session_scope,
        "session_phase": latest_session,
        "has_extended_hours": extended_point_count > 0,
        "regular_point_count": regular_point_count,
        "extended_point_count": extended_point_count,
        "previous_close": previous_close,
        "previous_close_source": "yahoo_finance_chart" if previous_close is not None else None,
        "previous_close_trade_date": None,
        "previous_close_provider": "yahoo_chart" if previous_close is not None else None,
        "regular_session_close": (
            latest_regular_point.get("price") if latest_regular_point else None
        ),
        "regular_session_close_time": (
            latest_regular_point.get("time") if latest_regular_point else None
        ),
        "point_count": len(points),
        "points": points,
        "source_url": source_url,
        "warnings": warnings,
    }


def parse_alphavantage_company_profile(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "alphavantage",
    source_url: str | None = None,
) -> USCompanyProfileRecord:
    if not payload:
        raise USMarketDataFetchError("Alpha Vantage overview payload is empty.")

    normalized_symbol = normalize_us_symbol(payload.get("Symbol") or symbol)
    if not normalized_symbol:
        raise USMarketDataFetchError("Alpha Vantage overview payload does not contain a symbol.")

    return USCompanyProfileRecord(
        provider=provider,
        symbol=normalized_symbol,
        company_name=_clean_text(payload.get("Name")),
        description=_clean_text(payload.get("Description")),
        exchange=_clean_text(payload.get("Exchange")),
        sector=_clean_text(payload.get("Sector")),
        industry=_clean_text(payload.get("Industry")),
        country=_clean_text(payload.get("Country")),
        currency=_clean_text(payload.get("Currency")),
        market_cap=_parse_int(payload.get("MarketCapitalization")),
        ebitda=_parse_int(payload.get("EBITDA")),
        pe_ratio=_parse_float(payload.get("PERatio")),
        peg_ratio=_parse_float(payload.get("PEGRatio")),
        beta=_parse_float(payload.get("Beta")),
        dividend_yield=_parse_float(payload.get("DividendYield")),
        eps=_parse_float(payload.get("EPS")),
        revenue_ttm=_parse_int(payload.get("RevenueTTM")),
        profit_margin=_parse_float(payload.get("ProfitMargin")),
        fiscal_year_end=_clean_text(payload.get("FiscalYearEnd")),
        latest_quarter=_parse_date(payload.get("LatestQuarter")),
        source_url=source_url,
        raw_payload_hash=_payload_hash(payload),
    )


def parse_alphavantage_dividends(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "alphavantage",
    source_url: str | None = None,
) -> list[USCorporateActionRecord]:
    normalized_symbol = normalize_us_symbol(payload.get("symbol") or symbol)
    payload_hash = _payload_hash(payload)
    records: list[USCorporateActionRecord] = []

    data = payload.get("data")
    if not isinstance(data, list):
        return records

    for item in data:
        if not isinstance(item, dict):
            continue

        event_date = _parse_date(item.get("ex_dividend_date"))
        if event_date is None:
            continue

        records.append(
            USCorporateActionRecord(
                provider=provider,
                symbol=normalized_symbol,
                action_type="dividend",
                event_date=event_date,
                declaration_date=_parse_date(item.get("declaration_date")),
                record_date=_parse_date(item.get("record_date")),
                payment_date=_parse_date(item.get("payment_date")),
                amount=_parse_float(item.get("amount")),
                split_from=None,
                split_to=None,
                split_ratio=None,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda record: record.event_date)


def _parse_split_factor(value: Any) -> tuple[float | None, float | None, float | None]:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None, None, None

    if ":" not in cleaned:
        ratio = _parse_float(cleaned)
        return None, None, ratio

    left_text, right_text = cleaned.split(":", maxsplit=1)
    split_to = _parse_float(left_text)
    split_from = _parse_float(right_text)
    split_ratio = (
        split_to / split_from
        if split_to is not None and split_from not in (None, 0)
        else None
    )
    return split_from, split_to, split_ratio


def parse_alphavantage_splits(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "alphavantage",
    source_url: str | None = None,
) -> list[USCorporateActionRecord]:
    normalized_symbol = normalize_us_symbol(payload.get("symbol") or symbol)
    payload_hash = _payload_hash(payload)
    records: list[USCorporateActionRecord] = []

    data = payload.get("data")
    if not isinstance(data, list):
        return records

    for item in data:
        if not isinstance(item, dict):
            continue

        event_date = _parse_date(item.get("effective_date"))
        if event_date is None:
            continue

        split_from, split_to, split_ratio = _parse_split_factor(item.get("split_factor"))
        records.append(
            USCorporateActionRecord(
                provider=provider,
                symbol=normalized_symbol,
                action_type="split",
                event_date=event_date,
                declaration_date=None,
                record_date=None,
                payment_date=None,
                amount=None,
                split_from=split_from,
                split_to=split_to,
                split_ratio=split_ratio,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda record: record.event_date)


def parse_finra_short_volume(
    text: str,
    *,
    trade_date: date | None = None,
    provider: str = "finra",
    source_url: str | None = None,
) -> list[USShortVolumeRecord]:
    payload_hash = _payload_hash(text)
    records: list[USShortVolumeRecord] = []

    for row in _iter_pipe_rows(text):
        symbol = normalize_us_symbol(row.get("Symbol"))
        row_date = _parse_compact_date(row.get("Date")) or trade_date
        if not symbol or row_date is None:
            continue

        short_volume = _parse_int(row.get("ShortVolume"))
        total_volume = _parse_int(row.get("TotalVolume"))
        if short_volume is None or total_volume is None:
            continue

        short_ratio = (
            short_volume / total_volume
            if short_volume is not None and total_volume not in (None, 0)
            else None
        )

        records.append(
            USShortVolumeRecord(
                provider=provider,
                symbol=symbol,
                trade_date=row_date,
                market_center=_clean_text(row.get("Market")) or "",
                short_volume=short_volume,
                short_exempt_volume=_parse_int(row.get("ShortExemptVolume")),
                total_volume=total_volume,
                short_ratio=short_ratio,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda record: (record.symbol, record.trade_date, record.market_center))


def parse_fred_series_observations(
    payload: dict[str, Any],
    *,
    series_id: str,
    provider: str = "fred",
    series_name: str | None = None,
    unit: str | None = None,
    frequency: str | None = None,
    source_url: str | None = None,
) -> list[MacroSeriesObservationRecord]:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise USMarketDataFetchError("FRED payload does not contain observations data.")

    payload_hash = _payload_hash(payload)
    normalized_series_id = series_id.strip().upper()
    records: list[MacroSeriesObservationRecord] = []

    for item in observations:
        if not isinstance(item, dict):
            continue

        observation_date = _parse_date(item.get("date"))
        if observation_date is None:
            continue

        records.append(
            MacroSeriesObservationRecord(
                provider=provider,
                series_id=normalized_series_id,
                series_name=series_name,
                observation_date=observation_date,
                value=_parse_float(item.get("value")),
                unit=unit,
                frequency=frequency,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda record: record.observation_date)


def fetch_sec_companyfacts_payload(
    *,
    cik: str,
    sec_user_agent: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    padded_cik = f"{_parse_int(cik) or 0:010d}"
    if padded_cik == "0000000000":
        raise USMarketDataFetchError(f"Invalid CIK value: {cik}")

    url = SEC_COMPANY_FACTS_URL_TEMPLATE.format(cik=padded_cik)
    payload = _get_json(
        url,
        headers={"User-Agent": sec_user_agent},
        timeout_seconds=timeout_seconds,
    )
    return payload, url


def _fact_key(*parts: Any) -> str:
    encoded = "\x1f".join("" if part is None else str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_sec_companyfacts(
    payload: dict[str, Any],
    *,
    symbol: str | None,
    source_url: str | None = None,
) -> list[USSecFactRecord]:
    cik_value = _parse_int(payload.get("cik"))
    if cik_value is None:
        raise USMarketDataFetchError("SEC company facts payload does not contain a valid CIK.")

    cik = f"{cik_value:010d}"
    normalized_symbol = normalize_us_symbol(symbol)
    entity_name = _clean_text(payload.get("entityName"))
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return []

    records: list[USSecFactRecord] = []

    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue

        for tag, concept in concepts.items():
            if not isinstance(concept, dict):
                continue

            units = concept.get("units")
            if not isinstance(units, dict):
                continue

            for unit, items in units.items():
                if not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    value = item.get("val")
                    value_numeric = value if isinstance(value, int | float) and not isinstance(value, bool) else _parse_float(value)
                    value_text = None if value is None else str(value)
                    fiscal_year = _parse_int(item.get("fy"))
                    fiscal_period = _clean_text(item.get("fp"))
                    form = _clean_text(item.get("form"))
                    filed_date = _parse_date(item.get("filed"))
                    period_start_date = _parse_date(item.get("start"))
                    period_end_date = _parse_date(item.get("end"))
                    accession_number = _clean_text(item.get("accn"))
                    frame = _clean_text(item.get("frame"))

                    records.append(
                        USSecFactRecord(
                            fact_key=_fact_key(
                                cik,
                                taxonomy,
                                tag,
                                unit,
                                fiscal_year,
                                fiscal_period,
                                form,
                                filed_date,
                                period_start_date,
                                period_end_date,
                                accession_number,
                                frame,
                            ),
                            cik=cik,
                            symbol=normalized_symbol or None,
                            entity_name=entity_name,
                            taxonomy=str(taxonomy),
                            tag=str(tag),
                            label=_clean_text(concept.get("label")),
                            description=_clean_text(concept.get("description")),
                            unit=str(unit),
                            fiscal_year=fiscal_year,
                            fiscal_period=fiscal_period,
                            form=form,
                            filed_date=filed_date,
                            period_start_date=period_start_date,
                            period_end_date=period_end_date,
                            accession_number=accession_number,
                            frame=frame,
                            value_numeric=value_numeric,
                            value_text=value_text,
                            source_url=source_url,
                        )
                    )

    return records
