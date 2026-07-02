from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.market.daily_metrics_backfill import (
    ensure_latest_daily_metrics,
    ensure_stock_daily_metrics,
)
from app.market.fundamental_metrics_backfill import (
    ensure_stock_fundamental_metrics,
)
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
from app.db.models import JobRun, utc_now
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
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_list,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.intraday import get_intraday_trend, get_market_intraday_history
from app.market.quote_depth import get_taiwan_stock_quote_depth
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
from app.market.tw_futures import (
    KGI_PROVIDER,
    TaiwanFuturesFetchError,
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    list_taiwan_futures_products,
    refresh_taiwan_futures_daily_bars,
    refresh_taiwan_futures_quotes,
    resolve_taiwan_futures_quote_provider,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
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
    MarketCalendarStatusRead,
    MarketIntradayChartRead,
    IntradayTrendRead,
    InstitutionalHoldingRatioRead,
    InstitutionalTradeDailyRead,
    MarginTradingDailyRead,
    MarketDailyChartRead,
    MarketIndexContributionRead,
    MarketIndexListRead,
    MarketIndexSummaryRead,
    MarketChipDailyRead,
    MarketOhlcChartRead,
    MarketDailyPriceRead,
    MonthlyRevenueRead,
    OvernightImpactRead,
    ShareholdingDistributionWeeklyRead,
    StockChipCoverageRead,
    TaiwanFuturesIntradayBarRead,
    TaiwanFuturesDailyBarRead,
    TaiwanFuturesProductRead,
    TaiwanFuturesQuoteRead,
    TaiwanStockQuoteDepthRead,
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

router = APIRouter()

TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE = "market.tw_futures_quote_refresh"
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
    market: str = Query(default="all", pattern="^(all|tw|us)$"),
    now: datetime | None = Query(default=None),
):
    try:
        return build_market_calendar_status(market=market, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


def _taiwan_futures_quote_source_name(provider: str | None) -> str:
    if resolve_taiwan_futures_quote_provider(provider) == KGI_PROVIDER:
        return "KGI"
    return "TAIFEX MIS"


def _format_taiwan_futures_quote_source_error(
    exc: TaiwanFuturesFetchError,
    *,
    provider: str | None = None,
) -> str:
    text = str(exc)
    source_name = _taiwan_futures_quote_source_name(provider)
    if "520" in text:
        return f"{source_name} 即時報價來源暫時回應 520，已改用快取資料。"

    return f"{source_name} 即時報價暫時無法讀取，已改用快取資料。"


def _record_taiwan_futures_quote_refresh_issue(
    db: Session,
    *,
    symbols: str,
    session: str,
    provider: str | None,
    exc: TaiwanFuturesFetchError,
    cached_count: int,
) -> None:
    symbol_list = _split_index_ids(symbols) or ["TXF", "MXF", "TMF"]
    target = ",".join(symbol_list)
    requested_count = max(len(symbol_list), 1)
    source_name = _taiwan_futures_quote_source_name(provider)
    resolved_provider = resolve_taiwan_futures_quote_provider(provider)
    message = _format_taiwan_futures_quote_source_error(exc, provider=provider)
    has_cache = cached_count > 0
    status_value = "partial_success" if has_cache else "error"
    if not has_cache:
        message = f"{source_name} 即時報價暫時無法讀取，且目前沒有可用快取。"

    result = {
        "status": status_value,
        "message": message,
        "requested_count": requested_count,
        "success_count": cached_count if has_cache else 0,
        "warning_count": requested_count if has_cache else 0,
        "error_count": 0 if has_cache else requested_count,
        "results": [
            {
                "symbol": symbol,
                "resource": "台指期即時報價",
                "source_name": source_name,
                "status": "partial_success" if has_cache else "error",
                "message": message,
                "error_message": message,
            }
            for symbol in symbol_list
        ],
    }

    cutoff = utc_now() - timedelta(minutes=5)
    job = (
        db.query(JobRun)
        .filter(JobRun.job_type == TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE)
        .filter(JobRun.target == target)
        .filter(JobRun.updated_at >= cutoff)
        .order_by(JobRun.updated_at.desc(), JobRun.id.desc())
        .first()
    )

    if job is None:
        job = job_service.create_job(
            db=db,
            job_type=TAIWAN_FUTURES_QUOTE_REFRESH_JOB_TYPE,
            target=target,
            request={
                "symbols": symbol_list,
                "session": session,
                "source": source_name,
                "provider": resolved_provider,
            },
            progress_total=requested_count,
            message="Refreshing Taiwan futures quotes.",
        )
    else:
        job.progress_current = cached_count if has_cache else 0
        job.progress_total = requested_count
        db.commit()
        db.refresh(job)

    if has_cache:
        job_service.complete_job(db=db, job_id=job.id, result=result, message=message)
    else:
        job_service.fail_job(db=db, job_id=job.id, error_message=message, result=result)


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


@router.get(
    "/tw-futures/products",
    response_model=list[TaiwanFuturesProductRead],
)
def list_taiwan_futures_products_api():
    return list_taiwan_futures_products()


@router.post(
    "/tw-futures/refresh",
    response_model=list[TaiwanFuturesQuoteRead],
)
def refresh_taiwan_futures_quotes_api(
    symbols: str = Query(default="TXF,MXF,TMF"),
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    source_error: str | None = None
    try:
        rows = refresh_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            session=session,
            active_only=active_only,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        source_error = str(exc)
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=False,
            session=session,
            provider=provider,
        )
        _record_taiwan_futures_quote_refresh_issue(
            db=db,
            symbols=symbols,
            session=session,
            provider=provider,
            exc=exc,
            cached_count=len(rows),
        )

    return [
        taiwan_futures_quote_to_dict(
            row,
            expected_session=session,
            source_error=source_error,
        )
        for row in rows
    ]


@router.get(
    "/tw-futures/latest",
    response_model=list[TaiwanFuturesQuoteRead],
)
def get_latest_taiwan_futures_quotes_api(
    symbols: str = Query(default="TXF,MXF,TMF"),
    refresh: bool = False,
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    db: Session = Depends(get_db),
):
    source_error: str | None = None
    try:
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=refresh,
            session=session,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        source_error = str(exc)
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=False,
            session=session,
            provider=provider,
        )
        _record_taiwan_futures_quote_refresh_issue(
            db=db,
            symbols=symbols,
            session=session,
            provider=provider,
            exc=exc,
            cached_count=len(rows),
        )

    return [
        taiwan_futures_quote_to_dict(
            row,
            expected_session=session,
            source_error=source_error,
        )
        for row in rows
    ]


@router.get(
    "/tw-futures/{symbol}/daily",
    response_model=list[TaiwanFuturesDailyBarRead],
)
def list_taiwan_futures_daily_bars_api(
    symbol: str,
    limit: int = Query(default=120, ge=1, le=1000),
    refresh: bool = False,
    lookback_days: int = Query(default=45, ge=1, le=730),
    start_date: date | None = None,
    end_date: date | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    try:
        if refresh:
            try:
                refresh_taiwan_futures_daily_bars(
                    db=db,
                    symbols=[symbol],
                    start_date=start_date,
                    end_date=end_date,
                    lookback_days=lookback_days,
                    force=False,
                )
            except TaiwanFuturesFetchError:
                existing_rows = list_taiwan_futures_daily_bars(
                    db=db,
                    symbol=symbol,
                    limit=limit,
                    active_only=active_only,
                )
                if not existing_rows:
                    raise

        rows = list_taiwan_futures_daily_bars(
            db=db,
            symbol=symbol,
            limit=limit,
            active_only=active_only,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return [taiwan_futures_daily_bar_to_dict(row) for row in rows]


@router.get(
    "/tw-futures/{symbol}/intraday",
    response_model=list[TaiwanFuturesIntradayBarRead],
)
def list_taiwan_futures_intraday_bars_api(
    symbol: str,
    interval: str = Query(default="1m", pattern="^1m$"),
    limit: int = Query(default=390, ge=1, le=3000),
    refresh: bool = True,
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    refresh_error: TaiwanFuturesFetchError | None = None
    try:
        if refresh:
            try:
                refresh_taiwan_futures_quotes(
                    db=db,
                    symbols=[symbol],
                    session=session,
                    active_only=True,
                    provider=provider,
                )
            except TaiwanFuturesFetchError as exc:
                db.rollback()
                refresh_error = exc

        rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=symbol,
            interval=interval,
            limit=limit,
            trade_date=trade_date,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not rows and refresh_error is not None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(refresh_error),
        ) from refresh_error

    return [taiwan_futures_intraday_bar_to_dict(row) for row in rows]


@router.get("/indices/summary", response_model=MarketIndexSummaryRead)
def get_indices_summary(
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    return get_market_index_summary(db=db, force_refresh=force_refresh)


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

    return market_chip_daily_to_dict(row)


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


@router.get("/indices/list", response_model=MarketIndexListRead)
def get_indices_list(
    market: str = Query(default="TWSE", pattern="^(TWSE|TPEX)$"),
    limit: int = Query(default=80, ge=1, le=200),
):
    try:
        return get_market_index_list(market=market, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index list source unavailable: {exc}",
        ) from exc


@router.get("/indices/{index_id}/intraday", response_model=IntradayTrendRead)
def get_index_intraday_trend(index_id: str):
    try:
        return get_market_index_intraday(index_id=index_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index intraday source unavailable: {exc}",
        ) from exc


@router.get("/indices/{index_id}/contributions", response_model=MarketIndexContributionRead)
def get_index_contributions(
    index_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return get_market_index_contributions(index_id=index_id, limit=limit, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index contribution source unavailable: {exc}",
        ) from exc


@router.get("/indices/{index_id}/ohlc", response_model=MarketOhlcChartRead)
def get_index_ohlc_chart_data(
    index_id: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return get_market_index_ohlc_chart_data(
            index_id=index_id,
            timeframe=timeframe,
            bars=bars,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index chart source unavailable: {exc}",
        ) from exc


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
