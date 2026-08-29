from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USStockMaster
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import build_us_daily_acquisition_rollout_state
from app.us_market.market_data.descriptors import (
    ALPACA_SIP_DAILY_RESOURCE_ID,
    YAHOO_DAILY_RESOURCE_ID,
)


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 22, 8, 0, tzinfo=EASTERN)
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
    db.commit()
    return db


def _yahoo(trade_date: date, close: float) -> dict:
    timestamp = int(datetime.combine(trade_date, datetime.min.time(), tzinfo=EASTERN).replace(hour=12).timestamp())
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "TSM", "currency": "USD"},
                    "timestamp": [timestamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [close - 1],
                                "high": [close + 1],
                                "low": [close - 2],
                                "close": [close],
                                "volume": [1_000_000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _alpaca(trade_date: date, close: float) -> dict:
    return {
        "symbol": "TSM",
        "bars": [{
            "t": f"{trade_date.isoformat()}T04:00:00Z",
            "o": close - 1,
            "h": close + 1,
            "l": close - 2,
            "c": close,
            "v": 1_001_000,
        }],
        "next_page_token": None,
    }


def _platform(
    db: Session,
    *,
    yahoo_date: date,
    yahoo_close: float,
    alpaca_date: date,
    alpaca_close: float,
):
    return USDailyOhlcvPlatform(
        db,
        rollout_state=ON_ROLLOUT,
        acquisition=USDailyOhlcvAcquisitionExecutor(
            fetchers={
                YAHOO_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                    payload=_yahoo(yahoo_date, yahoo_close),
                    url="https://query.example.invalid/chart/TSM",
                ),
                ALPACA_SIP_DAILY_RESOURCE_ID: lambda route, requirement: USProviderPayload(
                    payload=_alpaca(alpaca_date, alpaca_close),
                    url="https://data.example.invalid/v2/stocks/bars?feed=sip",
                ),
            },
            clock=lambda: NOW,
        ),
    )


def test_fresh_alpaca_is_selected_when_preferred_yahoo_is_stale() -> None:
    db = _session()
    try:
        result = _platform(
            db,
            yahoo_date=date(2026, 8, 20),
            yahoo_close=241,
            alpaca_date=date(2026, 8, 21),
            alpaca_close=244,
        ).refresh(symbol="TSM", bars=2, now=NOW)

        assert result.postcondition_satisfied is True
        assert result.projection["selected_provider"] == "alpaca"
        assert result.projection["fallback_used"] is True
        assert result.projection["latest_trade_date"] == "2026-08-21"
        assert result.projection["bars"][-1]["close_price"] == "244.0"
    finally:
        db.close()


def test_fresh_primary_short_circuits_secondary_without_hiding_selection() -> None:
    db = _session()
    try:
        result = _platform(
            db,
            yahoo_date=date(2026, 8, 21),
            yahoo_close=245,
            alpaca_date=date(2026, 8, 21),
            alpaca_close=244,
        ).refresh(symbol="TSM", bars=1, now=NOW)

        assert result.postcondition_satisfied is True
        assert result.projection["selected_provider"] == "yahoo_chart"
        assert result.projection["bars"][-1]["close_price"] == "245.0"
        assert {item["provider"] for item in result.projection["candidates"]} == {
            "yahoo_chart",
        }
        assert result.result.acquisition.providers_attempted == ("yahoo_chart",)
        assert result.result.acquisition.external_calls == 1
    finally:
        db.close()


def test_both_stale_remain_fail_visible_and_do_not_satisfy_postcondition() -> None:
    db = _session()
    try:
        result = _platform(
            db,
            yahoo_date=date(2026, 8, 20),
            yahoo_close=241,
            alpaca_date=date(2026, 8, 20),
            alpaca_close=242,
        ).refresh(symbol="TSM", bars=2, now=NOW)

        assert result.postcondition_satisfied is False
        assert result.projection["latest_trade_date"] == "2026-08-20"
        assert result.projection["research_usable"] is False
        assert result.result.dataset_health is not None
        assert result.result.dataset_health.status.value == "stale"
    finally:
        db.close()
