from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.jp_market.errors import JPMarketDataFetchError
from app.jp_market.providers import jpx, jquants, yahoo
from app.jp_market.symbols import local_code_from_symbol, normalize_jp_symbol


YAHOO_INSTRUMENT_TYPES = {
    "EQUITY": "stock",
    "ETF": "ETF",
    "INDEX": "index",
    "MUTUALFUND": "fund",
    "REIT": "REIT",
}


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


@dataclass(frozen=True)
class JPMarginInterestRecord:
    provider: str
    symbol: str
    report_date: date
    short_volume: int | None
    long_volume: int | None
    short_negotiable_volume: int | None
    long_negotiable_volume: int | None
    short_standardized_volume: int | None
    long_standardized_volume: int | None
    issue_type: str | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class JPInvestorTypeRecord:
    provider: str
    section: str
    published_date: date | None
    start_date: date | None
    end_date: date | None
    proprietary_sell: int | None
    proprietary_buy: int | None
    proprietary_total: int | None
    proprietary_balance: int | None
    broker_sell: int | None
    broker_buy: int | None
    broker_total: int | None
    broker_balance: int | None
    total_sell: int | None
    total_buy: int | None
    total_traded: int | None
    total_balance: int | None
    individual_sell: int | None
    individual_buy: int | None
    individual_total: int | None
    individual_balance: int | None
    foreign_sell: int | None
    foreign_buy: int | None
    foreign_total: int | None
    foreign_balance: int | None
    investment_trust_sell: int | None
    investment_trust_buy: int | None
    investment_trust_total: int | None
    investment_trust_balance: int | None
    trust_bank_sell: int | None
    trust_bank_buy: int | None
    trust_bank_total: int | None
    trust_bank_balance: int | None
    source_url: str | None
    raw_payload_hash: str | None


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


def fetch_jquants_refresh_token(
    *,
    base_url: str,
    mail_address: str,
    password: str,
    timeout_seconds: int = 30,
) -> str:
    return jquants.fetch_jquants_refresh_token(
        base_url=base_url,
        mail_address=mail_address,
        password=password,
        timeout_seconds=timeout_seconds,
    )


def fetch_jquants_id_token(
    *,
    base_url: str,
    refresh_token: str,
    timeout_seconds: int = 30,
) -> str:
    return jquants.fetch_jquants_id_token(
        base_url=base_url,
        refresh_token=refresh_token,
        timeout_seconds=timeout_seconds,
    )


def fetch_jquants_statements_payload(
    *,
    base_url: str,
    id_token: str,
    local_code: str,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    return jquants.fetch_jquants_statements_payload(
        base_url=base_url,
        id_token=id_token,
        local_code=local_code,
        timeout_seconds=timeout_seconds,
    )


def fetch_jquants_summary_payload(
    *,
    base_url: str,
    api_key: str,
    local_code: str,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    return jquants.fetch_jquants_summary_payload(
        base_url=base_url,
        api_key=api_key,
        local_code=local_code,
        timeout_seconds=timeout_seconds,
    )


def fetch_jquants_margin_interest_payload(
    *,
    base_url: str,
    api_key: str,
    local_code: str,
    from_date: date | None = None,
    to_date: date | None = None,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    return jquants.fetch_jquants_margin_interest_payload(
        base_url=base_url,
        api_key=api_key,
        local_code=local_code,
        from_date=from_date,
        to_date=to_date,
        timeout_seconds=timeout_seconds,
    )


def fetch_jquants_investor_types_payload(
    *,
    base_url: str,
    api_key: str,
    section: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    return jquants.fetch_jquants_investor_types_payload(
        base_url=base_url,
        api_key=api_key,
        section=section,
        from_date=from_date,
        to_date=to_date,
        timeout_seconds=timeout_seconds,
    )


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
        str(_row_value(row, "DisclosedDate", "disclosedDate", "DiscDate") or ""),
        str(_row_value(row, "DisclosedTime", "disclosedTime", "DiscTime") or ""),
        str(_row_value(row, "DisclosureNumber", "disclosureNumber", "DiscNo") or ""),
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
    return jpx.fetch_jpx_listed_issues_workbook(
        timeout_seconds=timeout_seconds,
    )


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return yahoo.fetch_yahoo_chart_payload(
        symbol=symbol,
        range_value=range_value,
        interval=interval,
        timeout_seconds=timeout_seconds,
    )


def fetch_yahoo_quote_summary_payload(
    *,
    symbol: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return yahoo.fetch_yahoo_quote_summary_payload(
        symbol=symbol,
        timeout_seconds=timeout_seconds,
    )


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


def _jp_intraday_session(value: datetime) -> str:
    local = value.astimezone(timezone(timedelta(hours=9)))
    minutes = local.hour * 60 + local.minute + local.second / 60

    if 9 * 60 <= minutes <= 11 * 60 + 30:
        return "regular"
    if 12 * 60 + 30 <= minutes <= 15 * 60 + 30:
        return "regular"
    if 11 * 60 + 30 < minutes < 12 * 60 + 30:
        return "lunch_break"
    if minutes < 9 * 60:
        return "pre_market"
    return "post_close"


def parse_yahoo_intraday_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    source_url: str | None = None,
) -> dict:
    normalized_symbol = normalize_jp_symbol(symbol)
    result = _chart_result(payload)
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0] or {}
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 32400)
    tz = timezone(timedelta(seconds=offset))

    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    points: list[dict] = []

    for index, timestamp in enumerate(timestamps):
        price = _parse_float(_list_value(closes, index))
        if price is None:
            continue

        point_time = datetime.fromtimestamp(int(timestamp), tz=tz)
        points.append(
            {
                "time": point_time.isoformat(),
                "session": _jp_intraday_session(point_time),
                "price": price,
                "volume": _parse_int(_list_value(volumes, index)),
                "open": _parse_float(_list_value(opens, index)),
                "high": _parse_float(_list_value(highs, index)),
                "low": _parse_float(_list_value(lows, index)),
            }
        )

    regular_points = [point for point in points if point.get("session") == "regular"]
    latest_point = points[-1] if points else None
    latest_regular_point = regular_points[-1] if regular_points else None
    previous_close = (
        _parse_float(meta.get("chartPreviousClose"))
        or _parse_float(meta.get("previousClose"))
        or _parse_float(meta.get("regularMarketPreviousClose"))
    )
    warnings: list[str] = []
    if not points:
        warnings.append("Yahoo chart returned no Japan intraday points.")

    return {
        "stock_id": normalized_symbol,
        "symbol": normalized_symbol,
        "source": "yahoo_finance_chart" if points else "unavailable",
        "session_scope": "regular",
        "session_phase": latest_point.get("session") if latest_point else None,
        "has_extended_hours": False,
        "regular_point_count": len(regular_points),
        "extended_point_count": 0,
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
    code = _clean_code(_row_value(row, "LocalCode", "Code", "localCode", "code"))
    if code and re.fullmatch(r"[0-9A-Z]{4}0", code):
        return code[:4]

    return code


def _jquants_int(row: dict[str, Any], *names: str) -> int | None:
    return _parse_int(_row_value(row, *names))


def _jquants_float(row: dict[str, Any], *names: str) -> float | None:
    return _parse_float(_row_value(row, *names))


def _jquants_text(row: dict[str, Any], *names: str) -> str | None:
    return _clean_text(_row_value(row, *names))


def _jquants_date(row: dict[str, Any], *names: str) -> date | None:
    return _parse_date_value(_row_value(row, *names))


def _jquants_data_rows(payload: dict[str, Any], *, resource_name: str) -> list[dict[str, Any]]:
    rows = payload.get("data")
    if rows is None:
        rows = payload.get(resource_name)

    if rows is None:
        return []

    if not isinstance(rows, list):
        raise JPMarketDataFetchError(f"J-Quants {resource_name} payload is not a list.")

    return [row for row in rows if isinstance(row, dict)]


def parse_jquants_margin_interest_records(
    payload: dict[str, Any],
    *,
    symbol: str,
    source_url: str | None = None,
    provider: str = "jquants_margin_interest",
) -> list[JPMarginInterestRecord]:
    normalized_symbol = normalize_jp_symbol(symbol)
    payload_hash = _payload_hash(payload)
    records: list[JPMarginInterestRecord] = []

    for row in _jquants_data_rows(payload, resource_name="margin_interest"):
        report_date = _jquants_date(row, "Date", "date")
        if report_date is None:
            continue

        records.append(
            JPMarginInterestRecord(
                provider=provider,
                symbol=normalized_symbol,
                report_date=report_date,
                short_volume=_jquants_int(row, "ShrtVol", "shortVolume", "short_volume"),
                long_volume=_jquants_int(row, "LongVol", "longVolume", "long_volume"),
                short_negotiable_volume=_jquants_int(
                    row,
                    "ShrtNegVol",
                    "shortNegotiableVolume",
                    "short_negotiable_volume",
                ),
                long_negotiable_volume=_jquants_int(
                    row,
                    "LongNegVol",
                    "longNegotiableVolume",
                    "long_negotiable_volume",
                ),
                short_standardized_volume=_jquants_int(
                    row,
                    "ShrtStdVol",
                    "shortStandardizedVolume",
                    "short_standardized_volume",
                ),
                long_standardized_volume=_jquants_int(
                    row,
                    "LongStdVol",
                    "longStandardizedVolume",
                    "long_standardized_volume",
                ),
                issue_type=_jquants_text(row, "IssType", "issueType", "issue_type"),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return records


def parse_jquants_investor_type_records(
    payload: dict[str, Any],
    *,
    source_url: str | None = None,
    provider: str = "jquants_investor_types",
) -> list[JPInvestorTypeRecord]:
    payload_hash = _payload_hash(payload)
    records: list[JPInvestorTypeRecord] = []

    for row in _jquants_data_rows(payload, resource_name="investor_types"):
        section = _jquants_text(row, "Section", "section")
        if section is None:
            continue

        records.append(
            JPInvestorTypeRecord(
                provider=provider,
                section=section,
                published_date=_jquants_date(row, "PubDate", "PublishedDate", "publishedDate"),
                start_date=_jquants_date(row, "StDate", "StartDate", "startDate"),
                end_date=_jquants_date(row, "EnDate", "EndDate", "endDate"),
                proprietary_sell=_jquants_int(row, "PropSell", "proprietarySell"),
                proprietary_buy=_jquants_int(row, "PropBuy", "proprietaryBuy"),
                proprietary_total=_jquants_int(row, "PropTot", "proprietaryTotal"),
                proprietary_balance=_jquants_int(row, "PropBal", "proprietaryBalance"),
                broker_sell=_jquants_int(row, "BrkSell", "brokerSell"),
                broker_buy=_jquants_int(row, "BrkBuy", "brokerBuy"),
                broker_total=_jquants_int(row, "BrkTot", "brokerTotal"),
                broker_balance=_jquants_int(row, "BrkBal", "brokerBalance"),
                total_sell=_jquants_int(row, "TotSell", "totalSell"),
                total_buy=_jquants_int(row, "TotBuy", "totalBuy"),
                total_traded=_jquants_int(row, "TotTot", "totalTraded"),
                total_balance=_jquants_int(row, "TotBal", "totalBalance"),
                individual_sell=_jquants_int(row, "IndSell", "individualSell"),
                individual_buy=_jquants_int(row, "IndBuy", "individualBuy"),
                individual_total=_jquants_int(row, "IndTot", "individualTotal"),
                individual_balance=_jquants_int(row, "IndBal", "individualBalance"),
                foreign_sell=_jquants_int(row, "FrgnSell", "foreignSell"),
                foreign_buy=_jquants_int(row, "FrgnBuy", "foreignBuy"),
                foreign_total=_jquants_int(row, "FrgnTot", "foreignTotal"),
                foreign_balance=_jquants_int(row, "FrgnBal", "foreignBalance"),
                investment_trust_sell=_jquants_int(row, "InvTrSell", "investmentTrustSell"),
                investment_trust_buy=_jquants_int(row, "InvTrBuy", "investmentTrustBuy"),
                investment_trust_total=_jquants_int(row, "InvTrTot", "investmentTrustTotal"),
                investment_trust_balance=_jquants_int(row, "InvTrBal", "investmentTrustBalance"),
                trust_bank_sell=_jquants_int(row, "TrstBnkSell", "trustBankSell"),
                trust_bank_buy=_jquants_int(row, "TrstBnkBuy", "trustBankBuy"),
                trust_bank_total=_jquants_int(row, "TrstBnkTot", "trustBankTotal"),
                trust_bank_balance=_jquants_int(row, "TrstBnkBal", "trustBankBalance"),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return records


def _period_end_for_growth(row: dict[str, Any]) -> date | None:
    return (
        _jquants_date(row, "CurrentPeriodEndDate", "currentPeriodEndDate", "CurPerEn")
        or _jquants_date(row, "CurrentFiscalYearEndDate", "currentFiscalYearEndDate", "CurFYEn")
    )


def _find_previous_jquants_statement(
    rows: list[dict[str, Any]],
    latest: dict[str, Any],
) -> dict[str, Any] | None:
    latest_code = _jquants_local_code(latest)
    latest_period = _jquants_text(latest, "TypeOfCurrentPeriod", "typeOfCurrentPeriod", "CurPerType")
    latest_end = _period_end_for_growth(latest)
    if latest_code is None or latest_end is None:
        return None

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if row is latest:
            continue
        if _jquants_local_code(row) != latest_code:
            continue
        if latest_period and _jquants_text(row, "TypeOfCurrentPeriod", "typeOfCurrentPeriod", "CurPerType") != latest_period:
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
    net_sales = _jquants_int(latest, "NetSales", "netSales", "Sales", "NCSales")
    operating_profit = _jquants_int(latest, "OperatingProfit", "operatingProfit", "OP", "NCOP")
    ordinary_profit = _jquants_int(latest, "OrdinaryProfit", "ordinaryProfit", "OdP", "NCOdP")
    profit = _jquants_int(latest, "Profit", "profit", "NP", "NCNP")
    total_assets = _jquants_int(latest, "TotalAssets", "totalAssets", "TA", "NCTA")
    equity = _jquants_int(latest, "Equity", "equity", "Eq", "NCEq")
    total_cash = _jquants_int(latest, "CashAndEquivalents", "cashAndEquivalents", "CashEq")
    total_debt = _jquants_int(latest, "InterestBearingDebt", "interestBearingDebt")
    shares_outstanding = _jquants_int(
        latest,
        "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "numberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "ShOutFY",
        "AverageNumberOfShares",
        "averageNumberOfShares",
        "AvgSh",
    )
    previous_net_sales = _jquants_int(previous or {}, "NetSales", "netSales", "Sales", "NCSales")
    previous_profit = _jquants_int(previous or {}, "Profit", "profit", "NP", "NCNP")

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
        disclosed_date=_jquants_date(latest, "DisclosedDate", "disclosedDate", "DiscDate"),
        fiscal_period=_jquants_text(latest, "TypeOfCurrentPeriod", "typeOfCurrentPeriod", "CurPerType"),
        fiscal_year_end=_jquants_date(latest, "CurrentFiscalYearEndDate", "currentFiscalYearEndDate", "CurFYEn"),
        document_type=_jquants_text(latest, "TypeOfDocument", "typeOfDocument", "DocType"),
        eps_ttm=_jquants_float(latest, "EarningsPerShare", "earningsPerShare", "EPS", "NCEPS"),
        forward_eps=_jquants_float(latest, "ForecastEarningsPerShare", "forecastEarningsPerShare", "FEPS", "FNCEPS"),
        revenue_ttm=net_sales,
        net_sales=net_sales,
        operating_profit=operating_profit,
        ordinary_profit=ordinary_profit,
        profit=profit,
        forecast_net_sales=_jquants_int(latest, "ForecastNetSales", "forecastNetSales", "FSales", "FNCSales"),
        forecast_operating_profit=_jquants_int(
            latest,
            "ForecastOperatingProfit",
            "forecastOperatingProfit",
            "FOP",
            "FNCOP",
        ),
        forecast_ordinary_profit=_jquants_int(
            latest,
            "ForecastOrdinaryProfit",
            "forecastOrdinaryProfit",
            "FOdP",
            "FNCOdP",
        ),
        forecast_profit=_jquants_int(latest, "ForecastProfit", "forecastProfit", "FNP", "FNCNP"),
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
            "EqAR",
            "NCEqAR",
        ),
        total_cash=total_cash,
        total_debt=total_debt,
        operating_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromOperatingActivities",
            "cashFlowsFromOperatingActivities",
            "CFO",
        ),
        investing_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromInvestingActivities",
            "cashFlowsFromInvestingActivities",
            "CFI",
        ),
        financing_cash_flow=_jquants_int(
            latest,
            "CashFlowsFromFinancingActivities",
            "cashFlowsFromFinancingActivities",
            "CFF",
        ),
        debt_to_equity=_ratio(total_debt, equity),
        current_ratio=None,
        quick_ratio=None,
        shares_outstanding=shares_outstanding,
        book_value=_jquants_float(latest, "BookValuePerShare", "bookValuePerShare", "BPS", "NCBPS"),
        earnings_date=_jquants_date(latest, "DisclosedDate", "disclosedDate", "DiscDate"),
        ex_dividend_date=None,
        source_url=source_url,
        raw_payload_hash=_payload_hash(payload),
    )
