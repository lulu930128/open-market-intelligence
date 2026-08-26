from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.schemas import (
    TaiwanDerivativesLargeTraderDailyRead,
    TaiwanDerivativesRefreshRead,
    TaiwanFuturesDailyBarRead,
    TaiwanFuturesDailyRefreshRead,
    TaiwanFuturesIntradayBarRead,
    TaiwanFuturesProductRead,
    TaiwanFuturesQuoteRead,
    TaiwanFuturesTermStructureDailyRead,
    TaiwanOptionChainDailyRead,
)
from app.market.tw_derivatives import (
    MAX_LARGE_TRADER_READ_LIMIT,
    MAX_OPTION_READ_LIMIT,
    MAX_TERM_STRUCTURE_READ_LIMIT,
    TaiwanDerivativesFetchError,
    large_trader_row_to_dict,
    list_taiwan_large_traders,
    list_taiwan_option_chain,
    list_taiwan_term_structure,
    refresh_taiwan_derivatives,
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
    resolve_taiwan_futures_daily_refresh_window,
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
    provider: str | None = Query(
        default=None,
        pattern="^(auto|taifex_mis|kgi)$",
        deprecated=True,
    ),
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    # Provider selection is a market-platform concern. Keep the deprecated
    # query parameter for compatibility, but never let it steer production.
    del provider
    source_error: str | None = None
    try:
        rows = refresh_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            session=session,
            active_only=active_only,
            provider=None,
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
            provider=None,
        )
        record_taiwan_futures_quote_refresh_issue(
            db=db,
            symbols=symbols,
            session=session,
            provider=None,
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
    refresh: bool = Query(default=False, deprecated=True),
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(
        default=None,
        pattern="^(auto|taifex_mis|kgi)$",
        deprecated=True,
    ),
    db: Session = Depends(get_db),
):
    if refresh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "GET /tw-futures/latest is cache-only. "
                "Use POST /tw-futures/refresh for an explicit refresh."
            ),
        )
    del provider
    try:
        rows = get_latest_taiwan_futures_quotes(
            db=db,
            symbols=symbols,
            refresh=False,
            session=session,
            provider=None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return [
        taiwan_futures_quote_to_dict(
            row,
            expected_session=session,
            source_error=None,
        )
        for row in rows
    ]


@router.post(
    "/tw-futures/derivatives/refresh",
    response_model=TaiwanDerivativesRefreshRead,
)
def refresh_taiwan_derivatives_api(
    db: Session = Depends(get_db),
):
    try:
        return refresh_taiwan_derivatives(db)
    except TaiwanDerivativesFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get(
    "/tw-futures/options-chain",
    response_model=list[TaiwanOptionChainDailyRead],
)
def list_taiwan_option_chain_api(
    trade_date: date | None = None,
    product_code: str = Query(default="TXO", pattern="^TXO$"),
    contract_month: str | None = Query(default=None, pattern="^[0-9A-Z]+$"),
    session: str = Query(default="regular", pattern="^(regular|after_hours|all)$"),
    option_type: str | None = Query(default=None, pattern="^(call|put)$"),
    center_strike: float | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=MAX_OPTION_READ_LIMIT),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
):
    try:
        return list_taiwan_option_chain(
            db,
            trade_date=trade_date,
            product_code=product_code,
            contract_month=contract_month,
            session=session,
            option_type=option_type,
            center_strike=center_strike,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/tw-futures/large-traders",
    response_model=list[TaiwanDerivativesLargeTraderDailyRead],
)
def list_taiwan_large_traders_api(
    trade_date: date | None = None,
    instrument_type: str | None = Query(default=None, pattern="^(futures|options)$"),
    settlement_bucket: str | None = Query(default=None, pattern="^(weekly|all_contracts|[0-9]{6})$"),
    trader_type: str | None = Query(default=None, pattern="^(all_traders|specific_institution)$"),
    limit: int = Query(default=100, ge=1, le=MAX_LARGE_TRADER_READ_LIMIT),
    db: Session = Depends(get_db),
):
    try:
        rows = list_taiwan_large_traders(
            db,
            trade_date=trade_date,
            instrument_type=instrument_type,
            settlement_bucket=settlement_bucket,
            trader_type=trader_type,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return [large_trader_row_to_dict(row) for row in rows]


@router.get(
    "/tw-futures/term-structure",
    response_model=list[TaiwanFuturesTermStructureDailyRead],
)
def list_taiwan_term_structure_api(
    trade_date: date | None = None,
    symbol: str = Query(default="TXF", pattern="^TXF$"),
    limit: int = Query(default=MAX_TERM_STRUCTURE_READ_LIMIT, ge=1, le=MAX_TERM_STRUCTURE_READ_LIMIT),
    db: Session = Depends(get_db),
):
    try:
        return list_taiwan_term_structure(
            db,
            trade_date=trade_date,
            symbol=symbol,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/tw-futures/{symbol}/daily",
    response_model=list[TaiwanFuturesDailyBarRead],
)
def list_taiwan_futures_daily_bars_api(
    symbol: str,
    limit: int = Query(default=120, ge=1, le=1000),
    refresh: bool = Query(default=False, deprecated=True),
    lookback_days: int = Query(default=45, ge=1, le=730, deprecated=True),
    start_date: date | None = Query(default=None, deprecated=True),
    end_date: date | None = Query(default=None, deprecated=True),
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    try:
        if refresh:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "GET /tw-futures/{symbol}/daily is read-only. "
                    "Use POST /tw-futures/{symbol}/daily/refresh for bounded refresh."
                ),
            )

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


@router.post(
    "/tw-futures/{symbol}/daily/refresh",
    response_model=TaiwanFuturesDailyRefreshRead,
)
def refresh_taiwan_futures_daily_bars_api(
    symbol: str,
    limit: int = Query(default=180, ge=1, le=1000),
    lookback_days: int = Query(default=45, ge=1, le=730),
    start_date: date | None = None,
    end_date: date | None = None,
    active_only: bool = True,
    force: bool = False,
    db: Session = Depends(get_db),
):
    try:
        refresh_window = resolve_taiwan_futures_daily_refresh_window(
            start_date=start_date,
            end_date=end_date,
            lookback_days=lookback_days,
        )
        refreshed_rows = refresh_taiwan_futures_daily_bars(
            db=db,
            symbols=[symbol],
            start_date=refresh_window["effective_start_date"],
            end_date=refresh_window["effective_end_date"],
            lookback_days=lookback_days,
            force=force,
        )
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

    skipped_unreleased = bool(refresh_window["skipped_unreleased_end_date"])
    warning = None
    if skipped_unreleased:
        warning = (
            "Requested end date is not officially released; refresh stopped at "
            f"{refresh_window['effective_end_date'].isoformat()}."
        )

    return {
        "status": "partial" if skipped_unreleased else "success",
        "symbol": symbol.strip().upper(),
        "requested_end_date": refresh_window["requested_end_date"],
        "effective_end_date": refresh_window["effective_end_date"],
        "latest_released_trade_date": refresh_window["latest_released_trade_date"],
        "release_time": refresh_window["release_time"],
        "skipped_unreleased_end_date": skipped_unreleased,
        "refreshed_row_count": len(refreshed_rows),
        "warning": warning,
        "rows": [taiwan_futures_daily_bar_to_dict(row) for row in rows],
    }


@router.get(
    "/tw-futures/{symbol}/intraday",
    response_model=list[TaiwanFuturesIntradayBarRead],
)
def list_taiwan_futures_intraday_bars_api(
    symbol: str,
    interval: str = Query(default="1m", pattern="^1m$"),
    limit: int = Query(default=390, ge=1, le=3000),
    refresh: bool = Query(default=False, deprecated=True),
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    provider: str | None = Query(
        default=None,
        pattern="^(auto|taifex_mis|kgi)$",
        deprecated=True,
    ),
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    if refresh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "GET /tw-futures/{symbol}/intraday is cache-only. "
                "Use POST /tw-futures/{symbol}/intraday/refresh for an explicit refresh."
            ),
        )
    del provider
    try:
        rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=symbol,
            interval=interval,
            limit=limit,
            trade_date=trade_date,
            session=session,
            provider=None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return [taiwan_futures_intraday_bar_to_dict(row) for row in rows]


@router.post(
    "/tw-futures/{symbol}/intraday/refresh",
    response_model=list[TaiwanFuturesIntradayBarRead],
)
def refresh_taiwan_futures_intraday_bars_api(
    symbol: str,
    interval: str = Query(default="1m", pattern="^1m$"),
    limit: int = Query(default=390, ge=1, le=3000),
    session: str = Query(default="auto", pattern="^(auto|regular|after_hours)$"),
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        refresh_taiwan_futures_intraday_bars(
            db=db,
            symbol=symbol,
            session=session,
            provider=None,
        )
        rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=symbol,
            interval=interval,
            limit=limit,
            trade_date=trade_date,
            session=session,
            provider=None,
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

    return [taiwan_futures_intraday_bar_to_dict(row) for row in rows]


__all__ = [
    "get_latest_taiwan_futures_quotes_api",
    "list_taiwan_large_traders_api",
    "list_taiwan_option_chain_api",
    "list_taiwan_term_structure_api",
    "list_taiwan_futures_daily_bars_api",
    "list_taiwan_futures_intraday_bars_api",
    "list_taiwan_futures_products_api",
    "refresh_taiwan_futures_intraday_bars_api",
    "refresh_taiwan_derivatives_api",
    "refresh_taiwan_futures_quotes_api",
    "router",
]
