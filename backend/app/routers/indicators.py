from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.indicator_service import (
    calculate_daily_indicators,
    calculate_latest_daily_indicator,
)
from app.market.schemas import DailyIndicatorPointRead

router = APIRouter()


@router.get("/{stock_id}/daily", response_model=list[DailyIndicatorPointRead])
def get_stock_daily_indicators(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        return calculate_daily_indicators(
            db=db,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{stock_id}/latest", response_model=DailyIndicatorPointRead)
def get_latest_stock_daily_indicator(
    stock_id: str,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        result = calculate_latest_daily_indicator(
            db=db,
            stock_id=stock_id,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indicator data for stock_id='{stock_id}' not found.",
        )

    return result
