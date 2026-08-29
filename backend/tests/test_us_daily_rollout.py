from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USStockMaster
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import (
    US_DAILY_READ_BINDING_MODE,
    build_us_daily_acquisition_rollout_state,
    require_us_daily_acquisition_enabled,
    us_daily_target_key,
)
from app.us_market.errors import USMarketConfigurationError
from app.us_market.market_data.descriptors import (
    ALPHAVANTAGE_DAILY_RESOURCE_ID,
    YAHOO_DAILY_RESOURCE_ID,
)
from test_us_daily_ohlcv_acquisition import NOW, _yahoo_payload


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all(
        [
            USStockMaster(symbol="AAPL", exchange="NASDAQ", is_etf=False),
            USStockMaster(symbol="TSM", exchange="NYSE", is_etf=False),
        ]
    )
    db.commit()
    return db


def test_canary_rollout_enables_only_explicit_normalized_targets() -> None:
    state = build_us_daily_acquisition_rollout_state(
        mode="canary",
        symbols="aapl, SOX, AAPL",
        max_symbols=2,
        changed_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )

    assert state.canary_targets == ("US:AAPL", "US:^SOX")
    require_us_daily_acquisition_enabled("AAPL", state=state)
    require_us_daily_acquisition_enabled("^SOX", state=state)
    with pytest.raises(
        USMarketConfigurationError,
        match=r"US_DAILY_ACQUISITION_ROLLOUT_DISABLED: mode=canary target=US:TSM",
    ):
        require_us_daily_acquisition_enabled("TSM", state=state)


def test_canary_rollout_fails_closed_when_target_limit_is_exceeded() -> None:
    with pytest.raises(
        USMarketConfigurationError,
        match=r"target_count=3 exceeds max_symbols=2",
    ):
        build_us_daily_acquisition_rollout_state(
            mode="canary",
            symbols="AAPL,TSM,^SOX",
            max_symbols=2,
        )


def test_read_binding_is_canonical_independent_of_acquisition_rollout() -> None:
    off = build_us_daily_acquisition_rollout_state(mode="off", symbols="AAPL")

    assert US_DAILY_READ_BINDING_MODE == "canonical"
    assert off.production_enabled_for(us_daily_target_key("AAPL")) is False


def test_platform_blocks_non_canary_target_before_provider_io() -> None:
    db = _session()
    calls: list[str] = []

    def fetch(route, requirement):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=_yahoo_payload("TSM"),
            url="https://query.example.invalid/chart/TSM",
        )

    try:
        platform = USDailyOhlcvPlatform(
            db,
            rollout_state=build_us_daily_acquisition_rollout_state(
                mode="canary",
                symbols="AAPL",
                max_symbols=1,
                changed_at=NOW,
            ),
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: fetch,
                    ALPHAVANTAGE_DAILY_RESOURCE_ID: fetch,
                },
                clock=lambda: NOW,
            ),
        )

        with pytest.raises(
            USMarketConfigurationError,
            match=r"target=US:TSM",
        ):
            platform.refresh(symbol="TSM", bars=1, now=NOW)

        assert calls == []
    finally:
        db.close()
