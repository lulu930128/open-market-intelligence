"""Progressive Taiwan workspace reads; canonical owners retain all semantics."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import TaiwanIntradayStockState
from app.market.trading_calendar import (
    TAIWAN_TZ, TAIWAN_SESSION_CLOSE_TIME, taiwan_market_session_phase, taiwan_presentation_session,
)
from app.market.tw_intraday_state import INTRADAY_STATE_VERSION, build_tw_hot_groups_snapshot
from app.market.tw_market_dashboard import (
    SUPPORTED_MARKETS, _aware_taipei, _build_resolved_indices, _build_watchlist,
    _freshness_status, _project_hot_groups_for_dashboard,
)


def build_tw_workspace_header(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    checked_at = _aware_taipei(now) or datetime.now(TAIWAN_TZ)
    presentation = taiwan_presentation_session(checked_at)
    trade_date = presentation["trade_date"]
    assert isinstance(trade_date, date)
    with db.no_autoflush:
        state = TaiwanIntradayStockState
        observed = func.coalesce(state.snapshot_as_of, state.event_time)
        ranked = db.query(
            observed.label("observed"),
            func.coalesce(state.event_time, observed).label("event_time"),
            func.row_number().over(
                partition_by=(state.market, state.stock_id),
                order_by=(observed.desc(), state.id.desc()),
            ).label("ordinal"),
        ).filter(
            state.market.in_(SUPPORTED_MARKETS), state.trade_date == trade_date,
            state.state_contract_version == INTRADAY_STATE_VERSION,
        ).subquery()
        oldest, newest, completed = db.query(
            func.min(ranked.c.observed), func.max(ranked.c.observed),
            func.max(case((func.time(ranked.c.event_time) >= TAIWAN_SESSION_CLOSE_TIME.isoformat(), 1), else_=0)),
        ).filter(ranked.c.ordinal == 1).one()
        oldest, newest = _aware_taipei(oldest), _aware_taipei(newest)
        freshness, age = _freshness_status(
            newest, now=checked_at, evidence_trade_date=trade_date if newest else None,
            expected_trade_date=trade_date, presentation_state=str(presentation["state"]),
            completed_session_evidence=bool(completed),
        )
        indices, breadth, warnings = _build_resolved_indices(db, requested_at=checked_at, allow_universe_fallback=False)
    warnings.extend(warning for item in breadth.values() for warning in item["warnings"])
    if freshness in {"delayed", "stale", "missing"}:
        warnings.append(f"Intraday state snapshot freshness is {freshness}.")
    return {
        "kind": "omi.tw_workspace_header", "version": "omi.tw_workspace_header.v1",
        "cache_only": True, "generated_at": checked_at,
        "session": {
            "phase": taiwan_market_session_phase(checked_at),
            "presentation_state": presentation["state"], "trade_date": trade_date,
            "is_current_trading_day": presentation["is_current_trading_day"],
            "next_transition_at": presentation["next_transition_at"],
        },
        "resolved_indices": indices, "resolved_breadth": breadth,
        "freshness": {
            "status": freshness,
            "basis": "completed_session_date" if freshness == "latest_completed_session" else "producer_cadence",
            "cache_only": True, "oldest_as_of": oldest, "newest_as_of": newest,
            "max_age_seconds": age, "source": "taiwan_intraday_stock_state",
            "producer_cadence_seconds": int(settings.scheduler_taiwan_intraday_bar_interval_seconds),
        },
        "warnings": list(dict.fromkeys(warnings)),
        "limitations": [
            "Freshness describes persisted intraday stock state; resolved indices and breadth retain their own evidence status.",
            "Independent workspace reads are not an atomic cross-panel snapshot.",
            "Official breadth uses persisted published summaries only; unavailable summaries do not trigger daily-universe reconstruction.",
        ],
    }


def build_tw_workspace_watchlist(
    db: Session, *, watchlist_group_id: int | None = None,
    include_watchlist_children: bool = True, watchlist_limit: int = 40,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= watchlist_limit <= 100:
        raise ValueError("watchlist_limit must be between 1 and 100")
    checked_at = _aware_taipei(now) or datetime.now(TAIWAN_TZ)
    with db.no_autoflush:
        result = _build_watchlist(db, requested_at=checked_at, group_id=watchlist_group_id,
                                 include_children=include_watchlist_children, limit=watchlist_limit)
    return {
        **result, "kind": "omi.tw_workspace_watchlist", "version": "omi.tw_workspace_watchlist.v1",
        "cache_only": True, "generated_at": checked_at,
    }


def build_tw_workspace_hot_groups(
    db: Session, *, group_limit: int = 8, now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= group_limit <= 30:
        raise ValueError("group_limit must be between 1 and 30")
    checked_at = _aware_taipei(now) or datetime.now(TAIWAN_TZ)
    with db.no_autoflush:
        snapshot = build_tw_hot_groups_snapshot(db, limit=group_limit, generated_at=checked_at,
                                               include_watchlist_groups=False)
    return {
        "kind": "omi.tw_workspace_hot_groups", "version": "omi.tw_workspace_hot_groups.v1",
        "cache_only": True, "generated_at": checked_at,
        "status": snapshot.get("status", "missing"), "lane": snapshot.get("lane", "actual"),
        "as_of": snapshot.get("event_time"),
        "hot_groups": _project_hot_groups_for_dashboard(snapshot, session_phase=taiwan_market_session_phase(checked_at)),
        "warnings": snapshot.get("warnings") or [],
        "limitations": ["Canonical hot-group ranking still reads the market universe; poll independently of header/watchlist/chart."],
    }
