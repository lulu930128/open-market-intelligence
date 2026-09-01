"""Unified cache-only Taiwan Bar transport."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.tw_bar_service import TaiwanBarService


router = APIRouter()


@router.get(
    "/bars/{instrument_id}",
    response_model=TaiwanBarSeriesRead,
)
def get_taiwan_bars(
    instrument_id: str,
    interval: str = Query(...),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=5000, ge=1, le=5000),
    include_partial: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> TaiwanBarSeriesRead:
    try:
        return TaiwanBarService(db).read_bars(
            instrument_id=instrument_id,
            interval=interval,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            include_partial=include_partial,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = ["get_taiwan_bars", "router"]
