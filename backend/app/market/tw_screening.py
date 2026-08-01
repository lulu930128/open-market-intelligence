from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import InstitutionalTradeDaily, MarginTradingDaily, StockMaster
from app.market.tw_universe import (
    TAIWAN_STOCK_MARKETS,
    list_taiwan_stock_universe,
    normalize_taiwan_markets,
)


SCREENING_SNAPSHOT_VERSION = "omi.tw.screening.snapshot.v1"
SUPPORTED_WINDOWS = (1, 5, 10, 20)
MAX_RESULT_LIMIT = 200
MAX_RESULT_OFFSET = 5_000


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    dataset: str
    unit: str
    frequency: str
    model: type[InstitutionalTradeDaily] | type[MarginTradingDaily]
    value_field: str | None = None


METRICS: dict[str, MetricSpec] = {
    "foreign_investor_net_shares": MetricSpec(
        metric_id="foreign_investor_net_shares",
        dataset="institutional_trade_daily",
        unit="shares",
        frequency="daily",
        model=InstitutionalTradeDaily,
        value_field="foreign_investor_net",
    ),
    "investment_trust_net_shares": MetricSpec(
        metric_id="investment_trust_net_shares",
        dataset="institutional_trade_daily",
        unit="shares",
        frequency="daily",
        model=InstitutionalTradeDaily,
        value_field="investment_trust_net",
    ),
    "margin_balance_change_pct": MetricSpec(
        metric_id="margin_balance_change_pct",
        dataset="margin_trading_daily",
        unit="percent",
        frequency="daily",
        model=MarginTradingDaily,
    ),
}


def _string_ids(value: Any, *, max_items: int = 2_500) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("screening universe stock ids must be arrays.")
    if len(value) > max_items:
        raise ValueError(
            f"screening universe stock ids must contain at most {max_items} items."
        )
    return tuple(
        dict.fromkeys(
            str(item or "").strip()
            for item in value
            if str(item or "").strip()
        )
    )


def normalize_screening_parameters(
    parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = dict(parameters or {})
    metric = str(raw.get("metric") or "foreign_investor_net_shares").strip()
    if metric not in METRICS:
        raise ValueError(
            "screening metric must be one of: " + ", ".join(sorted(METRICS))
        )
    window = raw.get("window", 1)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError("screening window must be an integer.")
    if window not in SUPPORTED_WINDOWS:
        raise ValueError(
            "screening window must be one of: "
            + ", ".join(str(item) for item in SUPPORTED_WINDOWS)
        )
    sort_order = str(raw.get("sort_order") or "desc").strip().lower()
    if sort_order not in {"asc", "desc"}:
        raise ValueError("screening sort_order must be asc or desc.")
    limit = raw.get("limit", 20)
    offset = raw.get("offset", 0)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("screening limit must be an integer.")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("screening offset must be an integer.")
    if not 1 <= limit <= MAX_RESULT_LIMIT:
        raise ValueError(
            f"screening limit must be between 1 and {MAX_RESULT_LIMIT}."
        )
    if not 0 <= offset <= MAX_RESULT_OFFSET:
        raise ValueError(
            f"screening offset must be between 0 and {MAX_RESULT_OFFSET}."
        )
    require_complete_window = raw.get("require_complete_window", True)
    if not isinstance(require_complete_window, bool):
        raise ValueError(
            "screening require_complete_window must be a boolean."
        )
    min_observed_periods = raw.get(
        "min_observed_periods",
        window if require_complete_window else 1,
    )
    if (
        isinstance(min_observed_periods, bool)
        or not isinstance(min_observed_periods, int)
        or not 1 <= min_observed_periods <= window
    ):
        raise ValueError(
            "screening min_observed_periods must be an integer between 1 "
            "and the requested window."
        )
    incomplete_window_policy = str(
        raw.get("incomplete_window_policy")
        or ("exclude" if require_complete_window else "include_and_flag")
    ).strip().lower()
    if incomplete_window_policy not in {
        "exclude",
        "include_and_flag",
        "separate_section",
    }:
        raise ValueError(
            "screening incomplete_window_policy must be exclude, "
            "include_and_flag, or separate_section."
        )

    universe = raw.get("universe")
    if universe is None:
        universe = {}
    if not isinstance(universe, dict):
        raise ValueError("screening universe must be an object.")
    markets = normalize_taiwan_markets(universe.get("markets"))
    stock_ids = _string_ids(universe.get("stock_ids"))
    exclude_stock_ids = _string_ids(universe.get("exclude_stock_ids"))
    overlap = sorted(set(stock_ids) & set(exclude_stock_ids))
    if overlap:
        raise ValueError(
            "screening universe cannot include and exclude the same stock id: "
            + ", ".join(overlap[:10])
        )
    return {
        "metric": metric,
        "window": window,
        "sort_order": sort_order,
        "limit": limit,
        "offset": offset,
        "require_complete_window": require_complete_window,
        "min_observed_periods": min_observed_periods,
        "incomplete_window_policy": incomplete_window_policy,
        "universe": {
            "markets": list(markets),
            "stock_ids": list(stock_ids),
            "exclude_stock_ids": list(exclude_stock_ids),
            "instrument_types": ["stock"],
        },
    }


def _latest_rows_by_stock_and_date(
    db: Session,
    *,
    metric: MetricSpec,
    stock_ids: list[str],
    window: int,
) -> tuple[list[date], dict[str, list[Any]]]:
    if not stock_ids:
        return [], {}
    model = metric.model
    trade_dates = [
        row[0]
        for row in (
            db.query(model.trade_date)
            .filter(model.stock_id.in_(stock_ids))
            .distinct()
            .order_by(model.trade_date.desc())
            .limit(window)
            .all()
        )
    ]
    if not trade_dates:
        return [], {}

    latest_by_key: dict[tuple[str, date], Any] = {}
    for chunk_start in range(0, len(stock_ids), 500):
        chunk = stock_ids[chunk_start : chunk_start + 500]
        rows = (
            db.query(model)
            .filter(model.stock_id.in_(chunk))
            .filter(model.trade_date.in_(trade_dates))
            .order_by(
                model.stock_id.asc(),
                model.trade_date.asc(),
                model.id.asc(),
            )
            .all()
        )
        for row in rows:
            latest_by_key[(row.stock_id, row.trade_date)] = row

    by_stock: dict[str, list[Any]] = defaultdict(list)
    for (stock_id, _trade_date), row in latest_by_key.items():
        by_stock[stock_id].append(row)
    for rows in by_stock.values():
        rows.sort(key=lambda row: (row.trade_date, row.id))
    return sorted(trade_dates), dict(by_stock)


def _metric_value(metric: MetricSpec, rows: list[Any]) -> float | int | None:
    if not rows:
        return None
    if metric.model is InstitutionalTradeDaily:
        values = [
            getattr(row, str(metric.value_field), None)
            for row in rows
        ]
        available = [int(value) for value in values if value is not None]
        return sum(available) if available else None

    earliest = rows[0]
    latest = rows[-1]
    previous = getattr(earliest, "margin_previous_balance", None)
    current = getattr(latest, "margin_today_balance", None)
    if previous is None or current is None or previous <= 0:
        return None
    return round(((float(current) - float(previous)) / float(previous)) * 100, 4)


def _snapshot_id(
    *,
    query: dict[str, Any],
    dates: list[date],
    ranked_values: list[tuple[str, float | int]],
    universe_ids: list[str],
) -> str:
    payload = {
        "version": SCREENING_SNAPSHOT_VERSION,
        "query": query,
        "dates": [item.isoformat() for item in dates],
        "ranked_values": ranked_values,
        "universe_ids": universe_ids,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"tw-screening-{digest[:24]}"


def _coverage_status(
    *,
    requested_window: int,
    available_dates: int,
    universe_count: int,
    covered_count: int,
    complete_window_count: int,
) -> str:
    if not universe_count or not covered_count:
        return "missing"
    if (
        available_dates < requested_window
        or covered_count < universe_count
        or complete_window_count < universe_count
    ):
        return "partial"
    return "latest_completed_session"


def build_tw_screening_snapshot(
    db: Session,
    *,
    parameters: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, cache-only Taiwan stock screening snapshot."""

    normalized = normalize_screening_parameters(parameters)
    universe_params = normalized["universe"]
    universe = list_taiwan_stock_universe(
        db,
        markets=universe_params["markets"],
        stock_ids=universe_params["stock_ids"],
        exclude_stock_ids=universe_params["exclude_stock_ids"],
    )
    universe_by_id: dict[str, StockMaster] = {
        stock.stock_id: stock for stock in universe
    }
    universe_ids = list(universe_by_id)
    metric = METRICS[normalized["metric"]]
    trade_dates, rows_by_stock = _latest_rows_by_stock_and_date(
        db,
        metric=metric,
        stock_ids=universe_ids,
        window=normalized["window"],
    )

    values: list[tuple[str, float | int]] = []
    observed_periods: dict[str, int] = {}
    for stock_id in universe_ids:
        rows = rows_by_stock.get(stock_id, [])
        value = _metric_value(metric, rows)
        if value is None:
            continue
        values.append((stock_id, value))
        observed_periods[stock_id] = len(rows)
    if normalized["sort_order"] == "desc":
        values.sort(key=lambda item: (-item[1], item[0]))
    else:
        values.sort(key=lambda item: (item[1], item[0]))
    eligible_values = [
        item
        for item in values
        if observed_periods.get(item[0], 0)
        >= normalized["min_observed_periods"]
        and (
            not normalized["require_complete_window"]
            or observed_periods.get(item[0], 0) >= normalized["window"]
        )
    ]
    incomplete_values = [
        item
        for item in values
        if observed_periods.get(item[0], 0) < normalized["window"]
    ]

    snapshot_id = _snapshot_id(
        query=normalized,
        dates=trade_dates,
        ranked_values=eligible_values,
        universe_ids=universe_ids,
    )
    offset = normalized["offset"]
    limit = normalized["limit"]
    selected_values = eligible_values[offset : offset + limit]
    rows: list[dict[str, Any]] = []
    previous_value: float | int | None = None
    previous_rank = 0
    for position, (stock_id, value) in enumerate(
        eligible_values,
        start=1,
    ):
        rank = previous_rank if previous_value == value else position
        previous_value = value
        previous_rank = rank
        if position <= offset or position > offset + limit:
            continue
        stock = universe_by_id[stock_id]
        rows.append(
            {
                "rank": rank,
                "position": position,
                "stock_id": stock.stock_id,
                "stock_name": stock.stock_name,
                "market": str(stock.market or "").upper(),
                "industry": stock.industry or stock.category,
                "instrument_type": "stock",
                "metric": metric.metric_id,
                "value": value,
                "unit": metric.unit,
                "observed_periods": observed_periods.get(stock_id, 0),
                "requested_periods": normalized["window"],
                "window_complete": (
                    observed_periods.get(stock_id, 0) >= normalized["window"]
                ),
            }
        )

    covered_count = len(values)
    universe_count = len(universe_ids)
    available_dates = len(trade_dates)
    complete_window_count = sum(
        1
        for stock_id in universe_ids
        if observed_periods.get(stock_id, 0) >= normalized["window"]
    )
    status = _coverage_status(
        requested_window=normalized["window"],
        available_dates=available_dates,
        universe_count=universe_count,
        covered_count=covered_count,
        complete_window_count=complete_window_count,
    )
    latest_date = trade_dates[-1].isoformat() if trade_dates else None
    earliest_date = trade_dates[0].isoformat() if trade_dates else None
    is_full_market_request = (
        set(universe_params["markets"]) == set(TAIWAN_STOCK_MARKETS)
        and not universe_params["stock_ids"]
        and not universe_params["exclude_stock_ids"]
    )
    warnings: list[str] = []
    missing: list[str] = []
    if not universe_count:
        missing.append("stock_master.tw_ordinary_stock_universe")
        warnings.append(
            "The requested Taiwan ordinary-stock universe is empty in the local cache."
        )
    if universe_count and not covered_count:
        missing.append(metric.dataset)
        warnings.append(
            f"No cached {metric.dataset} rows cover the requested universe."
        )
    coverage_gaps: list[dict[str, Any]] = []
    if available_dates < normalized["window"]:
        coverage_gaps.append(
            {
                "dataset": metric.dataset,
                "kind": "trading_window",
                "available_periods": available_dates,
                "requested_periods": normalized["window"],
            }
        )
        warnings.append(
            f"Only {available_dates}/{normalized['window']} cached trade dates are "
            "available for the requested screening window."
        )
    if covered_count < universe_count and covered_count:
        coverage_gaps.append(
            {
                "dataset": metric.dataset,
                "kind": "universe_coverage",
                "covered": covered_count,
                "expected": universe_count,
                "missing_count": universe_count - covered_count,
            }
        )
        warnings.append(
            f"Screening metric coverage is {covered_count}/{universe_count} "
            "stocks in the requested ordinary-stock universe."
        )
    if complete_window_count < covered_count:
        coverage_gaps.append(
            {
                "dataset": metric.dataset,
                "kind": "incomplete_windows",
                "complete_window_count": complete_window_count,
                "incomplete_window_count": (
                    covered_count - complete_window_count
                ),
                "eligible_rank_count": len(eligible_values),
            }
        )
        warnings.append(
            f"{covered_count - complete_window_count} covered stocks have fewer "
            "cached observations than the requested window."
        )

    generated = generated_at or datetime.now(timezone.utc)
    coverage = {
        "kind": "tw_screening_coverage",
        "version": SCREENING_SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "status": status,
        "metric": metric.metric_id,
        "dataset": metric.dataset,
        "unit": metric.unit,
        "frequency": metric.frequency,
        "requested_window_trade_days": normalized["window"],
        "available_window_trade_days": available_dates,
        "window_start": earliest_date,
        "window_end": latest_date,
        "universe_count": universe_count,
        "eligible_count": universe_count,
        "covered_count": covered_count,
        "complete_window_count": complete_window_count,
        "partial_window_count": max(
            covered_count - complete_window_count,
            0,
        ),
        "incomplete_window_count": max(
            covered_count - complete_window_count,
            0,
        ),
        "eligible_rank_count": len(eligible_values),
        "excluded_incomplete_count": max(
            covered_count - len(eligible_values),
            0,
        ),
        "missing_count": max(universe_count - covered_count, 0),
        "coverage_ratio": (
            round(covered_count / universe_count, 6)
            if universe_count
            else None
        ),
        "is_full_market_request": is_full_market_request,
        "is_full_requested_universe": (
            bool(universe_count)
            and complete_window_count == universe_count
        ),
        "markets": list(universe_params["markets"]),
        "instrument_types": ["stock"],
        "dedupe_policy": "latest_row_id_per_stock_trade_date",
        "cache_policy": "read_only_no_refresh",
        "as_of": latest_date,
        "missing": missing,
        "coverage_gaps": coverage_gaps,
        "warnings": warnings,
    }
    ranking = {
        "kind": "tw_screening_ranking",
        "version": SCREENING_SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "status": status,
        "metric": metric.metric_id,
        "unit": metric.unit,
        "frequency": metric.frequency,
        "sort_order": normalized["sort_order"],
        "tie_policy": "competition_rank_then_stock_id",
        "require_complete_window": normalized[
            "require_complete_window"
        ],
        "min_observed_periods": normalized["min_observed_periods"],
        "incomplete_window_policy": normalized[
            "incomplete_window_policy"
        ],
        "window": {
            "requested_trade_days": normalized["window"],
            "available_trade_days": available_dates,
            "start": earliest_date,
            "end": latest_date,
        },
        "universe": {
            **universe_params,
            "count": universe_count,
            "is_full_market_request": is_full_market_request,
        },
        "pagination": {
            "snapshot_id": snapshot_id,
            "offset": offset,
            "limit": limit,
            "returned_count": len(selected_values),
            "total_ranked_count": len(eligible_values),
            "covered_count": covered_count,
            "has_more": (
                offset + len(selected_values) < len(eligible_values)
            ),
        },
        "rows": rows,
        "incomplete_rows": (
            [
                {
                    "stock_id": stock_id,
                    "value": value,
                    "unit": metric.unit,
                    "observed_periods": observed_periods.get(stock_id, 0),
                    "requested_periods": normalized["window"],
                    "window_complete": False,
                }
                for stock_id, value in incomplete_values[:limit]
            ]
            if normalized["incomplete_window_policy"]
            == "separate_section"
            else []
        ),
        "as_of": latest_date,
        "generated_at": generated.isoformat(),
        "cache_policy": "read_only_no_refresh",
        "missing": missing,
        "coverage_gaps": coverage_gaps,
        "warnings": warnings,
    }
    freshness = {
        "status": status,
        "dataset": metric.dataset,
        "latest": latest_date,
        "as_of": latest_date,
        "event_time_basis": "taiwan_completed_trade_date",
        "frequency": metric.frequency,
        "cache_policy": "read_only_no_refresh",
        "is_current": status == "latest_completed_session",
        "missing": missing,
        "coverage_gaps": coverage_gaps,
        "warnings": warnings,
    }
    return {
        "kind": "tw_screening_snapshot",
        "version": SCREENING_SNAPSHOT_VERSION,
        "generated_at": generated,
        "as_of": latest_date,
        "snapshot_id": snapshot_id,
        "query": normalized,
        "ranking": ranking,
        "coverage": coverage,
        "freshness_by_capability": {
            "screening.ranking": dict(freshness),
            "screening.coverage": dict(freshness),
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "stock_master"},
            {"type": "table", "name": metric.dataset},
        ],
    }
