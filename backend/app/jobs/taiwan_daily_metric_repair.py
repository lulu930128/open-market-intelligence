from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JobRun
from app.jobs import backfill_tasks, service as job_service
from app.market.calendar_status import (
    build_taiwan_calendar_status,
    expected_trade_date_from_calendar,
    is_release_released_from_calendar,
)
from app.market.daily_metrics_backfill import evaluate_daily_metrics_postcondition
from app.market.taiwan_rules import (
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
)
from app.settings.refresh_execution import resolve_market_refresh_interval_seconds


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaiwanDailyMetricRepairSpec:
    job_type: str
    schedule: str
    category: str
    dataset_key: str


REPAIR_SPECS = (
    TaiwanDailyMetricRepairSpec(
        job_type="scheduler.market_daily_refresh",
        schedule="market_daily_refresh",
        category=TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
        dataset_key=TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    ),
    TaiwanDailyMetricRepairSpec(
        job_type="scheduler.market_margin_daily_refresh",
        schedule="market_margin_daily_refresh",
        category=TAIWAN_REFRESH_MARGIN_TRADING,
        dataset_key=TAIWAN_DATASET_MARGIN_TRADING,
    ),
)


def _timezone() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _request_dict(job: JobRun) -> dict[str, Any]:
    try:
        value = json.loads(job.request_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _repair_dict(job: JobRun) -> dict[str, Any]:
    value = _request_dict(job).get("repair")
    return value if isinstance(value, dict) else {}


def _repair_key(spec: TaiwanDailyMetricRepairSpec, expected_trade_date: date) -> str:
    return f"{spec.dataset_key}:{expected_trade_date.isoformat()}"


def _backoff_seconds(attempt: int) -> int:
    base = max(int(settings.scheduler_market_daily_repair_base_backoff_seconds), 60)
    ceiling = max(int(settings.scheduler_market_daily_repair_max_backoff_seconds), base)
    return min(base * (2 ** max(attempt - 1, 0)), ceiling)


def _provider_cooldown(
    postcondition: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    cooldown_seconds = max(
        int(settings.scheduler_market_daily_repair_provider_cooldown_seconds),
        60,
    )
    guarded_sources: list[dict[str, Any]] = []
    retry_at: datetime | None = None

    for source in postcondition.get("sources") or []:
        if source.get("satisfied"):
            continue
        last_error_at = _utc(source.get("last_error_at"))
        last_success_at = _utc(source.get("last_success_at"))
        if last_error_at is None or (
            last_success_at is not None and last_success_at >= last_error_at
        ):
            continue
        candidate_retry_at = last_error_at + timedelta(seconds=cooldown_seconds)
        if candidate_retry_at <= now:
            continue
        message = str(source.get("last_error_message") or "")
        normalized_message = message.lower()
        guarded_sources.append(
            {
                "source_id": source.get("source_id"),
                "source_name": source.get("source_name"),
                "last_error_at": last_error_at,
                "last_error_message": message or None,
                "circuit_open": any(
                    marker in normalized_message
                    for marker in ("circuit", "rate limit", "429", "too many requests")
                ),
            }
        )
        retry_at = max(retry_at, candidate_retry_at) if retry_at else candidate_retry_at

    return {
        "status": "cooldown" if guarded_sources else "available",
        "retry_at": retry_at,
        "sources": guarded_sources,
    }


def plan_taiwan_daily_metric_repair(
    db: Session,
    *,
    spec: TaiwanDailyMetricRepairSpec,
    expected_trade_date: date,
    now: datetime,
) -> dict[str, Any]:
    """Build a deterministic, read-only repair decision for one dataset/date."""

    now_utc = _utc(now) or now.replace(tzinfo=timezone.utc)
    target = expected_trade_date.isoformat()
    repair_key = _repair_key(spec, expected_trade_date)
    postcondition = evaluate_daily_metrics_postcondition(
        db,
        categories=[spec.category],
        expected_trade_date=expected_trade_date,
    )
    base = {
        "repair_key": repair_key,
        "job_type": spec.job_type,
        "dataset_key": spec.dataset_key,
        "category": spec.category,
        "target": target,
        "expected_trade_date": expected_trade_date,
        "postcondition": postcondition,
    }
    if postcondition["postcondition_met"]:
        return {**base, "status": "resolved", "reason": "postcondition_satisfied"}

    active_job = job_service.find_active_job_by_target(db, spec.job_type, target)
    if active_job is not None:
        return {
            **base,
            "status": "leased",
            "reason": "active_job",
            "active_job_id": active_job.id,
        }

    rows = (
        db.query(JobRun)
        .filter(JobRun.job_type == spec.job_type, JobRun.target == target)
        .order_by(JobRun.created_at.asc(), JobRun.id.asc())
        .limit(100)
        .all()
    )
    repair_jobs = [
        row
        for row in rows
        if _repair_dict(row).get("repair_key") == repair_key
    ]
    attempt_count = len(repair_jobs)
    max_attempts = max(int(settings.scheduler_market_daily_repair_max_attempts), 1)
    first_detected_at = next(
        (
            _repair_dict(row).get("detected_at")
            for row in repair_jobs
            if _repair_dict(row).get("detected_at")
        ),
        None,
    )
    if first_detected_at is None:
        first_detected_at = (
            _utc(rows[0].created_at).isoformat() if rows and rows[0].created_at else now_utc.isoformat()
        )
    last_job = rows[-1] if rows else None
    last_error = last_job.error_message if last_job is not None else None

    if attempt_count >= max_attempts:
        return {
            **base,
            "status": "exhausted",
            "reason": "max_attempts_reached",
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "detected_at": first_detected_at,
            "last_error": last_error,
        }

    next_retry_at: datetime | None = None
    if repair_jobs:
        latest_repair = repair_jobs[-1]
        latest_end = _utc(latest_repair.ended_at or latest_repair.updated_at)
        if latest_end is not None:
            next_retry_at = latest_end + timedelta(
                seconds=_backoff_seconds(attempt_count)
            )

    provider_guard = _provider_cooldown(postcondition, now=now_utc)
    provider_retry_at = provider_guard.get("retry_at")
    if provider_retry_at is not None:
        next_retry_at = (
            max(next_retry_at, provider_retry_at)
            if next_retry_at is not None
            else provider_retry_at
        )

    decision = {
        **base,
        "attempt_count": attempt_count,
        "next_attempt": attempt_count + 1,
        "max_attempts": max_attempts,
        "detected_at": first_detected_at,
        "last_error": last_error,
        "next_retry_at": next_retry_at,
        "provider_guard": provider_guard,
    }
    if next_retry_at is not None and now_utc < next_retry_at:
        return {
            **decision,
            "status": "suppressed",
            "reason": (
                "provider_cooldown"
                if provider_guard["status"] == "cooldown"
                else "retry_backoff"
            ),
        }
    return {**decision, "status": "ready", "reason": "postcondition_missing"}


def reconcile_taiwan_daily_metric_repairs(
    db: Session,
    *,
    now: datetime | None = None,
    trigger: str = "interval",
) -> dict[str, Any]:
    """Queue bounded repairs only after release-aware outcome truth is known."""

    current = now or datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=current)
    sleep_seconds = resolve_market_refresh_interval_seconds(db=db, market="tw")
    decisions: list[dict[str, Any]] = []

    for spec in REPAIR_SPECS:
        expected_trade_date = expected_trade_date_from_calendar(
            calendar_status,
            market="tw",
            key=spec.dataset_key,
        )
        released = is_release_released_from_calendar(
            calendar_status,
            market="tw",
            key=spec.dataset_key,
        )
        if expected_trade_date is None or not released:
            decisions.append(
                {
                    "dataset_key": spec.dataset_key,
                    "status": "not_due",
                    "reason": "release_pending",
                    "expected_trade_date": expected_trade_date,
                }
            )
            continue

        decision = plan_taiwan_daily_metric_repair(
            db,
            spec=spec,
            expected_trade_date=expected_trade_date,
            now=current,
        )
        if decision["status"] != "ready":
            decisions.append(decision)
            continue

        repair_context = {
            "repair_key": decision["repair_key"],
            "detected_at": decision["detected_at"],
            "attempt": decision["next_attempt"],
            "max_attempts": decision["max_attempts"],
            "next_retry_at": (
                (_utc(current) or current.replace(tzinfo=timezone.utc))
                + timedelta(seconds=_backoff_seconds(decision["next_attempt"]))
            ),
            "last_error": decision["last_error"],
            "dataset_key": spec.dataset_key,
            "category": spec.category,
            "trigger": trigger,
            "lease_key": f"{spec.job_type}:{expected_trade_date.isoformat()}",
            "lease_acquired_at": _utc(current) or current.replace(tzinfo=timezone.utc),
            "provider_guard": decision["provider_guard"],
        }
        request = {
            "schedule": spec.schedule,
            "start_date": expected_trade_date,
            "end_date": expected_trade_date,
            "categories": [spec.category],
            "lookback_days": 1,
            "include_today": True,
            "expected_trade_date": expected_trade_date,
            "sleep_seconds": sleep_seconds,
            "skip_existing": True,
            "repair": repair_context,
        }
        job, created = job_service.enqueue_job(
            db=db,
            job_type=spec.job_type,
            target=expected_trade_date.isoformat(),
            request=request,
            progress_total=1,
            message="Queued by bounded Taiwan daily-metric repair controller.",
            task=backfill_tasks.run_market_daily_metrics_job,
            task_args=(
                expected_trade_date,
                expected_trade_date,
                [spec.category],
                1,
                True,
                sleep_seconds,
                True,
                expected_trade_date,
                repair_context,
            ),
        )
        decisions.append(
            {
                **decision,
                "status": "queued" if created else "leased",
                "reason": "repair_enqueued" if created else "deduped_by_job_service",
                "job_id": job.id,
                "repair": repair_context,
            }
        )

    return {
        "kind": "taiwan_daily_metric_repair_reconciliation",
        "trigger": trigger,
        "checked_at": current,
        "calendar_phase": calendar_status.get("phase"),
        "decisions": decisions,
        "queued_count": sum(item.get("status") == "queued" for item in decisions),
    }


__all__ = [
    "REPAIR_SPECS",
    "TaiwanDailyMetricRepairSpec",
    "plan_taiwan_daily_metric_repair",
    "reconcile_taiwan_daily_metric_repairs",
]
