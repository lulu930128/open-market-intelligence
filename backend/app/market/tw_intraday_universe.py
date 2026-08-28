from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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


INTRADAY_UNIVERSE_VERSION = "tw.intraday.universe.v1"


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
    return _normalized_symbols(row[0] for row in rows)


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


def resolve_taiwan_intraday_target_universe(
    db: Session,
    *,
    max_symbols: int | None = None,
    configured_symbols: Iterable[object] | None = None,
    lease_symbols: Iterable[object] | None = None,
) -> dict[str, Any]:
    """Resolve the bounded Tier-A target set shared by acquisition and health.

    This is a read-only target planner. It never expands to the full Taiwan
    market and it validates every candidate against the active StockMaster.
    """

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
    sources = (
        (
            "configured",
            _normalized_symbols(
                configured_symbols
                if configured_symbols is not None
                else _configured_symbols()
            ),
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

    selected = eligible[:hard_cap]
    for symbol in eligible[hard_cap:]:
        skipped_targets.append(
            {
                "stock_id": symbol,
                "reason": "scheduler_hard_cap",
                "origins": origins_by_symbol[symbol],
            }
        )

    return {
        "version": INTRADAY_UNIVERSE_VERSION,
        "symbols": selected,
        "targets": [
            {
                "stock_id": symbol,
                "origins": origins_by_symbol[symbol],
                "instrument_type": masters[symbol].instrument_type,
                "market": masters[symbol].market,
            }
            for symbol in selected
        ],
        "candidate_count": len(ordered_candidates),
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "skipped_count": len(skipped_targets),
        "max_symbols": hard_cap,
        "skipped_targets": skipped_targets,
        "scope_semantics": "bounded_tier_a_universe_not_all_market",
        "source_priority": [
            "configured",
            "holding",
            "active_lease",
            "watchlist",
        ],
    }


__all__ = [
    "INTRADAY_UNIVERSE_VERSION",
    "resolve_taiwan_intraday_target_universe",
]
