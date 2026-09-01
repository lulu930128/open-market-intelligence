"""Bounded Control-Plane repair gate for canonical US index data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from threading import Lock
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JobRun
from app.db.session import SessionLocal
from app.jobs import service as job_service
from app.jobs.job_types import US_INDEX_DATA_REPAIR_JOB_TYPE
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.intraday_materializer import materialize_us_intraday_capability
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.intraday_profiles import US_BOOTSTRAP_INTRADAY_PROFILE
from app.us_market.ohlc_priority import (
    PRIORITY_DAILY_RESEARCH_CONTRACT,
    PRIORITY_US_INDEX_SYMBOLS,
    reconcile_us_priority_ohlc,
)


logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
DailyPlatformFactory = Callable[[Session], Any]
QuotePlatformFactory = Callable[[Session], Any]
_SUMMARY_LOCK = Lock()
_LAST_DECISION: dict[str, Any] = {}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _health_value(platform_result: Any) -> str | None:
    status = platform_result.result.resolved.health.status
    return getattr(status, "value", str(status)) if status is not None else None


def _record_decision(value: dict[str, Any]) -> None:
    with _SUMMARY_LOCK:
        _LAST_DECISION.clear()
        _LAST_DECISION.update(value)


def us_index_data_repair_runtime_summary() -> dict[str, Any]:
    with _SUMMARY_LOCK:
        return {
            "contract_version": "omi.us.index_data_repair_gate.runtime.v1",
            "last_decision": dict(_LAST_DECISION),
        }


def audit_us_index_data(
    db: Session,
    *,
    now: datetime | None = None,
    daily_platform_factory: DailyPlatformFactory = USDailyOhlcvPlatform,
    quote_platform_factory: QuotePlatformFactory = USIntradayMarketPlatform,
) -> dict[str, Any]:
    """Read canonical persistence only; never acquire, enqueue, or write."""

    requested_at = _utc(now) or datetime.now(timezone.utc)
    daily_platform = daily_platform_factory(db)
    quote_platform = quote_platform_factory(db)
    daily: list[dict[str, Any]] = []
    quotes: list[dict[str, Any]] = []

    for symbol in PRIORITY_US_INDEX_SYMBOLS:
        try:
            result = daily_platform.read(
                symbol=symbol,
                bars=PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count,
                now=requested_at,
            )
            satisfied = bool(
                result.temporal_postcondition_satisfied
                and result.coverage_postcondition_satisfied
            )
            daily.append(
                {
                    "symbol": symbol,
                    "satisfied": satisfied,
                    "temporal_postcondition_satisfied": bool(
                        result.temporal_postcondition_satisfied
                    ),
                    "coverage_postcondition_satisfied": bool(
                        result.coverage_postcondition_satisfied
                    ),
                    "expected_trade_date": result.projection.get(
                        "expected_trade_date"
                    ),
                    "latest_trade_date": result.projection.get("latest_trade_date"),
                    "coverage_status": result.projection.get("coverage_status"),
                }
            )
        except Exception as exc:
            daily.append(
                {
                    "symbol": symbol,
                    "satisfied": False,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

        try:
            result = quote_platform.read_quote(
                symbol=symbol,
                now=requested_at,
                profile=US_BOOTSTRAP_INTRADAY_PROFILE,
            )
            quotes.append(
                {
                    "symbol": symbol,
                    "satisfied": bool(result.postcondition_satisfied),
                    "resolved_status": _health_value(result),
                    "selected_provider": (
                        result.result.resolved.health.selected_provider
                    ),
                    "postcondition_reasons": list(result.postcondition_reasons),
                    "observed_at": result.projection.get("observed_at"),
                }
            )
        except Exception as exc:
            quotes.append(
                {
                    "symbol": symbol,
                    "satisfied": False,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

    missing_daily = [item["symbol"] for item in daily if not item["satisfied"]]
    missing_quotes = [item["symbol"] for item in quotes if not item["satisfied"]]
    expected_dates = sorted(
        {
            str(item["expected_trade_date"])
            for item in daily
            if item.get("expected_trade_date")
        }
    )
    return {
        "contract_version": "omi.us.index_data_repair_gate.audit.v1",
        "owner": "scheduler_control_plane",
        "read_policy": "canonical_persistence_only",
        "checked_at": requested_at,
        "symbols": list(PRIORITY_US_INDEX_SYMBOLS),
        "daily_minimum_bar_count": (
            PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count
        ),
        "expected_trade_date": expected_dates[-1] if expected_dates else None,
        "daily": daily,
        "quotes": quotes,
        "missing_daily_symbols": missing_daily,
        "missing_quote_symbols": missing_quotes,
        "missing_count": len(missing_daily) + len(missing_quotes),
        "postcondition_satisfied": not missing_daily and not missing_quotes,
    }


def _target_for_audit(audit: dict[str, Any], *, now: datetime) -> str:
    expected_date = audit.get("expected_trade_date")
    return f"index-gate:{expected_date or now.date().isoformat()}"


def plan_us_index_data_repair(
    db: Session,
    *,
    now: datetime | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan one repair attempt without provider I/O or mutation."""

    requested_at = _utc(now) or datetime.now(timezone.utc)
    current_audit = audit or audit_us_index_data(db, now=requested_at)
    target = _target_for_audit(current_audit, now=requested_at)
    base = {
        "target": target,
        "checked_at": requested_at,
        "audit": current_audit,
    }
    if current_audit["postcondition_satisfied"]:
        return {**base, "status": "resolved", "reason": "postcondition_satisfied"}

    active_job = job_service.find_active_job_by_target(
        db,
        US_INDEX_DATA_REPAIR_JOB_TYPE,
        target,
    )
    if active_job is not None:
        return {
            **base,
            "status": "leased",
            "reason": "active_job",
            "job_id": active_job.id,
        }

    attempt_query = db.query(JobRun).filter(
        JobRun.job_type == US_INDEX_DATA_REPAIR_JOB_TYPE,
        JobRun.target == target,
    )
    lifetime_attempt_count = attempt_query.count()
    rows = (
        attempt_query.order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .limit(100)
        .all()
    )
    rows.reverse()
    last_success_index = max(
        (
            index
            for index, row in enumerate(rows)
            if str(row.status).casefold() == "success"
        ),
        default=None,
    )
    attempts_since_success = (
        len(rows) - last_success_index - 1
        if last_success_index is not None
        else lifetime_attempt_count
    )
    max_attempts = int(settings.scheduler_us_index_data_repair_max_attempts)

    cooldown_seconds = int(settings.scheduler_us_index_data_repair_cooldown_seconds)
    last_job = rows[-1] if rows else None
    last_ended_at = _utc(
        (last_job.ended_at or last_job.updated_at) if last_job is not None else None
    )
    cooldown_retry_at = (
        last_ended_at + timedelta(seconds=cooldown_seconds)
        if last_ended_at is not None
        else None
    )
    completed_attempt_window = (
        attempts_since_success > 0
        and attempts_since_success % max_attempts == 0
    )
    if completed_attempt_window:
        manual_backoff_seconds = int(
            settings.scheduler_us_index_data_repair_manual_attention_backoff_seconds
        )
        retry_at = (
            last_ended_at + timedelta(seconds=manual_backoff_seconds)
            if last_ended_at is not None
            else None
        )
        if retry_at is not None and requested_at < retry_at:
            return {
                **base,
                "status": "manual_attention",
                "reason": "attempt_window_backoff",
                "retryable": True,
                "attempt_count": lifetime_attempt_count,
                "attempts_since_success": attempts_since_success,
                "attempts_in_current_window": max_attempts,
                "max_attempts": max_attempts,
                "retry_at": retry_at,
            }
    elif cooldown_retry_at is not None and requested_at < cooldown_retry_at:
        return {
            **base,
            "status": "backoff",
            "reason": "cooldown",
            "retryable": True,
            "attempt_count": lifetime_attempt_count,
            "attempts_since_success": attempts_since_success,
            "attempts_in_current_window": attempts_since_success % max_attempts,
            "max_attempts": max_attempts,
            "retry_at": cooldown_retry_at,
        }

    return {
        **base,
        "status": "ready",
        "reason": "postcondition_missing",
        "retryable": True,
        "attempt_count": lifetime_attempt_count,
        "attempts_since_success": attempts_since_success,
        "attempts_in_current_window": attempts_since_success % max_attempts,
        "next_attempt": lifetime_attempt_count + 1,
        "next_attempt_in_window": (
            attempts_since_success % max_attempts
        ) + 1,
        "max_attempts": max_attempts,
    }


def repair_us_index_data(
    db: Session,
    progress: Callable[[int | None, int | None, str | None], None],
    *,
    requested_at: datetime,
    missing_daily_symbols: list[str],
    missing_quote_symbols: list[str],
    daily_max_external_calls: int,
    quote_max_external_calls: int,
    max_runtime_seconds: int,
    daily_reconciler: Callable[..., dict[str, Any]] = reconcile_us_priority_ohlc,
    quote_materializer: Callable[..., dict[str, Any]] = (
        materialize_us_intraday_capability
    ),
) -> dict[str, Any]:
    """Run existing acquisition owners, then prove persisted postconditions."""

    progress(0, 3, "Auditing canonical US index persistence.")
    initial = audit_us_index_data(db, now=requested_at)
    db.rollback()
    daily_result: dict[str, Any] | None = None
    quote_result: dict[str, Any] | None = None

    if missing_daily_symbols:
        progress(1, 3, "Repairing bounded US index Daily history.")
        daily_result = daily_reconciler(
            max_runtime_seconds=max_runtime_seconds,
            max_symbols=len(PRIORITY_US_INDEX_SYMBOLS),
            max_external_calls=daily_max_external_calls,
            max_provider_attempts=2,
            requested_at=requested_at,
            repair=True,
        )

    if missing_quote_symbols:
        progress(2, 3, "Repairing bounded US index Quote snapshots.")
        quote_result = quote_materializer(
            "quote.snapshot",
            configured_symbols=",".join(missing_quote_symbols),
            max_symbols=len(PRIORITY_US_INDEX_SYMBOLS),
            max_provider_calls=2,
            max_external_calls=quote_max_external_calls,
            lane_id="index_repair_gate",
            instrument_type="index",
            profile=US_BOOTSTRAP_INTRADAY_PROFILE,
            now=requested_at,
        )

    db.expire_all()
    verification_at = datetime.now(timezone.utc)
    final = audit_us_index_data(db, now=verification_at)
    result = {
        "contract_version": "omi.us.index_data_repair_gate.run.v1",
        "status": "completed" if final["postcondition_satisfied"] else "partial",
        "requested_at": requested_at,
        "verified_at": verification_at,
        "initial_audit": initial,
        "daily_repair": daily_result,
        "quote_repair": quote_result,
        "final_audit": final,
        "daily_external_call_budget": daily_max_external_calls,
        "quote_external_call_budget": quote_max_external_calls,
        "external_call_budget": (
            daily_max_external_calls + quote_max_external_calls
        ),
    }
    _record_decision(
        {
            "status": result["status"],
            "checked_at": final["checked_at"],
            "missing_count": final["missing_count"],
            "missing_daily_symbols": final["missing_daily_symbols"],
            "missing_quote_symbols": final["missing_quote_symbols"],
        }
    )
    progress(3, 3, "Verified persisted US index repair postconditions.")
    if not final["postcondition_satisfied"]:
        raise job_service.JobExecutionError(
            "US index repair left canonical postconditions unsatisfied.",
            result=result,
        )
    return result


def run_us_index_data_repair_job(
    job_id: int,
    requested_at: str,
    missing_daily_symbols: list[str],
    missing_quote_symbols: list[str],
    daily_max_external_calls: int,
    quote_max_external_calls: int,
    max_runtime_seconds: int,
) -> None:
    parsed_requested_at = datetime.fromisoformat(requested_at)
    job_service.run_tracked_job(
        job_id,
        lambda db, progress: repair_us_index_data(
            db,
            progress,
            requested_at=parsed_requested_at,
            missing_daily_symbols=missing_daily_symbols,
            missing_quote_symbols=missing_quote_symbols,
            daily_max_external_calls=daily_max_external_calls,
            quote_max_external_calls=quote_max_external_calls,
            max_runtime_seconds=max_runtime_seconds,
        ),
    )


def reconcile_us_index_data_repair_gate(
    db: Session,
    *,
    now: datetime | None = None,
    trigger: str = "interval",
) -> dict[str, Any]:
    """Queue at most one bounded tracked repair after a cache-only audit."""

    requested_at = _utc(now) or datetime.now(timezone.utc)
    decision = plan_us_index_data_repair(db, now=requested_at)
    if decision["status"] != "ready":
        summary = {
            "status": decision["status"],
            "reason": decision["reason"],
            "checked_at": requested_at,
            "target": decision["target"],
            "missing_count": decision["audit"]["missing_count"],
            "attempt_count": decision.get("attempt_count"),
            "attempts_since_success": decision.get("attempts_since_success"),
            "attempts_in_current_window": decision.get(
                "attempts_in_current_window"
            ),
            "retry_at": decision.get("retry_at"),
        }
        _record_decision(summary)
        return decision

    audit = decision["audit"]
    request = {
        "contract_version": "omi.us.index_data_repair_gate.request.v1",
        "trigger": trigger,
        "requested_at": requested_at.isoformat(),
        "attempt": decision["next_attempt"],
        "attempt_in_window": decision["next_attempt_in_window"],
        "max_attempts": decision["max_attempts"],
        "symbols": list(PRIORITY_US_INDEX_SYMBOLS),
        "missing_daily_symbols": audit["missing_daily_symbols"],
        "missing_quote_symbols": audit["missing_quote_symbols"],
        "daily_max_external_calls": int(
            settings.scheduler_us_index_data_repair_daily_max_external_calls
        ),
        "quote_max_external_calls": int(
            settings.scheduler_us_index_data_repair_quote_max_external_calls
        ),
        "max_runtime_seconds": int(
            settings.scheduler_us_index_data_repair_max_runtime_seconds
        ),
    }
    task_args = (
        request["requested_at"],
        request["missing_daily_symbols"],
        request["missing_quote_symbols"],
        request["daily_max_external_calls"],
        request["quote_max_external_calls"],
        request["max_runtime_seconds"],
    )
    job, created = job_service.enqueue_job(
        db=db,
        job_type=US_INDEX_DATA_REPAIR_JOB_TYPE,
        target=decision["target"],
        request=request,
        progress_total=3,
        message="Queued by bounded US index missing-data repair gate.",
        task=run_us_index_data_repair_job,
        task_args=task_args,
    )
    outcome = {
        **decision,
        "status": "queued" if created else "leased",
        "reason": "repair_enqueued" if created else "deduped_by_job_service",
        "job_id": job.id,
        "request": request,
    }
    _record_decision(
        {
            "status": outcome["status"],
            "reason": outcome["reason"],
            "checked_at": requested_at,
            "target": decision["target"],
            "job_id": job.id,
            "missing_count": audit["missing_count"],
        }
    )
    return outcome


def enqueue_us_index_data_repair_gate() -> None:
    db = SessionLocal()
    try:
        result = reconcile_us_index_data_repair_gate(db)
        logger.info(
            "US index repair gate status=%s reason=%s job_id=%s missing=%s.",
            result["status"],
            result["reason"],
            result.get("job_id"),
            result["audit"]["missing_count"],
        )
    except Exception:
        logger.exception("Failed to reconcile the US index repair gate.")
    finally:
        db.close()


__all__ = [
    "audit_us_index_data",
    "enqueue_us_index_data_repair_gate",
    "plan_us_index_data_repair",
    "reconcile_us_index_data_repair_gate",
    "repair_us_index_data",
    "run_us_index_data_repair_job",
    "us_index_data_repair_runtime_summary",
]
