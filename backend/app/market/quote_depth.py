from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timezone
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    StockMaster,
    TaiwanStockQuoteSnapshot,
)
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.live_snapshot import market_status_from_session
from app.market.quote_volume import build_taiwan_quote_volume_contract
from app.market.public_quote_platform import (
    project_taiwan_session_close,
    reconcile_taiwan_session_close,
)
from app.market.taiwan_quote_evidence import (
    TaiwanQuoteEvidenceBundle,
    acquire_taiwan_quote_evidence_bundle,
    read_taiwan_quote_evidence_bundle,
)
from app.market.taiwan_rules import expected_daily_price_date
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
from app.market_data.contracts import (
    Quantity,
    QuantityUnit,
    ResolvedEvidenceStatus,
)
from app.market_data.policies import RealtimePolicy


TWSE_MIS_PROVIDER = "twse_mis"
TWSE_MIS_SOURCE = "twse_mis_quote_depth"
KGI_SUPERPY_PROVIDER = "kgi_superpy"
KGI_SUPERPY_SOURCE = "kgi_superpy_quote_all"
TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS = 180
TAIWAN_QUOTE_DEPTH_WAIT_START = time(5, 0)
TAIWAN_QUOTE_DEPTH_PREOPEN = time(8, 30)
LIVE_DEPTH_PHASES = {"preopen_auction", "regular_live", "closing_auction"}
POST_CLOSE_PHASES = {"post_close_snapshot", "market_closed"}
PHASE_LABELS = {
    "closed_waiting_preopen": "等待試撮",
    "preopen_auction": "試撮",
    "regular_live": "即時",
    "closing_auction": "收盤撮合",
    "close_resolution": "收盤確認",
    "post_close_snapshot": "收盤快照",
    "market_closed": "休市",
}

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
    return {
        "preopen_pending": "closed_waiting_preopen",
        "preopen": "preopen_auction",
        "regular": "regular_live",
        "closing_auction": "closing_auction",
        "close_resolution": "close_resolution",
        "post_close": "post_close_snapshot",
        "market_closed": "market_closed",
    }.get(taiwan_market_session_phase(local_now), "market_closed")


def _expected_trade_date_for_phase(phase: str, now: datetime | None = None) -> date | None:
    local_now = _local_now(now)
    current_date = local_now.date()
    if phase == "post_close_snapshot" and local_now.time() < TAIWAN_QUOTE_DEPTH_WAIT_START:
        return previous_taiwan_trading_day(current_date, include_value=False)
    if phase in {
        "preopen_auction",
        "regular_live",
        "closing_auction",
        "close_resolution",
        "post_close_snapshot",
    }:
        if is_taiwan_trading_day(current_date):
            return current_date
    if phase == "closed_waiting_preopen":
        presentation = taiwan_presentation_session(local_now)
        if presentation["state"] == "today_pending":
            return presentation["trade_date"]  # type: ignore[return-value]
    return previous_taiwan_trading_day(current_date, include_value=False)


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
    # A realtime provider snapshot can expose the final matched trade, but it
    # cannot promote itself to the completed official-close capability.  The
    # canonical daily result is applied later by the market-owned bundle.
    official_close_available = False

    if official_close_available:
        official_close_status = "confirmed"
    elif phase == "closing_auction":
        official_close_status = "closing_auction_pending"
    elif phase == "close_resolution":
        official_close_status = "pending"
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
    elif phase == "close_resolution":
        quote_semantics = (
            "close_resolution_candidate"
            if last_trade_available
            else "close_resolution_pending"
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
        else "close_resolution"
        if phase == "close_resolution"
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
    official_daily_bar: Any | None = None,
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
    daily_volume = getattr(official_daily_bar, "volume", None)
    daily_volume_shares = (
        int(daily_volume.value)
        if daily_volume is not None
        and daily_volume.unit is QuantityUnit.SHARE
        else None
    )
    daily_volume_trade_date = (
        official_daily_bar.end_at.astimezone(TAIWAN_TZ).date()
        if official_daily_bar is not None
        else None
    )
    daily_volume_source = (
        official_daily_bar.lineage.source
        if official_daily_bar is not None
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
            daily_volume_trade_date
        ),
        official_daily_volume_shares=daily_volume_shares,
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


def _resolved_quote_row(
    db: Session,
    result: Any,
) -> TaiwanStockQuoteSnapshot | None:
    quote = getattr(result.resolved, "quote", None)
    observation_id = quote.lineage.observation_id if quote is not None else None
    prefix = "taiwan_stock_quote_snapshot:"
    if not observation_id or not observation_id.startswith(prefix):
        return None
    try:
        row_id = int(observation_id.removeprefix(prefix))
    except ValueError:
        return None
    return (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.id == row_id)
        .first()
    )


def _quantity_lots(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    if (
        quantity.original_unit is QuantityUnit.BOARD_LOT
        and quantity.original_value is not None
    ):
        return int(quantity.original_value)
    if quantity.unit is QuantityUnit.BOARD_LOT:
        return int(quantity.value)
    if quantity.unit is QuantityUnit.SHARE:
        return int(quantity.value / 1000)
    return None


def _depth_level_projection(level: Any) -> dict[str, Any]:
    quantity_lots = _quantity_lots(level.quantity)
    return {
        "level": level.level,
        "price": float(level.price) if level.price is not None else None,
        "price_status": level.price_state.value,
        "size_lots": quantity_lots,
        "volume_lots": quantity_lots,
        "order_count": None,
        "order_count_status": "not_provided",
    }


def _apply_resolved_depth(
    payload: dict[str, Any],
    result: Any,
    *,
    phase: str,
) -> None:
    depth = getattr(result.resolved, "depth", None)
    usable = bool(depth is not None and result.resolved.health.facts_usable)
    available = usable and phase in LIVE_DEPTH_PHASES
    depth_event_time = (
        depth.lineage.event_at if depth is not None else None
    )
    bid_levels = (
        [_depth_level_projection(level) for level in depth.bids]
        if available
        else []
    )
    ask_levels = (
        [_depth_level_projection(level) for level in depth.asks]
        if available
        else []
    )
    depth_contract = _depth_contract(
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        depth_available=available,
    )
    best_bid = _first_price_level(bid_levels)
    best_ask = _first_price_level(ask_levels)
    payload.update(
        {
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
            "depth_available": available,
            "best_bid_price": best_bid.get("price") if best_bid else None,
            "best_bid_size_lots": best_bid.get("size_lots") if best_bid else None,
            "best_ask_price": best_ask.get("price") if best_ask else None,
            "best_ask_size_lots": best_ask.get("size_lots") if best_ask else None,
            "bid_total_size_lots": depth_contract["top5_bid_volume_lots"],
            "ask_total_size_lots": depth_contract["top5_ask_volume_lots"],
            "spread": (
                best_ask["price"] - best_bid["price"]
                if best_bid and best_ask
                else None
            ),
            "depth_event_time": depth_event_time,
            **depth_contract,
        }
    )


def _apply_resolved_auction(payload: dict[str, Any], result: Any) -> None:
    auction = getattr(result.resolved, "auction", None)
    if auction is None or not result.resolved.health.facts_usable:
        return
    indicative_lots = _quantity_lots(auction.indicative_quantity)
    payload.update(
        {
            "auction_indicative_available": auction.indicative_price is not None,
            "auction_indicative_status": auction.state.value,
            "auction_indicative_source": auction.lineage.source,
            "auction_phase": auction.auction_type.value,
            "auction_event_time": auction.lineage.event_at,
            "indicative_match_available": auction.indicative_price is not None,
            "indicative_match_price": (
                float(auction.indicative_price)
                if auction.indicative_price is not None
                else None
            ),
            "indicative_match_volume_lots": indicative_lots,
            "indicative_match_price_source_field": "canonical.indicative_price",
            "indicative_match_volume_source_field": "canonical.indicative_quantity",
            "indicative_match_status_source_field": "canonical.state",
            "indicative_match_status": auction.state.value,
            "indicative_price_available": auction.indicative_price is not None,
            "indicative_price": (
                float(auction.indicative_price)
                if auction.indicative_price is not None
                else None
            ),
            "indicative_bid": (
                float(auction.best_bid.price)
                if auction.best_bid is not None
                and auction.best_bid.price is not None
                else None
            ),
            "indicative_ask": (
                float(auction.best_ask.price)
                if auction.best_ask is not None
                and auction.best_ask.price is not None
                else None
            ),
            "last_trade_before_auction": bool(payload.get("last_trade_available")),
        }
    )


def _finalize_shared_projection_semantics(
    payload: dict[str, Any],
    *,
    phase: str,
    session_close: dict[str, object] | None = None,
    requested_at: datetime | None = None,
) -> None:
    """Recompute compatibility semantics after typed depth/auction projection.

    ``_row_to_response`` intentionally suppresses the legacy JSON depth columns.
    Its first-pass semantics therefore cannot know whether Shared Data Core later
    selected a typed depth candidate.  Keep this finalizer presentation-only and
    derive it exclusively from already-resolved observations.
    """

    depth_available = bool(payload.get("depth_available"))
    last_trade_available = bool(payload.get("last_trade_available"))
    indicative_available = bool(
        payload.get("auction_indicative_available")
        or payload.get("indicative_match_available")
    )
    auction_phase = phase in {"preopen_auction", "closing_auction"}
    auction_book_available = bool(
        auction_phase
        and depth_available
        and (
            payload.get("best_bid_price") is not None
            or payload.get("best_ask_price") is not None
        )
    )
    payload.update(
        {
            "auction_book_available": auction_book_available,
            "auction_book_status": (
                "depth_and_indicative_match"
                if auction_book_available and indicative_available
                else "depth_only"
                if auction_book_available
                else "unavailable"
            ),
            "auction_book_time": (
                payload.get("depth_event_time")
                if auction_book_available
                else None
            ),
            "auction_best_bid": (
                payload.get("best_bid_price")
                if auction_book_available
                else None
            ),
            "auction_best_ask": (
                payload.get("best_ask_price")
                if auction_book_available
                else None
            ),
        }
    )
    if auction_book_available and payload.get("auction_event_time") is None:
        payload["auction_event_time"] = payload.get("depth_event_time")

    if phase == "preopen_auction":
        semantics = (
            "preopen_indicative_match_and_depth"
            if indicative_available and auction_book_available
            else "preopen_indicative_match"
            if indicative_available
            else "preopen_depth_only"
            if auction_book_available
            else "preopen_unavailable"
        )
        delivery_status = "live_depth_only" if depth_available else "unavailable"
        payload["price_available"] = False
    elif phase == "regular_live":
        semantics = (
            "live_trade_and_depth"
            if last_trade_available and depth_available
            else "delayed_current_session_trade"
            if last_trade_available
            and payload.get("freshness", {}).get("status") != "live"
            else "live_trade_only"
            if last_trade_available
            else "live_depth_only"
            if depth_available
            else "current_session_unavailable"
        )
        delivery_status = str(
            payload.get("freshness", {}).get("status") or "unavailable"
        )
        payload["price_available"] = last_trade_available
    elif phase == "closing_auction":
        semantics = (
            "closing_auction_indicative_match_and_depth"
            if indicative_available and auction_book_available
            else "closing_auction_indicative_match"
            if indicative_available
            else "closing_auction_depth_only"
            if auction_book_available
            else "closing_auction_last_trade"
            if last_trade_available
            else "closing_auction_pending"
        )
        delivery_status = "closing_auction"
        payload["price_available"] = last_trade_available
    elif phase == "close_resolution":
        semantics = (
            "close_resolution_candidate"
            if last_trade_available
            else "close_resolution_pending"
        )
        delivery_status = "close_resolution"
        payload["price_available"] = last_trade_available
    elif phase in POST_CLOSE_PHASES:
        # The session close is a separate resolved projection. It can own the
        # post-close headline while official daily remains pending.
        session_close_available = bool(
            isinstance(session_close, dict)
            and session_close.get("available") is True
        )
        if session_close_available:
            session_trade_date = session_close.get("trade_date")
            if isinstance(session_trade_date, datetime):
                session_trade_date = session_trade_date.date()
            elif isinstance(session_trade_date, str):
                try:
                    session_trade_date = date.fromisoformat(session_trade_date)
                except ValueError:
                    session_trade_date = None
            official_daily_released = bool(
                isinstance(session_trade_date, date)
                and session_trade_date
                <= expected_daily_price_date(now=_local_now(requested_at))
            )
            official_close_status = (
                "unavailable_after_release"
                if official_daily_released
                else "pending"
                if phase == "post_close_snapshot"
                else "unverified_latest_session"
            )
            semantics = "completed_session_close"
            delivery_status = "session_final"
            session_price = session_close.get("price")
            payload.update(
                {
                    "session_close_available": True,
                    "session_close_status": session_close.get("status"),
                    "session_close_price": session_price,
                    "session_close_trade_date": session_close.get("trade_date"),
                    "session_close_event_time": session_close.get("event_time"),
                    "session_close_confirmed_at": session_close.get("confirmed_at"),
                    "last_price": session_price,
                    "last_trade_price": session_price,
                    "last_trade_available": True,
                    "last_trade_is_current_session": True,
                    "price_available": True,
                    "trade_date": session_close.get("trade_date"),
                    "quote_time": session_close.get("event_time"),
                    "provider_event_time": session_close.get("event_time"),
                }
            )
            freshness = payload.get("freshness")
            if isinstance(freshness, dict):
                freshness.update(
                    {
                        "status": "session_final",
                        "is_live": False,
                        "is_stale": False,
                        "expected_trade_date": session_close.get("trade_date"),
                        "message": (
                            "The Taiwan session close is confirmed, but the "
                            "released official daily EOD evidence is unavailable."
                            if official_daily_released
                            else "The current Taiwan session close is confirmed; "
                            "official daily EOD publication remains pending."
                        ),
                    }
                )
        else:
            official_close_status = (
                "pending"
                if phase == "post_close_snapshot"
                else "unverified_latest_session"
            )
            semantics = (
                "session_close_unavailable"
                if phase == "post_close_snapshot"
                else "latest_session_close_unverified"
            )
            delivery_status = semantics
            payload.update(
                {
                    "session_close_available": False,
                    "session_close_status": (
                        session_close.get("status")
                        if isinstance(session_close, dict)
                        else "unavailable"
                    ),
                    "session_close_price": None,
                    "price_available": False,
                }
            )
        payload.update(
            {
                "official_close_available": False,
                "official_close_status": official_close_status,
                "official_close_price": None,
            }
        )
    else:
        semantics = "unavailable"
        delivery_status = "unavailable"
        payload["price_available"] = False

    payload.update(
        {
            "quote_semantics": semantics,
            "observation_semantics": semantics,
            "delivery_status": delivery_status,
        }
    )


def _component_evidence(result: Any, observation: Any) -> dict[str, Any]:
    lineage = getattr(observation, "lineage", None)
    return {
        "result_kind": result.result_kind,
        "provider": (
            lineage.provider
            if lineage is not None
            else result.resolved.health.selected_provider
        ),
        "source": (
            lineage.source
            if lineage is not None
            else result.resolved.health.selected_source
        ),
        "event_at": getattr(lineage, "event_at", None),
        "lineage": (
            lineage.model_dump(mode="json") if lineage is not None else None
        ),
        "resolved_health": result.resolved.health.model_dump(mode="json"),
        "dataset_health": (
            result.dataset_health.model_dump(mode="json")
            if result.dataset_health is not None
            else None
        ),
        "candidate_rejections": [
            item.model_dump(mode="json") for item in result.candidate_rejections
        ],
        "limitations": list(
            dict.fromkeys(
                (*result.limitations, *result.resolved.health.limitations)
            )
        ),
    }


def _official_close_component_evidence(result: Any) -> dict[str, Any]:
    bar = result.resolved.bars[-1] if result.resolved.bars else None
    evidence = _component_evidence(result, bar)
    raw_close = format(bar.close_price, "f") if bar is not None else None
    precision = (
        max(-bar.close_price.as_tuple().exponent, 0)
        if bar is not None
        else None
    )
    return {
        **evidence,
        "available": bool(bar is not None and result.resolved.health.facts_usable),
        "price": bar.close_price if bar is not None else None,
        "trade_date": (
            bar.end_at.astimezone(TAIWAN_TZ).date()
            if bar is not None
            else None
        ),
        "raw": raw_close,
        "display": raw_close,
        "precision": precision,
        "observation_semantics": "latest_completed_official_daily_close",
        "decision_usable": bool(result.resolved.health.research_usable),
    }


def _apply_resolved_official_close(
    response: dict[str, Any],
    result: Any,
    *,
    requested_at: datetime,
) -> None:
    """Promote only the canonical daily owner to current official close."""

    bar = result.resolved.bars[-1] if result.resolved.bars else None
    if bar is None or not result.resolved.health.facts_usable:
        return
    local_now = _local_now(requested_at)
    trade_date = bar.end_at.astimezone(TAIWAN_TZ).date()
    expected_date = expected_daily_price_date(now=local_now)
    phase = str(response.get("session_phase") or "")
    if phase not in POST_CLOSE_PHASES:
        return
    expected_session_date = _expected_trade_date_for_phase(phase, local_now)
    if trade_date != expected_session_date or trade_date > expected_date:
        return
    status = (
        "confirmed"
        if expected_session_date == local_now.date()
        else "confirmed_latest_session"
    )

    raw_close = format(bar.close_price, "f")
    response.update(
        {
            "official_close_available": True,
            "official_close_status": status,
            "official_close_price": bar.close_price,
            "official_close_trade_date": trade_date,
            "official_close_source": bar.lineage.source,
            "last_price": bar.close_price,
            "last_trade_price": bar.close_price,
            "last_trade_available": True,
            "last_trade_is_current_session": status == "confirmed",
            "trade_date": trade_date,
            "quote_time": bar.lineage.event_at,
            "provider_event_time": bar.lineage.event_at,
            "official_close_raw": raw_close,
            "official_close_display": raw_close,
            "official_close_precision": max(
                -bar.close_price.as_tuple().exponent,
                0,
            ),
            "official_close_precision_semantics": (
                "canonical_daily_decimal_preserved"
            ),
            "quote_semantics": (
                "official_close"
                if status == "confirmed"
                else "latest_completed_session_close"
            ),
            "observation_semantics": (
                "official_close"
                if status == "confirmed"
                else "latest_completed_session_close"
            ),
            "delivery_status": (
                "official_close"
                if status == "confirmed"
                else "latest_completed_session"
            ),
            "price_available": True,
        }
    )
    freshness = response.get("freshness")
    if isinstance(freshness, dict):
        freshness.update(
            {
                "status": (
                    "official_close"
                    if status == "confirmed"
                    else "latest_completed_session"
                ),
                "is_live": False,
                "is_stale": False,
                "message": "Canonical official daily close is available.",
            }
        )
    ohlc_summary = response.get("ohlc_summary")
    if isinstance(ohlc_summary, dict):
        ohlc_summary.update(
            {
                "last": bar.close_price,
                "event_time": bar.lineage.event_at,
                "semantics": "latest_completed_session",
            }
        )


def project_taiwan_quote_evidence_bundle(
    *,
    db: Session,
    stock_id: str,
    bundle: TaiwanQuoteEvidenceBundle,
) -> dict[str, Any]:
    """Stable outward projection over independently resolved components."""

    normalized_stock_id = _normalize_stock_id(stock_id)
    stock = _get_stock(db, normalized_stock_id)
    requested_at = _local_now(bundle.requested_at)
    phase = resolve_taiwan_stock_quote_phase(now=requested_at)
    quote_result = bundle.quote
    depth_result = bundle.depth
    auction_result = bundle.auction
    session_close_result = bundle.session_close
    official_close_result = bundle.official_close
    session_close = reconcile_taiwan_session_close(
        project_taiwan_session_close(session_close_result),
        official_close_result,
    )
    official_daily_bar = (
        official_close_result.resolved.bars[-1]
        if official_close_result.resolved.bars
        else None
    )
    row = _resolved_quote_row(db, quote_result)
    response = (
        _row_to_response(
            db,
            row,
            official_daily_bar=official_daily_bar,
            phase=phase,
            now=requested_at,
            suppress_depth=True,
            refresh_outcome="not_attempted",
        )
        if row is not None
        else _empty_response(
            stock=stock,
            phase=phase,
            now=requested_at,
            refresh_outcome="not_attempted",
        )
    )
    _apply_resolved_depth(response, depth_result, phase=phase)
    _apply_resolved_auction(response, auction_result)
    _finalize_shared_projection_semantics(
        response,
        phase=phase,
        session_close=session_close,
        requested_at=requested_at,
    )
    _apply_resolved_official_close(
        response,
        official_close_result,
        requested_at=requested_at,
    )
    selected_sources = [
        observation.lineage.source
        for observation in (
            getattr(quote_result.resolved, "quote", None),
            getattr(session_close_result.resolved, "quote", None),
            getattr(depth_result.resolved, "depth", None),
            getattr(auction_result.resolved, "auction", None),
        )
        if observation is not None
    ]
    acquisition_scope = (
        bundle.acquisition_scope.projection()
        if bundle.acquisition_scope is not None
        else None
    )
    attempted_providers = tuple(
        dict.fromkeys(
            str(provider).strip()
            for provider in quote_result.acquisition.providers_attempted
            if str(provider).strip()
        )
    )
    provider_attempts = [
        {
            "provider": provider,
            "status": (
                "selected" if provider == response.get("provider") else "attempted"
            ),
            "error": None,
        }
        for provider in attempted_providers
    ]
    response.update(
        {
            "source_chain": list(dict.fromkeys(selected_sources)),
            "primary_provider": (
                attempted_providers[0]
                if attempted_providers
                else response.get("provider")
            ),
            "provider_attempts": provider_attempts,
            "primary_source_status": quote_result.resolved.health.status.value,
            "primary_source_error": None,
            "fallback_used": (
                quote_result.resolved.health.status is ResolvedEvidenceStatus.FALLBACK
            ),
            "fallback_reason": (
                quote_result.resolved.health.limitations[0]
                if quote_result.resolved.health.limitations
                and quote_result.resolved.health.status
                is ResolvedEvidenceStatus.FALLBACK
                else None
            ),
            "data_core_result_kinds": [
                "quote",
                "depth",
                "auction",
                "bar_series",
            ],
            "data_core_components": {
                "quote.snapshot": _component_evidence(
                    quote_result,
                    getattr(quote_result.resolved, "quote", None),
                ),
                "quote.session_close": session_close,
                "quote.order_book": _component_evidence(
                    depth_result,
                    getattr(depth_result.resolved, "depth", None),
                ),
                "quote.auction": _component_evidence(
                    auction_result,
                    getattr(auction_result.resolved, "auction", None),
                ),
                "quote.official_close": _official_close_component_evidence(
                    official_close_result
                ),
            },
            "acquisition_scope": acquisition_scope,
            "read_policy": "cache_only",
        }
    )
    return response


def read_taiwan_quote_evidence_projection(
    *,
    db: Session,
    stock_id: str,
    requested_at: datetime | None = None,
) -> dict[str, Any]:
    """Cache-only AI/API projection over the canonical quote bundle."""

    bundle = read_taiwan_quote_evidence_bundle(
        db,
        stock_id=stock_id,
        requested_at=_local_now(requested_at),
    )
    return project_taiwan_quote_evidence_bundle(
        db=db,
        stock_id=stock_id,
        bundle=bundle,
    )


def acquire_taiwan_quote_evidence_projection(
    *,
    db: Session,
    stock_id: str,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    requested_at: datetime | None = None,
    requested_capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Explicit bounded acquisition followed by the same canonical projection."""

    bundle = acquire_taiwan_quote_evidence_bundle(
        db,
        stock_id=stock_id,
        policy=policy,
        requested_at=_local_now(requested_at),
        requested_capabilities=requested_capabilities,
    )
    payload = project_taiwan_quote_evidence_bundle(
        db=db,
        stock_id=stock_id,
        bundle=bundle,
    )
    payload["read_policy"] = policy.value
    return payload


def get_taiwan_stock_quote_depth(
    *,
    db: Session,
    stock_id: str,
    refresh: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """GET compatibility projection; ``refresh`` is intentionally inert."""

    del refresh
    return read_taiwan_quote_evidence_projection(
        db=db,
        stock_id=stock_id,
        requested_at=now,
    )
