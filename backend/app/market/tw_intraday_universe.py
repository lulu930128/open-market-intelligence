from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    PortfolioHolding,
    StockMaster,
    WatchlistGroup,
    WatchlistItem,
)
from app.market.taiwan_market_state import SUPPORTED_MARKETS
from app.market.tw_realtime_lease_platform import (
    summarize_taiwan_realtime_quote_leases,
)
from app.market_data.contracts import CanonicalModel


INTRADAY_UNIVERSE_VERSION = "tw.intraday.universe.v1"
TIER_A_TARGET_PLAN_VERSION = "tw.tier_a_target_plan.v1"


class TaiwanTierATarget(CanonicalModel):
    stock_id: str
    origins: tuple[str, ...]
    instrument_type: str
    market: str


class TaiwanTierATargetPlan(CanonicalModel):
    contract_version: str = TIER_A_TARGET_PLAN_VERSION
    operation_profile: Literal[
        "production_intraday",
        "production_session_close",
        "acceptance_canary",
    ]
    symbols: tuple[str, ...]
    targets: tuple[TaiwanTierATarget, ...]
    candidate_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    max_symbols: int = Field(gt=0)
    configured_symbol_count: int = Field(ge=0)
    skipped_targets: tuple[dict[str, Any], ...] = ()
    scope_semantics: str = "bounded_tier_a_universe_not_all_market"
    profile_semantics: str
    source_priority: tuple[str, ...] = (
        "configured",
        "holding",
        "active_lease",
        "watchlist",
    )


def _normalized_symbols(values: Iterable[object]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value or "").strip().upper()
            for value in values
            if str(value or "").strip()
        )
    )


def _configured_symbols() -> list[str]:
    return _normalized_symbols(
        settings.scheduler_taiwan_quote_contract_symbols.split(",")
    )


def _holding_symbols(db: Session) -> list[str]:
    rows = (
        db.query(PortfolioHolding.symbol)
        .filter(PortfolioHolding.market == "tw")
        .filter(PortfolioHolding.is_active.is_(True))
        .filter(PortfolioHolding.quantity != 0)
        .order_by(PortfolioHolding.symbol.asc())
        .all()
    )
    return _normalized_symbols(row[0] for row in rows)


def _watchlist_symbols(db: Session) -> list[str]:
    rows = (
        db.query(WatchlistItem.stock_id)
        .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
        .filter(WatchlistItem.enabled.is_(True))
        .filter(WatchlistGroup.is_active.is_(True))
        .order_by(
            WatchlistItem.priority.asc(),
            WatchlistItem.stock_id.asc(),
        )
        .all()
    )
    symbols = _normalized_symbols(row[0] for row in rows)
    if not symbols:
        return []
    instrument_types = {
        row.stock_id: str(row.instrument_type or "").strip().lower()
        for row in (
            db.query(StockMaster)
            .filter(StockMaster.stock_id.in_(symbols))
            .all()
        )
    }
    # A bounded producer slot should not systematically starve ETFs merely
    # because ordinary stocks happen to have lower watchlist priorities.
    # This ordering stays inside the existing Watchlist source boundary.
    return [
        *[symbol for symbol in symbols if instrument_types.get(symbol) == "etf"],
        *[symbol for symbol in symbols if instrument_types.get(symbol) != "etf"],
    ]


def list_taiwan_active_watchlist_instruments(
    db: Session,
) -> tuple[StockMaster, ...]:
    """Return the bounded Stock/ETF identities referenced by active watchlists."""

    symbols = _watchlist_symbols(db)
    if not symbols:
        return ()
    masters = {
        row.stock_id: row
        for row in (
            db.query(StockMaster)
            .filter(StockMaster.stock_id.in_(symbols))
            .filter(StockMaster.is_active.is_(True))
            .all()
        )
    }
    return tuple(
        master
        for symbol in symbols
        if (master := masters.get(symbol)) is not None
        and str(master.market or "").strip().upper() in SUPPORTED_MARKETS
        and str(master.instrument_type or "").strip().lower() in {"stock", "etf"}
    )


def _lease_symbols() -> list[str]:
    summary = summarize_taiwan_realtime_quote_leases()
    counts = getattr(summary, "leases_by_symbol", {}) or {}
    return _normalized_symbols(
        symbol
        for symbol, _count in sorted(
            counts.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
    )


def resolve_taiwan_tier_a_target_plan(
    db: Session,
    *,
    operation_profile: Literal[
        "production_intraday",
        "production_session_close",
        "acceptance_canary",
    ] = "production_intraday",
    max_symbols: int | None = None,
    configured_symbols: Iterable[object] | None = None,
    lease_symbols: Iterable[object] | None = None,
) -> dict[str, Any]:
    """Resolve the single ordered Tier-A target plan for one operation profile.

    This is a read-only target planner. It never expands to the full Taiwan
    market and it validates every candidate against the active StockMaster.
    """

    if operation_profile not in {
        "production_intraday",
        "production_session_close",
        "acceptance_canary",
    }:
        raise ValueError("unsupported Taiwan Tier-A operation profile")

    hard_cap = max(
        min(
            int(
                max_symbols
                if max_symbols is not None
                else settings.scheduler_taiwan_intraday_bar_max_symbols
            ),
            100,
        ),
        1,
    )
    configured = _normalized_symbols(
        configured_symbols
        if configured_symbols is not None
        else _configured_symbols()
    )
    sources = (
        (
            "configured",
            configured,
        ),
        ("holding", _holding_symbols(db)),
        (
            "active_lease",
            _normalized_symbols(
                lease_symbols if lease_symbols is not None else _lease_symbols()
            ),
        ),
        ("watchlist", _watchlist_symbols(db)),
    )

    origins_by_symbol: dict[str, list[str]] = {}
    ordered_candidates: list[str] = []
    for origin, symbols in sources:
        for symbol in symbols:
            origins = origins_by_symbol.setdefault(symbol, [])
            origins.append(origin)
            if len(origins) == 1:
                ordered_candidates.append(symbol)

    masters = {
        row.stock_id: row
        for row in (
            db.query(StockMaster)
            .filter(StockMaster.stock_id.in_(ordered_candidates))
            .all()
            if ordered_candidates
            else []
        )
    }
    eligible: list[str] = []
    skipped_targets: list[dict[str, Any]] = []
    for symbol in ordered_candidates:
        master = masters.get(symbol)
        if master is None:
            skipped_targets.append(
                {
                    "stock_id": symbol,
                    "reason": "target_not_found",
                    "origins": origins_by_symbol[symbol],
                }
            )
            continue
        if not master.is_active:
            skipped_targets.append(
                {
                    "stock_id": symbol,
                    "reason": "inactive_instrument",
                    "origins": origins_by_symbol[symbol],
                }
            )
            continue
        if str(master.market or "").upper() not in SUPPORTED_MARKETS:
            skipped_targets.append(
                {
                    "stock_id": symbol,
                    "reason": "not_taiwan_cash_market",
                    "origins": origins_by_symbol[symbol],
                }
            )
            continue
        eligible.append(symbol)

    profile_eligible = eligible
    profile_semantics = "all_eligible_targets_in_canonical_order"
    if operation_profile == "acceptance_canary" and configured:
        configured_set = set(configured)
        profile_eligible = [
            symbol for symbol in eligible if symbol in configured_set
        ]
        profile_semantics = "configured_canary_subset_of_canonical_plan"
        for symbol in eligible:
            if symbol not in configured_set:
                skipped_targets.append(
                    {
                        "stock_id": symbol,
                        "reason": "acceptance_canary_profile_excluded",
                        "origins": origins_by_symbol[symbol],
                    }
                )
    elif operation_profile == "acceptance_canary":
        profile_semantics = "watchlist_fallback_canary_from_canonical_plan"

    selected = profile_eligible[:hard_cap]
    for symbol in profile_eligible[hard_cap:]:
        skipped_targets.append(
            {
                "stock_id": symbol,
                "reason": "scheduler_hard_cap",
                "origins": origins_by_symbol[symbol],
            }
        )

    plan = TaiwanTierATargetPlan(
        operation_profile=operation_profile,
        symbols=tuple(selected),
        targets=tuple(
            TaiwanTierATarget(
                stock_id=symbol,
                origins=tuple(origins_by_symbol[symbol]),
                instrument_type=masters[symbol].instrument_type,
                market=masters[symbol].market,
            )
            for symbol in selected
        ),
        candidate_count=len(ordered_candidates),
        eligible_count=len(eligible),
        selected_count=len(selected),
        skipped_count=len(skipped_targets),
        max_symbols=hard_cap,
        configured_symbol_count=len(configured),
        skipped_targets=tuple(skipped_targets),
        profile_semantics=profile_semantics,
    )
    return {
        "version": INTRADAY_UNIVERSE_VERSION,
        **plan.model_dump(mode="json"),
    }


def resolve_taiwan_intraday_target_universe(
    db: Session,
    *,
    max_symbols: int | None = None,
    configured_symbols: Iterable[object] | None = None,
    lease_symbols: Iterable[object] | None = None,
) -> dict[str, Any]:
    """Compatibility projection of the canonical production target plan."""

    return resolve_taiwan_tier_a_target_plan(
        db,
        operation_profile="production_intraday",
        max_symbols=max_symbols,
        configured_symbols=configured_symbols,
        lease_symbols=lease_symbols,
    )


__all__ = [
    "INTRADAY_UNIVERSE_VERSION",
    "TIER_A_TARGET_PLAN_VERSION",
    "TaiwanTierATarget",
    "TaiwanTierATargetPlan",
    "list_taiwan_active_watchlist_instruments",
    "resolve_taiwan_intraday_target_universe",
    "resolve_taiwan_tier_a_target_plan",
]
