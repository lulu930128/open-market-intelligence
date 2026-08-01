from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from math import isfinite
from statistics import median, pstdev
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    StockMaster,
    TaiwanIntradayStockState,
    WatchlistGroup,
    WatchlistItem,
    utc_now,
)
from app.market.trading_calendar import TAIWAN_TZ


INTRADAY_STATE_VERSION = "tw.intraday_stock_state.v1"
INTRADAY_SCREENING_VERSION = "tw.screening.intraday.v2"
HOT_GROUPS_VERSION = "tw.market.hot_groups.v1"
GROUP_SNAPSHOT_VERSION = "tw.market.group_snapshot.v1"
SECTOR_SNAPSHOT_VERSION = "tw.market.sectors.v2"
SUPPORTED_MARKETS = ("TWSE", "TPEX")
SUPPORTED_INTRADAY_METRICS = (
    "change_pct",
    "estimated_trade_value",
    "cumulative_volume_lots",
    "distance_from_high_pct",
    "rebound_from_low_pct",
    "five_minute_return",
    "fifteen_minute_return",
    "intraday_range_pct",
    "vwap_deviation_pct",
    "order_book_imbalance",
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _int(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _aware_taipei(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _percent_change(value: float | None, base: float | None) -> float | None:
    if value is None or base in {None, 0}:
        return None
    return ((value - float(base)) / float(base)) * 100


def _distance_below_high_pct(
    current_price: float | None,
    high_price: float | None,
) -> float | None:
    if current_price is None or high_price in {None, 0}:
        return None
    return ((float(high_price) - current_price) / float(high_price)) * 100


def _load_samples(
    value: str | None,
    *,
    trade_date: date,
) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    samples = [
        sample
        for sample in loaded
        if isinstance(sample, dict)
        and str(sample.get("time") or "")[:10] == trade_date.isoformat()
        and _number(sample.get("price")) is not None
    ]
    return samples[-32:]


def _rolling_reference(
    samples: list[dict[str, Any]],
    *,
    current_time: datetime,
    minutes: int,
) -> tuple[datetime, float] | None:
    target = current_time - timedelta(minutes=minutes)
    candidates: list[tuple[datetime, float]] = []
    for sample in samples:
        sample_time = _aware_taipei(sample.get("time"))
        sample_price = _number(sample.get("price"))
        if (
            sample_time is not None
            and sample_price is not None
            and sample_time <= target
        ):
            candidates.append((sample_time, sample_price))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def _rolling_return(
    samples: list[dict[str, Any]],
    *,
    current_time: datetime,
    current_price: float | None,
    minutes: int,
) -> float | None:
    if current_price is None:
        return None
    reference = _rolling_reference(
        samples,
        current_time=current_time,
        minutes=minutes,
    )
    if reference is None:
        return None
    _, base = reference
    return _percent_change(current_price, base)


def _freshness_status(
    event_time: datetime,
    *,
    now: datetime,
) -> str:
    age_seconds = max(int((now - event_time).total_seconds()), 0)
    if age_seconds <= 90:
        return "current"
    if age_seconds <= 600:
        return "delayed"
    return "stale"


def persist_taiwan_intraday_stock_states(
    db: Session,
    *,
    rows: Iterable[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = _aware_taipei(now) or datetime.now(TAIWAN_TZ)
    inserted_count = 0
    updated_count = 0
    unchanged_count = 0
    skipped: list[str] = []
    existing_rows = db.query(TaiwanIntradayStockState).all()
    existing_by_identity = {
        (row.provider, row.market, row.stock_id): row for row in existing_rows
    }
    session_highs: dict[tuple[str, str, date], float] = {}
    session_lows: dict[tuple[str, str, date], float] = {}
    for row in existing_rows:
        session_key = (row.market, row.stock_id, row.trade_date)
        if row.high_price is not None:
            session_highs[session_key] = max(
                session_highs.get(session_key, row.high_price),
                row.high_price,
            )
        if row.low_price is not None:
            session_lows[session_key] = min(
                session_lows.get(session_key, row.low_price),
                row.low_price,
            )

    for raw in rows:
        market = str(raw.get("market") or "").strip().upper()
        stock_id = str(raw.get("code") or raw.get("stock_id") or "").strip()
        event_time = _aware_taipei(raw.get("as_of") or raw.get("event_time"))
        trade_date = raw.get("trade_date")
        if isinstance(trade_date, datetime):
            trade_date = trade_date.date()
        elif isinstance(trade_date, str):
            try:
                trade_date = date.fromisoformat(trade_date[:10])
            except ValueError:
                trade_date = None
        if (
            market not in SUPPORTED_MARKETS
            or not stock_id
            or event_time is None
            or not isinstance(trade_date, date)
        ):
            skipped.append(f"{market or 'unknown'}:{stock_id or 'unknown'}")
            continue

        provider = str(raw.get("provider") or "twse_mis")
        identity_key = (provider, market, stock_id)
        existing = existing_by_identity.get(identity_key)
        samples = _load_samples(
            existing.samples_json if existing is not None else None,
            trade_date=trade_date,
        )
        current_price = _number(raw.get("current_price"))
        minute_time = event_time.replace(second=0, microsecond=0)
        if current_price is not None:
            current_sample = {
                "time": minute_time.isoformat(),
                "price": current_price,
            }
            samples_by_time = {
                str(sample.get("time")): sample for sample in samples
            }
            samples_by_time[current_sample["time"]] = current_sample
            samples = sorted(
                samples_by_time.values(),
                key=lambda sample: str(sample.get("time") or ""),
            )[-32:]

        previous_close = _number(raw.get("previous_close"))
        open_price = _number(raw.get("open_price"))
        high_price = _number(raw.get("high_price"))
        low_price = _number(raw.get("low_price"))
        session_key = (market, stock_id, trade_date)
        session_high_candidates = [
            value
            for value in (
                session_highs.get(session_key),
                high_price,
                open_price,
                current_price,
            )
            if value is not None
        ]
        session_low_candidates = [
            value
            for value in (
                session_lows.get(session_key),
                low_price,
                open_price,
                current_price,
            )
            if value is not None
        ]
        high_price = max(session_high_candidates) if session_high_candidates else None
        low_price = min(session_low_candidates) if session_low_candidates else None
        if high_price is not None:
            session_highs[session_key] = high_price
        if low_price is not None:
            session_lows[session_key] = low_price
        cumulative_volume_lots = _int(raw.get("cumulative_volume_lots"))
        estimated_trade_value = _int(raw.get("estimated_trade_value"))
        if (
            existing is not None
            and _aware_taipei(existing.event_time) == event_time
            and existing.current_price == current_price
            and existing.cumulative_volume_lots == cumulative_volume_lots
            and existing.high_price == high_price
            and existing.low_price == low_price
        ):
            unchanged_count += 1
            continue
        typical_values = [
            value
            for value in (open_price, high_price, low_price, current_price)
            if value is not None
        ]
        vwap_estimate = (
            sum(typical_values) / len(typical_values)
            if typical_values
            else None
        )
        freshness_status = _freshness_status(
            event_time,
            now=checked_at,
        )
        quality_status = (
            "ready"
            if current_price is not None and previous_close is not None
            else "partial"
            if current_price is not None
            else "missing"
        )
        values = {
            "provider": provider,
            "market": market,
            "stock_id": stock_id,
            "trade_date": trade_date,
            "event_time": event_time,
            "current_price": current_price,
            "previous_close": previous_close,
            "open_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "cumulative_volume_lots": cumulative_volume_lots,
            "estimated_trade_value": estimated_trade_value,
            "change_pct": _percent_change(current_price, previous_close),
            "distance_from_high_pct": _distance_below_high_pct(
                current_price,
                high_price,
            ),
            "rebound_from_low_pct": _percent_change(
                current_price,
                low_price,
            ),
            "five_minute_return": _rolling_return(
                samples,
                current_time=event_time,
                current_price=current_price,
                minutes=5,
            ),
            "fifteen_minute_return": _rolling_return(
                samples,
                current_time=event_time,
                current_price=current_price,
                minutes=15,
            ),
            "intraday_range_pct": (
                ((high_price - low_price) / previous_close) * 100
                if high_price is not None
                and low_price is not None
                and previous_close not in {None, 0}
                else None
            ),
            "vwap_estimate": vwap_estimate,
            "vwap_deviation_pct": _percent_change(
                current_price,
                vwap_estimate,
            ),
            "order_book_imbalance": _number(
                raw.get("order_book_imbalance")
            ),
            "sample_count": len(samples),
            "samples_json": json.dumps(
                samples,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "freshness_status": freshness_status,
            "quality_status": quality_status,
            "trade_value_semantics": (
                "estimated_current_price_x_cumulative_volume_lots"
            ),
            "source": str(
                raw.get("source")
                or f"twse_mis_{market.lower()}_registered_universe"
            ),
            "source_url": raw.get("source_url"),
            "updated_at": utc_now(),
        }
        if existing is None:
            existing = TaiwanIntradayStockState(**values)
            db.add(existing)
            existing_by_identity[identity_key] = existing
            inserted_count += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            updated_count += 1

    if inserted_count or updated_count:
        db.commit()
    return {
        "kind": "taiwan_intraday_stock_state_persist",
        "version": INTRADAY_STATE_VERSION,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "skipped_count": len(skipped),
        "skipped": skipped[:20],
    }


def _normalized_markets(value: Any) -> tuple[str, ...]:
    if value is None:
        return SUPPORTED_MARKETS
    values = value if isinstance(value, list) else [value]
    markets = tuple(
        dict.fromkeys(
            str(item or "").strip().upper()
            for item in values
            if str(item or "").strip().upper() in SUPPORTED_MARKETS
        )
    )
    return markets or SUPPORTED_MARKETS


def build_tw_intraday_screening_snapshot(
    db: Session,
    *,
    parameters: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    raw = dict(parameters or {})
    metric = str(raw.get("metric") or "change_pct").strip()
    if metric not in SUPPORTED_INTRADAY_METRICS:
        raise ValueError(
            "intraday screening metric must be one of: "
            + ", ".join(SUPPORTED_INTRADAY_METRICS)
        )
    sort_order = str(raw.get("sort_order") or "desc").strip().lower()
    if sort_order not in {"asc", "desc"}:
        raise ValueError("intraday screening sort_order must be asc or desc.")
    limit = int(raw.get("limit", 20))
    offset = int(raw.get("offset", 0))
    if not 1 <= limit <= 200 or not 0 <= offset <= 5000:
        raise ValueError("intraday screening limit/offset is out of range.")
    universe = raw.get("universe") if isinstance(raw.get("universe"), dict) else {}
    markets = _normalized_markets(universe.get("markets"))
    requested_stock_ids = {
        str(item).strip()
        for item in universe.get("stock_ids") or []
        if str(item).strip()
    }

    query = (
        db.query(TaiwanIntradayStockState, StockMaster)
        .join(
            StockMaster,
            StockMaster.stock_id == TaiwanIntradayStockState.stock_id,
        )
        .filter(TaiwanIntradayStockState.market.in_(markets))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
    )
    if requested_stock_ids:
        query = query.filter(
            TaiwanIntradayStockState.stock_id.in_(requested_stock_ids)
        )
    queried_pairs = query.all()
    latest_pairs: dict[
        tuple[str, str], tuple[TaiwanIntradayStockState, StockMaster]
    ] = {}
    for state, stock in queried_pairs:
        key = (state.market, state.stock_id)
        previous = latest_pairs.get(key)
        if previous is None or (
            _aware_taipei(state.event_time) or datetime.min.replace(tzinfo=TAIWAN_TZ)
        ) > (
            _aware_taipei(previous[0].event_time)
            or datetime.min.replace(tzinfo=TAIWAN_TZ)
        ):
            latest_pairs[key] = (state, stock)
    pairs = list(latest_pairs.values())
    ranked: list[tuple[float, TaiwanIntradayStockState, StockMaster]] = []
    for state, stock in pairs:
        value = _number(getattr(state, metric, None))
        if value is not None:
            ranked.append((value, state, stock))
    ranked.sort(
        key=lambda item: (
            -item[0] if sort_order == "desc" else item[0],
            item[1].stock_id,
        )
    )
    selected = ranked[offset : offset + limit]
    rows = []
    for index, (value, state, stock) in enumerate(selected, start=1):
        event_time = _aware_taipei(state.event_time)
        samples = _load_samples(state.samples_json, trade_date=state.trade_date)
        five_minute_reference = (
            _rolling_reference(samples, current_time=event_time, minutes=5)
            if event_time is not None
            else None
        )
        fifteen_minute_reference = (
            _rolling_reference(samples, current_time=event_time, minutes=15)
            if event_time is not None
            else None
        )
        price_invariant_status = (
            "balanced"
            if state.current_price is not None
            and state.high_price is not None
            and state.low_price is not None
            and state.low_price <= state.current_price <= state.high_price
            and state.low_price <= state.high_price
            else "partial"
        )
        rows.append({
            "rank": offset + index,
            "stock_id": state.stock_id,
            "stock_name": stock.stock_name,
            "market": state.market,
            "industry": stock.industry or stock.category,
            "metric": metric,
            "value": value,
            "current_price": state.current_price,
            "previous_close": state.previous_close,
            "open_price": state.open_price,
            "high_price": state.high_price,
            "low_price": state.low_price,
            "change_pct": state.change_pct,
            "estimated_trade_value": state.estimated_trade_value,
            "estimated_trade_value_unit": "TWD",
            "estimated_trade_value_method": state.trade_value_semantics,
            "estimated_trade_value_is_estimate": True,
            "cumulative_volume_lots": state.cumulative_volume_lots,
            "cumulative_volume_unit": "lots",
            "distance_from_high_pct": state.distance_from_high_pct,
            "rebound_from_low_pct": state.rebound_from_low_pct,
            "five_minute_return": state.five_minute_return,
            "five_minute_return_status": (
                "calculated"
                if state.five_minute_return is not None
                else "insufficient_data"
            ),
            "five_minute_reference_time": (
                five_minute_reference[0].isoformat()
                if five_minute_reference is not None
                else None
            ),
            "five_minute_reference_price": (
                five_minute_reference[1]
                if five_minute_reference is not None
                else None
            ),
            "fifteen_minute_return": state.fifteen_minute_return,
            "fifteen_minute_return_status": (
                "calculated"
                if state.fifteen_minute_return is not None
                else "insufficient_data"
            ),
            "fifteen_minute_reference_time": (
                fifteen_minute_reference[0].isoformat()
                if fifteen_minute_reference is not None
                else None
            ),
            "fifteen_minute_reference_price": (
                fifteen_minute_reference[1]
                if fifteen_minute_reference is not None
                else None
            ),
            "intraday_range_pct": state.intraday_range_pct,
            "intraday_range_basis": "previous_close",
            "vwap_deviation_pct": state.vwap_deviation_pct,
            "order_book_imbalance": state.order_book_imbalance,
            "event_time": state.event_time,
            "price_snapshot_id": (
                f"{state.market}:{state.stock_id}:{event_time.isoformat()}"
                if event_time is not None
                else None
            ),
            "price_snapshot_source": state.source,
            "price_invariant_status": price_invariant_status,
            "freshness_status": state.freshness_status,
            "quality_status": state.quality_status,
        })
    generated = _aware_taipei(generated_at) or datetime.now(TAIWAN_TZ)
    latest_event = max(
        (_aware_taipei(state.event_time) for _, state, _ in ranked),
        default=None,
    )
    universe_count = (
        db.query(StockMaster)
        .filter(func.upper(StockMaster.market).in_(markets))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .count()
    )
    coverage_count = len(latest_pairs)
    coverage_ratio = (
        coverage_count / universe_count if universe_count else 0.0
    )
    status = (
        "ready"
        if coverage_ratio >= 0.95 and rows
        else "partial"
        if rows
        else "missing"
    )
    return {
        "kind": "tw_intraday_screening",
        "version": INTRADAY_SCREENING_VERSION,
        "status": status,
        "metric": metric,
        "unit": (
            "TWD"
            if metric == "estimated_trade_value"
            else "lots"
            if metric == "cumulative_volume_lots"
            else "ratio"
            if metric == "order_book_imbalance"
            else "percent"
        ),
        "frequency": "rolling_minute_state",
        "sort_order": sort_order,
        "rows": rows,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned_count": len(rows),
            "total_eligible_count": len(ranked),
        },
        "coverage": {
            "markets": list(markets),
            "universe_count": universe_count,
            "coverage_count": coverage_count,
            "coverage_ratio": coverage_ratio,
            "status": status,
        },
        "observed_trade_date": (
            latest_event.date().isoformat() if latest_event else None
        ),
        "event_time": latest_event,
        "computed_at": generated,
        "data_mode": "intraday_rolling_state",
        "is_intraday": True,
        "cache_policy": "scheduler_owned_read_only",
        "warnings": (
            []
            if status == "ready"
            else [
                "Intraday screening coverage is incomplete; results rank "
                "only the scheduler-owned cached universe."
            ]
        ),
        "missing": [] if rows else ["taiwan_intraday_stock_state"],
        "source_refs": [
            {"type": "table", "name": "taiwan_intraday_stock_state"}
        ],
    }


def _group_metrics(
    *,
    group_id: str,
    group_name: str,
    group_type: str,
    membership_source: str,
    states: list[TaiwanIntradayStockState],
) -> dict[str, Any] | None:
    returns = [
        float(state.change_pct)
        for state in states
        if state.change_pct is not None
    ]
    if not returns:
        return None
    trade_values = [
        int(state.estimated_trade_value or 0) for state in states
    ]
    total_trade_value = sum(trade_values)
    leader_trade_value = max(trade_values, default=0)
    five_minute = [
        float(state.five_minute_return)
        for state in states
        if state.five_minute_return is not None
    ]
    fifteen_minute = [
        float(state.fifteen_minute_return)
        for state in states
        if state.fifteen_minute_return is not None
    ]
    return {
        "group_id": group_id,
        "group_name": group_name,
        "group_type": group_type,
        "membership_source": membership_source,
        "member_count": len(states),
        "observed_count": len(returns),
        "advance_count": sum(value > 0 for value in returns),
        "decline_count": sum(value < 0 for value in returns),
        "unchanged_count": sum(value == 0 for value in returns),
        "advance_ratio": sum(value > 0 for value in returns) / len(returns),
        "mean_return_pct": sum(returns) / len(returns),
        "median_return_pct": median(returns),
        "return_dispersion_pct": (
            pstdev(returns) if len(returns) > 1 else 0.0
        ),
        "estimated_trade_value": total_trade_value,
        "trade_value_method": (
            next(iter(trade_value_methods))
            if len(trade_value_methods := {
                str(state.trade_value_semantics)
                for state in states
                if state.trade_value_semantics
            }) == 1
            else "mixed_member_estimates"
            if trade_value_methods
            else "not_available"
        ),
        "trade_value_unit": "TWD",
        "trade_value_is_estimate": True,
        "member_price_semantics_summary": {
            "current_price": "provider_current_price",
            "previous_close": "provider_previous_close",
            "trade_value_methods": sorted(trade_value_methods),
        },
        "leader_concentration": (
            leader_trade_value / total_trade_value
            if total_trade_value > 0
            else None
        ),
        "median_five_minute_return": (
            median(five_minute) if five_minute else None
        ),
        "median_fifteen_minute_return": (
            median(fifteen_minute) if fifteen_minute else None
        ),
    }


def build_tw_hot_groups_snapshot(
    db: Session,
    *,
    limit: int = 20,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    return build_tw_intraday_group_snapshots(
        db,
        hot_group_limit=limit,
        generated_at=generated_at,
        include_watchlist_groups=True,
    )["hot_groups"]


def build_tw_intraday_group_snapshots(
    db: Session,
    *,
    hot_group_limit: int = 20,
    sector_limit: int = 100,
    generated_at: datetime | None = None,
    include_watchlist_groups: bool = True,
) -> dict[str, dict[str, Any]]:
    hot_group_limit = max(1, min(int(hot_group_limit), 100))
    sector_limit = max(1, min(int(sector_limit), 100))
    generated = _aware_taipei(generated_at) or datetime.now(TAIWAN_TZ)
    universe_rows = (
        db.query(StockMaster, TaiwanIntradayStockState)
        .outerjoin(
            TaiwanIntradayStockState,
            StockMaster.stock_id == TaiwanIntradayStockState.stock_id,
        )
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .all()
    )
    stocks_by_id = {
        str(stock.stock_id): stock for stock, _state in universe_rows
    }
    latest_state_by_stock: dict[str, TaiwanIntradayStockState] = {}
    for stock, state in universe_rows:
        if state is None:
            continue
        stock_id = str(stock.stock_id)
        existing = latest_state_by_stock.get(stock_id)
        if existing is None or (
            _aware_taipei(state.event_time)
            or datetime.min.replace(tzinfo=TAIWAN_TZ)
        ) > (
            _aware_taipei(existing.event_time)
            or datetime.min.replace(tzinfo=TAIWAN_TZ)
        ):
            latest_state_by_stock[stock_id] = state
    latest_trade_date = max(
        (
            state.trade_date
            for state in latest_state_by_stock.values()
            if isinstance(state.trade_date, date)
        ),
        default=None,
    )
    states_by_stock = {
        stock_id: state
        for stock_id, state in latest_state_by_stock.items()
        if latest_trade_date is None or state.trade_date == latest_trade_date
    }
    industry_groups: dict[str, list[TaiwanIntradayStockState]] = defaultdict(
        list
    )
    for stock_id, state in states_by_stock.items():
        stock = stocks_by_id.get(stock_id)
        if stock is None:
            continue
        industry = str(stock.industry or stock.category or "").strip()
        if industry:
            industry_groups[industry].append(state)

    exchange_groups: list[dict[str, Any]] = []
    for industry, states in industry_groups.items():
        metrics = _group_metrics(
            group_id=f"industry:{industry}",
            group_name=industry,
            group_type="exchange_industry",
            membership_source="stock_master.industry",
            states=states,
        )
        if metrics is not None:
            exchange_groups.append(metrics)

    watchlist_rows = []
    if include_watchlist_groups:
        watchlist_rows = (
            db.query(
                WatchlistGroup.id,
                WatchlistGroup.group_name,
                WatchlistItem.stock_id,
            )
            .join(
                WatchlistItem,
                WatchlistItem.group_id == WatchlistGroup.id,
            )
            .filter(WatchlistGroup.is_active.is_(True))
            .filter(WatchlistItem.enabled.is_(True))
            .all()
        )
    watchlist_members: dict[
        tuple[int, str],
        list[TaiwanIntradayStockState],
    ] = defaultdict(list)
    for group_id, group_name, stock_id in watchlist_rows:
        state = states_by_stock.get(str(stock_id))
        if state is not None:
            watchlist_members[(int(group_id), str(group_name))].append(state)
    watchlist_groups: list[dict[str, Any]] = []
    for (group_id, group_name), states in watchlist_members.items():
        metrics = _group_metrics(
            group_id=f"watchlist:{group_id}",
            group_name=group_name,
            group_type="user_curated_watchlist",
            membership_source="watchlist_group+watchlist_item",
            states=states,
        )
        if metrics is not None:
            watchlist_groups.append(metrics)

    groups = [*exchange_groups, *watchlist_groups]
    groups.sort(
        key=lambda item: (
            -float(item.get("median_return_pct") or 0),
            -float(item.get("advance_ratio") or 0),
            -int(item.get("estimated_trade_value") or 0),
            str(item.get("group_name") or ""),
        )
    )
    exchange_groups.sort(
        key=lambda item: (
            -float(item.get("median_return_pct") or 0),
            -float(item.get("advance_ratio") or 0),
            -int(item.get("estimated_trade_value") or 0),
            str(item.get("group_name") or ""),
        )
    )
    latest_event = max(
        (_aware_taipei(state.event_time) for state in states_by_stock.values()),
        default=None,
    )
    universe_count = len(stocks_by_id)
    coverage_count = len(states_by_stock)
    coverage_ratio = (
        coverage_count / universe_count if universe_count else 0.0
    )
    current_count = sum(
        str(state.freshness_status or "").lower() == "current"
        for state in states_by_stock.values()
    )
    current_ratio = (
        current_count / coverage_count if coverage_count else 0.0
    )
    snapshot_status = (
        "ready"
        if exchange_groups
        and coverage_ratio >= 0.95
        and current_ratio >= 0.95
        else "partial"
        if exchange_groups
        else "missing"
    )
    observed_trade_date = (
        latest_trade_date.isoformat() if latest_trade_date else None
    )
    snapshot_id = (
        "tw_intraday_groups:"
        f"{observed_trade_date or 'unknown'}:"
        f"{latest_event.isoformat() if latest_event else 'missing'}:"
        f"{coverage_count}"
    )
    coverage = {
        "scope": "active_stock_master_registered_universe",
        "markets": list(SUPPORTED_MARKETS),
        "universe_count": universe_count,
        "coverage_count": coverage_count,
        "unknown_count": max(universe_count - coverage_count, 0),
        "coverage_ratio": coverage_ratio,
        "current_count": current_count,
        "current_ratio": current_ratio,
        "coverage_status": (
            "complete_registered_universe"
            if coverage_ratio >= 0.95
            else "partial_registered_universe"
        ),
        "is_official_full_market": False,
    }
    shared_warnings = (
        []
        if snapshot_status == "ready"
        else [
            "Intraday group coverage or freshness is incomplete; metrics use "
            "only the scheduler-owned current-trade-date state."
        ]
        if exchange_groups
        else ["No scheduler-owned intraday group state is available yet."]
    )
    source_refs = [
        {"type": "table", "name": "taiwan_intraday_stock_state"},
        {"type": "table", "name": "stock_master"},
    ]
    hot_groups = {
        "kind": "tw_hot_groups",
        "version": HOT_GROUPS_VERSION,
        "snapshot_version": GROUP_SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "status": snapshot_status,
        "groups": groups[:hot_group_limit],
        "group_count": len(groups),
        "exchange_industry_group_count": len(exchange_groups),
        "watchlist_group_count": len(watchlist_groups),
        "coverage": coverage,
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "trade_value_is_estimate": True,
        "membership_provenance": {
            "allowed_sources": [
                "stock_master.industry",
                "watchlist_group+watchlist_item",
            ],
            "inferred_by_llm": False,
        },
        "observed_trade_date": observed_trade_date,
        "event_time": latest_event,
        "computed_at": generated,
        "data_mode": "intraday_rolling_state",
        "is_intraday": True,
        "warnings": shared_warnings,
        "missing": (
            [] if exchange_groups else ["taiwan_intraday_stock_state"]
        ),
        "source_refs": [
            *source_refs,
            *(
                [
                    {"type": "table", "name": "watchlist_group"},
                    {"type": "table", "name": "watchlist_item"},
                ]
                if include_watchlist_groups
                else []
            ),
        ],
    }
    sector_items = [
        {
            "sector_id": group["group_id"],
            "name": group["group_name"],
            "trade_date": observed_trade_date,
            "change_pct": group["mean_return_pct"],
            **{
                key: group.get(key)
                for key in (
                    "member_count",
                    "observed_count",
                    "advance_count",
                    "decline_count",
                    "unchanged_count",
                    "advance_ratio",
                    "mean_return_pct",
                    "median_return_pct",
                    "return_dispersion_pct",
                    "estimated_trade_value",
                    "trade_value_method",
                    "trade_value_unit",
                    "trade_value_is_estimate",
                    "member_price_semantics_summary",
                    "leader_concentration",
                    "median_five_minute_return",
                    "median_fifteen_minute_return",
                )
            },
            "universe_count": group["member_count"],
            "coverage_count": group["observed_count"],
            "coverage_ratio": (
                group["observed_count"] / group["member_count"]
                if group["member_count"]
                else None
            ),
            "ranking_basis": (
                "taiwan_intraday_stock_state_by_exchange_industry"
            ),
        }
        for group in exchange_groups[:sector_limit]
    ]
    sectors = {
        "kind": "tw_market_sectors",
        "version": SECTOR_SNAPSHOT_VERSION,
        "snapshot_version": GROUP_SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "status": snapshot_status,
        "as_of": latest_event,
        "observed_trade_date": observed_trade_date,
        "computed_at": generated,
        "data_mode": "intraday_rolling_state",
        "is_intraday": True,
        "ranking_basis": (
            "taiwan_intraday_stock_state_by_exchange_industry"
        ),
        "aggregation_method": "equal_weighted_stock_return_with_median",
        "currency": "TWD",
        "trade_value_unit": "TWD",
        "trade_value_is_estimate": True,
        "is_full_market": False,
        "coverage": coverage,
        "count": len(sector_items),
        "items": sector_items,
        "missing": (
            [] if sector_items else ["taiwan_intraday_stock_state"]
        ),
        "coverage_gaps": (
            ["taiwan_intraday_stock_state.incomplete_registered_universe"]
            if coverage_ratio < 0.95
            else []
        ),
        "warnings": shared_warnings,
        "source_refs": source_refs,
    }
    return {"hot_groups": hot_groups, "sectors": sectors}


__all__ = [
    "HOT_GROUPS_VERSION",
    "GROUP_SNAPSHOT_VERSION",
    "INTRADAY_SCREENING_VERSION",
    "INTRADAY_STATE_VERSION",
    "SUPPORTED_INTRADAY_METRICS",
    "SECTOR_SNAPSHOT_VERSION",
    "build_tw_hot_groups_snapshot",
    "build_tw_intraday_group_snapshots",
    "build_tw_intraday_screening_snapshot",
    "persist_taiwan_intraday_stock_states",
]
