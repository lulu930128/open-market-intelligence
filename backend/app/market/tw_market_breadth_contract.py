from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from app.market.trading_calendar import taiwan_market_session_phase


TW_MARKET_BREADTH_STOCK_STATE_VERSION = "tw.market_breadth.stock_state.v2"
TW_MARKET_BREADTH_VERSION = "tw.market.breadth.v2"
ACTUAL_TRADE_SESSIONS = frozenset({"regular", "closing_auction", "post_close"})
AUCTION_SESSIONS = frozenset({"preopen", "closing_auction"})


def _positive_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def taiwan_breadth_market_session(snapshot_as_of: datetime | None) -> str:
    if snapshot_as_of is None:
        return "unknown"
    phase = taiwan_market_session_phase(snapshot_as_of)
    if phase in {"preopen_pending", "preopen"}:
        return "preopen"
    return phase


def resolve_twse_mis_breadth_price_state(
    *,
    trade_date: date | None,
    snapshot_as_of: datetime | None,
    last_trade_price: Any,
    cumulative_volume_lots: Any,
    indicative_price: Any,
    indicative_volume_lots: Any,
    indicative_status: Any,
    cached_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve formal-trade and auction price semantics without IO or mutation."""

    market_session = taiwan_breadth_market_session(snapshot_as_of)
    parsed_last_trade = _positive_number(last_trade_price)
    parsed_volume = _nonnegative_int(cumulative_volume_lots)
    has_fresh_actual_trade = bool(
        market_session in ACTUAL_TRADE_SESSIONS
        and parsed_last_trade is not None
        and parsed_volume is not None
        and parsed_volume > 0
    )

    cached_price = None
    cached_price_as_of = None
    if (
        market_session in ACTUAL_TRADE_SESSIONS
        and isinstance(cached_state, Mapping)
        and cached_state.get("trade_date") == trade_date
        and cached_state.get("has_actual_trade") is True
    ):
        cached_price = _positive_number(cached_state.get("price"))
        cached_price_as_of = _aware_datetime(cached_state.get("price_as_of"))

    if has_fresh_actual_trade:
        current_price = parsed_last_trade
        price_as_of = snapshot_as_of
        price_source = "z"
        has_actual_trade = True
        cache_update = {
            "trade_date": trade_date,
            "price": current_price,
            "price_as_of": price_as_of,
            "has_actual_trade": True,
            "state_contract_version": TW_MARKET_BREADTH_STOCK_STATE_VERSION,
        }
    elif cached_price is not None and cached_price_as_of is not None:
        current_price = cached_price
        price_as_of = cached_price_as_of
        price_source = "session_cache"
        has_actual_trade = True
        cache_update = None
    else:
        current_price = None
        price_as_of = None
        price_source = None
        has_actual_trade = False
        cache_update = None

    parsed_indicative_status = _nonnegative_int(indicative_status)
    parsed_indicative_price = _positive_number(indicative_price)
    parsed_indicative_volume = _nonnegative_int(indicative_volume_lots)
    indicative_match_available = bool(
        market_session in AUCTION_SESSIONS
        and parsed_indicative_status not in {None, 0}
        and parsed_indicative_price is not None
    )

    return {
        "market_session": market_session,
        "snapshot_as_of": snapshot_as_of,
        "current_price": current_price,
        "price_as_of": price_as_of,
        "price_semantics": "actual_trade" if has_actual_trade else "unavailable",
        "price_source": price_source,
        "has_actual_trade": has_actual_trade,
        "cumulative_volume_lots": parsed_volume,
        "indicative_match_available": indicative_match_available,
        "indicative_match_price": (
            parsed_indicative_price if indicative_match_available else None
        ),
        "indicative_match_volume_lots": (
            parsed_indicative_volume if indicative_match_available else None
        ),
        "indicative_price_source": "pz" if indicative_match_available else None,
        "state_contract_version": TW_MARKET_BREADTH_STOCK_STATE_VERSION,
        "cache_update": cache_update,
    }
