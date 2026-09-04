from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_watchlist_state import (
    project_taiwan_watchlist_instrument_state,
)
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


ETF = InstrumentKey(
    market=Market.TW,
    symbol="0050",
    instrument_type=InstrumentType.ETF,
    venue="TWSE",
)


def _quote(*, trade_date: date, price: float, freshness: str = "current") -> dict:
    event_time = datetime.combine(
        trade_date,
        datetime.min.time().replace(hour=13, minute=30),
        tzinfo=TAIWAN_TZ,
    )
    return {
        "trade_date": trade_date,
        "actual_trade_occurred": True,
        "last_trade_price": price,
        "previous_close": 100.0,
        "change_pct": price - 100.0,
        "last_trade_time": event_time,
        "event_time": event_time,
        "provider": "kgi",
        "source": "kgi.quote",
        "freshness": {"status": freshness},
    }


def _daily(*, trade_date: date, close: str, change: str = "1") -> SimpleNamespace:
    return SimpleNamespace(
        daily=SimpleNamespace(
            trade_date=trade_date,
            close_price=Decimal(close),
            price_change=Decimal(change),
            provider="twse_rwd",
            source="twse.mops.rwd",
            event_at=datetime(
                trade_date.year,
                trade_date.month,
                trade_date.day,
                15,
                20,
                tzinfo=TAIWAN_TZ,
            ),
        )
    )


def test_regular_session_prefers_current_actual_trade_for_etf() -> None:
    projected = project_taiwan_watchlist_instrument_state(
        ETF,
        requested_at=datetime(2026, 9, 4, 10, 0, tzinfo=TAIWAN_TZ),
        quote=_quote(trade_date=date(2026, 9, 4), price=107.5),
        session_close=None,
        daily=_daily(trade_date=date(2026, 9, 3), close="106"),
    )

    assert projected["instrument_type"] == "etf"
    assert projected["status"] == "observed"
    assert projected["price"] == 107.5
    assert projected["price_semantics"] == "actual_trade"
    assert projected["provider"] == "kgi"


def test_post_close_prefers_current_session_final_before_daily_release() -> None:
    event_time = datetime(2026, 9, 4, 13, 30, tzinfo=TAIWAN_TZ)
    projected = project_taiwan_watchlist_instrument_state(
        ETF,
        requested_at=datetime(2026, 9, 4, 14, 0, tzinfo=TAIWAN_TZ),
        quote=_quote(trade_date=date(2026, 9, 4), price=107.9),
        session_close={
            "available": True,
            "status": "session_final",
            "trade_date": date(2026, 9, 4),
            "price": 107.9,
            "event_time": event_time,
            "provider": "kgi",
            "source": "kgi.quote",
        },
        daily=_daily(trade_date=date(2026, 9, 3), close="106"),
    )

    assert projected["status"] == "session_final"
    assert projected["price"] == 107.9
    assert projected["trade_date"] == date(2026, 9, 4)
    assert projected["freshness_status"] == "current"


def test_released_official_daily_close_has_highest_post_close_authority() -> None:
    projected = project_taiwan_watchlist_instrument_state(
        ETF,
        requested_at=datetime(2026, 9, 4, 16, 0, tzinfo=TAIWAN_TZ),
        quote=_quote(trade_date=date(2026, 9, 4), price=107.8),
        session_close={
            "available": True,
            "status": "session_final",
            "trade_date": date(2026, 9, 4),
            "price": 107.9,
            "event_time": datetime(2026, 9, 4, 13, 30, tzinfo=TAIWAN_TZ),
            "provider": "kgi",
            "source": "kgi.quote",
        },
        daily=_daily(trade_date=date(2026, 9, 4), close="108", change="2"),
    )

    assert projected["status"] == "official_close"
    assert projected["price"] == 108.0
    assert projected["previous_close"] == 106.0
    assert projected["provider"] == "twse_rwd"


def test_preopen_uses_latest_completed_daily_without_calling_it_today() -> None:
    projected = project_taiwan_watchlist_instrument_state(
        ETF,
        requested_at=datetime(2026, 9, 4, 8, 15, tzinfo=TAIWAN_TZ),
        quote=None,
        session_close=None,
        daily=_daily(trade_date=date(2026, 9, 3), close="106"),
    )

    assert projected["status"] == "latest_completed_session"
    assert projected["trade_date"] == date(2026, 9, 3)
    assert projected["expected_trade_date"] == date(2026, 9, 4)
    assert projected["price_semantics"] == "latest_completed_session_close"
    assert projected["freshness_status"] == "stale"


def test_missing_post_close_evidence_remains_null_and_explicit() -> None:
    projected = project_taiwan_watchlist_instrument_state(
        ETF,
        requested_at=datetime(2026, 9, 4, 16, 0, tzinfo=TAIWAN_TZ),
        quote=None,
        session_close=None,
        daily=None,
    )

    assert projected["status"] == "missing"
    assert projected["price"] is None
    assert projected["freshness_status"] == "missing"
    assert projected["reason_code"] == "WATCHLIST_EVIDENCE_MISSING"
    assert projected["cache_only"] is True
