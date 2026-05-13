from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.stocks.schemas import (
    StockMarketCapRead,
    StockMasterRead,
    StockMasterUpdate,
    StockProfileRead,
    StockSyncResultRead,
)
from app.stocks.service import (
    StockNotFoundError,
    StockProfileNotFoundError,
    get_latest_stock_market_cap,
    get_stock,
    get_stock_profile,
    list_stock_profiles,
    list_stocks,
    search_stocks,
    sync_stocks_from_market_daily,
    update_stock,
)

router = APIRouter()


@router.post("/sync-from-market", response_model=StockSyncResultRead)
def sync_stocks_from_market(db: Session = Depends(get_db)):
    return sync_stocks_from_market_daily(db)


@router.get("/search", response_model=list[StockMasterRead])
def search_stock_master(
    keyword: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return search_stocks(
        db=db,
        keyword=keyword,
        limit=limit,
    )


@router.get("/profiles", response_model=list[StockProfileRead])
def list_stock_profile_master(
    market: str | None = None,
    industry: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_stock_profiles(
        db=db,
        market=market,
        industry=industry,
        limit=limit,
        offset=offset,
    )


@router.get("/", response_model=list[StockMasterRead])
def list_stock_master(
    market: str | None = None,
    instrument_type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_stocks(
        db=db,
        market=market,
        instrument_type=instrument_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.get("/{stock_id}/profile", response_model=StockProfileRead)
def get_stock_profile_api(stock_id: str, db: Session = Depends(get_db)):
    try:
        return get_stock_profile(db=db, stock_id=stock_id)
    except StockProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{stock_id}/market-cap/latest", response_model=StockMarketCapRead)
def get_latest_stock_market_cap_api(stock_id: str, db: Session = Depends(get_db)):
    try:
        return get_latest_stock_market_cap(db=db, stock_id=stock_id)
    except StockProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{stock_id}", response_model=StockMasterRead)
def get_stock_master(stock_id: str, db: Session = Depends(get_db)):
    try:
        return get_stock(db=db, stock_id=stock_id)
    except StockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch("/{stock_id}", response_model=StockMasterRead)
def update_stock_master(
    stock_id: str,
    payload: StockMasterUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_stock(
            db=db,
            stock_id=stock_id,
            payload=payload,
        )
    except StockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
