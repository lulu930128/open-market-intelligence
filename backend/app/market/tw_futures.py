from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html import unescape
import json
import re
from typing import Any, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    TaiwanFuturesDailyBar,
    TaiwanFuturesIntradayBar,
    TaiwanFuturesQuoteSnapshot,
)
from app.http_client import new_session


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
TAIFEX_MIS_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
TAIFEX_MIS_REFERER = "https://mis.taifex.com.tw/futures/"
TAIFEX_DAILY_REPORT_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
TAIFEX_PROVIDER = "taifex_mis"
TAIFEX_DAILY_PROVIDER = "taifex_daily"
KGI_PROVIDER = "kgi"

SUPPORTED_TAIWAN_FUTURES_SYMBOLS = {"TXF", "MXF", "TMF"}
SUPPORTED_TAIWAN_FUTURES_SESSIONS = {"auto", "regular", "after_hours"}
SUPPORTED_TAIWAN_FUTURES_QUOTE_PROVIDERS = {"auto", TAIFEX_PROVIDER, KGI_PROVIDER}
TAIWAN_FUTURES_SESSION_LABELS = {
    "regular": "日盤",
    "after_hours": "夜盤",
}
TAIWAN_FUTURES_LIVE_QUOTE_MAX_AGE_SECONDS = 180
TAIFEX_MARKET_TYPE_BY_SESSION = {
    "regular": "0",
    "after_hours": "1",
}


class TaiwanFuturesFetchError(RuntimeError):
    """Raised when the Taiwan futures quote source cannot be read safely."""


@dataclass(frozen=True)
class TaiwanFuturesProduct:
    symbol: str
    product_code: str
    product_name: str
    official_code: str
    taifex_cid: str
    monthly_symbol_prefix: str
    multiplier: int
    tick_size: float
    underlying_index_id: str = "TAIEX"


TAIWAN_FUTURES_PRODUCTS: dict[str, TaiwanFuturesProduct] = {
    "TXF": TaiwanFuturesProduct(
        symbol="TXF",
        product_code="TX",
        product_name="大台 台指期",
        official_code="TX",
        taifex_cid="TXF",
        monthly_symbol_prefix="TXF",
        multiplier=200,
        tick_size=1,
    ),
    "MXF": TaiwanFuturesProduct(
        symbol="MXF",
        product_code="MTX",
        product_name="小台 台指期",
        official_code="MTX",
        taifex_cid="MXF",
        monthly_symbol_prefix="MXF",
        multiplier=50,
        tick_size=1,
    ),
    "TMF": TaiwanFuturesProduct(
        symbol="TMF",
        product_code="TMF",
        product_name="微台 台指期",
        official_code="TMF",
        taifex_cid="TMF",
        monthly_symbol_prefix="TMF",
        multiplier=10,
        tick_size=1,
    ),
}


def normalize_taiwan_futures_symbols(symbols: Iterable[str] | str | None = None) -> list[str]:
    if symbols is None:
        return ["TXF", "MXF", "TMF"]

    if isinstance(symbols, str):
        raw_symbols = symbols.split(",")
    else:
        raw_symbols = list(symbols)

    normalized: list[str] = []
    for value in raw_symbols:
        symbol = str(value).strip().upper()
        if not symbol:
            continue
        if symbol not in SUPPORTED_TAIWAN_FUTURES_SYMBOLS:
            raise ValueError(f"Unsupported Taiwan futures symbol: {value}")
        if symbol not in normalized:
            normalized.append(symbol)

    return normalized or ["TXF", "MXF", "TMF"]


def normalize_taiwan_futures_session(session: str | None = None) -> str:
    normalized = (session or "auto").strip().lower()
    if normalized not in SUPPORTED_TAIWAN_FUTURES_SESSIONS:
        raise ValueError(f"Unsupported Taiwan futures session: {session}")
    return normalized


def normalize_taiwan_futures_quote_provider(provider: str | None = None) -> str:
    configured_provider = provider if provider is not None else settings.taiwan_futures_quote_provider
    normalized = (configured_provider or TAIFEX_PROVIDER).strip().lower()
    if normalized not in SUPPORTED_TAIWAN_FUTURES_QUOTE_PROVIDERS:
        raise ValueError(
            "Unsupported Taiwan futures quote provider: "
            f"{configured_provider}. Expected one of: auto, {TAIFEX_PROVIDER}, {KGI_PROVIDER}."
        )
    return normalized


def resolve_taiwan_futures_quote_provider(provider: str | None = None) -> str:
    normalized = normalize_taiwan_futures_quote_provider(provider)
    if normalized == "auto":
        return TAIFEX_PROVIDER
    return normalized


def resolve_taiwan_futures_session(session: str | None = None) -> str:
    normalized = normalize_taiwan_futures_session(session)
    if normalized != "auto":
        return normalized

    now_time = datetime.now(TAIWAN_TZ).time()
    if now_time >= time(15, 0) or now_time <= time(5, 0):
        return "after_hours"
    return "regular"


def _ensure_taiwan_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _session_label(session: str | None) -> str:
    return TAIWAN_FUTURES_SESSION_LABELS.get(str(session or ""), str(session or "未知時段"))


def _format_age_message(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "報價時間無法判定。"
    if age_seconds < 60:
        return "報價剛更新。"
    if age_seconds < 3600:
        return f"報價已 {age_seconds // 60} 分鐘未更新。"
    return f"報價已 {age_seconds // 3600} 小時未更新。"


def build_taiwan_futures_quote_freshness(
    row: TaiwanFuturesQuoteSnapshot,
    *,
    expected_session: str | None = None,
    source_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_expected_session = resolve_taiwan_futures_session(expected_session or "auto")
    quote_time = _ensure_taiwan_datetime(row.quote_time)
    current_time = _ensure_taiwan_datetime(now) or datetime.now(TAIWAN_TZ)
    age_seconds = (
        max(int((current_time - quote_time).total_seconds()), 0)
        if quote_time is not None
        else None
    )
    is_session_mismatch = row.session != resolved_expected_session
    is_stale = (
        age_seconds is None
        or age_seconds > TAIWAN_FUTURES_LIVE_QUOTE_MAX_AGE_SECONDS
    )

    if source_error:
        status_value = "cached"
        message = f"即時來源失敗，使用{_session_label(row.session)}快取。"
    elif is_session_mismatch:
        status_value = "session_mismatch"
        message = (
            f"預期{_session_label(resolved_expected_session)}，"
            f"目前顯示{_session_label(row.session)}快取。"
        )
    elif is_stale:
        status_value = "stale"
        message = _format_age_message(age_seconds)
    else:
        status_value = "live"
        message = "即時報價已同步。"

    return {
        "status": status_value,
        "is_live": status_value == "live",
        "is_stale": is_stale or bool(source_error),
        "is_session_mismatch": is_session_mismatch,
        "expected_session": resolved_expected_session,
        "age_seconds": age_seconds,
        "message": message,
        "source_error": source_error,
    }


def list_taiwan_futures_products() -> list[dict[str, Any]]:
    return [
        {
            "symbol": product.symbol,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "official_code": product.official_code,
            "taifex_cid": product.taifex_cid,
            "multiplier": product.multiplier,
            "tick_size": product.tick_size,
            "underlying_index_id": product.underlying_index_id,
            "regular_session": "08:45-13:45",
            "after_hours_session": "15:00-05:00",
        }
        for product in TAIWAN_FUTURES_PRODUCTS.values()
    ]


def _parse_float(value: Any) -> float | None:
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    return None if parsed is None else int(parsed)


def _parse_signed_float(value: Any) -> float | None:
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text == "-":
        return None

    sign = -1 if "▼" in text else 1
    text = text.replace("▲", "").replace("▼", "").replace("+", "").strip()
    if text.startswith("-"):
        sign = -1
        text = text[1:].strip()

    try:
        return sign * float(text)
    except ValueError:
        return None


def _parse_taifex_date(value: Any) -> date | None:
    text = str(value).strip()
    if not re.fullmatch(r"\d{8}", text):
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _parse_taifex_datetime(date_value: Any, time_value: Any) -> datetime | None:
    quote_date = _parse_taifex_date(date_value)
    time_text = str(time_value or "").strip()
    if quote_date is None or not re.fullmatch(r"\d{6}", time_text):
        return None
    return datetime(
        quote_date.year,
        quote_date.month,
        quote_date.day,
        int(time_text[:2]),
        int(time_text[2:4]),
        int(time_text[4:6]),
        tzinfo=TAIWAN_TZ,
    )


def _infer_session_from_quote_time(quote_time: datetime, fallback: str) -> str:
    quote_clock = quote_time.astimezone(TAIWAN_TZ).time()
    if quote_clock >= time(15, 0) or quote_clock <= time(5, 0):
        return "after_hours"
    if fallback in {"regular", "after_hours"}:
        return fallback
    return "regular"


def _parse_contract_month(disp_ename: Any, quote_time: datetime) -> str | None:
    text = str(disp_ename or "").strip().upper()
    match = re.search(r"(\d{3})$", text)
    if not match:
        return None

    raw = match.group(1)
    month = int(raw[:2])
    year_digit = int(raw[2])
    if month < 1 or month > 12:
        return None

    quote_year = quote_time.astimezone(TAIWAN_TZ).year
    base_year = (quote_year // 10) * 10 + year_digit
    if base_year < quote_year - 1:
        base_year += 10

    return f"{base_year:04d}{month:02d}"


def _strip_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_html_cells(row_html: str) -> list[str]:
    cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, flags=re.IGNORECASE)
    return [_strip_html_text(cell) for cell in cells]


def _build_taifex_daily_report_url(*, product: TaiwanFuturesProduct, trade_date: date) -> str:
    query = urlencode(
        {
            "queryType": "2",
            "marketCode": "0",
            "commodity_id": product.official_code,
            "queryDate": trade_date.strftime("%Y/%m/%d"),
        }
    )
    return f"{TAIFEX_DAILY_REPORT_URL}?{query}"


def _is_monthly_contract(item: dict[str, Any], product: TaiwanFuturesProduct) -> bool:
    symbol_id = str(item.get("SymbolID") or "").upper()
    if not symbol_id.endswith("-F"):
        return False
    return symbol_id.startswith(product.monthly_symbol_prefix)


def parse_taifex_mis_quote_payload(
    *,
    symbol: str,
    session: str,
    payload: dict[str, Any],
    fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_session = resolve_taiwan_futures_session(session)
    product = TAIWAN_FUTURES_PRODUCTS[normalized_symbol]
    fetched_time = fetched_at or datetime.now(TAIWAN_TZ)

    if str(payload.get("RtCode")) != "0":
        message = str(payload.get("RtMsg") or "TAIFEX MIS returned a non-success response.")
        raise TaiwanFuturesFetchError(message)

    quote_list = ((payload.get("RtData") or {}).get("QuoteList") or [])
    if not isinstance(quote_list, list):
        raise TaiwanFuturesFetchError("TAIFEX MIS quote list has unexpected shape.")

    quotes: list[dict[str, Any]] = []
    for item in quote_list:
        if not isinstance(item, dict) or not _is_monthly_contract(item, product):
            continue

        quote_time = _parse_taifex_datetime(item.get("CDate"), item.get("CTime"))
        last_price = _parse_float(item.get("CLastPrice"))
        if quote_time is None or last_price is None:
            continue

        contract_month = _parse_contract_month(item.get("DispEName"), quote_time)
        if contract_month is None:
            continue

        quote_session = _infer_session_from_quote_time(
            quote_time,
            resolved_session,
        )
        quote = {
            "provider": TAIFEX_PROVIDER,
            "market": "TAIFEX",
            "symbol": normalized_symbol,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "contract_symbol": str(item.get("SymbolID") or "").strip(),
            "contract_month": contract_month,
            "session": quote_session,
            "trade_date": quote_time.date(),
            "quote_time": quote_time,
            "open_price": _parse_float(item.get("COpenPrice")),
            "high_price": _parse_float(item.get("CHighPrice")),
            "low_price": _parse_float(item.get("CLowPrice")),
            "last_price": last_price,
            "reference_price": _parse_float(item.get("CRefPrice")),
            "settlement_price": _parse_float(item.get("SettlementPrice")),
            "change": _parse_float(item.get("CDiff")),
            "change_pct": _parse_float(item.get("CDiffRate")),
            "amplitude_pct": _parse_float(item.get("CAmpRate")),
            "total_volume": _parse_int(item.get("CTotalVolume")),
            "open_interest": _parse_int(item.get("OpenInterest")),
            "bid_price": _parse_float(item.get("CBestBidPrice") or item.get("CBidPrice1")),
            "bid_size": _parse_int(item.get("CBestBidSize") or item.get("CBidSize1")),
            "ask_price": _parse_float(item.get("CBestAskPrice") or item.get("CAskPrice1")),
            "ask_size": _parse_int(item.get("CBestAskSize") or item.get("CAskSize1")),
            "source": "TAIFEX MIS futures quote",
            "source_url": TAIFEX_MIS_QUOTE_URL,
            "raw_payload_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
            "fetched_at": fetched_time,
        }
        quotes.append(quote)

    return quotes


def parse_taifex_daily_market_html(
    *,
    symbol: str,
    trade_date: date,
    html_text: str,
    source_url: str | None = None,
    fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    product = TAIWAN_FUTURES_PRODUCTS[normalized_symbol]
    fetched_time = fetched_at or datetime.now(TAIWAN_TZ)
    rows: list[dict[str, Any]] = []

    for match in re.finditer(r"<tr[\s\S]*?</tr>", html_text, flags=re.IGNORECASE):
        cells = _extract_html_cells(match.group(0))
        if len(cells) < 17:
            continue
        if cells[0].strip().upper() != product.official_code:
            continue

        contract_month = cells[1].strip().upper()
        if not re.fullmatch(r"\d{6}", contract_month):
            continue

        row = {
            "provider": TAIFEX_DAILY_PROVIDER,
            "market": "TAIFEX",
            "symbol": normalized_symbol,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "contract_symbol": f"{product.official_code}{contract_month}",
            "contract_month": contract_month,
            "trade_date": trade_date,
            "open_price": _parse_float(cells[2]),
            "high_price": _parse_float(cells[3]),
            "low_price": _parse_float(cells[4]),
            "close_price": _parse_float(cells[5]),
            "change": _parse_signed_float(cells[6]),
            "change_pct": _parse_signed_float(cells[7]),
            "after_hours_volume": _parse_int(cells[8]),
            "regular_volume": _parse_int(cells[9]),
            "total_volume": _parse_int(cells[10]),
            "settlement_price": _parse_float(cells[11]),
            "open_interest": _parse_int(cells[12]),
            "bid_price": _parse_float(cells[13]),
            "ask_price": _parse_float(cells[14]),
            "historical_high_price": _parse_float(cells[15]),
            "historical_low_price": _parse_float(cells[16]),
            "source": "TAIFEX futures daily market report",
            "source_url": source_url or _build_taifex_daily_report_url(
                product=product,
                trade_date=trade_date,
            ),
            "raw_payload_json": json.dumps(cells[:17], ensure_ascii=False),
            "fetched_at": fetched_time,
        }

        if row["open_price"] is None and row["close_price"] is None and row["settlement_price"] is None:
            continue
        rows.append(row)

    return rows


def fetch_taifex_daily_market_html(
    *,
    symbol: str,
    trade_date: date,
    timeout: float = 8.0,
) -> tuple[str, str]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    product = TAIWAN_FUTURES_PRODUCTS[normalized_symbol]
    url = _build_taifex_daily_report_url(product=product, trade_date=trade_date)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Referer": "https://www.taifex.com.tw/cht/3/futDailyMarketReport",
        "User-Agent": "Mozilla/5.0",
    }

    try:
        with new_session() as session_client:
            response = session_client.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
    except requests.RequestException as exc:
        raise TaiwanFuturesFetchError(f"TAIFEX daily market request failed: {exc}") from exc

    response.encoding = response.encoding or "utf-8"
    return response.text, response.url


def fetch_taiwan_futures_daily_bars(
    *,
    symbol: str,
    trade_date: date,
) -> list[dict[str, Any]]:
    html_text, source_url = fetch_taifex_daily_market_html(
        symbol=symbol,
        trade_date=trade_date,
    )
    return parse_taifex_daily_market_html(
        symbol=symbol,
        trade_date=trade_date,
        html_text=html_text,
        source_url=source_url,
    )


def select_active_taiwan_futures_quote(quotes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not quotes:
        return None

    return sorted(
        quotes,
        key=lambda item: (
            -(item.get("total_volume") or 0),
            str(item.get("contract_month") or "999999"),
            item["quote_time"],
        ),
    )[0]


def select_active_taiwan_futures_daily_bar(rows: list[TaiwanFuturesDailyBar]) -> TaiwanFuturesDailyBar | None:
    if not rows:
        return None

    return sorted(
        rows,
        key=lambda row: (
            -(row.total_volume or 0),
            str(row.contract_month or "999999"),
            row.id or 0,
        ),
    )[0]


def fetch_taifex_mis_quote_payload(
    *,
    symbol: str,
    session: str = "auto",
    timeout: float = 8.0,
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_session = resolve_taiwan_futures_session(session)
    product = TAIWAN_FUTURES_PRODUCTS[normalized_symbol]
    body = {
        "MarketType": TAIFEX_MARKET_TYPE_BY_SESSION[resolved_session],
        "SymbolType": "F",
        "KindID": "1",
        "CID": product.taifex_cid,
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": TAIFEX_MIS_REFERER,
        "User-Agent": "Mozilla/5.0",
    }

    try:
        with new_session() as session_client:
            response = session_client.post(
                TAIFEX_MIS_QUOTE_URL,
                data=json.dumps(body),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
    except requests.RequestException as exc:
        raise TaiwanFuturesFetchError(f"TAIFEX MIS quote request failed: {exc}") from exc

    try:
        return json.loads(response.content.decode("utf-8-sig"))
    except ValueError as exc:
        raise TaiwanFuturesFetchError("TAIFEX MIS quote response is not valid JSON.") from exc


def _configured_kgi_settings() -> list[str]:
    fields = {
        "KGI_API_KEY": settings.kgi_api_key,
        "KGI_API_SECRET": settings.kgi_api_secret,
        "KGI_ACCOUNT": settings.kgi_account,
        "KGI_CERT_PATH": settings.kgi_cert_path,
        "KGI_API_BASE_URL": settings.kgi_api_base_url,
    }
    return [name for name, value in fields.items() if str(value or "").strip()]


def fetch_kgi_taiwan_futures_quotes(
    *,
    symbols: Iterable[str] | str | None = None,
    session: str = "auto",
    active_only: bool = True,
) -> list[dict[str, Any]]:
    normalize_taiwan_futures_symbols(symbols)
    normalize_taiwan_futures_session(session)

    configured_settings = _configured_kgi_settings()
    if not configured_settings:
        raise TaiwanFuturesFetchError(
            "KGI Taiwan futures provider is selected but no KGI settings are configured. "
            "Set KGI_API_KEY/KGI_API_SECRET/KGI_ACCOUNT or use TAIWAN_FUTURES_QUOTE_PROVIDER=taifex_mis."
        )

    raise TaiwanFuturesFetchError(
        "KGI Taiwan futures provider slot is configured but the API adapter is not implemented yet. "
        "Wire the KGI SDK/API response mapping in fetch_kgi_taiwan_futures_quotes()."
    )


def fetch_taiwan_futures_quotes(
    *,
    symbols: Iterable[str] | str | None = None,
    session: str = "auto",
    active_only: bool = True,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    normalized_symbols = normalize_taiwan_futures_symbols(symbols)
    resolved_provider = resolve_taiwan_futures_quote_provider(provider)
    if resolved_provider == KGI_PROVIDER:
        return fetch_kgi_taiwan_futures_quotes(
            symbols=normalized_symbols,
            session=session,
            active_only=active_only,
        )

    fetched_at = datetime.now(TAIWAN_TZ)
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []

    for symbol in normalized_symbols:
        try:
            payload = fetch_taifex_mis_quote_payload(symbol=symbol, session=session)
            quotes = parse_taifex_mis_quote_payload(
                symbol=symbol,
                session=session,
                payload=payload,
                fetched_at=fetched_at,
            )
        except TaiwanFuturesFetchError as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        if active_only:
            active_quote = select_active_taiwan_futures_quote(quotes)
            if active_quote is not None:
                parsed.append(active_quote)
        else:
            parsed.extend(quotes)

    if not parsed and errors:
        raise TaiwanFuturesFetchError("; ".join(errors))

    return parsed


def _upsert_quote_snapshot(
    db: Session,
    *,
    quote: dict[str, Any],
) -> TaiwanFuturesQuoteSnapshot:
    existing = (
        db.query(TaiwanFuturesQuoteSnapshot)
        .filter(TaiwanFuturesQuoteSnapshot.provider == quote["provider"])
        .filter(TaiwanFuturesQuoteSnapshot.symbol == quote["symbol"])
        .filter(TaiwanFuturesQuoteSnapshot.contract_month == quote["contract_month"])
        .filter(TaiwanFuturesQuoteSnapshot.session == quote["session"])
        .filter(TaiwanFuturesQuoteSnapshot.quote_time == quote["quote_time"])
        .first()
    )

    values = {
        key: value
        for key, value in quote.items()
        if key
        in {
            "market",
            "product_code",
            "product_name",
            "contract_symbol",
            "open_price",
            "high_price",
            "low_price",
            "last_price",
            "reference_price",
            "settlement_price",
            "change",
            "change_pct",
            "amplitude_pct",
            "total_volume",
            "open_interest",
            "bid_price",
            "bid_size",
            "ask_price",
            "ask_size",
            "source",
            "source_url",
            "raw_payload_json",
            "fetched_at",
            "trade_date",
        }
    }

    if existing is None:
        existing = TaiwanFuturesQuoteSnapshot(
            provider=quote["provider"],
            symbol=quote["symbol"],
            contract_month=quote["contract_month"],
            session=quote["session"],
            quote_time=quote["quote_time"],
            **values,
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)

    return existing


def _upsert_one_minute_bar(
    db: Session,
    *,
    quote: dict[str, Any],
) -> TaiwanFuturesIntradayBar:
    quote_time = quote["quote_time"]
    bar_time = quote_time.replace(second=0, microsecond=0)
    last_price = quote.get("last_price")

    existing = (
        db.query(TaiwanFuturesIntradayBar)
        .filter(TaiwanFuturesIntradayBar.provider == quote["provider"])
        .filter(TaiwanFuturesIntradayBar.symbol == quote["symbol"])
        .filter(TaiwanFuturesIntradayBar.contract_month == quote["contract_month"])
        .filter(TaiwanFuturesIntradayBar.interval == "1m")
        .filter(TaiwanFuturesIntradayBar.bar_time == bar_time)
        .first()
    )

    if existing is None:
        existing = TaiwanFuturesIntradayBar(
            provider=quote["provider"],
            market=quote["market"],
            symbol=quote["symbol"],
            product_code=quote["product_code"],
            product_name=quote["product_name"],
            contract_symbol=quote["contract_symbol"],
            contract_month=quote["contract_month"],
            session=quote["session"],
            interval="1m",
            bar_time=bar_time,
            open_price=last_price,
            high_price=last_price,
            low_price=last_price,
            close_price=last_price,
            total_volume=quote.get("total_volume"),
            open_interest=quote.get("open_interest"),
            source=quote["source"],
            source_url=quote.get("source_url"),
        )
        db.add(existing)
        return existing

    if last_price is not None:
        existing.open_price = existing.open_price if existing.open_price is not None else last_price
        existing.high_price = max(
            value for value in (existing.high_price, last_price) if value is not None
        )
        existing.low_price = min(
            value for value in (existing.low_price, last_price) if value is not None
        )
        existing.close_price = last_price

    existing.session = quote["session"]
    existing.contract_symbol = quote["contract_symbol"]
    existing.total_volume = quote.get("total_volume")
    existing.open_interest = quote.get("open_interest")
    existing.source = quote["source"]
    existing.source_url = quote.get("source_url")
    return existing


def _upsert_daily_bar(
    db: Session,
    *,
    bar: dict[str, Any],
) -> TaiwanFuturesDailyBar:
    existing = (
        db.query(TaiwanFuturesDailyBar)
        .filter(TaiwanFuturesDailyBar.provider == bar["provider"])
        .filter(TaiwanFuturesDailyBar.symbol == bar["symbol"])
        .filter(TaiwanFuturesDailyBar.contract_month == bar["contract_month"])
        .filter(TaiwanFuturesDailyBar.trade_date == bar["trade_date"])
        .first()
    )

    values = {
        key: value
        for key, value in bar.items()
        if key
        in {
            "market",
            "product_code",
            "product_name",
            "contract_symbol",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "settlement_price",
            "change",
            "change_pct",
            "after_hours_volume",
            "regular_volume",
            "total_volume",
            "open_interest",
            "bid_price",
            "ask_price",
            "historical_high_price",
            "historical_low_price",
            "source",
            "source_url",
            "raw_payload_json",
            "fetched_at",
        }
    }

    if existing is None:
        existing = TaiwanFuturesDailyBar(
            provider=bar["provider"],
            symbol=bar["symbol"],
            contract_month=bar["contract_month"],
            trade_date=bar["trade_date"],
            **values,
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)

    return existing


def refresh_taiwan_futures_quotes(
    db: Session,
    *,
    symbols: Iterable[str] | str | None = None,
    session: str = "auto",
    active_only: bool = True,
    provider: str | None = None,
) -> list[TaiwanFuturesQuoteSnapshot]:
    quotes = fetch_taiwan_futures_quotes(
        symbols=symbols,
        session=session,
        active_only=active_only,
        provider=provider,
    )

    rows: list[TaiwanFuturesQuoteSnapshot] = []
    for quote in quotes:
        row = _upsert_quote_snapshot(db=db, quote=quote)
        _upsert_one_minute_bar(db=db, quote=quote)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def refresh_taiwan_futures_daily_bars(
    db: Session,
    *,
    symbols: Iterable[str] | str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback_days: int = 45,
    force: bool = False,
) -> list[TaiwanFuturesDailyBar]:
    normalized_symbols = normalize_taiwan_futures_symbols(symbols)
    resolved_end_date = end_date or datetime.now(TAIWAN_TZ).date()
    resolved_start_date = start_date or (resolved_end_date - timedelta(days=max(lookback_days, 1)))
    if resolved_start_date > resolved_end_date:
        raise ValueError("Taiwan futures daily start_date cannot be after end_date.")

    rows: list[TaiwanFuturesDailyBar] = []
    errors: list[str] = []
    current_date = resolved_start_date
    while current_date <= resolved_end_date:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue

        for symbol in normalized_symbols:
            if not force:
                existing = (
                    db.query(TaiwanFuturesDailyBar)
                    .filter(TaiwanFuturesDailyBar.provider == TAIFEX_DAILY_PROVIDER)
                    .filter(TaiwanFuturesDailyBar.symbol == symbol)
                    .filter(TaiwanFuturesDailyBar.trade_date == current_date)
                    .first()
                )
                if existing is not None:
                    continue

            try:
                parsed_bars = fetch_taiwan_futures_daily_bars(
                    symbol=symbol,
                    trade_date=current_date,
                )
            except TaiwanFuturesFetchError as exc:
                errors.append(f"{symbol} {current_date.isoformat()}: {exc}")
                continue

            for parsed_bar in parsed_bars:
                rows.append(_upsert_daily_bar(db=db, bar=parsed_bar))

        current_date += timedelta(days=1)

    if not rows and errors:
        raise TaiwanFuturesFetchError("; ".join(errors))

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def get_latest_taiwan_futures_quotes(
    db: Session,
    *,
    symbols: Iterable[str] | str | None = None,
    refresh: bool = False,
    session: str = "auto",
    provider: str | None = None,
) -> list[TaiwanFuturesQuoteSnapshot]:
    normalized_symbols = normalize_taiwan_futures_symbols(symbols)
    resolved_provider = normalize_taiwan_futures_quote_provider(provider)
    if refresh:
        return refresh_taiwan_futures_quotes(
            db=db,
            symbols=normalized_symbols,
            session=session,
            active_only=True,
            provider=provider,
        )

    rows: list[TaiwanFuturesQuoteSnapshot] = []
    for symbol in normalized_symbols:
        query = (
            db.query(TaiwanFuturesQuoteSnapshot)
            .filter(TaiwanFuturesQuoteSnapshot.symbol == symbol)
        )
        if resolved_provider != "auto":
            query = query.filter(TaiwanFuturesQuoteSnapshot.provider == resolved_provider)

        row = query.order_by(TaiwanFuturesQuoteSnapshot.quote_time.desc()).first()
        if row is not None:
            rows.append(row)
    return rows


def list_taiwan_futures_daily_bars(
    db: Session,
    *,
    symbol: str,
    limit: int = 180,
    active_only: bool = True,
) -> list[TaiwanFuturesDailyBar]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    query_limit = limit * 8 if active_only else limit
    rows = list(
        reversed(
            db.query(TaiwanFuturesDailyBar)
            .filter(TaiwanFuturesDailyBar.symbol == normalized_symbol)
            .order_by(TaiwanFuturesDailyBar.trade_date.desc(), TaiwanFuturesDailyBar.total_volume.desc())
            .limit(query_limit)
            .all()
        )
    )

    if not active_only:
        return rows

    rows_by_date: dict[date, list[TaiwanFuturesDailyBar]] = {}
    for row in rows:
        rows_by_date.setdefault(row.trade_date, []).append(row)

    selected = [
        active_row
        for trade_day in sorted(rows_by_date)
        if (active_row := select_active_taiwan_futures_daily_bar(rows_by_date[trade_day])) is not None
    ]
    return selected[-limit:]


def list_taiwan_futures_intraday_bars(
    db: Session,
    *,
    symbol: str,
    interval: str = "1m",
    limit: int = 390,
    trade_date: date | None = None,
    provider: str | None = None,
) -> list[TaiwanFuturesIntradayBar]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_provider = normalize_taiwan_futures_quote_provider(provider)
    if interval != "1m":
        raise ValueError("Taiwan futures intraday bars currently support interval='1m' only.")

    query_limit = max(limit, min(limit * 4, 12_000))
    query = (
        db.query(TaiwanFuturesIntradayBar)
        .filter(TaiwanFuturesIntradayBar.symbol == normalized_symbol)
        .filter(TaiwanFuturesIntradayBar.interval == interval)
    )
    if resolved_provider != "auto":
        query = query.filter(TaiwanFuturesIntradayBar.provider == resolved_provider)

    rows = list(
        reversed(
            query.order_by(TaiwanFuturesIntradayBar.bar_time.desc())
            .limit(query_limit)
            .all()
        )
    )

    if not rows:
        return []

    def row_trade_date(row: TaiwanFuturesIntradayBar) -> date:
        value = row.bar_time
        if value.tzinfo is None:
            value = value.replace(tzinfo=TAIWAN_TZ)
        return value.astimezone(TAIWAN_TZ).date()

    resolved_trade_date = trade_date or row_trade_date(rows[-1])
    filtered_rows = [row for row in rows if row_trade_date(row) == resolved_trade_date]
    return filtered_rows[-limit:]


def taiwan_futures_quote_to_dict(
    row: TaiwanFuturesQuoteSnapshot,
    *,
    expected_session: str | None = None,
    source_error: str | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "market": row.market,
        "symbol": row.symbol,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "contract_symbol": row.contract_symbol,
        "contract_month": row.contract_month,
        "session": row.session,
        "trade_date": row.trade_date,
        "quote_time": row.quote_time,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "last_price": row.last_price,
        "reference_price": row.reference_price,
        "settlement_price": row.settlement_price,
        "change": row.change,
        "change_pct": row.change_pct,
        "amplitude_pct": row.amplitude_pct,
        "total_volume": row.total_volume,
        "open_interest": row.open_interest,
        "bid_price": row.bid_price,
        "bid_size": row.bid_size,
        "ask_price": row.ask_price,
        "ask_size": row.ask_size,
        "source": row.source,
        "source_url": row.source_url,
        "fetched_at": row.fetched_at,
        "freshness": build_taiwan_futures_quote_freshness(
            row,
            expected_session=expected_session,
            source_error=source_error,
        ),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def taiwan_futures_daily_bar_to_dict(row: TaiwanFuturesDailyBar) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "market": row.market,
        "symbol": row.symbol,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "contract_symbol": row.contract_symbol,
        "contract_month": row.contract_month,
        "trade_date": row.trade_date,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "close_price": row.close_price,
        "settlement_price": row.settlement_price,
        "change": row.change,
        "change_pct": row.change_pct,
        "after_hours_volume": row.after_hours_volume,
        "regular_volume": row.regular_volume,
        "total_volume": row.total_volume,
        "open_interest": row.open_interest,
        "bid_price": row.bid_price,
        "ask_price": row.ask_price,
        "historical_high_price": row.historical_high_price,
        "historical_low_price": row.historical_low_price,
        "source": row.source,
        "source_url": row.source_url,
        "fetched_at": row.fetched_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def taiwan_futures_intraday_bar_to_dict(row: TaiwanFuturesIntradayBar) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "market": row.market,
        "symbol": row.symbol,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "contract_symbol": row.contract_symbol,
        "contract_month": row.contract_month,
        "session": row.session,
        "interval": row.interval,
        "bar_time": row.bar_time,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "close_price": row.close_price,
        "total_volume": row.total_volume,
        "open_interest": row.open_interest,
        "source": row.source,
        "source_url": row.source_url,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
