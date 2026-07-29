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
from app.market.trading_calendar import (
    is_taiwan_trading_day,
    latest_released_trading_day,
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
    taiwan_now,
    taiwan_market_holiday_name,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
TAIFEX_MIS_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
TAIFEX_MIS_CHART_1M_URL = "https://mis.taifex.com.tw/futures/api/getChartData1M"
TAIFEX_MIS_REFERER = "https://mis.taifex.com.tw/futures/"
TAIFEX_DAILY_REPORT_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
TAIFEX_PROVIDER = "taifex_mis"
TAIFEX_DAILY_PROVIDER = "taifex_daily"
KGI_PROVIDER = "kgi"

SUPPORTED_TAIWAN_FUTURES_SYMBOLS = {"TXF", "MXF", "TMF"}
TAIWAN_FUTURES_SYMBOL_ALIASES = {
    "TX": "TXF",
    "大台": "TXF",
    "大臺": "TXF",
    "小台": "MXF",
    "小臺": "MXF",
    "微台": "TMF",
    "微臺": "TMF",
}
SUPPORTED_TAIWAN_FUTURES_SESSIONS = {"auto", "regular", "after_hours"}
SUPPORTED_TAIWAN_FUTURES_QUOTE_PROVIDERS = {"auto", TAIFEX_PROVIDER, KGI_PROVIDER}
TAIWAN_FUTURES_SESSION_LABELS = {
    "regular": "日盤",
    "after_hours": "夜盤",
}
TAIWAN_FUTURES_LIVE_QUOTE_MAX_AGE_SECONDS = 180
TAIWAN_FUTURES_REGULAR_SESSION_START = time(8, 45)
TAIWAN_FUTURES_REGULAR_SESSION_END = time(13, 45)
TAIWAN_FUTURES_AFTER_HOURS_SESSION_START = time(15, 0)
TAIWAN_FUTURES_AFTER_HOURS_SESSION_END = time(5, 0)
TAIWAN_FUTURES_CLOSED_QUOTE_TOLERANCE_SECONDS = 15 * 60
# TAIFEX regular trading closes at 13:45.  Keep a conservative publication
# buffer before treating the current trade date's daily report as final.
TAIWAN_FUTURES_DAILY_RELEASE_TIME = time(14, 30)
TAIFEX_MARKET_TYPE_BY_SESSION = {
    "regular": "0",
    "after_hours": "1",
}
TAIFEX_CONTRACT_SUFFIX_BY_SESSION = {
    "regular": "-F",
    "after_hours": "-M",
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


@dataclass(frozen=True)
class TaiwanFuturesSessionWindow:
    session: str
    starts_at: datetime
    ends_at: datetime


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
        requested_symbol = str(value).strip()
        symbol = TAIWAN_FUTURES_SYMBOL_ALIASES.get(
            requested_symbol,
            requested_symbol.upper(),
        )
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


def resolve_taiwan_futures_daily_refresh_window(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback_days: int = 45,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a daily refresh range that contains released trade dates only."""

    local_now = taiwan_now(now)
    requested_end_date = end_date or local_now.date()
    latest_released_trade_date = latest_released_trading_day(
        release_time=TAIWAN_FUTURES_DAILY_RELEASE_TIME,
        now=local_now,
    )
    effective_end_date = min(requested_end_date, latest_released_trade_date)
    effective_start_date = start_date or (
        effective_end_date - timedelta(days=max(lookback_days, 1))
    )

    if effective_start_date > effective_end_date:
        raise ValueError(
            "Taiwan futures daily data has not reached its official release window; "
            f"latest released trade date is {latest_released_trade_date.isoformat()}."
        )

    return {
        "requested_end_date": requested_end_date,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "latest_released_trade_date": latest_released_trade_date,
        "skipped_unreleased_end_date": requested_end_date > effective_end_date,
        "release_time": TAIWAN_FUTURES_DAILY_RELEASE_TIME.strftime("%H:%M"),
    }


def resolve_taiwan_futures_quote_provider(provider: str | None = None) -> str:
    normalized = normalize_taiwan_futures_quote_provider(provider)
    if normalized == "auto":
        return TAIFEX_PROVIDER
    return normalized


def resolve_taiwan_futures_session(session: str | None = None) -> str:
    normalized = normalize_taiwan_futures_session(session)
    if normalized != "auto":
        return normalized

    market_status = build_taiwan_futures_market_status()
    return str(
        market_status.get("current_session")
        or market_status.get("last_session")
        or "regular"
    )


def _ensure_taiwan_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _canonical_taiwan_futures_quote_time(
    quote_time: datetime | None,
    *,
    provider: str | None,
    session: str | None,
    trade_date: date | None,
) -> datetime | None:
    resolved_time = _ensure_taiwan_datetime(quote_time)
    if resolved_time is None:
        return None

    # TAIFEX MIS keeps CDate on the calendar date when the night session began.
    # After midnight, CTime is 00:00-05:00 but the real timestamp is the next day.
    if (
        provider == TAIFEX_PROVIDER
        and session == "after_hours"
        and resolved_time.time() <= TAIWAN_FUTURES_AFTER_HOURS_SESSION_END
        and trade_date is not None
        and resolved_time.date() == trade_date
    ):
        resolved_time += timedelta(days=1)
    return resolved_time


def _session_label(session: str | None) -> str:
    return TAIWAN_FUTURES_SESSION_LABELS.get(str(session or ""), str(session or "未知時段"))


def _taiwan_futures_session_windows_for_trading_day(
    trading_day: date,
) -> tuple[TaiwanFuturesSessionWindow, TaiwanFuturesSessionWindow]:
    regular_start = datetime.combine(
        trading_day,
        TAIWAN_FUTURES_REGULAR_SESSION_START,
        tzinfo=TAIWAN_TZ,
    )
    regular_end = datetime.combine(
        trading_day,
        TAIWAN_FUTURES_REGULAR_SESSION_END,
        tzinfo=TAIWAN_TZ,
    )
    after_hours_start = datetime.combine(
        trading_day,
        TAIWAN_FUTURES_AFTER_HOURS_SESSION_START,
        tzinfo=TAIWAN_TZ,
    )
    after_hours_end = datetime.combine(
        trading_day + timedelta(days=1),
        TAIWAN_FUTURES_AFTER_HOURS_SESSION_END,
        tzinfo=TAIWAN_TZ,
    )
    return (
        TaiwanFuturesSessionWindow(
            session="regular",
            starts_at=regular_start,
            ends_at=regular_end,
        ),
        TaiwanFuturesSessionWindow(
            session="after_hours",
            starts_at=after_hours_start,
            ends_at=after_hours_end,
        ),
    )


def _taiwan_futures_candidate_session_windows(
    current_date: date,
) -> list[TaiwanFuturesSessionWindow]:
    trading_days = {
        previous_taiwan_trading_day(current_date, include_value=False),
        previous_taiwan_trading_day(current_date, include_value=True),
        next_taiwan_trading_day(current_date, include_value=True),
        next_taiwan_trading_day(current_date, include_value=False),
    }
    windows = [
        window
        for trading_day in trading_days
        if is_taiwan_trading_day(trading_day)
        for window in _taiwan_futures_session_windows_for_trading_day(trading_day)
    ]
    return sorted(windows, key=lambda window: window.starts_at)


def _session_window_fields(
    prefix: str,
    window: TaiwanFuturesSessionWindow | None,
) -> dict[str, Any]:
    return {
        f"{prefix}_session": window.session if window else None,
        f"{prefix}_session_start_at": window.starts_at if window else None,
        f"{prefix}_session_end_at": window.ends_at if window else None,
    }


def build_taiwan_futures_market_status(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _ensure_taiwan_datetime(now) or datetime.now(TAIWAN_TZ)
    current_date = current_time.date()
    windows = _taiwan_futures_candidate_session_windows(current_date)
    current_window = next(
        (
            window
            for window in windows
            if window.starts_at <= current_time <= window.ends_at
        ),
        None,
    )
    last_window = max(
        (window for window in windows if window.ends_at < current_time),
        key=lambda window: window.ends_at,
        default=None,
    )
    next_window = min(
        (window for window in windows if window.starts_at > current_time),
        key=lambda window: window.starts_at,
        default=None,
    )

    holiday_name = taiwan_market_holiday_name(current_date)
    if current_window is not None:
        phase = current_window.session
        reason = "trading"
    elif holiday_name:
        phase = "market_closed"
        reason = "holiday"
    elif current_date.weekday() >= 5:
        phase = "market_closed"
        reason = "weekend"
    elif (
        TAIWAN_FUTURES_AFTER_HOURS_SESSION_END
        < current_time.time()
        < TAIWAN_FUTURES_REGULAR_SESSION_START
    ):
        phase = "preopen"
        reason = "preopen"
    elif (
        TAIWAN_FUTURES_REGULAR_SESSION_END
        < current_time.time()
        < TAIWAN_FUTURES_AFTER_HOURS_SESSION_START
    ):
        phase = "between_sessions"
        reason = "between_sessions"
    else:
        phase = "market_closed"
        reason = "market_closed"

    return {
        "status": "open" if current_window is not None else "closed",
        "is_open": current_window is not None,
        "phase": phase,
        "reason": reason,
        "timezone": str(TAIWAN_TZ),
        "checked_at": current_time,
        "holiday_name": holiday_name,
        "regular_session": "08:45-13:45",
        "after_hours_session": "15:00-05:00",
        **_session_window_fields("current", current_window),
        **_session_window_fields("last", last_window),
        **_session_window_fields("next", next_window),
    }


def _format_age_message(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "報價時間無法判定。"
    if age_seconds < 60:
        return "報價剛更新。"
    if age_seconds < 3600:
        return f"報價已 {age_seconds // 60} 分鐘未更新。"
    return f"報價已 {age_seconds // 3600} 小時未更新。"


def _format_market_closed_message(market_status: dict[str, Any]) -> str:
    reason = market_status.get("reason")
    if reason == "weekend":
        prefix = "目前週末休市"
    elif reason == "holiday":
        holiday_name = market_status.get("holiday_name")
        prefix = f"目前因 {holiday_name} 休市" if holiday_name else "目前國定假日休市"
    elif reason == "between_sessions":
        prefix = "目前日盤與夜盤交接休市"
    elif reason == "preopen":
        prefix = "目前尚未開盤"
    else:
        prefix = "目前休市"

    next_open = market_status.get("next_session_start_at")
    next_session = market_status.get("next_session")
    if isinstance(next_open, datetime):
        return (
            f"{prefix}；下次開盤 {next_open.strftime('%m/%d %H:%M')}"
            f"（{_session_label(str(next_session or ''))}）。"
        )
    return f"{prefix}。"


def build_taiwan_futures_quote_freshness(
    row: TaiwanFuturesQuoteSnapshot,
    *,
    expected_session: str | None = None,
    source_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    quote_time = _canonical_taiwan_futures_quote_time(
        row.quote_time,
        provider=row.provider,
        session=row.session,
        trade_date=row.trade_date,
    )
    current_time = _ensure_taiwan_datetime(now) or datetime.now(TAIWAN_TZ)
    market_status = build_taiwan_futures_market_status(now=current_time)
    normalized_expected_session = normalize_taiwan_futures_session(expected_session or "auto")
    resolved_expected_session = (
        normalized_expected_session
        if normalized_expected_session != "auto"
        else str(
            market_status.get("current_session")
            or market_status.get("last_session")
            or row.session
        )
    )
    age_seconds = (
        max(int((current_time - quote_time).total_seconds()), 0)
        if quote_time is not None
        else None
    )
    is_session_mismatch = row.session != resolved_expected_session
    last_session_start_at = market_status.get("last_session_start_at")
    last_session_end_at = market_status.get("last_session_end_at")
    belongs_to_last_session = (
        quote_time is not None
        and isinstance(last_session_start_at, datetime)
        and isinstance(last_session_end_at, datetime)
        and last_session_start_at <= quote_time <= last_session_end_at
        and row.session == market_status.get("last_session")
    )
    last_session_quote_lag_seconds = (
        max(int((last_session_end_at - quote_time).total_seconds()), 0)
        if belongs_to_last_session
        and quote_time is not None
        and isinstance(last_session_end_at, datetime)
        else None
    )
    is_latest_completed_session_quote = (
        belongs_to_last_session
        and last_session_quote_lag_seconds is not None
        and last_session_quote_lag_seconds
        <= TAIWAN_FUTURES_CLOSED_QUOTE_TOLERANCE_SECONDS
    )
    is_stale = (
        age_seconds is None
        or (
            bool(market_status.get("is_open"))
            and age_seconds > TAIWAN_FUTURES_LIVE_QUOTE_MAX_AGE_SECONDS
        )
        or (
            not bool(market_status.get("is_open"))
            and not is_latest_completed_session_quote
        )
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
    elif not market_status.get("is_open") and is_latest_completed_session_quote:
        status_value = "closed"
        message = _format_market_closed_message(market_status)
    elif is_stale:
        status_value = "stale"
        if not market_status.get("is_open"):
            market_message = _format_market_closed_message(market_status).rstrip("。")
            if last_session_quote_lag_seconds is not None:
                message = (
                    f"{market_message}；最後報價距最近時段收盤"
                    f" {last_session_quote_lag_seconds // 60} 分鐘。"
                )
            else:
                message = f"{market_message}；最後報價未涵蓋最近完成的交易時段。"
        else:
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
        "last_session_quote_lag_seconds": last_session_quote_lag_seconds,
        "market_status": market_status,
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


def _is_monthly_contract(
    item: dict[str, Any],
    product: TaiwanFuturesProduct,
    session: str,
) -> bool:
    symbol_id = str(item.get("SymbolID") or "").upper()
    expected_suffix = TAIFEX_CONTRACT_SUFFIX_BY_SESSION[session]
    if not symbol_id.endswith(expected_suffix):
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
        if not isinstance(item, dict) or not _is_monthly_contract(
            item,
            product,
            resolved_session,
        ):
            continue

        raw_trade_date = _parse_taifex_date(item.get("CDate"))
        quote_time = _canonical_taiwan_futures_quote_time(
            _parse_taifex_datetime(item.get("CDate"), item.get("CTime")),
            provider=TAIFEX_PROVIDER,
            session=resolved_session,
            trade_date=raw_trade_date,
        )
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
            "trade_date": raw_trade_date or quote_time.date(),
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


def fetch_taifex_mis_intraday_payload(
    *,
    contract_symbol: str,
    timeout: float = 8.0,
) -> dict[str, Any]:
    normalized_contract_symbol = str(contract_symbol or "").strip().upper()
    if not normalized_contract_symbol:
        raise ValueError("TAIFEX MIS intraday chart requires a contract symbol.")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": TAIFEX_MIS_REFERER,
        "User-Agent": "Mozilla/5.0",
    }

    try:
        with new_session() as session_client:
            response = session_client.post(
                TAIFEX_MIS_CHART_1M_URL,
                data=json.dumps({"SymbolID": normalized_contract_symbol}),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
    except requests.RequestException as exc:
        raise TaiwanFuturesFetchError(
            f"TAIFEX MIS 1-minute chart request failed: {exc}"
        ) from exc

    try:
        return json.loads(response.content.decode("utf-8-sig"))
    except ValueError as exc:
        raise TaiwanFuturesFetchError(
            "TAIFEX MIS 1-minute chart response is not valid JSON."
        ) from exc


def _parse_taifex_hhmm(value: Any) -> time | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    try:
        return time(int(text[:2]), int(text[2:4]))
    except ValueError:
        return None


def parse_taifex_mis_intraday_payload(
    *,
    symbol: str,
    session: str,
    contract_symbol: str,
    contract_month: str,
    payload: dict[str, Any],
    fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_session = resolve_taiwan_futures_session(session)
    normalized_contract_symbol = str(contract_symbol or "").strip().upper()
    normalized_contract_month = str(contract_month or "").strip()
    expected_suffix = TAIFEX_CONTRACT_SUFFIX_BY_SESSION[resolved_session]
    if not normalized_contract_symbol.endswith(expected_suffix):
        raise TaiwanFuturesFetchError(
            f"TAIFEX MIS contract {normalized_contract_symbol or '<empty>'} does not match "
            f"the {resolved_session} session."
        )
    if not re.fullmatch(r"\d{6}", normalized_contract_month):
        raise TaiwanFuturesFetchError(
            "TAIFEX MIS 1-minute chart contract month is missing or malformed."
        )
    if str(payload.get("RtCode")) != "0":
        message = str(
            payload.get("RtMsg") or "TAIFEX MIS 1-minute chart returned a non-success response."
        )
        raise TaiwanFuturesFetchError(message)

    data = payload.get("RtData")
    if not isinstance(data, dict):
        raise TaiwanFuturesFetchError("TAIFEX MIS 1-minute chart data has unexpected shape.")

    returned_contract = str(data.get("SymbolID") or "").strip().upper()
    if returned_contract and returned_contract != normalized_contract_symbol:
        raise TaiwanFuturesFetchError(
            "TAIFEX MIS 1-minute chart returned a different contract symbol."
        )

    quote = data.get("Quote")
    info = data.get("Info")
    sessions = info.get("Sessions") if isinstance(info, dict) else None
    session_info = sessions[0] if isinstance(sessions, list) and sessions else None
    session_start = _parse_taifex_hhmm(
        session_info.get("Start") if isinstance(session_info, dict) else None
    )
    session_end = _parse_taifex_hhmm(
        session_info.get("End") if isinstance(session_info, dict) else None
    )
    chart_date = _parse_taifex_date(quote.get("CDate") if isinstance(quote, dict) else None)
    if chart_date is None or session_start is None or session_end is None:
        raise TaiwanFuturesFetchError(
            "TAIFEX MIS 1-minute chart is missing a valid chart date or session range."
        )

    ticks = data.get("Ticks")
    if not isinstance(ticks, list):
        raise TaiwanFuturesFetchError("TAIFEX MIS 1-minute ticks have unexpected shape.")

    product = TAIWAN_FUTURES_PRODUCTS[normalized_symbol]
    fetched_time = fetched_at or datetime.now(TAIWAN_TZ)
    crosses_midnight = session_start > session_end
    bars: list[dict[str, Any]] = []
    for tick in ticks:
        if not isinstance(tick, list) or len(tick) < 6:
            continue

        tick_time_text = str(tick[0] or "").strip()
        if not re.fullmatch(r"\d{6}", tick_time_text):
            continue
        try:
            tick_clock = time(
                int(tick_time_text[:2]),
                int(tick_time_text[2:4]),
                int(tick_time_text[4:6]),
            )
        except ValueError:
            continue

        in_session = (
            tick_clock >= session_start or tick_clock <= session_end
            if crosses_midnight
            else session_start <= tick_clock <= session_end
        )
        if not in_session:
            continue

        open_price = _parse_float(tick[1])
        high_price = _parse_float(tick[2])
        low_price = _parse_float(tick[3])
        close_price = _parse_float(tick[4])
        minute_volume = _parse_int(tick[5])
        if None in {open_price, high_price, low_price, close_price, minute_volume}:
            continue

        bar_date = chart_date
        if crosses_midnight and tick_clock <= session_end:
            bar_date += timedelta(days=1)
        bar_time = datetime.combine(bar_date, tick_clock, tzinfo=TAIWAN_TZ)
        bars.append(
            {
                "provider": TAIFEX_PROVIDER,
                "market": "TAIFEX",
                "symbol": normalized_symbol,
                "product_code": product.product_code,
                "product_name": product.product_name,
                "contract_symbol": normalized_contract_symbol,
                "contract_month": normalized_contract_month,
                "session": resolved_session,
                "interval": "1m",
                "bar_time": bar_time,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "total_volume": minute_volume,
                "open_interest": None,
                "source": "TAIFEX MIS 1-minute chart",
                "source_url": TAIFEX_MIS_CHART_1M_URL,
                "fetched_at": fetched_time,
            }
        )

    if ticks and not bars:
        raise TaiwanFuturesFetchError(
            "TAIFEX MIS 1-minute chart returned no usable bars for the requested session."
        )
    return bars


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
    resolved_session = resolve_taiwan_futures_session(session)
    resolved_provider = resolve_taiwan_futures_quote_provider(provider)
    if resolved_provider == KGI_PROVIDER:
        return fetch_kgi_taiwan_futures_quotes(
            symbols=normalized_symbols,
            session=resolved_session,
            active_only=active_only,
        )

    fetched_at = datetime.now(TAIWAN_TZ)
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []

    for symbol in normalized_symbols:
        try:
            payload = fetch_taifex_mis_quote_payload(
                symbol=symbol,
                session=resolved_session,
            )
            quotes = parse_taifex_mis_quote_payload(
                symbol=symbol,
                session=resolved_session,
                payload=payload,
                fetched_at=fetched_at,
            )
        except TaiwanFuturesFetchError as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        if not quotes:
            errors.append(
                f"{symbol}: TAIFEX MIS returned no usable {resolved_session} monthly quote."
            )
            continue

        if active_only:
            active_quote = select_active_taiwan_futures_quote(quotes)
            if active_quote is not None:
                parsed.append(active_quote)
        else:
            parsed.extend(quotes)

    if not parsed:
        message = "; ".join(errors) or (
            f"TAIFEX MIS returned no usable {resolved_session} monthly quotes."
        )
        raise TaiwanFuturesFetchError(message)

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
            total_volume=None,
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
    existing.open_interest = quote.get("open_interest")
    if existing.total_volume is None:
        existing.source = quote["source"]
        existing.source_url = quote.get("source_url")
    return existing


def _upsert_intraday_bar(
    db: Session,
    *,
    bar: dict[str, Any],
) -> TaiwanFuturesIntradayBar:
    existing = (
        db.query(TaiwanFuturesIntradayBar)
        .filter(TaiwanFuturesIntradayBar.provider == bar["provider"])
        .filter(TaiwanFuturesIntradayBar.symbol == bar["symbol"])
        .filter(TaiwanFuturesIntradayBar.contract_month == bar["contract_month"])
        .filter(TaiwanFuturesIntradayBar.interval == bar["interval"])
        .filter(TaiwanFuturesIntradayBar.bar_time == bar["bar_time"])
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
            "session",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "total_volume",
            "open_interest",
            "source",
            "source_url",
        }
    }

    if existing is None:
        existing = TaiwanFuturesIntradayBar(
            provider=bar["provider"],
            symbol=bar["symbol"],
            contract_month=bar["contract_month"],
            interval=bar["interval"],
            bar_time=bar["bar_time"],
            **values,
        )
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
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
    try:
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
    except Exception:
        db.rollback()
        raise

    for row in rows:
        db.refresh(row)
    return rows


def refresh_taiwan_futures_intraday_bars(
    db: Session,
    *,
    symbol: str,
    session: str = "auto",
    provider: str | None = None,
) -> list[TaiwanFuturesIntradayBar]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_session = resolve_taiwan_futures_session(session)
    resolved_provider = resolve_taiwan_futures_quote_provider(provider)
    if resolved_provider != TAIFEX_PROVIDER:
        raise TaiwanFuturesFetchError(
            "Taiwan futures 1-minute chart currently supports the TAIFEX MIS provider only."
        )

    quote = (
        db.query(TaiwanFuturesQuoteSnapshot)
        .filter(TaiwanFuturesQuoteSnapshot.provider == resolved_provider)
        .filter(TaiwanFuturesQuoteSnapshot.symbol == normalized_symbol)
        .filter(TaiwanFuturesQuoteSnapshot.session == resolved_session)
        .order_by(TaiwanFuturesQuoteSnapshot.quote_time.desc())
        .first()
    )
    expected_suffix = TAIFEX_CONTRACT_SUFFIX_BY_SESSION[resolved_session]
    if quote is None or not str(quote.contract_symbol or "").upper().endswith(expected_suffix):
        quote_rows = refresh_taiwan_futures_quotes(
            db=db,
            symbols=[normalized_symbol],
            session=resolved_session,
            active_only=True,
            provider=resolved_provider,
        )
        quote = quote_rows[0] if quote_rows else None

    if quote is None or quote.contract_month is None:
        raise TaiwanFuturesFetchError(
            f"No active {resolved_session} contract is available for {normalized_symbol}."
        )

    payload = fetch_taifex_mis_intraday_payload(
        contract_symbol=quote.contract_symbol,
    )
    bars = parse_taifex_mis_intraday_payload(
        symbol=normalized_symbol,
        session=resolved_session,
        contract_symbol=quote.contract_symbol,
        contract_month=quote.contract_month,
        payload=payload,
    )
    if not bars:
        raise TaiwanFuturesFetchError(
            f"TAIFEX MIS returned no {resolved_session} 1-minute bars for {normalized_symbol}."
        )

    try:
        rows = [_upsert_intraday_bar(db=db, bar=bar) for bar in bars]
        db.commit()
    except Exception:
        db.rollback()
        raise

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
    now: datetime | None = None,
) -> list[TaiwanFuturesDailyBar]:
    normalized_symbols = normalize_taiwan_futures_symbols(symbols)
    refresh_window = resolve_taiwan_futures_daily_refresh_window(
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        now=now,
    )
    resolved_start_date = refresh_window["effective_start_date"]
    resolved_end_date = refresh_window["effective_end_date"]

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

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

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

        candidates = (
            query.order_by(TaiwanFuturesQuoteSnapshot.fetched_at.desc())
            .limit(512)
            .all()
        )
        row = max(
            candidates,
            key=lambda candidate: _canonical_taiwan_futures_quote_time(
                candidate.quote_time,
                provider=candidate.provider,
                session=candidate.session,
                trade_date=candidate.trade_date,
            )
            or datetime.min.replace(tzinfo=TAIWAN_TZ),
            default=None,
        )
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
    session: str = "auto",
    provider: str | None = None,
) -> list[TaiwanFuturesIntradayBar]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    resolved_session = resolve_taiwan_futures_session(session)
    resolved_provider = normalize_taiwan_futures_quote_provider(provider)
    if interval != "1m":
        raise ValueError("Taiwan futures intraday bars currently support interval='1m' only.")

    query_limit = max(limit, min(limit * 4, 12_000))
    query = (
        db.query(TaiwanFuturesIntradayBar)
        .filter(TaiwanFuturesIntradayBar.symbol == normalized_symbol)
        .filter(TaiwanFuturesIntradayBar.interval == interval)
        .filter(TaiwanFuturesIntradayBar.session == resolved_session)
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
        local_value = value.astimezone(TAIWAN_TZ)
        logical_date = local_value.date()
        if row.session == "after_hours" and local_value.time() <= time(5, 0):
            logical_date -= timedelta(days=1)
        return logical_date

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
        "quote_time": _canonical_taiwan_futures_quote_time(
            row.quote_time,
            provider=row.provider,
            session=row.session,
            trade_date=row.trade_date,
        ),
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
