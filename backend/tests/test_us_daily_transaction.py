from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.daily_price_transaction import USDailyPriceTransaction
from app.us_market.market_data.descriptors import (
    ALPACA_SIP_DAILY_RESOURCE_ID,
    US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    US_DAILY_PROVIDER_DESCRIPTORS,
    YAHOO_DAILY_RESOURCE_ID,
)
from test_us_daily_ohlcv_acquisition import (
    NOW,
    _alpaca_payload,
    _requirement,
    _yahoo_payload,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _acquisition(requirement):
    plan = plan_data_acquisition_v2(requirement, US_DAILY_PROVIDER_DESCRIPTORS)
    symbol = requirement.target.instrument.symbol
    return USDailyOhlcvAcquisitionExecutor(
        fetchers={
            YAHOO_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                payload=_yahoo_payload(symbol),
                url=f"https://query.example.invalid/chart/{symbol}",
            )
        },
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)


def test_transaction_atomically_persists_receipt_and_complete_lineage() -> None:
    db = _session()
    try:
        requirement = _requirement()
        result = USDailyPriceTransaction(db).persist_bar_acquisition(
            requirement,
            _acquisition(requirement),
        )
        row = db.query(USDailyPrice).one()
        raw = db.query(RawFetchResult).one()

        assert result.committed is True
        assert result.receipts_written == 1
        assert result.observations_inserted == 1
        assert result.observations_updated == 0
        assert row.raw_result_id == raw.id
        assert row.source_id == raw.source_id
        assert row.authority == "vendor"
        assert row.raw_contract_version == "yahoo.chart.v8"
        assert row.event_at is not None
        assert row.finalization == "final"
        assert row.price_basis == "raw"
        assert row.volume_status == "observed"
        assert row.volume_unit == "shares"
        assert row.raw_payload_hash == raw.content_hash
    finally:
        db.close()


def test_retry_is_observation_idempotent_and_reuses_raw_receipt() -> None:
    db = _session()
    try:
        requirement = _requirement()
        transaction = USDailyPriceTransaction(db)
        acquisition = _acquisition(requirement)
        transaction.persist_bar_acquisition(requirement, acquisition)
        second = transaction.persist_bar_acquisition(requirement, acquisition)

        assert db.query(USDailyPrice).count() == 1
        assert db.query(RawFetchResult).count() == 1
        assert second.receipts_written == 0
        assert second.observations_inserted == 0
        assert second.observations_updated == 0
        assert second.observations_unchanged == 1
    finally:
        db.close()


def test_commit_failure_rolls_back_and_rethrows_original_error() -> None:
    db = _session()
    try:
        requirement = _requirement()
        transaction = USDailyPriceTransaction(db)
        with (
            patch.object(db, "commit", side_effect=RuntimeError("commit failed")),
            patch.object(db, "rollback", wraps=db.rollback) as rollback,
            pytest.raises(RuntimeError, match="commit failed"),
        ):
            transaction.persist_bar_acquisition(requirement, _acquisition(requirement))
        rollback.assert_called_once()
        db.expire_all()
        assert db.query(USDailyPrice).count() == 0
    finally:
        db.close()


def test_observation_without_matching_receipt_fails_closed() -> None:
    db = _session()
    try:
        requirement = _requirement()
        acquisition = _acquisition(requirement)
        broken = acquisition.__class__(
            summary=acquisition.summary,
            observations=acquisition.observations,
            receipts=(),
            provider_health=acquisition.provider_health,
        )
        with pytest.raises(ValueError, match="matching raw provider/source"):
            USDailyPriceTransaction(db).persist_bar_acquisition(requirement, broken)
        assert db.query(USDailyPrice).count() == 0
    finally:
        db.close()


def test_alpaca_source_metadata_comes_from_registered_resource() -> None:
    db = _session()
    try:
        requirement = _requirement(max_provider_calls=2)
        yahoo_payload = _yahoo_payload("TSM")
        yahoo_payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None]
        plan = plan_data_acquisition_v2(
            requirement,
            US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
        )
        acquisition = USDailyOhlcvAcquisitionExecutor(
            fetchers={
                YAHOO_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                    payload=yahoo_payload,
                    url="https://query.example.invalid/chart/TSM",
                ),
                ALPACA_SIP_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                    payload=_alpaca_payload("TSM"),
                    url="https://data.example.invalid/v2/stocks/TSM/bars?feed=sip",
                ),
            },
            clock=lambda: NOW,
        ).acquire_bar_observations(requirement, plan)

        result = USDailyPriceTransaction(db).persist_bar_acquisition(
            requirement,
            acquisition,
        )
        source = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == "alpaca.sip.stock_bars.1d")
            .one()
        )

        assert result.committed is True
        assert source.priority == 110
        assert source.auth_type == "api_key"
        assert "secret" not in source.endpoint_url.lower()
    finally:
        db.close()
