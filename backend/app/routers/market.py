import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.market.daily_metrics_backfill import (
    ensure_latest_daily_metrics,
    ensure_stock_daily_metrics,
)
from app.market.fundamental_metrics_backfill import (
    ensure_stock_fundamental_metrics,
)
from app.market.financial_contract import build_database_financial_contract
from app.market.financial_metrics_history_backfill import ensure_stock_financial_metrics_history
from app.market.monthly_revenue_history_backfill import ensure_stock_monthly_revenue_history
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.market.taiwan_rules import (
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_BROKER_BRANCH,
    TAIWAN_REFRESH_DAILY_PRICE,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
    TAIWAN_REFRESH_PROFILE_PATTERN,
    normalize_refresh_profile,
    refresh_profile_step_count,
)
from app.db.models import StockMaster
from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
from app.settings.refresh_execution import (
    resolve_market_refresh_interval_seconds,
    resolve_subresource_refresh_interval_seconds,
)
from app.market.institutional_holding_ratios import (
    InstitutionalHoldingRatioFetchError,
    fetch_institutional_holding_ratios,
)
from app.market.intraday import get_intraday_trend, get_market_intraday_history
from app.market.index_contract_snapshot import (
    get_taiwan_index_contract_replay,
)
from app.market.quote_depth import (
    get_taiwan_quote_contract_replay,
    get_taiwan_stock_quote_depth,
)
from app.market.kgi_market_data import backfill_taiwan_kgi_market_data
from app.market.providers.kgi_superpy import (
    acquire_kgi_superpy_quote_lease,
    get_kgi_superpy_quote_lease_summary,
    get_kgi_superpy_market_stream_snapshot,
    heartbeat_kgi_superpy_quote_lease,
    release_kgi_superpy_quote_lease,
)
from app.market.market_chips import (
    MarketChipFetchError,
    ensure_market_chip_daily,
    get_latest_market_chip_daily,
    list_market_chip_daily,
    market_chip_daily_to_dict,
    normalize_market_chip_index_ids,
)
from app.market.overnight_impact import (
    build_us_overnight_impact_report,
    ensure_current_us_overnight_impact_report,
)
from app.market.technical_report import build_stock_technical_report
from app.market.next_session_plan import build_tw_stock_next_session_plan
from app.market.next_session_plan_schemas import TaiwanNextSessionPlanRead
from app.market.broker_branch import (
    BrokerBranchFetchError,
    get_broker_branch_trade_summary,
)
from app.market.calendar_status import (
    build_market_calendar_status,
    build_taiwan_calendar_status,
    expected_taiwan_trade_date,
    is_release_released_from_calendar,
)
from app.market.exchange_calendar_refresh import refresh_exchange_calendars
from app.market.tw_disposition import (
    list_taiwan_dispositions,
    refresh_taiwan_dispositions,
)
from app.market.tw_corporate_events import (
    backfill_taiwan_corporate_event_history,
    get_taiwan_stock_event_history,
    list_taiwan_corporate_events,
    refresh_taiwan_corporate_events,
)
from app.routers.tw_market_etfs import router as market_etfs_router
from app.market.source_health import build_taiwan_source_health
from app.market.chart_drawings import (
    ChartDrawingSnapshotNotFoundError,
    delete_chart_drawing_snapshot,
    get_chart_drawing_snapshot,
    list_chart_drawing_snapshots,
    serialize_chart_drawing_snapshot,
    upsert_chart_drawing_snapshot,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    previous_taiwan_trading_day,
)
from app.market.schemas import (
    BrokerBranchTradeDailySummaryRead,
    ChartDrawingSnapshotRead,
    ChartDrawingSnapshotWrite,
    FinancialMetricQuarterlyRead,
    IntradayTrendRead,
    MarketCalendarRefreshRead,
    MarketCalendarStatusRead,
    MarketIntradayChartRead,
    InstitutionalHoldingRatioRead,
    InstitutionalTradeDailyRead,
    MarginTradingDailyRead,
    MarketDailyChartRead,
    MarketChipDailyRead,
    MarketDailyPriceRead,
    MarketOhlcChartRead,
    MonthlyRevenueRead,
    OvernightImpactRead,
    ShareholdingDistributionWeeklyRead,
    StockChipCoverageRead,
    TaiwanRealtimeQuoteLeaseCreate,
    TaiwanRealtimeQuoteLeaseRead,
    TaiwanRealtimeQuoteLeaseSummaryRead,
    TaiwanRealtimeMarketStreamRead,
    TaiwanKgiDataBackfillRead,
    TaiwanKgiDataBackfillRequest,
    TaiwanStockQuoteDepthRead,
    TaiwanIndexContractReplayRead,
    TaiwanQuoteContractReplayRead,
    TaiwanDispositionListRead,
    TaiwanDispositionRefreshRead,
    TaiwanCorporateEventListRead,
    TaiwanCorporateEventRefreshRead,
    TaiwanFinancialContractRead,
    TaiwanStockEventHistoryRead,
    TaiwanSourceHealthRead,
    TechnicalReportRead,
)
from app.market.service import (
    get_latest_stock_financial_metric,
    get_latest_stock_daily_price,
    get_latest_stock_institutional_trade,
    get_latest_stock_margin_trade,
    get_latest_stock_monthly_revenue,
    get_stock_chip_coverage,
    list_financial_metrics,
    list_institutional_trades,
    list_latest_institutional_trades,
    list_latest_margin_trades,
    list_latest_market_daily_prices,
    list_latest_stock_shareholding_distribution,
    list_margin_trades,
    list_market_daily_prices,
    list_monthly_revenues,
    list_shareholding_distributions,
    list_stock_chart_data,
    list_stock_daily_history,
    list_stock_financial_metric_history,
    list_stock_ohlc_chart_data,
    list_stock_institutional_trade_history,
    list_stock_margin_trade_history,
    list_stock_monthly_revenue_history,
    list_stock_shareholding_history,
)
from app.routers.tw_market_indices import (
    get_index_contributions,
    get_index_intraday_trend,
    get_index_ohlc_chart_data,
    get_indices_list,
    get_indices_summary,
    router as market_indices_router,
)
from app.routers.tw_market_futures import (
    get_latest_taiwan_futures_quotes_api,
    list_taiwan_large_traders_api,
    list_taiwan_option_chain_api,
    list_taiwan_term_structure_api,
    list_taiwan_futures_daily_bars_api,
    list_taiwan_futures_intraday_bars_api,
    list_taiwan_futures_products_api,
    refresh_taiwan_derivatives_api,
    refresh_taiwan_futures_daily_bars_api,
    refresh_taiwan_futures_quotes_api,
    router as market_futures_router,
)

router = APIRouter()
router.include_router(market_indices_router)
router.include_router(market_futures_router)
router.include_router(market_etfs_router)

TAIWAN_DAILY_METRIC_CATEGORY_DATASET_KEYS = {
    TAIWAN_REFRESH_DAILY_PRICE: TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE: TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING: TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_BROKER_BRANCH: TAIWAN_DATASET_BROKER_BRANCH,
}


def _split_categories(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_index_ids(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


@router.get("/calendar-status", response_model=MarketCalendarStatusRead)
def get_market_calendar_status(
    market: str = Query(default="all", pattern="^(all|tw|us|jp|kr)$"),
    now: datetime | None = Query(default=None),
):
    try:
        return build_market_calendar_status(market=market, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/calendar-refresh", response_model=MarketCalendarRefreshRead)
def refresh_market_calendar(
    market: str = Query(default="all", pattern="^(all|tw|us|jp|kr)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_exchange_calendars(
            markets=None if market == "all" else [market],
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/tw-dispositions", response_model=TaiwanDispositionListRead)
def get_taiwan_disposition_securities(
    include_upcoming: bool = Query(default=True),
    include_expired: bool = Query(default=False),
    now: datetime | None = Query(default=None),
):
    return list_taiwan_dispositions(
        include_upcoming=include_upcoming,
        include_expired=include_expired,
        now=now,
    )


@router.post("/tw-dispositions/refresh", response_model=TaiwanDispositionRefreshRead)
def refresh_taiwan_disposition_securities(
    db: Session = Depends(get_db),
):
    return refresh_taiwan_dispositions(db=db)


@router.get("/tw-corporate-events", response_model=TaiwanCorporateEventListRead)
def get_taiwan_corporate_events(
    stock_id: str | None = Query(default=None, min_length=1, max_length=20),
    market: str | None = Query(default=None, pattern="^(TWSE|TPEX|twse|tpex)$"),
    event_types: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    now: datetime | None = Query(default=None),
):
    reference_now = now or datetime.now(TAIWAN_TZ)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone.utc)
    calendar_today = reference_now.astimezone(TAIWAN_TZ).date()
    effective_date_from = max(date_from or calendar_today, calendar_today)
    if date_to and date_to < calendar_today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The market calendar only serves today and future events.",
        )
    allowed_types = {"ex_dividend", "financial_report", "investor_conference"}
    requested_types = set(_split_categories(event_types or ""))
    invalid_types = sorted(requested_types - allowed_types)
    if invalid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported event_types: {', '.join(invalid_types)}",
        )
    if date_to and date_to < effective_date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be on or after date_from.",
        )
    if date_to and (date_to - effective_date_from).days > 366:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Corporate-event date range cannot exceed 366 days.",
        )
    return list_taiwan_corporate_events(
        stock_id=stock_id,
        market=market,
        event_types=requested_types,
        date_from=effective_date_from,
        date_to=date_to,
        limit=limit,
        now=now,
    )


@router.get(
    "/tw-corporate-events/history/{stock_id}",
    response_model=TaiwanStockEventHistoryRead,
)
def get_taiwan_corporate_event_history(
    stock_id: str,
    market: str | None = Query(default=None, pattern="^(TWSE|TPEX|twse|tpex)$"),
    years: int = Query(default=5, ge=1, le=10),
    limit: int = Query(default=200, ge=1, le=200),
    now: datetime | None = Query(default=None),
):
    return get_taiwan_stock_event_history(
        stock_id,
        market=market,
        years=years,
        max_results=limit,
        now=now,
    )


@router.post(
    "/tw-corporate-events/refresh",
    response_model=TaiwanCorporateEventRefreshRead,
)
def refresh_taiwan_corporate_event_calendar(
    db: Session = Depends(get_db),
):
    return refresh_taiwan_corporate_events(db=db)


@router.post(
    "/tw-corporate-events/history/backfill",
    response_model=TaiwanCorporateEventRefreshRead,
)
def backfill_taiwan_corporate_event_calendar_history(
    years: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return backfill_taiwan_corporate_event_history(
        years=years,
        force=True,
        db=db,
    )


@router.get("/source-health", response_model=TaiwanSourceHealthRead)
def get_taiwan_source_health(
    stock_id: str | None = None,
    dataset: str | None = None,
    index_id: str | None = None,
    now: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return build_taiwan_source_health(
        db=db,
        stock_id=stock_id,
        dataset=dataset,
        index_id=index_id,
        now=now,
    )


@router.post("/source-health/snapshot", response_model=TaiwanSourceHealthRead)
def sync_taiwan_source_health_snapshot(
    stock_id: str | None = None,
    dataset: str | None = None,
    index_id: str | None = None,
    now: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return build_taiwan_source_health(
        db=db,
        stock_id=stock_id,
        dataset=dataset,
        index_id=index_id,
        now=now,
        sync_snapshots=True,
    )


def _resolve_daily_metric_include_today(
    categories: list[str],
    include_today: bool | None,
) -> bool:
    if include_today is not None:
        return include_today

    now = datetime.now(TAIWAN_TZ)
    calendar_status = build_taiwan_calendar_status(now=now)

    if not calendar_status.get("is_trading_day"):
        return False

    release_keys = [
        TAIWAN_DAILY_METRIC_CATEGORY_DATASET_KEYS[category]
        for category in categories
        if category in TAIWAN_DAILY_METRIC_CATEGORY_DATASET_KEYS
    ]
    if not release_keys:
        return False

    return all(
        is_release_released_from_calendar(
            calendar_status,
            market="tw",
            key=release_key,
        )
        for release_key in release_keys
    )


def _daily_metric_history_range(
    from_date: date | None,
    to_date: date | None,
    lookback_days: int,
    include_today: bool,
) -> tuple[date, date]:
    end_date = to_date or datetime.now(TAIWAN_TZ).date()

    if to_date is None:
        end_date = previous_taiwan_trading_day(
            end_date,
            include_value=include_today,
        )
    else:
        end_date = previous_taiwan_trading_day(end_date, include_value=True)

    start_date = from_date or end_date - timedelta(days=lookback_days)
    return start_date, end_date


def _queue_backfill_job(
    *,
    db: Session,
    background_tasks: BackgroundTasks,
    job_type: str,
    target: str | None,
    request: dict,
    progress_total: int = 1,
    task,
    task_args: tuple,
    reuse_success_within_seconds: float = 0,
):
    del background_tasks

    job, _created = job_service.enqueue_job(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=progress_total,
        message="Queued.",
        task=task,
        task_args=task_args,
        reuse_success_within_seconds=reuse_success_within_seconds,
    )
    return job_service.serialize_job(job)


@router.get(
    "/chart-drawings/{market}/{symbol}",
    response_model=list[ChartDrawingSnapshotRead],
)
def list_stock_chart_drawing_snapshots_api(
    market: str,
    symbol: str,
    db: Session = Depends(get_db),
):
    try:
        rows = list_chart_drawing_snapshots(db=db, market=market, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return [serialize_chart_drawing_snapshot(row) for row in rows]


@router.get(
    "/chart-drawings/{market}/{symbol}/{timeframe}",
    response_model=ChartDrawingSnapshotRead,
)
def get_stock_chart_drawing_snapshot_api(
    market: str,
    symbol: str,
    timeframe: str,
    db: Session = Depends(get_db),
):
    try:
        row = get_chart_drawing_snapshot(
            db=db,
            market=market,
            symbol=symbol,
            timeframe=timeframe,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chart drawing snapshot for {market}:{symbol}:{timeframe} was not found.",
        )

    return serialize_chart_drawing_snapshot(row)


@router.put(
    "/chart-drawings/{market}/{symbol}/{timeframe}",
    response_model=ChartDrawingSnapshotRead,
)
def put_stock_chart_drawing_snapshot_api(
    market: str,
    symbol: str,
    timeframe: str,
    payload: ChartDrawingSnapshotWrite,
    db: Session = Depends(get_db),
):
    try:
        row = upsert_chart_drawing_snapshot(
            db=db,
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            drawings=payload.drawings,
            label=payload.label,
            time_mode=payload.time_mode,
            selected_drawing_id=payload.selected_drawing_id,
            summary=payload.summary,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return serialize_chart_drawing_snapshot(row)


@router.delete(
    "/chart-drawings/{market}/{symbol}/{timeframe}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_stock_chart_drawing_snapshot_api(
    market: str,
    symbol: str,
    timeframe: str,
    db: Session = Depends(get_db),
):
    try:
        delete_chart_drawing_snapshot(
            db=db,
            market=market,
            symbol=symbol,
            timeframe=timeframe,
        )
    except ChartDrawingSnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return None


@router.post(
    "/selection-refresh/{stock_id}",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_selected_stock_data_api(
    stock_id: str,
    background_tasks: BackgroundTasks,
    include_today: bool | None = None,
    profile: str = Query(default="full", pattern=TAIWAN_REFRESH_PROFILE_PATTERN),
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    db: Session = Depends(get_db),
):
    refresh_profile = normalize_refresh_profile(profile)
    progress_total = refresh_profile_step_count(refresh_profile)
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )

    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_selection_refresh",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "include_today": include_today,
            "profile": refresh_profile,
            "sleep_seconds": resolved_sleep_seconds,
        },
        progress_total=progress_total,
        task=backfill_tasks.run_stock_selection_refresh_job,
        task_args=(stock_id, include_today, resolved_sleep_seconds, refresh_profile),
        reuse_success_within_seconds=120,
    )


@router.post(
    "/backfill/twse/{stock_id}",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_twse_stock_daily_prices(
    stock_id: str,
    start_date: date,
    end_date: date,
    background_tasks: BackgroundTasks,
    source_id: int | None = None,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
    db: Session = Depends(get_db),
):
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.twse_daily_price_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
            "source_id": source_id,
            "sleep_seconds": sleep_seconds,
            "skip_existing_months": skip_existing_months,
        },
        task=backfill_tasks.run_twse_daily_price_job,
        task_args=(
            stock_id,
            start_date,
            end_date,
            source_id,
            sleep_seconds,
            skip_existing_months,
        ),
    )


@router.post(
    "/backfill/tpex/{stock_id}",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_tpex_stock_daily_prices(
    stock_id: str,
    start_date: date,
    end_date: date,
    background_tasks: BackgroundTasks,
    source_id: int | None = None,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
    db: Session = Depends(get_db),
):
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.tpex_daily_price_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
            "source_id": source_id,
            "sleep_seconds": sleep_seconds,
            "skip_existing_months": skip_existing_months,
        },
        task=backfill_tasks.run_tpex_daily_price_job,
        task_args=(
            stock_id,
            start_date,
            end_date,
            source_id,
            sleep_seconds,
            skip_existing_months,
        ),
    )


@router.post(
    "/backfill/daily-metrics",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_market_daily_metrics(
    background_tasks: BackgroundTasks,
    start_date: date | None = None,
    end_date: date | None = None,
    categories: str = Query(default="institutional_trade,margin_trading"),
    lookback_days: int = Query(default=30, ge=1, le=1000),
    include_today: bool | None = None,
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    resolved_include_today = _resolve_daily_metric_include_today(
        categories=category_list,
        include_today=include_today,
    )
    resolved_sleep_seconds = resolve_market_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.daily_metrics_backfill",
        target=None,
        request={
            "start_date": start_date,
            "end_date": end_date,
            "categories": category_list,
            "lookback_days": lookback_days,
            "include_today": resolved_include_today,
            "sleep_seconds": resolved_sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_market_daily_metrics_job,
        task_args=(
            start_date,
            end_date,
            category_list,
            lookback_days,
            resolved_include_today,
            resolved_sleep_seconds,
            skip_existing,
            None,
            None,
        ),
    )


@router.post(
    "/backfill/daily-metrics/{stock_id}/history",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_stock_daily_metrics_history(
    stock_id: str,
    background_tasks: BackgroundTasks,
    from_date: date | None = None,
    to_date: date | None = None,
    categories: str = Query(default="institutional_trade,margin_trading"),
    lookback_days: int = Query(default=365, ge=1, le=5000),
    include_today: bool | None = None,
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    resolved_include_today = _resolve_daily_metric_include_today(
        categories=category_list,
        include_today=include_today,
    )
    start_date, end_date = _daily_metric_history_range(
        from_date=from_date,
        to_date=to_date,
        lookback_days=lookback_days,
        include_today=resolved_include_today,
    )
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_daily_metrics_history_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
            "categories": category_list,
            "include_today": resolved_include_today,
            "sleep_seconds": resolved_sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_daily_metrics_history_job,
        task_args=(
            stock_id,
            start_date,
            end_date,
            category_list,
            resolved_sleep_seconds,
            skip_existing,
        ),
    )


@router.post(
    "/backfill/fundamentals",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_market_fundamental_metrics(
    background_tasks: BackgroundTasks,
    categories: str = Query(
        default="shareholding_distribution,monthly_revenue,financial_metrics"
    ),
    force: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    resolved_sleep_seconds = resolve_market_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.fundamental_metrics_backfill",
        target=None,
        request={
            "categories": category_list,
            "force": force,
            "sleep_seconds": resolved_sleep_seconds,
        },
        task=backfill_tasks.run_market_fundamental_metrics_job,
        task_args=(category_list, force, resolved_sleep_seconds),
    )


@router.post(
    "/backfill/fundamentals/{stock_id}",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_stock_fundamental_metrics(
    stock_id: str,
    background_tasks: BackgroundTasks,
    categories: str = Query(
        default="shareholding_distribution,monthly_revenue,financial_metrics"
    ),
    force: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_fundamental_metrics_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "categories": category_list,
            "force": force,
            "sleep_seconds": resolved_sleep_seconds,
        },
        task=backfill_tasks.run_stock_fundamental_metrics_job,
        task_args=(stock_id, category_list, force, resolved_sleep_seconds),
    )


@router.post(
    "/backfill/shareholding/{stock_id}/history",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_stock_shareholding_history(
    stock_id: str,
    background_tasks: BackgroundTasks,
    from_date: date | None = None,
    to_date: date | None = None,
    lookback_weeks: int = Query(default=52, ge=1, le=60),
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_shareholding_history_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "from_date": from_date,
            "to_date": to_date,
            "lookback_weeks": lookback_weeks,
            "sleep_seconds": resolved_sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_shareholding_history_job,
        task_args=(
            stock_id,
            from_date,
            to_date,
            lookback_weeks,
            resolved_sleep_seconds,
            skip_existing,
        ),
    )


@router.post(
    "/backfill/revenue/{stock_id}/history",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_stock_monthly_revenue_history(
    stock_id: str,
    background_tasks: BackgroundTasks,
    from_period: date | None = None,
    to_period: date | None = None,
    lookback_months: int = Query(default=120, ge=1, le=120),
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_monthly_revenue_history_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "from_period": from_period,
            "to_period": to_period,
            "lookback_months": lookback_months,
            "sleep_seconds": resolved_sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_monthly_revenue_history_job,
        task_args=(
            stock_id,
            from_period,
            to_period,
            lookback_months,
            resolved_sleep_seconds,
            skip_existing,
        ),
    )


@router.post(
    "/backfill/financials/{stock_id}/history",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_stock_financial_metrics_history(
    stock_id: str,
    background_tasks: BackgroundTasks,
    from_fiscal_year: int | None = Query(default=None, ge=1900, le=2100),
    from_quarter: int | None = Query(default=None, ge=1, le=4),
    to_fiscal_year: int | None = Query(default=None, ge=1900, le=2100),
    to_quarter: int | None = Query(default=None, ge=1, le=4),
    lookback_quarters: int = Query(default=40, ge=1, le=80),
    sleep_seconds: float | None = Query(default=None, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_financial_metrics_history_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "from_fiscal_year": from_fiscal_year,
            "from_quarter": from_quarter,
            "to_fiscal_year": to_fiscal_year,
            "to_quarter": to_quarter,
            "lookback_quarters": lookback_quarters,
            "sleep_seconds": resolved_sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_financial_metrics_history_job,
        task_args=(
            stock_id,
            from_fiscal_year,
            from_quarter,
            to_fiscal_year,
            to_quarter,
            lookback_quarters,
            resolved_sleep_seconds,
            skip_existing,
        ),
    )


@router.get("/ohlc/{stock_id}", response_model=MarketOhlcChartRead)
def get_stock_ohlc_chart_data(
    stock_id: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    ensure_history: bool = False,
    include_intraday: bool = False,
    to_date: date | None = None,
    sleep_seconds: float = Query(default=0.08, ge=0, le=2),
    db: Session = Depends(get_db),
):
    try:
        return list_stock_ohlc_chart_data(
            db=db,
            stock_id=stock_id,
            timeframe=timeframe,
            bars=bars,
            ensure_history=ensure_history,
            include_intraday=include_intraday,
            to_date=to_date,
            sleep_seconds=sleep_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/intraday/{stock_id}", response_model=IntradayTrendRead)
def get_stock_intraday_trend(
    stock_id: str,
    db: Session = Depends(get_db),
):
    return get_intraday_trend(db=db, stock_id=stock_id)


@router.get("/intraday/{stock_id}/history", response_model=MarketIntradayChartRead)
def get_stock_intraday_history(
    stock_id: str,
    interval: str = Query(default="1m", pattern="^(1m|5m|15m|30m|1h|4h)$"),
    range_value: str = Query(default="auto", alias="range", pattern="^(auto|1d|5d|1mo|3mo)$"),
    refresh: bool = True,
    db: Session = Depends(get_db),
):
    try:
        return get_market_intraday_history(
            db=db,
            stock_id=stock_id,
            interval=interval,
            range_value=range_value,
            refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/quote-depth/{stock_id}", response_model=TaiwanStockQuoteDepthRead)
def get_stock_quote_depth(
    stock_id: str,
    refresh: bool = True,
    db: Session = Depends(get_db),
):
    try:
        return get_taiwan_stock_quote_depth(
            db=db,
            stock_id=stock_id,
            refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/realtime-quote-leases/summary",
    response_model=TaiwanRealtimeQuoteLeaseSummaryRead,
)
def get_realtime_quote_lease_summary():
    return get_kgi_superpy_quote_lease_summary()


@router.post(
    "/realtime-quote-leases",
    response_model=TaiwanRealtimeQuoteLeaseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_realtime_quote_lease(
    request: TaiwanRealtimeQuoteLeaseCreate,
    db: Session = Depends(get_db),
):
    stock_id = str(request.stock_id or "").strip()
    if not stock_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stock_id is required.",
        )
    stock_exists = (
        db.query(StockMaster.stock_id)
        .filter(StockMaster.stock_id == stock_id)
        .first()
        is not None
    )
    if not stock_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown Taiwan stock id: {stock_id}",
        )
    return acquire_kgi_superpy_quote_lease(
        stock_id,
        owner_kind=request.owner_kind,
    )


@router.patch(
    "/realtime-quote-leases/{lease_id}",
    response_model=TaiwanRealtimeQuoteLeaseRead,
)
def heartbeat_realtime_quote_lease(lease_id: str):
    lease = heartbeat_kgi_superpy_quote_lease(lease_id)
    if lease is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realtime quote lease was not found or has expired.",
        )
    return lease


@router.delete(
    "/realtime-quote-leases/{lease_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_realtime_quote_lease(lease_id: str):
    release_kgi_superpy_quote_lease(lease_id)
    return None


@router.post(
    "/kgi-data/{stock_id}/backfill",
    response_model=TaiwanKgiDataBackfillRead,
)
def backfill_kgi_market_data(
    stock_id: str,
    request: TaiwanKgiDataBackfillRequest,
    db: Session = Depends(get_db),
):
    normalized = str(stock_id or "").strip()
    stock_exists = (
        db.query(StockMaster.stock_id)
        .filter(StockMaster.stock_id == normalized)
        .first()
        is not None
    )
    if not stock_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown Taiwan stock id: {normalized}",
        )
    try:
        return backfill_taiwan_kgi_market_data(
            stock_id=normalized,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _taiwan_realtime_sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


async def _iter_taiwan_realtime_quote_sse(
    request: Request,
    *,
    stock_id: str,
    interval_ms: int,
):
    interval_seconds = interval_ms / 1000
    while not await request.is_disconnected():
        payload = TaiwanRealtimeMarketStreamRead.model_validate(
            get_kgi_superpy_market_stream_snapshot(stock_id)
        ).model_dump(mode="json")
        yield _taiwan_realtime_sse_event("snapshot", payload)
        await asyncio.sleep(interval_seconds)


@router.get(
    "/realtime-quotes/{stock_id}",
    response_model=TaiwanRealtimeMarketStreamRead,
)
def get_realtime_quote_stream_snapshot(
    stock_id: str,
    recent_trade_limit: int = Query(default=40, ge=1, le=60),
    auction_limit: int = Query(default=40, ge=1, le=120),
    kbar_limit: int = Query(default=60, ge=1, le=120),
    diagnostic_limit: int = Query(default=0, ge=0, le=240),
):
    try:
        return get_kgi_superpy_market_stream_snapshot(
            stock_id,
            recent_trade_limit=recent_trade_limit,
            auction_limit=auction_limit,
            kbar_limit=kbar_limit,
            diagnostic_limit=diagnostic_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/realtime-quotes/{stock_id}/stream")
async def stream_realtime_quote_snapshots(
    request: Request,
    stock_id: str,
    interval_ms: int = Query(default=500, ge=250, le=5000),
):
    try:
        get_kgi_superpy_market_stream_snapshot(stock_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return StreamingResponse(
        _iter_taiwan_realtime_quote_sse(
            request,
            stock_id=stock_id,
            interval_ms=interval_ms,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/quote-depth/{stock_id}/replay",
    response_model=TaiwanQuoteContractReplayRead,
)
def get_stock_quote_depth_replay(
    stock_id: str,
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return get_taiwan_quote_contract_replay(
            db=db,
            stock_id=stock_id,
            trade_date=trade_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/index/{index_id}/contract-replay",
    response_model=TaiwanIndexContractReplayRead,
)
def get_index_contract_replay(
    index_id: str,
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return get_taiwan_index_contract_replay(
            db=db,
            index_id=index_id,
            trade_date=trade_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/technical/{stock_id}/next-session-plan",
    response_model=TaiwanNextSessionPlanRead,
)
def get_stock_next_session_plan(
    stock_id: str,
    db: Session = Depends(get_db),
):
    try:
        return build_tw_stock_next_session_plan(
            db=db,
            stock_id=stock_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/technical/{stock_id}", response_model=TechnicalReportRead)
def get_stock_technical_report(
    stock_id: str,
    timeframe: str = Query(default="daily", pattern="^(today|daily|weekly|monthly)$"),
    include_intraday: bool = True,
    db: Session = Depends(get_db),
):
    try:
        return build_stock_technical_report(
            db=db,
            stock_id=stock_id,
            timeframe=timeframe,
            include_intraday=include_intraday,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/overnight-impact/{stock_id}", response_model=OvernightImpactRead)
def get_stock_overnight_impact(
    stock_id: str,
    refresh: bool = True,
    max_refresh_symbols: int = Query(default=8, ge=1, le=8),
    db: Session = Depends(get_db),
):
    try:
        if not refresh:
            return build_us_overnight_impact_report(
                db=db,
                stock_id=stock_id,
                suppress_stale_signal=True,
            )

        return ensure_current_us_overnight_impact_report(
            db=db,
            stock_id=stock_id,
            max_refresh_symbols=max_refresh_symbols,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/market-chips/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_market_chip_daily_api(
    background_tasks: BackgroundTasks,
    index_ids: str = Query(default="TAIEX,TPEX"),
    trade_date: date | None = None,
    include_today: bool | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
):
    try:
        index_id_list = normalize_market_chip_index_ids(_split_index_ids(index_ids))
        target_trade_date = trade_date or expected_taiwan_trade_date(
            "market_chip_daily",
            include_today=include_today,
        )
        if target_trade_date is None:
            raise ValueError("No expected trade date is available for market chip refresh.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.market_chip_daily_refresh",
        target="market-chips",
        request={
            "index_ids": index_id_list,
            "trade_date": target_trade_date,
            "include_today": include_today,
            "force": force,
        },
        progress_total=len(index_id_list),
        task=backfill_tasks.run_market_chip_daily_refresh_job,
        task_args=(index_id_list, target_trade_date, include_today, force),
    )


@router.get("/market-chips/latest", response_model=MarketChipDailyRead)
def get_latest_market_chip_daily_api(
    index_id: str = Query(default="TAIEX", pattern="^(TAIEX|TPEX)$"),
    ensure_latest: bool = False,
    include_today: bool | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
):
    try:
        if ensure_latest:
            row = ensure_market_chip_daily(
                db=db,
                index_id=index_id,
                include_today=include_today,
                force=force,
            )
        else:
            row = get_latest_market_chip_daily(db=db, index_id=index_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except MarketChipFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest market chip data for index_id='{index_id}' not found.",
        )

    return market_chip_daily_to_dict(row, db=db, resolve_expected_margin=True)


@router.get("/market-chips", response_model=list[MarketChipDailyRead])
def list_market_chip_daily_api(
    index_id: str = Query(default="TAIEX", pattern="^(TAIEX|TPEX)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    return [
        market_chip_daily_to_dict(row)
        for row in list_market_chip_daily(
            db=db,
            index_id=index_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    ]


@router.get("/institutional/latest", response_model=list[InstitutionalTradeDailyRead])
def get_latest_institutional_trades(limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_latest_institutional_trades(db=db, limit=limit, offset=offset)


@router.get("/institutional/{stock_id}/latest", response_model=InstitutionalTradeDailyRead)
def get_latest_stock_institutional_trade_api(
    stock_id: str,
    ensure_daily: bool = False,
    include_today: bool | None = None,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_daily:
        resolved_include_today = _resolve_daily_metric_include_today(
            categories=["institutional_trade"],
            include_today=include_today,
        )
        ensure_latest_daily_metrics(
            db=db,
            categories=["institutional_trade"],
            include_today=resolved_include_today,
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_institutional_trade(db=db, stock_id=stock_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Latest institutional trade for stock_id='{stock_id}' not found.")
    return result


@router.get("/institutional/{stock_id}/history", response_model=list[InstitutionalTradeDailyRead])
def get_stock_institutional_trade_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    ensure_history: bool = False,
    lookback_days: int = Query(default=365, ge=1, le=5000),
    include_today: bool | None = None,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        resolved_include_today = _resolve_daily_metric_include_today(
            categories=["institutional_trade"],
            include_today=include_today,
        )
        start_date, end_date = _daily_metric_history_range(
            from_date=from_date,
            to_date=to_date,
            lookback_days=lookback_days,
            include_today=resolved_include_today,
        )
        ensure_stock_daily_metrics(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            categories=["institutional_trade"],
            sleep_seconds=sleep_seconds,
        )

    return list_stock_institutional_trade_history(db=db, stock_id=stock_id, from_date=from_date, to_date=to_date, limit=limit, ascending=True)


@router.get(
    "/institutional/{stock_id}/holding-ratios",
    response_model=InstitutionalHoldingRatioRead,
)
def get_stock_institutional_holding_ratios(stock_id: str):
    try:
        return fetch_institutional_holding_ratios(stock_id=stock_id)
    except InstitutionalHoldingRatioFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/institutional", response_model=list[InstitutionalTradeDailyRead])
def get_institutional_trades(trade_date: date | None = None, stock_id: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_institutional_trades(db=db, trade_date=trade_date, stock_id=stock_id, limit=limit, offset=offset)


@router.get(
    "/broker-branches/{stock_id}/daily",
    response_model=BrokerBranchTradeDailySummaryRead,
)
def get_stock_broker_branch_daily(
    stock_id: str,
    trade_date: date | None = None,
    days: int = Query(default=1, ge=1, le=120),
    ensure_daily: bool = False,
    force: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return get_broker_branch_trade_summary(
            db=db,
            stock_id=stock_id,
            trade_date=trade_date,
            days=days,
            ensure_daily=ensure_daily,
            force=force,
        )
    except BrokerBranchFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/margin/latest", response_model=list[MarginTradingDailyRead])
def get_latest_margin_trades(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_latest_margin_trades(db=db, limit=limit, offset=offset)


@router.get("/margin/{stock_id}/latest", response_model=MarginTradingDailyRead)
def get_latest_stock_margin_trade_api(
    stock_id: str,
    ensure_daily: bool = False,
    include_today: bool | None = None,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_daily:
        resolved_include_today = _resolve_daily_metric_include_today(
            categories=["margin_trading"],
            include_today=include_today,
        )
        ensure_latest_daily_metrics(
            db=db,
            categories=["margin_trading"],
            include_today=resolved_include_today,
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_margin_trade(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest margin trading for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/margin/{stock_id}/history", response_model=list[MarginTradingDailyRead])
def get_stock_margin_trade_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    ensure_history: bool = False,
    lookback_days: int = Query(default=365, ge=1, le=5000),
    include_today: bool | None = None,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        resolved_include_today = _resolve_daily_metric_include_today(
            categories=["margin_trading"],
            include_today=include_today,
        )
        start_date, end_date = _daily_metric_history_range(
            from_date=from_date,
            to_date=to_date,
            lookback_days=lookback_days,
            include_today=resolved_include_today,
        )
        ensure_stock_daily_metrics(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            categories=["margin_trading"],
            sleep_seconds=sleep_seconds,
        )

    return list_stock_margin_trade_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )


@router.get("/margin", response_model=list[MarginTradingDailyRead])
def get_margin_trades(
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_margin_trades(
        db=db,
        trade_date=trade_date,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/chips/{stock_id}/coverage",
    response_model=StockChipCoverageRead,
)
def get_stock_chip_coverage_api(stock_id: str, db: Session = Depends(get_db)):
    return get_stock_chip_coverage(db=db, stock_id=stock_id)


@router.get(
    "/shareholding/{stock_id}/latest",
    response_model=list[ShareholdingDistributionWeeklyRead],
)
def get_latest_stock_shareholding_distribution_api(
    stock_id: str,
    ensure_latest: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_latest:
        ensure_stock_fundamental_metrics(
            db=db,
            stock_id=stock_id,
            categories=["shareholding_distribution"],
            sleep_seconds=sleep_seconds,
        )

    return list_latest_stock_shareholding_distribution(db=db, stock_id=stock_id)


@router.get(
    "/shareholding/{stock_id}/history",
    response_model=list[ShareholdingDistributionWeeklyRead],
)
def get_stock_shareholding_history_api(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=5000, ge=1, le=20000),
    ensure_history: bool = False,
    lookback_weeks: int = Query(default=52, ge=1, le=60),
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        ensure_stock_shareholding_history(
            db=db,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            lookback_weeks=lookback_weeks,
            sleep_seconds=sleep_seconds,
        )

    return list_stock_shareholding_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.get("/shareholding", response_model=list[ShareholdingDistributionWeeklyRead])
def get_shareholding_distributions(
    data_date: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_shareholding_distributions(
        db=db,
        data_date=data_date,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )


@router.get("/revenue/{stock_id}/latest", response_model=MonthlyRevenueRead)
def get_latest_stock_monthly_revenue_api(
    stock_id: str,
    ensure_latest: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_latest:
        ensure_stock_fundamental_metrics(
            db=db,
            stock_id=stock_id,
            categories=["monthly_revenue"],
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_monthly_revenue(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest monthly revenue for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/revenue/{stock_id}/history", response_model=list[MonthlyRevenueRead])
def get_stock_monthly_revenue_history_api(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=120, ge=1, le=5000),
    ensure_history: bool = False,
    backfill_months: int | None = Query(default=None, ge=1, le=120),
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        ensure_stock_monthly_revenue_history(
            db=db,
            stock_id=stock_id,
            from_period=from_date,
            to_period=to_date,
            lookback_months=backfill_months or min(limit, 120),
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        )

    return list_stock_monthly_revenue_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )


@router.get("/revenue", response_model=list[MonthlyRevenueRead])
def get_monthly_revenues(
    period: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_monthly_revenues(
        db=db,
        period=period,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )


@router.get("/financials/{stock_id}/latest", response_model=FinancialMetricQuarterlyRead)
def get_latest_stock_financial_metric_api(
    stock_id: str,
    ensure_latest: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_latest:
        ensure_stock_fundamental_metrics(
            db=db,
            stock_id=stock_id,
            categories=["financial_metrics"],
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_financial_metric(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest financial metric for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/financials/{stock_id}/history", response_model=list[FinancialMetricQuarterlyRead])
def get_stock_financial_metric_history_api(
    stock_id: str,
    limit: int = Query(default=40, ge=1, le=400),
    ensure_history: bool = False,
    backfill_quarters: int | None = Query(default=None, ge=1, le=80),
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        ensure_stock_financial_metrics_history(
            db=db,
            stock_id=stock_id,
            lookback_quarters=backfill_quarters or min(limit, 80),
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        )

    return list_stock_financial_metric_history(
        db=db,
        stock_id=stock_id,
        limit=limit,
        ascending=True,
    )


@router.get(
    "/financials/{stock_id}/contract",
    response_model=TaiwanFinancialContractRead,
)
def get_stock_financial_contract_api(
    stock_id: str,
    mode: str = Query(
        default="current_comparable",
        pattern="^(current_comparable|as_reported_as_of)$",
    ),
    as_of: datetime | None = None,
    financial_limit: int = Query(default=8, ge=1, le=40),
    revenue_limit: int = Query(default=24, ge=1, le=120),
    price: Decimal | None = Query(default=None, gt=0),
    price_as_of: datetime | None = None,
    price_basis: str = Query(
        default="explicit_input",
        min_length=1,
        max_length=80,
    ),
    db: Session = Depends(get_db),
):
    if (price is None) != (price_as_of is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="price and price_as_of must be provided together",
        )
    financial_history = list_stock_financial_metric_history(
        db=db,
        stock_id=stock_id,
        limit=financial_limit,
        ascending=True,
    )
    revenue_history = list_stock_monthly_revenue_history(
        db=db,
        stock_id=stock_id,
        limit=revenue_limit,
        ascending=True,
    )
    return build_database_financial_contract(
        db,
        stock_id=stock_id,
        financial_history=financial_history,
        revenue_history=revenue_history,
        mode=mode,
        as_of=as_of,
        price=price,
        price_as_of=price_as_of,
        price_basis=price_basis,
        normalized_period_limit=min(financial_limit + 1, 41),
    )


@router.get("/financials", response_model=list[FinancialMetricQuarterlyRead])
def get_financial_metrics(
    stock_id: str | None = None,
    fiscal_year: int | None = None,
    quarter: int | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_financial_metrics(
        db=db,
        stock_id=stock_id,
        fiscal_year=fiscal_year,
        quarter=quarter,
        limit=limit,
        offset=offset,
    )



@router.get("/daily/latest", response_model=list[MarketDailyPriceRead])
def get_latest_market_daily_prices(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_latest_market_daily_prices(
        db=db,
        limit=limit,
        offset=offset,
    )


@router.get("/daily/{stock_id}/latest", response_model=MarketDailyPriceRead)
def get_latest_stock_daily_price_api(
    stock_id: str,
    db: Session = Depends(get_db),
):
    result = get_latest_stock_daily_price(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest market daily price for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/daily/{stock_id}/history", response_model=list[MarketDailyPriceRead])
def get_stock_daily_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )


@router.get("/daily/{stock_id}/chart", response_model=list[MarketDailyChartRead])
def get_stock_daily_chart_data(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_stock_chart_data(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.get("/daily", response_model=list[MarketDailyPriceRead])
def get_market_daily_prices(
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_market_daily_prices(
        db=db,
        trade_date=trade_date,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )
