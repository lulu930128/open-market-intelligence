from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.market import indicator_service
from app.market.daily_ohlcv_platform import read_taiwan_official_daily
from app.market.daily_ohlcv_platform import TAIWAN_TZ
from app.market.technical_evidence import (
    INDICATOR_ALGORITHM_VERSION,
    calculate_canonical_indicator_points,
)
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
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 100,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[Any]:
    resolved = parameters or get_technical_analysis_parameters()
    if not canonical_active():
        return indicator_service.calculate_daily_indicators(
            db=db,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            ma_windows=resolved.ma_windows_text,
            volume_ma_windows=resolved.volume_ma_windows_text,
            parameters=resolved,
        )
    resolved_daily = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    points = [
        {
            "time": bar.end_at.astimezone(TAIWAN_TZ).date(),
            "open": float(bar.open_price),
            "high": float(bar.high_price),
            "low": float(bar.low_price),
            "close": float(bar.close_price),
            "volume": int(bar.volume.value) if bar.volume is not None else None,
            "price_change": None,
        }
        for bar in resolved_daily.resolved.bars
    ]
    return calculate_canonical_indicator_points(points, parameters=resolved)


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
    "LEGACY_ALGORITHM_VERSION",
    "active_engine_contract",
    "calculate_active_daily_indicators",
    "calculate_active_indicator_points",
    "calculate_active_latest_daily_indicator",
    "canonical_active",
]
