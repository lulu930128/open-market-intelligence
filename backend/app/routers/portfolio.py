from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.portfolio import service
from app.portfolio.schemas import (
    PortfolioHoldingCreate,
    PortfolioHoldingRead,
    PortfolioHoldingSummaryRead,
    PortfolioHoldingUpdate,
)


router = APIRouter()


def _handle_portfolio_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.PortfolioHoldingNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.PortfolioSymbolNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, service.PortfolioDuplicateHoldingError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/holdings", response_model=list[PortfolioHoldingRead])
def list_holdings(
    market: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    is_active: bool | None = Query(default=True),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return service.list_holdings(
            db,
            market=market,
            symbol=symbol,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/holdings/summary", response_model=PortfolioHoldingSummaryRead)
def holdings_summary(
    market: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    try:
        normalized_market = service.normalize_market(market)
        holdings = service.list_holdings(db, market=normalized_market, is_active=True, limit=1000)
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc

    return {
        "market": normalized_market,
        "holding_count": len(holdings),
        "total_cost_amount": sum(float(item["cost_amount"]) for item in holdings),
        "currencies": sorted(
            {
                str(item["currency"])
                for item in holdings
                if item.get("currency")
            }
        ),
        "holdings": holdings,
    }


@router.post(
    "/holdings",
    response_model=PortfolioHoldingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_holding(
    payload: PortfolioHoldingCreate,
    db: Session = Depends(get_db),
):
    try:
        return service.create_holding(db, payload)
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/holdings/{holding_id}", response_model=PortfolioHoldingRead)
def get_holding(
    holding_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.holding_to_dict(service.get_holding(db, holding_id))
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.patch("/holdings/{holding_id}", response_model=PortfolioHoldingRead)
def update_holding(
    holding_id: int,
    payload: PortfolioHoldingUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_holding(db, holding_id, payload)
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
):
    try:
        service.delete_holding(db, holding_id)
    except service.PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc
