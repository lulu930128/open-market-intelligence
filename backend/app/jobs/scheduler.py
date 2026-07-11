from datetime import datetime, time, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.session import SessionLocal
from app.jobs import backfill_tasks, service as job_service
from app.jobs.job_types import (
    JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    KR_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE,
)
from app.market.calendar_status import (
    build_taiwan_calendar_status,
    build_us_calendar_status,
    expected_trade_date_from_calendar,
    is_release_released_from_calendar,
)
from app.market.market_chips import normalize_market_chip_index_ids
from app.market.taiwan_rules import (
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
)
from app.market.trading_calendar import is_taiwan_trading_day
from app.market.tw_futures import (
    TaiwanFuturesFetchError,
    refresh_taiwan_futures_quotes,
    resolve_taiwan_futures_quote_provider,
)
from app.observability.provider_health import record_provider_event
from app.settings.refresh_execution import resolve_market_refresh_interval_seconds


logger = logging.getLogger(__name__)
TAIWAN_FUTURES_REGULAR_START = time(8, 40)
TAIWAN_FUTURES_REGULAR_END = time(13, 50)
TAIWAN_FUTURES_AFTER_HOURS_START = time(15, 0)
TAIWAN_FUTURES_AFTER_HOURS_END = time(5, 10)
TAIWAN_REFRESH_CATEGORY_DATASET_KEYS = {
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE: TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING: TAIWAN_DATASET_MARGIN_TRADING,
}
_LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT: datetime | None = None


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


def _is_taiwan_futures_live_window(now: datetime) -> bool:
    local_now = now.astimezone(_timezone()) if now.tzinfo else now.replace(tzinfo=_timezone())
    current_date = local_now.date()
    current_time = local_now.time()

    if TAIWAN_FUTURES_REGULAR_START <= current_time <= TAIWAN_FUTURES_REGULAR_END:
        return is_taiwan_trading_day(current_date)

    if current_time >= TAIWAN_FUTURES_AFTER_HOURS_START:
        return is_taiwan_trading_day(current_date)

    if current_time <= TAIWAN_FUTURES_AFTER_HOURS_END:
        previous_date = current_date - timedelta(days=1)
        return is_taiwan_trading_day(previous_date)

    return False


def _should_record_taiwan_futures_success(now: datetime) -> bool:
    global _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT

    interval_seconds = max(
        int(settings.scheduler_taiwan_futures_success_event_interval_seconds),
        0,
    )
    if interval_seconds == 0:
        _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT = now
        return True

    if _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT is None:
        _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT = now
        return True

    if (now - _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT).total_seconds() >= interval_seconds:
        _LAST_TAIWAN_FUTURES_SUCCESS_EVENT_AT = now
        return True

    return False


def _record_taiwan_futures_provider_event(
    db,
    *,
    provider: str,
    status: str,
    symbols: list[str],
    message: str | None = None,
    error_message: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        record_provider_event(
            db,
            market="tw",
            provider=provider,
            resource="tw_futures_quote",
            target=",".join(symbols) if symbols else "all",
            status=status,
            event_type="poll",
            message=message,
            error_message=error_message,
            detail=detail,
        )
    except Exception:
        db.rollback()
        logger.warning("Failed to record Taiwan futures provider event.", exc_info=True)


def enqueue_market_daily_refresh() -> None:
    categories = [TAIWAN_REFRESH_INSTITUTIONAL_TRADE]
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled market daily refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    sleep_seconds = resolve_market_refresh_interval_seconds(market="tw")
    include_today = all(
        is_release_released_from_calendar(
            calendar_status,
            market="tw",
            key=TAIWAN_REFRESH_CATEGORY_DATASET_KEYS[category],
        )
        for category in categories
    )

    request = {
        "schedule": "market_daily_refresh",
        "run_date": now.date().isoformat(),
        "categories": categories,
        "lookback_days": settings.scheduler_market_refresh_lookback_days,
        "include_today": include_today,
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_windows": {
            dataset_key: calendar_status.get("release_windows", {}).get(dataset_key)
            for dataset_key in TAIWAN_REFRESH_CATEGORY_DATASET_KEYS.values()
        },
        "sleep_seconds": sleep_seconds,
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
                include_today,
                sleep_seconds,
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


def enqueue_market_margin_daily_refresh() -> None:
    categories = [TAIWAN_REFRESH_MARGIN_TRADING]
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled market margin daily refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    sleep_seconds = resolve_market_refresh_interval_seconds(market="tw")
    include_today = all(
        is_release_released_from_calendar(
            calendar_status,
            market="tw",
            key=TAIWAN_REFRESH_CATEGORY_DATASET_KEYS[category],
        )
        for category in categories
    )

    request = {
        "schedule": "market_margin_daily_refresh",
        "run_date": now.date().isoformat(),
        "categories": categories,
        "lookback_days": settings.scheduler_market_refresh_lookback_days,
        "include_today": include_today,
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_windows": {
            dataset_key: calendar_status.get("release_windows", {}).get(dataset_key)
            for dataset_key in TAIWAN_REFRESH_CATEGORY_DATASET_KEYS.values()
        },
        "sleep_seconds": sleep_seconds,
        "skip_existing": True,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type="scheduler.market_margin_daily_refresh",
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
                include_today,
                sleep_seconds,
                True,
            ),
        )
        logger.info(
            "Scheduled market margin daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_market_chip_daily_refresh() -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled market chip daily refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    try:
        index_ids = normalize_market_chip_index_ids(
            _split_csv(settings.scheduler_market_chip_refresh_index_ids)
        )
    except ValueError as exc:
        logger.error("Skipped scheduled market chip daily refresh: %s", exc)
        return

    trade_date = expected_trade_date_from_calendar(
        calendar_status,
        market="tw",
        key="market_chip_daily",
    ) or now.date()
    include_today = is_release_released_from_calendar(
        calendar_status,
        market="tw",
        key="market_chip_daily",
    )

    request = {
        "schedule": "market_chip_daily_refresh",
        "run_date": now.date().isoformat(),
        "index_ids": index_ids,
        "trade_date": trade_date,
        "include_today": include_today,
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_window": calendar_status.get("release_windows", {}).get("market_chip_daily"),
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
                trade_date,
                include_today,
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


def enqueue_market_chip_margin_daily_refresh() -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled market chip margin daily refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    try:
        index_ids = normalize_market_chip_index_ids(
            _split_csv(settings.scheduler_market_chip_refresh_index_ids)
        )
    except ValueError as exc:
        logger.error("Skipped scheduled market chip margin daily refresh: %s", exc)
        return

    trade_date = expected_trade_date_from_calendar(
        calendar_status,
        market="tw",
        key="market_chip_margin_daily",
    ) or now.date()
    include_today = is_release_released_from_calendar(
        calendar_status,
        market="tw",
        key="market_chip_margin_daily",
    )

    request = {
        "schedule": "market_chip_margin_daily_refresh",
        "run_date": now.date().isoformat(),
        "index_ids": index_ids,
        "trade_date": trade_date,
        "include_today": include_today,
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_window": calendar_status.get("release_windows", {}).get(
            "market_chip_margin_daily"
        ),
        "force": settings.scheduler_market_chip_refresh_force,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type="scheduler.market_chip_margin_daily_refresh",
            target="market-chips",
            request=request,
            progress_total=len(index_ids),
            message="Queued by scheduler.",
            task=backfill_tasks.run_market_chip_daily_refresh_job,
            task_args=(
                index_ids,
                trade_date,
                include_today,
                settings.scheduler_market_chip_refresh_force,
            ),
        )
        logger.info(
            "Scheduled market chip margin daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_us_market_daily_refresh() -> None:
    now = datetime.now(_timezone())
    calendar_status = build_us_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled US market daily refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    sleep_seconds = resolve_market_refresh_interval_seconds(market="us")
    request = {
        "schedule": "us_market_daily_refresh",
        "run_date": now.date().isoformat(),
        "market_date": calendar_status.get("date"),
        "expected_trade_date": expected_trade_date_from_calendar(
            calendar_status,
            market="us",
            key="us_daily_price",
        ),
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_window": calendar_status.get("release_windows", {}).get("us_daily_price"),
        "group_id": None,
        "include_children": True,
        "enabled_only": True,
        "outputsize": settings.scheduler_us_market_refresh_outputsize,
        "adjusted": settings.scheduler_us_market_refresh_adjusted,
        "sleep_seconds": sleep_seconds,
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
                sleep_seconds,
            ),
        )
        logger.info(
            "Scheduled US market daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_jp_market_watchlist_resource_refresh() -> None:
    now = datetime.now(_timezone())
    sleep_seconds = resolve_market_refresh_interval_seconds(market="jp")
    request = {
        "schedule": "jp_market_watchlist_resource_refresh",
        "run_date": now.date().isoformat(),
        "group_id": None,
        "include_children": True,
        "enabled_only": True,
        "include_daily": True,
        "include_fundamentals": settings.scheduler_jp_market_refresh_include_fundamentals,
        "outputsize": settings.scheduler_jp_market_refresh_outputsize,
        "provider": settings.scheduler_jp_market_refresh_provider,
        "sleep_seconds": sleep_seconds,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type=JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
            target="all",
            request=request,
            progress_total=1,
            message="Queued by scheduler.",
            task=backfill_tasks.run_jp_watchlist_resource_refresh_job,
            task_args=(
                None,
                True,
                True,
                True,
                settings.scheduler_jp_market_refresh_include_fundamentals,
                settings.scheduler_jp_market_refresh_outputsize,
                settings.scheduler_jp_market_refresh_provider,
                sleep_seconds,
            ),
        )
        logger.info(
            "Scheduled JP market watchlist resource refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_kr_market_watchlist_resource_refresh() -> None:
    now = datetime.now(_timezone())
    sleep_seconds = resolve_market_refresh_interval_seconds(market="kr")
    request = {
        "schedule": "kr_market_watchlist_resource_refresh",
        "run_date": now.date().isoformat(),
        "group_id": None,
        "include_children": True,
        "enabled_only": True,
        "include_daily": True,
        "include_investors": settings.scheduler_kr_market_refresh_include_investors,
        "include_fundamentals": settings.scheduler_kr_market_refresh_include_fundamentals,
        "outputsize": settings.scheduler_kr_market_refresh_outputsize,
        "provider": settings.scheduler_kr_market_refresh_provider,
        "sleep_seconds": sleep_seconds,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type=KR_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
            target="all",
            request=request,
            progress_total=1,
            message="Queued by scheduler.",
            task=backfill_tasks.run_kr_watchlist_resource_refresh_job,
            task_args=(
                None,
                True,
                True,
                True,
                settings.scheduler_kr_market_refresh_include_investors,
                settings.scheduler_kr_market_refresh_include_fundamentals,
                settings.scheduler_kr_market_refresh_outputsize,
                settings.scheduler_kr_market_refresh_provider,
                sleep_seconds,
                None,
            ),
        )
        logger.info(
            "Scheduled KR market watchlist resource refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def collect_taiwan_futures_quotes() -> None:
    now = datetime.now(_timezone())

    if not _is_taiwan_futures_live_window(now):
        logger.debug(
            "Skipped Taiwan futures quote collector outside live window now=%s.",
            now.isoformat(),
        )
        return

    symbols = _split_csv(settings.scheduler_taiwan_futures_symbols)
    if not symbols:
        logger.warning("Skipped Taiwan futures quote collector because no symbols are configured.")
        return

    provider = settings.taiwan_futures_quote_provider
    db = SessionLocal()

    try:
        provider = resolve_taiwan_futures_quote_provider(provider)
        rows = refresh_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            session=settings.scheduler_taiwan_futures_session,
            active_only=True,
            provider=provider,
        )
        if _should_record_taiwan_futures_success(now):
            _record_taiwan_futures_provider_event(
                db,
                provider=provider,
                status="success",
                symbols=symbols,
                message=f"Taiwan futures quote collector refreshed {len(rows)} active quote(s).",
                detail={
                    "symbols": symbols,
                    "session": settings.scheduler_taiwan_futures_session,
                    "provider": provider,
                    "row_count": len(rows),
                },
            )
        logger.info(
            "Taiwan futures quote collector refreshed %s active quote(s) symbols=%s.",
            len(rows),
            ",".join(symbols),
        )
    except (TaiwanFuturesFetchError, ValueError) as exc:
        db.rollback()
        _record_taiwan_futures_provider_event(
            db,
            provider=provider,
            status="error",
            symbols=symbols,
            error_message=str(exc),
            detail={
                "symbols": symbols,
                "session": settings.scheduler_taiwan_futures_session,
                "provider": provider,
            },
        )
        logger.warning("Taiwan futures quote collector failed: %s", exc)
    finally:
        db.close()


def _add_taiwan_futures_collector_job(scheduler: Any) -> bool:
    if not settings.enable_taiwan_futures_scheduler:
        return False

    interval_seconds = max(int(settings.scheduler_taiwan_futures_interval_seconds), 10)
    scheduler.add_job(
        collect_taiwan_futures_quotes,
        trigger="interval",
        seconds=interval_seconds,
        id="taiwan_futures_quote_collector",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def _add_jp_market_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_scheduler or not settings.enable_jp_market_scheduler:
        return False

    hour, minute = _parse_hour_minute(settings.scheduler_jp_market_refresh_time)
    scheduler.add_job(
        enqueue_jp_market_watchlist_resource_refresh,
        trigger="cron",
        day_of_week=settings.scheduler_jp_market_refresh_day_of_week,
        hour=hour,
        minute=minute,
        id="jp_market_watchlist_resource_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def _add_kr_market_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_scheduler or not settings.enable_kr_market_scheduler:
        return False

    hour, minute = _parse_hour_minute(settings.scheduler_kr_market_refresh_time)
    scheduler.add_job(
        enqueue_kr_market_watchlist_resource_refresh,
        trigger="cron",
        day_of_week=settings.scheduler_kr_market_refresh_day_of_week,
        hour=hour,
        minute=minute,
        id="kr_market_watchlist_resource_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def enqueue_watchlist_radar_auto_snapshot() -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)
    release_window = calendar_status.get("release_windows", {}).get(TAIWAN_DATASET_DAILY_PRICE)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled watchlist radar snapshot because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    daily_price_released = is_release_released_from_calendar(
        calendar_status,
        market="tw",
        key=TAIWAN_DATASET_DAILY_PRICE,
    )
    if settings.scheduler_watchlist_radar_require_daily_release and not daily_price_released:
        logger.info(
            "Skipped scheduled watchlist radar snapshot because daily price release is not ready date=%s window=%s.",
            calendar_status.get("date"),
            release_window,
        )
        return

    group_ids = _split_csv(settings.scheduler_watchlist_radar_group_ids)
    evaluate_before_date = (
        expected_trade_date_from_calendar(
            calendar_status,
            market="tw",
            key=TAIWAN_DATASET_DAILY_PRICE,
        )
        or now.date()
    )
    request = {
        "schedule": "watchlist_radar_auto_snapshot",
        "run_date": now.date().isoformat(),
        "group_ids": group_ids or None,
        "modes": settings.scheduler_watchlist_radar_modes,
        "include_children": settings.scheduler_watchlist_radar_include_children,
        "enabled_only": settings.scheduler_watchlist_radar_enabled_only,
        "max_results": settings.scheduler_watchlist_radar_max_results,
        "calculation_limit": settings.scheduler_watchlist_radar_calculation_limit,
        "use_intraday": settings.scheduler_watchlist_radar_use_intraday,
        "intraday_limit": settings.scheduler_watchlist_radar_intraday_limit,
        "evaluate_before_date": evaluate_before_date,
        "evaluate_lookback_days": settings.scheduler_watchlist_radar_evaluate_lookback_days,
        "save_snapshots": True,
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_window": release_window,
    }
    db = SessionLocal()

    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type=WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE,
            target=",".join(group_ids) if group_ids else "active-root",
            request=request,
            progress_total=1,
            message="Queued by scheduler.",
            task=backfill_tasks.run_watchlist_radar_auto_snapshot_job,
            task_args=(
                group_ids or None,
                settings.scheduler_watchlist_radar_modes,
                settings.scheduler_watchlist_radar_include_children,
                settings.scheduler_watchlist_radar_enabled_only,
                settings.scheduler_watchlist_radar_max_results,
                settings.scheduler_watchlist_radar_calculation_limit,
                settings.scheduler_watchlist_radar_use_intraday,
                settings.scheduler_watchlist_radar_intraday_limit,
                evaluate_before_date,
                settings.scheduler_watchlist_radar_evaluate_lookback_days,
                True,
            ),
        )
        logger.info(
            "Scheduled watchlist radar snapshot %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def _add_watchlist_radar_auto_snapshot_job(scheduler: Any) -> bool:
    if not settings.enable_watchlist_radar_scheduler:
        return False

    hour, minute = _parse_hour_minute(settings.scheduler_watchlist_radar_time)
    scheduler.add_job(
        enqueue_watchlist_radar_auto_snapshot,
        trigger="cron",
        day_of_week=settings.scheduler_watchlist_radar_day_of_week,
        hour=hour,
        minute=minute,
        id="watchlist_radar_auto_snapshot",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def enqueue_due_dispatch_schedules() -> None:
    from app.dispatch import service as dispatch_service

    db = SessionLocal()

    try:
        result = dispatch_service.enqueue_due_schedules(db=db)
        if result.get("queued_count") or result.get("error_count"):
            logger.info(
                "Dispatch schedule tick checked=%s queued=%s errors=%s.",
                result.get("checked_count"),
                result.get("queued_count"),
                result.get("error_count"),
            )
    finally:
        db.close()


def _add_dispatch_schedule_tick_job(scheduler: Any) -> bool:
    if not settings.enable_dispatch_scheduler:
        return False

    interval_seconds = max(int(settings.scheduler_dispatch_tick_interval_seconds), 10)
    scheduler.add_job(
        enqueue_due_dispatch_schedules,
        trigger="interval",
        seconds=interval_seconds,
        id="dispatch_schedule_tick",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def start_scheduler() -> Any | None:
    if (
        not settings.enable_scheduler
        and not settings.enable_taiwan_futures_scheduler
        and not settings.enable_dispatch_scheduler
        and not settings.enable_watchlist_radar_scheduler
    ):
        logger.info("Job scheduler disabled.")
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler is not installed; job scheduler disabled.")
        return None

    scheduler = BackgroundScheduler(timezone=_timezone())

    if settings.enable_scheduler:
        hour, minute = _parse_hour_minute(settings.scheduler_market_refresh_time)
        margin_hour, margin_minute = _parse_hour_minute(
            settings.scheduler_market_margin_refresh_time
        )
        chip_hour, chip_minute = _parse_hour_minute(
            settings.scheduler_market_chip_refresh_time
        )
        chip_margin_hour, chip_margin_minute = _parse_hour_minute(
            settings.scheduler_market_chip_margin_refresh_time
        )
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
            enqueue_market_margin_daily_refresh,
            trigger="cron",
            day_of_week="mon-fri",
            hour=margin_hour,
            minute=margin_minute,
            id="market_margin_daily_refresh",
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
        scheduler.add_job(
            enqueue_market_chip_margin_daily_refresh,
            trigger="cron",
            day_of_week="mon-fri",
            hour=chip_margin_hour,
            minute=chip_margin_minute,
            id="market_chip_margin_daily_refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    if settings.enable_scheduler and settings.enable_us_market_scheduler:
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
    jp_market_refresh_enabled = _add_jp_market_refresh_job(scheduler)
    kr_market_refresh_enabled = _add_kr_market_refresh_job(scheduler)
    watchlist_radar_snapshot_enabled = _add_watchlist_radar_auto_snapshot_job(scheduler)
    taiwan_futures_collector_enabled = _add_taiwan_futures_collector_job(scheduler)
    dispatch_schedule_tick_enabled = _add_dispatch_schedule_tick_job(scheduler)
    scheduler.start()
    logger.info(
        "Job scheduler started. core_scheduler_enabled=%s; market_daily_refresh=%s %s weekdays; market_margin_daily_refresh=%s %s weekdays; market_chip_daily_refresh=%s %s weekdays; market_chip_margin_daily_refresh=%s %s weekdays; us_market_daily_refresh=%s %s %s enabled=%s; jp_market_watchlist_resource_refresh=%s %s %s enabled=%s; kr_market_watchlist_resource_refresh=%s %s %s enabled=%s; watchlist_radar_auto_snapshot=%s %s %s enabled=%s; taiwan_futures_quote_collector interval=%ss enabled=%s; dispatch_schedule_tick interval=%ss enabled=%s.",
        settings.enable_scheduler,
        settings.scheduler_market_refresh_time,
        settings.timezone,
        settings.scheduler_market_margin_refresh_time,
        settings.timezone,
        settings.scheduler_market_chip_refresh_time,
        settings.timezone,
        settings.scheduler_market_chip_margin_refresh_time,
        settings.timezone,
        settings.scheduler_us_market_refresh_time,
        settings.scheduler_us_market_refresh_day_of_week,
        settings.timezone,
        settings.enable_us_market_scheduler,
        settings.scheduler_jp_market_refresh_time,
        settings.scheduler_jp_market_refresh_day_of_week,
        settings.timezone,
        jp_market_refresh_enabled,
        settings.scheduler_kr_market_refresh_time,
        settings.scheduler_kr_market_refresh_day_of_week,
        settings.timezone,
        kr_market_refresh_enabled,
        settings.scheduler_watchlist_radar_time,
        settings.scheduler_watchlist_radar_day_of_week,
        settings.timezone,
        watchlist_radar_snapshot_enabled,
        max(int(settings.scheduler_taiwan_futures_interval_seconds), 10),
        taiwan_futures_collector_enabled,
        max(int(settings.scheduler_dispatch_tick_interval_seconds), 10),
        dispatch_schedule_tick_enabled,
    )
    return scheduler


def stop_scheduler(scheduler: Any | None) -> None:
    if scheduler is None:
        return

    scheduler.shutdown(wait=False)
    logger.info("Job scheduler stopped.")
