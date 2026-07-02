from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timezone
import json
import time as monotonic_time
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StockMaster, TaiwanStockQuoteSnapshot, utc_now
from app.http_client import get as http_get
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    previous_taiwan_trading_day,
)


TWSE_MIS_PROVIDER = "twse_mis"
TWSE_MIS_SOURCE = "twse_mis_quote_depth"
TWSE_MIS_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_MIS_REFERER_URL = "https://mis.twse.com.tw/stock/fibest.jsp"
QUOTE_DEPTH_CACHE_TTL_SECONDS = 4.75
TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS = 180
TAIWAN_QUOTE_DEPTH_WAIT_START = time(5, 0)
TAIWAN_QUOTE_DEPTH_PREOPEN = time(8, 30)
TAIWAN_QUOTE_DEPTH_OPEN = time(9, 0)
TAIWAN_QUOTE_DEPTH_CLOSING_AUCTION = time(13, 25)
TAIWAN_QUOTE_DEPTH_CLOSE = time(13, 30)
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

_QUOTE_DEPTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class TaiwanStockQuoteDepthFetchError(RuntimeError):
    """Raised when Taiwan stock quote depth cannot be fetched safely."""


def _cache_get(cache_key: str) -> dict[str, Any] | None:
    cached = _QUOTE_DEPTH_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if monotonic_time.monotonic() - cached_at > QUOTE_DEPTH_CACHE_TTL_SECONDS:
        _QUOTE_DEPTH_CACHE.pop(cache_key, None)
        return None

    return deepcopy(payload)


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


def _parse_depth_levels(price_text: Any, size_text: Any) -> list[dict[str, int | float | None]]:
    prices = _split_field(price_text)
    sizes = _split_field(size_text)
    levels: list[dict[str, int | float | None]] = []

    for index in range(5):
        price = _as_float(prices[index]) if index < len(prices) else None
        size_lots = _as_int(sizes[index]) if index < len(sizes) else None
        if price is None and size_lots is None:
            continue
        levels.append(
            {
                "level": index + 1,
                "price": price,
                "size_lots": size_lots,
            }
        )

    return levels


def _first_price_level(levels: list[dict[str, int | float | None]]) -> dict[str, int | float | None] | None:
    for level in levels:
        if level.get("price") is not None or level.get("size_lots") is not None:
            return level
    return None


def _sum_level_sizes(levels: list[dict[str, int | float | None]]) -> int | None:
    total = sum(
        int(size)
        for size in (level.get("size_lots") for level in levels)
        if isinstance(size, (int, float))
    )
    return total if total > 0 else None


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
    return loaded if isinstance(loaded, list) else []


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
    )
    response.raise_for_status()
    payload = response.json()
    message = (payload.get("msgArray") or [None])[0]
    if not isinstance(message, dict):
        raise TaiwanStockQuoteDepthFetchError("TWSE MIS did not return quote data.")
    return message, response.url, payload


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
        "best_bid_price": best_bid_price,
        "best_bid_size_lots": best_bid_size_lots,
        "best_ask_price": best_ask_price,
        "best_ask_size_lots": best_ask_size_lots,
        "bid_total_size_lots": _sum_level_sizes(bid_levels),
        "ask_total_size_lots": _sum_level_sizes(ask_levels),
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


def _upsert_quote_snapshot(db: Session, values: dict[str, Any]) -> TaiwanStockQuoteSnapshot:
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
    else:
        row = existing
        for key, value in values.items():
            setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return row


def _latest_snapshot(db: Session, stock_id: str) -> TaiwanStockQuoteSnapshot | None:
    return (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.stock_id == stock_id)
        .order_by(TaiwanStockQuoteSnapshot.quote_time.desc())
        .first()
    )


def _freshness_for_row(
    row: TaiwanStockQuoteSnapshot | None,
    *,
    phase: str,
    source_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    expected_trade_date = _expected_trade_date_for_phase(phase, now=local_now)
    fetched_at = _local_now(row.fetched_at) if row and row.fetched_at else None
    age_seconds = (
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
        return {
            "status": "empty",
            "is_live": False,
            "is_stale": False,
            "age_seconds": None,
            "expected_trade_date": expected_trade_date,
            "message": "05:00-08:30 等待試撮，五檔暫不顯示。",
            "source_error": source_error,
        }

    if row is None:
        return {
            "status": "source_unavailable" if source_error else "no_snapshot",
            "is_live": False,
            "is_stale": True,
            "age_seconds": None,
            "expected_trade_date": expected_trade_date,
            "message": source_error or "尚無五檔快照。",
            "source_error": source_error,
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
        "expected_trade_date": expected_trade_date,
        "message": message,
        "source_error": source_error,
    }


def _empty_response(
    *,
    stock: StockMaster,
    phase: str,
    source_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "stock_id": stock.stock_id,
        "stock_name": stock.stock_name,
        "market": stock.market,
        "provider": TWSE_MIS_PROVIDER,
        "source": "unavailable" if source_error else TWSE_MIS_SOURCE,
        "source_url": None,
        "exchange_channel": None,
        "session_phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "trade_date": None,
        "quote_time": None,
        "fetched_at": None,
        "last_price": None,
        "previous_close": None,
        "open_price": None,
        "high_price": None,
        "low_price": None,
        "change": None,
        "change_pct": None,
        "total_volume_lots": None,
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
        "freshness": _freshness_for_row(
            None,
            phase=phase,
            source_error=source_error,
            now=now,
        ),
    }


def _row_to_response(
    row: TaiwanStockQuoteSnapshot,
    *,
    phase: str,
    source_error: str | None = None,
    now: datetime | None = None,
    suppress_depth: bool = False,
) -> dict[str, Any]:
    bid_levels = [] if suppress_depth else _loads_levels(row.bid_levels_json)
    ask_levels = [] if suppress_depth else _loads_levels(row.ask_levels_json)
    depth_available = bool((bid_levels or ask_levels) and phase in LIVE_DEPTH_PHASES)

    return {
        "stock_id": row.stock_id,
        "stock_name": row.stock_name,
        "market": row.market,
        "provider": row.provider,
        "source": row.source,
        "source_url": row.source_url,
        "exchange_channel": row.exchange_channel,
        "session_phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "trade_date": row.trade_date,
        "quote_time": row.quote_time,
        "fetched_at": row.fetched_at,
        "last_price": row.last_price,
        "previous_close": row.previous_close,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "change": row.change,
        "change_pct": row.change_pct,
        "total_volume_lots": row.total_volume_lots,
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
        "freshness": _freshness_for_row(
            row,
            phase=phase,
            source_error=source_error,
            now=now,
        ),
    }


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

    cache_key = f"{normalized_stock_id}:{phase}:{int(refresh)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    source_error: str | None = None
    if refresh:
        try:
            fetched_at = utc_now()
            message, source_url, payload = _fetch_mis_quote_depth(
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
            row = _upsert_quote_snapshot(db, values)
            return _cache_set(cache_key, _row_to_response(row, phase=phase, now=now))
        except Exception as exc:
            source_error = str(exc) or exc.__class__.__name__

    latest = _latest_snapshot(db, normalized_stock_id)
    if latest is None:
        return _cache_set(
            cache_key,
            _empty_response(
                stock=stock,
                phase=phase,
                source_error=source_error,
                now=now,
            ),
        )

    return _cache_set(
        cache_key,
        _row_to_response(
            latest,
            phase=phase,
            source_error=source_error,
            now=now,
            suppress_depth=phase == "closed_waiting_preopen",
        ),
    )
