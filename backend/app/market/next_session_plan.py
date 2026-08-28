from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.daily_ohlcv_platform import (
    TaiwanCanonicalDailyRow,
    project_taiwan_daily_rows,
    read_taiwan_official_daily,
)
from app.market.taiwan_rules import (
    TAIWAN_DAILY_PRICE_RELEASE_TIME,
    expected_daily_price_date,
)
from app.market.trading_calendar import (
    next_taiwan_trading_day,
    taiwan_market_session_phase,
    taiwan_now,
)


PLAN_KIND = "tw_stock_next_session_plan"
PLAN_VERSION = "tw_next_session_plan_v1"
METHODOLOGY_ID = "tw_next_session_sma_transition"
METHODOLOGY_VERSION = "1.0.0"
HISTORY_LIMIT = 250
MAX_GAP_DAYS = 10
TRANSITION_PERIODS = (20, 60)
KNOWN_RANGE_PERIOD = 20
SUPPORTED_MARKETS = frozenset({"TWSE", "TPEX"})


def _list_daily_history(
    *,
    db: Session,
    stock_id: str,
    limit: int,
) -> list[TaiwanCanonicalDailyRow]:
    try:
        result = read_taiwan_official_daily(
            db,
            stock_id=stock_id,
            limit=limit,
        )
    except ValueError:
        return []
    return project_taiwan_daily_rows(db, result)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def normalize_daily_history(rows: Iterable[Any]) -> tuple[list[dict[str, Any]], int]:
    """Return one deterministic row per trade date in ascending order.

    Compatibility input is still normalized deterministically, but production
    reads arrive pre-selected from the canonical daily resolver.
    """

    selected: dict[date, dict[str, Any]] = {}
    raw_count = 0
    for raw_count, row in enumerate(rows, start=1):
        row_date = _trade_date(_row_value(row, "trade_date"))
        if row_date is None:
            continue
        row_id = _row_value(row, "id")
        try:
            normalized_id = int(row_id) if row_id is not None else raw_count
        except (TypeError, ValueError):
            normalized_id = raw_count
        candidate = {
            "id": normalized_id,
            "source_id": _row_value(row, "source_id"),
            "trade_date": row_date,
            "open": _number(_row_value(row, "open_price") or _row_value(row, "open")),
            "high": _number(_row_value(row, "high_price") or _row_value(row, "high")),
            "low": _number(_row_value(row, "low_price") or _row_value(row, "low")),
            "close": _number(_row_value(row, "close_price") or _row_value(row, "close")),
        }
        previous = selected.get(row_date)
        if previous is None or normalized_id >= int(previous["id"]):
            selected[row_date] = candidate

    return [selected[key] for key in sorted(selected)], raw_count


def _window_has_acceptable_gaps(
    rows: list[dict[str, Any]],
    *,
    max_gap_days: int,
) -> bool:
    dates = [row["trade_date"] for row in rows]
    return all(
        (right - left).days <= max_gap_days
        for left, right in zip(dates, dates[1:])
    )


def _transition_window_issue(
    history: list[dict[str, Any]],
    *,
    period: int,
    max_gap_days: int,
) -> str | None:
    required = period - 1
    if period < 2:
        return f"ma{period}_period_invalid"
    if len(history) < required:
        return f"ma{period}_history_insufficient"

    transition_window = history[-required:]
    if any(_number(row.get("close")) is None for row in transition_window):
        return f"ma{period}_close_missing"
    if not _window_has_acceptable_gaps(
        transition_window,
        max_gap_days=max_gap_days,
    ):
        return f"ma{period}_history_gap"
    return None


def build_transition_level(
    history: list[dict[str, Any]],
    *,
    period: int,
    as_of_close: float,
    max_gap_days: int = MAX_GAP_DAYS,
) -> dict[str, Any] | None:
    required = period - 1
    if _transition_window_issue(
        history,
        period=period,
        max_gap_days=max_gap_days,
    ) is not None:
        return None

    transition_window = history[-required:]
    closes = [_number(row.get("close")) for row in transition_window]
    normalized_closes = [value for value in closes if value is not None]
    transition_sum = sum(normalized_closes)
    transition_price = transition_sum / required
    projected_ma_if_flat = (transition_sum + as_of_close) / period

    current_ma: float | None = None
    dropped_close: float | None = None
    if len(history) >= period:
        current_window = history[-period:]
        current_closes = [_number(row.get("close")) for row in current_window]
        if not any(value is None for value in current_closes) and _window_has_acceptable_gaps(
            current_window,
            max_gap_days=max_gap_days,
        ):
            current_ma = sum(
                value for value in current_closes if value is not None
            ) / period
            dropped_close = current_closes[0]

    relation = (
        "above"
        if as_of_close > transition_price
        else "below"
        if as_of_close < transition_price
        else "at"
    )
    role = "support" if relation == "above" else "reclaim" if relation == "below" else "pivot"
    move_pct = (
        (transition_price / as_of_close - 1) * 100
        if as_of_close > 0
        else None
    )
    rounded_current_ma = _round(current_ma)
    rounded_projected = _round(projected_ma_if_flat)
    drift = (
        rounded_projected - rounded_current_ma
        if rounded_projected is not None and rounded_current_ma is not None
        else None
    )

    return {
        "key": f"ma{period}_transition",
        "period": period,
        "transition_price": _round(transition_price),
        "current_ma": rounded_current_ma,
        "projected_ma_if_flat": rounded_projected,
        "drift_if_flat": _round(drift),
        "dropped_close": _round(dropped_close),
        "as_of_close_relation": relation,
        "role_at_as_of_close": role,
        "move_from_as_of_close_pct": _round(move_pct),
        "required_close_count": required,
        "available_close_count": len(normalized_closes),
        "window_start_date": transition_window[0]["trade_date"],
        "window_end_date": transition_window[-1]["trade_date"],
        "candidate_price_semantics": "hypothetical_target_session_close",
        "comparison_rule": (
            "candidate_close_gte_transition_price_means_"
            "candidate_close_gte_projected_ma"
        ),
    }


def build_known_range(
    history: list[dict[str, Any]],
    *,
    period: int = KNOWN_RANGE_PERIOD,
    max_gap_days: int = MAX_GAP_DAYS,
) -> dict[str, Any]:
    latest = history[-1] if history else None
    result = {
        "period": period,
        "support": None,
        "resistance": None,
        "previous_session_low": _round(latest.get("low")) if latest else None,
        "previous_session_high": _round(latest.get("high")) if latest else None,
        "previous_session_close": _round(latest.get("close")) if latest else None,
        "window_start_date": None,
        "window_end_date": None,
        "method": f"last_{period}_completed_session_high_low_including_as_of",
    }
    if len(history) < period:
        return result

    window = history[-period:]
    highs = [_number(row.get("high")) for row in window]
    lows = [_number(row.get("low")) for row in window]
    if (
        any(value is None for value in highs + lows)
        or not _window_has_acceptable_gaps(window, max_gap_days=max_gap_days)
    ):
        return result

    result.update(
        {
            "support": _round(min(value for value in lows if value is not None)),
            "resistance": _round(max(value for value in highs if value is not None)),
            "window_start_date": window[0]["trade_date"],
            "window_end_date": window[-1]["trade_date"],
        }
    )
    return result


def build_scenario_zones(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (
            (str(level["key"]), float(level["transition_price"]))
            for level in levels
            if _number(level.get("transition_price")) is not None
        ),
        key=lambda item: (item[1], item[0]),
    )
    if not ordered:
        return []
    if len(ordered) == 1:
        key, price = ordered[0]
        return [
            {
                "key": "below_available_level",
                "lower_bound": None,
                "upper_bound": price,
                "lower_bound_rule": None,
                "upper_bound_rule": "exclusive",
                "at_or_above_level_keys": [],
                "below_level_keys": [key],
            },
            {
                "key": "at_or_above_available_level",
                "lower_bound": price,
                "upper_bound": None,
                "lower_bound_rule": "inclusive",
                "upper_bound_rule": None,
                "at_or_above_level_keys": [key],
                "below_level_keys": [],
            },
        ]

    low_key, low_price = ordered[0]
    high_key, high_price = ordered[-1]
    if low_price == high_price:
        all_keys = sorted({key for key, _ in ordered})
        return [
            {
                "key": "below_confluence",
                "lower_bound": None,
                "upper_bound": low_price,
                "lower_bound_rule": None,
                "upper_bound_rule": "exclusive",
                "at_or_above_level_keys": [],
                "below_level_keys": all_keys,
            },
            {
                "key": "at_or_above_confluence",
                "lower_bound": low_price,
                "upper_bound": None,
                "lower_bound_rule": "inclusive",
                "upper_bound_rule": None,
                "at_or_above_level_keys": all_keys,
                "below_level_keys": [],
            },
        ]

    return [
        {
            "key": "below_both",
            "lower_bound": None,
            "upper_bound": low_price,
            "lower_bound_rule": None,
            "upper_bound_rule": "exclusive",
            "at_or_above_level_keys": [],
            "below_level_keys": [key for key, _ in ordered],
        },
        {
            "key": "between_transition_levels",
            "lower_bound": low_price,
            "upper_bound": high_price,
            "lower_bound_rule": "inclusive",
            "upper_bound_rule": "exclusive",
            "at_or_above_level_keys": [low_key],
            "below_level_keys": [high_key],
        },
        {
            "key": "at_or_above_both",
            "lower_bound": high_price,
            "upper_bound": None,
            "lower_bound_rule": "inclusive",
            "upper_bound_rule": None,
            "at_or_above_level_keys": [key for key, _ in ordered],
            "below_level_keys": [],
        },
    ]


def _trading_day_lag(latest: date | None, expected: date) -> int | None:
    if latest is None:
        return None
    if latest >= expected:
        return 0

    lag = 0
    cursor = latest
    while cursor < expected and lag <= 3660:
        cursor = next_taiwan_trading_day(cursor, include_value=False)
        lag += 1
    return lag if cursor == expected else None


def _target_session_state(target: date | None, local_now: datetime) -> str:
    if target is None:
        return "unavailable"
    if target > local_now.date():
        return "upcoming"
    if target < local_now.date():
        return "expired"
    phase = taiwan_market_session_phase(local_now)
    if phase == "post_close":
        return "completed_waiting_refresh"
    return "active"


def _base_contract(
    *,
    stock_id: str,
    stock: StockMaster | None,
    local_now: datetime,
    expected_trade_date: date,
    history: list[dict[str, Any]],
    raw_row_count: int,
) -> dict[str, Any]:
    latest_trade_date = history[-1]["trade_date"] if history else None
    source_ids = sorted(
        {
            int(row["source_id"])
            for row in history
            if row.get("source_id") is not None
        }
    )
    freshness_status = (
        "missing"
        if latest_trade_date is None
        else "current"
        if latest_trade_date == expected_trade_date
        else "stale"
        if latest_trade_date < expected_trade_date
        else "future"
    )
    return {
        "kind": PLAN_KIND,
        "version": PLAN_VERSION,
        "market": str(stock.market or "tw").upper() if stock else "TW",
        "stock_id": stock_id,
        "stock_name": stock.stock_name if stock else None,
        "instrument_type": stock.instrument_type if stock else None,
        "currency": "TWD",
        "price_unit": "TWD_per_share",
        "status": "missing",
        "generated_at": local_now,
        "as_of_trade_date": latest_trade_date,
        "target_trade_date": (
            next_taiwan_trading_day(latest_trade_date, include_value=False)
            if latest_trade_date
            else None
        ),
        "target_session_state": "unavailable",
        "as_of_close": _round(history[-1].get("close")) if history else None,
        "methodology": {
            "id": METHODOLOGY_ID,
            "version": METHODOLOGY_VERSION,
            "price_series": "raw_unadjusted_completed_daily_close",
            "candidate_price_semantics": "hypothetical_target_session_close",
            "transition_formula": "mean(last_N_minus_1_completed_closes)",
            "projected_ma_formula": "(sum(last_N_minus_1_closes)+candidate_close)/N",
            "comparison_rule": (
                "candidate_close_gte_transition_price_iff_"
                "candidate_close_gte_projected_ma"
            ),
        },
        "freshness": {
            "status": freshness_status,
            "expected_trade_date": expected_trade_date,
            "latest_trade_date": latest_trade_date,
            "calendar_day_lag": (
                max((expected_trade_date - latest_trade_date).days, 0)
                if latest_trade_date
                else None
            ),
            "trading_day_lag": _trading_day_lag(
                latest_trade_date,
                expected_trade_date,
            ),
            "release_time": TAIWAN_DAILY_PRICE_RELEASE_TIME.strftime("%H:%M"),
            "release_timezone": "Asia/Taipei",
            "checked_at": local_now,
        },
        "history": {
            "requested_limit": HISTORY_LIMIT,
            "raw_row_count": raw_row_count,
            "distinct_trade_date_count": len(history),
            "duplicate_trade_date_count": max(raw_row_count - len(history), 0),
            "valid_close_count": sum(row.get("close") is not None for row in history),
            "first_trade_date": history[0]["trade_date"] if history else None,
            "latest_trade_date": latest_trade_date,
            "source_ids": source_ids,
            "max_gap_days": MAX_GAP_DAYS,
        },
        "readiness": {
            "status": "missing",
            "decision_usable": False,
            "reason_codes": [],
            "available_level_keys": [],
            "missing_level_keys": ["ma20_transition", "ma60_transition"],
        },
        "levels": [],
        "known_range": build_known_range(history),
        "scenario_zones": [],
        "corporate_action_adjustment": {
            "status": "not_applied",
            "event_check": "not_performed",
            "price_series": "raw_unadjusted_completed_daily_close",
        },
        "missing": [],
        "warning_codes": [],
        "warnings": [],
        "limitation_codes": [
            "conditional_level_not_price_forecast",
            "intraday_candidate_is_hypothetical_close",
            "corporate_action_adjustment_not_applied",
            "transition_price_not_tick_rounded",
        ],
        "limitations": [
            "Transition levels are conditional price thresholds, not target-session price forecasts.",
            "Any intraday candidate price must be interpreted as a hypothetical target-session close.",
            "The v1 price series is raw and unadjusted; corporate-action adjustment and event checks are not applied.",
            "Transition prices are mathematical thresholds and are not rounded to Taiwan exchange tick sizes.",
        ],
        "source_refs": [
            {"type": "table", "name": "market_daily_price"},
            {"type": "table", "name": "stock_master"},
            {"type": "calendar", "name": "app.market.trading_calendar"},
            {"type": "derived", "name": "app.market.next_session_plan"},
        ],
    }


def build_tw_stock_next_session_plan(
    *,
    db: Session,
    stock_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_stock_id = str(stock_id or "").strip()
    if not normalized_stock_id:
        raise ValueError("stock_id is required.")

    local_now = taiwan_now(now)
    expected_trade_date = expected_daily_price_date(now=local_now)
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    raw_rows = _list_daily_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=HISTORY_LIMIT,
    )
    history, raw_row_count = normalize_daily_history(raw_rows)
    contract = _base_contract(
        stock_id=normalized_stock_id,
        stock=stock,
        local_now=local_now,
        expected_trade_date=expected_trade_date,
        history=history,
        raw_row_count=raw_row_count,
    )
    target_trade_date = contract["target_trade_date"]
    target_session_state = _target_session_state(target_trade_date, local_now)
    contract["target_session_state"] = target_session_state

    instrument_type = str(stock.instrument_type or "unknown").strip().lower() if stock else "missing"
    market = str(stock.market or "unknown").strip().upper() if stock else "UNKNOWN"
    explicitly_not_applicable = stock is not None and (
        instrument_type not in {"stock", "unknown"}
        or (market not in SUPPORTED_MARKETS and market != "UNKNOWN")
    )
    if explicitly_not_applicable:
        contract["status"] = "not_applicable"
        contract["readiness"].update(
            {
                "status": "not_applicable",
                "decision_usable": False,
                "reason_codes": ["unsupported_instrument_or_market"],
            }
        )
        contract["warning_codes"].append("unsupported_instrument_or_market")
        contract["warnings"].append(
            "The v1 next-session plan applies only to Taiwan-listed or OTC stocks."
        )
        return contract

    as_of_close = _number(contract.get("as_of_close"))
    if not history or as_of_close is None:
        contract["missing"].append("market_daily_price.close")
        contract["readiness"]["reason_codes"].append("daily_close_missing")
        return contract

    levels = [
        level
        for period in TRANSITION_PERIODS
        if (
            level := build_transition_level(
                history,
                period=period,
                as_of_close=as_of_close,
            )
        )
        is not None
    ]
    available_level_keys = [str(level["key"]) for level in levels]
    missing_level_keys = [
        f"ma{period}_transition"
        for period in TRANSITION_PERIODS
        if f"ma{period}_transition" not in available_level_keys
    ]
    missing_level_reasons = [
        issue
        for period in TRANSITION_PERIODS
        if f"ma{period}_transition" in missing_level_keys
        if (
            issue := _transition_window_issue(
                history,
                period=period,
                max_gap_days=MAX_GAP_DAYS,
            )
        )
        is not None
    ]
    contract["levels"] = levels
    contract["scenario_zones"] = build_scenario_zones(levels)
    contract["readiness"]["available_level_keys"] = available_level_keys
    contract["readiness"]["missing_level_keys"] = missing_level_keys

    if "ma20_transition" not in available_level_keys:
        contract["missing"].append("market_daily_price.close.ma20_transition_window")
        contract["readiness"]["reason_codes"].extend(
            reason
            for reason in missing_level_reasons
            if reason.startswith("ma20_")
        )
        return contract

    freshness_status = str(contract["freshness"]["status"])
    metadata_complete = stock is not None and instrument_type == "stock" and market in SUPPORTED_MARKETS
    known_range_complete = (
        contract["known_range"].get("support") is not None
        and contract["known_range"].get("resistance") is not None
    )
    reasons: list[str] = []

    if target_session_state == "completed_waiting_refresh":
        status = "pending"
        reasons.append("awaiting_latest_completed_daily_bar")
    elif freshness_status == "stale":
        status = "stale"
        reasons.append("daily_price_stale")
    elif freshness_status == "future":
        status = "partial"
        reasons.append("daily_price_date_ahead_of_expected")
    elif target_session_state == "expired":
        status = "stale"
        reasons.append("target_session_expired")
    elif missing_level_keys or not known_range_complete or not metadata_complete:
        status = "partial"
        if missing_level_keys:
            reasons.append("level_history_partial")
            reasons.extend(missing_level_reasons)
        if not known_range_complete:
            reasons.append("known_range_partial")
        if not metadata_complete:
            reasons.append("instrument_metadata_partial")
    else:
        status = "ready"

    decision_usable = (
        status in {"ready", "partial"}
        and freshness_status == "current"
        and target_session_state in {"active", "upcoming"}
        and metadata_complete
    )
    contract["status"] = status
    contract["readiness"].update(
        {
            "status": status,
            "decision_usable": decision_usable,
            "reason_codes": reasons,
        }
    )
    if missing_level_keys:
        contract["missing"].extend(
            f"market_daily_price.close.{key}_window"
            for key in missing_level_keys
        )
    if status == "pending":
        contract["warning_codes"].append("awaiting_latest_completed_daily_bar")
        contract["warnings"].append(
            "The target session has completed, but the latest released daily bar is not yet available for the next plan."
        )
    elif status == "stale":
        contract["warning_codes"].append("daily_price_stale")
        contract["warnings"].append(
            "The latest completed daily price is older than the expected Taiwan trade date."
        )
    if not metadata_complete:
        contract["warning_codes"].append("instrument_metadata_partial")
        contract["warnings"].append(
            "Stock master metadata is missing or incomplete; the calculated levels are not decision-usable."
        )
    return contract


__all__ = [
    "HISTORY_LIMIT",
    "KNOWN_RANGE_PERIOD",
    "MAX_GAP_DAYS",
    "PLAN_KIND",
    "PLAN_VERSION",
    "TRANSITION_PERIODS",
    "build_known_range",
    "build_scenario_zones",
    "build_transition_level",
    "build_tw_stock_next_session_plan",
    "normalize_daily_history",
]
