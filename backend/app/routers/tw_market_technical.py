"""Canonical Taiwan technical series and atomic chart bundle transport."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.tw_bar_contracts import TaiwanBarSessionScope
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_chart_service import (
    TaiwanChartBundleRead,
    TaiwanChartService,
    TaiwanChartSessionScope,
)
from app.market.tw_technical_service import (
    BarSeriesRevisionConflict,
    BarSnapshotRevisionConflict,
    TaiwanTechnicalSeriesRead,
    TaiwanTechnicalService,
    build_taiwan_technical_capability_contract,
)


router = APIRouter()


def _technical(
    bars,
    *,
    expected_series_revision: str | None,
    expected_snapshot_revision: str | None,
    response_limit: int | None,
    ma_windows: str | None,
    volume_ma_windows: str | None,
) -> TaiwanTechnicalSeriesRead:
    try:
        parameters = get_technical_analysis_parameters(
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
        return TaiwanTechnicalService().calculate(
            bars,
            parameters=parameters,
            expected_series_revision=expected_series_revision,
            expected_snapshot_revision=expected_snapshot_revision,
            response_limit=response_limit,
        )
    except BarSeriesRevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BAR_SERIES_REVISION_CONFLICT",
                "expected_series_revision": exc.expected,
                "current_series_revision": exc.current,
            },
        ) from exc
    except BarSnapshotRevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BAR_SNAPSHOT_REVISION_CONFLICT",
                "expected_snapshot_revision": exc.expected,
                "current_snapshot_revision": exc.current,
            },
        ) from exc


@router.get("/technical/contracts/tw")
def get_taiwan_technical_contract():
    """Pure Backend capability/default contract; performs no market-data I/O."""

    return build_taiwan_technical_capability_contract()


@router.get(
    "/technical/{instrument_id}/series",
    response_model=TaiwanTechnicalSeriesRead,
)
def get_taiwan_technical_series(
    instrument_id: str,
    interval: str = Query(default="1d"),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    include_partial: bool = True,
    expected_series_revision: str | None = None,
    expected_snapshot_revision: str | None = None,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    session_scope: TaiwanBarSessionScope = TaiwanBarSessionScope.HISTORY,
    db: Session = Depends(get_db),
):
    try:
        bar_service = TaiwanBarService(db)
        if (
            session_scope is TaiwanBarSessionScope.CURRENT_SESSION
            and expected_snapshot_revision is not None
        ):
            if from_time is not None or to_time is not None:
                raise ValueError(
                    "current_session bar scope cannot be combined with from/to"
                )
            bars = bar_service.read_current_session_snapshot_by_revision(
                instrument_id=instrument_id,
                interval=interval,
                expected_snapshot_revision=expected_snapshot_revision,
                include_partial=include_partial,
            )
        else:
            bars = bar_service.read_scoped_bars(
                instrument_id=instrument_id,
                interval=interval,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                include_partial=include_partial,
                session_scope=session_scope,
            )
        return _technical(
            bars,
            expected_series_revision=expected_series_revision,
            expected_snapshot_revision=expected_snapshot_revision,
            response_limit=limit,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/chart/{instrument_id}", response_model=TaiwanChartBundleRead)
def get_taiwan_chart_bundle(
    instrument_id: str,
    interval: str = Query(default="1d"),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    include_partial: bool = True,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    session_scope: TaiwanChartSessionScope = TaiwanChartSessionScope.HISTORY,
    db: Session = Depends(get_db),
):
    try:
        parameters = get_technical_analysis_parameters(
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
        return TaiwanChartService(db).read(
            instrument_id=instrument_id,
            interval=interval,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            include_partial=include_partial,
            parameters=parameters,
            session_scope=session_scope,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = ["TaiwanChartBundleRead", "router"]
