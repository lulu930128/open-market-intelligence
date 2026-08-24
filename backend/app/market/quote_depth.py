from __future__ import annotations

from copy import deepcopy
from concurrent.futures import Future
from datetime import date, datetime, time, timezone
import json
import logging
from threading import RLock
import time as monotonic_time
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    MarketDailyPrice,
    SourceRegistry,
    StockMaster,
    TaiwanQuoteContractSnapshot,
    TaiwanStockQuoteSnapshot,
    utc_now,
)
from app.market.providers import http_get
from app.market.providers.kgi_canonical import (
    canonical_snapshot_from_kgi,
    kgi_quote_is_indicative,
)
from app.market.providers.kgi_superpy import (
    KGI_SUPERPY_PROVIDER,
    KGI_SUPERPY_SOURCE,
    KgiSuperPyQuoteSnapshot,
    get_kgi_superpy_quote_snapshot,
)
from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.live_snapshot import market_status_from_session
from app.market.quote_volume import build_taiwan_quote_volume_contract
from app.observability.provider_http import provider_http_failure
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    previous_taiwan_trading_day,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.twse_mis_observation import (
    resolve_twse_mis_actual_trade,
    resolve_twse_mis_observation,
)
from app.market_data.comparison import (
    CANONICAL_COMPARISON_METRICS,
    build_telemetry_event,
    compare_legacy_to_canonical,
)
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


TWSE_MIS_PROVIDER = "twse_mis"
TWSE_MIS_SOURCE = "twse_mis_quote_depth"
TWSE_MIS_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_MIS_REFERER_URL = "https://mis.twse.com.tw/stock/fibest.jsp"
KGI_SUPERPY_SOURCE_URL = (
    "https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/quoteSubscribeAll"
)
QUOTE_DEPTH_CACHE_TTL_SECONDS = 4.75
TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS = 180
TWSE_MIS_CIRCUIT_FAILURE_THRESHOLD = 3
TWSE_MIS_CIRCUIT_COOLDOWN_SECONDS = 90
TWSE_MIS_COALESCE_WINDOW_SECONDS = 2.5
TAIWAN_QUOTE_DEPTH_WAIT_START = time(5, 0)
TAIWAN_QUOTE_DEPTH_PREOPEN = time(8, 30)
TAIWAN_QUOTE_DEPTH_OPEN = time(9, 0)
TAIWAN_QUOTE_DEPTH_CLOSING_AUCTION = time(13, 25)
TAIWAN_QUOTE_DEPTH_CLOSE = time(13, 30)
TAIWAN_QUOTE_DEPTH_OFFICIAL_CLOSE_DEADLINE = time(13, 33)
TAIWAN_QUOTE_CONTRACT_SLOTS = (
    "08:30",
    "08:50",
    "08:55",
    "08:58",
    "08:59",
    "09:00",
    "09:01",
    "09:02",
    "09:05",
    "11:00",
    "13:24",
    "13:28",
    "13:30",
    "13:31",
    "13:32",
    "13:33",
    "13:34",
)
LIVE_DEPTH_PHASES = {"preopen_auction", "regular_live", "closing_auction"}
POST_CLOSE_PHASES = {"post_close_snapshot", "market_closed"}
PHASE_LABELS = {
    "closed_waiting_preopen": "等待試撮",
    "preopen_auction": "試撮",
    "regular_live": "即時",
    "closing_auction": "收盤撮合",
    "post_close_snapshot": "收盤快照",
    "market_closed": "休市",
}

logger = logging.getLogger(__name__)
runtime_logger = logging.getLogger("uvicorn.error")

_QUOTE_DEPTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TWSE_MIS_GUARD_LOCK = RLock()
_TWSE_MIS_INFLIGHT: dict[str, Future[tuple[dict[str, Any], str | None, dict[str, Any]]]] = {}
_TWSE_MIS_RESULT_CACHE: dict[
    str,
    tuple[float, tuple[dict[str, Any], str | None, dict[str, Any]]],
] = {}
_TWSE_MIS_CIRCUIT_FAILURES = 0
_TWSE_MIS_CIRCUIT_OPEN_UNTIL = 0.0
_TWSE_MIS_CIRCUIT_LAST_ERROR: str | None = None


class TaiwanStockQuoteDepthFetchError(RuntimeError):
    """Raised when Taiwan stock quote depth cannot be fetched safely."""


class TaiwanStockQuoteDepthCircuitOpenError(TaiwanStockQuoteDepthFetchError):
    """Raised while the TWSE MIS quote-depth circuit is cooling down."""

    def __init__(self, *, retry_after_seconds: int, last_error: str | None) -> None:
        message = (
            "TWSE MIS quote-depth circuit is open; "
            f"retry after {retry_after_seconds}s."
        )
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.last_error = last_error


def reset_twse_mis_quote_depth_guard() -> None:
    global _TWSE_MIS_CIRCUIT_FAILURES
    global _TWSE_MIS_CIRCUIT_OPEN_UNTIL
    global _TWSE_MIS_CIRCUIT_LAST_ERROR
    with _TWSE_MIS_GUARD_LOCK:
        _QUOTE_DEPTH_CACHE.clear()
        _TWSE_MIS_INFLIGHT.clear()
        _TWSE_MIS_RESULT_CACHE.clear()
        _TWSE_MIS_CIRCUIT_FAILURES = 0
        _TWSE_MIS_CIRCUIT_OPEN_UNTIL = 0.0
        _TWSE_MIS_CIRCUIT_LAST_ERROR = None


def _cache_get(cache_key: str) -> dict[str, Any] | None:
    cached = _QUOTE_DEPTH_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if monotonic_time.monotonic() - cached_at > QUOTE_DEPTH_CACHE_TTL_SECONDS:
        _QUOTE_DEPTH_CACHE.pop(cache_key, None)
        return None

    result = deepcopy(payload)
    result["refresh_outcome"] = "cache_hit"
    return result


def _cache_set(cache_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    _QUOTE_DEPTH_CACHE[cache_key] = (monotonic_time.monotonic(), deepcopy(payload))
    return payload


def _as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "--"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)


def _normalize_stock_id(stock_id: str) -> str:
    normalized = str(stock_id or "").strip()
    if not normalized:
        raise ValueError("stock_id is required.")
    return normalized


def _get_stock(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is None:
        raise ValueError(f"Unknown Taiwan stock id: {stock_id}")
    return stock


def _mis_exchange(market: str | None) -> str:
    return "otc" if str(market or "").upper() == "TPEX" else "tse"


def _local_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(TAIWAN_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(TAIWAN_TZ)


def _taiwan_exchange_datetime(value: datetime | None) -> datetime | None:
    """Restore exchange-local timestamps after SQLite drops timezone metadata."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def resolve_taiwan_stock_quote_phase(now: datetime | None = None) -> str:
    local_now = _local_now(now)
    current_date = local_now.date()
    if not is_taiwan_trading_day(current_date):
        return "market_closed"

    current_time = local_now.time()
    if current_time < TAIWAN_QUOTE_DEPTH_WAIT_START:
        return "post_close_snapshot"
    if TAIWAN_QUOTE_DEPTH_WAIT_START <= current_time < TAIWAN_QUOTE_DEPTH_PREOPEN:
        return "closed_waiting_preopen"
    if current_time < TAIWAN_QUOTE_DEPTH_OPEN:
        return "preopen_auction"
    if current_time < TAIWAN_QUOTE_DEPTH_CLOSING_AUCTION:
        return "regular_live"
    if current_time <= TAIWAN_QUOTE_DEPTH_CLOSE:
        return "closing_auction"
    return "post_close_snapshot"


def _expected_trade_date_for_phase(phase: str, now: datetime | None = None) -> date | None:
    local_now = _local_now(now)
    current_date = local_now.date()
    if phase == "post_close_snapshot" and local_now.time() < TAIWAN_QUOTE_DEPTH_WAIT_START:
        return previous_taiwan_trading_day(current_date, include_value=False)
    if phase in {"preopen_auction", "regular_live", "closing_auction", "post_close_snapshot"}:
        if is_taiwan_trading_day(current_date):
            return current_date
    if phase == "closed_waiting_preopen":
        presentation = taiwan_presentation_session(local_now)
        if presentation["state"] == "today_pending":
            return presentation["trade_date"]  # type: ignore[return-value]
    return previous_taiwan_trading_day(current_date, include_value=False)


def _parse_mis_trade_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None

    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _parse_mis_datetime(message: dict[str, Any], fallback: datetime) -> datetime:
    trade_date = _parse_mis_trade_date(message.get("d"))
    time_text = str(message.get("t") or message.get("%") or "").strip()
    if trade_date is None or not time_text:
        return fallback.astimezone(TAIWAN_TZ)

    parts = time_text.split(":")
    if len(parts) != 3:
        return fallback.astimezone(TAIWAN_TZ)

    try:
        return datetime.combine(
            trade_date,
            time(int(parts[0]), int(parts[1]), int(parts[2])),
            tzinfo=TAIWAN_TZ,
        )
    except ValueError:
        return fallback.astimezone(TAIWAN_TZ)


def _split_field(value: Any) -> list[str]:
    if value is None:
        return []
    return str(value).split("_")


def _parse_depth_levels(price_text: Any, size_text: Any) -> list[dict[str, Any]]:
    prices = _split_field(price_text)
    sizes = _split_field(size_text)
    levels: list[dict[str, Any]] = []

    for index in range(5):
        price = _as_float(prices[index]) if index < len(prices) else None
        size_lots = _as_int(sizes[index]) if index < len(sizes) else None
        if price is None and size_lots is None:
            continue
        levels.append(
            {
                "level": index + 1,
                "price": price,
                "price_status": (
                    "limit_price"
                    if price is not None and price > 0
                    else "non_price_level"
                    if price is not None
                    else "price_missing"
                ),
                "size_lots": size_lots,
                "volume_lots": size_lots,
                "order_count": None,
                "order_count_status": "not_provided",
            }
        )

    return levels


def _first_price_level(levels: list[dict[str, Any]]) -> dict[str, Any] | None:
    for level in levels:
        price = _as_float(level.get("price"))
        if price is not None and price > 0:
            return level
    return None


def _limit_price_levels(
    levels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    limit_levels: list[dict[str, Any]] = []
    for level in levels:
        price = _as_float(level.get("price"))
        if price is not None and price > 0:
            limit_levels.append(level)
    return limit_levels


def _non_price_levels(
    levels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_price_levels: list[dict[str, Any]] = []
    for level in levels:
        price = _as_float(level.get("price"))
        if price is None or price <= 0:
            non_price_levels.append(level)
    return non_price_levels


def _sum_level_sizes(levels: list[dict[str, Any]]) -> int | None:
    total = sum(
        int(size)
        for size in (level.get("size_lots") for level in levels)
        if isinstance(size, (int, float))
    )
    return total if total > 0 else None


def _depth_contract(
    *,
    bid_levels: list[dict[str, Any]],
    ask_levels: list[dict[str, Any]],
    depth_available: bool,
) -> dict[str, Any]:
    limit_bid_levels = _limit_price_levels(bid_levels)
    limit_ask_levels = _limit_price_levels(ask_levels)
    non_price_bid_levels = _non_price_levels(bid_levels)
    non_price_ask_levels = _non_price_levels(ask_levels)
    bid_total = _sum_level_sizes(limit_bid_levels)
    ask_total = _sum_level_sizes(limit_ask_levels)
    raw_bid_total = _sum_level_sizes(bid_levels)
    raw_ask_total = _sum_level_sizes(ask_levels)
    denominator = (bid_total or 0) + (ask_total or 0)
    imbalance = (
        ((bid_total or 0) - (ask_total or 0)) / denominator
        if depth_available and denominator > 0
        else None
    )
    status = "available" if depth_available else "unavailable"
    return {
        "bid_depth": bid_levels if depth_available else [],
        "ask_depth": ask_levels if depth_available else [],
        "limit_bid_depth": limit_bid_levels if depth_available else [],
        "limit_ask_depth": limit_ask_levels if depth_available else [],
        "non_price_bid_levels": non_price_bid_levels if depth_available else [],
        "non_price_ask_levels": non_price_ask_levels if depth_available else [],
        "bid_depth_status": status,
        "ask_depth_status": status,
        "depth_level_semantics": "provider_levels_with_non_price_levels_explicit",
        "non_price_level_semantics": (
            "provider_non_price_level_unclassified_not_market_order"
        ),
        "depth_volume_unit": "lots",
        "depth_order_count_status": "not_provided",
        "top5_bid_volume_lots": bid_total if depth_available else None,
        "top5_ask_volume_lots": ask_total if depth_available else None,
        "raw_top5_bid_volume_lots": raw_bid_total if depth_available else None,
        "raw_top5_ask_volume_lots": raw_ask_total if depth_available else None,
        "top5_imbalance": imbalance,
        "top5_imbalance_formula": (
            "(bid_volume_lots-ask_volume_lots)/(bid_volume_lots+ask_volume_lots)"
            if imbalance is not None
            else None
        ),
    }


def _percent_change(change: float | None, base: float | None) -> float | None:
    if change is None or base is None or base == 0:
        return None
    return change / base * 100


def _loads_levels(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [
        {
            **level,
            "price_status": level.get("price_status")
            or (
                "limit_price"
                if _as_float(level.get("price")) is not None
                and _as_float(level.get("price")) > 0
                else "non_price_level"
                if _as_float(level.get("price")) is not None
                else "price_missing"
            ),
            "volume_lots": level.get("volume_lots", level.get("size_lots")),
            "order_count": level.get("order_count"),
            "order_count_status": level.get(
                "order_count_status",
                "not_provided",
            ),
        }
        for level in loaded
        if isinstance(level, dict)
    ]


def _official_close_precision_contract(
    row: TaiwanStockQuoteSnapshot | None,
    *,
    official_close_available: bool,
) -> dict[str, Any]:
    if row is None or not official_close_available:
        return {
            "official_close_raw": None,
            "official_close_display": None,
            "official_close_precision": None,
            "official_close_precision_semantics": "unavailable",
        }
    raw_value: Any = None
    try:
        payload = json.loads(row.raw_payload_json or "{}")
        message = (payload.get("msgArray") or [None])[0]
        if isinstance(message, dict):
            raw_value = message.get("z")
    except (TypeError, json.JSONDecodeError):
        raw_value = None
    raw_text = str(raw_value).strip() if raw_value not in (None, "", "-") else None
    if raw_text is None and row.last_price is not None:
        raw_text = format(float(row.last_price), "g")
    precision = (
        len(raw_text.rsplit(".", 1)[1])
        if raw_text is not None and "." in raw_text
        else 0
        if raw_text is not None
        else None
    )
    return {
        "official_close_raw": raw_text,
        "official_close_display": raw_text,
        "official_close_precision": precision,
        "official_close_precision_semantics": "provider_decimal_preserved",
    }


def _fetch_mis_quote_depth(
    *,
    stock_id: str,
    market: str | None,
) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    exchange = _mis_exchange(market)
    response = http_get(
        TWSE_MIS_STOCK_INFO_URL,
        params={
            "ex_ch": f"{exchange}_{stock_id}.tw",
            "json": "1",
            "delay": "0",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": f"{TWSE_MIS_REFERER_URL}?stock={stock_id}",
        },
        timeout=10,
        omi_resource="quote_depth",
        omi_target=stock_id,
    )
    response.raise_for_status()
    payload = response.json()
    message = (payload.get("msgArray") or [None])[0]
    if not isinstance(message, dict):
        raise TaiwanStockQuoteDepthFetchError("TWSE MIS did not return quote data.")
    return message, response.url, payload


def _guarded_mis_quote_depth_fetch(
    *,
    stock_id: str,
    market: str | None,
) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    global _TWSE_MIS_CIRCUIT_FAILURES
    global _TWSE_MIS_CIRCUIT_OPEN_UNTIL
    global _TWSE_MIS_CIRCUIT_LAST_ERROR

    leader = False
    with _TWSE_MIS_GUARD_LOCK:
        cached = _TWSE_MIS_RESULT_CACHE.get(stock_id)
        now_monotonic = monotonic_time.monotonic()
        if cached is not None:
            cached_at, cached_result = cached
            if now_monotonic - cached_at <= TWSE_MIS_COALESCE_WINDOW_SECONDS:
                return deepcopy(cached_result)
            _TWSE_MIS_RESULT_CACHE.pop(stock_id, None)
        future = _TWSE_MIS_INFLIGHT.get(stock_id)
        if future is None:
            if now_monotonic < _TWSE_MIS_CIRCUIT_OPEN_UNTIL:
                raise TaiwanStockQuoteDepthCircuitOpenError(
                    retry_after_seconds=max(
                        int(_TWSE_MIS_CIRCUIT_OPEN_UNTIL - now_monotonic),
                        1,
                    ),
                    last_error=_TWSE_MIS_CIRCUIT_LAST_ERROR,
                )
            future = Future()
            _TWSE_MIS_INFLIGHT[stock_id] = future
            leader = True

    if not leader:
        return future.result()

    try:
        result = _fetch_mis_quote_depth(stock_id=stock_id, market=market)
    except Exception as exc:
        with _TWSE_MIS_GUARD_LOCK:
            _TWSE_MIS_CIRCUIT_FAILURES += 1
            _TWSE_MIS_CIRCUIT_LAST_ERROR = str(exc) or type(exc).__name__
            if _TWSE_MIS_CIRCUIT_FAILURES >= TWSE_MIS_CIRCUIT_FAILURE_THRESHOLD:
                _TWSE_MIS_CIRCUIT_OPEN_UNTIL = (
                    monotonic_time.monotonic() + TWSE_MIS_CIRCUIT_COOLDOWN_SECONDS
                )
            future.set_exception(exc)
            _TWSE_MIS_INFLIGHT.pop(stock_id, None)
        raise
    else:
        with _TWSE_MIS_GUARD_LOCK:
            _TWSE_MIS_CIRCUIT_FAILURES = 0
            _TWSE_MIS_CIRCUIT_OPEN_UNTIL = 0.0
            _TWSE_MIS_CIRCUIT_LAST_ERROR = None
            _TWSE_MIS_RESULT_CACHE[stock_id] = (
                monotonic_time.monotonic(),
                deepcopy(result),
            )
            future.set_result(result)
            _TWSE_MIS_INFLIGHT.pop(stock_id, None)
        return result


def _source_error_detail(exc: BaseException) -> dict[str, Any]:
    failure = provider_http_failure(exc)
    if failure is not None:
        return failure.diagnostic_fields()
    if isinstance(exc, TaiwanStockQuoteDepthCircuitOpenError):
        return {
            "provider": TWSE_MIS_PROVIDER,
            "resource": "quote_depth",
            "status": "circuit_open",
            "exception_type": type(exc).__name__,
            "retry_after_seconds": exc.retry_after_seconds,
            "retry_count": 0,
            "last_error": exc.last_error,
        }
    return {
        "provider": TWSE_MIS_PROVIDER,
        "resource": "quote_depth",
        "status": "error",
        "exception_type": type(exc).__name__,
        "error_message": str(exc) or type(exc).__name__,
        "retry_count": 0,
    }


def _snapshot_values_from_message(
    *,
    stock: StockMaster,
    session_phase: str,
    message: dict[str, Any],
    source_url: str | None,
    payload: dict[str, Any],
    fetched_at: datetime,
) -> dict[str, Any]:
    market = stock.market.upper() if stock.market else None
    exchange = _mis_exchange(market)
    bid_levels = _parse_depth_levels(message.get("b"), message.get("g"))
    ask_levels = _parse_depth_levels(message.get("a"), message.get("f"))
    best_bid = _first_price_level(bid_levels)
    best_ask = _first_price_level(ask_levels)
    best_bid_price = _as_float(best_bid.get("price")) if best_bid else None
    best_ask_price = _as_float(best_ask.get("price")) if best_ask else None
    best_bid_size_lots = _as_int(best_bid.get("size_lots")) if best_bid else None
    best_ask_size_lots = _as_int(best_ask.get("size_lots")) if best_ask else None
    last_price = _as_float(message.get("z"))
    previous_close = _as_float(message.get("y"))
    change = last_price - previous_close if last_price is not None and previous_close is not None else None
    spread = best_ask_price - best_bid_price if best_ask_price is not None and best_bid_price is not None else None
    quote_time = _parse_mis_datetime(message, fallback=fetched_at)

    return {
        "provider": TWSE_MIS_PROVIDER,
        "market": market,
        "stock_id": stock.stock_id,
        "stock_name": message.get("n") or stock.stock_name,
        "exchange_channel": message.get("ch") or f"{exchange}_{stock.stock_id}.tw",
        "session_phase": session_phase,
        "trade_date": _parse_mis_trade_date(message.get("d")) or quote_time.date(),
        "quote_time": quote_time,
        "open_price": _as_float(message.get("o")),
        "high_price": _as_float(message.get("h")),
        "low_price": _as_float(message.get("l")),
        "last_price": last_price,
        "previous_close": previous_close,
        "change": change,
        "change_pct": _percent_change(change, previous_close),
        "total_volume_lots": _as_int(message.get("v")),
        "last_trade_volume_lots": _as_int(message.get("tv")),
        "best_bid_price": best_bid_price,
        "best_bid_size_lots": best_bid_size_lots,
        "best_ask_price": best_ask_price,
        "best_ask_size_lots": best_ask_size_lots,
        "bid_total_size_lots": _sum_level_sizes(_limit_price_levels(bid_levels)),
        "ask_total_size_lots": _sum_level_sizes(_limit_price_levels(ask_levels)),
        "spread": spread,
        "spread_pct": _percent_change(spread, best_bid_price),
        "bid_levels_json": json.dumps(bid_levels, ensure_ascii=False, separators=(",", ":")),
        "ask_levels_json": json.dumps(ask_levels, ensure_ascii=False, separators=(",", ":")),
        "source": TWSE_MIS_SOURCE,
        "source_url": source_url,
        "raw_payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
    }


def _join_kgi_depth(values: Any) -> str:
    if not isinstance(values, (list, tuple)):
        return ""
    return "_".join(str(value) for value in values[:5])


def _kgi_quote_to_mis_message(
    *,
    stock: StockMaster,
    quote: dict[str, Any],
    session_phase: str,
) -> dict[str, Any]:
    raw_datetime = str(quote.get("datetime") or "").strip()
    if len(raw_datetime) != 14 or not raw_datetime.isdigit():
        raise ValueError("KGI SuperPy quote datetime must use YYYYMMDDHHMMSS.")
    if str(quote.get("symbol") or "").strip() != stock.stock_id:
        raise ValueError("KGI SuperPy quote symbol does not match the requested stock.")
    odd_lot = str(quote.get("odd_lot") or "").strip().lower()
    if odd_lot in {"1", "true", "yes", "on"}:
        raise ValueError("KGI SuperPy odd-lot quotes are outside the v1 contract.")

    close = _as_float(quote.get("close"))
    price_change = _as_float(quote.get("price_chg"))
    previous_close = (
        close - price_change
        if close is not None and price_change is not None
        else None
    )
    simtrade = _as_int(quote.get("simtrade")) or 0
    is_trial = kgi_quote_is_indicative(quote, session=session_phase)
    indicative_status_source = (
        "simtrade" if simtrade == 1 else "session+total_volume" if is_trial else None
    )
    event_time = raw_datetime[8:]
    return {
        "c": stock.stock_id,
        "n": stock.stock_name,
        "ch": f"kgi_{stock.stock_id}.tw",
        "d": raw_datetime[:8],
        "t": f"{event_time[:2]}:{event_time[2:4]}:{event_time[4:6]}",
        "o": quote.get("open"),
        "h": quote.get("high"),
        "l": quote.get("low"),
        "z": "-" if is_trial else quote.get("close"),
        "y": previous_close,
        "v": quote.get("total_volume"),
        "tv": None if is_trial else quote.get("volume"),
        "b": _join_kgi_depth(quote.get("bid_prices")),
        "g": _join_kgi_depth(quote.get("bid_volumes")),
        "a": _join_kgi_depth(quote.get("ask_prices")),
        "f": _join_kgi_depth(quote.get("ask_volumes")),
        "ts": "1" if is_trial else "0",
        "pz": quote.get("close") if is_trial else None,
        "ps": quote.get("volume") if is_trial else None,
        "_kgi_indicative_status_source": indicative_status_source,
        "suspend": quote.get("suspend"),
    }


def _snapshot_values_from_kgi_quote(
    *,
    stock: StockMaster,
    session_phase: str,
    quote: dict[str, Any],
) -> dict[str, Any]:
    message = _kgi_quote_to_mis_message(
        stock=stock,
        quote=quote,
        session_phase=session_phase,
    )
    received_at_raw = str(quote.get("received_at") or "").strip()
    try:
        received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00"))
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        received_at = received_at.astimezone(timezone.utc)
    except ValueError:
        received_at = utc_now()
    raw_payload = {
        "provider": KGI_SUPERPY_PROVIDER,
        "source": KGI_SUPERPY_SOURCE,
        "data": quote,
        "normalized_message": message,
    }
    values = _snapshot_values_from_message(
        stock=stock,
        session_phase=session_phase,
        message=message,
        source_url=KGI_SUPERPY_SOURCE_URL,
        payload={"msgArray": [message]},
        fetched_at=received_at,
    )
    values.update(
        {
            "provider": KGI_SUPERPY_PROVIDER,
            "source": KGI_SUPERPY_SOURCE,
            "source_url": KGI_SUPERPY_SOURCE_URL,
            "exchange_channel": f"kgi_{stock.stock_id}.tw",
            "raw_payload_json": json.dumps(
                raw_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    )
    return values


def _upsert_quote_snapshot(
    db: Session,
    values: dict[str, Any],
) -> tuple[TaiwanStockQuoteSnapshot, str]:
    existing = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.provider == values["provider"])
        .filter(TaiwanStockQuoteSnapshot.stock_id == values["stock_id"])
        .filter(TaiwanStockQuoteSnapshot.quote_time == values["quote_time"])
        .first()
    )

    if existing is None:
        row = TaiwanStockQuoteSnapshot(**values)
        db.add(row)
        refresh_outcome = "updated"
    else:
        row = existing
        refresh_outcome = (
            "updated"
            if any(
                getattr(existing, key) != value
                for key, value in values.items()
                if key not in {"fetched_at", "updated_at"}
            )
            else "unchanged"
        )
        for key, value in values.items():
            setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return row, refresh_outcome


def _latest_snapshot(db: Session, stock_id: str) -> TaiwanStockQuoteSnapshot | None:
    return (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.stock_id == stock_id)
        .order_by(TaiwanStockQuoteSnapshot.quote_time.desc())
        .first()
    )


def _latest_official_daily_volume(
    db: Session,
    stock_id: str,
) -> tuple[MarketDailyPrice, SourceRegistry] | None:
    return (
        db.query(MarketDailyPrice, SourceRegistry)
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.trade_volume.isnot(None))
        .filter(SourceRegistry.reliability_level == "official")
        .order_by(
            MarketDailyPrice.trade_date.desc(),
            SourceRegistry.priority.asc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .first()
    )


def _last_trade_volume_lots_for_row(
    row: TaiwanStockQuoteSnapshot,
) -> int | None:
    stored_value = getattr(row, "last_trade_volume_lots", None)
    if stored_value is not None:
        return _as_int(stored_value)
    if not row.raw_payload_json:
        return None
    try:
        payload = json.loads(row.raw_payload_json)
    except (TypeError, ValueError):
        return None
    messages = payload.get("msgArray") if isinstance(payload, dict) else None
    message = messages[0] if isinstance(messages, list) and messages else None
    return _as_int(message.get("tv")) if isinstance(message, dict) else None


def _raw_message_for_row(
    row: TaiwanStockQuoteSnapshot | None,
) -> dict[str, Any] | None:
    if row is None or not row.raw_payload_json:
        return None
    try:
        payload = json.loads(row.raw_payload_json)
    except (TypeError, ValueError):
        return None
    normalized_message = (
        payload.get("normalized_message") if isinstance(payload, dict) else None
    )
    if isinstance(normalized_message, dict):
        return normalized_message
    messages = payload.get("msgArray") if isinstance(payload, dict) else None
    message = messages[0] if isinstance(messages, list) and messages else None
    return message if isinstance(message, dict) else None


def _observation_for_row(
    row: TaiwanStockQuoteSnapshot | None,
    *,
    clock_phase: str,
    now: datetime | None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    message = _raw_message_for_row(row)
    observation = resolve_twse_mis_observation(
        request_now=local_now,
        market_calendar_phase=taiwan_market_session_phase(local_now),
        legacy_clock_phase=clock_phase,
        provider_event_time=(
            _taiwan_exchange_datetime(row.quote_time) if row is not None else None
        ),
        trial_status=message.get("ts") if message is not None else None,
        indicative_price=(
            _as_float(message.get("pz")) if message is not None else None
        ),
        indicative_volume_lots=(
            _as_int(message.get("ps")) if message is not None else None
        ),
        last_trade_price=row.last_price if row is not None else None,
        cumulative_volume_lots=(
            row.total_volume_lots if row is not None else None
        ),
    )
    actual_trade = resolve_twse_mis_actual_trade(
        expected_trade_date=_expected_trade_date_for_phase(clock_phase, now=local_now),
        observation_trade_date=row.trade_date if row is not None else None,
        provider_event_time=(
            _taiwan_exchange_datetime(row.quote_time) if row is not None else None
        ),
        trial_status=message.get("ts") if message is not None else None,
        last_trade_price=row.last_price if row is not None else None,
        last_trade_volume_lots=(
            _last_trade_volume_lots_for_row(row) if row is not None else None
        ),
        cumulative_volume_lots=(
            row.total_volume_lots if row is not None else None
        ),
    )
    return {
        **observation,
        "actual_trade_occurred": actual_trade["actual_trade_occurred"],
        "actual_trade_price_available": actual_trade[
            "actual_trade_price_available"
        ],
        "actual_trade_reason_code": actual_trade["reason_code"],
    }


def _latest_confirmed_same_session_trade(
    db: Session,
    *,
    stock_id: str,
    trade_date: date | None,
    event_time_upper_bound: datetime | None,
) -> TaiwanStockQuoteSnapshot | None:
    if trade_date is None:
        return None
    query = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.stock_id == stock_id)
        .filter(TaiwanStockQuoteSnapshot.trade_date == trade_date)
        .filter(TaiwanStockQuoteSnapshot.last_price.isnot(None))
    )
    if event_time_upper_bound is not None:
        query = query.filter(
            TaiwanStockQuoteSnapshot.quote_time <= event_time_upper_bound
        )
    candidates = (
        query.order_by(TaiwanStockQuoteSnapshot.quote_time.desc()).limit(100).all()
    )
    for candidate in candidates:
        message = _raw_message_for_row(candidate)
        actual_trade = resolve_twse_mis_actual_trade(
            expected_trade_date=trade_date,
            observation_trade_date=candidate.trade_date,
            provider_event_time=_taiwan_exchange_datetime(candidate.quote_time),
            trial_status=message.get("ts") if message is not None else None,
            last_trade_price=candidate.last_price,
            last_trade_volume_lots=_last_trade_volume_lots_for_row(candidate),
            cumulative_volume_lots=candidate.total_volume_lots,
        )
        if actual_trade["actual_trade_price_available"]:
            return candidate
    return None


def _auction_indicative_contract(
    row: TaiwanStockQuoteSnapshot | None,
    *,
    phase: str,
) -> dict[str, Any]:
    message = _raw_message_for_row(row)
    trial_status = (
        str(message.get("ts") or "").strip()
        if message is not None
        else ""
    )
    is_auction_phase = phase in {"preopen_auction", "closing_auction"}
    is_trial_snapshot = is_auction_phase and trial_status not in {"", "0"}
    price = _as_float(message.get("pz")) if is_trial_snapshot else None
    volume_lots = _as_int(message.get("ps")) if is_trial_snapshot else None
    if price is not None and price <= 0:
        price = None
    if volume_lots is not None and volume_lots < 0:
        volume_lots = None
    available = price is not None and volume_lots is not None
    partial = (price is not None or volume_lots is not None) and not available
    status = "available" if available else "partial" if partial else "not_provided"
    is_kgi = row is not None and row.provider == KGI_SUPERPY_PROVIDER
    return {
        "available": available,
        "price": price,
        "volume_lots": volume_lots,
        "status": status,
        "source": (
            KGI_SUPERPY_SOURCE
            if (available or partial) and is_kgi
            else TWSE_MIS_SOURCE
            if available or partial
            else None
        ),
        "price_source_field": (
            "close" if price is not None and is_kgi else "pz" if price is not None else None
        ),
        "volume_source_field": (
            "volume"
            if volume_lots is not None and is_kgi
            else "ps"
            if volume_lots is not None
            else None
        ),
        "status_source_field": (
            str(message.get("_kgi_indicative_status_source") or "simtrade")
            if is_trial_snapshot and is_kgi
            else "ts"
            if is_trial_snapshot
            else None
        ),
    }


def _freshness_for_row(
    row: TaiwanStockQuoteSnapshot | None,
    *,
    phase: str,
    source_error: str | None = None,
    source_error_detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    expected_trade_date = _expected_trade_date_for_phase(phase, now=local_now)
    quote_at = _taiwan_exchange_datetime(row.quote_time) if row else None
    fetched_at = _local_now(row.fetched_at) if row and row.fetched_at else None
    age_seconds = (
        max(int((local_now - quote_at).total_seconds()), 0)
        if quote_at is not None
        else None
    )
    fetch_age_seconds = (
        max(int((local_now - fetched_at).total_seconds()), 0)
        if fetched_at is not None
        else None
    )
    trade_date_mismatch = bool(
        row is not None
        and expected_trade_date is not None
        and row.trade_date is not None
        and row.trade_date < expected_trade_date
    )
    is_live_phase = phase in LIVE_DEPTH_PHASES
    is_stale = bool(
        row is None
        or trade_date_mismatch
        or (is_live_phase and (age_seconds is None or age_seconds > TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS))
        or source_error
    )

    if phase == "closed_waiting_preopen":
        presentation = taiwan_presentation_session(local_now)
        today_pending = presentation["state"] == "today_pending"
        return {
            "status": "empty",
            "is_live": False,
            "is_stale": False,
            "age_seconds": None,
            "fetch_age_seconds": None,
            "expected_trade_date": expected_trade_date,
            "message": (
                "今日交易日已建立，08:30 前行情尚未開始。"
                if today_pending
                else "05:00-08:00 顯示最近完成交易日，等待今日工作區切換。"
            ),
            "source_error": source_error,
            "source_error_detail": source_error_detail,
        }

    if row is None:
        return {
            "status": "source_unavailable" if source_error else "no_snapshot",
            "is_live": False,
            "is_stale": True,
            "age_seconds": None,
            "fetch_age_seconds": None,
            "expected_trade_date": expected_trade_date,
            "message": source_error or "尚無五檔快照。",
            "source_error": source_error,
            "source_error_detail": source_error_detail,
        }

    if source_error:
        status = "cached"
        message = "即時五檔來源暫時不可用，顯示最近快照。"
    elif trade_date_mismatch:
        status = "stale"
        message = "五檔快照交易日落後，請等待來源更新。"
    elif is_live_phase and is_stale:
        status = "stale"
        message = "五檔快照已超過即時 freshness 門檻。"
    elif is_live_phase:
        status = "live"
        message = "五檔即時更新中。"
    elif phase in POST_CLOSE_PHASES:
        status = "final_snapshot"
        message = "顯示最近收盤快照。"
    else:
        status = "snapshot"
        message = "顯示最近五檔快照。"

    return {
        "status": status,
        "is_live": status == "live",
        "is_stale": is_stale,
        "age_seconds": age_seconds,
        "fetch_age_seconds": fetch_age_seconds,
        "expected_trade_date": expected_trade_date,
        "message": message,
        "source_error": source_error,
        "source_error_detail": source_error_detail,
    }


def _price_semantics_contract(
    *,
    row: TaiwanStockQuoteSnapshot | None,
    phase: str,
    freshness: dict[str, Any],
    depth_available: bool,
    best_bid_price: float | None,
    best_ask_price: float | None,
    refresh_outcome: str,
    observation: dict[str, Any],
    confirmed_trade_row: TaiwanStockQuoteSnapshot | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    expected_trade_date = _expected_trade_date_for_phase(phase, now=local_now)
    current_row_has_trade = bool(
        row is not None
        and row.last_price is not None
        and observation.get("actual_trade_price_available")
        and expected_trade_date is not None
        and row.trade_date == expected_trade_date
    )
    current_snapshot_last_price = (
        row.last_price if current_row_has_trade and row is not None else None
    )
    selected_trade_row = (
        row if current_row_has_trade else confirmed_trade_row
    )
    last_trade_price = (
        selected_trade_row.last_price if selected_trade_row is not None else None
    )
    last_trade_time = (
        _taiwan_exchange_datetime(selected_trade_row.quote_time)
        if selected_trade_row is not None
        else None
    )
    last_trade_is_current_session = bool(
        selected_trade_row is not None
        and expected_trade_date is not None
        and selected_trade_row.trade_date == expected_trade_date
    )
    actual_trade_price_cached = bool(
        selected_trade_row is not None
        and row is not None
        and selected_trade_row.id != row.id
    )
    provider_trade_field = (
        "close"
        if selected_trade_row is not None
        and selected_trade_row.provider == KGI_SUPERPY_PROVIDER
        else "z"
    )
    actual_trade_price_source = (
        f"same_session_snapshot_{provider_trade_field}"
        if actual_trade_price_cached
        else f"current_snapshot_{provider_trade_field}"
        if current_row_has_trade
        else None
    )
    actual_trade_occurred = bool(
        observation.get("actual_trade_occurred")
        or selected_trade_row is not None
    )
    fetched_at = (
        _local_now(row.fetched_at)
        if row is not None and row.fetched_at is not None
        else None
    )
    snapshot_time = fetched_at
    persisted_after_close = bool(
        row is not None
        and fetched_at is not None
        and row.trade_date == fetched_at.date()
        and fetched_at.time() >= TAIWAN_QUOTE_DEPTH_CLOSE
    )
    provider_observed_current_state = (
        refresh_outcome in {"updated", "unchanged", "cache_hit"}
        and not freshness.get("source_error")
    )
    closing_state_finalized = (
        phase == "market_closed"
        or (
            phase == "post_close_snapshot"
            and local_now.time()
            >= TAIWAN_QUOTE_DEPTH_OFFICIAL_CLOSE_DEADLINE
        )
    )
    official_close_available = bool(
        closing_state_finalized
        and current_snapshot_last_price is not None
        and not freshness.get("source_error")
        and (provider_observed_current_state or persisted_after_close)
    )

    if official_close_available:
        official_close_status = "confirmed"
    elif phase == "closing_auction":
        official_close_status = "closing_auction_pending"
    elif phase == "post_close_snapshot":
        official_close_status = "pending"
    elif phase == "market_closed":
        official_close_status = "unverified_latest_session"
    else:
        official_close_status = "not_available_yet"

    auction_phase = bool(observation.get("auction_applicable"))
    indicative = _auction_indicative_contract(row, phase=phase)
    auction_book_available = bool(
        auction_phase
        and depth_available
        and (best_bid_price is not None or best_ask_price is not None)
    )
    auction_indicative_available = bool(indicative["available"])
    auction_book_time = snapshot_time if auction_book_available else None
    last_trade_available = bool(
        last_trade_price is not None
        and last_trade_is_current_session
        and observation.get("instrument_phase")
        not in {"preopen_auction", "opening_auction_delayed"}
    )
    if phase == "preopen_auction":
        quote_semantics = (
            "preopen_indicative_match_and_depth"
            if auction_indicative_available and auction_book_available
            else "preopen_indicative_match"
            if auction_indicative_available
            else
            "preopen_depth_only"
            if auction_book_available
            else "preopen_unavailable"
        )
        price_available = False
    elif phase == "regular_live":
        quote_semantics = (
            "live_trade_and_depth"
            if last_trade_available and depth_available
            else "delayed_current_session_trade"
            if last_trade_available and freshness.get("status") != "live"
            else "live_trade_only"
            if last_trade_available
            else "live_depth_only"
            if depth_available
            else "current_session_unavailable"
        )
        price_available = last_trade_available
    elif phase == "closing_auction":
        quote_semantics = (
            "closing_auction_indicative_match_and_depth"
            if auction_indicative_available and auction_book_available
            else "closing_auction_indicative_match"
            if auction_indicative_available
            else
            "closing_auction_depth_only"
            if auction_book_available
            else "closing_auction_last_trade"
            if last_trade_available
            else "closing_auction_pending"
        )
        price_available = last_trade_available
    elif phase in POST_CLOSE_PHASES:
        quote_semantics = (
            "official_close"
            if official_close_available
            else "official_close_pending"
            if phase == "post_close_snapshot"
            else "latest_session_close_unverified"
        )
        price_available = official_close_available
    else:
        quote_semantics = "unavailable"
        price_available = False
    delivery_status = (
        "official_close"
        if official_close_available
        else "official_close_pending"
        if phase == "post_close_snapshot"
        else "closing_auction"
        if phase == "closing_auction"
        else "live_depth_only"
        if phase == "preopen_auction" and depth_available
        else str(freshness.get("status") or "unavailable")
    )

    return {
        "market_calendar_phase": observation.get("market_calendar_phase"),
        "instrument_phase": observation.get("instrument_phase"),
        "observation_reason_code": observation.get("reason_code"),
        "actual_trade_reason_code": observation.get("actual_trade_reason_code"),
        "actual_trade_occurred": actual_trade_occurred,
        "actual_trade_price_cached": actual_trade_price_cached,
        "actual_trade_price_source": actual_trade_price_source,
        "actual_trade_price_as_of": (
            last_trade_time if last_trade_available else None
        ),
        "quote_semantics": quote_semantics,
        "observation_semantics": quote_semantics,
        "delivery_status": delivery_status,
        "fallback_used": False,
        "price_available": price_available,
        "last_trade_available": last_trade_available,
        "last_trade_price": (
            last_trade_price if last_trade_available else None
        ),
        "last_trade_time": (
            last_trade_time if last_trade_available else None
        ),
        "last_trade_is_current_session": last_trade_is_current_session,
        "last_trade_before_auction": bool(
            phase == "closing_auction" and last_trade_available
        ),
        "snapshot_time": snapshot_time,
        "snapshot_time_basis": "provider_response_received_at",
        "provider_event_time": last_trade_time,
        "auction_book_available": auction_book_available,
        "auction_book_status": (
            "depth_and_indicative_match"
            if auction_book_available and auction_indicative_available
            else "depth_only"
            if auction_book_available
            else "unavailable"
        ),
        "auction_book_time": auction_book_time,
        "auction_best_bid": (
            best_bid_price if auction_book_available else None
        ),
        "auction_best_ask": (
            best_ask_price if auction_book_available else None
        ),
        "auction_indicative_available": auction_indicative_available,
        "auction_indicative_status": indicative["status"],
        "auction_indicative_source": indicative["source"],
        "auction_phase": phase if auction_phase else None,
        "auction_event_time": (
            auction_book_time if auction_book_available else None
        ),
        "indicative_match_available": auction_indicative_available,
        "indicative_match_price": indicative["price"],
        "indicative_match_volume_lots": indicative["volume_lots"],
        "indicative_match_price_source_field": indicative["price_source_field"],
        "indicative_match_volume_source_field": indicative["volume_source_field"],
        "indicative_match_status_source_field": indicative["status_source_field"],
        "indicative_unmatched_buy_volume_lots": None,
        "indicative_unmatched_sell_volume_lots": None,
        "indicative_match_status": indicative["status"],
        "indicative_price_available": indicative["price"] is not None,
        "indicative_price": indicative["price"],
        "indicative_bid": None,
        "indicative_ask": None,
        "official_close_available": official_close_available,
        "official_close_status": official_close_status,
        "official_close_price": (
            current_snapshot_last_price if official_close_available else None
        ),
        "official_close_trade_date": (
            row.trade_date if row is not None and official_close_available else None
        ),
        "official_close_source": (
            TWSE_MIS_SOURCE if official_close_available else None
        ),
    }


def _empty_response(
    *,
    stock: StockMaster,
    phase: str,
    source_error: str | None = None,
    source_error_detail: dict[str, Any] | None = None,
    now: datetime | None = None,
    refresh_outcome: str = "not_attempted",
) -> dict[str, Any]:
    calendar_status = build_taiwan_calendar_status(now=now)
    market_status = market_status_from_session(calendar_status)
    session = calendar_status.get("session") if isinstance(calendar_status.get("session"), dict) else {}
    presentation = taiwan_presentation_session(now)
    observation = _observation_for_row(None, clock_phase=phase, now=now)
    effective_phase = str(observation["legacy_session_phase"])
    freshness = _freshness_for_row(
        None,
        phase=effective_phase,
        source_error=source_error,
        source_error_detail=source_error_detail,
        now=now,
    )
    semantics = _price_semantics_contract(
        row=None,
        phase=effective_phase,
        freshness=freshness,
        depth_available=False,
        best_bid_price=None,
        best_ask_price=None,
        refresh_outcome=refresh_outcome,
        observation=observation,
        now=now,
    )
    if effective_phase == "post_close_snapshot" and not source_error:
        freshness["status"] = "official_close_pending"
        freshness["is_stale"] = False
        freshness["message"] = (
            "The closing auction has ended, but an official close snapshot "
            "has not been confirmed yet."
        )
    depth_contract = _depth_contract(
        bid_levels=[],
        ask_levels=[],
        depth_available=False,
    )
    volume_contract = build_taiwan_quote_volume_contract(
        snapshot_trade_date=None,
        cumulative_volume_lots=None,
    )
    return {
        "stock_id": stock.stock_id,
        "stock_name": stock.stock_name,
        "market": stock.market,
        "provider": TWSE_MIS_PROVIDER,
        "source": "unavailable" if source_error else TWSE_MIS_SOURCE,
        "source_url": None,
        "exchange_channel": None,
        "session_phase": effective_phase,
        "presentation_trade_date": presentation["trade_date"],
        "presentation_session_state": presentation["state"],
        "presentation_session_transition_at": presentation["next_transition_at"],
        "market_status": market_status,
        "timezone": calendar_status.get("timezone"),
        "session_start": session.get("open_time"),
        "session_end": session.get("close_time"),
        "holiday_name": calendar_status.get("holiday_name"),
        "phase_label": (
            "今日待開盤"
            if presentation["state"] == "today_pending"
            else PHASE_LABELS.get(effective_phase, effective_phase)
        ),
        "trade_date": None,
        "quote_time": None,
        "snapshot_time": None,
        "provider_event_time": None,
        "fetched_at": None,
        "last_price": None,
        "previous_close": None,
        "open_price": None,
        "high_price": None,
        "low_price": None,
        "change": None,
        "change_pct": None,
        **volume_contract,
        "best_bid_price": None,
        "best_bid_size_lots": None,
        "best_ask_price": None,
        "best_ask_size_lots": None,
        "bid_total_size_lots": None,
        "ask_total_size_lots": None,
        "spread": None,
        "spread_pct": None,
        "bid_levels": [],
        "ask_levels": [],
        "depth_available": False,
        **depth_contract,
        "ohlc_summary": {
            "open": None,
            "high": None,
            "low": None,
            "last": None,
            "previous_close": None,
            "event_time": None,
            "semantics": "unavailable",
        },
        "refresh_outcome": refresh_outcome,
        **semantics,
        **_official_close_precision_contract(
            None,
            official_close_available=False,
        ),
        "freshness": freshness,
    }


def _row_to_response(
    db: Session,
    row: TaiwanStockQuoteSnapshot,
    *,
    phase: str,
    source_error: str | None = None,
    source_error_detail: dict[str, Any] | None = None,
    now: datetime | None = None,
    suppress_depth: bool = False,
    refresh_outcome: str = "not_attempted",
) -> dict[str, Any]:
    presentation = taiwan_presentation_session(now)
    observation = _observation_for_row(row, clock_phase=phase, now=now)
    effective_phase = str(observation["legacy_session_phase"])
    bid_levels = [] if suppress_depth else _loads_levels(row.bid_levels_json)
    ask_levels = [] if suppress_depth else _loads_levels(row.ask_levels_json)
    freshness = _freshness_for_row(
        row,
        phase=effective_phase,
        source_error=source_error,
        source_error_detail=source_error_detail,
        now=now,
    )
    depth_available = bool(
        (bid_levels or ask_levels)
        and effective_phase in LIVE_DEPTH_PHASES
        and freshness.get("is_live")
    )
    calendar_status = build_taiwan_calendar_status(now=now)
    market_status = market_status_from_session(calendar_status)
    session = calendar_status.get("session") if isinstance(calendar_status.get("session"), dict) else {}
    confirmed_trade_row = None
    if row.last_price is None:
        confirmed_trade_row = _latest_confirmed_same_session_trade(
            db,
            stock_id=row.stock_id,
            trade_date=_expected_trade_date_for_phase(effective_phase, now=now),
            event_time_upper_bound=row.quote_time,
        )
    semantics = _price_semantics_contract(
        row=row,
        phase=effective_phase,
        freshness=freshness,
        depth_available=depth_available,
        best_bid_price=row.best_bid_price,
        best_ask_price=row.best_ask_price,
        refresh_outcome=refresh_outcome,
        observation=observation,
        confirmed_trade_row=confirmed_trade_row,
        now=now,
    )
    if semantics["official_close_available"]:
        freshness["status"] = "official_close"
        freshness["is_live"] = False
        freshness["is_stale"] = False
        freshness["message"] = (
            "The latest completed regular-session close is confirmed."
        )
    elif (
        effective_phase == "post_close_snapshot"
        and not freshness.get("source_error")
        and not freshness.get("is_stale")
    ):
        freshness["status"] = "official_close_pending"
        freshness["is_live"] = False
        freshness["message"] = (
            "The closing auction has ended, but an official close snapshot "
            "has not been confirmed yet."
        )
    depth_contract = _depth_contract(
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        depth_available=depth_available,
    )
    close_precision = _official_close_precision_contract(
        row,
        official_close_available=bool(semantics["official_close_available"]),
    )
    snapshot_time = _local_now(row.fetched_at)
    provider_event_time = _taiwan_exchange_datetime(row.quote_time)
    served_at = _local_now(now)
    event_age_seconds = (
        max(
            0.0,
            (served_at - provider_event_time).total_seconds(),
        )
        if provider_event_time is not None
        else None
    )
    daily_volume_reference = _latest_official_daily_volume(db, row.stock_id)
    daily_volume_row = (
        daily_volume_reference[0]
        if daily_volume_reference is not None
        else None
    )
    daily_volume_source = (
        daily_volume_reference[1].source_name
        if daily_volume_reference is not None
        else None
    )
    volume_contract = build_taiwan_quote_volume_contract(
        snapshot_trade_date=row.trade_date,
        cumulative_volume_lots=(
            None if effective_phase == "preopen_auction" else row.total_volume_lots
        ),
        last_trade_volume_lots=(
            None
            if effective_phase == "preopen_auction"
            else _last_trade_volume_lots_for_row(row)
        ),
        official_daily_trade_date=(
            daily_volume_row.trade_date if daily_volume_row is not None else None
        ),
        official_daily_volume_shares=(
            daily_volume_row.trade_volume if daily_volume_row is not None else None
        ),
        official_daily_volume_source=daily_volume_source,
        provider=row.provider,
        cumulative_volume_source_field=(
            "total_volume" if row.provider == KGI_SUPERPY_PROVIDER else "v"
        ),
        last_trade_volume_source_field=(
            "volume" if row.provider == KGI_SUPERPY_PROVIDER else "tv"
        ),
    )

    return {
        "stock_id": row.stock_id,
        "stock_name": row.stock_name,
        "market": row.market,
        "provider": row.provider,
        "source": row.source,
        "source_url": row.source_url,
        "exchange_channel": row.exchange_channel,
        "session_phase": effective_phase,
        "presentation_trade_date": presentation["trade_date"],
        "presentation_session_state": presentation["state"],
        "presentation_session_transition_at": presentation["next_transition_at"],
        "market_status": market_status,
        "timezone": calendar_status.get("timezone"),
        "session_start": session.get("open_time"),
        "session_end": session.get("close_time"),
        "holiday_name": calendar_status.get("holiday_name"),
        "phase_label": PHASE_LABELS.get(effective_phase, effective_phase),
        "trade_date": row.trade_date,
        "quote_time": provider_event_time,
        "quote_time_basis": "provider_exchange_event_time",
        "snapshot_time": snapshot_time,
        "snapshot_time_basis": "omi_fetch_completed_at",
        "provider_event_time": provider_event_time,
        "event_time": provider_event_time,
        "fetched_at": snapshot_time,
        "received_at": snapshot_time,
        "served_at": served_at,
        "event_age_seconds": event_age_seconds,
        "provider_delay_ms": None,
        "network_latency_ms": None,
        "last_price": semantics["last_trade_price"],
        "previous_close": row.previous_close,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "change": (
            semantics["last_trade_price"] - row.previous_close
            if semantics["last_trade_price"] is not None
            and row.previous_close is not None
            else None
        ),
        "change_pct": _percent_change(
            (
                semantics["last_trade_price"] - row.previous_close
                if semantics["last_trade_price"] is not None
                and row.previous_close is not None
                else None
            ),
            row.previous_close,
        ),
        **volume_contract,
        "best_bid_price": row.best_bid_price,
        "best_bid_size_lots": row.best_bid_size_lots,
        "best_ask_price": row.best_ask_price,
        "best_ask_size_lots": row.best_ask_size_lots,
        "bid_total_size_lots": row.bid_total_size_lots,
        "ask_total_size_lots": row.ask_total_size_lots,
        "spread": row.spread,
        "spread_pct": row.spread_pct,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "depth_available": depth_available,
        **depth_contract,
        "ohlc_summary": {
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "last": (
                semantics["last_trade_price"]
                if semantics["last_trade_available"]
                or semantics["official_close_available"]
                else None
            ),
            "previous_close": row.previous_close,
            "event_time": _taiwan_exchange_datetime(row.quote_time),
            "semantics": (
                "current_session_to_date"
                if effective_phase in LIVE_DEPTH_PHASES
                else "latest_completed_session"
                if semantics["official_close_available"]
                else "provider_snapshot_unconfirmed"
            ),
        },
        "refresh_outcome": refresh_outcome,
        **semantics,
        **close_precision,
        "freshness": freshness,
    }


def _with_kgi_primary_metadata(
    payload: dict[str, Any],
    *,
    primary: KgiSuperPyQuoteSnapshot | None,
    primary_status: str | None = None,
    primary_error: str | None = None,
) -> dict[str, Any]:
    if primary is None or primary.active_leases <= 0:
        return payload

    status = primary_status or primary.status
    error = primary_error if primary_error is not None else primary.error
    used_primary = payload.get("provider") == KGI_SUPERPY_PROVIDER
    source_chain = [KGI_SUPERPY_SOURCE]
    secondary_source = str(payload.get("source") or "").strip()
    if secondary_source and secondary_source not in source_chain:
        source_chain.append(secondary_source)
    payload.update(
        {
            "source_chain": source_chain,
            "primary_provider": KGI_SUPERPY_PROVIDER,
            "primary_source_status": "live" if used_primary else status,
            "primary_source_error": None if used_primary else error,
            "fallback_used": not used_primary,
            "fallback_reason": None if used_primary else f"kgi_superpy_{status}",
        }
    )
    return payload


def _canonical_market_data_mode() -> str:
    return settings.canonical_market_data_mode


def _canonical_instrument_key(stock: StockMaster) -> InstrumentKey:
    instrument_type = InstrumentType(str(stock.instrument_type or "").strip().lower())
    return InstrumentKey(
        market=Market.TW,
        symbol=stock.stock_id,
        instrument_type=instrument_type,
        venue=str(stock.market or "").strip().upper() or None,
    )


def _flag_enabled(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _record_canonical_shadow_event(event: Any) -> None:
    try:
        CANONICAL_COMPARISON_METRICS.record(event)
    except Exception:
        pass
    try:
        runtime_logger.info(
            "canonical_market_data_shadow %s",
            event.model_dump_json(),
        )
    except Exception:
        pass


def _run_canonical_quote_shadow(
    *,
    provider: str,
    stock: StockMaster,
    session_phase: str,
    raw_observation: dict[str, Any],
    legacy_values: dict[str, Any],
    fetched_at: datetime | None = None,
) -> None:
    """Run bounded same-payload shadow work without changing legacy output."""

    mode = _canonical_market_data_mode()
    if mode == "off":
        return
    try:
        instrument = _canonical_instrument_key(stock)
        if provider == KGI_SUPERPY_PROVIDER:
            canonical = canonical_snapshot_from_kgi(
                instrument=instrument,
                quote=raw_observation,
                session=session_phase,
                received_at=fetched_at,
            )
            trial = kgi_quote_is_indicative(
                raw_observation,
                session=session_phase,
            )
            semantics = {
                "trial": trial,
                "indicative_price": raw_observation.get("close") if trial else None,
                "indicative_volume_lots": (
                    raw_observation.get("volume") if trial else None
                ),
                "suspend_hint": _flag_enabled(raw_observation.get("suspend")),
            }
        elif provider == TWSE_MIS_PROVIDER:
            if fetched_at is None:
                raise ValueError("MIS canonical shadow requires fetched_at")
            canonical = canonical_snapshot_from_twse_mis(
                instrument=instrument,
                message=raw_observation,
                session=session_phase,
                fetched_at=fetched_at,
                expected_trade_date=legacy_values.get("trade_date"),
            )
            trial = str(raw_observation.get("ts") or "").strip() not in {"", "0"}
            semantics = {
                "trial": trial,
                "indicative_price": raw_observation.get("pz") if trial else None,
                "indicative_volume_lots": raw_observation.get("ps") if trial else None,
            }
            if "suspend" in raw_observation:
                semantics["suspend_hint"] = _flag_enabled(
                    raw_observation.get("suspend")
                )
        else:
            raise ValueError("Unsupported canonical shadow provider")

        result = (
            compare_legacy_to_canonical(
                legacy=legacy_values,
                canonical=canonical,
                semantics=semantics,
            )
            if mode == "compare"
            else None
        )
        event = build_telemetry_event(
            mode=mode,
            provider=provider,
            market_phase=session_phase,
            result=result,
        )
        _record_canonical_shadow_event(event)
    except Exception as exc:
        try:
            event = build_telemetry_event(
                mode=mode,
                provider=provider,
                market_phase=session_phase,
                error_code=type(exc).__name__,
            )
            _record_canonical_shadow_event(event)
        except Exception:
            pass


def get_taiwan_stock_quote_depth(
    *,
    db: Session,
    stock_id: str,
    refresh: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_stock_id = _normalize_stock_id(stock_id)
    stock = _get_stock(db, normalized_stock_id)
    phase = resolve_taiwan_stock_quote_phase(now=now)

    if phase == "closed_waiting_preopen":
        return _empty_response(stock=stock, phase=phase, now=now)

    primary = (
        get_kgi_superpy_quote_snapshot(normalized_stock_id)
        if phase in LIVE_DEPTH_PHASES
        else None
    )
    primary_token = "secondary"
    if primary is not None and primary.active_leases > 0:
        primary_token = str(
            primary.quote.get("datetime")
            if primary.quote is not None
            else primary.status
        )
    cache_key = f"{normalized_stock_id}:{phase}:{int(refresh)}:{primary_token}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return _with_kgi_primary_metadata(cached, primary=primary)

    primary_status = primary.status if primary is not None else None
    primary_error = primary.error if primary is not None else None
    if primary is not None and primary.quote is not None:
        try:
            values = _snapshot_values_from_kgi_quote(
                stock=stock,
                session_phase=phase,
                quote=primary.quote,
            )
            _run_canonical_quote_shadow(
                provider=KGI_SUPERPY_PROVIDER,
                stock=stock,
                session_phase=phase,
                raw_observation=primary.quote,
                legacy_values=values,
            )
            row, refresh_outcome = _upsert_quote_snapshot(db, values)
            response = _row_to_response(
                db,
                row,
                phase=phase,
                now=now,
                refresh_outcome=refresh_outcome,
            )
            return _cache_set(
                cache_key,
                _with_kgi_primary_metadata(response, primary=primary),
            )
        except Exception as exc:
            db.rollback()
            primary_status = "invalid"
            primary_error = str(exc) or type(exc).__name__

    source_error: str | None = None
    source_error_detail: dict[str, Any] | None = None
    if refresh:
        try:
            fetched_at = utc_now()
            message, source_url, payload = _guarded_mis_quote_depth_fetch(
                stock_id=normalized_stock_id,
                market=stock.market,
            )
            values = _snapshot_values_from_message(
                stock=stock,
                session_phase=phase,
                message=message,
                source_url=source_url,
                payload=payload,
                fetched_at=fetched_at,
            )
            _run_canonical_quote_shadow(
                provider=TWSE_MIS_PROVIDER,
                stock=stock,
                session_phase=phase,
                raw_observation=message,
                legacy_values=values,
                fetched_at=fetched_at,
            )
            row, refresh_outcome = _upsert_quote_snapshot(db, values)
            response = _row_to_response(
                db,
                row,
                phase=phase,
                now=now,
                refresh_outcome=refresh_outcome,
            )
            return _cache_set(
                cache_key,
                _with_kgi_primary_metadata(
                    response,
                    primary=primary,
                    primary_status=primary_status,
                    primary_error=primary_error,
                ),
            )
        except Exception as exc:
            source_error = str(exc) or exc.__class__.__name__
            source_error_detail = _source_error_detail(exc)

    latest = _latest_snapshot(db, normalized_stock_id)
    if latest is None:
        response = _empty_response(
            stock=stock,
            phase=phase,
            source_error=source_error,
            source_error_detail=source_error_detail,
            now=now,
            refresh_outcome="failed" if source_error else "not_attempted",
        )
        return _cache_set(
            cache_key,
            _with_kgi_primary_metadata(
                response,
                primary=primary,
                primary_status=primary_status,
                primary_error=primary_error,
            ),
        )

    response = _row_to_response(
        db,
        latest,
        phase=phase,
        source_error=source_error,
        source_error_detail=source_error_detail,
        now=now,
        refresh_outcome="failed" if source_error else "not_attempted",
        suppress_depth=phase == "closed_waiting_preopen",
    )
    return _cache_set(
        cache_key,
        _with_kgi_primary_metadata(
            response,
            primary=primary,
            primary_status=primary_status,
            primary_error=primary_error,
        ),
    )


def _quote_contract_json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported quote contract snapshot value: {type(value)!r}")


def _quote_contract_slot_time(capture_slot: str) -> time:
    normalized = str(capture_slot or "").strip()
    if normalized not in TAIWAN_QUOTE_CONTRACT_SLOTS:
        raise ValueError(
            "capture_slot must be one of: "
            + ", ".join(TAIWAN_QUOTE_CONTRACT_SLOTS)
        )
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return time(int(hour_text), int(minute_text))


def _upsert_quote_contract_snapshot(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
    capture_slot: str,
    scheduled_at: datetime,
    captured_at: datetime,
    payload: dict[str, Any] | None,
    error: str | None,
) -> TaiwanQuoteContractSnapshot:
    freshness = (
        payload.get("freshness")
        if isinstance(payload, dict) and isinstance(payload.get("freshness"), dict)
        else {}
    )
    capture_status = (
        "failed"
        if payload is None
        else "captured_degraded"
        if error or freshness.get("source_error")
        else "captured"
    )
    values = {
        "provider": payload.get("provider") if payload else None,
        "market": payload.get("market") if payload else None,
        "scheduled_at": scheduled_at,
        "captured_at": captured_at,
        "quote_time": payload.get("quote_time") if payload else None,
        "session_phase": payload.get("session_phase") if payload else None,
        "capture_status": capture_status,
        "refresh_outcome": payload.get("refresh_outcome") if payload else "failed",
        "freshness_status": freshness.get("status"),
        "source": (
            str(payload.get("source") or TWSE_MIS_SOURCE)
            if payload
            else TWSE_MIS_SOURCE
        ),
        "payload_json": (
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_quote_contract_json_default,
            )
            if payload is not None
            else None
        ),
        "error": error or freshness.get("source_error"),
        "updated_at": captured_at,
    }
    row = (
        db.query(TaiwanQuoteContractSnapshot)
        .filter(TaiwanQuoteContractSnapshot.stock_id == stock_id)
        .filter(TaiwanQuoteContractSnapshot.trade_date == trade_date)
        .filter(TaiwanQuoteContractSnapshot.capture_slot == capture_slot)
        .first()
    )
    if row is None:
        row = TaiwanQuoteContractSnapshot(
            stock_id=stock_id,
            trade_date=trade_date,
            capture_slot=capture_slot,
            created_at=captured_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def capture_taiwan_quote_contract_snapshot(
    *,
    db: Session,
    stock_id: str,
    capture_slot: str,
    now: datetime | None = None,
    contract_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_stock_id = _normalize_stock_id(stock_id)
    local_now = _local_now(now)
    if not is_taiwan_trading_day(local_now.date()):
        raise ValueError(
            f"Taiwan quote contract capture requires a trading day: {local_now.date()}."
        )
    slot_time = _quote_contract_slot_time(capture_slot)
    scheduled_at = datetime.combine(
        local_now.date(),
        slot_time,
        tzinfo=TAIWAN_TZ,
    )
    payload: dict[str, Any] | None = None
    error: str | None = None
    try:
        payload = get_taiwan_stock_quote_depth(
            db=db,
            stock_id=normalized_stock_id,
            refresh=True,
            now=local_now,
        )
        if isinstance(payload, dict) and contract_context:
            payload = {
                **payload,
                "scheduler_contract": deepcopy(contract_context),
            }
    except Exception as exc:
        db.rollback()
        error = str(exc) or exc.__class__.__name__

    row = _upsert_quote_contract_snapshot(
        db,
        stock_id=normalized_stock_id,
        trade_date=local_now.date(),
        capture_slot=capture_slot,
        scheduled_at=scheduled_at,
        captured_at=local_now,
        payload=payload,
        error=error,
    )
    return {
        "stock_id": row.stock_id,
        "trade_date": row.trade_date,
        "capture_slot": row.capture_slot,
        "scheduled_at": _taiwan_exchange_datetime(row.scheduled_at),
        "captured_at": _taiwan_exchange_datetime(row.captured_at),
        "capture_delay_seconds": int(
            (
                _taiwan_exchange_datetime(row.captured_at)
                - _taiwan_exchange_datetime(row.scheduled_at)
            ).total_seconds()
        ),
        "capture_status": row.capture_status,
        "refresh_outcome": row.refresh_outcome,
        "freshness_status": row.freshness_status,
        "error": row.error,
    }


def _project_replay_quote_contract(
    payload: dict[str, Any] | None,
    *,
    captured_at: datetime,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    output = dict(payload)
    phase = str(output.get("session_phase") or "")
    source = str(output.get("source") or "")
    snapshot_time = (
        output.get("snapshot_time")
        or captured_at.isoformat()
    )
    provider_event_time = (
        output.get("provider_event_time")
        or output.get("last_trade_time")
        or output.get("quote_time")
    )
    output["quote_time"] = provider_event_time
    output.setdefault(
        "quote_time_basis",
        "provider_exchange_event_time",
    )
    output["snapshot_time"] = snapshot_time
    output.setdefault(
        "snapshot_time_basis",
        "persisted_capture_time",
    )
    output["provider_event_time"] = provider_event_time
    output["event_time"] = provider_event_time

    if source == TWSE_MIS_SOURCE:
        auction_phase = phase in {"preopen_auction", "closing_auction"}
        auction_book_available = bool(
            auction_phase and output.get("depth_available")
        )
        output["auction_book_available"] = auction_book_available
        indicative_available = bool(
            output.get("auction_indicative_available")
            or output.get("indicative_match_available")
        )
        output.setdefault(
            "auction_book_status",
            "depth_and_indicative_match"
            if auction_book_available and indicative_available
            else "depth_only"
            if auction_book_available
            else "unavailable",
        )
        output.setdefault(
            "auction_book_time",
            snapshot_time if auction_book_available else None,
        )
        output.setdefault(
            "auction_event_time",
            snapshot_time if auction_book_available else None,
        )
        output.setdefault(
            "auction_best_bid",
            output.get("best_bid_price") if auction_book_available else None,
        )
        output.setdefault(
            "auction_best_ask",
            output.get("best_ask_price") if auction_book_available else None,
        )
        output.setdefault("auction_indicative_available", False)
        output.setdefault("auction_indicative_status", "not_provided")
        output.setdefault("indicative_match_available", False)
        output.setdefault("indicative_match_price", None)
        output.setdefault("indicative_match_volume_lots", None)
        output.setdefault("indicative_unmatched_buy_volume_lots", None)
        output.setdefault("indicative_unmatched_sell_volume_lots", None)
        output.setdefault("indicative_match_status", "not_provided")
        output.setdefault("indicative_price_available", False)
        output.setdefault("indicative_price", None)
        output.setdefault("indicative_bid", None)
        output.setdefault("indicative_ask", None)
        output["last_trade_before_auction"] = bool(
            phase == "closing_auction"
            and output.get("last_trade_available")
        )

    output["replay_projection"] = "captured_public_contract_preserved"
    output["captured_contract_semantics"] = "persisted_public_payload"
    return output


def get_taiwan_quote_contract_replay(
    *,
    db: Session,
    stock_id: str,
    trade_date: date | None = None,
) -> dict[str, Any]:
    normalized_stock_id = _normalize_stock_id(stock_id)
    _get_stock(db, normalized_stock_id)
    target_trade_date = trade_date
    if target_trade_date is None:
        target_trade_date = (
            db.query(TaiwanQuoteContractSnapshot.trade_date)
            .filter(TaiwanQuoteContractSnapshot.stock_id == normalized_stock_id)
            .order_by(TaiwanQuoteContractSnapshot.trade_date.desc())
            .limit(1)
            .scalar()
        )

    rows: list[TaiwanQuoteContractSnapshot] = []
    if target_trade_date is not None:
        rows = (
            db.query(TaiwanQuoteContractSnapshot)
            .filter(TaiwanQuoteContractSnapshot.stock_id == normalized_stock_id)
            .filter(TaiwanQuoteContractSnapshot.trade_date == target_trade_date)
            .order_by(TaiwanQuoteContractSnapshot.capture_slot.asc())
            .all()
        )
    rows_by_slot = {row.capture_slot: row for row in rows}
    slot_results: list[dict[str, Any]] = []
    captured_count = 0
    for capture_slot in TAIWAN_QUOTE_CONTRACT_SLOTS:
        row = rows_by_slot.get(capture_slot)
        if row is None:
            slot_results.append(
                {
                    "capture_slot": capture_slot,
                    "status": "missing",
                    "quote": None,
                }
            )
            continue
        payload = (
            json.loads(row.payload_json)
            if row.payload_json
            else None
        )
        payload = _project_replay_quote_contract(
            payload,
            captured_at=_taiwan_exchange_datetime(row.captured_at),
        )
        if row.capture_status.startswith("captured"):
            captured_count += 1
        slot_results.append(
            {
                "capture_slot": capture_slot,
                "status": row.capture_status,
                "scheduled_at": _taiwan_exchange_datetime(row.scheduled_at),
                "captured_at": _taiwan_exchange_datetime(row.captured_at),
                "quote_time": _taiwan_exchange_datetime(row.quote_time),
                "freshness_status": row.freshness_status,
                "refresh_outcome": row.refresh_outcome,
                "error": row.error,
                "quote": payload,
            }
        )
    required_count = len(TAIWAN_QUOTE_CONTRACT_SLOTS)
    missing_slots = [
        item["capture_slot"]
        for item in slot_results
        if not str(item["status"]).startswith("captured")
    ]
    return {
        "kind": "taiwan_quote_contract_replay",
        "stock_id": normalized_stock_id,
        "trade_date": target_trade_date,
        "timezone": str(TAIWAN_TZ),
        "required_slots": list(TAIWAN_QUOTE_CONTRACT_SLOTS),
        "required_count": required_count,
        "captured_count": captured_count,
        "coverage_ratio": captured_count / required_count,
        "complete": captured_count == required_count,
        "missing_slots": missing_slots,
        "snapshots": slot_results,
        "source": "taiwan_quote_contract_snapshot",
        "replay_semantics": (
            "persisted_fixed_slot_evidence_projected_to_current_public_contract"
        ),
        "read_path_side_effects": False,
    }
