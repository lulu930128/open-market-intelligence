from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.market_data_shadow import (
    compare_cached_daily_legacy_to_resolved,
    compare_yahoo_legacy_to_canonical,
)
from app.us_market import service as us_market_service


NEW_YORK = ZoneInfo("America/New_York")
START = datetime(2026, 8, 21, 9, 30, tzinfo=NEW_YORK)


def _payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "exchangeName": "NMS",
                        "currency": "USD",
                        "chartPreviousClose": 224.5,
                    },
                    "timestamp": [int(START.timestamp())],
                    "indicators": {
                        "quote": [
                            {
                                "open": [225.0],
                                "high": [225.8],
                                "low": [224.9],
                                "close": [225.6],
                                "volume": [1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _legacy(*, price: float = 225.6) -> dict:
    return {
        "symbol": "AAPL",
        "point_count": 1,
        "session_phase": "regular",
        "points": [
            {
                "time": START.isoformat(),
                "session": "regular",
                "price": price,
                "volume": 1200,
            }
        ],
    }


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol="AAPL",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )


def test_off_mode_does_no_canonical_work() -> None:
    assert (
        compare_yahoo_legacy_to_canonical(
            instrument=_instrument(),
            payload={},
            legacy={},
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
            session_scope="regular",
            mode="off",
        )
        is None
    )


def test_shadow_mode_validates_without_claiming_comparison() -> None:
    result = compare_yahoo_legacy_to_canonical(
        instrument=_instrument(),
        payload=_payload(),
        legacy=_legacy(),
        fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        session_scope="regular",
        mode="shadow",
    )
    assert result is not None
    assert result.status == "validated"
    assert result.compared_fields == 0
    assert result.mismatches == ()


def test_compare_mode_reports_match_and_bounded_semantic_mismatch() -> None:
    matched = compare_yahoo_legacy_to_canonical(
        instrument=_instrument(),
        payload=_payload(),
        legacy=_legacy(),
        fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        session_scope="regular",
        mode="compare",
    )
    assert matched is not None
    assert matched.status == "matched"
    assert matched.compared_fields == 6
    assert matched.mismatches == ()

    mismatched = compare_yahoo_legacy_to_canonical(
        instrument=_instrument(),
        payload=_payload(),
        legacy=_legacy(price=999),
        fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        session_scope="regular",
        mode="compare",
    )
    assert mismatched is not None
    assert mismatched.status == "mismatched"
    assert mismatched.mismatches == ("latest_price",)


def test_compare_mode_normalizes_legacy_1600_regular_close_as_closing_auction() -> None:
    close_time = datetime(2026, 8, 21, 16, 0, tzinfo=NEW_YORK)
    payload = _payload()
    payload["chart"]["result"][0]["timestamp"] = [int(close_time.timestamp())]
    legacy = _legacy()
    legacy["points"][0]["time"] = close_time.isoformat()

    result = compare_yahoo_legacy_to_canonical(
        instrument=_instrument(),
        payload=payload,
        legacy=legacy,
        fetched_at=datetime(2026, 8, 21, 16, 2, tzinfo=NEW_YORK),
        session_scope="regular",
        mode="compare",
    )

    assert result is not None
    assert result.status == "matched"
    assert result.mismatches == ()


def test_service_canary_wiring_is_zero_io_and_does_not_change_legacy_payload() -> None:
    payload = _payload()
    payload["chart"]["result"][0]["meta"]["exchangeName"] = "NMS"
    legacy = _legacy()
    with (
        patch.object(
            us_market_service.settings,
            "us_canonical_market_data_mode",
            "canary",
        ),
        patch.object(
            us_market_service.settings,
            "us_canonical_shadow_symbols",
            "AAPL",
        ),
        patch.object(
            us_market_service,
            "compare_yahoo_legacy_to_canonical",
            wraps=compare_yahoo_legacy_to_canonical,
        ) as compare,
    ):
        resolved = us_market_service._observe_us_intraday_canonical_shadow(
            payload=payload,
            parsed_payload=legacy,
            symbol="AAPL",
            session_scope="regular",
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        )
    compare.assert_called_once()
    assert resolved is not None
    assert resolved["quote_snapshot"]["schema_version"] == "omi.market.quote.snapshot.v1"
    assert resolved["intraday_bars"]["schema_version"] == "omi.market.bars.v1"
    assert legacy == _legacy()


def test_service_compare_mode_stays_dark_after_successful_comparison() -> None:
    with (
        patch.object(
            us_market_service.settings,
            "us_canonical_market_data_mode",
            "compare",
        ),
        patch.object(
            us_market_service.settings,
            "us_canonical_shadow_symbols",
            "AAPL",
        ),
    ):
        resolved = us_market_service._observe_us_intraday_canonical_shadow(
            payload=_payload(),
            parsed_payload=_legacy(),
            symbol="AAPL",
            session_scope="regular",
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        )

    assert resolved is None


def test_service_shadow_wiring_is_bounded_to_configured_symbols() -> None:
    with (
        patch.object(
            us_market_service.settings,
            "us_canonical_market_data_mode",
            "compare",
        ),
        patch.object(
            us_market_service.settings,
            "us_canonical_shadow_symbols",
            "AAPL",
        ),
        patch.object(
            us_market_service,
            "compare_yahoo_legacy_to_canonical",
        ) as compare,
    ):
        us_market_service._observe_us_intraday_canonical_shadow(
            payload=_payload(),
            parsed_payload=_legacy(),
            symbol="MSFT",
            session_scope="regular",
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        )
    compare.assert_not_called()


def test_service_on_mode_applies_to_requested_symbol_without_allowlist() -> None:
    with (
        patch.object(
            us_market_service.settings,
            "us_canonical_market_data_mode",
            "on",
        ),
        patch.object(
            us_market_service.settings,
            "us_canonical_shadow_symbols",
            "",
        ),
    ):
        resolved = us_market_service._observe_us_intraday_canonical_shadow(
            payload=_payload(),
            parsed_payload=_legacy(),
            symbol="AAPL",
            session_scope="regular",
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        )

    assert resolved is not None
    assert resolved["quote_snapshot"]["selected_session"] == "continuous"


def test_service_off_mode_does_not_call_shadow_adapter() -> None:
    with (
        patch.object(us_market_service.settings, "us_canonical_market_data_mode", "off"),
        patch.object(
            us_market_service,
            "compare_yahoo_legacy_to_canonical",
        ) as compare,
    ):
        us_market_service._observe_us_intraday_canonical_shadow(
            payload={},
            parsed_payload={},
            symbol="AAPL",
            session_scope="regular",
            fetched_at=datetime(2026, 8, 21, 10, 0, tzinfo=NEW_YORK),
        )
    compare.assert_not_called()


def test_daily_comparison_fails_closed_on_ohlcv_mismatch() -> None:
    legacy = {
        "points": [
            {
                "time": date(2026, 8, 21),
                "open": 224.0,
                "high": 226.0,
                "low": 223.0,
                "close": 225.0,
                "volume": 1000,
            }
        ]
    }
    resolved = {
        "bars": [
            {
                "start_at": "2026-08-21T09:30:00-04:00",
                "open_price": "224.0",
                "high_price": "226.0",
                "low_price": "223.0",
                "close_price": "999.0",
                "volume": "1000",
            }
        ]
    }

    comparison = compare_cached_daily_legacy_to_resolved(
        legacy=legacy,
        resolved=resolved,
    )

    assert comparison.status == "mismatched"
    assert comparison.mismatches == ("bars[0].close",)


def test_daily_service_canary_uses_cache_only_and_never_commits() -> None:
    db = MagicMock()
    fetched_at = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=date(2026, 8, 20),
            open_price=223.0,
            high_price=225.0,
            low_price=222.0,
            close_price=224.0,
            trade_volume=900,
            fetched_at=fetched_at,
            source_url="https://example.test/AAPL?range=1y&interval=1d",
        ),
        SimpleNamespace(
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=date(2026, 8, 21),
            open_price=224.0,
            high_price=226.0,
            low_price=223.0,
            close_price=225.0,
            trade_volume=1000,
            fetched_at=fetched_at,
            source_url="https://example.test/AAPL?range=1y&interval=1d",
        ),
    ]
    legacy_chart = {
        "timeframe": "daily",
        "from_date": date(2026, 8, 1),
        "to_date": date(2026, 8, 23),
        "expected_data_date": date(2026, 8, 21),
        "points": [
            {
                "time": date(2026, 8, 20),
                "open": 223.0,
                "high": 225.0,
                "low": 222.0,
                "close": 224.0,
                "volume": 900,
            },
            {
                "time": date(2026, 8, 21),
                "open": 224.0,
                "high": 226.0,
                "low": 223.0,
                "close": 225.0,
                "volume": 1000,
            },
        ],
    }
    with (
        patch.object(
            us_market_service.settings,
            "us_canonical_market_data_mode",
            "canary",
        ),
        patch.object(
            us_market_service.settings,
            "us_canonical_shadow_symbols",
            "AAPL",
        ),
        patch.object(
            us_market_service,
            "_list_us_ohlc_source_rows",
            return_value=rows,
        ),
        patch.object(
            us_market_service,
            "is_us_daily_price_finalized",
            return_value=True,
        ),
    ):
        result = us_market_service.get_us_daily_resolved_canary(
            db,
            symbol="AAPL",
            legacy_chart=legacy_chart,
            instrument_type="stock",
            venue="NASDAQ",
        )

    assert result is not None
    assert result["daily_ohlcv"]["schema_version"] == "omi.market.bars.v1"
    assert result["daily_ohlcv"]["selected_provider"] == "yahoo_chart"
    db.commit.assert_not_called()
    db.flush.assert_not_called()
