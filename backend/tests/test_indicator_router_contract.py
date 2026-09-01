from __future__ import annotations

from datetime import date
from unittest.mock import Mock, patch

from app.market.schemas import DailyIndicatorPointRead
from app.routers.indicators import (
    get_active_indicator_engine_contract,
    get_stock_daily_indicators,
)


def test_daily_indicator_route_uses_active_backend_gateway() -> None:
    db = Mock()
    parameters = Mock()
    expected = [{"time": date(2026, 8, 25), "ma": {}, "volume_ma": {}}]

    with (
        patch(
            "app.routers.indicators.get_technical_analysis_parameters",
            return_value=parameters,
        ) as resolve_parameters,
        patch(
            "app.routers.indicators.calculate_active_daily_indicators",
            return_value=expected,
        ) as calculate,
    ):
        result = get_stock_daily_indicators(
            stock_id="2330",
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 25),
            limit=250,
            ma_windows="5,20,60",
            volume_ma_windows="5,20",
            db=db,
        )

    assert result == expected
    resolve_parameters.assert_called_once_with(
        ma_windows="5,20,60",
        volume_ma_windows="5,20",
    )
    calculate.assert_called_once_with(
        db=db,
        stock_id="2330",
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 25),
        limit=250,
        parameters=parameters,
    )


def test_indicator_point_keeps_backend_authority_metadata() -> None:
    point = DailyIndicatorPointRead.model_validate(
        {
            "time": "2026-08-25",
            "algorithm_version": "tw.technical.indicators.v4",
            "price_basis": "raw_unadjusted",
            "calculation_role": "backend_authoritative",
            "parameter_contract": {"rsi_period": 14},
            "ma": {},
            "volume_ma": {},
        }
    )

    assert point.algorithm_version == "tw.technical.indicators.v4"
    assert point.calculation_role == "backend_authoritative"
    assert point.parameter_contract == {"rsi_period": 14}


def test_active_indicator_contract_exposes_canonical_version() -> None:
    with patch(
        "app.routers.indicators.active_engine_contract",
        return_value={
            "active_engine": "canonical",
            "algorithm_version": "tw.technical.indicators.v4",
        },
    ):
        result = get_active_indicator_engine_contract()

    assert result["active_engine"] == "canonical"
    assert result["algorithm_version"] == "tw.technical.indicators.v4"
