from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.schemas import (
    TaiwanFuturesDailyBarRead,
    TaiwanFuturesIntradayBarRead,
    TaiwanFuturesProductRead,
    TaiwanFuturesQuoteRead,
)
from app.market.tw_futures import (
    TaiwanFuturesFetchError,
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    list_taiwan_futures_products,
    refresh_taiwan_futures_daily_bars,
    refresh_taiwan_futures_intraday_bars,
    refresh_taiwan_futures_quotes,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
from app.market.tw_futures_jobs import record_taiwan_futures_quote_refresh_issue


router = APIRouter()


@router.get(
    "/tw-futures/products",
    response_model=list[TaiwanFuturesProductRead],
)
def list_taiwan_futures_products_api():
    return list_taiwan_futures_products()


@router.post(
    "/tw-futures/refresh",
    response_model=list[TaiwanFuturesQuoteRead],
)
def refresh_taiwan_futures_quotes_api(
    symbols: str = Query(default="TXF,MXF,TMF"),
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    source_error: str | None = None
    try:
        rows = refresh_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            session=session,
            active_only=active_only,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        source_error = str(exc)
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=False,
            session=session,
            provider=provider,
        )
        record_taiwan_futures_quote_refresh_issue(
            db=db,
            symbols=symbols,
            session=session,
            provider=provider,
            exc=exc,
            cached_count=len(rows),
        )

    return [
        taiwan_futures_quote_to_dict(
            row,
            expected_session=session,
            source_error=source_error,
        )
        for row in rows
    ]


@router.get(
    "/tw-futures/latest",
    response_model=list[TaiwanFuturesQuoteRead],
)
def get_latest_taiwan_futures_quotes_api(
    symbols: str = Query(default="TXF,MXF,TMF"),
    refresh: bool = False,
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    db: Session = Depends(get_db),
):
    source_error: str | None = None
    try:
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=refresh,
            session=session,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        source_error = str(exc)
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=False,
            session=session,
            provider=provider,
        )
        record_taiwan_futures_quote_refresh_issue(
            db=db,
            symbols=symbols,
            session=session,
            provider=provider,
            exc=exc,
            cached_count=len(rows),
        )

    return [
        taiwan_futures_quote_to_dict(
            row,
            expected_session=session,
            source_error=source_error,
        )
        for row in rows
    ]


@router.get(
    "/tw-futures/{symbol}/daily",
    response_model=list[TaiwanFuturesDailyBarRead],
)
def list_taiwan_futures_daily_bars_api(
    symbol: str,
    limit: int = Query(default=120, ge=1, le=1000),
    refresh: bool = False,
    lookback_days: int = Query(default=45, ge=1, le=730),
    start_date: date | None = None,
    end_date: date | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    try:
        if refresh:
            try:
                refresh_taiwan_futures_daily_bars(
                    db=db,
                    symbols=[symbol],
                    start_date=start_date,
                    end_date=end_date,
                    lookback_days=lookback_days,
                    force=False,
                )
            except TaiwanFuturesFetchError:
                existing_rows = list_taiwan_futures_daily_bars(
                    db=db,
                    symbol=symbol,
                    limit=limit,
                    active_only=active_only,
                )
                if not existing_rows:
                    raise

        rows = list_taiwan_futures_daily_bars(
            db=db,
            symbol=symbol,
            limit=limit,
            active_only=active_only,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TaiwanFuturesFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return [taiwan_futures_daily_bar_to_dict(row) for row in rows]


@router.get(
    "/tw-futures/{symbol}/intraday",
    response_model=list[TaiwanFuturesIntradayBarRead],
)
def list_taiwan_futures_intraday_bars_api(
    symbol: str,
    interval: str = Query(default="1m", pattern="^1m$"),
    limit: int = Query(default=390, ge=1, le=3000),
    refresh: bool = True,
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(default=None, pattern="^(auto|taifex_mis|kgi)$"),
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    refresh_error: TaiwanFuturesFetchError | None = None
    try:
        if refresh:
            try:
                refresh_taiwan_futures_intraday_bars(
                    db=db,
                    symbol=symbol,
                    session=session,
                    provider=provider,
                )
            except TaiwanFuturesFetchError as exc:
                refresh_error = exc

        rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=symbol,
            interval=interval,
            limit=limit,
            trade_date=trade_date,
            session=session,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if refresh_error is not None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(refresh_error),
        ) from refresh_error

    return [taiwan_futures_intraday_bar_to_dict(row) for row in rows]


__all__ = [
    "get_latest_taiwan_futures_quotes_api",
    "list_taiwan_futures_daily_bars_api",
    "list_taiwan_futures_intraday_bars_api",
    "list_taiwan_futures_products_api",
    "refresh_taiwan_futures_quotes_api",
    "router",
]
