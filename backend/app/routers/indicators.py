from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.technical_indicator_gateway import (
    active_engine_contract,
    calculate_active_daily_indicators,
    calculate_active_latest_daily_indicator,
)
from app.market.schemas import DailyIndicatorPointRead
from app.market.technical_parameters import get_technical_analysis_parameters

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
        parameters = get_technical_analysis_parameters(
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
        return calculate_active_daily_indicators(
            db=db,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            parameters=parameters,
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
        parameters = get_technical_analysis_parameters(
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
        result = calculate_active_latest_daily_indicator(
            db=db,
            stock_id=stock_id,
            parameters=parameters,
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


@router.get("/contract/active")
def get_active_indicator_engine_contract():
    """Expose the backend-owned algorithm/version switch without market data I/O."""

    return active_engine_contract()
