from __future__ import annotations

import ast
import hashlib
from html.parser import HTMLParser
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

from app.observability.provider_http import (
    ProviderRequestContext,
    get as provider_get,
    post as provider_post,
)


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NAVER_SISE_INDEX_URL = "https://api.finance.naver.com/siseJson.naver"
NAVER_SISE_INDEX_TIME_URL = "https://finance.naver.com/sise/sise_index_time.naver"
NAVER_INDEX_REALTIME_URL = "https://polling.finance.naver.com/api/realtime"
KRX_DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_STOCK_MASTER_BLD = "dbms/MDC/STAT/standard/MDCSTAT01901"
KRX_DAILY_PRICE_BLD = "dbms/MDC/STAT/standard/MDCSTAT01501"
KRX_INVESTOR_TRADE_BLD = "dbms/MDC/STAT/standard/MDCSTAT02401"
OPENDART_SINGLE_ACCOUNT_ALL_PATH = "/fnlttSinglAcntAll.json"
KR_SYMBOL_TOKEN_PATTERN = re.compile(r"^[0-9A-Z][0-9A-Z.\-]{0,31}")
YAHOO_INSTRUMENT_TYPES = {
    "EQUITY": "stock",
    "ETF": "ETF",
    "INDEX": "index",
    "MUTUALFUND": "fund",
    "REIT": "REIT",
}


class KRMarketDataFetchError(Exception):
    pass


def _provider_context(
    *,
    provider: str,
    resource: str,
    target: str = "all",
) -> ProviderRequestContext:
    return ProviderRequestContext(
        market="kr",
        provider=provider,
        resource=resource,
        target=target,
    )


def _provider_get(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    return provider_get(
        _provider_context(provider=provider, resource=resource, target=target),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def _provider_post(
    url: str,
    *,
    provider: str,
    resource: str,
    target: str = "all",
    timeout_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    return provider_post(
        _provider_context(provider=provider, resource=resource, target=target),
        url,
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


@dataclass(frozen=True)
class KRStockRecord:
    symbol: str
    local_code: str | None
    security_name: str | None
    security_name_kr: str | None
    exchange: str | None
    market_segment: str | None
    sector: str | None
    industry: str | None
    asset_type: str
    listing_source: str
    currency: str
    exchange_timezone_name: str | None


@dataclass(frozen=True)
class KRDailyPriceRecord:
    provider: str
    symbol: str
    trade_date: date
    currency: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    adjusted_close: float | None
    price_change: float | None
    change_pct: float | None
    trade_volume: int | None
    trade_value: int | None
    market_cap: int | None
    listed_shares: int | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class KRCompanyFundamentalRecord:
    provider: str
    symbol: str
    corp_code: str | None
    stock_code: str | None
    company_name: str | None
    fiscal_year: int | None
    report_code: str | None
    report_name: str | None
    statement_name: str | None
    account_name: str | None
    account_id: str | None
    current_amount: int | None
    previous_amount: int | None
    currency: str | None
    disclosed_date: date | None
    receipt_no: str | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class KRInvestorTradeRecord:
    provider: str
    symbol: str
    trade_date: date
    investor_type: str
    buy_value: int | None
    sell_value: int | None
    net_buy_value: int | None
    buy_volume: int | None
    sell_volume: int | None
    net_buy_volume: int | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class KRIndexRecord:
    index_id: str
    provider_symbol: str
    name: str
    short_name: str
    name_kr: str | None
    market_segment: str
    index_family: str
    currency: str
    provider: str
    source_url: str | None
    exchange_timezone_name: str
    sort_order: int


@dataclass(frozen=True)
class KRIndexDailyPriceRecord:
    provider: str
    index_id: str
    trade_date: date
    currency: str
    open_value: float | None
    high_value: float | None
    low_value: float | None
    close_value: float | None
    price_change: float | None
    change_pct: float | None
    trade_volume: int | None
    source_url: str | None
    raw_payload_hash: str | None


@dataclass(frozen=True)
class KRIndexIntradayPointRecord:
    index_id: str
    time: datetime
    price: float
    volume: int | None
    cumulative_volume: int | None
    trade_value: int | None


@dataclass(frozen=True)
class KRIndexRealtimeQuoteRecord:
    index_id: str
    provider_symbol: str
    time: datetime | None
    price: float | None
    change: float | None
    change_pct: float | None
    open_value: float | None
    high_value: float | None
    low_value: float | None
    volume: int | None
    trade_value: int | None
    market_status: str | None
    polling_interval_seconds: int | None


KR_INDEX_RECORDS: tuple[KRIndexRecord, ...] = (
    KRIndexRecord(
        index_id="KOSPI",
        provider_symbol="KOSPI",
        name="KOSPI Composite Index",
        short_name="KOSPI",
        name_kr="코스피",
        market_segment="KOSPI",
        index_family="KOSPI",
        currency="KRW",
        provider="naver_sise_index",
        source_url="https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
        exchange_timezone_name="Asia/Seoul",
        sort_order=10,
    ),
    KRIndexRecord(
        index_id="KOSDAQ",
        provider_symbol="KOSDAQ",
        name="KOSDAQ Composite Index",
        short_name="KOSDAQ",
        name_kr="코스닥",
        market_segment="KOSDAQ",
        index_family="KOSDAQ",
        currency="KRW",
        provider="naver_sise_index",
        source_url="https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
        exchange_timezone_name="Asia/Seoul",
        sort_order=20,
    ),
    KRIndexRecord(
        index_id="KOSPI200",
        provider_symbol="KPI200",
        name="KOSPI 200",
        short_name="KOSPI 200",
        name_kr="코스피 200",
        market_segment="KOSPI",
        index_family="KOSPI",
        currency="KRW",
        provider="naver_sise_index",
        source_url="https://finance.naver.com/sise/sise_index.naver?code=KPI200",
        exchange_timezone_name="Asia/Seoul",
        sort_order=30,
    ),
)
KR_INDEX_CONFIG_BY_ID = {record.index_id: record for record in KR_INDEX_RECORDS}
KR_INDEX_ALIAS_TO_ID = {
    record.index_id: record.index_id
    for record in KR_INDEX_RECORDS
}
KR_INDEX_ALIAS_TO_ID.update(
    {
        "KPI200": "KOSPI200",
        "KOSPI_200": "KOSPI200",
        "KOSPI-200": "KOSPI200",
        "^KS11": "KOSPI",
        "^KQ11": "KOSDAQ",
        "^KS200": "KOSPI200",
    }
)


def normalize_kr_symbol(value: str | None) -> str:
    if value is None:
        return ""

    cleaned = str(value).strip().upper()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[-1].strip()

    if "/" in cleaned:
        cleaned = cleaned.split("/", maxsplit=1)[0].strip()

    if " " in cleaned:
        cleaned = cleaned.split(" ", maxsplit=1)[0].strip()

    match = KR_SYMBOL_TOKEN_PATTERN.match(cleaned)
    normalized = match.group(0) if match else cleaned

    if "." in normalized:
        local, suffix = normalized.split(".", maxsplit=1)
        local = _normalize_local_code(local)
        return f"{local}.{suffix}"

    local_code = _normalize_local_code(normalized)
    if local_code:
        return f"{local_code}.KS"

    return normalized


def normalize_kr_index_id(value: str | None) -> str:
    cleaned = (value or "").strip().upper()
    if not cleaned:
        return ""
    return KR_INDEX_ALIAS_TO_ID.get(cleaned, cleaned)


def local_code_from_symbol(symbol: str) -> str:
    normalized_symbol = normalize_kr_symbol(symbol)
    return normalized_symbol.split(".", maxsplit=1)[0]


def _normalize_local_code(value: Any) -> str:
    cleaned = _clean_code(value) or ""
    if re.fullmatch(r"\d{1,6}", cleaned):
        return cleaned.zfill(6)
    return cleaned


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in {"N/A", "NULL", "NONE", "-", "--"}:
        return None

    return cleaned


def _clean_code(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    if re.fullmatch(r"\d+\.0", cleaned):
        cleaned = cleaned[:-2]

    return cleaned.strip().upper()


def _parse_int(value: Any) -> int | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    cleaned = cleaned.replace(",", "").replace("KRW", "").replace("원", "").strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    cleaned = cleaned.replace(",", "").replace("%", "").strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date_value(value: Any) -> date | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def _parse_index_datetime(value: Any) -> datetime | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    return None


def _list_value(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _payload_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _payload_text_hash(payload_text: str) -> str:
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


def _kr_index_scaled_float(value: Any) -> float | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return parsed / 100


def _row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("OutBlock_1", "output", "data", "list", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    return []


def _market_suffix(market_segment: str | None) -> str:
    segment = (market_segment or "").upper()
    if "KOSDAQ" in segment or "코스닥" in segment:
        return "KQ"
    if "KONEX" in segment or "코넥스" in segment:
        return "KX"
    return "KS"


def _asset_type_from_market_segment(market_segment: str | None) -> str:
    segment = (market_segment or "").lower()
    if "etf" in segment:
        return "ETF"
    if "etn" in segment:
        return "ETN"
    if "reit" in segment or "부동산" in segment:
        return "REIT"
    if "index" in segment:
        return "index"
    return "stock"


def _record_from_krx_stock_row(row: dict[str, Any]) -> KRStockRecord | None:
    code = _normalize_local_code(
        _row_value(
            row,
            "ISU_SRT_CD",
            "isuSrtCd",
            "Short Code",
            "short_code",
            "stock_code",
            "종목코드",
        )
    )
    if not code:
        return None

    market_segment = _clean_text(
        _row_value(
            row,
            "MKT_TP_NM",
            "market",
            "Market",
            "market_segment",
            "시장구분",
        )
    )
    suffix = _market_suffix(market_segment)
    symbol = f"{code}.{suffix}"

    return KRStockRecord(
        symbol=symbol,
        local_code=code,
        security_name=_clean_text(
            _row_value(row, "ISU_ABBRV", "ISU_NM", "Name", "name", "security_name")
        ),
        security_name_kr=_clean_text(
            _row_value(row, "ISU_NM", "ISU_ABBRV", "한글 종목명", "종목명")
        ),
        exchange="Korea Exchange",
        market_segment=market_segment,
        sector=_clean_text(_row_value(row, "IDX_IND_NM", "sector", "Sector", "업종")),
        industry=_clean_text(_row_value(row, "IND_NM", "industry", "Industry")),
        asset_type=_asset_type_from_market_segment(market_segment),
        listing_source="krx_data",
        currency="KRW",
        exchange_timezone_name="Asia/Seoul",
    )


def parse_krx_stock_records(payload: Any) -> list[KRStockRecord]:
    records: list[KRStockRecord] = []
    seen_symbols: set[str] = set()

    for row in _payload_rows(payload):
        record = _record_from_krx_stock_row(row)
        if record is None or record.symbol in seen_symbols:
            continue
        records.append(record)
        seen_symbols.add(record.symbol)

    return records


def parse_krx_daily_price_records(
    payload: Any,
    *,
    symbol: str | None = None,
    trade_date: date | None = None,
    provider: str = "krx_data",
    source_url: str | None = None,
) -> list[KRDailyPriceRecord]:
    payload_hash = _payload_hash(payload)
    records: list[KRDailyPriceRecord] = []
    requested_symbol = normalize_kr_symbol(symbol) if symbol else None

    for row in _payload_rows(payload):
        row_date = (
            _parse_date_value(_row_value(row, "TRD_DD", "trade_date", "Date", "날짜"))
            or trade_date
        )
        if row_date is None:
            continue

        row_code = _normalize_local_code(
            _row_value(row, "ISU_SRT_CD", "stock_code", "symbol", "종목코드")
        )
        market_segment = _clean_text(_row_value(row, "MKT_NM", "MKT_TP_NM", "market"))
        row_symbol = (
            f"{row_code}.{_market_suffix(market_segment)}"
            if row_code
            else requested_symbol
        )
        if not row_symbol:
            continue

        close_price = _parse_float(
            _row_value(row, "TDD_CLSPRC", "close", "Close", "종가")
        )
        if close_price is None:
            continue

        records.append(
            KRDailyPriceRecord(
                provider=provider,
                symbol=normalize_kr_symbol(row_symbol),
                trade_date=row_date,
                currency="KRW",
                open_price=_parse_float(_row_value(row, "TDD_OPNPRC", "open", "Open", "시가")),
                high_price=_parse_float(_row_value(row, "TDD_HGPRC", "high", "High", "고가")),
                low_price=_parse_float(_row_value(row, "TDD_LWPRC", "low", "Low", "저가")),
                close_price=close_price,
                adjusted_close=None,
                price_change=_parse_float(_row_value(row, "CMPPREVDD_PRC", "change", "대비")),
                change_pct=_parse_float(_row_value(row, "FLUC_RT", "change_pct", "등락률")),
                trade_volume=_parse_int(_row_value(row, "ACC_TRDVOL", "volume", "Volume", "거래량")),
                trade_value=_parse_int(_row_value(row, "ACC_TRDVAL", "trade_value", "거래대금")),
                market_cap=_parse_int(_row_value(row, "MKTCAP", "market_cap", "시가총액")),
                listed_shares=_parse_int(_row_value(row, "LIST_SHRS", "listed_shares", "상장주식수")),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda item: (item.symbol, item.trade_date))


def parse_krx_investor_trade_records(
    payload: Any,
    *,
    symbol: str,
    trade_date: date | None = None,
    provider: str = "krx_investor_trading",
    source_url: str | None = None,
) -> list[KRInvestorTradeRecord]:
    normalized_symbol = normalize_kr_symbol(symbol)
    payload_hash = _payload_hash(payload)
    records: list[KRInvestorTradeRecord] = []

    for row in _payload_rows(payload):
        row_date = (
            _parse_date_value(_row_value(row, "TRD_DD", "trade_date", "Date", "날짜"))
            or trade_date
        )
        investor_type = _clean_text(
            _row_value(row, "INVST_TP_NM", "investor_type", "Investor", "투자자구분")
        )
        if row_date is None or investor_type is None:
            continue

        records.append(
            KRInvestorTradeRecord(
                provider=provider,
                symbol=normalized_symbol,
                trade_date=row_date,
                investor_type=investor_type,
                buy_value=_parse_int(_row_value(row, "ASK_TRDVAL", "buy_value", "매수거래대금")),
                sell_value=_parse_int(_row_value(row, "BID_TRDVAL", "sell_value", "매도거래대금")),
                net_buy_value=_parse_int(_row_value(row, "NETBID_TRDVAL", "net_buy_value", "순매수거래대금")),
                buy_volume=_parse_int(_row_value(row, "ASK_TRDVOL", "buy_volume", "매수거래량")),
                sell_volume=_parse_int(_row_value(row, "BID_TRDVOL", "sell_volume", "매도거래량")),
                net_buy_volume=_parse_int(_row_value(row, "NETBID_TRDVOL", "net_buy_volume", "순매수거래량")),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return records


def _chart_result(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("chart", {}).get("error")
    if error:
        raise KRMarketDataFetchError(str(error))

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise KRMarketDataFetchError("Yahoo chart payload does not contain chart result data.")

    return result


def parse_yahoo_stock_record(payload: dict[str, Any], *, symbol: str) -> KRStockRecord:
    normalized_symbol = normalize_kr_symbol(symbol)
    result = _chart_result(payload)
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    discovered_symbol = normalize_kr_symbol(meta.get("symbol") or normalized_symbol)
    if normalized_symbol and discovered_symbol != normalized_symbol:
        raise KRMarketDataFetchError(
            f"Yahoo chart symbol mismatch. requested={normalized_symbol} discovered={discovered_symbol}."
        )

    instrument_type = str(meta.get("instrumentType") or "").upper()
    exchange_name = _clean_text(meta.get("fullExchangeName") or meta.get("exchangeName"))

    return KRStockRecord(
        symbol=discovered_symbol,
        local_code=local_code_from_symbol(discovered_symbol),
        security_name=_clean_text(meta.get("longName") or meta.get("shortName")),
        security_name_kr=None,
        exchange=exchange_name or "Korea Exchange",
        market_segment=_clean_text(meta.get("exchangeName")),
        sector=None,
        industry=None,
        asset_type=YAHOO_INSTRUMENT_TYPES.get(instrument_type, "unknown"),
        listing_source="discovered_yahoo_chart",
        currency=_clean_text(meta.get("currency")) or "KRW",
        exchange_timezone_name=_clean_text(meta.get("exchangeTimezoneName")) or "Asia/Seoul",
    )


def parse_yahoo_daily_prices(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "yahoo_chart",
    source_url: str | None = None,
) -> list[KRDailyPriceRecord]:
    normalized_symbol = normalize_kr_symbol(symbol)
    result = _chart_result(payload)
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    discovered_symbol = normalize_kr_symbol(meta.get("symbol") or normalized_symbol)
    if normalized_symbol and discovered_symbol != normalized_symbol:
        raise KRMarketDataFetchError(
            f"Yahoo chart symbol mismatch. requested={normalized_symbol} discovered={discovered_symbol}."
        )

    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote_values = (indicators.get("quote") or [{}])[0] or {}
    adjusted_values = (indicators.get("adjclose") or [{}])[0] or {}
    tz = timezone.utc
    offset = _parse_int(meta.get("gmtoffset"))
    if offset is not None:
        tz = timezone(timedelta(seconds=offset))
    currency = _clean_text(meta.get("currency")) or "KRW"

    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    adjusted_closes = adjusted_values.get("adjclose") or []
    payload_hash = _payload_hash(payload)
    records: list[KRDailyPriceRecord] = []

    for index, timestamp in enumerate(timestamps):
        close_price = _parse_float(_list_value(closes, index))
        adjusted_close = _parse_float(_list_value(adjusted_closes, index))
        if close_price is None and adjusted_close is None:
            continue

        records.append(
            KRDailyPriceRecord(
                provider=provider,
                symbol=discovered_symbol,
                trade_date=datetime.fromtimestamp(int(timestamp), tz=tz).date(),
                currency=currency,
                open_price=_parse_float(_list_value(opens, index)),
                high_price=_parse_float(_list_value(highs, index)),
                low_price=_parse_float(_list_value(lows, index)),
                close_price=close_price,
                adjusted_close=adjusted_close,
                price_change=None,
                change_pct=None,
                trade_volume=_parse_int(_list_value(volumes, index)),
                trade_value=None,
                market_cap=None,
                listed_shares=None,
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return sorted(records, key=lambda item: item.trade_date)


def _parse_naver_index_rows(payload_text: str) -> list[list[Any]]:
    text = payload_text.strip()
    if not text:
        raise KRMarketDataFetchError("Naver index payload was empty.")

    try:
        payload = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        raise KRMarketDataFetchError("Naver index payload was not a valid array.") from exc

    if not isinstance(payload, list):
        raise KRMarketDataFetchError("Naver index payload was not a list.")

    return [row for row in payload if isinstance(row, list)]


def parse_naver_index_daily_prices(
    payload_text: str,
    *,
    index_id: str,
    provider: str = "naver_sise_index",
    source_url: str | None = None,
) -> list[KRIndexDailyPriceRecord]:
    normalized_index_id = normalize_kr_index_id(index_id)
    if normalized_index_id not in KR_INDEX_CONFIG_BY_ID:
        supported = ", ".join(sorted(KR_INDEX_CONFIG_BY_ID))
        raise KRMarketDataFetchError(f"Unsupported KR index_id='{index_id}'. Supported: {supported}.")

    rows = _parse_naver_index_rows(payload_text)
    payload_hash = _payload_text_hash(payload_text)
    records: list[KRIndexDailyPriceRecord] = []
    previous_close: float | None = None

    for row in rows:
        if len(row) < 6:
            continue

        row_date = _parse_date_value(_list_value(row, 0))
        close_value = _parse_float(_list_value(row, 4))
        if row_date is None or close_value is None:
            continue

        price_change = None
        change_pct = None
        if previous_close is not None and previous_close != 0:
            price_change = close_value - previous_close
            change_pct = (price_change / previous_close) * 100

        records.append(
            KRIndexDailyPriceRecord(
                provider=provider,
                index_id=normalized_index_id,
                trade_date=row_date,
                currency=KR_INDEX_CONFIG_BY_ID[normalized_index_id].currency,
                open_value=_parse_float(_list_value(row, 1)),
                high_value=_parse_float(_list_value(row, 2)),
                low_value=_parse_float(_list_value(row, 3)),
                close_value=close_value,
                price_change=price_change,
                change_pct=change_pct,
                trade_volume=_parse_int(_list_value(row, 5)),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )
        previous_close = close_value

    if not records:
        raise KRMarketDataFetchError(f"Naver index returned no OHLC rows for index_id='{normalized_index_id}'.")

    return records


class _NaverIndexTimeTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._capture_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._current_row = []
            return

        if tag.lower() != "td" or self._current_row is None:
            return

        attr_map = {name.lower(): value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())
        self._capture_cell = bool(
            classes.intersection({"date", "number_1", "rate_up", "rate_down", "rate_same"})
        )
        self._current_cell = [] if self._capture_cell else None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "td" and self._current_row is not None and self._current_cell is not None:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            self._current_cell = None
            self._capture_cell = False
            return

        if tag.lower() == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None
            self._capture_cell = False


def _parse_intraday_trade_date(thistime: str | None) -> date:
    parsed = _parse_index_datetime(thistime)
    if parsed is not None:
        return parsed.date()
    return datetime.now(timezone(timedelta(hours=9))).date()


def _parse_intraday_time(value: str, *, trade_date: date) -> datetime | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    return datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        hour,
        minute,
        tzinfo=timezone(timedelta(hours=9)),
    )


def parse_naver_index_intraday_points(
    payload_text: str,
    *,
    index_id: str,
    thistime: str | None = None,
) -> list[KRIndexIntradayPointRecord]:
    normalized_index_id = normalize_kr_index_id(index_id)
    if normalized_index_id not in KR_INDEX_CONFIG_BY_ID:
        supported = ", ".join(sorted(KR_INDEX_CONFIG_BY_ID))
        raise KRMarketDataFetchError(f"Unsupported KR index_id='{index_id}'. Supported: {supported}.")

    parser = _NaverIndexTimeTableParser()
    parser.feed(payload_text)
    trade_date = _parse_intraday_trade_date(thistime)
    records: list[KRIndexIntradayPointRecord] = []

    for row in parser.rows:
        if len(row) < 2:
            continue
        row_time = _parse_intraday_time(row[0], trade_date=trade_date)
        price = _parse_float(row[1])
        if row_time is None or price is None:
            continue

        records.append(
            KRIndexIntradayPointRecord(
                index_id=normalized_index_id,
                time=row_time,
                price=price,
                volume=_parse_int(_list_value(row, 3)),
                cumulative_volume=_parse_int(_list_value(row, 4)),
                trade_value=_parse_int(_list_value(row, 5)),
            )
        )

    return sorted(records, key=lambda item: item.time)


def parse_naver_index_realtime_quote(
    payload: dict[str, Any],
    *,
    index_id: str,
) -> KRIndexRealtimeQuoteRecord:
    normalized_index_id = normalize_kr_index_id(index_id)
    if normalized_index_id not in KR_INDEX_CONFIG_BY_ID:
        supported = ", ".join(sorted(KR_INDEX_CONFIG_BY_ID))
        raise KRMarketDataFetchError(f"Unsupported KR index_id='{index_id}'. Supported: {supported}.")

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    areas = result.get("areas") if isinstance(result.get("areas"), list) else []
    data: dict[str, Any] | None = None
    for area in areas:
        if not isinstance(area, dict):
            continue
        rows = area.get("datas") if isinstance(area.get("datas"), list) else []
        for row in rows:
            if isinstance(row, dict):
                data = row
                break
        if data is not None:
            break

    if data is None:
        raise KRMarketDataFetchError("Naver realtime index payload did not contain index data.")

    payload_time = _parse_int(result.get("time"))
    quote_time = (
        datetime.fromtimestamp(payload_time / 1000, tz=timezone(timedelta(hours=9)))
        if payload_time is not None
        else None
    )
    polling_interval_ms = _parse_int(result.get("pollingInterval"))

    return KRIndexRealtimeQuoteRecord(
        index_id=normalized_index_id,
        provider_symbol=_clean_text(data.get("cd")) or KR_INDEX_CONFIG_BY_ID[normalized_index_id].provider_symbol,
        time=quote_time,
        price=_kr_index_scaled_float(data.get("nv")),
        change=_kr_index_scaled_float(data.get("cv")),
        change_pct=_parse_float(data.get("cr")),
        open_value=_kr_index_scaled_float(data.get("ov")),
        high_value=_kr_index_scaled_float(data.get("hv")),
        low_value=_kr_index_scaled_float(data.get("lv")),
        volume=_parse_int(data.get("aq")),
        trade_value=_parse_int(data.get("aa")),
        market_status=_clean_text(data.get("ms")),
        polling_interval_seconds=(
            max(1, int(polling_interval_ms / 1000))
            if polling_interval_ms is not None
            else None
        ),
    )


def parse_opendart_company_fundamental_records(
    payload: dict[str, Any],
    *,
    symbol: str,
    provider: str = "opendart_fnltt_singl_acnt_all",
    source_url: str | None = None,
) -> list[KRCompanyFundamentalRecord]:
    status = _clean_text(payload.get("status"))
    message = _clean_text(payload.get("message"))
    if status and status != "000":
        raise KRMarketDataFetchError(f"OpenDART returned status={status}: {message or 'unknown error'}.")

    normalized_symbol = normalize_kr_symbol(symbol)
    payload_hash = _payload_hash(payload)
    records: list[KRCompanyFundamentalRecord] = []

    for row in _payload_rows(payload):
        account_name = _clean_text(_row_value(row, "account_nm", "account_name"))
        statement_name = _clean_text(_row_value(row, "sj_nm", "statement_name"))
        if account_name is None or statement_name is None:
            continue

        fiscal_year = _parse_int(_row_value(row, "bsns_year", "fiscal_year"))
        records.append(
            KRCompanyFundamentalRecord(
                provider=provider,
                symbol=normalized_symbol,
                corp_code=_clean_code(_row_value(row, "corp_code")),
                stock_code=_normalize_local_code(_row_value(row, "stock_code")) or local_code_from_symbol(normalized_symbol),
                company_name=_clean_text(_row_value(row, "corp_name", "company_name")),
                fiscal_year=fiscal_year,
                report_code=_clean_code(_row_value(row, "reprt_code", "report_code")),
                report_name=_clean_text(_row_value(row, "reprt_nm", "report_name")),
                statement_name=statement_name,
                account_name=account_name,
                account_id=_clean_code(_row_value(row, "account_id")),
                current_amount=_parse_int(_row_value(row, "thstrm_amount", "current_amount")),
                previous_amount=_parse_int(_row_value(row, "frmtrm_amount", "previous_amount")),
                currency=_clean_text(_row_value(row, "currency")) or "KRW",
                disclosed_date=_parse_date_value(_row_value(row, "rcept_dt", "disclosed_date")),
                receipt_no=_clean_code(_row_value(row, "rcept_no", "receipt_no")),
                source_url=source_url,
                raw_payload_hash=payload_hash,
            )
        )

    return records


def fetch_naver_index_chart_payload(
    *,
    provider_symbol: str,
    start_date: date,
    end_date: date,
    timeout_seconds: int,
) -> tuple[str, str]:
    response = _provider_get(
        NAVER_SISE_INDEX_URL,
        provider="naver_sise_index",
        resource="index_daily_price",
        target=provider_symbol,
        params={
            "symbol": provider_symbol,
            "requestType": "1",
            "startTime": start_date.strftime("%Y%m%d"),
            "endTime": end_date.strftime("%Y%m%d"),
            "timeframe": "day",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/plain,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    response.encoding = response.encoding or "utf-8"
    return response.text, response.url


def fetch_naver_index_intraday_page_payload(
    *,
    provider_symbol: str,
    thistime: str,
    page: int,
    timeout_seconds: int,
) -> tuple[str, str]:
    response = _provider_get(
        NAVER_SISE_INDEX_TIME_URL,
        provider="naver_sise_index",
        resource="index_intraday",
        target=provider_symbol,
        params={
            "code": provider_symbol,
            "thistime": thistime,
            "page": page,
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "text/html,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    response.encoding = response.encoding or "euc-kr"
    return response.text, response.url


def fetch_naver_index_realtime_payload(
    *,
    provider_symbol: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    response = _provider_get(
        NAVER_INDEX_REALTIME_URL,
        provider="naver_sise_index",
        resource="index_quote",
        target=provider_symbol,
        params={"query": f"SERVICE_INDEX:{provider_symbol}"},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://finance.naver.com/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("Naver realtime index returned a non-object JSON payload.")
    return payload, response.url


def fetch_krx_stock_master_payload(*, timeout_seconds: int) -> tuple[dict[str, Any], str]:
    response = _provider_post(
        KRX_DATA_URL,
        provider="krx_data",
        resource="symbol_master",
        data={
            "bld": KRX_STOCK_MASTER_BLD,
            "mktId": "ALL",
            "share": "1",
            "csvxls_isNo": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.krx.co.kr/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("KRX stock master returned a non-object JSON payload.")
    return payload, response.url


def fetch_krx_daily_price_payload(
    *,
    local_code: str | None = None,
    market_id: str = "ALL",
    trade_date: date | None = None,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    params = {
        "bld": KRX_DAILY_PRICE_BLD,
        "mktId": market_id,
        "isuCd": local_code or "",
        "isuCd2": local_code or "",
        "csvxls_isNo": "false",
    }
    if trade_date is not None:
        params["trdDd"] = trade_date.strftime("%Y%m%d")

    response = _provider_post(
        KRX_DATA_URL,
        provider="krx_data",
        resource="daily_price",
        target=local_code or "all",
        data=params,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.krx.co.kr/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("KRX daily price returned a non-object JSON payload.")
    return payload, response.url


def fetch_krx_investor_trade_payload(
    *,
    local_code: str,
    trade_date: date | None = None,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    params = {
        "bld": KRX_INVESTOR_TRADE_BLD,
        "mktId": "ALL",
        "isuCd": local_code,
        "isuCd2": local_code,
        "csvxls_isNo": "false",
    }
    if trade_date is not None:
        params["trdDd"] = trade_date.strftime("%Y%m%d")

    response = _provider_post(
        KRX_DATA_URL,
        provider="krx_data",
        resource="investor_trading",
        target=local_code,
        data=params,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.krx.co.kr/",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("KRX investor trading returned a non-object JSON payload.")
    return payload, response.url


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_kr_symbol(symbol)
    response = _provider_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider="yahoo_chart",
        resource="daily_price",
        target=normalized_symbol,
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")
    return payload, response.url


def fetch_opendart_financial_statement_payload(
    *,
    base_url: str,
    api_key: str,
    corp_code: str,
    fiscal_year: int,
    report_code: str,
    fs_div: str = "CFS",
    timeout_seconds: int = 30,
) -> tuple[dict[str, Any], str]:
    response = _provider_get(
        f"{base_url.rstrip('/')}{OPENDART_SINGLE_ACCOUNT_ALL_PATH}",
        provider="opendart_fnltt_singl_acnt_all",
        resource="financials",
        target=corp_code,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(fiscal_year),
            "reprt_code": report_code,
            "fs_div": fs_div,
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("OpenDART financial statement returned a non-object JSON payload.")
    return payload, response.url
