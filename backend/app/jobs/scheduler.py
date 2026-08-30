from datetime import datetime, time, timedelta
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import JobRun
from app.jobs import backfill_tasks, service as job_service
from app.jobs.eod_coverage import enqueue_eod_coverage_reconcile
from app.jobs.job_types import (
    JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    KR_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    TAIWAN_BROKER_BRANCH_BEHAVIOR_SHADOW_JOB_TYPE,
    TAIWAN_BROKER_BRANCH_MARKET_REFRESH_JOB_TYPE,
    TAIWAN_DERIVATIVES_SCHEDULED_REFRESH_JOB_TYPE,
    US_PRIORITY_OHLC_RECONCILE_JOB_TYPE,
    WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE,
    WATCHLIST_RADAR_OUTCOME_RECONCILE_JOB_TYPE,
)
from app.jobs.taiwan_fundamental_scheduler import (
    add_taiwan_fundamental_refresh_jobs,
)
from app.jobs.taiwan_index_contract_scheduler import (
    TAIWAN_INDEX_CONTRACT_SLOTS,
    add_taiwan_index_contract_snapshot_jobs,
)
from app.jobs.taiwan_daily_metric_repair import (
    reconcile_taiwan_daily_metric_repairs,
)
from app.jobs.taiwan_quote_contract_scheduler import (
    TAIWAN_QUOTE_CONTRACT_SLOTS,
    add_taiwan_quote_contract_snapshot_jobs,
)
from app.jobs.taiwan_intraday_bar_scheduler import (
    add_taiwan_intraday_bar_jobs,
)
from app.market.calendar_status import (
    build_jp_calendar_status,
    build_taiwan_calendar_status,
    build_us_calendar_status,
    expected_trade_date_from_calendar,
    is_release_released_from_calendar,
)
from app.market.exchange_calendar_refresh import refresh_exchange_calendars
from app.market.tw_disposition import refresh_taiwan_dispositions
from app.market.tw_corporate_events import (
    backfill_taiwan_corporate_event_history,
    refresh_taiwan_corporate_events,
)
from app.market.broker_branch_market_refresh import (
    get_taiwan_broker_branch_market_coverage,
)
from app.market.broker_branch import expected_broker_branch_trade_date
from app.market.broker_branch_behavior import (
    BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS,
    BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
)
from app.market.market_chips import normalize_market_chip_index_ids
from app.market.taiwan_market_state import persist_taiwan_market_minute_state
from app.market.taiwan_index_minute import (
    persist_taiwan_index_minute_snapshots,
)
from app.market.indices import (
    TAIWAN_INDEX_RECONCILIATION_END_TIME,
    TAIWAN_INDEX_RECONCILIATION_RETRY_SECONDS,
    get_market_index_summary,
    is_taiwan_index_live_refresh_window,
    market_index_summary_needs_reconciliation,
    refresh_market_index_summary,
    refresh_current_market_breadth_snapshots,
    refresh_current_market_index_snapshots,
)
from app.market.official_index_platform import (
    read_taiwan_official_index,
    refresh_taiwan_official_index,
)
from app.market.providers.twse_mis_current_breadth import (
    get_cached_current_breadth_stock_rows,
)
from app.market.source_health import build_taiwan_source_health
from app.market_data.eod_coverage import (
    expected_eod_trade_date,
    should_enqueue_eod_reconcile,
)
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from app.market.tw_intraday_state import (
    attach_current_market_lineage_to_stock_rows,
    persist_taiwan_intraday_stock_states,
)
from app.market.taiwan_rules import (
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
    expected_daily_price_date,
)
from app.market.trading_calendar import is_taiwan_trading_day
from app.market.tw_derivatives import (
    DERIVATIVES_RELEASE_TIME,
    expected_taiwan_derivatives_date,
)
from app.market.tw_futures import (
    TaiwanFuturesFetchError,
    refresh_taiwan_futures_quotes,
    resolve_taiwan_futures_quote_provider,
)
from app.observability.provider_health import record_provider_event
from app.settings.refresh_execution import resolve_market_refresh_interval_seconds
from app.us_market.corporate_events import (
    USCorporateEventConfigurationError,
    refresh_us_corporate_events,
)
from app.watchlists import radar_automation


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
_LAST_TAIWAN_FUTURES_FAILURE_AT: datetime | None = None


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


def _resolved_taiwan_derivatives_schedule_time() -> time:
    hour, minute = _parse_hour_minute(
        settings.scheduler_taiwan_derivatives_refresh_time
    )
    configured = time(hour, minute)
    if configured < DERIVATIVES_RELEASE_TIME:
        logger.warning(
            "Taiwan derivatives scheduler time %s is before the conservative "
            "TAIFEX release guard %s; using the release guard time.",
            configured.strftime("%H:%M"),
            DERIVATIVES_RELEASE_TIME.strftime("%H:%M"),
        )
        return DERIVATIVES_RELEASE_TIME
    return configured


def _is_taiwan_derivatives_refresh_ready(now: datetime) -> bool:
    local_now = now.astimezone(_timezone()) if now.tzinfo else now.replace(tzinfo=_timezone())
    return (
        is_taiwan_trading_day(local_now.date())
        and local_now.time() >= DERIVATIVES_RELEASE_TIME
    )


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


def _should_attempt_taiwan_futures_refresh(now: datetime) -> bool:
    if _LAST_TAIWAN_FUTURES_FAILURE_AT is None:
        return True

    backoff_seconds = max(
        int(settings.scheduler_taiwan_futures_failure_backoff_seconds),
        0,
    )
    return (now - _LAST_TAIWAN_FUTURES_FAILURE_AT).total_seconds() >= backoff_seconds


def _taiwan_futures_failure_retry_at() -> datetime | None:
    if _LAST_TAIWAN_FUTURES_FAILURE_AT is None:
        return None

    backoff_seconds = max(
        int(settings.scheduler_taiwan_futures_failure_backoff_seconds),
        0,
    )
    return _LAST_TAIWAN_FUTURES_FAILURE_AT + timedelta(seconds=backoff_seconds)


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


def enqueue_market_daily_refresh(*, allow_non_trading_day: bool = False) -> None:
    categories = [TAIWAN_REFRESH_INSTITUTIONAL_TRADE]
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day") and not allow_non_trading_day:
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
    expected_trade_date = expected_trade_date_from_calendar(
        calendar_status,
        market="tw",
        key=TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    )
    if expected_trade_date is None:
        logger.error(
            "Skipped scheduled market daily refresh because the release calendar did not provide an expected trade date."
        )
        return

    request = {
        "schedule": "market_daily_refresh",
        "run_date": now.date().isoformat(),
        "categories": categories,
        "lookback_days": settings.scheduler_market_refresh_lookback_days,
        "include_today": include_today,
        "expected_trade_date": expected_trade_date,
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
            target=(
                expected_trade_date.isoformat()
                if expected_trade_date is not None
                else "market"
            ),
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
                expected_trade_date,
                None,
            ),
        )
        logger.info(
            "Scheduled market daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_market_margin_daily_refresh(
    *,
    allow_non_trading_day: bool = False,
) -> None:
    categories = [TAIWAN_REFRESH_MARGIN_TRADING]
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day") and not allow_non_trading_day:
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
    expected_trade_date = expected_trade_date_from_calendar(
        calendar_status,
        market="tw",
        key=TAIWAN_DATASET_MARGIN_TRADING,
    )
    if expected_trade_date is None:
        logger.error(
            "Skipped scheduled market margin daily refresh because the release calendar did not provide an expected trade date."
        )
        return

    request = {
        "schedule": "market_margin_daily_refresh",
        "run_date": now.date().isoformat(),
        "categories": categories,
        "lookback_days": settings.scheduler_market_refresh_lookback_days,
        "include_today": include_today,
        "expected_trade_date": expected_trade_date,
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
            target=(
                expected_trade_date.isoformat()
                if expected_trade_date is not None
                else "market"
            ),
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
                expected_trade_date,
                None,
            ),
        )
        logger.info(
            "Scheduled market margin daily refresh %s job_id=%s",
            "queued" if created else "deduped",
            job.id,
        )
    finally:
        db.close()


def enqueue_market_chip_daily_refresh(
    *,
    allow_non_trading_day: bool = False,
) -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if (
        not calendar_status.get("is_trading_day")
        and not allow_non_trading_day
    ):
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


def enqueue_market_chip_daily_startup_catchup() -> None:
    enqueue_market_chip_daily_refresh(allow_non_trading_day=True)


def enqueue_market_chip_margin_daily_refresh(
    *,
    allow_non_trading_day: bool = False,
) -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day") and not allow_non_trading_day:
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


def enqueue_market_chip_margin_daily_startup_catchup() -> None:
    enqueue_market_chip_margin_daily_refresh(allow_non_trading_day=True)


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
    calendar_status = build_jp_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        logger.info(
            "Skipped scheduled JP market refresh because %s is not a trading day phase=%s reason=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
        )
        return

    sleep_seconds = resolve_market_refresh_interval_seconds(market="jp")
    request = {
        "schedule": "jp_market_watchlist_resource_refresh",
        "run_date": now.date().isoformat(),
        "market_date": calendar_status.get("date"),
        "expected_trade_date": expected_trade_date_from_calendar(
            calendar_status,
            market="jp",
            key="jp_daily_price",
        ),
        "calendar_phase": calendar_status.get("phase"),
        "calendar_release_window": calendar_status.get("release_windows", {}).get(
            "jp_daily_price"
        ),
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
    global _LAST_TAIWAN_FUTURES_FAILURE_AT

    now = datetime.now(_timezone())

    if not _is_taiwan_futures_live_window(now):
        logger.debug(
            "Skipped Taiwan futures quote collector outside live window now=%s.",
            now.isoformat(),
        )
        return

    if not _should_attempt_taiwan_futures_refresh(now):
        retry_at = _taiwan_futures_failure_retry_at()
        logger.debug(
            "Skipped Taiwan futures quote collector during provider failure backoff retry_at=%s.",
            retry_at.isoformat() if retry_at else None,
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
        _LAST_TAIWAN_FUTURES_FAILURE_AT = None
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
        _LAST_TAIWAN_FUTURES_FAILURE_AT = now
        retry_at = _taiwan_futures_failure_retry_at()
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
                "retry_at": retry_at.isoformat() if retry_at else None,
            },
        )
        logger.warning(
            "Taiwan futures quote collector failed; retry_at=%s: %s",
            retry_at.isoformat() if retry_at else None,
            exc,
        )
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


def enqueue_taiwan_derivatives_refresh() -> None:
    now = datetime.now(_timezone())
    if not _is_taiwan_derivatives_refresh_ready(now):
        logger.info(
            "Skipped scheduled TAIFEX derivatives refresh before the official "
            "release window or on a non-trading day now=%s release_time=%s.",
            now.isoformat(),
            DERIVATIVES_RELEASE_TIME.strftime("%H:%M"),
        )
        return

    expected_trade_date = expected_taiwan_derivatives_date(now=now)
    request = {
        "schedule": "taiwan_derivatives_refresh",
        "run_date": now.date().isoformat(),
        "expected_trade_date": expected_trade_date.isoformat(),
        "release_time": DERIVATIVES_RELEASE_TIME.strftime("%H:%M"),
        "provider": "taifex_openapi",
        "provider_request_limit": 5,
    }
    db = SessionLocal()
    try:
        job, created = job_service.enqueue_job(
            db=db,
            job_type=TAIWAN_DERIVATIVES_SCHEDULED_REFRESH_JOB_TYPE,
            target="TXF/TXO",
            request=request,
            progress_total=5,
            message="Queued by scheduler after the TAIFEX post-close release guard.",
            task=backfill_tasks.run_taiwan_derivatives_refresh_job,
            task_args=(expected_trade_date,),
            reuse_success_within_seconds=max(
                int(settings.scheduler_taiwan_derivatives_success_cooldown_seconds),
                0,
            ),
        )
        logger.info(
            "Scheduled TAIFEX derivatives refresh created=%s job_id=%s "
            "expected_trade_date=%s.",
            created,
            job.id,
            expected_trade_date.isoformat(),
        )
    finally:
        db.close()


def _add_taiwan_derivatives_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_taiwan_derivatives_scheduler:
        return False

    schedule_time = _resolved_taiwan_derivatives_schedule_time()
    scheduler.add_job(
        enqueue_taiwan_derivatives_refresh,
        trigger="cron",
        day_of_week=settings.scheduler_taiwan_derivatives_refresh_day_of_week,
        hour=schedule_time.hour,
        minute=schedule_time.minute,
        id="taiwan_derivatives_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def enqueue_taiwan_broker_branch_market_refresh() -> None:
    now = datetime.now(_timezone())
    calendar_status = build_taiwan_calendar_status(now=now)
    release_window = calendar_status.get("release_windows", {}).get(
        TAIWAN_DATASET_BROKER_BRANCH
    )

    expected_trade_date = (
        expected_trade_date_from_calendar(
            calendar_status,
            market="tw",
            key=TAIWAN_DATASET_BROKER_BRANCH,
        )
        or now.date()
    )
    current_date_release_ready = (
        calendar_status.get("is_trading_day")
        and is_release_released_from_calendar(
            calendar_status,
            market="tw",
            key=TAIWAN_DATASET_BROKER_BRANCH,
        )
    )
    if expected_trade_date >= now.date() and not current_date_release_ready:
        logger.info(
            "Skipped Taiwan all-market broker-branch refresh before the current "
            "trade-date release date=%s phase=%s reason=%s window=%s.",
            calendar_status.get("date"),
            calendar_status.get("phase"),
            calendar_status.get("reason"),
            release_window,
        )
        return

    if expected_trade_date > now.date():
        logger.warning(
            "Skipped Taiwan all-market broker-branch refresh because calendar "
            "returned a future expected date=%s now=%s.",
            expected_trade_date,
            now.date(),
        )
        return

    if expected_trade_date < now.date():
        logger.info(
            "Running Taiwan all-market broker-branch catch-up date=%s now=%s.",
            expected_trade_date,
            now.date(),
        )

    sleep_seconds = max(
        float(settings.scheduler_tw_broker_branch_sleep_seconds),
        0.0,
    )
    max_stocks = max(int(settings.scheduler_tw_broker_branch_max_stocks), 1)
    max_runtime_seconds = max(
        int(settings.scheduler_tw_broker_branch_max_runtime_seconds),
        1,
    )
    db = SessionLocal()
    try:
        coverage = get_taiwan_broker_branch_market_coverage(
            db,
            trade_date=expected_trade_date,
        )
        if coverage["complete"]:
            logger.info(
                "Skipped Taiwan all-market broker-branch refresh because daily "
                "coverage is complete date=%s covered=%s expected=%s.",
                expected_trade_date,
                coverage["covered_count"],
                coverage["expected_count"],
            )
            return

        request = {
            "schedule": "tw_broker_branch_market_refresh",
            "collection_mode": (
                "current_release"
                if expected_trade_date == now.date()
                else "startup_catchup"
            ),
            "run_date": now.date().isoformat(),
            "expected_trade_date": expected_trade_date.isoformat(),
            "markets": ["TWSE", "TPEX"],
            "instrument_type": "stock",
            "provider": "nstock",
            "provider_request_limit": max_stocks + 1,
            "max_stocks": max_stocks,
            "sleep_seconds": sleep_seconds,
            "max_runtime_seconds": max_runtime_seconds,
            "calendar_phase": calendar_status.get("phase"),
            "calendar_release_window": release_window,
        }
        progress_total = max(
            min(int(coverage["missing_count"]), max_stocks),
            1,
        )
        job, created = job_service.enqueue_job(
            db=db,
            job_type=TAIWAN_BROKER_BRANCH_MARKET_REFRESH_JOB_TYPE,
            target=expected_trade_date.isoformat(),
            request=request,
            progress_total=progress_total,
            message="Queued by scheduler for Taiwan all-market broker-branch collection.",
            task=backfill_tasks.run_taiwan_broker_branch_market_refresh_job,
            task_args=(
                expected_trade_date,
                sleep_seconds,
                max_stocks,
                max_runtime_seconds,
            ),
        )
        logger.info(
            "Taiwan all-market broker-branch refresh %s job_id=%s date=%s "
            "covered=%s expected=%s missing=%s.",
            "queued" if created else "deduped",
            job.id,
            expected_trade_date,
            coverage["covered_count"],
            coverage["expected_count"],
            coverage["missing_count"],
        )
    finally:
        db.close()


def reconcile_taiwan_broker_branch_market_refresh() -> None:
    now = datetime.now(_timezone())
    if now.weekday() >= 5:
        return
    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_broker_branch_refresh_time
    )
    end_hour, end_minute = _parse_hour_minute(
        settings.scheduler_tw_broker_branch_reconcile_until
    )
    if (now.hour, now.minute) < (hour, minute):
        return
    if (now.hour, now.minute) > (end_hour, end_minute):
        return

    enqueue_taiwan_broker_branch_market_refresh()


def _add_taiwan_broker_branch_market_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_tw_broker_branch_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_broker_branch_refresh_time
    )
    scheduler.add_job(
        enqueue_taiwan_broker_branch_market_refresh,
        trigger="cron",
        day_of_week=settings.scheduler_tw_broker_branch_refresh_day_of_week,
        hour=hour,
        minute=minute,
        id="tw_broker_branch_market_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        reconcile_taiwan_broker_branch_market_refresh,
        trigger="interval",
        minutes=max(
            int(settings.scheduler_tw_broker_branch_reconcile_interval_minutes),
            5,
        ),
        id="tw_broker_branch_market_refresh_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    scheduler.add_job(
        enqueue_taiwan_broker_branch_market_refresh,
        trigger="date",
        run_date=datetime.now(_timezone()),
        id="tw_broker_branch_market_refresh_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def enqueue_taiwan_broker_branch_behavior_shadow() -> None:
    now = datetime.now(_timezone())
    as_of_trade_date = expected_broker_branch_trade_date(now=now)
    lookback_sessions = max(
        2,
        min(
            int(
                settings.scheduler_tw_broker_branch_behavior_lookback_sessions
            ),
            BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS,
        ),
    )
    db = SessionLocal()
    try:
        coverage = get_taiwan_broker_branch_market_coverage(
            db,
            trade_date=as_of_trade_date,
        )
        expected_count = int(coverage.get("expected_count") or 0)
        covered_count = int(coverage.get("covered_count") or 0)
        coverage_ratio = (
            covered_count / expected_count if expected_count > 0 else 0.0
        )
        if coverage_ratio < 0.95:
            logger.info(
                "Skipped broker-branch shadow behavior date=%s because raw "
                "coverage is below 95%% covered=%s expected=%s ratio=%.4f.",
                as_of_trade_date,
                covered_count,
                expected_count,
                coverage_ratio,
            )
            return

        request = {
            "schedule": "tw_broker_branch_behavior_shadow",
            "mode": "shadow",
            "advertised": False,
            "decision_usable": False,
            "as_of_trade_date": as_of_trade_date.isoformat(),
            "lookback_sessions": lookback_sessions,
            "methodology_version": BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
            "raw_coverage": {
                "covered_count": covered_count,
                "expected_count": expected_count,
                "coverage_ratio": coverage_ratio,
            },
            "external_fetches": 0,
        }
        target = (
            f"{as_of_trade_date.isoformat()}|"
            f"{BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0}"
        )
        job, created = job_service.enqueue_job(
            db=db,
            job_type=TAIWAN_BROKER_BRANCH_BEHAVIOR_SHADOW_JOB_TYPE,
            target=target,
            request=request,
            progress_total=1,
            message="Queued broker-branch shadow behavior materialization.",
            task=backfill_tasks.run_taiwan_broker_branch_behavior_shadow_job,
            task_args=(
                as_of_trade_date,
                lookback_sessions,
                BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
            ),
            reuse_success_within_seconds=86400,
        )
        logger.info(
            "Broker-branch shadow behavior %s job_id=%s date=%s "
            "coverage=%s/%s.",
            "queued" if created else "deduped",
            job.id,
            as_of_trade_date,
            covered_count,
            expected_count,
        )
    finally:
        db.close()


def _add_taiwan_broker_branch_behavior_shadow_job(scheduler: Any) -> bool:
    if not settings.enable_tw_broker_branch_behavior_shadow_scheduler:
        return False
    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_broker_branch_behavior_shadow_time
    )
    scheduler.add_job(
        enqueue_taiwan_broker_branch_behavior_shadow,
        trigger="cron",
        day_of_week=settings.scheduler_tw_broker_branch_refresh_day_of_week,
        hour=hour,
        minute=minute,
        id="tw_broker_branch_behavior_shadow",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def enqueue_taiwan_stock_detail_daily_startup_catchup() -> None:
    enqueue_market_daily_refresh(allow_non_trading_day=True)
    enqueue_market_margin_daily_refresh(allow_non_trading_day=True)


def _add_taiwan_stock_detail_daily_refresh_jobs(scheduler: Any) -> bool:
    if not settings.enable_tw_stock_detail_scheduler:
        return False

    institutional_hour, institutional_minute = _parse_hour_minute(
        settings.scheduler_tw_institutional_refresh_time
    )
    margin_hour, margin_minute = _parse_hour_minute(
        settings.scheduler_tw_margin_refresh_time
    )
    scheduler.add_job(
        enqueue_market_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=institutional_hour,
        minute=institutional_minute,
        id="tw_stock_detail_institutional_refresh",
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
        id="tw_stock_detail_margin_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_taiwan_stock_detail_daily_startup_catchup,
        trigger="date",
        run_date=datetime.now(_timezone()) + timedelta(seconds=3),
        id="tw_stock_detail_daily_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def reconcile_taiwan_daily_metric_repair_jobs(*, trigger: str = "interval") -> None:
    db = SessionLocal()
    try:
        result = reconcile_taiwan_daily_metric_repairs(db, trigger=trigger)
        logger.info(
            "Taiwan daily-metric repair reconciliation completed trigger=%s queued=%s decisions=%s.",
            trigger,
            result.get("queued_count"),
            len(result.get("decisions") or []),
        )
    except Exception:
        db.rollback()
        logger.exception("Taiwan daily-metric repair reconciliation failed.")
    finally:
        db.close()


def reconcile_taiwan_daily_metric_repairs_startup() -> None:
    reconcile_taiwan_daily_metric_repair_jobs(trigger="startup")


def _add_taiwan_daily_metric_repair_jobs(scheduler: Any) -> bool:
    if not settings.enable_market_daily_repair_scheduler or not (
        settings.enable_scheduler or settings.enable_tw_stock_detail_scheduler
    ):
        return False

    interval_minutes = max(
        int(settings.scheduler_market_daily_repair_interval_minutes),
        5,
    )
    current = datetime.now(_timezone())
    scheduler.add_job(
        reconcile_taiwan_daily_metric_repair_jobs,
        trigger="interval",
        minutes=interval_minutes,
        id="taiwan_daily_metric_repair_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=current + timedelta(minutes=interval_minutes),
    )
    scheduler.add_job(
        reconcile_taiwan_daily_metric_repairs_startup,
        trigger="date",
        run_date=current + timedelta(seconds=6),
        id="taiwan_daily_metric_repair_startup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def collect_taiwan_market_index_summary() -> None:
    now = datetime.now(_timezone())
    if not is_taiwan_index_live_refresh_window(now):
        return
    db = SessionLocal()
    try:
        payload = refresh_current_market_index_snapshots(db=db)
        persistence = persist_taiwan_market_minute_state(
            db,
            payload=payload,
            finalized=False,
            now=now,
        )
        index_minute_persistence = persist_taiwan_index_minute_snapshots(
            db,
            payload=payload,
            now=now,
        )
        logger.debug(
            "Taiwan market index summary cache refreshed as_of=%s indices=%s "
            "minute_rows=%s index_minute_rows=%s.",
            payload.get("as_of"),
            len(payload.get("indices") or []),
            persistence.get("inserted_count", 0) + persistence.get("updated_count", 0),
            index_minute_persistence.get("inserted_count", 0)
            + index_minute_persistence.get("updated_count", 0),
        )
    except Exception:
        db.rollback()
        logger.exception("Taiwan market index summary cache refresh failed.")
    finally:
        db.close()


def collect_taiwan_market_breadth_summary() -> None:
    now = datetime.now(_timezone())
    if not is_taiwan_index_live_refresh_window(now):
        return
    db = SessionLocal()
    try:
        payload = refresh_current_market_breadth_snapshots(db=db)
        persistence = persist_taiwan_market_minute_state(
            db,
            payload=payload,
            finalized=False,
            now=now,
        )
        stock_state_persistence = persist_taiwan_intraday_stock_states(
            db,
            rows=attach_current_market_lineage_to_stock_rows(
                get_cached_current_breadth_stock_rows(),
                summary=payload,
            ),
            now=now,
        )
        logger.debug(
            "Taiwan market breadth cache refreshed as_of=%s minute_rows=%s "
            "stock_state_rows=%s.",
            payload.get("as_of"),
            persistence.get("inserted_count", 0)
            + persistence.get("updated_count", 0),
            stock_state_persistence.get("inserted_count", 0)
            + stock_state_persistence.get("updated_count", 0),
        )
    except Exception:
        db.rollback()
        logger.exception("Taiwan market breadth cache refresh failed.")
    finally:
        db.close()


def _reconcile_taiwan_official_index_rows(
    db: Any,
    *,
    requested_at: datetime,
) -> list[dict[str, Any]]:
    """Bounded scheduler-owned repair for the two official cash indices."""

    expected_index_date = expected_daily_price_date(now=requested_at)
    if expected_index_date is None:
        return []
    results: list[dict[str, Any]] = []
    for index_id in ("TAIEX", "TPEX"):
        current = read_taiwan_official_index(
            db,
            index_id=index_id,
            trade_date=expected_index_date,
            requested_at=requested_at,
        )
        selected = current.resolved.market_index
        if (
            selected is not None
            and selected.trade_date == expected_index_date
            and current.resolved.health.facts_usable
        ):
            results.append(
                {
                    "index_id": index_id,
                    "status": "already_current",
                    "trade_date": expected_index_date.isoformat(),
                }
            )
            continue
        try:
            refreshed = refresh_taiwan_official_index(
                db,
                index_id=index_id,
                trade_date=expected_index_date,
                requested_at=requested_at,
            )
        except Exception as exc:
            db.rollback()
            logger.exception(
                "Taiwan official index reconciliation failed "
                "index_id=%s trade_date=%s.",
                index_id,
                expected_index_date,
            )
            results.append(
                {
                    "index_id": index_id,
                    "status": "failed",
                    "trade_date": expected_index_date.isoformat(),
                    "error": str(exc) or exc.__class__.__name__,
                }
            )
            continue
        results.append(
            {
                "index_id": index_id,
                "status": (
                    "refreshed"
                    if refreshed.postcondition_satisfied
                    else "postcondition_unsatisfied"
                ),
                "trade_date": expected_index_date.isoformat(),
                "raw_result_ids": list(refreshed.persistence.raw_result_ids),
            }
        )
    return results


def reconcile_taiwan_market_index_summary(
    *,
    allow_late: bool = False,
    now: datetime | None = None,
) -> None:
    local_now = now or datetime.now(_timezone())
    db = SessionLocal()
    try:
        cached_payload = get_market_index_summary(db=db)
        if not market_index_summary_needs_reconciliation(
            cached_payload,
            now=local_now,
            allow_late=allow_late,
        ):
            return
        official_refresh_results = _reconcile_taiwan_official_index_rows(
            db,
            requested_at=local_now,
        )
        payload = refresh_market_index_summary(
            db=db,
            refresh_daily_stats=True,
        )
        persistence = persist_taiwan_market_minute_state(
            db,
            payload=payload,
            finalized=True,
            now=local_now,
        )
        logger.info(
            "Taiwan market index summary post-close reconciliation completed "
            "as_of=%s indices=%s minute_rows=%s startup_catchup=%s "
            "official_daily=%s.",
            payload.get("as_of"),
            len(payload.get("indices") or []),
            persistence.get("inserted_count", 0) + persistence.get("updated_count", 0),
            allow_late,
            official_refresh_results,
        )
    except Exception:
        db.rollback()
        logger.exception("Taiwan market index summary post-close reconciliation failed.")
    finally:
        db.close()


def reconcile_taiwan_market_index_summary_startup() -> None:
    reconcile_taiwan_market_index_summary(allow_late=True)


def sync_taiwan_source_health() -> None:
    db = SessionLocal()
    try:
        build_taiwan_source_health(
            db,
            sync_snapshots=True,
        )
    except Exception:
        db.rollback()
        logger.exception("Taiwan source-health snapshot sync failed.")
    finally:
        db.close()


def _add_taiwan_source_health_sync_job(scheduler: Any) -> bool:
    if not settings.enable_taiwan_source_health_scheduler:
        return False
    scheduler.add_job(
        sync_taiwan_source_health,
        trigger="interval",
        seconds=max(
            int(settings.scheduler_taiwan_source_health_interval_seconds),
            30,
        ),
        id="taiwan_source_health_snapshot_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()) + timedelta(seconds=10),
    )
    return True


def _add_taiwan_market_index_collector_job(scheduler: Any) -> bool:
    if not (
        settings.enable_taiwan_market_index_scheduler
        or settings.enable_taiwan_market_breadth_scheduler
    ):
        return False
    interval_seconds = max(
        int(settings.scheduler_taiwan_market_index_interval_seconds),
        5,
    )
    if settings.enable_taiwan_market_index_scheduler:
        scheduler.add_job(
            collect_taiwan_market_index_summary,
            trigger="interval",
            seconds=interval_seconds,
            id="taiwan_market_index_summary_collector",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(_timezone()),
        )
    if settings.enable_taiwan_market_breadth_scheduler:
        scheduler.add_job(
            collect_taiwan_market_breadth_summary,
            trigger="interval",
            seconds=max(
                int(settings.scheduler_taiwan_market_breadth_interval_seconds),
                30,
            ),
            id="taiwan_market_breadth_summary_collector",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(_timezone()) + timedelta(seconds=3),
        )
    reconciliation_minutes = max(
        TAIWAN_INDEX_RECONCILIATION_RETRY_SECONDS // 60,
        5,
    )
    scheduler.add_job(
        reconcile_taiwan_market_index_summary,
        trigger="interval",
        minutes=reconciliation_minutes,
        id="taiwan_market_index_summary_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()) + timedelta(minutes=reconciliation_minutes),
    )
    scheduler.add_job(
        reconcile_taiwan_market_index_summary_startup,
        trigger="date",
        run_date=datetime.now(_timezone()),
        id="taiwan_market_index_summary_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
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


def refresh_market_calendars() -> None:
    db = SessionLocal()
    try:
        result = refresh_exchange_calendars(db=db)
        logger.info(
            "Scheduled exchange-calendar refresh completed success=%s errors=%s markets=%s.",
            result.get("success_count"),
            result.get("error_count"),
            ",".join(result.get("requested_markets") or []),
        )
    except Exception:
        db.rollback()
        logger.exception("Scheduled exchange-calendar refresh failed.")
    finally:
        db.close()


def _add_market_calendar_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_market_calendar_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_market_calendar_refresh_time
    )
    scheduler.add_job(
        refresh_market_calendars,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="market_calendar_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def refresh_taiwan_disposition_securities() -> None:
    db = SessionLocal()
    try:
        result = refresh_taiwan_dispositions(db=db)
        logger.info(
            "Scheduled Taiwan disposition refresh completed success=%s errors=%s active=%s upcoming=%s.",
            result.get("success_count"),
            result.get("error_count"),
            result.get("active_count"),
            result.get("upcoming_count"),
        )
    except Exception:
        db.rollback()
        logger.exception("Scheduled Taiwan disposition refresh failed.")
    finally:
        db.close()


def _add_taiwan_disposition_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_tw_disposition_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_disposition_refresh_time
    )
    scheduler.add_job(
        refresh_taiwan_disposition_securities,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="taiwan_disposition_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def refresh_taiwan_corporate_event_calendar() -> None:
    db = SessionLocal()
    try:
        result = refresh_taiwan_corporate_events(db=db)
        logger.info(
            "Scheduled Taiwan corporate-event refresh completed success=%s errors=%s events=%s requests=%s/%s.",
            result.get("success_count"),
            result.get("error_count"),
            result.get("event_count"),
            result.get("request_count"),
            result.get("request_limit"),
        )
    except Exception:
        db.rollback()
        logger.exception("Scheduled Taiwan corporate-event refresh failed.")
    finally:
        db.close()


def _add_taiwan_corporate_event_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_tw_corporate_event_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_corporate_event_refresh_time
    )
    scheduler.add_job(
        refresh_taiwan_corporate_event_calendar,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="taiwan_corporate_event_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def refresh_us_corporate_event_calendar() -> None:
    if not str(settings.alphavantage_api_key or "").strip():
        logger.info(
            "Skipped scheduled US corporate-event refresh because "
            "ALPHAVANTAGE_API_KEY is not configured."
        )
        return

    db = SessionLocal()
    try:
        result = refresh_us_corporate_events(db=db)
        logger.info(
            "Scheduled US corporate-event refresh completed events=%s "
            "inserted=%s updated=%s requests=%s/%s.",
            result.get("valid_count"),
            result.get("inserted_count"),
            result.get("updated_count"),
            result.get("request_count"),
            result.get("request_limit"),
        )
    except USCorporateEventConfigurationError:
        db.rollback()
        logger.info(
            "Skipped scheduled US corporate-event refresh because the provider "
            "is not configured."
        )
    except Exception:
        db.rollback()
        logger.exception("Scheduled US corporate-event refresh failed.")
    finally:
        db.close()


def _add_us_corporate_event_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_us_corporate_event_scheduler:
        return False

    interval_hours = max(
        int(settings.scheduler_us_corporate_event_refresh_hours),
        1,
    )
    scheduler.add_job(
        refresh_us_corporate_event_calendar,
        trigger="interval",
        hours=interval_hours,
        id="us_corporate_event_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()) + timedelta(seconds=10),
    )
    return True


def refresh_taiwan_corporate_event_history() -> None:
    db = SessionLocal()
    try:
        result = backfill_taiwan_corporate_event_history(
            force=False,
            db=db,
        )
        logger.info(
            "Scheduled Taiwan corporate-event history reconciliation completed success=%s errors=%s events=%s requests=%s/%s.",
            result.get("success_count"),
            result.get("error_count"),
            result.get("event_count"),
            result.get("request_count"),
            result.get("request_limit"),
        )
    except Exception:
        db.rollback()
        logger.exception("Scheduled Taiwan corporate-event history reconciliation failed.")
    finally:
        db.close()


def _add_taiwan_corporate_event_history_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_tw_corporate_event_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_tw_corporate_event_history_refresh_time
    )
    scheduler.add_job(
        refresh_taiwan_corporate_event_history,
        trigger="cron",
        day_of_week=settings.scheduler_tw_corporate_event_history_refresh_day_of_week,
        hour=hour,
        minute=minute,
        id="taiwan_corporate_event_history_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()) + timedelta(seconds=15),
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
        coverage = radar_automation.get_watchlist_radar_daily_coverage(
            db=db,
            snapshot_date=evaluate_before_date,
            group_ids=group_ids or None,
            modes=settings.scheduler_watchlist_radar_modes,
            include_children=settings.scheduler_watchlist_radar_include_children,
            enabled_only=settings.scheduler_watchlist_radar_enabled_only,
            evaluate_lookback_days=settings.scheduler_watchlist_radar_evaluate_lookback_days,
        )
        if coverage["reconciliation_complete"]:
            logger.info(
                "Skipped scheduled watchlist radar snapshot because daily reconciliation is complete date=%s covered=%s expected=%s pending_evaluations=%s.",
                coverage["snapshot_date"],
                coverage["covered_count"],
                coverage["expected_count"],
                coverage["pending_evaluation_count"],
            )
            return

        job, created = job_service.enqueue_job(
            db=db,
            job_type=WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE,
            target=",".join(group_ids) if group_ids else "all-active",
            request=request,
            progress_total=max(int(coverage["expected_count"]), 1),
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


def reconcile_watchlist_radar_auto_snapshot() -> None:
    now = datetime.now(_timezone())
    hour, minute = _parse_hour_minute(settings.scheduler_watchlist_radar_time)
    end_hour, end_minute = _parse_hour_minute(
        settings.scheduler_watchlist_radar_reconcile_until
    )
    if (now.hour, now.minute) < (hour, minute):
        logger.info(
            "Skipped watchlist radar reconciliation before configured time now=%s configured=%s.",
            now.strftime("%H:%M"),
            settings.scheduler_watchlist_radar_time,
        )
        return
    if (now.hour, now.minute) > (end_hour, end_minute):
        logger.info(
            "Skipped watchlist radar reconciliation after retry window now=%s until=%s.",
            now.strftime("%H:%M"),
            settings.scheduler_watchlist_radar_reconcile_until,
        )
        return

    enqueue_watchlist_radar_auto_snapshot()


def enqueue_watchlist_radar_outcome_reconcile() -> None:
    group_ids = _split_csv(settings.scheduler_watchlist_radar_group_ids)
    db = SessionLocal()
    try:
        coverage = (
            radar_automation.get_watchlist_radar_v2_outcome_due_coverage(
                db=db,
                group_ids=group_ids or None,
                modes=settings.scheduler_watchlist_radar_modes,
            )
        )
        if not coverage["due_count"]:
            logger.info(
                "Skipped Radar v2 outcome reconciliation because no mature pending paths remain latest_available_trade_date=%s.",
                coverage.get("latest_available_trade_date"),
            )
            return
        request = {
            "schedule": "watchlist_radar_v2_outcome_reconcile",
            "group_ids": group_ids or None,
            "modes": settings.scheduler_watchlist_radar_modes,
            "limit": 200,
            "initialize_limit": 200,
            "as_of_trade_date": coverage.get(
                "latest_available_trade_date"
            ),
            "due_count": coverage["due_count"],
            "oldest_due_trade_date": coverage.get(
                "oldest_due_trade_date"
            ),
        }
        job, created = job_service.enqueue_job(
            db=db,
            job_type=WATCHLIST_RADAR_OUTCOME_RECONCILE_JOB_TYPE,
            target=(
                ",".join(group_ids) if group_ids else "all-active"
            ),
            request=request,
            progress_total=max(
                len(coverage["group_ids"]) * len(coverage["modes"]),
                1,
            ),
            message="Queued Radar v2 outcome reconciliation by scheduler.",
            task=backfill_tasks.run_watchlist_radar_outcome_reconcile_job,
            task_args=(
                group_ids or None,
                settings.scheduler_watchlist_radar_modes,
                200,
                200,
                coverage.get("latest_available_trade_date"),
            ),
        )
        logger.info(
            "Scheduled Radar v2 outcome reconciliation %s job_id=%s due_count=%s oldest_due=%s.",
            "queued" if created else "deduped",
            job.id,
            coverage["due_count"],
            coverage.get("oldest_due_trade_date"),
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
    scheduler.add_job(
        reconcile_watchlist_radar_auto_snapshot,
        trigger="interval",
        minutes=max(
            int(settings.scheduler_watchlist_radar_reconcile_interval_minutes),
            5,
        ),
        id="watchlist_radar_auto_snapshot_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    scheduler.add_job(
        enqueue_watchlist_radar_outcome_reconcile,
        trigger="interval",
        minutes=max(
            int(settings.scheduler_watchlist_radar_reconcile_interval_minutes),
            5,
        ),
        id="watchlist_radar_v2_outcome_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def enqueue_due_dispatch_schedules() -> None:
    from app.dispatch import service as dispatch_service

    db = SessionLocal()

    try:
        result = dispatch_service.enqueue_due_schedules(db=db)
        if (
            result.get("queued_count")
            or result.get("waiting_count")
            or result.get("skipped_count")
            or result.get("error_count")
        ):
            logger.info(
                "Dispatch schedule tick checked=%s queued=%s waiting=%s skipped=%s errors=%s.",
                result.get("checked_count"),
                result.get("queued_count"),
                result.get("waiting_count", 0),
                result.get("skipped_count", 0),
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


def reconcile_dispatch_schedule_runs() -> None:
    from app.dispatch import service as dispatch_service

    db = SessionLocal()
    try:
        result = dispatch_service.reconcile_schedule_runs(db=db)
        if any(
            result.get(key)
            for key in ("processed_count", "recovered_count", "unknown_count", "error_count")
        ):
            logger.info(
                "Dispatch reconciliation processed=%s recovered=%s unknown=%s errors=%s.",
                result.get("processed_count", 0),
                result.get("recovered_count", 0),
                result.get("unknown_count", 0),
                result.get("error_count", 0),
            )
    finally:
        db.close()


def _add_dispatch_schedule_reconcile_job(scheduler: Any) -> bool:
    if not (
        settings.enable_dispatch_scheduler
        and settings.dispatch_scheduler_v2_enabled
    ):
        return False
    scheduler.add_job(
        reconcile_dispatch_schedule_runs,
        trigger="interval",
        seconds=max(int(settings.scheduler_dispatch_reconcile_interval_seconds), 30),
        id="dispatch_schedule_run_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return True


def _add_market_chip_margin_refresh_job(scheduler: Any) -> bool:
    if not settings.enable_market_chip_margin_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_market_chip_margin_refresh_time
    )
    scheduler.add_job(
        enqueue_market_chip_margin_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id="market_chip_margin_daily_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_market_chip_margin_daily_startup_catchup,
        trigger="date",
        id="market_chip_margin_daily_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def _add_market_chip_daily_refresh_jobs(scheduler: Any) -> bool:
    if not settings.enable_scheduler:
        return False

    hour, minute = _parse_hour_minute(
        settings.scheduler_market_chip_refresh_time
    )
    scheduler.add_job(
        enqueue_market_chip_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id="market_chip_daily_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    retry_delay_minutes = max(
        int(settings.scheduler_market_chip_refresh_retry_delay_minutes),
        1,
    )
    retry_clock = (
        datetime(2000, 1, 1, hour, minute)
        + timedelta(minutes=retry_delay_minutes)
    )
    scheduler.add_job(
        enqueue_market_chip_daily_refresh,
        trigger="cron",
        day_of_week="mon-fri",
        hour=retry_clock.hour,
        minute=retry_clock.minute,
        id="market_chip_daily_refresh_retry",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        enqueue_market_chip_daily_startup_catchup,
        trigger="date",
        id="market_chip_daily_startup_catchup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def enqueue_market_eod_coverage_reconcile() -> None:
    from app.us_market.daily_rollout import (
        us_daily_full_market_acquisition_enabled,
    )

    markets = [item.upper() for item in _split_csv(settings.scheduler_eod_coverage_markets)]
    for market in markets:
        if market not in {"TW", "US"}:
            logger.warning("Skipping unsupported EOD coverage scheduler market=%s.", market)
            continue
        if market == "US" and not us_daily_full_market_acquisition_enabled():
            logger.info(
                "Skipping US full-market EOD coverage while Daily acquisition "
                "rollout is not on."
            )
            continue
        db = SessionLocal()
        try:
            us_port = (
                US_FULL_MARKET_EOD_LIFECYCLE
                if market.strip().upper() == "US"
                else None
            )
            expected_trade_date = expected_eod_trade_date(
                market,
                us_port=us_port,
            )
            if not should_enqueue_eod_reconcile(
                db,
                market=market,
                expected_trade_date=expected_trade_date,
                us_port=us_port,
            ):
                continue
            job, created = enqueue_eod_coverage_reconcile(
                db,
                market=market,
                repair=True,
                expected_trade_date=expected_trade_date,
                max_symbols=(
                    settings.scheduler_eod_coverage_us_max_symbols_per_run
                    if market == "US"
                    else 2
                ),
                max_runtime_seconds=(
                    settings.scheduler_eod_coverage_us_max_runtime_seconds
                    if market == "US"
                    else 120
                ),
                sleep_seconds=(
                    settings.scheduler_eod_coverage_us_sleep_seconds
                    if market == "US"
                    else 0
                ),
                max_consecutive_errors=(
                    settings.scheduler_eod_coverage_us_max_consecutive_errors
                    if market == "US"
                    else 2
                ),
                error_backoff_seconds=settings.scheduler_eod_coverage_error_backoff_seconds,
                message="Queued by full-market EOD coverage scheduler.",
            )
            logger.info(
                "Full-market EOD coverage reconcile market=%s %s job_id=%s.",
                market,
                "queued" if created else "deduped",
                job.id,
            )
        except Exception:
            logger.exception(
                "Failed to inspect or enqueue full-market EOD coverage market=%s.",
                market,
            )
        finally:
            db.close()


def _add_market_eod_coverage_reconcile_job(scheduler: Any) -> bool:
    if not settings.enable_eod_coverage_scheduler:
        return False
    scheduler.add_job(
        enqueue_market_eod_coverage_reconcile,
        trigger="interval",
        minutes=max(int(settings.scheduler_eod_coverage_interval_minutes), 5),
        id="market_eod_coverage_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(_timezone()),
    )
    return True


def enqueue_us_priority_ohlc_reconcile() -> None:
    db = SessionLocal()
    try:
        latest_completed = (
            db.query(JobRun)
            .filter(JobRun.job_type == US_PRIORITY_OHLC_RECONCILE_JOB_TYPE)
            .filter(JobRun.status == "success")
            .order_by(JobRun.ended_at.desc(), JobRun.id.desc())
            .first()
        )
        cursor_symbol = None
        if latest_completed is not None and latest_completed.result_json:
            try:
                previous_result = json.loads(latest_completed.result_json)
            except (TypeError, json.JSONDecodeError):
                previous_result = None
            if isinstance(previous_result, dict):
                cursor_symbol = previous_result.get("cursor_symbol")
        request = {
            "max_runtime_seconds": settings.scheduler_us_priority_ohlc_max_runtime_seconds,
            "cursor_symbol": cursor_symbol,
        }
        job, created = job_service.enqueue_job(
            db=db,
            job_type=US_PRIORITY_OHLC_RECONCILE_JOB_TYPE,
            target="priority-research",
            request=request,
            progress_total=1,
            message="Queued by cache-only priority US OHLC continuity audit scheduler.",
            task=backfill_tasks.run_us_priority_ohlc_reconcile_job,
            task_args=(
                request["max_runtime_seconds"],
                request["cursor_symbol"],
            ),
        )
        logger.info(
            "Priority US OHLC reconcile %s job_id=%s.",
            "queued" if created else "deduped",
            job.id,
        )
    except Exception:
        logger.exception("Failed to enqueue priority US OHLC continuity audit.")
    finally:
        db.close()


def _add_us_priority_ohlc_reconcile_job(scheduler: Any) -> bool:
    if not settings.enable_us_priority_ohlc_scheduler:
        return False
    scheduler.add_job(
        enqueue_us_priority_ohlc_reconcile,
        trigger="interval",
        minutes=max(int(settings.scheduler_us_priority_ohlc_interval_minutes), 5),
        id="us_priority_ohlc_reconcile",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=(
            datetime.now(_timezone())
            + timedelta(
                seconds=max(
                    int(settings.scheduler_us_priority_ohlc_startup_delay_seconds),
                    0,
                )
            )
        ),
    )
    return True


def start_scheduler() -> Any | None:
    if (
        not settings.enable_scheduler
        and not settings.enable_tw_stock_detail_scheduler
        and not settings.enable_market_chip_margin_scheduler
        and not settings.enable_market_calendar_scheduler
        and not settings.enable_tw_disposition_scheduler
        and not settings.enable_tw_corporate_event_scheduler
        and not settings.enable_us_corporate_event_scheduler
        and not settings.enable_tw_broker_branch_scheduler
        and not settings.enable_tw_broker_branch_behavior_shadow_scheduler
        and not settings.enable_taiwan_market_index_scheduler
        and not settings.enable_taiwan_quote_contract_scheduler
        and not settings.enable_taiwan_intraday_bar_scheduler
        and not settings.enable_taiwan_futures_scheduler
        and not settings.enable_taiwan_derivatives_scheduler
        and not settings.enable_dispatch_scheduler
        and not settings.enable_watchlist_radar_scheduler
        and not settings.enable_us_priority_ohlc_scheduler
        and not settings.enable_eod_coverage_scheduler
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
        if not settings.enable_tw_stock_detail_scheduler:
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
    market_chip_daily_refresh_enabled = _add_market_chip_daily_refresh_jobs(
        scheduler
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
    market_calendar_refresh_enabled = _add_market_calendar_refresh_job(scheduler)
    taiwan_disposition_refresh_enabled = _add_taiwan_disposition_refresh_job(
        scheduler
    )
    taiwan_corporate_event_refresh_enabled = (
        _add_taiwan_corporate_event_refresh_job(scheduler)
    )
    us_corporate_event_refresh_enabled = _add_us_corporate_event_refresh_job(
        scheduler
    )
    taiwan_corporate_event_history_refresh_enabled = (
        _add_taiwan_corporate_event_history_refresh_job(scheduler)
    )
    taiwan_broker_branch_refresh_enabled = (
        _add_taiwan_broker_branch_market_refresh_job(scheduler)
    )
    taiwan_broker_branch_behavior_shadow_enabled = (
        _add_taiwan_broker_branch_behavior_shadow_job(scheduler)
    )
    watchlist_radar_snapshot_enabled = _add_watchlist_radar_auto_snapshot_job(scheduler)
    taiwan_market_index_collector_enabled = _add_taiwan_market_index_collector_job(
        scheduler
    )
    taiwan_source_health_sync_enabled = _add_taiwan_source_health_sync_job(
        scheduler
    )
    taiwan_quote_contract_snapshot_enabled = (
        add_taiwan_quote_contract_snapshot_jobs(scheduler)
    )
    taiwan_intraday_bar_scheduler_enabled = add_taiwan_intraday_bar_jobs(
        scheduler
    )
    taiwan_index_contract_snapshot_enabled = (
        add_taiwan_index_contract_snapshot_jobs(scheduler)
    )
    taiwan_futures_collector_enabled = _add_taiwan_futures_collector_job(scheduler)
    taiwan_derivatives_refresh_enabled = _add_taiwan_derivatives_refresh_job(scheduler)
    dispatch_schedule_tick_enabled = _add_dispatch_schedule_tick_job(scheduler)
    dispatch_schedule_reconcile_enabled = _add_dispatch_schedule_reconcile_job(scheduler)
    market_chip_margin_refresh_enabled = _add_market_chip_margin_refresh_job(
        scheduler
    )
    us_priority_ohlc_reconcile_enabled = _add_us_priority_ohlc_reconcile_job(
        scheduler
    )
    market_eod_coverage_reconcile_enabled = _add_market_eod_coverage_reconcile_job(
        scheduler
    )
    taiwan_stock_detail_daily_refresh_enabled = (
        _add_taiwan_stock_detail_daily_refresh_jobs(scheduler)
    )
    taiwan_daily_metric_repair_enabled = _add_taiwan_daily_metric_repair_jobs(
        scheduler
    )
    taiwan_fundamental_refresh_enabled = add_taiwan_fundamental_refresh_jobs(
        scheduler
    )
    scheduler.start()
    logger.info(
        "Market chip daily scheduler enabled=%s primary=%s retry_delay=%sm.",
        market_chip_daily_refresh_enabled,
        settings.scheduler_market_chip_refresh_time,
        max(int(settings.scheduler_market_chip_refresh_retry_delay_minutes), 1),
    )
    logger.info(
        "Taiwan intraday bar scheduler enabled=%s interval=%ss max_symbols=%s.",
        taiwan_intraday_bar_scheduler_enabled,
        max(int(settings.scheduler_taiwan_intraday_bar_interval_seconds), 60),
        max(int(settings.scheduler_taiwan_intraday_bar_max_symbols), 1),
    )
    logger.info(
        "Priority US OHLC cache-only audit scheduler enabled=%s interval=%sm.",
        us_priority_ohlc_reconcile_enabled,
        max(int(settings.scheduler_us_priority_ohlc_interval_minutes), 5),
    )
    logger.info(
        "Full-market EOD coverage scheduler enabled=%s markets=%s interval=%sm.",
        market_eod_coverage_reconcile_enabled,
        settings.scheduler_eod_coverage_markets,
        max(int(settings.scheduler_eod_coverage_interval_minutes), 5),
    )
    logger.info(
        "Broker-branch shadow behavior scheduler enabled=%s time=%s "
        "lookback_sessions=%s advertised=false.",
        taiwan_broker_branch_behavior_shadow_enabled,
        settings.scheduler_tw_broker_branch_behavior_shadow_time,
        min(
            max(
                int(
                    settings.scheduler_tw_broker_branch_behavior_lookback_sessions
                ),
                2,
            ),
            BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS,
        ),
    )
    logger.info(
        "Taiwan market index summary collector interval=%ss; post-close "
        "reconciliation=%sm until=%s; enabled=%s.",
        max(int(settings.scheduler_taiwan_market_index_interval_seconds), 5),
        max(TAIWAN_INDEX_RECONCILIATION_RETRY_SECONDS // 60, 5),
        TAIWAN_INDEX_RECONCILIATION_END_TIME.strftime("%H:%M"),
        taiwan_market_index_collector_enabled,
    )
    logger.info(
        "Taiwan source-health snapshot sync interval=%ss enabled=%s.",
        max(
            int(settings.scheduler_taiwan_source_health_interval_seconds),
            30,
        ),
        taiwan_source_health_sync_enabled,
    )
    logger.info(
        "Taiwan quote contract fixed-slot snapshots=%s symbols=%s max_symbols=%s "
        "enabled=%s.",
        ",".join(TAIWAN_QUOTE_CONTRACT_SLOTS),
        settings.scheduler_taiwan_quote_contract_symbols or "<watchlist>",
        settings.scheduler_taiwan_quote_contract_max_symbols,
        taiwan_quote_contract_snapshot_enabled,
    )
    logger.info(
        "Taiwan index contract fixed-slot snapshots=%s indices=TAIEX,TPEX "
        "enabled=%s.",
        ",".join(TAIWAN_INDEX_CONTRACT_SLOTS),
        taiwan_index_contract_snapshot_enabled,
    )
    logger.info(
        "Exchange-calendar refresh=%s %s enabled=%s.",
        settings.scheduler_market_calendar_refresh_time,
        settings.timezone,
        market_calendar_refresh_enabled,
    )
    logger.info(
        "Taiwan disposition refresh=%s %s enabled=%s.",
        settings.scheduler_tw_disposition_refresh_time,
        settings.timezone,
        taiwan_disposition_refresh_enabled,
    )
    logger.info(
        "Taiwan corporate-event refresh=%s %s enabled=%s.",
        settings.scheduler_tw_corporate_event_refresh_time,
        settings.timezone,
        taiwan_corporate_event_refresh_enabled,
    )
    logger.info(
        "US corporate-event refresh interval=%sh enabled=%s provider_configured=%s.",
        max(int(settings.scheduler_us_corporate_event_refresh_hours), 1),
        us_corporate_event_refresh_enabled,
        bool(str(settings.alphavantage_api_key or "").strip()),
    )
    logger.info(
        "Taiwan corporate-event history reconciliation=%s %s %s enabled=%s.",
        settings.scheduler_tw_corporate_event_history_refresh_time,
        settings.scheduler_tw_corporate_event_history_refresh_day_of_week,
        settings.timezone,
        taiwan_corporate_event_history_refresh_enabled,
    )
    logger.info(
        "Taiwan all-market broker-branch refresh=%s %s %s; reconcile_interval=%sm "
        "until=%s; max_stocks=%s; sleep=%ss; enabled=%s.",
        settings.scheduler_tw_broker_branch_refresh_time,
        settings.scheduler_tw_broker_branch_refresh_day_of_week,
        settings.timezone,
        max(int(settings.scheduler_tw_broker_branch_reconcile_interval_minutes), 5),
        settings.scheduler_tw_broker_branch_reconcile_until,
        max(int(settings.scheduler_tw_broker_branch_max_stocks), 1),
        max(float(settings.scheduler_tw_broker_branch_sleep_seconds), 0.0),
        taiwan_broker_branch_refresh_enabled,
    )
    logger.info(
        "Taiwan stock-detail daily refresh institutional=%s margin=%s %s; "
        "enabled=%s.",
        settings.scheduler_tw_institutional_refresh_time,
        settings.scheduler_tw_margin_refresh_time,
        settings.timezone,
        taiwan_stock_detail_daily_refresh_enabled,
    )
    logger.info(
        "Taiwan daily-metric bounded repair interval=%sm max_attempts=%s enabled=%s.",
        max(int(settings.scheduler_market_daily_repair_interval_minutes), 5),
        max(int(settings.scheduler_market_daily_repair_max_attempts), 1),
        taiwan_daily_metric_repair_enabled,
    )
    logger.info(
        "Taiwan stock-detail fundamental refresh shareholding=%s Saturday; "
        "revenue=%s day 11/16; financial=%s statutory deadlines; enabled=%s.",
        settings.scheduler_tw_shareholding_refresh_time,
        settings.scheduler_tw_revenue_refresh_time,
        settings.scheduler_tw_financial_refresh_time,
        taiwan_fundamental_refresh_enabled,
    )
    logger.info(
        "Dispatch schedule v2=%s tick_interval=%ss reconcile_interval=%ss reconcile_enabled=%s.",
        settings.dispatch_scheduler_v2_enabled,
        max(int(settings.scheduler_dispatch_tick_interval_seconds), 10),
        max(int(settings.scheduler_dispatch_reconcile_interval_seconds), 30),
        dispatch_schedule_reconcile_enabled,
    )
    logger.info(
        "Job scheduler started. core_scheduler_enabled=%s; market_daily_refresh=%s %s weekdays; market_margin_daily_refresh=%s %s weekdays; market_chip_daily_refresh=%s %s weekdays; market_chip_margin_daily_refresh=%s %s weekdays enabled=%s; us_market_daily_refresh=%s %s %s enabled=%s; jp_market_watchlist_resource_refresh=%s %s %s enabled=%s; kr_market_watchlist_resource_refresh=%s %s %s enabled=%s; watchlist_radar_auto_snapshot=%s %s %s reconcile_interval=%sm reconcile_until=%s enabled=%s; taiwan_futures_quote_collector interval=%ss enabled=%s; taiwan_derivatives_refresh=%s %s %s enabled=%s; dispatch_schedule_tick interval=%ss enabled=%s.",
        settings.enable_scheduler,
        settings.scheduler_market_refresh_time,
        settings.timezone,
        settings.scheduler_market_margin_refresh_time,
        settings.timezone,
        settings.scheduler_market_chip_refresh_time,
        settings.timezone,
        settings.scheduler_market_chip_margin_refresh_time,
        settings.timezone,
        market_chip_margin_refresh_enabled,
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
        max(int(settings.scheduler_watchlist_radar_reconcile_interval_minutes), 5),
        settings.scheduler_watchlist_radar_reconcile_until,
        watchlist_radar_snapshot_enabled,
        max(int(settings.scheduler_taiwan_futures_interval_seconds), 10),
        taiwan_futures_collector_enabled,
        _resolved_taiwan_derivatives_schedule_time().strftime("%H:%M"),
        settings.scheduler_taiwan_derivatives_refresh_day_of_week,
        settings.timezone,
        taiwan_derivatives_refresh_enabled,
        max(int(settings.scheduler_dispatch_tick_interval_seconds), 10),
        dispatch_schedule_tick_enabled,
    )
    return scheduler


def stop_scheduler(scheduler: Any | None) -> None:
    if scheduler is None:
        return

    scheduler.shutdown(wait=False)
    logger.info("Job scheduler stopped.")
