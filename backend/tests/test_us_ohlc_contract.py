from __future__ import annotations

from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, USDailyPrice
from app.us_market.service import (
    _apply_us_intraday_previous_close_reference,
    list_us_ohlc_chart_data,
    repair_us_ohlc_history,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def _daily_row(symbol: str, trade_date: date, close: float) -> USDailyPrice:
    return USDailyPrice(
        provider="yahoo_chart",
        symbol=symbol,
        trade_date=trade_date,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        trade_volume=100,
        source_url="https://query1.finance.yahoo.com/v8/chart?range=1y",
        raw_payload_hash=f"{symbol}:{trade_date.isoformat()}",
    )


def _intraday_payload(symbol: str, trade_date: date, price: float) -> dict:
    return {
        "symbol": symbol,
        "source": "yahoo_finance_chart",
        "session_phase": "regular",
        "point_count": 1,
        "points": [
            {
                "time": f"{trade_date.isoformat()}T12:00:00-04:00",
                "price": price,
                "open": price,
                "high": price,
                "low": price,
                "volume": 100,
                "session": "regular",
            }
        ],
    }


def test_spx_overlay_rejects_stale_previous_close_when_completed_sessions_are_missing() -> None:
    db = _session()
    try:
        db.add_all(
            [
                _daily_row("^GSPC", date(2026, 8, 18), 7684.0),
                _daily_row("^GSPC", date(2026, 8, 19), 7707.98),
            ]
        )
        db.commit()

        with (
            patch(
                "app.us_market.service.expected_us_daily_price_date",
                return_value=date(2026, 8, 21),
            ),
            patch(
                "app.us_market.service.get_us_intraday_trend",
                return_value=_intraday_payload("^GSPC", date(2026, 8, 24), 7646.36),
            ),
        ):
            chart = list_us_ohlc_chart_data(
                db=db,
                symbol="^GSPC",
                timeframe="daily",
                bars=3,
                include_intraday=True,
            )

        assert chart["missing_trade_dates"] == [
            date(2026, 8, 20),
            date(2026, 8, 21),
        ]
        assert chart["coverage_status"] == "partial"
        assert chart["expected_previous_close_trade_date"] == date(2026, 8, 21)
        assert chart["previous_close"] is None
        assert chart["previous_close_status"] == "missing"
        assert chart["is_current"] is False
    finally:
        db.close()


def test_umc_overlay_uses_exact_august_21_close_as_reference() -> None:
    db = _session()
    try:
        db.add_all(
            [
                _daily_row("UMC", date(2026, 8, 19), 17.9),
                _daily_row("UMC", date(2026, 8, 20), 18.0),
                _daily_row("UMC", date(2026, 8, 21), 18.34),
            ]
        )
        db.commit()

        with (
            patch(
                "app.us_market.service.expected_us_daily_price_date",
                return_value=date(2026, 8, 21),
            ),
            patch(
                "app.us_market.service.get_us_intraday_trend",
                return_value=_intraday_payload("UMC", date(2026, 8, 24), 18.83),
            ),
        ):
            chart = list_us_ohlc_chart_data(
                db=db,
                symbol="UMC",
                timeframe="daily",
                bars=3,
                include_intraday=True,
            )

        assert chart["coverage_status"] == "complete"
        assert chart["previous_close"] == 18.34
        assert chart["previous_close_trade_date"] == date(2026, 8, 21)
        assert chart["previous_close_status"] == "current"
        assert chart["is_current"] is True
    finally:
        db.close()


def test_intraday_reference_fails_closed_when_cached_daily_close_is_too_old() -> None:
    db = _session()
    try:
        db.add(_daily_row("UMC", date(2026, 8, 20), 18.0))
        db.commit()
        payload = _intraday_payload("UMC", date(2026, 8, 24), 18.83)
        payload.update(
            {
                "previous_close": 18.0,
                "previous_close_trade_date": "2026-08-20",
                "previous_close_provider": "yahoo_chart",
            }
        )

        with patch(
            "app.us_market.service._us_previous_regular_intraday_close_reference",
            return_value=None,
        ):
            result = _apply_us_intraday_previous_close_reference(
                payload,
                db=db,
                symbol="UMC",
            )

        assert result["expected_previous_close_trade_date"] == "2026-08-21"
        assert result["rejected_previous_close_trade_date"] == "2026-08-20"
        assert result["previous_close"] is None
        assert result["previous_close_status"] == "missing"
    finally:
        db.close()


def test_explicit_repair_reloads_cache_and_proves_postcondition() -> None:
    db = _session()
    try:
        db.add_all(
            [
                _daily_row("UMC", date(2026, 8, 18), 17.8),
                _daily_row("UMC", date(2026, 8, 19), 17.9),
            ]
        )
        db.commit()

        def refresh(**kwargs) -> dict:
            rows = [
                _daily_row("UMC", date(2026, 8, 20), 18.0),
                _daily_row("UMC", date(2026, 8, 21), 18.34),
            ]
            for row in rows:
                row.source_url = (
                    "https://query1.finance.yahoo.com/v8/chart?range=10y"
                )
            kwargs["db"].add_all(rows)
            kwargs["db"].commit()
            return {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "UMC",
                "fetched_count": 2,
                "inserted_count": 2,
                "updated_count": 0,
            }

        with patch("app.us_market.service.refresh_us_daily_prices", side_effect=refresh):
            result = repair_us_ohlc_history(
                symbol="UMC",
                timeframe="daily",
                bars=4,
                max_provider_calls=1,
                force_full=True,
                to_date=date(2026, 8, 21),
                session_factory=lambda: Session(db.get_bind()),
            )

        assert result["status"] == "success"
        assert result["provider_call_count"] == 1
        assert result["postcondition_met"] is True
        assert result["before"]["missing_trade_date_count"] == 2
        assert result["after"]["coverage_status"] == "complete"
        assert result["after"]["previous_close_trade_date"] == date(2026, 8, 20)
    finally:
        db.close()


def test_explicit_repair_does_not_report_success_when_provider_did_not_fill_gap() -> None:
    db = _session()
    try:
        db.add_all(
            [
                _daily_row("^GSPC", date(2026, 8, 18), 7684.0),
                _daily_row("^GSPC", date(2026, 8, 19), 7707.98),
            ]
        )
        db.commit()
        refresh_result = {
            "status": "success",
            "provider": "yahoo_chart",
            "symbol": "^GSPC",
            "fetched_count": 2,
            "inserted_count": 0,
            "updated_count": 2,
        }

        with patch(
            "app.us_market.service.refresh_us_daily_prices",
            return_value=refresh_result,
        ):
            result = repair_us_ohlc_history(
                symbol="^GSPC",
                timeframe="daily",
                bars=4,
                max_provider_calls=1,
                force_full=True,
                to_date=date(2026, 8, 21),
                session_factory=lambda: Session(db.get_bind()),
            )

        assert result["status"] == "partial_success"
        assert result["postcondition_met"] is False
        assert result["after"]["missing_trade_date_count"] == 2
    finally:
        db.close()
