from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Callable

from sqlalchemy.orm import Session

from app.db.models import PortfolioHolding, USWatchlistGroup, USWatchlistItem
from app.db.session import SessionLocal
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.symbols import normalize_us_symbol


PRIORITY_US_INDEX_SYMBOLS = (
    "^GSPC",
    "^DJI",
    "^IXIC",
    "^SOX",
    "^NDX",
    "^VIX",
)
PRIORITY_TIMEFRAME = "monthly"
PRIORITY_BAR_COUNT = 72
ProgressCallback = Callable[[int | None, int | None, str | None], None]
SessionFactory = Callable[[], Session]
PlatformFactory = Callable[[Session], USDailyOhlcvPlatform]


def list_us_priority_ohlc_symbols(db: Session) -> tuple[str, ...]:
    ordered: dict[str, None] = {}

    for symbol in PRIORITY_US_INDEX_SYMBOLS:
        ordered[normalize_us_symbol(symbol)] = None

    holding_rows = (
        db.query(PortfolioHolding.symbol)
        .filter(PortfolioHolding.market == "US")
        .filter(PortfolioHolding.is_active.is_(True))
        .order_by(PortfolioHolding.symbol.asc())
        .all()
    )
    for row in holding_rows:
        symbol = normalize_us_symbol(row.symbol)
        if symbol:
            ordered[symbol] = None

    watchlist_rows = (
        db.query(USWatchlistItem.symbol)
        .join(
            USWatchlistGroup,
            USWatchlistGroup.id == USWatchlistItem.group_id,
        )
        .filter(USWatchlistItem.enabled.is_(True))
        .filter(USWatchlistGroup.is_active.is_(True))
        .order_by(USWatchlistItem.priority.asc(), USWatchlistItem.symbol.asc())
        .all()
    )
    for row in watchlist_rows:
        symbol = normalize_us_symbol(row.symbol)
        if symbol:
            ordered[symbol] = None

    return tuple(ordered)


def reconcile_us_priority_ohlc(
    *,
    max_runtime_seconds: int = 600,
    cursor_symbol: str | None = None,
    progress_callback: ProgressCallback | None = None,
    session_factory: SessionFactory | None = None,
    platform_factory: PlatformFactory | None = None,
    repair: bool = True,
) -> dict:
    """Run a bounded priority read and optional explicit Shared-platform repair."""

    if max_runtime_seconds <= 0:
        raise ValueError("max_runtime_seconds must be greater than 0.")

    resolved_session_factory = session_factory or SessionLocal
    resolved_platform_factory = platform_factory or USDailyOhlcvPlatform
    universe_db = resolved_session_factory()
    try:
        universe_symbols = list_us_priority_ohlc_symbols(universe_db)
    finally:
        universe_db.close()
    normalized_cursor = normalize_us_symbol(cursor_symbol)
    if normalized_cursor and normalized_cursor in universe_symbols:
        cursor_index = universe_symbols.index(normalized_cursor)
        symbols = (
            universe_symbols[cursor_index + 1 :]
            + universe_symbols[: cursor_index + 1]
        )
    else:
        symbols = universe_symbols
    started = monotonic()
    checked_count = 0
    satisfied_count = 0
    repaired_count = 0
    provider_call_count = 0
    unresolved: list[dict] = []
    errors: list[dict] = []
    stopped_reason = "complete_scan"
    last_processed_symbol = normalized_cursor or None

    for index, symbol in enumerate(symbols, start=1):
        if monotonic() - started >= max_runtime_seconds:
            stopped_reason = "runtime_budget_exhausted"
            break
        if progress_callback is not None:
            progress_callback(
                index - 1,
                max(len(symbols), 1),
                f"Checking priority US OHLC {symbol}.",
            )

        chart_db = resolved_session_factory()
        try:
            platform = resolved_platform_factory(chart_db)
            platform_result = platform.read(
                symbol=symbol,
                bars=PRIORITY_BAR_COUNT,
            )
            history_satisfied = bool(
                platform_result.temporal_postcondition_satisfied
                and platform_result.coverage_postcondition_satisfied
            )
            if not history_satisfied and repair:
                platform_result = platform.ensure_history_coverage(
                    symbol=symbol,
                    bars=PRIORITY_BAR_COUNT,
                )
                provider_call_count += len(
                    platform_result.result.acquisition.attempts
                    if platform_result.result.acquisition is not None
                    else ()
                )
                history_satisfied = bool(
                    platform_result.temporal_postcondition_satisfied
                    and platform_result.coverage_postcondition_satisfied
                )
                if history_satisfied:
                    repaired_count += 1
        finally:
            chart_db.close()
        checked_count += 1
        if history_satisfied:
            satisfied_count += 1
        else:
            unresolved.append(
                {
                    "symbol": symbol,
                    "coverage_status": platform_result.projection.get("coverage_status"),
                    "latest_trade_date": platform_result.projection.get("latest_trade_date"),
                    "expected_trade_date": platform_result.projection.get("expected_trade_date"),
                    "reason": (
                        "shared_core_postcondition_unsatisfied"
                        if repair
                        else "repair_not_requested"
                    ),
                }
            )
            stopped_reason = "shared_core_postcondition_unsatisfied"
        last_processed_symbol = symbol

        if progress_callback is not None:
            progress_callback(
                index,
                max(len(symbols), 1),
                f"Checked {index}/{len(symbols)} priority US symbols.",
            )

    status = (
        "completed"
        if checked_count == len(symbols) and not unresolved and not errors
        else "partial"
    )
    return {
        "status": status,
        "dataset_id": "us.daily.ohlcv.priority_research",
        "scope": "indices+active_holdings+enabled_watchlist",
        "contract": {
            "timeframe": PRIORITY_TIMEFRAME,
            "bars": PRIORITY_BAR_COUNT,
            "continuity": "all completed US sessions from first available row",
            "history": "requested bars or provider-confirmed best available history",
        },
        "universe_count": len(symbols),
        "checked_count": checked_count,
        "satisfied_count": satisfied_count,
        "repair_available": True,
        "repair_requested": repair,
        "repaired_count": repaired_count,
        "external_call_count": provider_call_count,
        "provider_call_count": provider_call_count,
        "unresolved_count": max(len(symbols) - satisfied_count, 0),
        "unscanned_count": max(len(symbols) - checked_count, 0),
        "unresolved_sample": unresolved[:20],
        "error_count": len(errors),
        "errors": errors[:10],
        "stopped_reason": stopped_reason,
        "cursor_symbol": last_processed_symbol,
        "checked_at": datetime.now(timezone.utc),
        "runtime_seconds": round(monotonic() - started, 3),
        "message": (
            "Priority US OHLC cache-only continuity audit completed."
            if status == "completed"
            else "Priority US OHLC cache-only audit stopped at its runtime budget."
            if stopped_reason == "runtime_budget_exhausted"
            else "Priority US OHLC Shared-platform reconcile left unresolved coverage."
        ),
    }


__all__ = [
    "PRIORITY_BAR_COUNT",
    "PRIORITY_TIMEFRAME",
    "PRIORITY_US_INDEX_SYMBOLS",
    "list_us_priority_ohlc_symbols",
    "reconcile_us_priority_ohlc",
]
