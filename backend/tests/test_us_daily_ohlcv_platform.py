from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USDailyPrice, USStockMaster
from app.jobs import backfill_tasks
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.daily_ohlcv_platform import (
    USDailyOhlcvPlatform,
    refresh_us_daily_ohlcv,
)
from app.us_market.daily_rollout import build_us_daily_acquisition_rollout_state
from app.us_market.daily_ohlcv_chart import (
    read_us_daily_ohlcv_chart,
    read_us_daily_ohlcv_history,
)
from app.us_market.market_data.descriptors import (
    ALPHAVANTAGE_DAILY_RESOURCE_ID,
    ALPACA_SIP_DAILY_RESOURCE_ID,
    ALPACA_SIP_DAILY_DESCRIPTOR,
    YAHOO_DAILY_DESCRIPTOR,
    YAHOO_DAILY_RESOURCE_ID,
    us_daily_history_descriptors,
)
from app.us_market.schemas import USDailyPriceRefreshResultRead, USOhlcChartRead
from test_us_daily_ohlcv_acquisition import NOW, _yahoo_payload


ON_ROLLOUT = build_us_daily_acquisition_rollout_state(
    mode="on",
    symbols="",
    changed_at=NOW,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(USStockMaster(symbol="TSM", exchange="NYSE", is_etf=False))
    db.add(USStockMaster(symbol="AAPL", exchange="NASDAQ", is_etf=False))
    db.commit()
    return db


def test_cache_read_is_zero_io_and_explicit_refresh_mandatorily_rereads() -> None:
    db = _session()
    calls = []

    def fetch(route, requirement):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=_yahoo_payload("TSM"),
            url="https://query.example.invalid/chart/TSM",
        )

    def no_fallback(route, requirement):
        raise RuntimeError("fixture fallback unavailable")

    try:
        platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: fetch,
                    ALPHAVANTAGE_DAILY_RESOURCE_ID: no_fallback,
                },
                clock=lambda: NOW + timedelta(seconds=1),
            ),
        )
        before = platform.read(symbol="TSM", bars=1, now=NOW)
        assert calls == []
        assert before.postcondition_satisfied is False
        assert before.projection["latest_trade_date"] is None
        assert before.projection["freshness_status"] == "missing"
        assert before.projection["refresh_recommended"] is True
        assert before.projection["decision_usable"] is False

        refreshed = platform.refresh(symbol="TSM", bars=1, now=NOW)
        assert calls == [YAHOO_DAILY_RESOURCE_ID]
        assert refreshed.result.persistence.committed is True
        assert refreshed.postcondition_satisfied is True
        assert refreshed.projection["expected_trade_date"] == "2026-08-21"
        assert refreshed.projection["latest_trade_date"] == "2026-08-21"
        assert refreshed.projection["selected_provider"] == "yahoo_chart"
        assert refreshed.projection["selected_event_at"] is not None
        assert refreshed.projection["freshness_status"] == "current"
        assert refreshed.projection["is_current"] is True
        assert refreshed.projection["refresh_recommended"] is False
        assert refreshed.projection["decision_usable"] is True
        assert refreshed.projection["bars"][0]["volume_status"] == "observed"
        assert refreshed.projection["bars"][0]["price_basis"] == "raw"

        with patch(
            "app.us_market.daily_ohlcv_platform.USDailyOhlcvPlatform"
        ) as platform_type:
            platform_type.return_value.refresh.return_value = refreshed
            refresh_payload = refresh_us_daily_ohlcv(db, symbol="TSM")

        serialized_refresh = USDailyPriceRefreshResultRead.model_validate(
            refresh_payload
        ).model_dump()
        assert serialized_refresh["selected_source"] == "yahoo.chart.1d"
        assert serialized_refresh["selected_event_at"] is not None
        assert serialized_refresh["external_call_count"] == 1
        assert serialized_refresh["providers_attempted"] == ["yahoo_chart"]
        assert serialized_refresh["resource_attempts"] == [
            {
                "provider": "yahoo_chart",
                "resource_id": YAHOO_DAILY_RESOURCE_ID,
            },
        ]
        assert serialized_refresh["persistence_committed"] is True
        assert serialized_refresh["inserted_count"] == 1
        assert serialized_refresh["updated_count"] == 0
        assert serialized_refresh["unchanged_count"] == 0
        assert serialized_refresh["postcondition_satisfied"] is True
        assert serialized_refresh["raw_result_ids"]

        calls.clear()
        reread = platform.read(
            symbol="TSM",
            bars=1,
            now=NOW + timedelta(seconds=2),
        )
        assert calls == []
        assert reread.postcondition_satisfied is True
        assert db.query(USDailyPrice).count() == 1

        chart = read_us_daily_ohlcv_chart(
            db,
            symbol="TSM",
            bars=1,
            now=NOW + timedelta(seconds=2),
        )
        assert calls == []
        assert chart["point_count"] == 1
        assert chart["latest_data_date"].isoformat() == "2026-08-21"
        assert chart["selected_provider"] == "yahoo_chart"
        assert chart["latest_trade_date"].isoformat() == "2026-08-21"
        assert chart["expected_trade_date"].isoformat() == "2026-08-21"
        assert chart["facts_usable"] is True
        assert chart["decision_usable"] is True
        assert chart["usability_status"] == "decision_usable"
        assert chart["previous_close_status"] == "missing"
        assert chart["refresh_recommended"] is False
        assert chart["coverage_refresh_recommended"] is False
        assert chart["selected_event_at"] is not None
        assert chart["request_coverage_status"] == chart["coverage_status"]
        serialized_chart = USOhlcChartRead.model_validate(chart).model_dump()
        assert serialized_chart["selected_source"] == "yahoo.chart.1d"
        assert serialized_chart["selected_event_at"] is not None
        assert serialized_chart["expected_trade_date"].isoformat() == "2026-08-21"

        history = read_us_daily_ohlcv_history(
            db,
            symbol="TSM",
            limit=1,
            now=NOW + timedelta(seconds=2),
        )
        assert calls == []
        assert len(history) == 1
        assert history[0]["id"] > 0
        assert history[0]["symbol"] == "TSM"
        assert history[0]["trade_date"].isoformat() == "2026-08-21"
        assert history[0]["provider"] == "yahoo_chart"
        assert history[0]["raw_payload_hash"]
    finally:
        db.close()


def test_history_coverage_is_separate_from_daily_temporal_usability() -> None:
    db = _session()
    try:
        seed_platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            descriptors=(YAHOO_DAILY_DESCRIPTOR,),
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                        payload=_yahoo_payload("TSM"),
                        url="https://query.example.invalid/chart/TSM",
                    )
                },
                clock=lambda: NOW + timedelta(seconds=1),
            ),
        )
        seed_platform.refresh(symbol="TSM", bars=1, now=NOW, max_provider_calls=1)

        short = seed_platform.read(
            symbol="TSM",
            bars=2,
            now=NOW + timedelta(seconds=2),
        )
        assert short.temporal_postcondition_satisfied is True
        assert short.coverage_postcondition_satisfied is False
        assert short.postcondition_satisfied is True
        assert short.projection["decision_usable"] is True
        assert short.projection["history_status"] == "insufficient_history"
        short_chart = read_us_daily_ohlcv_chart(
            db,
            symbol="TSM",
            bars=2,
            now=NOW + timedelta(seconds=2),
        )
        assert short_chart["refresh_recommended"] is False
        assert short_chart["coverage_refresh_recommended"] is True

        first = int(datetime(2026, 8, 20, 12, 0, tzinfo=NOW.tzinfo).timestamp())
        second = int(datetime(2026, 8, 21, 12, 0, tzinfo=NOW.tzinfo).timestamp())
        history_payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "TSM", "currency": "USD"},
                        "timestamp": [first, second],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [238.0, 240.0],
                                    "high": [242.0, 245.0],
                                    "low": [237.0, 239.0],
                                    "close": [241.0, 244.0],
                                    "volume": [900, 1000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
        history_platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            descriptors=(YAHOO_DAILY_DESCRIPTOR,),
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                        payload=history_payload,
                        url="https://query.example.invalid/chart/TSM",
                    )
                },
                clock=lambda: NOW + timedelta(seconds=3),
            ),
        )
        repaired = history_platform.ensure_history_coverage(
            symbol="TSM",
            bars=2,
            now=NOW + timedelta(seconds=2),
            max_provider_calls=1,
        )

        assert repaired.temporal_postcondition_satisfied is True
        assert repaired.coverage_postcondition_satisfied is True
        assert repaired.postcondition_satisfied is True
        assert repaired.projection["available_bar_count"] == 2
        assert repaired.projection["coverage_status"] == "complete"
        repaired_chart = read_us_daily_ohlcv_chart(
            db,
            symbol="TSM",
            bars=2,
            now=NOW + timedelta(seconds=4),
        )
        assert repaired_chart["coverage_refresh_recommended"] is False
    finally:
        db.close()


def test_history_provider_order_is_operation_scoped() -> None:
    assert [
        item.provider_key
        for item in us_daily_history_descriptors(
            (YAHOO_DAILY_DESCRIPTOR, ALPACA_SIP_DAILY_DESCRIPTOR)
        )
    ] == ["alpaca", "yahoo_chart"]
    assert [
        item.provider_key
        for item in (YAHOO_DAILY_DESCRIPTOR, ALPACA_SIP_DAILY_DESCRIPTOR)
    ] == ["yahoo_chart", "alpaca"]


def test_sox_vertical_slice_preserves_not_applicable_volume() -> None:
    db = _session()
    try:
        platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            descriptors=(YAHOO_DAILY_DESCRIPTOR,),
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                        payload=_yahoo_payload("^SOX", volume=None),
                        url="https://query.example.invalid/chart/%5ESOX",
                    ),
                    ALPHAVANTAGE_DAILY_RESOURCE_ID: lambda route, requirement: (_ for _ in ()).throw(
                        RuntimeError("fixture fallback unavailable")
                    ),
                },
                clock=lambda: NOW,
            ),
        )
        result = platform.refresh(symbol="^SOX", bars=1, now=NOW)

        assert result.postcondition_satisfied is True
        assert result.identity.identity_source == "market_index_registry"
        assert result.projection["volume_applicability"] == "not_applicable"
        assert result.projection["bars"][0]["volume"] is None
        assert result.projection["bars"][0]["volume_status"] == "not_applicable"
        chart = read_us_daily_ohlcv_chart(db, symbol="^SOX", bars=1, now=NOW)
        assert chart["points"][0]["volume"] is None
        assert chart["volume_unit"] is None
        assert chart["volume_status"] == "not_applicable"
    finally:
        db.close()


def test_legacy_diagnostics_repair_delegates_to_canonical_platform() -> None:
    db = _session()
    calls = []

    def fetch(route, requirement):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=_yahoo_payload("TSM"),
            url="https://query.example.invalid/chart/TSM",
        )

    try:
        platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            descriptors=(YAHOO_DAILY_DESCRIPTOR,),
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: fetch,
                    ALPHAVANTAGE_DAILY_RESOURCE_ID: lambda route, requirement: (_ for _ in ()).throw(
                        RuntimeError("fixture fallback unavailable")
                    ),
                },
                clock=lambda: NOW,
            ),
        )
        with patch.object(
            backfill_tasks,
            "USDailyOhlcvPlatform",
            return_value=platform,
        ):
            result = backfill_tasks._run_canonical_us_ohlc_repair(
                db,
                symbol="TSM",
                timeframe="weekly",
                bars=1,
                provider="yahoo_chart",
                adjusted=False,
                max_provider_calls=1,
                force_full=False,
            )

        assert calls == [YAHOO_DAILY_RESOURCE_ID]
        assert result["provider"] == "canonical"
        assert result["provider_path_compatibility"] == "yahoo_chart"
        assert result["provider_call_budget"] == 1
        assert result["provider_call_count"] == 1
        assert result["inserted_count"] == 1
        assert result["updated_count"] == 0
        assert result["unchanged_count"] == 0
        assert result["refreshes"][0]["selected_provider"] is None
        assert result["refreshes"][0]["coverage_postcondition_satisfied"] is False
        assert result["refreshes"][0]["persistence_committed"] is True
        assert result["refreshes"][0]["inserted_count"] == 1
        assert result["refreshes"][0]["updated_count"] == 0
        assert result["refreshes"][0]["unchanged_count"] == 0
        assert result["postcondition_met"] is False
        assert result["status"] == "partial_success"
    finally:
        db.close()


@pytest.mark.parametrize("symbol", ["AAPL", "TSM"])
def test_stock_yahoo_missing_close_resolves_through_alpaca_p2_after_reread(
    symbol: str,
) -> None:
    from app.us_market.market_data.descriptors import (
        ALPACA_SIP_DAILY_RESOURCE_ID,
        US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    )
    from test_us_daily_ohlcv_acquisition import _alpaca_payload

    db = _session()
    request_now = datetime(2026, 8, 29, 9, 0, tzinfo=NOW.tzinfo)
    previous_timestamp = int(
        datetime(2026, 8, 27, 12, 0, tzinfo=NOW.tzinfo).timestamp()
    )
    missing_timestamp = int(
        datetime(2026, 8, 28, 12, 0, tzinfo=NOW.tzinfo).timestamp()
    )
    yahoo_gap = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol, "currency": "USD"},
                    "timestamp": [previous_timestamp, missing_timestamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [229.0, 230.5],
                                "high": [231.0, 233.2],
                                "low": [228.5, 229.9],
                                "close": [230.1, None],
                                "volume": [50000000, 55881234],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    alpaca_828 = _alpaca_payload(symbol, close=232.14)
    alpaca_828["bars"][0]["t"] = "2026-08-28T04:00:00Z"
    alpaca_828["bars"][0].update({"o": 230.5, "h": 233.2, "l": 229.9})

    try:
        platform = USDailyOhlcvPlatform(
            db,
            rollout_state=ON_ROLLOUT,
            descriptors=US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
            acquisition=USDailyOhlcvAcquisitionExecutor(
                fetchers={
                    YAHOO_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                        payload=yahoo_gap,
                        url=f"https://query.example.invalid/chart/{symbol}",
                    ),
                    ALPACA_SIP_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                        payload=alpaca_828,
                        url=f"https://data.example.invalid/v2/stocks/{symbol}/bars?feed=sip",
                    ),
                },
                clock=lambda: request_now + timedelta(seconds=1),
            ),
        )
        result = platform.refresh(symbol=symbol, bars=5, now=request_now)

        assert result.postcondition_satisfied is True
        assert result.projection["expected_trade_date"] == "2026-08-28"
        assert result.projection["latest_trade_date"] == "2026-08-28"
        assert result.projection["selected_provider"] == "alpaca"
        assert result.projection["selected_source"] == "alpaca.sip.stock_bars.1d"
        assert result.projection["fallback_used"] is True
        assert result.result.acquisition.external_calls == 2
        assert result.result.persistence.committed is True
        assert db.query(USDailyPrice).filter(USDailyPrice.provider == "alpaca").count() == 1
    finally:
        db.close()
