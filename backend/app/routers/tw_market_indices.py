from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_list,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.schemas import (
    IntradayTrendRead,
    MarketIndexContributionRead,
    MarketIndexListRead,
    MarketIndexSummaryRead,
    MarketOhlcChartRead,
)


router = APIRouter()


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
    "router",
]
