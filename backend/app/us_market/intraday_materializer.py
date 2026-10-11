"""Bounded background owner for persisted US quote and intraday evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import logging
import json
import re
from contextlib import contextmanager
from pathlib import Path
import os
from uuid import uuid4

from sqlalchemy import inspect as inspect_database, text
from app.db.models import JobRun
from app.jobs import service as job_service
from app.us_market.intraday_read_model_cache import (
    invalidate_us_intraday_read_cache, us_intraday_cache_generation,
)
from threading import Lock
import time
from typing import Any, Callable, Literal

from app.db.session import SessionLocal
from app.market_data.contracts import BarFinalization, MarketSession, ResolvedEvidenceStatus
from app.market_data.gateway import PostAcquisitionError
from app.market_data.provider_catalog import ProviderResourceRouteV2
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import (
    US_QUOTE_REGISTERED_DESCRIPTORS, US_INTRADAY_REGISTERED_DESCRIPTORS,
)
from app.us_market.intraday_profiles import (
    US_BOOTSTRAP_INTRADAY_PROFILE,
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    US_RECURRING_INTRADAY_PROFILE,
    USIntradayOperationProfile,
)
from app.us_market.session_policy import us_session_for_timestamp
from app.us_market.symbols import US_INDEX_SYMBOLS, normalize_us_symbol
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, is_us_trading_day
from app.us_market.active_equity_targets import us_active_equity_viewer_summary
from app.us_market.historical_intraday import completed_intraday_window, regular_intraday_coverage


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
_MATERIALIZER_LOCKS_GUARD = Lock()
_MATERIALIZER_LOCKS: dict[tuple[str, USMaterializerCapability], Any] = {}
_MAX_MATERIALIZER_LOCKS = 64
_LAST_RUNS_LOCK = Lock()
_LAST_RUNS: dict[tuple[str, USMaterializerCapability], dict[str, Any]] = {}
_RUN_COUNTERS: dict[tuple[str, USMaterializerCapability], dict[str, Any]] = {}

# JobRun holds bounded operational obligations, never canonical coverage truth.
_EOD_LOCK = Lock()
_EOD_JOB_TYPE = "us.intraday_eod_obligation"
_EOD_HISTORY_DAYS = 5
_EOD_MAX_ATTEMPTS = 3
_EOD_COOLDOWN = timedelta(minutes=15)


def _eod_target(symbol: str, trade_date: date) -> str:
    return f"us-eod:{symbol}:{trade_date.isoformat()}:NY:regular:1m"


def resolve_us_eod_universe(configured_symbols: str, *, max_symbols: int = 2) -> dict[str, Any]:
    universe = resolve_us_materializer_universe(
        configured_symbols, max_symbols=20, lane_id="equity_eod",
        owner="explicit_completed_session_reconciliation")
    universe["configured_symbol_sample"] = universe["symbols"][:3]
    valid = (1 <= max_symbols <= 2 and universe["configured_count"] <= max_symbols
             and universe["rejected_count"] == 0)
    universe.update(scope_valid=valid, max_symbols=max_symbols)
    if not valid:
        universe.update(symbols=[], selected_count=0, skipped_count=universe["configured_count"],
                        reason="US_EOD_INVALID_EXPLICIT_SCOPE")
    return universe


def read_us_eod_job_snapshot(
    *, configured_symbols: str, now: datetime, max_symbols: int = 2,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, Any]:
    """Startup/background-only bounded ledger read; no acquisition or mutation."""
    universe = resolve_us_eod_universe(configured_symbols, max_symbols=max_symbols)
    snapshot: dict[str, Any] = {
        "source": "persisted_job_run", "loaded_at": now.isoformat(),
        "snapshot_available": False, "jobs": [], "limit": 12,
        "coverage_semantics": "last_recorded_canonical_reread_not_live_coverage",
    }
    if not universe["scope_valid"] or not universe["symbols"]:
        return {**snapshot, "reason": "invalid_or_empty_scope"}
    db = None
    try:
        db = session_factory()
        # Two index range seeks, six most recent targets each; no ledger-wide scan.
        rows = []
        for symbol in universe["symbols"]:
            prefix = f"us-eod:{symbol}:"
            rows.extend(db.query(JobRun).filter(
                JobRun.job_type == _EOD_JOB_TYPE,
                JobRun.target >= prefix, JobRun.target < prefix + "~",
            ).order_by(JobRun.target.desc()).limit(6).all())
        for row in rows:
            request = json.loads(row.request_json)
            snapshot["jobs"].append({
                "job_id": row.id, "job_status": row.status, "target": row.target,
                "symbol": request["symbol"], "trade_date": request["trade_date"],
                "attempt_count": len(request["attempts"]),
                "attempts": request["attempts"],
                "next_retry_at": request.get("next_retry_at"),
                "last_recorded_result": json.loads(row.result_json or "{}"),
            })
        snapshot.update(snapshot_available=True, job_run_count=len(rows))
    except Exception as exc:
        snapshot.update(reason="durable_snapshot_unavailable", error_type=type(exc).__name__)
    finally:
        if db is not None:
            db.close()
    return snapshot


def _eod_begin(db: Any) -> None:
    """Short SQLite writer transaction; no lock may cross provider IO.

    The scoped unique index protects enrollment. BEGIN IMMEDIATE serializes
    read/check/reserve across processes, including a just-finished attempt.
    Missing migration / unsupported dialect fails closed before acquisition.
    """
    db.rollback()
    if db.get_bind().dialect.name != "sqlite":
        raise RuntimeError("US_EOD_DURABLE_ADMISSION_UNSUPPORTED_DIALECT")
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        indexes = inspect_database(db.connection()).get_indexes("job_run")
        valid = any(i["name"] == "uq_job_run_us_eod_obligation" and i["unique"]
                    and i["column_names"] == ["job_type", "target"] for i in indexes)
        definition = db.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_job_run_us_eod_obligation'")).scalar()
        predicate = " ".join(definition.split("WHERE", 1)[-1].split()) if definition else ""
        if not valid or predicate != "job_type = 'us.intraday_eod_obligation'":
            raise RuntimeError("US_EOD_DURABLE_ADMISSION_MIGRATION_REQUIRED")
    except Exception:
        db.rollback()
        raise


@contextmanager
def _eod_worker_lease(db: Any):
    """One advisory file lock per SQLite DB; released by OS on process death.

    No DB transaction spans IO. A live worker keeps this lock until its final
    canonical reread/record. A successor can therefore reclaim an orphaned
    running reservation without relying on timeouts or restarting the runtime.
    This is local SQLite only, not a distributed/network-filesystem lease.
    """
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("US_EOD_DURABLE_ADMISSION_UNSUPPORTED_DIALECT")
    database = bind.url.database
    if not database or database == ":memory:":
        # In-memory SQLite is fixture-only; the enclosing process lock owns it.
        yield True
        return
    lock_path = Path(database).resolve().with_suffix(Path(database).suffix + ".us-eod.lock")
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _eod_admit(db: Any, *, symbol: str, trade_date: date, now: datetime,
               evidence: dict[str, Any], allow_call: bool, recover_orphan: bool = False,
               planned_resource: ProviderResourceRouteV2 | None = None,
               route_unavailable: bool = False) -> dict[str, Any]:
    _eod_begin(db)
    try:
        target = _eod_target(symbol, trade_date)
        job = db.query(JobRun).filter_by(job_type=_EOD_JOB_TYPE, target=target).one_or_none()
        if job is None:
            job = job_service.create_job_record(
                db, _EOD_JOB_TYPE, target=target,
                request={"symbol": symbol, "trade_date": trade_date.isoformat(),
                         "session_scope": "regular", "interval": "1m", "attempts": []},
            )
            job.status = "error"  # enrolled, no provider reservation yet
            db.flush()
        request = json.loads(job.request_json)
        attempts = request["attempts"]
        next_retry = request.get("next_retry_at")
        # Never infer historical provider identity from outcome or current catalog.
        history_valid = isinstance(attempts, list) and all(
            isinstance(a, dict) and isinstance(a.get("planned_resource"), dict)
            and isinstance(a["planned_resource"].get("provider_key"), str)
            and bool(a["planned_resource"]["provider_key"])
            and isinstance(a["planned_resource"].get("resource_id"), str)
            and bool(a["planned_resource"]["resource_id"])
            and a.get("external_call_reservation") == 1
            for a in attempts
        )
        excluded = tuple(a["planned_resource"]["provider_key"] for a in attempts) if history_valid else ()
        if planned_resource is not None and (
            planned_resource.capability_id != "intraday.bars"
            or planned_resource.max_external_calls != 1
            or not planned_resource.fetch_allowed or planned_resource.subscription_allowed
        ):
            raise RuntimeError("US_EOD_INVALID_PLANNED_RESOURCE")
        active = job_service.find_active_job_by_target(db, _EOD_JOB_TYPE, target)
        if active is not None and recover_orphan:
            # Only the holder of the DB-scoped OS lease may reclaim an orphan.
            job.status = "error"
            job.message = "Recovered orphan; prior reserved calls remain consumed."
            active = None
        reason = (
            "active_or_interrupted_reservation" if active is not None
            else "canonical_cache_already_satisfied" if evidence["postcondition_satisfied"]
            else "retry_budget_exhausted" if len(attempts) >= _EOD_MAX_ATTEMPTS
            else "legacy_route_history_unknown" if not history_valid
            else "cooldown" if next_retry and now < datetime.fromisoformat(next_retry)
            else "external_call_budget_exhausted" if not allow_call
            else "acquisition_plan_unfillable" if route_unavailable
            else "route_pending" if planned_resource is None
            else "provider_already_reserved" if planned_resource.provider_key in excluded
            else "reserved"
        )
        if reason == "reserved":
            next_retry = (now + _EOD_COOLDOWN).isoformat()
            attempts.append({"reservation_id": uuid4().hex, "reserved_at": now.isoformat(), "external_call_reservation": 1,
                             "outcome": "unknown", "next_retry_at": next_retry,
                             "planned_resource": planned_resource.model_dump(mode="json")})
            request["next_retry_at"] = next_retry
            job.status = "running"
            job.started_at = now
            job.ended_at = None
        elif active is None:
            job.status = "success" if evidence["postcondition_satisfied"] else "error"
        item = {**evidence, "job_id": job.id, "attempt_count": len(attempts),
                "reason": reason, "next_retry_at": next_retry,
                "acquisition_attempted": reason == "reserved",
                "excluded_providers": list(excluded),
                "planned_resource": planned_resource.model_dump(mode="json") if reason == "reserved" else None,
                "reservation_id": attempts[-1]["reservation_id"] if attempts else None,
                "checked_at": now.isoformat(),
                "unfillable_reason": reason if reason in {"retry_budget_exhausted", "legacy_route_history_unknown", "acquisition_plan_unfillable", "provider_already_reserved"} else None}
        if reason == "reserved":
            job.request_json = json.dumps(request)
        job.result_json = json.dumps(item)
        job.updated_at = now
        db.commit()
        return item
    except Exception:
        db.rollback()
        raise


def _eod_finish(db: Any, item: dict[str, Any], *, now: datetime) -> None:
    _eod_begin(db)
    try:
        job = db.get(JobRun, item["job_id"])
        request = json.loads(job.request_json)
        # A lifecycle interruption must not let an old worker overwrite a new reservation.
        if (len(request["attempts"]) != item["attempt_count"] or job.status != "running"
                or request["attempts"][-1]["reservation_id"] != item["reservation_id"]):
            raise RuntimeError("US_EOD_RESERVATION_LOST")
        request["attempts"][-1]["outcome"] = item["reason"]
        request["attempts"][-1]["error_type"] = item.get("error_type")
        request["attempts"][-1]["acquisition_limitations"] = item.get("acquisition_limitations", [])
        request["attempts"][-1]["selected_resources"] = item.get("selected_resources", [])
        job.request_json = json.dumps(request)
        job.status = "success" if item["postcondition_satisfied"] else "error"
        job.result_json = json.dumps(item)
        job.ended_at = now
        job.updated_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise


def expire_us_intraday_obligations(
    *, configured_symbols: str, now: datetime, max_symbols: int = 2,
    session_factory: Callable[[], Any] = SessionLocal,
) -> list[dict[str, Any]]:
    """Bounded operational terminalization; never infer canonical completeness."""
    universe = resolve_us_eod_universe(configured_symbols, max_symbols=max_symbols)
    if not universe["scope_valid"]:
        raise ValueError("US_EOD_INVALID_EXPLICIT_SCOPE")
    symbols = universe["symbols"]
    if not symbols:
        return []
    cutoff = (now.astimezone(US_MARKET_TIMEZONE).date() - timedelta(days=5)).isoformat()
    db = session_factory()
    try:
        with _eod_worker_lease(db) as acquired:
            if not acquired:
                return []
            _eod_begin(db)
            rows = []
            for symbol in symbols:
                prefix = f"us-eod:{symbol}:"
                # Bound both the range seek and returned rows. Old terminal rows
                # do not cause an ever-growing scan on each tick.
                rows.extend(db.query(JobRun).filter(
                    JobRun.job_type == _EOD_JOB_TYPE,
                    JobRun.target >= prefix, JobRun.target < prefix + cutoff,
                ).order_by(JobRun.target.desc()).limit(6).all())
            expired = []
            for job in rows:
                request = json.loads(job.request_json)
                item = json.loads(job.result_json or "{}")
                if job.status == "success" or item.get("unfillable_reason") == "retention_expired":
                    continue
                item.update(symbol=request["symbol"], trade_date=request["trade_date"],
                            job_id=job.id, postcondition_satisfied=False,
                            reason="retention_expired", unfillable_reason="retention_expired",
                            next_retry_at=None, terminalized_at=now.isoformat())
                request["next_retry_at"] = None
                job.request_json = json.dumps(request)
                job.result_json = json.dumps(item)
                job.status = "error"
                job.updated_at = now
                expired.append(item)
            db.commit()
            return expired
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reconcile_us_intraday_session(
    *, configured_symbols: str, trade_date: date, max_symbols: int = 2,
    max_external_calls: int = 2, now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    platform_factory: Callable[[Any], Any] = USIntradayMarketPlatform,
    publish: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Durably reserve bounded attempts, then acquire and canonical reread."""
    requested_at = now or datetime.now(timezone.utc)
    start, end = completed_intraday_window(trade_date, now=requested_at)
    if (requested_at.astimezone(US_MARKET_TIMEZONE).date() - trade_date).days > _EOD_HISTORY_DAYS:
        raise ValueError("US_EOD_RECONCILIATION_OUTSIDE_BOUNDED_HORIZON")
    if not 1 <= max_symbols <= 2 or not 0 <= max_external_calls <= 2:
        raise ValueError("US EOD permits at most two symbols and two calls per run")
    universe = resolve_us_eod_universe(configured_symbols, max_symbols=max_symbols)
    if not universe["scope_valid"]:
        raise ValueError("US_EOD_INVALID_EXPLICIT_SCOPE")
    started = time.monotonic()
    result = _base_result(capability="intraday.bars", now=requested_at,
                          phase=us_session_for_timestamp(requested_at), lane_id="equity_eod",
                          profile=US_BOOTSTRAP_MATERIALIZER_PROFILE)
    result.update(trade_date=trade_date.isoformat(), session_scope="regular", interval="1m",
                  budget_scope="durable_job_run", max_attempts=_EOD_MAX_ATTEMPTS,
                  cooldown_seconds=int(_EOD_COOLDOWN.total_seconds()), universe=universe,
                  requested_count=len(universe["symbols"]), reserved_external_call_count=0)
    if not _EOD_LOCK.acquire(blocking=False):
        result.update(status="skipped", reason="materializer_run_in_flight")
        return _finish_run("intraday.bars", result, started_monotonic=started)
    try:
        db = session_factory()
        try:
            with _eod_worker_lease(db) as owns_lease:
                if not owns_lease:
                    result.update(status="skipped", reason="durable_worker_in_flight")
                    return _finish_run("intraday.bars", result, started_monotonic=started)
                platform = platform_factory(db)

                def inspect(symbol: str) -> dict[str, Any]:
                    # Release any snapshot retained by the pre-acquisition read.
                    db.rollback()
                    read = platform.read_intraday_bars_for_trade_date(
                        symbol=symbol, trade_date=trade_date, bars=1000, now=requested_at,
                        completed_regular=True)
                    bars = tuple(bar for bar in read.result.resolved.bars if start <= bar.start_at < end)
                    coverage = regular_intraday_coverage([bar.start_at for bar in bars], trade_date=trade_date)
                    coverage["unfinalized_count"] = sum(
                        bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED} for bar in bars)
                    coverage["corrected_count"] = sum(bar.finalization == BarFinalization.CORRECTED for bar in bars)
                    usable = bool(read.result.resolved.health.facts_usable)
                    complete = coverage["coverage_status"] == "complete" and coverage["unfinalized_count"] == 0 and usable
                    return {"coverage": coverage, "postcondition_satisfied": complete,
                            "facts_usable": usable,
                            "status": "complete" if complete else "partial" if bars else "missing"}

                for symbol in universe["symbols"]:
                    item: dict[str, Any] = {"symbol": symbol, "trade_date": trade_date.isoformat(),
                                            "acquisition_attempted": False}
                    result["results"].append(item)
                    try:
                        evidence = inspect(symbol)
                        item.update(_eod_admit(db, symbol=symbol, trade_date=trade_date, now=requested_at,
                                              evidence=evidence, allow_call=result["reserved_external_call_count"] < max_external_calls,
                                              recover_orphan=True))
                        if item["reason"] != "route_pending":
                            continue

                        def reserve_route(route: ProviderResourceRouteV2) -> None:
                            admission = _eod_admit(
                                db, symbol=symbol, trade_date=trade_date, now=requested_at,
                                evidence=inspect(symbol),
                                allow_call=result["reserved_external_call_count"] < max_external_calls,
                                planned_resource=route,
                            )
                            item.update(admission)
                            if not admission["acquisition_attempted"]:
                                raise RuntimeError("US_EOD_ROUTE_ADMISSION_DENIED")
                            result["reserved_external_call_count"] += 1

                        generation = us_intraday_cache_generation(symbol)
                        try:
                            refreshed = platform.refresh_intraday_bars(
                                symbol=symbol, trade_date=trade_date, session_scope="regular",
                                bars=1000, now=requested_at, require_live=False,
                                max_provider_calls=1, profile=US_BOOTSTRAP_MATERIALIZER_PROFILE,
                                excluded_providers=tuple(item["excluded_providers"]),
                                before_acquire=reserve_route)
                            acquisition = getattr(refreshed.result, "acquisition", None)
                            result["external_call_count"] += int(getattr(acquisition, "external_calls", 0) or 0)
                            item["acquisition_limitations"] = list(getattr(acquisition, "limitations", ()) or ())
                            item["selected_resources"] = [a.model_dump(mode="json") for a in getattr(acquisition, "resource_attempts", ())]
                            item["acquisition_status"] = getattr(getattr(acquisition, "status", None), "value", None)
                            persistence = getattr(refreshed.result, "persistence", None)
                            item["persistence_committed"] = bool(getattr(persistence, "committed", False))
                            item["observations_written"] = int(getattr(persistence, "observations_written", 0) or 0)
                        except Exception as exc:
                            db.rollback()
                            item["error_type"] = type(exc).__name__
                            if isinstance(exc, PostAcquisitionError):
                                result["external_call_count"] += exc.acquisition.external_calls
                                item["selected_resources"] = [a.model_dump(mode="json") for a in exc.acquisition.resource_attempts]
                                item["acquisition_limitations"] = list(exc.acquisition.limitations)
                            elif item["acquisition_attempted"]:
                                item["external_call_count_unknown"] = True
                                item["acquisition_limitations"] = ["PROVIDER_OUTCOME_UNKNOWN"]
                            logger.warning("US EOD acquisition failed symbol=%s error_type=%s", symbol, type(exc).__name__)
                        finally:
                            # The transaction invalidates immediately after commit, even if
                            # Gateway post-processing throws. Same-symbol concurrent commits
                            # can conservatively schedule an extra cache-only publish.
                            item["consumer_cache_invalidated"] = us_intraday_cache_generation(symbol) != generation
                        try:
                            item.update(inspect(symbol))
                            item["reason"] = ("canonical_reread_complete" if item["postcondition_satisfied"]
                                              else "provider_error" if item.get("error_type") or item.get("acquisition_status") == "failed"
                                              else "canonical_reread_incomplete")
                        except Exception as exc:
                            db.rollback()
                            item.update(status="error", postcondition_satisfied=False,
                                        reason="canonical_reread_failed", error_type=type(exc).__name__)
                        if item["consumer_cache_invalidated"] or item.get("observations_written", 0):
                            invalidate_us_intraday_read_cache(symbol)
                            item["consumer_cache_invalidated"] = True
                            if publish is not None:
                                try:
                                    publication = publish({"results": [item]})
                                    item["consumer_cache_publish_scheduled_count"] = publication.get("consumer_cache_publish_scheduled_count", 0)
                                    item["consumer_cache_publish_deferred_symbols"] = publication.get("consumer_cache_publish_deferred_symbols", [])
                                except Exception as exc:
                                    item["consumer_cache_publish_error"] = type(exc).__name__
                        if not item["postcondition_satisfied"] and item["attempt_count"] >= _EOD_MAX_ATTEMPTS:
                            item["unfillable_reason"] = "retry_budget_exhausted"
                        if item["acquisition_attempted"]:
                            _eod_finish(db, item, now=requested_at)
                        else:
                            item.update(_eod_admit(
                                db, symbol=symbol, trade_date=trade_date, now=requested_at,
                                evidence=item, allow_call=True, route_unavailable=True,
                            ))
                    except Exception as exc:
                        db.rollback()
                        item.update(status="error", postcondition_satisfied=False,
                                    reason="durable_admission_or_recording_failed", error_type=type(exc).__name__,
                                    error_code=str(exc) if str(exc).startswith("US_EOD_") else None)
                        logger.warning("US EOD failed closed symbol=%s error=%s", symbol, exc)
                result["succeeded_count"] = sum(item.get("postcondition_satisfied", False) for item in result["results"])
                result["failed_count"] = result["requested_count"] - result["succeeded_count"]
                result["postconditions_by_symbol"] = {item["symbol"]: dict(item) for item in result["results"]}
                result["status"] = "success" if result["results"] and not result["failed_count"] else "partial" if result["results"] else "skipped"
        finally:
            db.close()
        return _finish_run("intraday.bars", result, started_monotonic=started)
    finally:
        _EOD_LOCK.release()


def _materializer_lock_for(
    lane_id: str,
    capability: USMaterializerCapability,
) -> Any:
    key = (lane_id, capability)
    with _MATERIALIZER_LOCKS_GUARD:
        lock = _MATERIALIZER_LOCKS.get(key)
        if lock is not None:
            return lock
        if len(_MATERIALIZER_LOCKS) >= _MAX_MATERIALIZER_LOCKS:
            raise RuntimeError("US materializer lock registry is full")
        lock = Lock()
        _MATERIALIZER_LOCKS[key] = lock
        return lock


def resolve_us_materializer_universe(
    configured_symbols: str,
    *,
    max_symbols: int,
    lane_id: str = "equity_research",
    instrument_type: USMaterializerInstrumentType = "stock",
    owner: str = "configuration",
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
        "owner": owner,
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
        "succeeded_count": 0,
        "cache_satisfied_count": 0,
        "acquired_count": 0,
        "persisted_count": 0,
        "selected_count": 0,
        "refreshed_count": 0,
        "failed_count": 0,
        "external_call_count": 0,
        "observed_external_call_count": 0,
        "producer_refresh_due_seconds": profile.producer_refresh_due_seconds,
        "consumer_stale_after_seconds": profile.consumer_stale_after_seconds,
        "results": [],
    }


def _symbol_run_diagnostics(results: Any) -> list[dict[str, Any]]:
    """Project at most two outcomes; never retain provider payloads or free text."""
    if not isinstance(results, (list, tuple)):
        return []
    providers = {descriptor.provider_key for descriptor in (
        *US_QUOTE_REGISTERED_DESCRIPTORS, *US_INTRADAY_REGISTERED_DESCRIPTORS,
    )}
    reasons = {
        "canonical_cache_already_satisfied", "refresh_postcondition_unsatisfied",
        "external_call_budget_exhausted", "post_acquisition_exception",
        "pre_acquisition_exception",
    }
    # Deliberate disclosure allowlist, not a second source of postcondition policy.
    postconditions = {
        "REQUIRED_EVIDENCE_MISSING", "REQUIRED_FACTS_UNUSABLE",
        "RESOLUTION_POLICY_UNSATISFIED", "FRESHNESS_POSTCONDITION_UNSATISFIED",
        "LATEST_AVAILABLE_STALE_ACCEPTED", "HISTORICAL_SESSION_COVERAGE_INCOMPLETE",
    }
    projected = []
    seen: set[str] = set()
    for item in results[:20]:  # Existing materializer input bound.
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not (
            symbol in US_INDEX_SYMBOLS
            or re.fullmatch(r"[A-Z0-9][A-Z0-9.$-]{0,31}", symbol)
        ) or symbol in seen:
            continue
        seen.add(symbol)
        diagnostic: dict[str, Any] = {"symbol": symbol}
        for key, allowed in (
            ("status", {"success", "failed", "skipped"}),
            ("reason", reasons),
            ("resolved_status", {status.value for status in ResolvedEvidenceStatus}),
        ):
            value = item.get(key)
            if key in item and (value is None or isinstance(value, str) and value in allowed):
                diagnostic[key] = value
        failure_stages = {
            "post_acquisition_exception": "post_acquisition",
            # The generic catch also covers an acquisition port that raises
            # before it returns accounting; do not claim zero provider IO.
            "pre_acquisition_exception": "pre_acquisition_or_acquisition",
        }
        if diagnostic.get("reason") in failure_stages:
            diagnostic["failure_stage"] = failure_stages[diagnostic["reason"]]
            error_type = item.get("error_type")
            if isinstance(error_type, str) and error_type in {
                "OperationalError", "IntegrityError", "DatabaseError",
                "TimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout",
                "ValidationError", "ValueError", "TypeError", "LookupError",
                "RuntimeError", "PostAcquisitionError",
            }:
                diagnostic["error_type"] = error_type
        for source, target in (
            ("acquisition_attempted", "attempted"), ("persistence_committed", "persisted"),
            ("cache_satisfied", "cache_satisfied"), ("facts_usable", "facts_usable"),
        ):
            if type(item.get(source)) is bool:
                diagnostic[target] = item[source]
        calls = item.get("external_calls")
        if type(calls) is int and 0 <= calls <= 40:
            diagnostic["external_calls"] = calls
        provider = item.get("selected_provider")
        if "selected_provider" in item and (
            provider is None or isinstance(provider, str) and provider in providers
        ):
            diagnostic["provider"] = provider
        codes = item.get("postcondition_reasons")
        if isinstance(codes, (list, tuple)):
            diagnostic["postcondition_reason_codes"] = list(dict.fromkeys(
                code for code in codes[:20] if isinstance(code, str) and code in postconditions
            ))
        projected.append(diagnostic)
        if len(projected) == 2:
            break
    return projected


def _record_last_run(capability: USMaterializerCapability, result: dict[str, Any]) -> None:
    lane_id = str(result.get("lane_id") or "unknown")
    with _LAST_RUNS_LOCK:
        _LAST_RUNS[(lane_id, capability)] = {
            key: value
            for key, value in result.items()
            if key not in {"results", "universe"}
        }
        _LAST_RUNS[(lane_id, capability)]["symbol_runs"] = _symbol_run_diagnostics(
            result.get("results")
        )
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
                "cache_satisfied_count": 0,
                "acquired_count": 0,
                "persisted_count": 0,
                "selected_count": 0,
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
            "cache_satisfied_count",
            "acquired_count",
            "persisted_count",
            "selected_count",
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
    return deepcopy(max(matching, key=lambda item: str(item.get("started_at") or ""))) if matching else {}


def us_intraday_materializer_runtime_summary() -> dict[str, Any]:
    with _LAST_RUNS_LOCK:
        return {
            "contract_version": "omi.us.intraday_materializer.runtime.v1",
            "last_quote_run": _latest_run("quote.snapshot"),
            "last_intraday_run": _latest_run("intraday.bars"),
            "runs_by_lane": {
                lane_id: {
                    capability: deepcopy(value)
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
            "active_equity_viewers": us_active_equity_viewer_summary(),
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
    universe_owner: str = "configuration",
    profile: USMaterializerProfile = US_RECURRING_MATERIALIZER_PROFILE,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    platform_factory: Callable[[Any], Any] = USIntradayMarketPlatform,
    run_lock: Any | None = None,
    selection_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh one capability for a bounded, explicitly named universe owner."""

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
    if selection_metadata is not None:
        result["selection"] = dict(selection_metadata)
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

    effective_run_lock = (
        run_lock
        if run_lock is not None
        else _materializer_lock_for(lane_id, capability)
    )
    if not effective_run_lock.acquire(blocking=False):
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
            owner=universe_owner,
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
                                    "cache_satisfied": True,
                                    "acquisition_attempted": False,
                                    "persistence_committed": False,
                                    "selected": bool(
                                        cached.result.resolved.health.selected_provider
                                    ),
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
                    acquisition_attempted = bool(
                        getattr(acquisition, "attempted", True)
                    )
                    persistence = getattr(refreshed.result, "persistence", None)
                    persistence_committed = bool(
                        getattr(
                            persistence,
                            "committed",
                            acquisition_attempted,
                        )
                    )
                    # A successful intraday producer schedules a cache-only
                    # read-model publisher after releasing this lane. Keep the
                    # previous projection available within its truthful
                    # evidence-age boundary until the publisher atomically
                    # replaces it; invalidating here creates a cold-read race.
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
                                "canonical_cache_already_satisfied"
                                if postcondition and not acquisition_attempted
                                else None
                                if postcondition
                                else "refresh_postcondition_unsatisfied"
                            ),
                            "cache_satisfied": (
                                postcondition and not acquisition_attempted
                            ),
                            "acquisition_attempted": acquisition_attempted,
                            "persistence_committed": persistence_committed,
                            "selected": bool(health.selected_provider),
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
                            "acquisition_attempted": bool(exc.acquisition.attempted),
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

        result["succeeded_count"] = sum(
            item["status"] == "success" for item in result["results"]
        )
        result["cache_satisfied_count"] = sum(
            bool(item.get("cache_satisfied")) for item in result["results"]
        )
        result["acquired_count"] = sum(
            bool(item.get("acquisition_attempted")) for item in result["results"]
        )
        result["persisted_count"] = sum(
            bool(item.get("persistence_committed")) for item in result["results"]
        )
        result["selected_count"] = sum(
            bool(item.get("selected")) for item in result["results"]
        )
        result["refreshed_count"] = sum(
            item["status"] == "success" and bool(item.get("acquisition_attempted"))
            for item in result["results"]
        )
        result["failed_count"] = len(result["results"]) - result["succeeded_count"]
        result.update(
            {
                "status": (
                    "success"
                    if result["results"] and result["failed_count"] == 0
                    else "partial"
                    if result["succeeded_count"] > 0
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
        effective_run_lock.release()


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
        ("index_current", "index", "intraday.bars", index_symbols, 6),
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
