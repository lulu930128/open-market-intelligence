from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import monotonic
from typing import Callable

from sqlalchemy.orm import Session

from app.db.models import PortfolioHolding, USWatchlistGroup, USWatchlistItem
from app.db.session import SessionLocal
from app.market_data.rollout import CapabilityRolloutMode
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import build_us_daily_acquisition_rollout_state
from app.us_market.symbols import normalize_us_symbol


PRIORITY_US_INDEX_SYMBOLS = (
    "^GSPC",
    "^DJI",
    "^IXIC",
    "^SOX",
    "^NDX",
    "^VIX",
)


@dataclass(frozen=True, slots=True)
class USPriorityDailyResearchContract:
    """Executable coverage intent for the bounded US priority universe."""

    dataset_id: str = "us.daily.ohlcv.priority_research"
    timeframe: str = "daily"
    minimum_bar_count: int = 260


PRIORITY_DAILY_RESEARCH_CONTRACT = USPriorityDailyResearchContract()
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
    max_symbols: int = 20,
    max_external_calls: int = 20,
    max_provider_attempts: int = 2,
    cursor_symbol: str | None = None,
    to_date: date | None = None,
    requested_at: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    session_factory: SessionFactory | None = None,
    platform_factory: PlatformFactory | None = None,
    repair: bool = True,
) -> dict:
    """Run a bounded priority read and optional explicit Shared-platform repair."""

    if max_runtime_seconds <= 0:
        raise ValueError("max_runtime_seconds must be greater than 0.")
    if max_symbols <= 0:
        raise ValueError("max_symbols must be greater than 0.")
    if max_external_calls <= 0:
        raise ValueError("max_external_calls must be greater than 0.")
    if max_provider_attempts <= 0 or max_provider_attempts > 2:
        raise ValueError("max_provider_attempts must be between 1 and 2.")

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
    run_symbols = symbols[:max_symbols]
    operation_rollout = (
        build_us_daily_acquisition_rollout_state(
            mode=CapabilityRolloutMode.CANARY,
            symbols=",".join(run_symbols),
            max_symbols=max(len(run_symbols), 1),
            changed_at=requested_at,
        )
        if run_symbols and platform_factory is None
        else None
    )
    if platform_factory is None:
        def _rollout_platform_factory(db: Session) -> USDailyOhlcvPlatform:
            return USDailyOhlcvPlatform(
                db,
                rollout_state=operation_rollout,
            )

        resolved_platform_factory = _rollout_platform_factory
    started = monotonic()
    checked_count = 0
    satisfied_count = 0
    repaired_count = 0
    provider_call_count = 0
    unresolved: list[dict] = []
    errors: list[dict] = []
    stopped_reason = "complete_scan"
    last_processed_symbol = normalized_cursor or None

    for index, symbol in enumerate(run_symbols, start=1):
        if monotonic() - started >= max_runtime_seconds:
            stopped_reason = "runtime_budget_exhausted"
            break
        if progress_callback is not None:
            progress_callback(
                index - 1,
                max(len(run_symbols), 1),
                f"Checking priority US OHLC {symbol}.",
            )

        chart_db = resolved_session_factory()
        try:
            platform = resolved_platform_factory(chart_db)
            platform_result = platform.read(
                symbol=symbol,
                bars=PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
                to_date=to_date,
                now=requested_at,
            )
            history_satisfied = bool(
                platform_result.temporal_postcondition_satisfied
                and platform_result.coverage_postcondition_satisfied
            )
            remaining_external_calls = max_external_calls - provider_call_count
            if not history_satisfied and repair and remaining_external_calls > 0:
                platform_result = platform.ensure_history_coverage(
                    symbol=symbol,
                    bars=PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
                    to_date=to_date,
                    now=requested_at,
                    max_provider_calls=min(
                        max_provider_attempts,
                        remaining_external_calls,
                    ),
                )
                provider_call_count += int(
                    platform_result.result.acquisition.external_calls
                    if platform_result.result.acquisition is not None
                    else 0
                )
                history_satisfied = bool(
                    platform_result.temporal_postcondition_satisfied
                    and platform_result.coverage_postcondition_satisfied
                )
                if history_satisfied:
                    repaired_count += 1
            elif not history_satisfied and repair:
                stopped_reason = "external_call_budget_exhausted"
        except Exception as exc:
            chart_db.rollback()
            errors.append(
                {
                    "symbol": symbol,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            checked_count += 1
            last_processed_symbol = symbol
            stopped_reason = "per_symbol_failure"
            continue
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
                max(len(run_symbols), 1),
                f"Checked {index}/{len(run_symbols)} priority US symbols.",
            )

    if (
        stopped_reason in {"complete_scan", "shared_core_postcondition_unsatisfied"}
        and len(run_symbols) < len(symbols)
    ):
        stopped_reason = "symbol_budget_exhausted"
    status = (
        "completed"
        if checked_count == len(symbols) and not unresolved and not errors
        else "partial"
    )
    return {
        "status": status,
        "dataset_id": PRIORITY_DAILY_RESEARCH_CONTRACT.dataset_id,
        "scope": "indices+active_holdings+enabled_watchlist",
        "contract": {
            "timeframe": PRIORITY_DAILY_RESEARCH_CONTRACT.timeframe,
            "bars": PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
            "minimum_observation_count": (
                PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count
            ),
            "continuity": "all completed US sessions from first available row",
            "history": (
                "provider-coherent completed-session Daily bars; requests below the "
                "minimum remain partial with explicit coverage limitations"
            ),
        },
        "universe_count": len(symbols),
        "run_target_count": len(run_symbols),
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
            else "Priority US OHLC reconcile exhausted its symbol budget."
            if stopped_reason == "symbol_budget_exhausted"
            else "Priority US OHLC reconcile exhausted its external-call budget."
            if stopped_reason == "external_call_budget_exhausted"
            else "Priority US OHLC Shared-platform reconcile left unresolved coverage."
        ),
    }


__all__ = [
    "PRIORITY_DAILY_RESEARCH_CONTRACT",
    "PRIORITY_US_INDEX_SYMBOLS",
    "USPriorityDailyResearchContract",
    "list_us_priority_ohlc_symbols",
    "reconcile_us_priority_ohlc",
]
