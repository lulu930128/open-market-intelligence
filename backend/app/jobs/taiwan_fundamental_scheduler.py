from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from app.config import settings
from app.db.models import ProviderEvent
from app.db.session import SessionLocal
from app.jobs import backfill_tasks, service as job_service
from app.market.taiwan_rules import (
    TAIWAN_DATASET_FINANCIAL_METRICS,
    TAIWAN_DATASET_MONTHLY_REVENUE,
    TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
    expected_financial_metrics_period,
    expected_monthly_revenue_period,
    expected_shareholding_distribution_date,
)
from app.market.trading_calendar import TAIWAN_TZ


logger = logging.getLogger(__name__)


def _parse_hour_minute(value: str) -> tuple[int, int]:
    parts = value.split(":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Expected HH:MM format.")
    hour, minute = int(parts[0]), int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Expected HH:MM within a 24-hour clock.")
    return hour, minute


def _previous_month_period(current: date) -> date:
    if current.month == 1:
        return date(current.year - 1, 12, 1)
    return date(current.year, current.month - 1, 1)


def _completion_target(scope: str, expected_key: str) -> str:
    return f"{scope}:{expected_key}"


def _completed_event_exists(
    db,
    *,
    dataset: str,
    completion_target: str,
) -> bool:
    return (
        db.query(ProviderEvent.id)
        .filter(ProviderEvent.market == "tw")
        .filter(ProviderEvent.resource == dataset)
        .filter(ProviderEvent.target == completion_target)
        .filter(ProviderEvent.event_type == "scheduled_collection")
        .filter(ProviderEvent.status == "success")
        .first()
        is not None
    )


def _enqueue_snapshot(
    *,
    category: str,
    dataset: str,
    expected_key: str,
    scope: str,
    schedule: str,
    sleep_seconds: float = 0.2,
) -> None:
    completion_target = _completion_target(scope, expected_key)
    db = SessionLocal()
    try:
        if _completed_event_exists(
            db,
            dataset=dataset,
            completion_target=completion_target,
        ):
            logger.info(
                "Skipped Taiwan %s scheduled snapshot because target=%s is already complete.",
                category,
                completion_target,
            )
            return

        request = {
            "schedule": schedule,
            "category": category,
            "dataset": dataset,
            "expected_key": expected_key,
            "completion_target": completion_target,
            "sleep_seconds": sleep_seconds,
        }
        job, created = job_service.enqueue_job(
            db=db,
            job_type=f"scheduler.tw_stock_detail_{category}_refresh",
            target=completion_target,
            request=request,
            progress_total=1,
            message="Queued by Taiwan stock-detail scheduler.",
            task=backfill_tasks.run_taiwan_fundamental_snapshot_refresh_job,
            task_args=(
                category,
                dataset,
                expected_key,
                completion_target,
                sleep_seconds,
            ),
        )
        logger.info(
            "Taiwan %s scheduled snapshot %s job_id=%s target=%s.",
            category,
            "queued" if created else "deduped",
            job.id,
            completion_target,
        )
    finally:
        db.close()


def enqueue_taiwan_shareholding_snapshot_refresh() -> None:
    now = datetime.now(TAIWAN_TZ)
    expected_key = expected_shareholding_distribution_date(now=now).isoformat()
    _enqueue_snapshot(
        category="shareholding_distribution",
        dataset=TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
        expected_key=expected_key,
        scope="market",
        schedule="tw_shareholding_release_plus_5",
    )


def enqueue_taiwan_revenue_regular_deadline_refresh() -> None:
    now = datetime.now(TAIWAN_TZ)
    expected_key = _previous_month_period(now.date()).isoformat()
    _enqueue_snapshot(
        category="monthly_revenue",
        dataset=TAIWAN_DATASET_MONTHLY_REVENUE,
        expected_key=expected_key,
        scope="regular",
        schedule="tw_revenue_regular_deadline_plus_5",
    )


def enqueue_taiwan_revenue_market_deadline_refresh() -> None:
    now = datetime.now(TAIWAN_TZ)
    expected_key = expected_monthly_revenue_period(now=now).isoformat()
    _enqueue_snapshot(
        category="monthly_revenue",
        dataset=TAIWAN_DATASET_MONTHLY_REVENUE,
        expected_key=expected_key,
        scope="market",
        schedule="tw_revenue_market_deadline_plus_5",
    )


def enqueue_taiwan_financial_deadline_refresh() -> None:
    now = datetime.now(TAIWAN_TZ)
    expected_key = expected_financial_metrics_period(now=now)
    _enqueue_snapshot(
        category="financial_metrics",
        dataset=TAIWAN_DATASET_FINANCIAL_METRICS,
        expected_key=expected_key,
        scope="market",
        schedule="tw_financial_deadline_plus_5",
    )


def enqueue_taiwan_fundamental_startup_catchup() -> None:
    enqueue_taiwan_shareholding_snapshot_refresh()
    enqueue_taiwan_revenue_market_deadline_refresh()
    enqueue_taiwan_financial_deadline_refresh()


def _bounded_hour_expression(start_hour: int, end_hour: int) -> str | int:
    if start_hour >= end_hour:
        return start_hour
    return f"{start_hour}-{end_hour}"


def add_taiwan_fundamental_refresh_jobs(scheduler: Any) -> bool:
    if not settings.enable_tw_stock_detail_scheduler:
        return False

    shareholding_hour, shareholding_minute = _parse_hour_minute(
        settings.scheduler_tw_shareholding_refresh_time
    )
    revenue_hour, revenue_minute = _parse_hour_minute(
        settings.scheduler_tw_revenue_refresh_time
    )
    financial_hour, financial_minute = _parse_hour_minute(
        settings.scheduler_tw_financial_refresh_time
    )
    scheduler.add_job(
        enqueue_taiwan_shareholding_snapshot_refresh,
        trigger="cron",
        day_of_week="sat",
        hour=_bounded_hour_expression(shareholding_hour, 18),
        minute=shareholding_minute,
        id="tw_shareholding_snapshot_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_taiwan_revenue_regular_deadline_refresh,
        trigger="cron",
        day=11,
        hour=_bounded_hour_expression(revenue_hour, 3),
        minute=revenue_minute,
        id="tw_revenue_regular_deadline_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_taiwan_revenue_market_deadline_refresh,
        trigger="cron",
        day=16,
        hour=_bounded_hour_expression(revenue_hour, 3),
        minute=revenue_minute,
        id="tw_revenue_market_deadline_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    for month, day, suffix in (
        (4, 1, "annual"),
        (5, 16, "q1"),
        (8, 15, "q2"),
        (11, 15, "q3"),
    ):
        scheduler.add_job(
            enqueue_taiwan_financial_deadline_refresh,
            trigger="cron",
            month=month,
            day=day,
            hour=_bounded_hour_expression(financial_hour, 3),
            minute=financial_minute,
            id=f"tw_financial_{suffix}_deadline_refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    scheduler.add_job(
        enqueue_taiwan_fundamental_startup_catchup,
        trigger="date",
        run_date=datetime.now(TAIWAN_TZ) + timedelta(seconds=5),
        id="tw_fundamental_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


__all__ = [
    "add_taiwan_fundamental_refresh_jobs",
    "enqueue_taiwan_financial_deadline_refresh",
    "enqueue_taiwan_fundamental_startup_catchup",
    "enqueue_taiwan_revenue_market_deadline_refresh",
    "enqueue_taiwan_revenue_regular_deadline_refresh",
    "enqueue_taiwan_shareholding_snapshot_refresh",
]
