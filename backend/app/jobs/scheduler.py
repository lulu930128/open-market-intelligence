from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.session import SessionLocal
from app.jobs import backfill_tasks, service as job_service
from app.market.market_chips import normalize_market_chip_index_ids
from app.market.trading_calendar import is_taiwan_trading_day


logger = logging.getLogger(__name__)


def _parse_hour_minute(value: str) -> tuple[int, int]:
    parts = value.split(":", maxsplit=1)

    if len(parts) != 2:
        raise ValueError("Expected HH:MM format.")

    hour = int(parts[0])
    minute = int(parts[1])

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Expected HH:MM within a 24-hour clock.")

    return hour, minute


def _timezone() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def enqueue_market_daily_refresh() -> None:
    categories = ["institutional_trade", "margin_trading"]
    now = datetime.now(_timezone())

    if not is_taiwan_trading_day(now.date()):
        logger.info("Skipped scheduled market daily refresh because %s is not a trading day.", now.date())
        return

    request = {
        "schedule": "market_daily_refresh",
        "run_date": now.date().isoformat(),
        "categories": categories,
        "lookback_days": settings.scheduler_market_refresh_lookback_days,
        "include_today": True,
        "sleep_seconds": settings.scheduler_market_refresh_sleep_seconds,
        "skip_existing": True,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type="scheduler.market_daily_refresh",
            target="market",
            request=request,
            progress_total=1,
            message="Queued by scheduler.",
            task=backfill_tasks.run_market_daily_metrics_job,
            task_args=(
                None,
                None,
                categories,
                settings.scheduler_market_refresh_lookback_days,
                True,
                settings.scheduler_market_refresh_sleep_seconds,
                True,
            ),
        )
        logger.info(
            "Scheduled market daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_market_chip_daily_refresh() -> None:
    now = datetime.now(_timezone())

    if not is_taiwan_trading_day(now.date()):
        logger.info(
            "Skipped scheduled market chip daily refresh because %s is not a trading day.",
            now.date(),
        )
        return

    try:
        index_ids = normalize_market_chip_index_ids(
            _split_csv(settings.scheduler_market_chip_refresh_index_ids)
        )
    except ValueError as exc:
        logger.error("Skipped scheduled market chip daily refresh: %s", exc)
        return

    request = {
        "schedule": "market_chip_daily_refresh",
        "run_date": now.date().isoformat(),
        "index_ids": index_ids,
        "trade_date": now.date(),
        "include_today": True,
        "force": settings.scheduler_market_chip_refresh_force,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type="scheduler.market_chip_daily_refresh",
            target="market-chips",
            request=request,
            progress_total=len(index_ids),
            message="Queued by scheduler.",
            task=backfill_tasks.run_market_chip_daily_refresh_job,
            task_args=(
                index_ids,
                now.date(),
                True,
                settings.scheduler_market_chip_refresh_force,
            ),
        )
        logger.info(
            "Scheduled market chip daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_us_market_daily_refresh() -> None:
    now = datetime.now(_timezone())
    request = {
        "schedule": "us_market_daily_refresh",
        "run_date": now.date().isoformat(),
        "group_id": None,
        "include_children": True,
        "enabled_only": True,
        "outputsize": settings.scheduler_us_market_refresh_outputsize,
        "adjusted": settings.scheduler_us_market_refresh_adjusted,
        "sleep_seconds": settings.scheduler_us_market_refresh_sleep_seconds,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type="scheduler.us_market_daily_refresh",
            target="all",
            request=request,
            progress_total=1,
            message="Queued by scheduler.",
            task=backfill_tasks.run_us_watchlist_daily_refresh_job,
            task_args=(
                None,
                True,
                True,
                settings.scheduler_us_market_refresh_outputsize,
                settings.scheduler_us_market_refresh_adjusted,
                settings.scheduler_us_market_refresh_sleep_seconds,
            ),
        )
        logger.info(
            "Scheduled US market daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def start_scheduler() -> Any | None:
    if not settings.enable_scheduler:
        logger.info("Job scheduler disabled.")
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler is not installed; job scheduler disabled.")
        return None

    hour, minute = _parse_hour_minute(settings.scheduler_market_refresh_time)
    chip_hour, chip_minute = _parse_hour_minute(
        settings.scheduler_market_chip_refresh_time
    )
    scheduler = BackgroundScheduler(timezone=_timezone())
    scheduler.add_job(
        enqueue_market_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id="market_daily_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_market_chip_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=chip_hour,
        minute=chip_minute,
        id="market_chip_daily_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    if settings.enable_us_market_scheduler:
        us_hour, us_minute = _parse_hour_minute(settings.scheduler_us_market_refresh_time)
        scheduler.add_job(
            enqueue_us_market_daily_refresh,
            trigger="cron",
            day_of_week=settings.scheduler_us_market_refresh_day_of_week,
            hour=us_hour,
            minute=us_minute,
            id="us_market_daily_refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    logger.info(
        "Job scheduler started. market_daily_refresh=%s %s weekdays; market_chip_daily_refresh=%s %s weekdays; us_market_daily_refresh=%s %s %s enabled=%s.",
        settings.scheduler_market_refresh_time,
        settings.timezone,
        settings.scheduler_market_chip_refresh_time,
        settings.timezone,
        settings.scheduler_us_market_refresh_time,
        settings.scheduler_us_market_refresh_day_of_week,
        settings.timezone,
        settings.enable_us_market_scheduler,
    )
    return scheduler


def stop_scheduler(scheduler: Any | None) -> None:
    if scheduler is None:
        return

    scheduler.shutdown(wait=False)
    logger.info("Job scheduler stopped.")
