from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_market_dashboard import (
    DEFAULT_GROUP_LIMIT,
    DEFAULT_WATCHLIST_LIMIT,
    TaiwanDashboardStockNotFoundError,
    TaiwanDashboardWatchlistGroupNotFoundError,
    build_tw_dashboard_stock_detail,
    build_tw_market_dashboard,
    build_tw_stock_chart,
    build_tw_stock_research,
    search_tw_dashboard_symbols,
)
from app.market.tw_market_dashboard_schemas import (
    TaiwanDashboardSymbolSearchRead,
    TaiwanDashboardStockDetailRead,
    TaiwanMarketDashboardRead,
    TaiwanStockChartRead,
    TaiwanStockResearchResponseRead,
    TaiwanWorkspaceHeaderRead,
    TaiwanWorkspaceWatchlistRead,
    TaiwanWorkspaceHotGroupsRead,
)
from app.market.tw_workspace import (
    build_tw_workspace_header, build_tw_workspace_watchlist, build_tw_workspace_hot_groups,
)
from app.market.tw_workspace_research import TaiwanResearchProjectionTooLarge


router = APIRouter()


@router.get("/header", response_model=TaiwanWorkspaceHeaderRead)
def read_tw_workspace_header(db: Session = Depends(get_db)):
    return build_tw_workspace_header(db)


@router.get("/watchlist", response_model=TaiwanWorkspaceWatchlistRead)
def read_tw_workspace_watchlist(
    watchlist_group_id: int | None = Query(default=None, ge=1),
    include_watchlist_children: bool = Query(default=True),
    watchlist_limit: int = Query(default=DEFAULT_WATCHLIST_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_workspace_watchlist(
            db, watchlist_group_id=watchlist_group_id,
            include_watchlist_children=include_watchlist_children, watchlist_limit=watchlist_limit,
        )
    except TaiwanDashboardWatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/hot-groups", response_model=TaiwanWorkspaceHotGroupsRead)
def read_tw_workspace_hot_groups(
    group_limit: int = Query(default=DEFAULT_GROUP_LIMIT, ge=1, le=30),
    db: Session = Depends(get_db),
):
    return build_tw_workspace_hot_groups(db, group_limit=group_limit)


@router.get("/stocks/{stock_id}/chart", response_model=TaiwanStockChartRead)
def read_tw_stock_chart(
    stock_id: str, timeframe: str = Query(default="daily", pattern="^(today|daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=20, le=500), db: Session = Depends(get_db),
):
    try:
        return build_tw_stock_chart(db, stock_id=stock_id, timeframe=timeframe, bars=bars)
    except TaiwanDashboardStockNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stocks/{stock_id}/research", response_model=TaiwanStockResearchResponseRead)
def read_tw_stock_research(
    stock_id: str, timeframe: str = Query(default="daily", pattern="^(today|daily|weekly|monthly)$"),
    projection: str = Query(default="full", pattern="^(full|workspace)$"),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_stock_research(db, stock_id=stock_id, timeframe=timeframe, projection=projection)
    except TaiwanResearchProjectionTooLarge as exc:
        raise HTTPException(status_code=413, detail={"code": "TW_WORKSPACE_RESEARCH_BUDGET_EXCEEDED", "message": str(exc)}) from exc
    except TaiwanDashboardStockNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/snapshot", response_model=TaiwanMarketDashboardRead)
def read_tw_market_dashboard(
    watchlist_group_id: int | None = Query(default=None, ge=1),
    include_watchlist_children: bool = Query(default=True),
    watchlist_limit: int = Query(
        default=DEFAULT_WATCHLIST_LIMIT,
        ge=1,
        le=100,
    ),
    group_limit: int = Query(default=DEFAULT_GROUP_LIMIT, ge=1, le=30),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_market_dashboard(
            db,
            watchlist_group_id=watchlist_group_id,
            include_watchlist_children=include_watchlist_children,
            watchlist_limit=watchlist_limit,
            group_limit=group_limit,
        )
    except TaiwanDashboardWatchlistGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/symbols/search", response_model=TaiwanDashboardSymbolSearchRead)
def search_tw_market_dashboard_symbols(
    keyword: str = Query(min_length=1, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        return search_tw_dashboard_symbols(db, keyword=keyword, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/stocks/{stock_id}",
    response_model=TaiwanDashboardStockDetailRead,
)
def read_tw_market_dashboard_stock_detail(
    stock_id: str,
    timeframe: str = Query(
        default="daily",
        pattern="^(today|daily|weekly|monthly)$",
    ),
    bars: int = Query(default=90, ge=20, le=500),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_dashboard_stock_detail(
            db,
            stock_id=stock_id,
            timeframe=timeframe,
            bars=bars,
        )
    except TaiwanDashboardStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
