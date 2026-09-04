"""Unified cache-only Taiwan Bar transport."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_bar_contracts import (
    TaiwanBarSeriesRead,
    TaiwanBarSessionScope,
    TaiwanChartBarSeriesRead,
    project_taiwan_chart_bar_series,
)
from app.market.tw_bar_service import TaiwanBarService


router = APIRouter()


def _read_taiwan_bars(
    *,
    instrument_id: str,
    interval: str,
    from_time: datetime | None,
    to_time: datetime | None,
    limit: int,
    include_partial: bool,
    session_scope: TaiwanBarSessionScope,
    expected_snapshot_revision: str | None,
    db: Session,
) -> TaiwanBarSeriesRead:
    service = TaiwanBarService(db)
    if expected_snapshot_revision is not None:
        if session_scope is not TaiwanBarSessionScope.CURRENT_SESSION:
            raise ValueError(
                "expected_snapshot_revision requires current_session scope"
            )
        if from_time is not None or to_time is not None:
            raise ValueError(
                "current_session bar scope cannot be combined with from/to"
            )
        series = service.read_current_session_snapshot_by_revision(
            instrument_id=instrument_id,
            interval=interval,
            expected_snapshot_revision=expected_snapshot_revision,
            limit=limit,
            include_partial=include_partial,
        )
        current_revision = (
            series.current_session_coverage.snapshot_revision
            if series.current_session_coverage is not None
            else None
        )
        if current_revision != expected_snapshot_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BAR_SNAPSHOT_REVISION_CONFLICT",
                    "expected_snapshot_revision": expected_snapshot_revision,
                    "current_snapshot_revision": current_revision,
                },
            )
        return series
    return service.read_scoped_bars(
        instrument_id=instrument_id,
        interval=interval,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        include_partial=include_partial,
        session_scope=session_scope,
    )


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
    session_scope: TaiwanBarSessionScope = TaiwanBarSessionScope.HISTORY,
    expected_snapshot_revision: str | None = None,
    db: Session = Depends(get_db),
) -> TaiwanBarSeriesRead:
    try:
        return _read_taiwan_bars(
            instrument_id=instrument_id,
            interval=interval,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            include_partial=include_partial,
            session_scope=session_scope,
            expected_snapshot_revision=expected_snapshot_revision,
            db=db,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/bars/{instrument_id}/chart",
    response_model=TaiwanChartBarSeriesRead,
)
def get_taiwan_chart_bars(
    instrument_id: str,
    interval: str = Query(...),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=5000, ge=1, le=5000),
    include_partial: bool = Query(default=True),
    session_scope: TaiwanBarSessionScope = TaiwanBarSessionScope.HISTORY,
    expected_snapshot_revision: str | None = None,
    db: Session = Depends(get_db),
) -> TaiwanChartBarSeriesRead:
    """Return only the fields required to render a chart.

    The canonical resolver still runs once and caches the exact current-session
    snapshot for the subsequent revision-pinned Technical request.
    """

    try:
        series = _read_taiwan_bars(
            instrument_id=instrument_id,
            interval=interval,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            include_partial=include_partial,
            session_scope=session_scope,
            expected_snapshot_revision=expected_snapshot_revision,
            db=db,
        )
        presentation_events = (
            TaiwanBarService(db).read_current_session_presentation_events(
                series=series,
            )
            if session_scope is TaiwanBarSessionScope.CURRENT_SESSION
            else ()
        )
        return project_taiwan_chart_bar_series(
            series,
            presentation_events=presentation_events,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = ["get_taiwan_bars", "get_taiwan_chart_bars", "router"]
