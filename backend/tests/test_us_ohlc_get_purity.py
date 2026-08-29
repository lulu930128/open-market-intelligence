from __future__ import annotations

import inspect
from datetime import date
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.us_market import (
    get_us_ohlc_chart_data,
    list_us_daily_history,
    refresh_us_daily_prices,
)


def test_public_get_does_not_expose_acquisition_or_provider_controls() -> None:
    parameters = inspect.signature(get_us_ohlc_chart_data).parameters
    assert "ensure_history" not in parameters
    assert "provider" not in parameters
    assert "outputsize" not in parameters
    assert "adjusted" not in parameters
    assert "include_intraday" not in parameters


def test_public_get_forces_cache_only_service_read() -> None:
    expected = {"symbol": "TSM", "points": []}
    database = object()
    with patch(
        "app.routers.us_market.read_us_daily_ohlcv_chart",
        return_value=expected,
    ) as read:
        actual = get_us_ohlc_chart_data(
            symbol="TSM",
            timeframe="daily",
            bars=90,
            to_date=date(2026, 8, 21),
            db=database,
        )

    assert actual is expected
    read.assert_called_once_with(
        db=database,
        symbol="TSM",
        timeframe="daily",
        bars=90,
        to_date=date(2026, 8, 21),
    )


def test_public_refresh_marks_provider_compatibility_argument_deprecated() -> None:
    provider = inspect.signature(refresh_us_daily_prices).parameters["provider"].default

    assert provider.deprecated is True
    assert "non-auto values are rejected" in provider.description


def test_public_refresh_rejects_provider_override_before_refresh() -> None:
    with patch("app.routers.us_market.refresh_us_daily_ohlcv") as refresh:
        with pytest.raises(HTTPException) as captured:
            refresh_us_daily_prices(
                symbol="AAPL",
                outputsize="compact",
                adjusted=False,
                provider="yahoo_chart",
                db=object(),
            )

    assert captured.value.status_code == 400
    assert "requires provider=auto" in captured.value.detail
    refresh.assert_not_called()


@pytest.mark.parametrize(
    ("call", "patch_target"),
    [
        (
            lambda: get_us_ohlc_chart_data(
                symbol="UNKNOWN",
                timeframe="daily",
                bars=2,
                to_date=None,
                db=object(),
            ),
            "app.routers.us_market.read_us_daily_ohlcv_chart",
        ),
        (
            lambda: list_us_daily_history(
                symbol="UNKNOWN",
                provider=None,
                from_date=None,
                to_date=None,
                limit=2,
                offset=0,
                db=object(),
            ),
            "app.routers.us_market.read_us_daily_ohlcv_history",
        ),
        (
            lambda: refresh_us_daily_prices(
                symbol="UNKNOWN",
                outputsize="compact",
                adjusted=False,
                provider="auto",
                db=object(),
            ),
            "app.routers.us_market.refresh_us_daily_ohlcv",
        ),
    ],
)
def test_public_daily_routes_return_404_for_unknown_identity(
    call,
    patch_target: str,
) -> None:
    with patch(
        patch_target,
        side_effect=LookupError("US instrument identity is unavailable: UNKNOWN"),
    ):
        with pytest.raises(HTTPException) as captured:
            call()

    assert captured.value.status_code == 404
    assert captured.value.detail == "US instrument identity is unavailable: UNKNOWN"
