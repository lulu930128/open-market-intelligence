"""Bounded background owner for persisted US quote and intraday evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from threading import Lock
import time
from typing import Any, Callable, Literal

from app.db.session import SessionLocal
from app.market_data.contracts import MarketSession
from app.market_data.gateway import PostAcquisitionError
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.intraday_profiles import (
    US_BOOTSTRAP_INTRADAY_PROFILE,
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    US_RECURRING_INTRADAY_PROFILE,
    USIntradayOperationProfile,
)
from app.us_market.providers.canonical import us_session_for_timestamp
from app.us_market.symbols import US_INDEX_SYMBOLS, normalize_us_symbol
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, is_us_trading_day


logger = logging.getLogger(__name__)

USMaterializerCapability = Literal["quote.snapshot", "intraday.bars"]
USMaterializerInstrumentType = Literal["stock", "index"]


USMaterializerProfile = USIntradayOperationProfile
US_RECURRING_MATERIALIZER_PROFILE = US_RECURRING_INTRADAY_PROFILE
US_BOOTSTRAP_MATERIALIZER_PROFILE = US_BOOTSTRAP_INTRADAY_PROFILE
_ACQUISITION_SESSIONS = {
    MarketSession.PRE_OPEN,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
    MarketSession.POST_CLOSE,
}
_MATERIALIZER_LOCK = Lock()
_LAST_RUNS_LOCK = Lock()
_LAST_RUNS: dict[tuple[str, USMaterializerCapability], dict[str, Any]] = {}
_RUN_COUNTERS: dict[tuple[str, USMaterializerCapability], dict[str, Any]] = {}


def resolve_us_materializer_universe(
    configured_symbols: str,
    *,
    max_symbols: int,
    lane_id: str = "equity_research",
    instrument_type: USMaterializerInstrumentType = "stock",
) -> dict[str, Any]:
    if max_symbols < 1 or max_symbols > 20:
        raise ValueError("US intraday materializer max_symbols must be between 1 and 20")

    ordered: dict[str, None] = {}
    rejected: list[str] = []
    for raw_symbol in configured_symbols.split(","):
        normalized = normalize_us_symbol(raw_symbol)
        if not normalized:
            if raw_symbol.strip():
                rejected.append(raw_symbol.strip())
            continue
        is_index = normalized in US_INDEX_SYMBOLS
        if (instrument_type == "index") is not is_index:
            rejected.append(raw_symbol.strip())
            continue
        ordered[normalized] = None

    configured = list(ordered)
    selected = configured[:max_symbols]
    return {
        "contract_version": "omi.us.materializer.universe.v1",
        "owner": "configuration",
        "lane_id": lane_id,
        "instrument_type": instrument_type,
        "configured_count": len(configured),
        "selected_count": len(selected),
        "skipped_count": max(0, len(configured) - len(selected)),
        "rejected_count": len(rejected),
        "symbols": selected,
        "is_bounded": len(selected) <= max_symbols,
        "max_symbols": max_symbols,
    }


def _base_result(
    *,
    capability: USMaterializerCapability,
    now: datetime,
    phase: MarketSession,
    lane_id: str,
    profile: USMaterializerProfile,
) -> dict[str, Any]:
    return {
        "contract_version": "omi.us.intraday_materializer.run.v1",
        "capability": capability,
        "lane_id": lane_id,
        "profile_id": profile.profile_id,
        "started_at": now.astimezone(timezone.utc).isoformat(),
        "phase": phase.value,
        "requested_count": 0,
        "refreshed_count": 0,
        "failed_count": 0,
        "external_call_count": 0,
        "observed_external_call_count": 0,
        "results": [],
    }


def _record_last_run(capability: USMaterializerCapability, result: dict[str, Any]) -> None:
    lane_id = str(result.get("lane_id") or "unknown")
    with _LAST_RUNS_LOCK:
        _LAST_RUNS[(lane_id, capability)] = {
            key: value
            for key, value in result.items()
            if key not in {"results", "universe"}
        }
        counters = _RUN_COUNTERS.setdefault(
            (lane_id, capability),
            {
                "run_count": 0,
                "success_count": 0,
                "partial_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "materializer_run_in_flight_count": 0,
                "external_call_count": 0,
                "observed_external_call_count": 0,
                "refreshed_count": 0,
            },
        )
        status = str(result.get("status") or "unknown")
        counters["run_count"] += 1
        status_counter = f"{status}_count"
        if status_counter in counters:
            counters[status_counter] += 1
        if result.get("reason") == "materializer_run_in_flight":
            counters["materializer_run_in_flight_count"] += 1
        for field in (
            "external_call_count",
            "observed_external_call_count",
            "refreshed_count",
        ):
            counters[field] += int(result.get(field) or 0)
        counters["last_duration_ms"] = int(result.get("duration_ms") or 0)
        counters["last_started_at"] = result.get("started_at")
        counters["last_completed_at"] = result.get("completed_at")


def _finish_run(
    capability: USMaterializerCapability,
    result: dict[str, Any],
    *,
    started_monotonic: float,
) -> dict[str, Any]:
    result.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
    result["duration_ms"] = max(
        0,
        int((time.monotonic() - started_monotonic) * 1000),
    )
    _record_last_run(capability, result)
    return result


def _latest_run(capability: USMaterializerCapability) -> dict[str, Any]:
    matching = [
        value
        for (_lane_id, stored_capability), value in _LAST_RUNS.items()
        if stored_capability == capability
    ]
    return dict(max(matching, key=lambda item: str(item.get("started_at") or ""))) if matching else {}


def us_intraday_materializer_runtime_summary() -> dict[str, Any]:
    with _LAST_RUNS_LOCK:
        return {
            "contract_version": "omi.us.intraday_materializer.runtime.v1",
            "last_quote_run": _latest_run("quote.snapshot"),
            "last_intraday_run": _latest_run("intraday.bars"),
            "runs_by_lane": {
                lane_id: {
                    capability: dict(value)
                    for (stored_lane, capability), value in _LAST_RUNS.items()
                    if stored_lane == lane_id
                }
                for lane_id in sorted({lane for lane, _capability in _LAST_RUNS})
            },
            "counters_by_lane": {
                lane_id: {
                    capability: dict(value)
                    for (stored_lane, capability), value in _RUN_COUNTERS.items()
                    if stored_lane == lane_id
                }
                for lane_id in sorted(
                    {lane for lane, _capability in _RUN_COUNTERS}
                )
            },
        }


def materialize_us_intraday_capability(
    capability: USMaterializerCapability,
    *,
    configured_symbols: str,
    max_symbols: int = 2,
    max_provider_calls: int = 2,
    max_external_calls: int | None = None,
    lane_id: str = "equity_research",
    instrument_type: USMaterializerInstrumentType = "stock",
    profile: USMaterializerProfile = US_RECURRING_MATERIALIZER_PROFILE,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    platform_factory: Callable[[Any], Any] = USIntradayMarketPlatform,
    run_lock: Any = _MATERIALIZER_LOCK,
) -> dict[str, Any]:
    """Refresh one capability for a bounded configuration-owned universe."""

    if capability not in {"quote.snapshot", "intraday.bars"}:
        raise ValueError("Unsupported US intraday materializer capability")
    if max_provider_calls < 1 or max_provider_calls > 2:
        raise ValueError("max_provider_calls must be between 1 and 2")
    effective_max_external_calls = (
        max_symbols * max_provider_calls
        if max_external_calls is None
        else max_external_calls
    )
    if effective_max_external_calls < 1 or effective_max_external_calls > 40:
        raise ValueError("max_external_calls must be between 1 and 40")

    requested_at = now or datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    local_now = requested_at.astimezone(US_MARKET_TIMEZONE)
    phase = us_session_for_timestamp(requested_at)
    result = _base_result(
        capability=capability,
        now=requested_at,
        phase=phase,
        lane_id=lane_id,
        profile=profile,
    )
    if (
        not profile.allow_outside_acquisition_window
        and (
            not is_us_trading_day(local_now.date())
            or phase not in _ACQUISITION_SESSIONS
        )
    ):
        result.update(
            {
                "status": "skipped",
                "reason": "outside_us_intraday_acquisition_window",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return _finish_run(
            capability,
            result,
            started_monotonic=started_monotonic,
        )

    if not run_lock.acquire(blocking=False):
        result.update(
            {
                "status": "skipped",
                "reason": "materializer_run_in_flight",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return _finish_run(
            capability,
            result,
            started_monotonic=started_monotonic,
        )

    try:
        universe = resolve_us_materializer_universe(
            configured_symbols,
            max_symbols=max_symbols,
            lane_id=lane_id,
            instrument_type=instrument_type,
        )
        symbols = list(universe["symbols"])
        result["universe"] = universe
        result["requested_count"] = len(symbols)
        if not symbols:
            result.update(
                {
                    "status": "skipped",
                    "reason": "no_configured_symbols",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return _finish_run(
                capability,
                result,
                started_monotonic=started_monotonic,
            )

        db = session_factory()
        try:
            platform = platform_factory(db)
            for symbol in symbols:
                provider_calls = 0
                try:
                    remaining_calls = (
                        effective_max_external_calls - result["external_call_count"]
                    )
                    if remaining_calls <= 0:
                        result["results"].append(
                            {
                                "symbol": symbol,
                                "status": "failed",
                                "reason": "external_call_budget_exhausted",
                            }
                        )
                        continue
                    if profile.cache_satisfied_noop:
                        try:
                            cached = (
                                platform.read_quote(
                                    symbol=symbol,
                                    now=requested_at,
                                    profile=profile,
                                )
                                if capability == "quote.snapshot"
                                else platform.read_intraday_bars(
                                    symbol=symbol,
                                    bars=profile.intraday_bars,
                                    now=requested_at,
                                    profile=profile,
                                )
                            )
                        except (LookupError, ValueError):
                            cached = None
                        if cached is not None and bool(
                            cached.postcondition_satisfied
                        ):
                            result["results"].append(
                                {
                                    "symbol": symbol,
                                    "status": "success",
                                    "reason": "canonical_cache_already_satisfied",
                                    "external_calls": 0,
                                    "resolved_status": cached.result.resolved.health.status.value,
                                    "selected_provider": cached.result.resolved.health.selected_provider,
                                    "fallback_used": cached.result.resolved.health.fallback_used,
                                    "facts_usable": cached.result.resolved.health.facts_usable,
                                    "limitations": list(cached.result.resolved.health.limitations),
                                    "postcondition_reasons": list(
                                        cached.postcondition_reasons
                                    ),
                                }
                            )
                            continue
                    provider_calls = min(max_provider_calls, remaining_calls)
                    refreshed = (
                        platform.refresh_quote(
                            symbol=symbol,
                            now=requested_at,
                            require_live=False,
                            max_provider_calls=provider_calls,
                            profile=profile,
                        )
                        if capability == "quote.snapshot"
                        else platform.refresh_intraday_bars(
                            symbol=symbol,
                            bars=profile.intraday_bars,
                            now=requested_at,
                            require_live=False,
                            max_provider_calls=provider_calls,
                            profile=profile,
                        )
                    )
                    acquisition = getattr(refreshed.result, "acquisition", None)
                    external_calls = int(
                        getattr(acquisition, "external_calls", 0) or 0
                    )
                    result["external_call_count"] += external_calls
                    result["observed_external_call_count"] += external_calls
                    postcondition = bool(refreshed.postcondition_satisfied)
                    health = refreshed.result.resolved.health
                    result["results"].append(
                        {
                            "symbol": symbol,
                            "status": "success" if postcondition else "failed",
                            "reason": (
                                None
                                if postcondition
                                else "refresh_postcondition_unsatisfied"
                            ),
                            "resolved_status": health.status.value,
                            "selected_provider": health.selected_provider,
                            "fallback_used": health.fallback_used,
                            "facts_usable": health.facts_usable,
                            "limitations": list(health.limitations),
                            "external_calls": external_calls,
                            "postcondition_reasons": list(
                                refreshed.postcondition_reasons
                            ),
                        }
                    )
                except PostAcquisitionError as exc:
                    db.rollback()
                    external_calls = int(exc.acquisition.external_calls or 0)
                    result["external_call_count"] += external_calls
                    result["observed_external_call_count"] += external_calls
                    logger.warning(
                        "US intraday materializer post-acquisition failure "
                        "capability=%s symbol=%s external_calls=%s error_type=%s.",
                        capability,
                        symbol,
                        external_calls,
                        type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                    )
                    result["results"].append(
                        {
                            "symbol": symbol,
                            "status": "failed",
                            "reason": "post_acquisition_exception",
                            "error_type": (
                                type(exc.__cause__).__name__
                                if exc.__cause__
                                else type(exc).__name__
                            ),
                            "external_calls": external_calls,
                        }
                    )
                except Exception as exc:
                    db.rollback()
                    logger.warning(
                        "US intraday materializer failed capability=%s symbol=%s error_type=%s.",
                        capability,
                        symbol,
                        type(exc).__name__,
                    )
                    result["results"].append(
                        {
                            "symbol": symbol,
                            "status": "failed",
                            "reason": "pre_acquisition_exception",
                            "error_type": type(exc).__name__,
                            "external_calls": 0,
                        }
                    )
        finally:
            db.close()

        result["refreshed_count"] = sum(
            item["status"] == "success" for item in result["results"]
        )
        result["failed_count"] = len(result["results"]) - result["refreshed_count"]
        result.update(
            {
                "status": (
                    "success"
                    if result["results"] and result["failed_count"] == 0
                    else "partial"
                    if result["refreshed_count"] > 0
                    else "failed"
                    if result["results"]
                    else "skipped"
                ),
                "reason": None if result["results"] else "no_configured_symbols",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return _finish_run(
            capability,
            result,
            started_monotonic=started_monotonic,
        )
    finally:
        run_lock.release()


def bootstrap_us_current_market(
    *,
    equity_symbols: str,
    index_symbols: str,
    max_external_calls: int = US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    platform_factory: Callable[[Any], Any] = USIntradayMarketPlatform,
) -> dict[str, Any]:
    """Run an explicit, bounded, idempotent cold-cache bootstrap plan."""

    if max_external_calls < 1 or max_external_calls > 20:
        raise ValueError("bootstrap max_external_calls must be between 1 and 20")
    remaining = max_external_calls
    runs: list[dict[str, Any]] = []
    configured_plans = (
        ("index_current", "index", "quote.snapshot", index_symbols, 6),
        ("equity_research", "stock", "quote.snapshot", equity_symbols, 2),
        ("equity_research", "stock", "intraday.bars", equity_symbols, 2),
    )
    plans = tuple(plan for plan in configured_plans if plan[3].strip())
    for lane_id, instrument_type, capability, symbols, max_symbols in plans:
        if remaining <= 0:
            break
        run = materialize_us_intraday_capability(
            capability,
            configured_symbols=symbols,
            max_symbols=max_symbols,
            max_provider_calls=2,
            max_external_calls=remaining,
            lane_id=lane_id,
            instrument_type=instrument_type,
            profile=US_BOOTSTRAP_MATERIALIZER_PROFILE,
            now=now,
            session_factory=session_factory,
            platform_factory=platform_factory,
        )
        runs.append(run)
        remaining -= int(run.get("external_call_count") or 0)
    return {
        "contract_version": "omi.us.current_market_bootstrap.v1",
        "status": (
            "success"
            if len(runs) == len(plans)
            and bool(runs)
            and all(run["status"] == "success" for run in runs)
            else "partial"
            if runs and any(run["refreshed_count"] for run in runs)
            else "failed"
        ),
        "max_external_calls": max_external_calls,
        "external_call_count": max_external_calls - remaining,
        "remaining_external_calls": remaining,
        "runs": runs,
    }


__all__ = [
    "US_BOOTSTRAP_MATERIALIZER_PROFILE",
    "US_RECURRING_MATERIALIZER_PROFILE",
    "USMaterializerProfile",
    "bootstrap_us_current_market",
    "materialize_us_intraday_capability",
    "resolve_us_materializer_universe",
    "us_intraday_materializer_runtime_summary",
]
