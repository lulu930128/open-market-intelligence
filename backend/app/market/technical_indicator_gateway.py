from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.market.technical_evidence import (
    INDICATOR_ALGORITHM_VERSION,
    calculate_canonical_indicator_points,
)
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    get_technical_analysis_parameters,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_technical_service import TaiwanTechnicalService


def active_engine_contract() -> dict[str, Any]:
    return {
        "active_engine": "canonical",
        "algorithm_version": INDICATOR_ALGORITHM_VERSION,
        "calculation_owner": "TaiwanTechnicalService",
        "legacy_fallback_allowed": False,
    }


def calculate_active_indicator_points(
    points: list[dict[str, Any]],
    *,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[dict[str, Any]]:
    resolved = parameters or get_technical_analysis_parameters()
    return calculate_canonical_indicator_points(points, parameters=resolved)


def calculate_active_daily_indicators(
    *,
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 100,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[Any]:
    resolved = parameters or get_technical_analysis_parameters()
    requested_at = datetime.now(TAIWAN_TZ)
    from_time = (
        datetime.combine(from_date, time.min, tzinfo=TAIWAN_TZ)
        if from_date is not None
        else None
    )
    to_time = (
        datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=TAIWAN_TZ)
        if to_date is not None
        else None
    )
    bars = TaiwanBarService(db).read_bars(
        instrument_id=stock_id,
        interval="1d",
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        include_partial=False,
        requested_at=requested_at,
    )
    technical = TaiwanTechnicalService().calculate(bars, parameters=resolved)
    return [
        {
            **point,
            "time": point["time"].astimezone(TAIWAN_TZ).date(),
        }
        for point in technical.points
    ]


def calculate_active_latest_daily_indicator(
    *,
    db: Session,
    stock_id: str,
    to_date: date | None = None,
    limit: int = 400,
    parameters: TechnicalAnalysisParameters | None = None,
) -> Any | None:
    points = calculate_active_daily_indicators(
        db=db,
        stock_id=stock_id,
        to_date=to_date,
        limit=limit,
        parameters=parameters,
    )
    return points[-1] if points else None


__all__ = [
    "active_engine_contract",
    "calculate_active_daily_indicators",
    "calculate_active_indicator_points",
    "calculate_active_latest_daily_indicator",
]
