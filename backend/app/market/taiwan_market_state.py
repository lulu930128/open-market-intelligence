from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TaiwanMarketMinuteState, utc_now
from app.market.trading_calendar import TAIWAN_TZ


SUPPORTED_MARKETS = {"TWSE", "TPEX"}
INDEX_ID_BY_MARKET = {"TWSE": "TAIEX", "TPEX": "TPEX"}
TAIWAN_SESSION_CLOSE = time(13, 30)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None


def _as_taiwan_datetime(value: Any, *, naive_is_local: bool = False) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIWAN_TZ if naive_is_local else timezone.utc)
    return value.astimezone(TAIWAN_TZ)


def _as_trade_date(value: Any) -> date | None:
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


def _minute_at_for_payload(
    *,
    payload: dict[str, Any],
    trade_date: date,
    finalized: bool,
    now: datetime | None,
) -> datetime:
    if finalized:
        return datetime.combine(trade_date, TAIWAN_SESSION_CLOSE, tzinfo=TAIWAN_TZ)
    observed_at = (
        _as_taiwan_datetime(payload.get("as_of"))
        or _as_taiwan_datetime(now)
        or datetime.now(TAIWAN_TZ)
    )
    if observed_at.time() > TAIWAN_SESSION_CLOSE:
        return datetime.combine(trade_date, TAIWAN_SESSION_CLOSE, tzinfo=TAIWAN_TZ)
    return observed_at.replace(second=0, microsecond=0)


def _validated_quality_status(
    *,
    raw_status: str,
    breadth: dict[str, Any],
    cumulative_trade_value: int | None,
    previous_trade_value: int | None,
    out_of_order: bool,
    finalized: bool,
) -> str:
    if raw_status != "ready":
        return raw_status
    numeric_counts = [
        _as_int(breadth.get(key))
        for key in (
            "advance_count",
            "decline_count",
            "unchanged_count",
            "total_count",
            "limit_up_count",
            "limit_down_count",
            "unknown_count",
            "missing_count",
        )
    ]
    if any(value is not None and value < 0 for value in numeric_counts):
        return "invalid_value"
    total_count = _as_int(breadth.get("total_count"))
    categorized_count = sum(
        _as_int(breadth.get(key)) or 0
        for key in ("advance_count", "decline_count", "unchanged_count", "unknown_count")
    )
    if total_count is not None and categorized_count > total_count:
        return "invalid_value"
    if cumulative_trade_value is not None and cumulative_trade_value < 0:
        return "invalid_value"
    if (
        not finalized
        and cumulative_trade_value is not None
        and previous_trade_value is not None
        and cumulative_trade_value < previous_trade_value
    ):
        return "invalid_value"
    if out_of_order and not finalized:
        return "out_of_order"
    return "ready"


def persist_taiwan_market_minute_state(
    db: Session,
    *,
    payload: dict[str, Any],
    finalized: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    inserted_count = 0
    updated_count = 0
    skipped: list[str] = []
    persisted: list[dict[str, Any]] = []

    for item in payload.get("indices") or []:
        if not isinstance(item, dict):
            continue
        market = str(item.get("market") or "").upper()
        index_id = str(item.get("index_id") or INDEX_ID_BY_MARKET.get(market) or "").upper()
        if market not in SUPPORTED_MARKETS or not index_id:
            continue
        breadth = item.get("breadth") if isinstance(item.get("breadth"), dict) else None
        if not breadth:
            skipped.append(f"{index_id}:missing_breadth")
            continue
        trade_date = _as_trade_date(breadth.get("trade_date") or item.get("time"))
        if trade_date is None:
            skipped.append(f"{index_id}:missing_trade_date")
            continue
        minute_at = _minute_at_for_payload(
            payload=payload,
            trade_date=trade_date,
            finalized=finalized,
            now=now,
        )
        breadth_status = (
            item.get("breadth_status")
            if isinstance(item.get("breadth_status"), dict)
            else {}
        )
        raw_quality_status = str(breadth_status.get("status") or "unknown")
        breadth_scope = str(breadth.get("scope") or "") or None
        cumulative_trade_value = _as_int(
            breadth.get("trade_value")
            if breadth.get("trade_value") is not None
            else item.get("trade_value")
        )
        existing = (
            db.query(TaiwanMarketMinuteState)
            .filter(TaiwanMarketMinuteState.market == market)
            .filter(TaiwanMarketMinuteState.index_id == index_id)
            .filter(TaiwanMarketMinuteState.minute_at == minute_at)
            .first()
        )
        latest_prior = (
            db.query(TaiwanMarketMinuteState)
            .filter(TaiwanMarketMinuteState.market == market)
            .filter(TaiwanMarketMinuteState.index_id == index_id)
            .filter(TaiwanMarketMinuteState.trade_date == trade_date)
            .filter(TaiwanMarketMinuteState.minute_at < minute_at)
            .order_by(TaiwanMarketMinuteState.minute_at.desc())
            .first()
        )
        latest_any = (
            db.query(TaiwanMarketMinuteState)
            .filter(TaiwanMarketMinuteState.market == market)
            .filter(TaiwanMarketMinuteState.index_id == index_id)
            .filter(TaiwanMarketMinuteState.trade_date == trade_date)
            .order_by(TaiwanMarketMinuteState.minute_at.desc())
            .first()
        )
        previous_trade_value = (
            existing.cumulative_trade_value
            if existing is not None
            else latest_prior.cumulative_trade_value
            if latest_prior is not None
            else None
        )
        quality_status = _validated_quality_status(
            raw_status=raw_quality_status,
            breadth=breadth,
            cumulative_trade_value=cumulative_trade_value,
            previous_trade_value=previous_trade_value,
            out_of_order=(
                existing is None
                and latest_any is not None
                and _row_minute_at(latest_any) > minute_at
            ),
            finalized=finalized,
        )
        official_flag = quality_status == "ready" and breadth_scope == "full_market"
        session_status = (
            "final"
            if finalized and official_flag
            else "final_partial"
            if finalized
            else "provisional"
        )
        values = {
            "market": market,
            "index_id": index_id,
            "trade_date": trade_date,
            "minute_at": minute_at,
            "session_status": session_status,
            "breadth_status": quality_status,
            "breadth_scope": breadth_scope,
            "quality_status": quality_status,
            "index_value": _as_float(item.get("close")),
            "index_change": _as_float(item.get("change")),
            "index_change_pct": _as_float(item.get("change_pct")),
            "advance_count": _as_int(breadth.get("advance_count")),
            "decline_count": _as_int(breadth.get("decline_count")),
            "unchanged_count": _as_int(breadth.get("unchanged_count")),
            "total_count": _as_int(breadth.get("total_count")),
            "limit_up_count": _as_int(breadth.get("limit_up_count")),
            "limit_down_count": _as_int(breadth.get("limit_down_count")),
            "unknown_count": _as_int(breadth.get("unknown_count")),
            "missing_count": _as_int(breadth.get("missing_count")),
            "cumulative_trade_value": cumulative_trade_value,
            "estimated_full_day_trade_value": _as_int(item.get("estimated_trade_value")),
            "source": str(breadth.get("source") or item.get("source") or "unknown"),
            "source_category": "official_public" if official_flag else "normalized_cache",
            "source_url": breadth.get("source_url") or item.get("source_url"),
            "official_flag": official_flag,
            "derived_flag": True,
            "updated_at": utc_now(),
        }
        row = existing
        if row is None:
            row = TaiwanMarketMinuteState(**values)
            db.add(row)
            inserted_count += 1
        else:
            for key, value in values.items():
                setattr(row, key, value)
            updated_count += 1
        persisted.append(
            {
                "market": market,
                "index_id": index_id,
                "trade_date": trade_date.isoformat(),
                "minute_at": minute_at.isoformat(),
                "session_status": session_status,
                "quality_status": quality_status,
            }
        )

    if inserted_count or updated_count:
        db.commit()
    return {
        "kind": "taiwan_market_minute_state_persist",
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "skipped": skipped,
        "rows": persisted,
    }


def _row_minute_at(row: TaiwanMarketMinuteState) -> datetime:
    return _as_taiwan_datetime(row.minute_at, naive_is_local=True) or datetime.combine(
        row.trade_date,
        time.min,
        tzinfo=TAIWAN_TZ,
    )


def _complete_minute_groups(
    rows: list[TaiwanMarketMinuteState],
) -> dict[datetime, dict[str, TaiwanMarketMinuteState]]:
    groups: dict[datetime, dict[str, TaiwanMarketMinuteState]] = defaultdict(dict)
    for row in rows:
        groups[_row_minute_at(row)][row.market] = row
    return groups


def _combined_trade_value(rows_by_market: dict[str, TaiwanMarketMinuteState]) -> int | None:
    if any(
        row.quality_status != "ready"
        for market, row in rows_by_market.items()
        if market in SUPPORTED_MARKETS
    ):
        return None
    values = [
        row.cumulative_trade_value
        for market, row in rows_by_market.items()
        if market in SUPPORTED_MARKETS
    ]
    if len(values) < len(SUPPORTED_MARKETS) or any(value is None for value in values):
        return None
    return sum(int(value) for value in values if value is not None)


def _baseline_payload(
    current_value: int | None,
    values: list[int],
    days: int,
    *,
    dates: list[str] | None = None,
) -> dict[str, Any]:
    selected = values[-days:]
    selected_dates = (dates or [])[-len(selected) :] if selected else []
    baseline = int(median(selected)) if selected else None
    ratio = current_value / baseline if current_value is not None and baseline not in {None, 0} else None
    return {
        "requested_days": days,
        "sample_days": len(selected),
        "sample_status": (
            "complete"
            if len(selected) >= days
            else "provisional"
            if selected
            else "empty"
        ),
        "samples": [
            {
                "trade_date": selected_dates[index]
                if index < len(selected_dates)
                else None,
                "cumulative_trade_value": value,
            }
            for index, value in enumerate(selected)
        ],
        "median_cumulative_trade_value": baseline,
        "pace_ratio": ratio,
    }


def read_taiwan_market_volume_state(
    db: Session,
    *,
    lookback_days: int = 20,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    latest_trade_date = db.query(TaiwanMarketMinuteState.trade_date).order_by(
        TaiwanMarketMinuteState.trade_date.desc()
    ).limit(1).scalar()
    if latest_trade_date is None:
        return {
            "kind": "taiwan_market_volume_state",
            "generated_at": generated_at.isoformat(),
            "as_of": None,
            "trade_date": None,
            "status": "empty",
            "session_status": "unavailable",
            "currency": "TWD",
            "trade_value_unit": "TWD",
            "current_cumulative_trade_value": None,
            "available_cumulative_trade_value": None,
            "trade_value_available": False,
            "trade_value_complete": False,
            "trade_value_status": "missing",
            "included_markets": [],
            "missing_markets": ["TWSE", "TPEX"],
            "trade_value_estimate": None,
            "trade_value_estimate_method": "not_estimated",
            "same_time_baseline_5d": _baseline_payload(None, [], 5),
            "same_time_baseline_20d": _baseline_payload(None, [], 20),
            "field_status": {
                "current_cumulative_trade_value": {
                    "status": "missing",
                    "reason": "No Taiwan market minute-state row is available.",
                },
                "previous_minute_cumulative_trade_value": {
                    "status": "missing",
                    "reason": "No prior complete minute is available.",
                },
                "one_minute_trade_value_change": {
                    "status": "missing",
                    "reason": "Current and previous complete minutes are required.",
                },
            },
            "markets": [],
            "warnings": [
                "Minute-level market state history is empty; same-time volume baselines will accumulate from the scheduler."
            ],
            "source_refs": [{"type": "table", "name": "taiwan_market_minute_state"}],
        }

    current_rows = (
        db.query(TaiwanMarketMinuteState)
        .filter(TaiwanMarketMinuteState.trade_date == latest_trade_date)
        .order_by(TaiwanMarketMinuteState.minute_at.asc())
        .all()
    )
    current_groups = _complete_minute_groups(current_rows)
    complete_current = [
        minute_at
        for minute_at, rows_by_market in current_groups.items()
        if SUPPORTED_MARKETS.issubset(rows_by_market)
    ]
    selected_minute = max(complete_current or current_groups.keys())
    selected_rows = current_groups[selected_minute]
    current_value = _combined_trade_value(selected_rows)
    available_markets = [
        market
        for market in ("TWSE", "TPEX")
        if market in selected_rows
        and selected_rows[market].cumulative_trade_value is not None
        and selected_rows[market].quality_status == "ready"
    ]
    missing_markets = [
        market for market in ("TWSE", "TPEX") if market not in available_markets
    ]
    available_current_value = (
        sum(
            int(selected_rows[market].cumulative_trade_value or 0)
            for market in available_markets
        )
        if available_markets
        else None
    )

    previous_minutes = [minute_at for minute_at in complete_current if minute_at < selected_minute]
    previous_value = (
        _combined_trade_value(current_groups[max(previous_minutes)])
        if previous_minutes
        else None
    )
    one_minute_change = (
        current_value - previous_value
        if current_value is not None and previous_value is not None
        else None
    )

    history_start = latest_trade_date - timedelta(days=max(lookback_days * 3, 45))
    history_rows = (
        db.query(TaiwanMarketMinuteState)
        .filter(TaiwanMarketMinuteState.trade_date >= history_start)
        .filter(TaiwanMarketMinuteState.trade_date < latest_trade_date)
        .order_by(
            TaiwanMarketMinuteState.trade_date.asc(),
            TaiwanMarketMinuteState.minute_at.asc(),
        )
        .all()
    )
    rows_by_date: dict[date, list[TaiwanMarketMinuteState]] = defaultdict(list)
    for row in history_rows:
        rows_by_date[row.trade_date].append(row)
    historical_values: list[int] = []
    historical_dates: list[str] = []
    comparison_time = selected_minute.time()
    for trade_date_value in sorted(rows_by_date):
        groups = _complete_minute_groups(rows_by_date[trade_date_value])
        candidates = [
            minute_at
            for minute_at, rows_by_market in groups.items()
            if minute_at.time() <= comparison_time
            and SUPPORTED_MARKETS.issubset(rows_by_market)
        ]
        if not candidates:
            continue
        value = _combined_trade_value(groups[max(candidates)])
        if value is not None:
            historical_values.append(value)
            historical_dates.append(trade_date_value.isoformat())
    historical_values = historical_values[-max(lookback_days, 20) :]
    historical_dates = historical_dates[-max(lookback_days, 20) :]

    market_payloads = []
    for market in ("TWSE", "TPEX"):
        row = selected_rows.get(market)
        if row is None:
            continue
        market_payloads.append(
            {
                "market": market,
                "index_id": row.index_id,
                "currency": "TWD",
                "trade_value_unit": "TWD",
                "cumulative_trade_value": row.cumulative_trade_value,
                "estimated_full_day_trade_value": row.estimated_full_day_trade_value,
                "advance_count": row.advance_count,
                "decline_count": row.decline_count,
                "unchanged_count": row.unchanged_count,
                "total_count": row.total_count,
                "session_status": row.session_status,
                "quality_status": row.quality_status,
                "source": row.source,
                "source_category": row.source_category,
                "official_flag": row.official_flag,
                "derived_flag": row.derived_flag,
            }
        )
    warnings: list[str] = []
    if current_value is None:
        warnings.append("TWSE and TPEX cumulative trade value are not both available at the selected minute.")
    if len(historical_values) < 5:
        warnings.append(
            "Fewer than 5 prior sessions are available at the same minute; volume pace remains provisional."
        )
    if len(historical_values) < 20:
        warnings.append(
            "The 20-session same-time baseline is incomplete and will improve as minute history accumulates."
        )
    session_statuses = {row.session_status for row in selected_rows.values()}
    session_status = "final" if session_statuses == {"final"} else "provisional"
    field_status = {
        "current_cumulative_trade_value": {
            "status": "available" if current_value is not None else "missing",
            "source": "taiwan_market_minute_state" if current_value is not None else None,
            "reason": (
                None
                if current_value is not None
                else "TWSE and TPEX same-minute trade values are not both usable."
            ),
        },
        "previous_minute_cumulative_trade_value": {
            "status": "available" if previous_value is not None else "missing",
            "source": "taiwan_market_minute_state" if previous_value is not None else None,
            "reason": (
                None
                if previous_value is not None
                else "No prior complete TWSE+TPEX minute exists for this session."
            ),
        },
        "one_minute_trade_value_change": {
            "status": "available" if one_minute_change is not None else "missing",
            "source": "derived_from_complete_minutes"
            if one_minute_change is not None
            else None,
            "reason": (
                None
                if one_minute_change is not None
                else "Current and previous complete TWSE+TPEX minutes are required."
            ),
        },
    }
    return {
        "kind": "taiwan_market_volume_state",
        "generated_at": generated_at.isoformat(),
        "as_of": selected_minute.isoformat(),
        "trade_date": latest_trade_date.isoformat(),
        "status": "ready" if len(historical_values) >= 5 and current_value is not None else "partial",
        "session_status": session_status,
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "comparison_minute": selected_minute.strftime("%H:%M"),
        "calculation_basis": "TWSE+TPEX cumulative trade value compared with prior sessions at or before the same minute",
        "current_cumulative_trade_value": current_value,
        "available_cumulative_trade_value": available_current_value,
        "trade_value_available": available_current_value is not None,
        "trade_value_complete": current_value is not None,
        "trade_value_status": (
            "complete"
            if current_value is not None
            else "partial"
            if available_current_value is not None
            else "missing"
        ),
        "included_markets": available_markets,
        "missing_markets": missing_markets,
        "trade_value_estimate": None,
        "trade_value_estimate_method": "not_estimated",
        "previous_minute_cumulative_trade_value": previous_value,
        "one_minute_trade_value_change": one_minute_change,
        "field_status": field_status,
        "same_time_baseline_5d": _baseline_payload(
            current_value,
            historical_values,
            5,
            dates=historical_dates,
        ),
        "same_time_baseline_20d": _baseline_payload(
            current_value,
            historical_values,
            20,
            dates=historical_dates,
        ),
        "history_trade_dates": historical_dates,
        "markets": market_payloads,
        "warnings": warnings,
        "source_refs": [{"type": "table", "name": "taiwan_market_minute_state"}],
        "limitations": [
            "Up/down-side trade-value split requires full-market per-stock realtime state and is not inferred here."
        ],
    }


__all__ = [
    "persist_taiwan_market_minute_state",
    "read_taiwan_market_volume_state",
]
