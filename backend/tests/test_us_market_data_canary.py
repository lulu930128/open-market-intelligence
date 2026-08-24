from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.market_data_canary import (
    build_cached_daily_resolved_canary,
    build_yahoo_intraday_resolved_canary,
)


NEW_YORK = ZoneInfo("America/New_York")


def test_completed_session_canary_resolves_without_claiming_live() -> None:
    close_time = datetime(2026, 8, 21, 16, 0, tzinfo=NEW_YORK)
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "chartPreviousClose": 224.5,
                    },
                    "timestamp": [int(close_time.timestamp())],
                    "indicators": {
                        "quote": [
                            {
                                "open": [225.0],
                                "high": [226.0],
                                "low": [224.9],
                                "close": [225.8],
                                "volume": [5000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }

    resolved = build_yahoo_intraday_resolved_canary(
        instrument=InstrumentKey(
            market=Market.US,
            symbol="AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        payload=payload,
        fetched_at=datetime(2026, 8, 23, 4, 0, tzinfo=NEW_YORK),
        session_scope="regular",
    )

    quote = resolved["quote_snapshot"]
    bars = resolved["intraday_bars"]
    assert quote["status"] == "selected"
    assert quote["selection_reason"] == "COMPLETED_SESSION_SELECTED"
    assert quote["selected_session"] == "closed"
    assert quote["research_usable"] is True
    assert bars["status"] == "selected"
    assert bars["selected_session"] == "closed"
    assert bars["returned_bar_count"] == 1
    assert bars["bars"][0]["finalization"] == "final"


def test_cached_daily_canary_selects_fresh_provider_without_io_or_writes() -> None:
    def row(
        provider: str,
        trade_date: date,
        close: float,
        fetched_at: datetime,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            provider=provider,
            symbol="AAPL",
            trade_date=trade_date,
            open_price=close - 1,
            high_price=close + 1,
            low_price=close - 2,
            close_price=close,
            trade_volume=1000,
            fetched_at=fetched_at,
        )

    resolved = build_cached_daily_resolved_canary(
        instrument=InstrumentKey(
            market=Market.US,
            symbol="AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        rows=[
            row(
                "alphavantage",
                date(2026, 8, 20),
                224.0,
                datetime(2026, 8, 21, 1, 0, tzinfo=timezone.utc),
            ),
            row(
                "yahoo_chart",
                date(2026, 8, 20),
                224.0,
                datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
            ),
            row(
                "yahoo_chart",
                date(2026, 8, 21),
                225.0,
                datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
            ),
        ],
        expected_trade_date=date(2026, 8, 21),
        now=datetime(2026, 8, 23, 4, 0, tzinfo=NEW_YORK),
        max_bars=10,
    )

    assert resolved["schema_version"] == "omi.market.bars.v1"
    assert resolved["compatibility_schema_versions"] == []
    assert resolved["selected_provider"] == "yahoo_chart"
    assert resolved["selected_session"] == "closed"
    assert resolved["selection_reason"] == "COMPLETED_SESSION_SELECTED"
    assert resolved["status"] == "selected"
    assert resolved["available_bar_count"] == 2
    assert resolved["bars"][-1]["close_price"] == "225.0"
    assert resolved["bars"][-1]["provider"] == "yahoo_chart"
    assert resolved["bars"][-1]["source"] == "yahoo.chart.1d"
