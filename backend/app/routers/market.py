from datetime import date, datetime, time, timedelta

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
from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
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
from app.market.intraday import get_intraday_trend
from app.market.broker_branch import (
    BrokerBranchFetchError,
    get_broker_branch_trade_summary,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    previous_taiwan_trading_day,
)
from app.market.schemas import (
    BrokerBranchTradeDailySummaryRead,
    FinancialMetricQuarterlyRead,
    IntradayTrendRead,
    InstitutionalHoldingRatioRead,
    InstitutionalTradeDailyRead,
    MarginTradingDailyRead,
    MarketDailyChartRead,
    MarketIndexContributionRead,
    MarketIndexListRead,
    MarketIndexSummaryRead,
    MarketOhlcChartRead,
    MarketDailyPriceRead,
    MonthlyRevenueRead,
    ShareholdingDistributionWeeklyRead,
    StockChipCoverageRead,
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

DAILY_METRIC_RELEASE_TIMES = {
    "institutional_trade": time(18, 10),
    "margin_trading": time(21, 10),
}


def _split_categories(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_daily_metric_include_today(
    categories: list[str],
    include_today: bool | None,
) -> bool:
    if include_today is not None:
        return include_today

    now = datetime.now(TAIWAN_TZ)

    if not is_taiwan_trading_day(now.date()):
        return False

    release_time = max(
        (
            DAILY_METRIC_RELEASE_TIMES.get(category, time(21, 10))
            for category in categories
        ),
        default=time(21, 10),
    )
    return now.time() >= release_time


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


@router.post(
    "/selection-refresh/{stock_id}",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_selected_stock_data_api(
    stock_id: str,
    background_tasks: BackgroundTasks,
    include_today: bool | None = None,
    sleep_seconds: float = Query(default=0.05, ge=0, le=3),
    db: Session = Depends(get_db),
):
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_selection_refresh",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "include_today": include_today,
            "sleep_seconds": sleep_seconds,
        },
        progress_total=6,
        task=backfill_tasks.run_stock_selection_refresh_job,
        task_args=(stock_id, include_today, sleep_seconds),
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
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    resolved_include_today = _resolve_daily_metric_include_today(
        categories=category_list,
        include_today=include_today,
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
            "sleep_seconds": sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_market_daily_metrics_job,
        task_args=(
            start_date,
            end_date,
            category_list,
            lookback_days,
            resolved_include_today,
            sleep_seconds,
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
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
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
            "sleep_seconds": sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_daily_metrics_history_job,
        task_args=(
            stock_id,
            start_date,
            end_date,
            category_list,
            sleep_seconds,
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
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.fundamental_metrics_backfill",
        target=None,
        request={
            "categories": category_list,
            "force": force,
            "sleep_seconds": sleep_seconds,
        },
        task=backfill_tasks.run_market_fundamental_metrics_job,
        task_args=(category_list, force, sleep_seconds),
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
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    category_list = _split_categories(categories)
    return _queue_backfill_job(
        db=db,
        background_tasks=background_tasks,
        job_type="market.stock_fundamental_metrics_backfill",
        target=stock_id,
        request={
            "stock_id": stock_id,
            "categories": category_list,
            "force": force,
            "sleep_seconds": sleep_seconds,
        },
        task=backfill_tasks.run_stock_fundamental_metrics_job,
        task_args=(stock_id, category_list, force, sleep_seconds),
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
    sleep_seconds: float = Query(default=0.1, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
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
            "sleep_seconds": sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_shareholding_history_job,
        task_args=(
            stock_id,
            from_date,
            to_date,
            lookback_weeks,
            sleep_seconds,
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
    sleep_seconds: float = Query(default=0.05, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
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
            "sleep_seconds": sleep_seconds,
            "skip_existing": skip_existing,
        },
        task=backfill_tasks.run_stock_monthly_revenue_history_job,
        task_args=(
            stock_id,
            from_period,
            to_period,
            lookback_months,
            sleep_seconds,
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
    sleep_seconds: float = Query(default=0.05, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
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
            "sleep_seconds": sleep_seconds,
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
            sleep_seconds,
            skip_existing,
        ),
    )


@router.get("/ohlc/{stock_id}", response_model=MarketOhlcChartRead)
def get_stock_ohlc_chart_data(
    stock_id: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    ensure_history: bool = False,
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


@router.get("/indices/summary", response_model=MarketIndexSummaryRead)
def get_indices_summary(
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    return get_market_index_summary(db=db, force_refresh=force_refresh)


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
):
    try:
        return get_market_index_contributions(index_id=index_id, limit=limit)
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
):
    try:
        return get_market_index_ohlc_chart_data(
            index_id=index_id,
            timeframe=timeframe,
            bars=bars,
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
