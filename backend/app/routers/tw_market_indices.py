from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_list,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
    refresh_market_index_daily_stats,
    refresh_market_index_summary,
)
from app.market.schemas import (
    IntradayTrendRead,
    MarketIndexContributionRead,
    MarketIndexDailyStatRefreshRead,
    MarketIndexListRead,
    MarketIndexSummaryRead,
    MarketOhlcChartRead,
    TaiwanMarketVolumeStateRead,
)
from app.market.taiwan_market_state import (
    persist_taiwan_market_minute_state,
    read_taiwan_market_volume_state,
)


router = APIRouter()


@router.get("/indices/summary", response_model=MarketIndexSummaryRead)
def get_indices_summary(
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    return get_market_index_summary(db=db, force_refresh=force_refresh)


@router.get("/market-state/volume", response_model=TaiwanMarketVolumeStateRead)
def get_taiwan_market_volume_state(
    lookback_days: int = Query(default=20, ge=5, le=60),
    db: Session = Depends(get_db),
):
    return read_taiwan_market_volume_state(db, lookback_days=lookback_days)


@router.post(
    "/indices/summary/refresh-job",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_indices_summary_refresh(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    del background_tasks
    request = {"scope": "tw_market_indices"}
    job, _created = job_service.enqueue_job(
        db=db,
        job_type="market.index_summary_refresh",
        target="all",
        request=request,
        progress_total=1,
        message="Queued.",
        task=backfill_tasks.run_market_index_summary_refresh_job,
        reuse_success_within_seconds=45,
    )
    return job_service.serialize_job(job)


@router.post("/indices/summary/refresh", response_model=MarketIndexSummaryRead)
def refresh_indices_summary(
    refresh_daily_stats: bool = False,
    db: Session = Depends(get_db),
):
    try:
        payload = refresh_market_index_summary(
            db=db,
            refresh_daily_stats=refresh_daily_stats,
        )
        persist_taiwan_market_minute_state(db, payload=payload)
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index summary refresh failed: {exc}",
        ) from exc


@router.post(
    "/indices/{index_id}/daily-stats/refresh",
    response_model=MarketIndexDailyStatRefreshRead,
)
def refresh_index_daily_stats(
    index_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    normalized_to_date = to_date or date.today()
    normalized_from_date = from_date or normalized_to_date - timedelta(days=90)
    try:
        return refresh_market_index_daily_stats(
            db=db,
            index_id=index_id,
            from_date=normalized_from_date,
            to_date=normalized_to_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Index daily stat refresh failed: {exc}",
        ) from exc


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
def get_index_intraday_trend(
    index_id: str,
    acquisition_policy: str = Query(
        default="prefer_live",
        pattern="^(cache_only|prefer_live|require_live)$",
    ),
):
    try:
        return get_market_index_intraday(
            index_id=index_id,
            acquisition_policy=acquisition_policy,
        )
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


__all__ = [
    "get_index_contributions",
    "get_index_intraday_trend",
    "get_index_ohlc_chart_data",
    "get_indices_list",
    "get_indices_summary",
    "get_taiwan_market_volume_state",
    "queue_indices_summary_refresh",
    "refresh_indices_summary",
    "refresh_index_daily_stats",
    "router",
]
