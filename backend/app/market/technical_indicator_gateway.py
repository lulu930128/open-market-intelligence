from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.market import indicator_service
from app.market.technical_evidence import (
    INDICATOR_ALGORITHM_VERSION,
    calculate_canonical_indicator_points,
)
from app.market.service import list_stock_daily_history
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    get_technical_analysis_parameters,
)


LEGACY_ALGORITHM_VERSION = "tw.technical.indicators.v1-legacy"


def canonical_active() -> bool:
    return bool(settings.technical_canonical_v2_active)


def active_engine_contract() -> dict[str, Any]:
    active = canonical_active()
    return {
        "active_engine": "canonical" if active else "legacy",
        "algorithm_version": (
            INDICATOR_ALGORITHM_VERSION if active else LEGACY_ALGORITHM_VERSION
        ),
        "rollback_flag": "TECHNICAL_CANONICAL_V2_ACTIVE",
        "rollback_value": False,
    }


def calculate_active_indicator_points(
    points: list[dict[str, Any]],
    *,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[dict[str, Any]]:
    resolved = parameters or get_technical_analysis_parameters()
    if canonical_active():
        return calculate_canonical_indicator_points(points, parameters=resolved)
    return indicator_service.calculate_indicator_points_from_ohlc_points(
        points,
        parameters=resolved,
    )


def calculate_active_daily_indicators(
    *,
    db: Session,
    stock_id: str,
    limit: int = 100,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[Any]:
    resolved = parameters or get_technical_analysis_parameters()
    if not canonical_active():
        return indicator_service.calculate_daily_indicators(
            db=db,
            stock_id=stock_id,
            limit=limit,
            ma_windows=resolved.ma_windows_text,
            volume_ma_windows=resolved.volume_ma_windows_text,
            parameters=resolved,
        )
    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        limit=limit,
        ascending=True,
    )
    points = [
        {
            "time": row.trade_date,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "volume": row.trade_volume,
            "price_change": row.price_change,
        }
        for row in rows
    ]
    return calculate_canonical_indicator_points(points, parameters=resolved)


def calculate_active_latest_daily_indicator(
    *,
    db: Session,
    stock_id: str,
    limit: int = 400,
    parameters: TechnicalAnalysisParameters | None = None,
) -> Any | None:
    points = calculate_active_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=limit,
        parameters=parameters,
    )
    return points[-1] if points else None


__all__ = [
    "LEGACY_ALGORITHM_VERSION",
    "active_engine_contract",
    "calculate_active_daily_indicators",
    "calculate_active_indicator_points",
    "calculate_active_latest_daily_indicator",
    "canonical_active",
]
