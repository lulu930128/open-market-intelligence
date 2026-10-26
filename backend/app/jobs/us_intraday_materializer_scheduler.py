"""Scheduler registration for feature-off US Quote／Intraday materialization."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import logging
import math
import re
import time
from threading import Lock, Thread, current_thread
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import PortfolioHolding, USWatchlistItem
from app.us_market.intraday_maintenance import prune_expired_us_quote_snapshots
from app.us_market.source_health import snapshot_us_source_health
from app.us_market.intraday_materializer import (
    US_RECURRING_MATERIALIZER_PROFILE,
    materialize_us_intraday_capability,
    reconcile_us_intraday_session,
    resolve_us_eod_universe,
    expire_us_intraday_obligations,
    read_us_eod_job_snapshot,
)
from app.us_market.active_equity_targets import active_us_equity_viewer_symbols
from app.us_market.trading_calendar import US_MARKET_TIMEZONE
from app.us_market.historical_intraday import completed_intraday_window
from app.us_market.symbols import US_INDEX_SYMBOLS, normalize_us_symbol
from app.us_market.session_policy import us_session_for_timestamp
from app.us_market.trading_calendar import is_us_trading_day
from app.market_data.contracts import MarketSession


logger = logging.getLogger(__name__)
_SCHEDULED_US_ACTIVE_LANE_LOCK = Lock()
_SCHEDULED_US_CANARY_LANE_LOCK = Lock()
_SCHEDULED_US_INDEX_LANE_LOCK = Lock()
_INDEX_BATCH_STATE_LOCK = Lock()
_INDEX_BATCH_OFFSETS = {"quote.snapshot": 0, "intraday.bars": 0}
_READ_MODEL_PUBLISH_LOCK = Lock()
_READ_MODEL_PUBLISH_MAX_IN_FLIGHT = 4
_READ_MODEL_PUBLISH_CLOSED = False
_READ_MODEL_PUBLISH_PAUSE = None
_READ_MODEL_PUBLISH_COMPLETED = 0
_READ_MODEL_PUBLISH_FAILURES = 0
_READ_MODEL_PUBLISH_SKIPPED = 0
_READ_MODEL_PUBLISH_LAST_EXIT_AT: float | None = None


@dataclass
class _ReadModelPublishTask:
    thread: Thread | None = None
    session: Any = None
    session_closed: bool = False
    finished: bool = False
    failed: bool = False
    ownership_failed: bool = False
    skipped: bool = False


_READ_MODEL_PUBLISH_TASKS: dict[str, _ReadModelPublishTask] = {}


@dataclass(frozen=True)
class PublisherDrainResult:
    state: str
    admission_closed: bool
    retained_symbols: tuple[str, ...]
    unclosed_sessions: tuple[str, ...]
    unknown_symbols: tuple[str, ...]
    completed: int
    failures: int  # Outcome telemetry; closed/finished failures do not block quiescence.
    skipped: int
    ownership_failures: int = 0
    last_exit_observed_at: float | None = None

    @property
    def drained(self) -> bool:
        return (self.state == "drained" and self.admission_closed
                and not self.retained_symbols and not self.ownership_failures
                and not self.unclosed_sessions and not self.unknown_symbols)


def require_intraday_publisher_admission() -> None:
    with _READ_MODEL_PUBLISH_LOCK:
        if _READ_MODEL_PUBLISH_CLOSED:
            raise RuntimeError("Publisher drain is terminal; new process lifecycle required")


def begin_intraday_publisher_drain() -> None:
    global _READ_MODEL_PUBLISH_CLOSED
    with _READ_MODEL_PUBLISH_LOCK:
        _READ_MODEL_PUBLISH_CLOSED = True


def pause_publishers_if_idle():
    global _READ_MODEL_PUBLISH_PAUSE
    with _READ_MODEL_PUBLISH_LOCK:
        if _READ_MODEL_PUBLISH_CLOSED or _READ_MODEL_PUBLISH_PAUSE is not None:
            raise RuntimeError("Publisher quiescence unavailable")
        _reap_intraday_publishers_locked()
        if _READ_MODEL_PUBLISH_TASKS:
            return None
        _READ_MODEL_PUBLISH_PAUSE = object()
        return _READ_MODEL_PUBLISH_PAUSE


def resume_publishers(lease):
    global _READ_MODEL_PUBLISH_PAUSE
    with _READ_MODEL_PUBLISH_LOCK:
        if lease is not _READ_MODEL_PUBLISH_PAUSE or _READ_MODEL_PUBLISH_CLOSED:
            raise RuntimeError("Invalid publisher quiescence lease")
        _READ_MODEL_PUBLISH_PAUSE = None


def _reap_intraday_publishers_locked() -> None:
    global _READ_MODEL_PUBLISH_COMPLETED, _READ_MODEL_PUBLISH_FAILURES, _READ_MODEL_PUBLISH_SKIPPED
    global _READ_MODEL_PUBLISH_LAST_EXIT_AT
    for symbol, task in tuple(_READ_MODEL_PUBLISH_TASKS.items()):
        # A worker's finally is not thread exit. Never drop a live/unknown owner
        # or a Session whose close failed, even if its thread has exited.
        if (task.thread is None or task.thread.ident is None or task.thread.is_alive()
                or not task.finished or (task.session is not None and not task.session_closed)):
            continue
        task.thread.join(timeout=0)
        _READ_MODEL_PUBLISH_LAST_EXIT_AT = time.monotonic()
        _READ_MODEL_PUBLISH_COMPLETED += 1
        _READ_MODEL_PUBLISH_FAILURES += int(task.failed)
        _READ_MODEL_PUBLISH_SKIPPED += int(task.skipped)
        del _READ_MODEL_PUBLISH_TASKS[symbol]


def intraday_publisher_drain_status() -> PublisherDrainResult:
    with _READ_MODEL_PUBLISH_LOCK:
        _reap_intraday_publishers_locked()
        retained = tuple(sorted(_READ_MODEL_PUBLISH_TASKS))
        unclosed = tuple(sorted(symbol for symbol, task in _READ_MODEL_PUBLISH_TASKS.items()
                                if task.session is not None and not task.session_closed))
        unknown = tuple(sorted(symbol for symbol, task in _READ_MODEL_PUBLISH_TASKS.items()
                               if not task.finished and (task.thread is None or not task.thread.is_alive())
                               and not task.failed))
        failures = _READ_MODEL_PUBLISH_FAILURES + sum(task.failed for task in _READ_MODEL_PUBLISH_TASKS.values())
        ownership_failures = sum(task.ownership_failed for task in _READ_MODEL_PUBLISH_TASKS.values())
        state = ("error" if ownership_failures else "unknown" if unknown else "waiting" if retained
                 else "drained" if _READ_MODEL_PUBLISH_CLOSED else "open")
        return PublisherDrainResult(state, _READ_MODEL_PUBLISH_CLOSED, retained, unclosed, unknown,
                                    _READ_MODEL_PUBLISH_COMPLETED, failures, _READ_MODEL_PUBLISH_SKIPPED,
                                    ownership_failures, _READ_MODEL_PUBLISH_LAST_EXIT_AT)


async def drain_intraday_publishers(*, deadline: float) -> PublisherDrainResult:
    if not math.isfinite(deadline):
        raise ValueError("Publisher drain deadline must be finite")
    begin_intraday_publisher_drain()
    while True:
        result = intraday_publisher_drain_status()
        if not result.retained_symbols:
            if result.last_exit_observed_at is not None and result.last_exit_observed_at > deadline:
                return replace(result, state="timeout")
            return result
        with _READ_MODEL_PUBLISH_LOCK:
            all_exited = all(task.thread is None or not task.thread.is_alive()
                             for task in _READ_MODEL_PUBLISH_TASKS.values())
        if all_exited:
            # A thread may exit between the first status and this observation.
            # Reap that proven completion before classifying an orphan.
            result = intraday_publisher_drain_status()
            if result.retained_symbols:
                return result  # Waiting cannot repair failed/unknown ownership.
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return replace(result, state="timeout" if result.state == "waiting" else result.state)
        # Poll actual Thread completion, with a nonblocking join above; no
        # executor/helper thread or cancellable wrapper stands in for its exit.
        await asyncio.sleep(min(0.01, remaining))

# One opt-in equity budget, including canary, across both recurring capabilities.
# This is scheduler state, not another producer, queue, or durable repair ledger.
_EQUITY_SELECTION_LOCK = Lock()
_EQUITY_WINDOW_SECONDS = 60
_EQUITY_MAX_SYMBOLS = 2
_EQUITY_MAX_RESERVATIONS = 4
_BACKGROUND_TURNS = ("portfolio", "portfolio", "watchlist", "canary")


@dataclass
class _EquityRotation:
    cursors: dict[str, int] = field(default_factory=dict)
    background_turn: int = 0
    single_slot_turn: int = 0
    symbols: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    canary_symbols: tuple[str, ...] = ()
    capacity: int = 0
    consumed: set[str] = field(default_factory=set)
    reservations: int = 0
    # Restart cannot immediately refill quota from a previous process.
    not_before: float = field(
        default_factory=lambda: time.monotonic() + _EQUITY_WINDOW_SECONDS
    )
    counts: dict[str, int] = field(default_factory=dict)


_EQUITY_ROTATION = _EquityRotation()


def _equity_source_symbols(*, now: datetime) -> dict[str, tuple[str, ...]]:
    """Read eligible account intent; never persist or acquire market data."""
    raw = {"active_viewer": sorted(active_us_equity_viewer_symbols(now=now))}
    explicit = settings.scheduler_us_active_equity_materializer_symbols
    if explicit.strip():
        raw["explicit"] = explicit.split(",")
    raw.update({"portfolio": [], "watchlist": [], "canary": []})
    db = SessionLocal()
    try:
        raw["portfolio"] = [
            row.symbol for row in db.query(PortfolioHolding).filter(
                PortfolioHolding.market == "US",
                PortfolioHolding.is_active.is_(True),
                PortfolioHolding.quantity != 0,
            ).order_by(PortfolioHolding.id.asc()).all()
            if row.quantity is not None and math.isfinite(row.quantity)
        ]
        raw["watchlist"] = [
            row.symbol for row in db.query(USWatchlistItem).filter(
                USWatchlistItem.enabled.is_(True),
            ).order_by(USWatchlistItem.priority.asc(), USWatchlistItem.id.asc()).all()
        ]
    finally:
        db.close()
    raw["canary"] = settings.scheduler_us_intraday_materializer_symbols.split(",")
    seen: set[str] = set()
    sources: dict[str, tuple[str, ...]] = {}
    for source, values in raw.items():
        accepted = []
        for value in values:
            token = str(value or "").strip().upper()
            # Reject malformed tokens before the permissive legacy normalizer
            # can turn e.g. 'AAPL garbage' into a different acquisition intent.
            if re.fullmatch(r"[A-Z0-9][A-Z0-9.$-]{0,31}", token) is None:
                continue
            symbol = normalize_us_symbol(token)
            if symbol in US_INDEX_SYMBOLS or symbol in accepted:
                continue
            if source != "canary" and symbol in seen:
                continue
            seen.add(symbol)
            accepted.append(symbol)
        sources[source] = tuple(accepted)
    return sources


def _select_equity_batch(
    state: _EquityRotation, sources: dict[str, tuple[str, ...]], capacity: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Viewer first, bounded background progress, round robin inside each tier."""
    if capacity <= 0:
        return (), ()
    # An explicit target must not wait for an entire watchlist traversal.
    # Keep the legacy sequence unchanged when the explicit tier is empty.
    background_turns = (("explicit",) + _BACKGROUND_TURNS
                        if sources.get("explicit") else _BACKGROUND_TURNS)
    selected: list[str] = []
    owners: list[str] = []

    def take(source: str) -> bool:
        values = sources[source]
        if not values:
            return False
        start = state.cursors.get(source, 0) % len(values)
        for offset in range(len(values)):
            symbol = values[(start + offset) % len(values)]
            if symbol not in selected:
                selected.append(symbol)
                owners.append(next(
                    owner for owner, candidates in sources.items() if symbol in candidates
                ))
                state.cursors[source] = (start + offset + 1) % len(values)
                return True
        return False

    has_background = any(sources[source] for source in set(background_turns))
    viewer_turn = capacity > 1 or not has_background or state.single_slot_turn % 2 == 0
    if viewer_turn:
        take("active_viewer")
    if capacity == 1:
        state.single_slot_turn = (state.single_slot_turn + 1) % 2
    while len(selected) < capacity:
        added = False
        for _ in background_turns:
            source = background_turns[state.background_turn % len(background_turns)]
            state.background_turn = (state.background_turn + 1) % len(background_turns)
            if take(source):
                added = True
                break
        if not added and not take("active_viewer"):
            break
    return tuple(selected), tuple(owners)


def _collect_rotating_equities(capability: str, *, now: datetime | None) -> dict[str, Any]:
    """All opt-in equity job triggers share one reservation and producer owner."""
    requested_at = now or datetime.now(timezone.utc)
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    def skipped(reason: str) -> dict[str, Any]:
        return {"status": "skipped", "reason": reason, "results": [],
                "requested_count": 0, "refreshed_count": 0, "failed_count": 0,
                "external_call_count": 0, "reserved_external_call_count": 0,
                "duration_ms": 0, "lane_id": "equity_active"}

    if not is_us_trading_day(requested_at.astimezone(US_MARKET_TIMEZONE).date()) or us_session_for_timestamp(requested_at) not in {
        MarketSession.PRE_OPEN, MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION, MarketSession.POST_CLOSE,
    }:
        return skipped("outside_us_intraday_acquisition_window")
    if not _EQUITY_SELECTION_LOCK.acquire(blocking=False):
        return skipped("materializer_run_in_flight")
    try:
        state = _EQUITY_ROTATION
        tick = time.monotonic()
        if _SCHEDULED_US_ACTIVE_LANE_LOCK.locked():
            return skipped("materializer_run_in_flight")
        if tick >= state.not_before:
            # Never exceed either original equity lane's configured bounds.
            capacity = min(
                _EQUITY_MAX_SYMBOLS,
                settings.scheduler_us_active_equity_materializer_max_symbols,
                settings.scheduler_us_intraday_materializer_max_symbols,
                settings.scheduler_us_active_equity_materializer_max_external_calls,
                settings.scheduler_us_intraday_materializer_max_external_calls,
            )
            sources = _equity_source_symbols(now=requested_at)
            state.symbols, state.sources = _select_equity_batch(state, sources, capacity)
            state.canary_symbols = tuple(
                symbol for symbol in state.symbols if symbol in sources["canary"]
            )
            state.capacity = capacity
            state.counts = {source: len(values) for source, values in sources.items()}
            state.consumed.clear()
            # Reserve both capabilities together at the fixed window boundary.
            # The second capability consumes its reservation, never extends it.
            state.reservations = 2 * len(state.symbols)
            state.not_before = tick + _EQUITY_WINDOW_SECONDS
        if not state.symbols:
            return skipped("equity_rotation_cooldown_or_empty")
        if capability in state.consumed:
            return skipped("equity_capability_already_reserved")
        reservation = len(state.symbols)
        if state.reservations > _EQUITY_MAX_RESERVATIONS:
            return skipped("equity_external_call_budget_exhausted")
        # Reserve before IO. Unknown errors/cache noops never refund quota.
        state.consumed.add(capability)
        selected_counts = {source: state.sources.count(source) for source in state.counts}
        selected_counts["canary"] = len(state.canary_symbols)
        selection = {
            "symbols": list(state.symbols), "sources": list(state.sources),
            "canary_probe_symbols": list(state.canary_symbols),
            "canary_role_may_overlap_primary_source": True,
            "eligible_counts": dict(state.counts),
            "count_semantics": "exclusive_priority_owner_except_overlapping_canary_role",
            "deferred_counts": {
                source: count - selected_counts[source]
                for source, count in state.counts.items()
            },
            "deferred_reason": "bounded_priority_round_robin_capacity",
            "window_seconds": _EQUITY_WINDOW_SECONDS,
            "capacity": state.capacity, "selected_count": len(state.symbols),
            "max_symbols": _EQUITY_MAX_SYMBOLS,
            "max_external_call_reservations": _EQUITY_MAX_RESERVATIONS,
            "window_reserved_external_calls": state.reservations,
            "reserved_external_call_count": reservation,
            "budget_scope": "process_all_recurring_equity_jobs",
        }
        result = materialize_us_intraday_capability(
            capability,
            configured_symbols=",".join(state.symbols),
            max_symbols=len(state.symbols), max_provider_calls=1,
            max_external_calls=reservation, lane_id="equity_active",
            instrument_type="stock", universe_owner="scheduler_priority_round_robin",
            profile=replace(US_RECURRING_MATERIALIZER_PROFILE,
                            intraday_bars=settings.scheduler_us_intraday_materializer_bars),
            now=requested_at, run_lock=_SCHEDULED_US_ACTIVE_LANE_LOCK,
            selection_metadata=selection,
        )
        return result
    finally:
        _EQUITY_SELECTION_LOCK.release()


_EOD_DIAGNOSTICS_LOCK = Lock()
_EOD_LAST_DECISION: dict[str, Any] = {}
_EOD_DURABLE_SNAPSHOT: dict[str, Any] = {"snapshot_available": False, "reason": "not_loaded"}
_EOD_SCHEDULER: Any = None
_EOD_JOB_ID = "us_intraday_completed_session_reconciliation"


def us_eod_runtime_summary() -> dict[str, Any]:
    """Effective in-process configuration and bounded background snapshot; no IO."""
    universe = resolve_us_eod_universe(
        settings.scheduler_us_intraday_reconciliation_symbols,
        max_symbols=min(2, settings.scheduler_us_intraday_reconciliation_max_symbols),
    )
    with _EOD_DIAGNOSTICS_LOCK:
        decision = deepcopy(_EOD_LAST_DECISION)
        durable = deepcopy(_EOD_DURABLE_SNAPSHOT)
    enabled = bool(settings.enable_us_intraday_reconciliation)
    lookup = getattr(_EOD_SCHEDULER, "get_job", None)
    registered = False if _EOD_SCHEDULER is None else lookup(_EOD_JOB_ID) is not None if callable(lookup) else None
    return {
        "contract_version": "omi.us.eod.runtime.v1", "enabled": enabled,
        "configuration_source": "effective_process_settings",
        "configuration_status": "disabled" if not enabled else "invalid_configuration" if not universe["scope_valid"] else "configured" if universe["symbols"] else "empty_scope",
        "symbols": universe["symbols"], "universe": universe,
        "scheduler_registered": registered,
        "max_symbols_per_run": min(2, settings.scheduler_us_intraday_reconciliation_max_symbols),
        "max_external_calls_per_run": min(2, settings.scheduler_us_intraday_reconciliation_max_external_calls),
        "max_attempts_per_target": 3, "cooldown_seconds": 900,
        "history_calendar_days": 5, "budget_scope": "durable_job_run",
        "diagnostic_source": "background_canonical_reread_and_job_run_snapshot",
        "snapshot_available": bool(decision), "last_decision": decision,
        "last_decision_in_process_only": True, "persisted_jobs_snapshot": durable,
        "coverage_is_live_read": False,
    }


def _record_eod_decision(result: dict[str, Any]) -> dict[str, Any]:
    with _EOD_DIAGNOSTICS_LOCK:
        _EOD_LAST_DECISION.clear()
        _EOD_LAST_DECISION.update(deepcopy(result))
    return result


def _load_eod_durable_snapshot(*, now: datetime) -> None:
    snapshot = read_us_eod_job_snapshot(
        configured_symbols=settings.scheduler_us_intraday_reconciliation_symbols,
        max_symbols=min(2, settings.scheduler_us_intraday_reconciliation_max_symbols),
        now=now, session_factory=SessionLocal,
    )
    with _EOD_DIAGNOSTICS_LOCK:
        _EOD_DURABLE_SNAPSHOT.clear()
        _EOD_DURABLE_SNAPSHOT.update(snapshot)


def reconcile_us_completed_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    """Latest completed date plus bounded recoverable backlog, explicit scope only."""
    requested_at = now or datetime.now(timezone.utc)
    if not settings.enable_us_intraday_reconciliation:
        return _record_eod_decision({"status": "skipped", "reason": "disabled", "checked_at": requested_at.isoformat()})
    universe = resolve_us_eod_universe(
        settings.scheduler_us_intraday_reconciliation_symbols,
        max_symbols=min(2, settings.scheduler_us_intraday_reconciliation_max_symbols))
    if not universe["scope_valid"] or not universe["symbols"]:
        return _record_eod_decision({
            "status": "blocked", "reason": "invalid_configuration" if not universe["scope_valid"] else "empty_scope",
            "universe": universe, "checked_at": requested_at.isoformat(),
        })
    try:
        expired = expire_us_intraday_obligations(
            configured_symbols=settings.scheduler_us_intraday_reconciliation_symbols,
            now=requested_at,
            max_symbols=min(2, settings.scheduler_us_intraday_reconciliation_max_symbols),
        )
    except Exception as exc:
        logger.warning("US EOD ledger unavailable: %s", exc)
        return _record_eod_decision({
            "status": "blocked", "reason": "durable_ledger_unavailable",
            "error_code": str(exc) if str(exc).startswith("US_EOD_") else None,
            "error_type": type(exc).__name__, "checked_at": requested_at.isoformat(),
        })
    local_day = requested_at.astimezone(US_MARKET_TIMEZONE).date()
    days = []
    for offset in range(6):
        day = local_day - timedelta(days=offset)
        if not is_us_trading_day(day):
            continue
        try:
            _start, end = completed_intraday_window(day, now=requested_at)
        except ValueError:
            continue
        if requested_at >= end + timedelta(minutes=5):
            days.append(day)
    results = []
    reserved = 0
    limit = min(2, settings.scheduler_us_intraday_reconciliation_max_external_calls)
    for day in days:
        result = reconcile_us_intraday_session(
            configured_symbols=settings.scheduler_us_intraday_reconciliation_symbols,
            trade_date=day,
            max_symbols=min(2, settings.scheduler_us_intraday_reconciliation_max_symbols),
            max_external_calls=limit - reserved, now=requested_at,
            publish=_publish_intraday_consumer_read_models,
        )
        reserved += result["reserved_external_call_count"]
        results.extend(result["results"])
    counts: dict[str, int] = {}
    for item in results:
        reason = item.get("reason", "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    summary = {
        "checked_at": requested_at.isoformat(), "status": "success" if results and all(i.get("postcondition_satisfied") for i in results) else "partial" if results else "skipped",
        "reason": "bounded_completed_session_audit" if days else "no_eligible_completed_session",
        "trade_dates": [day.isoformat() for day in days],
        "reserved_external_call_count": reserved, "results": results,
        "job_run_count": len({i["job_id"] for i in results if i.get("job_id")}),
        "reason_counts": counts,
        "expired_obligations": expired,
        "succeeded_count": sum(bool(i.get("postcondition_satisfied")) for i in results),
        "failed_count": sum(not i.get("postcondition_satisfied") for i in results),
        "retention_policy": "dates_older_than_five_calendar_days_unfillable_no_acquisition",
    }
    _load_eod_durable_snapshot(now=requested_at)
    return _record_eod_decision(summary)


def _rotating_index_batch(capability: str) -> tuple[str, int, int]:
    configured = list(
        dict.fromkeys(
            value.strip()
            for value in settings.scheduler_us_index_quote_symbols.split(",")
            if value.strip()
        )
    )[: settings.scheduler_us_index_quote_max_symbols]
    if not configured:
        return "", 0, 60
    batch_size = min(
        settings.scheduler_us_index_quote_batch_size
        if capability == "quote.snapshot"
        else settings.scheduler_us_index_intraday_batch_size,
        len(configured),
    )
    with _INDEX_BATCH_STATE_LOCK:
        start = _INDEX_BATCH_OFFSETS[capability] % len(configured)
        batch = [
            configured[(start + offset) % len(configured)]
            for offset in range(batch_size)
        ]
    cycle_count = (len(configured) + batch_size - 1) // batch_size
    full_cycle_seconds = (
        settings.scheduler_us_quote_materializer_interval_seconds
        if capability == "quote.snapshot"
        else settings.scheduler_us_index_intraday_materializer_interval_seconds
    )
    run_interval_seconds = max(5, full_cycle_seconds // cycle_count)
    return ",".join(batch), batch_size, run_interval_seconds


def _advance_index_batch(capability: str, batch_size: int) -> None:
    configured_count = len(
        list(
            dict.fromkeys(
                value.strip()
                for value in settings.scheduler_us_index_quote_symbols.split(",")
                if value.strip()
            )
        )[: settings.scheduler_us_index_quote_max_symbols]
    )
    if configured_count == 0 or batch_size == 0:
        return
    with _INDEX_BATCH_STATE_LOCK:
        _INDEX_BATCH_OFFSETS[capability] = (
            _INDEX_BATCH_OFFSETS[capability] + batch_size
        ) % configured_count


def _equity_canary_universe() -> tuple[str, str]:
    active_symbols = set(active_us_equity_viewer_symbols())
    configured = [
        symbol.strip()
        for symbol in settings.scheduler_us_intraday_materializer_symbols.split(",")
        if symbol.strip() and symbol.strip().upper() not in active_symbols
    ]
    owner = (
        "configuration_canary_minus_active_viewers"
        if active_symbols
        else "configuration_canary"
    )
    return ",".join(configured), owner


def _active_equity_materializer_universe(
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    ordered = list(active_us_equity_viewer_symbols(now=now))
    owner_parts = ["active_viewer"] if ordered else []

    configured = settings.scheduler_us_active_equity_materializer_symbols
    # Dynamic sources are selected only by the shared opt-in rotation above.
    if configured.strip():
        ordered.extend(configured.split(","))
        owner_parts.append("configuration_dynamic")
    return ",".join(ordered), "+".join(owner_parts) or "active_equity_empty"


def collect_us_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    if settings.enable_us_dynamic_equity_materializer_universe:
        return _collect_rotating_equities("quote.snapshot", now=now)
    configured_symbols, universe_owner = _equity_canary_universe()
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_canary",
        instrument_type="stock",
        universe_owner=universe_owner,
        now=now,
        run_lock=_SCHEDULED_US_CANARY_LANE_LOCK,
    )
    logger.info(
        "US Quote materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def collect_us_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    if settings.enable_us_dynamic_equity_materializer_universe:
        return _publish_intraday_consumer_read_models(
            _collect_rotating_equities("intraday.bars", now=now)
        )
    configured_symbols, universe_owner = _equity_canary_universe()
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_canary",
        instrument_type="stock",
        universe_owner=universe_owner,
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_CANARY_LANE_LOCK,
    )
    logger.info(
        "US Intraday materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def collect_us_active_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    if settings.enable_us_dynamic_equity_materializer_universe:
        return _collect_rotating_equities("quote.snapshot", now=now)
    configured_symbols, universe_owner = _active_equity_materializer_universe(now=now)
    return materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_active_equity_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_active_equity_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_active_equity_materializer_max_external_calls,
        lane_id="equity_active",
        instrument_type="stock",
        universe_owner=universe_owner,
        now=now,
        run_lock=_SCHEDULED_US_ACTIVE_LANE_LOCK,
    )


def _publish_intraday_consumer_read_model(symbol: str) -> None:
    """Publish one cache-only projection without extending a producer job."""

    started_at = time.monotonic()
    with _READ_MODEL_PUBLISH_LOCK:
        task = _READ_MODEL_PUBLISH_TASKS.get(symbol)
        if task is None or task.thread is not current_thread():
            raise RuntimeError("Publisher requires its registered thread owner")
    db = None
    try:
        with _READ_MODEL_PUBLISH_LOCK:
            if _READ_MODEL_PUBLISH_CLOSED:
                task.skipped = True
                return
            # SessionLocal only constructs a lazy Session, with no connection or
            # SQL here. Serialize construction with the terminal admission fence.
            # Queries, rollback and close must remain outside this short lock.
            db = task.session = SessionLocal()
        from app.us_market.service import get_us_intraday_trend

        get_us_intraday_trend(
            symbol=symbol,
            session_scope="regular",
            interval="1m",
            db=db,
            bypass_read_cache=True,
        )
        logger.info(
            "US intraday read-model publish completed symbol=%s duration_ms=%s.",
            symbol,
            int((time.monotonic() - started_at) * 1000),
        )
    except BaseException as exc:
        with _READ_MODEL_PUBLISH_LOCK:
            task.failed = True
        if db is not None:
            try:
                db.rollback()
            except BaseException:
                logger.exception("US intraday publisher rollback failed symbol=%s.", symbol)
        logger.warning(
            "US intraday read-model publish failed symbol=%s error_type=%s.",
            symbol,
            type(exc).__name__,
        )
    finally:
        if db is not None:
            try:
                db.close()
            except BaseException:
                with _READ_MODEL_PUBLISH_LOCK:
                    task.failed = True
                    task.ownership_failed = True
                logger.exception("US intraday publisher close failed symbol=%s.", symbol)
            else:
                with _READ_MODEL_PUBLISH_LOCK:
                    task.session_closed = True
        with _READ_MODEL_PUBLISH_LOCK:
            task.finished = True


def _schedule_intraday_consumer_read_model(symbol: str) -> bool:
    """Start one bounded daemon publisher and deduplicate in-flight symbols."""

    with _READ_MODEL_PUBLISH_LOCK:
        _reap_intraday_publishers_locked()
        if (
            _READ_MODEL_PUBLISH_CLOSED
            or _READ_MODEL_PUBLISH_PAUSE is not None
            or symbol in _READ_MODEL_PUBLISH_TASKS
            or len(_READ_MODEL_PUBLISH_TASKS)
            >= _READ_MODEL_PUBLISH_MAX_IN_FLIGHT
        ):
            return False
        task = _ReadModelPublishTask()
        _READ_MODEL_PUBLISH_TASKS[symbol] = task
        try:
            task.thread = Thread(
                target=_publish_intraday_consumer_read_model,
                args=(symbol,),
                name=f"us-intraday-read-model-{symbol}",
                daemon=True,
            )
            task.thread.start()
        except BaseException:
            # A failed start is not proof that no thread was launched. Retain
            # the reference and fail the drain; never release uncertain ownership.
            task.failed = True
            task.ownership_failed = True
            raise
    return True


def _publish_intraday_consumer_read_models(result: dict[str, Any]) -> dict[str, Any]:
    """Schedule bounded cache-only projections after persisted producer truth."""

    successful_symbols = [
        str(item.get("symbol") or "")
        for item in result.get("results", [])
        if (item.get("status") == "success" or item.get("consumer_cache_invalidated")) and item.get("symbol")
    ]
    scheduled = [
        symbol
        for symbol in successful_symbols
        if _schedule_intraday_consumer_read_model(symbol)
    ]
    result["consumer_cache_publish_scheduled_count"] = len(scheduled)
    result["consumer_cache_publish_scheduled_symbols"] = scheduled
    result["consumer_cache_publish_deferred_symbols"] = [
        symbol for symbol in successful_symbols if symbol not in scheduled
    ]
    return result


def collect_us_active_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    if settings.enable_us_dynamic_equity_materializer_universe:
        return _publish_intraday_consumer_read_models(
            _collect_rotating_equities("intraday.bars", now=now)
        )
    configured_symbols, universe_owner = _active_equity_materializer_universe(now=now)
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_active_equity_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_active_equity_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_active_equity_materializer_max_external_calls,
        lane_id="equity_active",
        instrument_type="stock",
        universe_owner=universe_owner,
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_ACTIVE_LANE_LOCK,
    )
    return _publish_intraday_consumer_read_models(result)


def collect_us_index_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, batch_size, _run_interval = _rotating_index_batch(
        "quote.snapshot"
    )
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=max(batch_size, 1),
        max_provider_calls=2,
        max_external_calls=min(
            settings.scheduler_us_index_quote_max_external_calls,
            max(batch_size * 2, 1),
        ),
        lane_id="index_current",
        instrument_type="index",
        universe_owner="configuration_round_robin",
        now=now,
        run_lock=_SCHEDULED_US_INDEX_LANE_LOCK,
    )
    if result.get("reason") != "materializer_run_in_flight":
        _advance_index_batch("quote.snapshot", batch_size)
    logger.info(
        "US Index Quote materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def collect_us_index_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, batch_size, _run_interval = _rotating_index_batch(
        "intraday.bars"
    )
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=max(batch_size, 1),
        max_provider_calls=2,
        max_external_calls=min(
            settings.scheduler_us_index_intraday_max_external_calls,
            max(batch_size * 2, 1),
        ),
        lane_id="index_current",
        instrument_type="index",
        universe_owner="configuration_round_robin",
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_index_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_INDEX_LANE_LOCK,
    )
    if result.get("reason") != "materializer_run_in_flight":
        _advance_index_batch("intraday.bars", batch_size)
    logger.info(
        "US Index Intraday materializer status=%s requested=%s refreshed=%s "
        "failed=%s calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return _publish_intraday_consumer_read_models(result)


def cleanup_us_quote_snapshots(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, object]:
    db = session_factory()
    try:
        result = prune_expired_us_quote_snapshots(
            db,
            now=now,
            retention_days=settings.us_quote_snapshot_retention_days,
            max_rows=settings.scheduler_us_quote_cleanup_max_rows,
        )
        logger.info(
            "US Quote retention status=%s deleted=%s remaining_expired=%s.",
            result["status"],
            result["deleted_count"],
            result["remaining_expired"],
        )
        return result
    finally:
        db.close()


def snapshot_us_source_health_job(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, Any]:
    """Persist a bounded cache-only health observation; never performs provider IO."""

    db = session_factory()
    try:
        payload = snapshot_us_source_health(db, now=now)
        return {
            "status": "success",
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary") or {},
            "provider_io_performed": False,
        }
    finally:
        db.close()


def add_us_intraday_materializer_jobs(scheduler: Any) -> bool:
    global _EOD_SCHEDULER
    _EOD_SCHEDULER = scheduler
    if not us_intraday_materializer_jobs_requested():
        return False

    now = datetime.now(timezone.utc)
    registered = False
    if settings.enable_us_intraday_reconciliation:
        _load_eod_durable_snapshot(now=now)
        scheduler.add_job(
            reconcile_us_completed_intraday_bars,
            trigger="interval", seconds=900,
            id="us_intraday_completed_session_reconciliation",
            replace_existing=True, coalesce=True, max_instances=1,
            next_run_time=now + timedelta(seconds=120),
        )
        registered = True
    if settings.enable_us_intraday_materializer:
        # Active viewers get an independent owner lane, so long-running index
        # work cannot starve a viewed stock. Quote and intraday serialize
        # inside each owner lane, bounding concurrent provider parsing and
        # SQLite persistence to active, canary, and index work at most.
        scheduler.add_job(
            collect_us_active_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_active_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=5),
        )
        scheduler.add_job(
            collect_us_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=15),
        )
        scheduler.add_job(
            collect_us_active_intraday_bars,
            trigger="interval",
            seconds=settings.scheduler_us_intraday_materializer_interval_seconds,
            id="us_active_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=35),
        )
        scheduler.add_job(
            collect_us_intraday_bars,
            trigger="interval",
            seconds=settings.scheduler_us_intraday_materializer_interval_seconds,
            id="us_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=55),
        )
        registered = True
    if settings.enable_us_index_quote_materializer:
        _symbols, _batch_size, quote_run_interval = _rotating_index_batch(
            "quote.snapshot"
        )
        with _INDEX_BATCH_STATE_LOCK:
            _INDEX_BATCH_OFFSETS["quote.snapshot"] = 0
        scheduler.add_job(
            collect_us_index_quote_snapshots,
            trigger="interval",
            seconds=quote_run_interval,
            id="us_index_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=30),
        )
        registered = True
    if settings.enable_us_index_intraday_materializer:
        _symbols, _batch_size, intraday_run_interval = _rotating_index_batch(
            "intraday.bars"
        )
        intraday_start_delay = 85.0
        if settings.enable_us_index_quote_materializer:
            # Maximize the minimum separation of the two periodic trigger grids.
            # Keep startup >=85s and all recurring intervals/budgets unchanged.
            # Work lasting longer than this half-GCD gap can still hit the lock.
            phase_period = math.gcd(quote_run_interval, intraday_run_interval)
            intraday_start_delay += (
                30 + phase_period / 2 - intraday_start_delay
            ) % phase_period
        with _INDEX_BATCH_STATE_LOCK:
            _INDEX_BATCH_OFFSETS["intraday.bars"] = 0
        scheduler.add_job(
            collect_us_index_intraday_bars,
            trigger="interval",
            seconds=intraday_run_interval,
            id="us_index_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=intraday_start_delay),
        )
        registered = True
    if settings.enable_us_quote_retention_scheduler:
        scheduler.add_job(
            cleanup_us_quote_snapshots,
            trigger="cron",
            hour=3,
            minute=15,
            timezone=US_MARKET_TIMEZONE,
            id="us_quote_snapshot_retention",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        registered = True
    if settings.enable_us_source_health_snapshot_scheduler:
        scheduler.add_job(
            snapshot_us_source_health_job,
            trigger="interval",
            seconds=settings.scheduler_us_source_health_snapshot_interval_seconds,
            id="us_source_health_snapshot",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=110),
        )
        registered = True
    return registered


def us_intraday_materializer_jobs_requested() -> bool:
    """Return whether any independently owned US intraday job is requested."""

    return any(
        (
            settings.enable_us_intraday_materializer,
            settings.enable_us_intraday_reconciliation,
            settings.enable_us_index_quote_materializer,
            settings.enable_us_index_intraday_materializer,
            settings.enable_us_quote_retention_scheduler,
            settings.enable_us_source_health_snapshot_scheduler,
        )
    )


__all__ = [
    "add_us_intraday_materializer_jobs",
    "cleanup_us_quote_snapshots",
    "collect_us_active_intraday_bars",
    "collect_us_active_quote_snapshots",
    "collect_us_index_quote_snapshots",
    "collect_us_index_intraday_bars",
    "collect_us_intraday_bars",
    "collect_us_quote_snapshots",
    "snapshot_us_source_health_job",
    "us_intraday_materializer_jobs_requested",
]
