from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping

from app.market.trading_calendar import taiwan_market_session_phase
from app.market.twse_mis_observation import resolve_twse_mis_actual_trade


TW_MARKET_BREADTH_STOCK_STATE_VERSION = "tw.market_breadth.stock_state.v2"
TW_MARKET_BREADTH_VERSION = "tw.market.breadth.v2"
ACTUAL_TRADE_SESSIONS = frozenset(
    {"regular", "closing_auction", "close_resolution", "post_close"}
)
AUCTION_SESSIONS = frozenset({"preopen", "closing_auction"})
BREADTH_COVERAGE_REASON_KEYS = (
    "advance",
    "decline",
    "unchanged",
    "valid_no_trade",
    "suspended_or_not_tradable",
    "provider_missing",
    "mapping_error",
    "unknown",
)


def _positive_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) and parsed > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
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
    last_trade_volume_lots: Any = None,
) -> dict[str, Any]:
    """Resolve formal-trade and auction price semantics without IO or mutation."""

    market_session = taiwan_breadth_market_session(snapshot_as_of)
    parsed_last_trade = _positive_number(last_trade_price)
    parsed_volume = _nonnegative_int(cumulative_volume_lots)
    actual_trade = resolve_twse_mis_actual_trade(
        expected_trade_date=snapshot_as_of.date() if snapshot_as_of else None,
        observation_trade_date=trade_date,
        provider_event_time=snapshot_as_of,
        trial_status=indicative_status,
        last_trade_price=parsed_last_trade,
        last_trade_volume_lots=_nonnegative_int(last_trade_volume_lots),
        cumulative_volume_lots=parsed_volume,
    )
    has_fresh_actual_trade = actual_trade["actual_trade_price_available"]

    cached_price = None
    cached_price_as_of = None
    if (
        market_session in ACTUAL_TRADE_SESSIONS
        and actual_trade["trade_date_matches"]
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
        "actual_trade_reason_code": actual_trade["reason_code"],
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


def classify_twse_mis_breadth_coverage(
    rows: list[Mapping[str, Any]],
    *,
    universe_count: int,
) -> dict[str, int]:
    """Partition provider rows without turning missing quotes into unchanged."""

    counts = {key: 0 for key in BREADTH_COVERAGE_REASON_KEYS}
    received_codes: set[str] = set()
    for row in rows:
        code = str(row.get("code") or "").strip()
        if not code or code in received_codes:
            continue
        received_codes.add(code)
        direction = str(row.get("direction") or "").strip().lower()
        if direction in {"advance", "decline", "unchanged"}:
            counts[direction] += 1
            continue

        market_session = str(row.get("market_session") or "unknown").strip()
        volume = _nonnegative_int(row.get("cumulative_volume_lots"))
        previous_close = _positive_number(row.get("previous_close"))
        has_actual_trade = row.get("has_actual_trade") is True
        if (
            market_session in ACTUAL_TRADE_SESSIONS
            and not has_actual_trade
            and volume == 0
            and previous_close is not None
        ):
            counts["valid_no_trade"] += 1
        elif previous_close is None or (not has_actual_trade and (volume or 0) > 0):
            counts["mapping_error"] += 1
        else:
            counts["unknown"] += 1

    counts["provider_missing"] = max(universe_count - len(received_codes), 0)
    partition_total = sum(counts.values())
    if partition_total < universe_count:
        counts["unknown"] += universe_count - partition_total
    elif partition_total > universe_count:
        counts["unknown"] = max(
            counts["unknown"] - (partition_total - universe_count),
            0,
        )
    return counts
