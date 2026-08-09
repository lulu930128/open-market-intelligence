from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_etf import (
    TaiwanEtfNotApplicableError,
    TaiwanEtfNotFoundError,
    get_taiwan_etf_overview,
    refresh_taiwan_etf,
)
from app.market.tw_etf_schemas import (
    TaiwanEtfOverviewRead,
    TaiwanEtfRefreshRequest,
)


router = APIRouter()


def _translate_lookup_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaiwanEtfNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/etfs/{stock_id}/overview",
    response_model=TaiwanEtfOverviewRead,
)
def get_taiwan_etf_overview_api(
    stock_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_taiwan_etf_overview(db, stock_id)
    except (TaiwanEtfNotFoundError, TaiwanEtfNotApplicableError) as exc:
        raise _translate_lookup_error(exc) from exc


@router.post(
    "/etfs/{stock_id}/refresh",
    response_model=TaiwanEtfOverviewRead,
)
def refresh_taiwan_etf_api(
    stock_id: str,
    payload: TaiwanEtfRefreshRequest,
    db: Session = Depends(get_db),
):
    try:
        return refresh_taiwan_etf(
            db,
            stock_id,
            refresh_profile=payload.refresh_profile,
            refresh_nav=payload.refresh_nav,
            refresh_pcf=payload.refresh_pcf,
            refresh_inav=payload.refresh_inav,
            target_nav_date=payload.target_nav_date,
            target_pcf_date=payload.target_pcf_date,
        )
    except (TaiwanEtfNotFoundError, TaiwanEtfNotApplicableError) as exc:
        raise _translate_lookup_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
