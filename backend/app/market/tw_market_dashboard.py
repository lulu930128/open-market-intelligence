from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from hashlib import sha256
from math import isfinite
from statistics import median, pstdev
from typing import Any, Iterable

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from app.db.models import (
    MarketIndexDailyStat,
    StockMaster,
    StockProfile,
    TaiwanIntradayStockState,
    WatchlistGroup,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    previous_taiwan_trading_day,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.service import list_stock_ohlc_chart_data
from app.market.technical_report import build_stock_technical_report
from app.market.taiwan_industries import normalize_tw_industry_label
from app.market.tw_intraday_state import INTRADAY_STATE_VERSION
from app.watchlists.service import list_groups, list_items


TW_MARKET_DASHBOARD_VERSION = "omi.tw_market_dashboard.v1"
TW_SYMBOL_SEARCH_VERSION = "omi.tw_symbol_search.v1"
TW_STOCK_DASHBOARD_DETAIL_VERSION = "omi.tw_stock_dashboard_detail.v1"
SUPPORTED_MARKETS = ("TWSE", "TPEX")
INDEX_ID_BY_MARKET = {"TWSE": "TAIEX", "TPEX": "TPEX"}
INDEX_ESTIMATE_METHOD_VERSION = "omi.tw_preopen_index_estimate.proxy.v1"
DEFAULT_WATCHLIST_LIMIT = 40
DEFAULT_GROUP_LIMIT = 8
MIN_INDEX_COMPONENT_DATA_COVERAGE = 0.8


class TaiwanDashboardWatchlistGroupNotFoundError(ValueError):
    pass


class TaiwanDashboardStockNotFoundError(ValueError):
    pass


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _aware_taipei(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _state_as_of(state: TaiwanIntradayStockState) -> datetime:
    return (
        _aware_taipei(state.snapshot_as_of)
        or _aware_taipei(state.event_time)
        or datetime.min.replace(tzinfo=TAIWAN_TZ)
    )


def _freshness_status(
    newest_as_of: datetime | None,
    *,
    now: datetime,
) -> tuple[str, int | None]:
    if newest_as_of is None:
        return "missing", None
    age_seconds = max(int((now - newest_as_of).total_seconds()), 0)
    if age_seconds <= 90:
        return "current", age_seconds
    if age_seconds <= 600:
        return "delayed", age_seconds
    return "stale", age_seconds


def _observation(
    state: TaiwanIntradayStockState | None,
    *,
    session_phase: str,
) -> dict[str, Any]:
    if state is None:
        return {
            "status": "unknown",
            "reason": "state_missing",
            "price": None,
            "previous_close": None,
            "change_pct": None,
            "price_semantics": "unavailable",
            "as_of": None,
        }

    previous_close = _number(state.previous_close)
    as_of = _state_as_of(state)
    if session_phase == "preopen":
        price = (
            _number(state.indicative_match_price)
            if state.indicative_match_available
            else None
        )
        semantics = "auction_indicative"
        missing_reason = (
            "indicative_match_missing"
            if price is None
            else "previous_close_missing"
        )
    elif session_phase == "preopen_pending":
        price = None
        semantics = "not_observed"
        missing_reason = "preopen_collection_not_started"
    else:
        price = (
            _number(state.current_price)
            if state.has_actual_trade and state.decision_usable
            else None
        )
        semantics = "actual_trade" if price is not None else "unavailable"
        missing_reason = (
            "actual_trade_missing" if price is None else "previous_close_missing"
        )

    if price is None or previous_close in {None, 0}:
        return {
            "status": "unknown",
            "reason": missing_reason,
            "price": price,
            "previous_close": previous_close,
            "change_pct": None,
            "price_semantics": semantics,
            "as_of": as_of,
        }

    return {
        "status": "observed",
        "reason": None,
        "price": price,
        "previous_close": previous_close,
        "change_pct": ((price - previous_close) / previous_close) * 100,
        "price_semantics": semantics,
        "as_of": as_of,
    }


def _load_universe(db: Session) -> list[StockMaster]:
    return (
        db.query(StockMaster)
        .filter(StockMaster.market.in_(SUPPORTED_MARKETS))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .order_by(StockMaster.market.asc(), StockMaster.stock_id.asc())
        .all()
    )


def _load_state_by_stock(
    db: Session,
    *,
    trade_date: date,
) -> dict[tuple[str, str], TaiwanIntradayStockState]:
    rows = (
        db.query(TaiwanIntradayStockState)
        .filter(TaiwanIntradayStockState.market.in_(SUPPORTED_MARKETS))
        .filter(TaiwanIntradayStockState.trade_date == trade_date)
        .filter(
            TaiwanIntradayStockState.state_contract_version
            == INTRADAY_STATE_VERSION
        )
        .all()
    )
    latest: dict[tuple[str, str], TaiwanIntradayStockState] = {}
    for state in rows:
        key = (state.market, state.stock_id)
        current = latest.get(key)
        if current is None or _state_as_of(state) > _state_as_of(current):
            latest[key] = state
    return latest


def _build_breadth(
    stocks: Iterable[StockMaster],
    state_by_stock: dict[tuple[str, str], TaiwanIntradayStockState],
    *,
    market: str,
    session_phase: str,
) -> dict[str, Any]:
    market_stocks = [stock for stock in stocks if stock.market == market]
    observations = [
        _observation(
            state_by_stock.get((market, stock.stock_id)),
            session_phase=session_phase,
        )
        for stock in market_stocks
    ]
    observed = [item for item in observations if item["status"] == "observed"]
    advance = sum(1 for item in observed if float(item["change_pct"]) > 0)
    decline = sum(1 for item in observed if float(item["change_pct"]) < 0)
    unchanged = len(observed) - advance - decline
    universe = len(market_stocks)
    coverage = advance + decline + unchanged
    unknown = universe - coverage
    as_of_values = [item["as_of"] for item in observed if item["as_of"] is not None]
    warnings: list[str] = []
    if session_phase == "preopen_pending":
        status = "not_observed"
        warnings.append("Taiwan preopen collection has not started yet.")
    elif coverage == 0:
        status = "missing"
        warnings.append(f"No classified {market} observations are available.")
    elif unknown > 0:
        status = "partial"
        warnings.append(
            f"{unknown} of {universe} {market} stocks remain unclassified."
        )
    else:
        status = "ready"

    return {
        "market": market,
        "status": status,
        "session_phase": session_phase,
        "price_semantics": (
            "auction_indicative"
            if session_phase == "preopen"
            else "not_observed"
            if session_phase == "preopen_pending"
            else "actual_trade"
        ),
        "provisional": session_phase in {"preopen", "closing_auction"},
        "decision_usable": session_phase not in {"preopen", "preopen_pending"}
        and coverage > 0,
        "universe": universe,
        "coverage": coverage,
        "advance": advance,
        "decline": decline,
        "unchanged": unchanged,
        "unknown": unknown,
        "coverage_ratio": coverage / universe if universe else 0.0,
        "as_of": max(as_of_values) if as_of_values else None,
        "warnings": warnings,
    }


def _build_hot_groups(
    stocks: Iterable[StockMaster],
    state_by_stock: dict[tuple[str, str], TaiwanIntradayStockState],
    *,
    session_phase: str,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[StockMaster]] = defaultdict(list)
    for stock in stocks:
        group_key = str(stock.industry or stock.category or "").strip()
        if group_key:
            grouped[(stock.market, group_key)].append(stock)

    items: list[dict[str, Any]] = []
    for (market, group_key), group_stocks in grouped.items():
        observations = [
            _observation(
                state_by_stock.get((market, stock.stock_id)),
                session_phase=session_phase,
            )
            for stock in group_stocks
        ]
        observed = [item for item in observations if item["status"] == "observed"]
        changes = [float(item["change_pct"]) for item in observed]
        universe = len(group_stocks)
        coverage = len(changes)
        if coverage < 3:
            continue
        coverage_ratio = coverage / universe if universe else 0.0
        advance_ratio = sum(1 for value in changes if value > 0) / coverage
        as_of_values = [
            item["as_of"] for item in observed if item["as_of"] is not None
        ]
        items.append(
            {
                "group_id": f"{market}:{group_key}",
                "group_key": group_key,
                "label": normalize_tw_industry_label(group_key),
                "market": market,
                "status": "ready" if coverage == universe else "partial",
                "universe": universe,
                "coverage": coverage,
                "unknown": universe - coverage,
                "coverage_ratio": coverage_ratio,
                "advance_ratio": advance_ratio,
                "mean_change_pct": sum(changes) / coverage,
                "median_change_pct": median(changes),
                "dispersion_pct": pstdev(changes) if coverage > 1 else 0.0,
                "as_of": max(as_of_values) if as_of_values else None,
                "provisional": session_phase in {"preopen", "closing_auction"},
                "decision_usable": session_phase not in {
                    "preopen",
                    "preopen_pending",
                },
            }
        )

    items.sort(
        key=lambda item: (
            -float(item["median_change_pct"]),
            -float(item["advance_ratio"]),
            -float(item["coverage_ratio"]),
            str(item["group_id"]),
        )
    )
    return items[:limit]


def _list_watchlist_groups(db: Session) -> list[dict[str, Any]]:
    return [
        {
            "group_id": int(group.id),
            "group_name": group.group_name,
            "parent_id": int(group.parent_id) if group.parent_id is not None else None,
            "sort_order": int(group.sort_order),
        }
        for group in list_groups(db=db, is_active=True)
    ]


def _resolve_watchlist_group(
    db: Session,
    group_id: int | None,
) -> tuple[WatchlistGroup | None, str]:
    if group_id is not None:
        group = (
            db.query(WatchlistGroup)
            .filter(WatchlistGroup.id == group_id)
            .filter(WatchlistGroup.is_active.is_(True))
            .first()
        )
        if group is None:
            raise TaiwanDashboardWatchlistGroupNotFoundError(
                f"Active watchlist group id={group_id} was not found."
            )
        return group, "explicit_group_id"

    group = (
        db.query(WatchlistGroup)
        .filter(WatchlistGroup.is_active.is_(True))
        .filter(WatchlistGroup.parent_id.is_(None))
        .order_by(WatchlistGroup.sort_order.asc(), WatchlistGroup.id.asc())
        .first()
    )
    return group, "first_active_root_by_sort_order"


def _build_watchlist(
    db: Session,
    state_by_stock: dict[tuple[str, str], TaiwanIntradayStockState],
    *,
    session_phase: str,
    group_id: int | None,
    include_children: bool,
    limit: int,
) -> dict[str, Any]:
    groups = _list_watchlist_groups(db)
    group, selection_policy = _resolve_watchlist_group(db, group_id)
    selection = {
        "group_id": group.id if group is not None else None,
        "group_name": group.group_name if group is not None else None,
        "selection_policy": selection_policy,
        "include_children": include_children,
        "enabled_only": True,
        "limit": limit,
        "truncated": False,
    }
    if group is None:
        return {
            "status": "missing",
            "groups": groups,
            "selection": selection,
            "items": [],
            "warnings": ["No active root watchlist group is configured."],
        }

    raw_items = list_items(
        db=db,
        group_id=group.id,
        enabled=True,
        include_children=include_children,
        limit=limit + 1,
        offset=0,
    )
    selection["truncated"] = len(raw_items) > limit
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        stock_id = str(item.get("stock_id") or "")
        if not stock_id or stock_id in seen:
            continue
        seen.add(stock_id)
        market = str(item.get("market") or "").upper()
        observation = _observation(
            state_by_stock.get((market, stock_id)),
            session_phase=session_phase,
        )
        deduplicated.append(
            {
                "stock_id": stock_id,
                "stock_name": item.get("stock_name"),
                "market": market or None,
                "status": observation["status"],
                "price": observation["price"],
                "previous_close": observation["previous_close"],
                "change_pct": observation["change_pct"],
                "price_semantics": observation["price_semantics"],
                "as_of": observation["as_of"],
                "warning": observation["reason"],
            }
        )
        if len(deduplicated) >= limit:
            break

    observed_count = sum(item["status"] == "observed" for item in deduplicated)
    return {
        "status": (
            "ready"
            if deduplicated and observed_count == len(deduplicated)
            else "partial"
            if deduplicated
            else "missing"
        ),
        "groups": groups,
        "selection": selection,
        "items": deduplicated,
        "warnings": (
            []
            if observed_count == len(deduplicated)
            else [
                f"{len(deduplicated) - observed_count} watchlist item(s) "
                "do not have a classified current-session observation."
            ]
        ),
    }


def estimate_cap_weighted_index(
    *,
    baseline_close: float | None,
    components: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    component_rows = list(components)
    eligible: list[tuple[float, float, float | None]] = []
    for component in component_rows:
        shares = _number(component.get("shares"))
        reference_price = _number(component.get("reference_price"))
        observed_price = _number(component.get("observed_price"))
        if shares is None or shares <= 0 or reference_price is None or reference_price <= 0:
            continue
        eligible.append((shares, reference_price, observed_price))

    universe_count = len(component_rows)
    eligible_count = len(eligible)
    observed_count = sum(observed_price is not None for _, _, observed_price in eligible)
    total_reference_cap = sum(shares * reference for shares, reference, _ in eligible)
    observed_reference_cap = sum(
        shares * reference
        for shares, reference, observed_price in eligible
        if observed_price is not None
    )
    market_cap_delta = sum(
        shares * (observed_price - reference)
        for shares, reference, observed_price in eligible
        if observed_price is not None
    )
    component_data_coverage_ratio = (
        eligible_count / universe_count if universe_count else 0.0
    )
    observed_weight = (
        observed_reference_cap / total_reference_cap
        if total_reference_cap > 0
        else None
    )
    uncovered_weight = (
        max(1.0 - observed_weight, 0.0) if observed_weight is not None else None
    )
    estimate_available = (
        baseline_close is not None
        and baseline_close > 0
        and total_reference_cap > 0
        and observed_count > 0
        and component_data_coverage_ratio >= MIN_INDEX_COMPONENT_DATA_COVERAGE
    )
    change_pct = (
        (market_cap_delta / total_reference_cap) * 100
        if estimate_available
        else None
    )
    change = (
        baseline_close * market_cap_delta / total_reference_cap
        if estimate_available
        else None
    )
    estimate = baseline_close + change if change is not None else None
    return {
        "estimate": estimate,
        "change": change,
        "change_pct": change_pct,
        "component_universe_count": universe_count,
        "eligible_component_count": eligible_count,
        "observed_component_count": observed_count,
        "component_data_coverage_ratio": component_data_coverage_ratio,
        "observed_weight": observed_weight,
        "uncovered_weight": uncovered_weight,
        "estimate_available": estimate_available,
    }


def _latest_index_baseline(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
) -> MarketIndexDailyStat | None:
    previous_session = previous_taiwan_trading_day(
        trade_date,
        include_value=False,
    )
    return (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date <= previous_session)
        .filter(MarketIndexDailyStat.close_value.is_not(None))
        .order_by(MarketIndexDailyStat.trade_date.desc())
        .first()
    )


def _build_index_estimates(
    db: Session,
    stocks: Iterable[StockMaster],
    state_by_stock: dict[tuple[str, str], TaiwanIntradayStockState],
    *,
    session_phase: str,
    trade_date: date,
) -> list[dict[str, Any]]:
    stock_rows = list(stocks)
    stock_ids = [stock.stock_id for stock in stock_rows]
    profiles = (
        db.query(StockProfile)
        .filter(StockProfile.stock_id.in_(stock_ids))
        .all()
        if stock_ids
        else []
    )
    profile_by_stock = {profile.stock_id: profile for profile in profiles}
    estimates: list[dict[str, Any]] = []
    for market in SUPPORTED_MARKETS:
        index_id = INDEX_ID_BY_MARKET[market]
        baseline = _latest_index_baseline(
            db,
            index_id=index_id,
            trade_date=trade_date,
        )
        components: list[dict[str, Any]] = []
        shares_dates: list[date] = []
        for stock in stock_rows:
            if stock.market != market:
                continue
            state = state_by_stock.get((market, stock.stock_id))
            observation = _observation(state, session_phase=session_phase)
            profile = profile_by_stock.get(stock.stock_id)
            if profile is not None and profile.report_date is not None:
                shares_dates.append(profile.report_date)
            components.append(
                {
                    "shares": profile.issued_shares if profile is not None else None,
                    "reference_price": (
                        state.previous_close if state is not None else None
                    ),
                    "observed_price": (
                        observation["price"]
                        if observation["status"] == "observed"
                        else None
                    ),
                }
            )
        estimate = estimate_cap_weighted_index(
            baseline_close=_number(baseline.close_value) if baseline else None,
            components=components,
        )
        warnings: list[str] = []
        limitations = [
            "The component universe uses active StockMaster stocks as a proxy and is not an official dated constituent file.",
            "Corporate-action and divisor adjustments are not yet verified for this snapshot.",
            "Missing indicative quotes contribute zero price delta without renormalizing observed weights.",
        ]
        if not estimate["estimate_available"]:
            warnings.append(
                "The provisional estimate is unavailable because baseline or component data coverage is insufficient."
            )
        if estimate["uncovered_weight"] not in {None, 0.0}:
            warnings.append(
                f"{float(estimate['uncovered_weight']) * 100:.2f}% of eligible reference weight has no classified quote."
            )
        estimates.append(
            {
                "index_id": index_id,
                "market": market,
                "status": "partial" if estimate["estimate_available"] else "unavailable",
                "estimate": estimate["estimate"],
                "change": estimate["change"],
                "change_pct": estimate["change_pct"],
                "baseline_close": _number(baseline.close_value) if baseline else None,
                "baseline_trade_date": baseline.trade_date if baseline else None,
                "component_universe_count": estimate["component_universe_count"],
                "eligible_component_count": estimate["eligible_component_count"],
                "observed_component_count": estimate["observed_component_count"],
                "component_data_coverage_ratio": estimate[
                    "component_data_coverage_ratio"
                ],
                "observed_weight": estimate["observed_weight"],
                "uncovered_weight": estimate["uncovered_weight"],
                "constituent_as_of": None,
                "shares_as_of": max(shares_dates) if shares_dates else None,
                "divisor_adjustment_status": "not_verified",
                "methodology_version": INDEX_ESTIMATE_METHOD_VERSION,
                "component_universe_source": "stock_master.active_stock_proxy",
                "provisional": True,
                "official": False,
                "decision_usable": False,
                "warnings": warnings,
                "limitations": limitations,
            }
        )
    return estimates


def build_tw_market_dashboard(
    db: Session,
    *,
    watchlist_group_id: int | None = None,
    include_watchlist_children: bool = True,
    watchlist_limit: int = DEFAULT_WATCHLIST_LIMIT,
    group_limit: int = DEFAULT_GROUP_LIMIT,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = _aware_taipei(now) or datetime.now(TAIWAN_TZ)
    presentation = taiwan_presentation_session(checked_at)
    trade_date = presentation["trade_date"]
    assert isinstance(trade_date, date)
    session_phase = taiwan_market_session_phase(checked_at)
    stocks = _load_universe(db)
    state_by_stock = _load_state_by_stock(db, trade_date=trade_date)
    state_times = [_state_as_of(state) for state in state_by_stock.values()]
    oldest_as_of = min(state_times) if state_times else None
    newest_as_of = max(state_times) if state_times else None
    freshness_status, max_age_seconds = _freshness_status(
        newest_as_of,
        now=checked_at,
    )
    breadth = {
        market: _build_breadth(
            stocks,
            state_by_stock,
            market=market,
            session_phase=session_phase,
        )
        for market in SUPPORTED_MARKETS
    }
    hot_groups = _build_hot_groups(
        stocks,
        state_by_stock,
        session_phase=session_phase,
        limit=group_limit,
    )
    watchlist = _build_watchlist(
        db,
        state_by_stock,
        session_phase=session_phase,
        group_id=watchlist_group_id,
        include_children=include_watchlist_children,
        limit=watchlist_limit,
    )
    indices = _build_index_estimates(
        db,
        stocks,
        state_by_stock,
        session_phase=session_phase,
        trade_date=trade_date,
    )
    trade_date_floor = datetime.combine(
        trade_date,
        time.min,
        tzinfo=TAIWAN_TZ,
    )
    state_version = max(
        int(trade_date_floor.timestamp() * 1000),
        int(newest_as_of.timestamp() * 1000) if newest_as_of else 0,
    )
    snapshot_seed = "|".join(
        (
            TW_MARKET_DASHBOARD_VERSION,
            trade_date.isoformat(),
            session_phase,
            str(state_version),
            str(watchlist["selection"]["group_id"]),
        )
    )
    warnings = [
        warning
        for item in breadth.values()
        for warning in item["warnings"]
    ]
    warnings.extend(watchlist["warnings"])
    if freshness_status in {"delayed", "stale", "missing"}:
        warnings.append(f"Dashboard snapshot freshness is {freshness_status}.")
    if any(item["status"] != "partial" for item in indices):
        warnings.append("One or more provisional index estimates are unavailable.")
    warnings = list(dict.fromkeys(warnings))
    return {
        "kind": "omi.tw_market_dashboard",
        "version": TW_MARKET_DASHBOARD_VERSION,
        "snapshot_id": sha256(snapshot_seed.encode("utf-8")).hexdigest()[:24],
        "state_version": state_version,
        "trade_date": trade_date,
        "session": {
            "phase": session_phase,
            "presentation_state": str(presentation["state"]),
            "trade_date": trade_date,
            "is_current_trading_day": bool(
                presentation["is_current_trading_day"]
            ),
            "next_transition_at": presentation["next_transition_at"],
        },
        "as_of": newest_as_of,
        "indices": indices,
        "breadth": breadth,
        "hot_groups": hot_groups,
        "watchlist": watchlist,
        "freshness": {
            "status": freshness_status,
            "cache_only": True,
            "oldest_as_of": oldest_as_of,
            "newest_as_of": newest_as_of,
            "max_age_seconds": max_age_seconds,
            "source": "taiwan_intraday_stock_state",
        },
        "warnings": warnings,
        "limitations": [
            "The dashboard read path is cache-only and never triggers provider refresh.",
            "Preopen observations and all index estimates are provisional and not decision-usable.",
            "Hot groups use current StockMaster industry/category membership.",
        ],
    }


def search_tw_dashboard_symbols(
    db: Session,
    *,
    keyword: str,
    limit: int = 20,
) -> dict[str, Any]:
    normalized = str(keyword or "").strip()
    if not normalized:
        raise ValueError("keyword must not be empty.")
    escaped = (
        normalized.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    pattern = f"%{escaped}%"
    prefix = f"{escaped}%"
    rows = (
        db.query(StockMaster)
        .filter(StockMaster.market.in_(SUPPORTED_MARKETS))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .filter(
            or_(
                StockMaster.stock_id.ilike(pattern, escape="\\"),
                StockMaster.stock_name.ilike(pattern, escape="\\"),
            )
        )
        .order_by(
            case((StockMaster.stock_id == normalized, 0), else_=1),
            case(
                (StockMaster.stock_id.ilike(prefix, escape="\\"), 0),
                else_=1,
            ),
            StockMaster.stock_id.asc(),
        )
        .limit(limit)
        .all()
    )
    items = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "market": row.market,
            "industry": row.industry,
        }
        for row in rows
    ]
    return {
        "kind": "omi.tw_symbol_search",
        "version": TW_SYMBOL_SEARCH_VERSION,
        "query": normalized,
        "count": len(items),
        "limit": limit,
        "items": items,
    }


def build_dashboard_moving_average_series(
    points: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = list(points)
    closes = [_number(row.get("close")) for row in rows]
    periods = (5, 20, 60)
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item: dict[str, Any] = {"time": row.get("time")}
        for period in periods:
            start = index - period + 1
            window = closes[start : index + 1] if start >= 0 else []
            item[f"ma{period}"] = (
                sum(float(value) for value in window) / period
                if len(window) == period
                and all(value is not None for value in window)
                else None
            )
        output.append(item)
    return output


def build_tw_dashboard_stock_detail(
    db: Session,
    *,
    stock_id: str,
    timeframe: str = "daily",
    bars: int = 90,
) -> dict[str, Any]:
    normalized_stock_id = str(stock_id or "").strip()
    normalized_timeframe = str(timeframe or "daily").strip().lower()
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .filter(StockMaster.market.in_(SUPPORTED_MARKETS))
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .first()
    )
    if stock is None:
        raise TaiwanDashboardStockNotFoundError(
            f"Active Taiwan stock id='{normalized_stock_id}' was not found."
        )
    if normalized_timeframe not in {"daily", "weekly", "monthly"}:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    include_intraday = normalized_timeframe == "daily"
    chart = list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe=normalized_timeframe,
        bars=bars,
        ensure_history=False,
        include_intraday=include_intraday,
    )
    technical = build_stock_technical_report(
        db=db,
        stock_id=normalized_stock_id,
        timeframe=normalized_timeframe,
        include_intraday=include_intraday,
    )
    warnings = list(
        dict.fromkeys(
            [
                *[str(value) for value in chart.get("warnings") or []],
                *[str(value) for value in technical.get("warnings") or []],
            ]
        )
    )
    return {
        "kind": "omi.tw_stock_dashboard_detail",
        "version": TW_STOCK_DASHBOARD_DETAIL_VERSION,
        "stock_id": normalized_stock_id,
        "stock_name": stock.stock_name,
        "market": stock.market,
        "timeframe": normalized_timeframe,
        "bars": bars,
        "cache_only": True,
        "chart": chart,
        "moving_averages": build_dashboard_moving_average_series(
            chart.get("points") or []
        ),
        "technical": technical,
        "warnings": warnings,
        "limitations": [
            "This read path uses cached local OHLC, intraday, and technical evidence only.",
            "Missing or stale history is returned truthfully and never backfilled by this GET request.",
        ],
    }


__all__ = [
    "DEFAULT_GROUP_LIMIT",
    "DEFAULT_WATCHLIST_LIMIT",
    "INDEX_ESTIMATE_METHOD_VERSION",
    "TW_MARKET_DASHBOARD_VERSION",
    "TW_STOCK_DASHBOARD_DETAIL_VERSION",
    "TW_SYMBOL_SEARCH_VERSION",
    "TaiwanDashboardWatchlistGroupNotFoundError",
    "TaiwanDashboardStockNotFoundError",
    "build_dashboard_moving_average_series",
    "build_tw_dashboard_stock_detail",
    "build_tw_market_dashboard",
    "estimate_cap_weighted_index",
    "search_tw_dashboard_symbols",
]
