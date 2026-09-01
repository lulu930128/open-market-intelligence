from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import us_market as us_market_router


@pytest.mark.parametrize(
    "handler",
    (
        us_market_router.get_us_market_truth_api,
        us_market_router.get_us_market_truth_intraday_api,
    ),
)
def test_truth_api_maps_unknown_symbol_to_not_found(monkeypatch, handler) -> None:
    target = (
        "read_us_market_truth_snapshot"
        if handler is us_market_router.get_us_market_truth_api
        else "read_us_intraday_series_projection"
    )

    def missing(*args, **kwargs):
        raise LookupError("unknown US symbol")

    monkeypatch.setattr(us_market_router, target, missing)

    with pytest.raises(HTTPException) as captured:
        if handler is us_market_router.get_us_market_truth_api:
            handler(symbol="UNKNOWN", db=object())
        else:
            handler(symbol="UNKNOWN", session_scope="regular", db=object())

    assert captured.value.status_code == 404


def test_truth_api_does_not_reclassify_internal_contract_failure(monkeypatch) -> None:
    def invalid_contract(*args, **kwargs):
        raise ValueError("US Market Truth component identity mismatch")

    monkeypatch.setattr(
        us_market_router,
        "read_us_market_truth_snapshot",
        invalid_contract,
    )

    with pytest.raises(ValueError, match="component identity mismatch"):
        us_market_router.get_us_market_truth_api(symbol="AAPL", db=object())


def test_truth_api_keeps_known_client_value_error_as_bad_request(monkeypatch) -> None:
    def invalid_symbol(*args, **kwargs):
        raise ValueError("symbol must not be empty")

    monkeypatch.setattr(
        us_market_router,
        "read_us_market_truth_snapshot",
        invalid_symbol,
    )

    with pytest.raises(HTTPException) as captured:
        us_market_router.get_us_market_truth_api(symbol="", db=object())

    assert captured.value.status_code == 400
