from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import monotonic
from typing import Callable, Iterable

from app.utils.owner_checkpoint import OwnerWork, OwnerOutcomeUnknown

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import PortfolioHolding, USWatchlistGroup, USWatchlistItem
from app.db.session import SessionLocal
from app.portfolio.service import normalize_market
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import build_us_daily_operation_rollout_state
from app.us_market.daily_market_state import expected_us_completed_daily_state
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
    ordered: dict[str, None] = dict.fromkeys(list_us_priority_ohlc_critical_symbols(db))

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


def list_us_priority_ohlc_critical_symbols(db: Session) -> tuple[str, ...]:
    """Return the priority targets that must be audited on every scheduler run."""

    ordered: dict[str, None] = {
        normalize_us_symbol(symbol): None for symbol in PRIORITY_US_INDEX_SYMBOLS
    }
    holding_rows = (
        db.query(PortfolioHolding.symbol)
        .filter(func.lower(func.trim(PortfolioHolding.market)) == normalize_market("US"))
        .filter(PortfolioHolding.is_active.is_(True))
        .order_by(PortfolioHolding.symbol.asc())
        .all()
    )
    for row in holding_rows:
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
    required_symbols: Iterable[str] | None = None,
    continuation_remaining_count: int | None = None,
    continuation=None,
    resume_state=None,
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
    if continuation_remaining_count is not None and continuation_remaining_count < 1:
        raise ValueError("continuation_remaining_count must be positive.")

    decision_time = requested_at or datetime.now(timezone.utc)
    expected_date = to_date or expected_us_completed_daily_state(now=decision_time).expected_trade_date

    resolved_session_factory = session_factory or SessionLocal
    resolved_platform_factory = platform_factory or USDailyOhlcvPlatform
    universe_db = resolved_session_factory()
    try:
        base_universe_symbols = list_us_priority_ohlc_symbols(universe_db)
        normalized_required_symbols = tuple(
            dict.fromkeys(
                symbol
                for raw_symbol in required_symbols or ()
                if (symbol := normalize_us_symbol(raw_symbol))
            )
        )
        universe_symbols = tuple(
            dict.fromkeys((*base_universe_symbols, *normalized_required_symbols))
        )
        base_critical_symbols = list_us_priority_ohlc_critical_symbols(universe_db)
        critical_symbols = tuple(
            symbol
            for symbol in dict.fromkeys(
                (*base_critical_symbols, *normalized_required_symbols)
            )
            if symbol in universe_symbols
        )
    finally:
        universe_db.close()
    rotatable_symbols = tuple(
        symbol for symbol in universe_symbols if symbol not in critical_symbols
    )
    # When the critical prefix fills the entire bound, a durable cursor must
    # also rotate that prefix; otherwise later critical/watchlist targets starve.
    pinned_symbols = critical_symbols
    if len(critical_symbols) >= max_symbols:
        pinned_symbols = ()
        rotatable_symbols = critical_symbols + rotatable_symbols
    normalized_cursor = normalize_us_symbol(cursor_symbol)
    if normalized_cursor and normalized_cursor in rotatable_symbols:
        cursor_index = rotatable_symbols.index(normalized_cursor)
        rotated_symbols = (
            rotatable_symbols[cursor_index + 1 :]
            + rotatable_symbols[: cursor_index + 1]
        )
    else:
        rotated_symbols = rotatable_symbols
    remaining = min(continuation_remaining_count or len(rotatable_symbols), len(rotatable_symbols))
    rotated_symbols = rotated_symbols[:remaining]
    symbols = pinned_symbols + rotated_symbols
    run_symbols = symbols[:max_symbols]
    identity = dict(contract=repr(PRIORITY_DAILY_RESEARCH_CONTRACT), date=expected_date.isoformat(),
        release=expected_us_completed_daily_state(now=decision_time).expected_trade_date.isoformat(),
        universe=list(universe_symbols),
        budget=dict(symbols=max_symbols, calls=max_external_calls, runtime=max_runtime_seconds, attempts=max_provider_attempts),
        options=[list(critical_symbols), list(normalized_required_symbols), normalized_cursor,
                 continuation_remaining_count, repair])
    work = OwnerWork("us_priority_symbols", identity, list(run_symbols),
        continuation=continuation, resume_state=resume_state,
        context={"rotatable": list(rotatable_symbols), "remaining": remaining, "cursor": normalized_cursor or None,
                 "stopped_reason": "complete_scan"})
    run_symbols = tuple(work.state["items"])
    operation_rollout = (
        build_us_daily_operation_rollout_state(
            symbols=run_symbols,
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
    tick = monotonic()
    outcomes = [row["outcome"] for row in work.state["results"]]
    unresolved = [row["unresolved"] for row in outcomes if row["unresolved"] is not None]
    errors = [row["error"] for row in outcomes if row["error"] is not None]
    unknown_usage = any(row["usage_unknown"] for row in outcomes)
    stopped_reason = work.state["context"]["stopped_reason"]
    last_processed_symbol = work.state["context"]["cursor"]
    work.notify("save")
    work.notify("checkpoint")
    for index, symbol in enumerate(run_symbols[len(work.state["results"]):], start=len(work.state["results"]) + 1):
        if unknown_usage:
            break
        if work.state["elapsed"] + monotonic() - tick >= max_runtime_seconds:
            stopped_reason = "runtime_budget_exhausted"
            break
        if progress_callback is not None:
            progress_callback(index - 1, max(len(run_symbols), 1), f"Checking priority US OHLC {symbol}.")
        remaining_external_calls = max_external_calls - work.state["totals"]["calls"]
        reserved = min(max_provider_attempts, remaining_external_calls) if repair else 0
        # Reserve before opening the chart Session; never write the Job ledger
        # while an opaque Shared read/ensure scope still holds a transaction.
        work.begin(reserved)
        error = None
        unresolved_item = None
        history_satisfied = False
        repaired = False
        used = 0
        acquiring = False
        try:
            chart_db = resolved_session_factory()
        except Exception as exc:
            raise OwnerOutcomeUnknown("US_PRIORITY_SESSION_OPEN_UNKNOWN") from exc
        try:
            platform = resolved_platform_factory(chart_db)
            platform_result = platform.read(symbol=symbol,
                bars=PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
                to_date=to_date, now=requested_at)
            history_satisfied = bool(platform_result.temporal_postcondition_satisfied
                and platform_result.coverage_postcondition_satisfied)
            if not history_satisfied and repair and reserved > 0:
                acquiring = True
                platform_result = platform.ensure_history_coverage(symbol=symbol,
                    bars=PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
                    to_date=to_date, now=requested_at, max_provider_calls=reserved)
                actual = (platform_result.result.acquisition.external_calls
                    if platform_result.result.acquisition is not None else None)
                if type(actual) is not int or not 0 <= actual <= reserved:
                    raise RuntimeError("US_PRIORITY_PROVIDER_USAGE_UNKNOWN")
                used = actual
                history_satisfied = bool(platform_result.temporal_postcondition_satisfied
                    and platform_result.coverage_postcondition_satisfied)
                repaired = history_satisfied
            elif not history_satisfied and repair:
                stopped_reason = "external_call_budget_exhausted"
        except Exception as exc:
            try:
                chart_db.rollback()
            except Exception as rollback_exc:
                raise OwnerOutcomeUnknown("US_PRIORITY_ROLLBACK_UNKNOWN") from rollback_exc
            if isinstance(exc, SQLAlchemyError):
                raise OwnerOutcomeUnknown("US_PRIORITY_PERSISTENCE_UNKNOWN") from exc
            error = {"symbol": symbol, "error_type": type(exc).__name__, "message": str(exc)}
            errors.append(error)
            if acquiring:
                used = reserved  # Unknown consumption never refunds admission.
                unknown_usage = True
            stopped_reason = "provider_usage_unknown" if acquiring else "per_symbol_failure"
        finally:
            try:
                chart_db.close()
            except Exception as exc:
                raise OwnerOutcomeUnknown("US_PRIORITY_SESSION_CLOSE_UNKNOWN") from exc
        if error is None and not history_satisfied:
            unresolved_item = {"symbol": symbol,
                "coverage_status": platform_result.projection.get("coverage_status"),
                "latest_trade_date": platform_result.projection.get("latest_trade_date"),
                "expected_trade_date": platform_result.projection.get("expected_trade_date"),
                "reason": "shared_core_postcondition_unsatisfied" if repair else "repair_not_requested"}
            unresolved.append(unresolved_item)
            stopped_reason = "shared_core_postcondition_unsatisfied"
        rotated = symbol in rotatable_symbols
        if rotated:
            last_processed_symbol = symbol
        work.state["context"].update(cursor=last_processed_symbol, stopped_reason=stopped_reason)
        work.state["elapsed"] += monotonic() - tick
        tick = monotonic()
        work.finish(dict(checked=1, satisfied=int(history_satisfied), repaired=int(repaired),
                         calls=used, rotated=int(rotated)),
                    dict(error=error, unresolved=unresolved_item, usage_unknown=unknown_usage))
        work.notify("save")
        work.notify("checkpoint")
        if progress_callback is not None:
            progress_callback(index, max(len(run_symbols), 1), f"Checked {index}/{len(run_symbols)} priority US symbols.")
    checked_count = work.state["totals"]["checked"]
    satisfied_count = work.state["totals"]["satisfied"]
    repaired_count = work.state["totals"]["repaired"]
    provider_call_count = work.state["totals"]["calls"]
    rotated_checked = work.state["totals"]["rotated"]

    if (
        stopped_reason in {"complete_scan", "shared_core_postcondition_unsatisfied"}
        and len(run_symbols) < len(symbols)
    ):
        stopped_reason = "symbol_budget_exhausted"
    status = (
        "completed"
        if checked_count == len(universe_symbols) and not unresolved and not errors
        else "partial"
    )
    return {
        "status": status,
        "dataset_id": PRIORITY_DAILY_RESEARCH_CONTRACT.dataset_id,
        "scope": "indices+active_holdings+enabled_watchlist+required_consumers",
        "required_consumer_symbols": list(normalized_required_symbols),
        "critical_symbol_count": len(critical_symbols),
        "rotatable_symbol_count": len(rotatable_symbols),
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
        "universe_count": len(universe_symbols),
        "expected_trade_date": expected_date.isoformat(),
        "run_target_count": len(run_symbols),
        "checked_count": checked_count,
        "satisfied_count": satisfied_count,
        "repair_available": True,
        "repair_requested": repair,
        "repaired_count": repaired_count,
        "external_call_count": None if unknown_usage else provider_call_count,
        "external_call_budget_used": provider_call_count,
        "provider_call_count": None if unknown_usage else provider_call_count,
        "unresolved_count": max(len(universe_symbols) - satisfied_count, 0),
        "unscanned_count": max(len(universe_symbols) - checked_count, 0),
        "continuation_remaining_count": max(remaining - rotated_checked, 0),
        "continuation_required": bool(
            repair and rotated_checked > 0 and remaining > rotated_checked
            and not errors and not unresolved and satisfied_count == checked_count
        ),
        "unresolved_sample": unresolved[:20],
        "error_count": len(errors),
        "errors": errors[:10],
        "stopped_reason": stopped_reason,
        "cursor_symbol": last_processed_symbol,
        "checked_at": datetime.now(timezone.utc),
        "runtime_seconds": round(work.state["elapsed"] + monotonic() - tick, 3),
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
    "list_us_priority_ohlc_critical_symbols",
    "list_us_priority_ohlc_symbols",
    "reconcile_us_priority_ohlc",
]
