from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from app.http_client import get as http_get
from app.http_client import post as http_post


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_QUOTE_SUMMARY_MODULES = (
    "price",
    "assetProfile",
    "summaryDetail",
    "defaultKeyStatistics",
    "financialData",
    "calendarEvents",
)
JQUANTS_AUTH_USER_PATH = "/token/auth_user"
JQUANTS_AUTH_REFRESH_PATH = "/token/auth_refresh"
JQUANTS_STATEMENTS_PATH = "/fins/statements"
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


@dataclass(frozen=True)
class JPCompanyFundamentalRecord:
    provider: str
    symbol: str
    company_name: str | None
    exchange: str | None
    sector: str | None
    industry: str | None
    currency: str | None
    market_cap: int | None
    enterprise_value: int | None
    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    dividend_yield: float | None
    beta: float | None
    disclosed_date: date | None
    fiscal_period: str | None
    fiscal_year_end: date | None
    document_type: str | None
    eps_ttm: float | None
    forward_eps: float | None
    revenue_ttm: int | None
    net_sales: int | None
    operating_profit: int | None
    ordinary_profit: int | None
    profit: int | None
    forecast_net_sales: int | None
    forecast_operating_profit: int | None
    forecast_ordinary_profit: int | None
    forecast_profit: int | None
    gross_margin: float | None
    operating_margin: float | None
    profit_margin: float | None
    return_on_equity: float | None
    return_on_assets: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    total_assets: int | None
    equity: int | None
    equity_to_asset_ratio: float | None
    total_cash: int | None
    total_debt: int | None
    operating_cash_flow: int | None
    investing_cash_flow: int | None
    financing_cash_flow: int | None
    debt_to_equity: float | None
    current_ratio: float | None
    quick_ratio: float | None
    shares_outstanding: int | None
    book_value: float | None
    earnings_date: date | None
    ex_dividend_date: date | None
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


def _yahoo_raw(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")

    return value


def _yahoo_int(value: Any) -> int | None:
    return _parse_int(_yahoo_raw(value))


def _yahoo_float(value: Any) -> float | None:
    return _parse_float(_yahoo_raw(value))


def _yahoo_text(value: Any) -> str | None:
    return _clean_text(_yahoo_raw(value))


def _yahoo_date(value: Any) -> date | None:
    raw_value = _yahoo_raw(value)
    if raw_value is None:
        return None

    if isinstance(raw_value, list):
        for item in raw_value:
            parsed = _yahoo_date(item)
            if parsed is not None:
                return parsed
        return None

    if isinstance(raw_value, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw_value), tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None

    cleaned = _clean_text(raw_value)
    if cleaned is None:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def _parse_date_value(value: Any) -> date | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


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


def _jquants_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _jquants_url(base_url: str, path: str) -> str:
    return f"{_jquants_base_url(base_url)}{path}"


def fetch_jquants_refresh_token(
    *,
    base_url: str,
    mail_address: str,
    password: str,
    timeout_seconds: int = 30,
) -> str:
    response = http_post(
        _jquants_url(base_url, JQUANTS_AUTH_USER_PATH),
        json={"mailaddress": mail_address, "password": password},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise JPMarketDataFetchError(
            f"J-Quants auth_user failed: HTTP {response.status_code}."
        )

    payload = response.json()
    refresh_token = _clean_text(payload.get("refreshToken"))
    if refresh_token is None:
        raise JPMarketDataFetchError("J-Quants auth_user did not return refreshToken.")

    return refresh_token


def fetch_jquants_id_token(
    *,
    base_url: str,
    refresh_token: str,
    timeout_seconds: int = 30,
) -> str:
    response = http_post(
        _jquants_url(base_url, JQUANTS_AUTH_REFRESH_PATH),
        params={"refreshtoken": refresh_token},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise JPMarketDataFetchError(
            f"J-Quants auth_refresh failed: HTTP {response.status_code}."
        )

    payload = response.json()
    id_token = _clean_text(payload.get("idToken"))
    if id_token is None:
        raise JPMarketDataFetchError("J-Quants auth_refresh did not return idToken.")

    return id_token


def fetch_jquants_statements_payload(
    *,
    base_url: str,
    id_token: str,
    local_code: str,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    url = _jquants_url(base_url, JQUANTS_STATEMENTS_PATH)
    response = http_get(
        url,
        params={"code": local_code},
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise JPMarketDataFetchError(
            f"J-Quants statements failed: HTTP {response.status_code}."
        )

    return response.json(), response.url


def _jquants_statement_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("statements")
    if rows is None:
        rows = payload.get("data")

    if rows is None:
        return []

    if not isinstance(rows, list):
        raise JPMarketDataFetchError("J-Quants statements payload is not a list.")

    return [row for row in rows if isinstance(row, dict)]


def _statement_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(_row_value(row, "DisclosedDate", "disclosedDate") or ""),
        str(_row_value(row, "DisclosedTime", "disclosedTime") or ""),
        str(_row_value(row, "DisclosureNumber", "disclosureNumber") or ""),
    )


def _latest_jquants_statement(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = _jquants_statement_rows(payload)
    if not rows:
        return None

    return max(rows, key=_statement_sort_key)


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None

    return float(numerator) / float(denominator)


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


def fetch_yahoo_quote_summary_payload(
    *,
    symbol: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_jp_symbol(symbol)
    response = http_get(
        YAHOO_QUOTE_SUMMARY_URL.format(symbol=quote(normalized_symbol, safe="")),
        params={"modules": ",".join(YAHOO_QUOTE_SUMMARY_MODULES)},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise JPMarketDataFetchError("Yahoo quote summary returned a non-object JSON payload.")

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


def _quote_summary_result(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("quoteSummary", {}).get("error")
    if error:
        raise JPMarketDataFetchError(str(error))

    result = (payload.get("quoteSummary", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise JPMarketDataFetchError("Yahoo quote summary payload does not contain result data.")

    return result


def parse_yahoo_company_fundamental(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "yahoo_quote_summary",
    source_url: str | None = None,
) -> JPCompanyFundamentalRecord:
    normalized_symbol = normalize_jp_symbol(symbol)
    result = _quote_summary_result(payload)
    price = result.get("price") if isinstance(result.get("price"), dict) else {}
    profile = result.get("assetProfile") if isinstance(result.get("assetProfile"), dict) else {}
    summary = result.get("summaryDetail") if isinstance(result.get("summaryDetail"), dict) else {}
    statistics = (
        result.get("defaultKeyStatistics")
        if isinstance(result.get("defaultKeyStatistics"), dict)
        else {}
    )
    financial = result.get("financialData") if isinstance(result.get("financialData"), dict) else {}
    calendar = result.get("calendarEvents") if isinstance(result.get("calendarEvents"), dict) else {}
    earnings = calendar.get("earnings") if isinstance(calendar.get("earnings"), dict) else {}

    discovered_symbol = normalize_jp_symbol(
        _yahoo_text(price.get("symbol"))
        or _yahoo_text(price.get("underlyingSymbol"))
        or normalized_symbol
    )
    if normalized_symbol and discovered_symbol != normalized_symbol:
        raise JPMarketDataFetchError(
            f"Yahoo quote summary symbol mismatch. requested={normalized_symbol} discovered={discovered_symbol}."
        )

    currency = (
        _yahoo_text(financial.get("financialCurrency"))
        or _yahoo_text(price.get("currency"))
        or "JPY"
    )

    return JPCompanyFundamentalRecord(
        provider=provider,
        symbol=discovered_symbol,
        company_name=(
            _yahoo_text(price.get("longName"))
            or _yahoo_text(price.get("shortName"))
            or discovered_symbol
        ),
        exchange=(
            _yahoo_text(price.get("fullExchangeName"))
            or _yahoo_text(price.get("exchangeName"))
            or "Tokyo Stock Exchange"
        ),
        sector=_yahoo_text(profile.get("sector")),
        industry=_yahoo_text(profile.get("industry")),
        currency=currency,
        market_cap=_yahoo_int(price.get("marketCap")) or _yahoo_int(summary.get("marketCap")),
        enterprise_value=_yahoo_int(statistics.get("enterpriseValue")),
        trailing_pe=_yahoo_float(summary.get("trailingPE")) or _yahoo_float(statistics.get("trailingPE")),
        forward_pe=_yahoo_float(summary.get("forwardPE")) or _yahoo_float(statistics.get("forwardPE")),
        price_to_book=_yahoo_float(statistics.get("priceToBook")),
        dividend_yield=_yahoo_float(summary.get("dividendYield")),
        beta=_yahoo_float(summary.get("beta")) or _yahoo_float(statistics.get("beta")),
        disclosed_date=None,
        fiscal_period=None,
        fiscal_year_end=None,
        document_type=None,
        eps_ttm=_yahoo_float(statistics.get("trailingEps")),
        forward_eps=_yahoo_float(statistics.get("forwardEps")),
        revenue_ttm=_yahoo_int(financial.get("totalRevenue")),
        net_sales=None,
        operating_profit=None,
        ordinary_profit=None,
        profit=None,
        forecast_net_sales=None,
        forecast_operating_profit=None,
        forecast_ordinary_profit=None,
        forecast_profit=None,
        gross_margin=_yahoo_float(financial.get("grossMargins")),
        operating_margin=_yahoo_float(financial.get("operatingMargins")),
        profit_margin=_yahoo_float(financial.get("profitMargins")),
        return_on_equity=_yahoo_float(financial.get("returnOnEquity")),
        return_on_assets=_yahoo_float(financial.get("returnOnAssets")),
        revenue_growth=_yahoo_float(financial.get("revenueGrowth")),
        earnings_growth=_yahoo_float(financial.get("earningsGrowth")),
        total_assets=None,
        equity=None,
        equity_to_asset_ratio=None,
        total_cash=_yahoo_int(financial.get("totalCash")),
        total_debt=_yahoo_int(financial.get("totalDebt")),
        operating_cash_flow=None,
        investing_cash_flow=None,
        financing_cash_flow=None,
        debt_to_equity=_yahoo_float(financial.get("debtToEquity")),
        current_ratio=_yahoo_float(financial.get("currentRatio")),
        quick_ratio=_yahoo_float(financial.get("quickRatio")),
        shares_outstanding=_yahoo_int(statistics.get("sharesOutstanding")),
        book_value=_yahoo_float(statistics.get("bookValue")),
        earnings_date=_yahoo_date(earnings.get("earningsDate")),
        ex_dividend_date=_yahoo_date(calendar.get("exDividendDate")),
        source_url=source_url,
        raw_payload_hash=_payload_hash(payload),
    )


def _jquants_local_code(row: dict[str, Any]) -> str | None:
    return _clean_code(_row_value(row, "LocalCode", "Code", "localCode", "code"))


def _jquants_int(row: dict[str, Any], *names: str) -> int | None:
    return _parse_int(_row_value(row, *names))


def _jquants_float(row: dict[str, Any], *names: str) -> float | None:
    return _parse_float(_row_value(row, *names))


def _jquants_text(row: dict[str, Any], *names: str) -> str | None:
    return _clean_text(_row_value(row, *names))


def _jquants_date(row: dict[str, Any], *names: str) -> date | None:
    return _parse_date_value(_row_value(row, *names))


def _period_end_for_growth(row: dict[str, Any]) -> date | None:
    return (
        _jquants_date(row, "CurrentPeriodEndDate", "currentPeriodEndDate")
        or _jquants_date(row, "CurrentFiscalYearEndDate", "currentFiscalYearEndDate")
    )


def _find_previous_jquants_statement(
    rows: list[dict[str, Any]],
    latest: dict[str, Any],
) -> dict[str, Any] | None:
    latest_code = _jquants_local_code(latest)
    latest_period = _jquants_text(latest, "TypeOfCurrentPeriod", "typeOfCurrentPeriod")
    latest_end = _period_end_for_growth(latest)
    if latest_code is None or latest_end is None:
        return None

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if row is latest:
            continue
        if _jquants_local_code(row) != latest_code:
            continue
        if latest_period and _jquants_text(row, "TypeOfCurrentPeriod", "typeOfCurrentPeriod") != latest_period:
            continue

        row_end = _period_end_for_growth(row)
        if row_end is None or row_end >= latest_end:
            continue
        candidates.append(row)

    if not candidates:
        return None

    return max(candidates, key=lambda row: _period_end_for_growth(row) or date.min)


def _growth_rate(current: int | None, previous: int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None

    return (current - previous) / abs(previous)


def parse_jquants_company_fundamental(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "jquants_statements",
    source_url: str | None = None,
    company_name: str | None = None,
    exchange: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
) -> JPCompanyFundamentalRecord | None:
    normalized_symbol = normalize_jp_symbol(symbol)
    rows = _jquants_statement_rows(payload)
    latest = _latest_jquants_statement(payload)
    if latest is None:
        return None

    local_code = _jquants_local_code(latest)
    if local_code is not None and local_code_from_symbol(normalized_symbol) != local_code:
        raise JPMarketDataFetchError(
            f"J-Quants statements code mismatch. requested={normalized_symbol} discovered={local_code}."
        )

    previous = _find_previous_jquants_statement(rows, latest)
    net_sales = _jquants_int(latest, "NetSales", "netSales")
    operating_profit = _jquants_int(latest, "OperatingProfit", "operatingProfit")
    ordinary_profit = _jquants_int(latest, "OrdinaryProfit", "ordinaryProfit")
    profit = _jquants_int(latest, "Profit", "profit")
    total_assets = _jquants_int(latest, "TotalAssets", "totalAssets")
    equity = _jquants_int(latest, "Equity", "equity")
    total_cash = _jquants_int(latest, "CashAndEquivalents", "cashAndEquivalents")
    total_debt = _jquants_int(latest, "InterestBearingDebt", "interestBearingDebt")
    shares_outstanding = _jquants_int(
        latest,
        "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "numberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "AverageNumberOfShares",
        "averageNumberOfShares",
    )
    previous_net_sales = _jquants_int(previous or {}, "NetSales", "netSales")
    previous_profit = _jquants_int(previous or {}, "Profit", "profit")

    return JPCompanyFundamentalRecord(
        provider=provider,
        symbol=normalized_symbol,
        company_name=company_name or normalized_symbol,
        exchange=exchange or "Tokyo Stock Exchange",
        sector=sector,
        industry=industry,
        currency="JPY",
        market_cap=None,
        enterprise_value=None,
        trailing_pe=None,
        forward_pe=None,
        price_to_book=None,
        dividend_yield=None,
        beta=None,
        disclosed_date=_jquants_date(latest, "DisclosedDate", "disclosedDate"),
        fiscal_period=_jquants_text(latest, "TypeOfCurrentPeriod", "typeOfCurrentPeriod"),
        fiscal_year_end=_jquants_date(latest, "CurrentFiscalYearEndDate", "currentFiscalYearEndDate"),
        document_type=_jquants_text(latest, "TypeOfDocument", "typeOfDocument"),
        eps_ttm=_jquants_float(latest, "EarningsPerShare", "earningsPerShare"),
        forward_eps=_jquants_float(latest, "ForecastEarningsPerShare", "forecastEarningsPerShare"),
        revenue_ttm=net_sales,
        net_sales=net_sales,
        operating_profit=operating_profit,
        ordinary_profit=ordinary_profit,
        profit=profit,
        forecast_net_sales=_jquants_int(latest, "ForecastNetSales", "forecastNetSales"),
        forecast_operating_profit=_jquants_int(
            latest,
            "ForecastOperatingProfit",
            "forecastOperatingProfit",
        ),
        forecast_ordinary_profit=_jquants_int(
            latest,
            "ForecastOrdinaryProfit",
            "forecastOrdinaryProfit",
        ),
        forecast_profit=_jquants_int(latest, "ForecastProfit", "forecastProfit"),
        gross_margin=None,
        operating_margin=_ratio(operating_profit, net_sales),
        profit_margin=_ratio(profit, net_sales),
        return_on_equity=_ratio(profit, equity),
        return_on_assets=_ratio(profit, total_assets),
        revenue_growth=_growth_rate(net_sales, previous_net_sales),
        earnings_growth=_growth_rate(profit, previous_profit),
        total_assets=total_assets,
        equity=equity,
        equity_to_asset_ratio=_jquants_float(
            latest,
            "EquityToAssetRatio",
            "equityToAssetRatio",
        ),
        total_cash=total_cash,
        total_debt=total_debt,
        operating_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromOperatingActivities",
            "cashFlowsFromOperatingActivities",
        ),
        investing_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromInvestingActivities",
            "cashFlowsFromInvestingActivities",
        ),
        financing_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromFinancingActivities",
            "cashFlowsFromFinancingActivities",
        ),
        debt_to_equity=_ratio(total_debt, equity),
        current_ratio=None,
        quick_ratio=None,
        shares_outstanding=shares_outstanding,
        book_value=_jquants_float(latest, "BookValuePerShare", "bookValuePerShare"),
        earnings_date=_jquants_date(latest, "DisclosedDate", "disclosedDate"),
        ex_dividend_date=None,
        source_url=source_url,
        raw_payload_hash=_payload_hash(payload),
    )
