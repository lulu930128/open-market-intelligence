from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.us_market.corporate_event_schemas import (
    USCorporateEventListRead,
    USCorporateEventRefreshRead,
    USCorporateEventSummaryRead,
)
from app.us_market.corporate_events import (
    USCorporateEventConfigurationError,
    get_us_stock_event_summary,
    list_us_corporate_events,
    refresh_us_corporate_events,
)
from app.us_market.errors import USMarketDataFetchError


router = APIRouter()


def _event_type_set(value: str | None) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").split(",")
        if item.strip()
    }


@router.get("/corporate-events", response_model=USCorporateEventListRead)
def list_us_corporate_events_api(
    symbol: str | None = None,
    event_types: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return list_us_corporate_events(
            db=db,
            symbol=symbol,
            event_types=_event_type_set(event_types),
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/corporate-events/{symbol}/summary",
    response_model=USCorporateEventSummaryRead,
)
def get_us_stock_event_summary_api(
    symbol: str,
    reminder_days: int | None = Query(default=None, ge=1, le=30),
    max_results: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    try:
        return get_us_stock_event_summary(
            db=db,
            symbol=symbol,
            reminder_days=reminder_days,
            max_results=max_results,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/corporate-events/refresh",
    response_model=USCorporateEventRefreshRead,
)
def refresh_us_corporate_events_api(db: Session = Depends(get_db)):
    try:
        return refresh_us_corporate_events(db=db)
    except USCorporateEventConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
