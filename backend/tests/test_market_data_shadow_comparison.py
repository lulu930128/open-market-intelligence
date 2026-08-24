from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db.models import StockMaster
from app.market.providers.kgi_canonical import canonical_snapshot_from_kgi
from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
from app.market.quote_depth import (
    KGI_SUPERPY_PROVIDER,
    TWSE_MIS_PROVIDER,
    _run_canonical_quote_shadow,
    _snapshot_values_from_kgi_quote,
    _snapshot_values_from_message,
)
from app.market_data.comparison import (
    MAX_MISMATCHES,
    BoundedComparisonMetrics,
    MismatchCategory,
    build_telemetry_event,
    compare_legacy_to_canonical,
)
from app.market_data.contracts import InstrumentKey, InstrumentType, Market


FETCHED_AT = datetime(2026, 6, 30, 1, 5, 13, tzinfo=timezone.utc)


def _stock() -> StockMaster:
    return StockMaster(
        stock_id="2330",
        stock_name="TSMC",
        market="TWSE",
        instrument_type="stock",
    )


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _kgi_quote(*, trial: bool = False) -> dict[str, object]:
    return {
        "exchange": "TWStock",
        "symbol": "2330",
        "odd_lot": False,
        "datetime": "20260630085900" if trial else "20260630090512",
        "open": 0 if trial else 2380,
        "high": 0 if trial else 2420,
        "low": 0 if trial else 2375,
        "close": 2412.5 if trial else 2410,
        "volume": 2046 if trial else 750,
        "total_volume": 0 if trial else 49540,
        "bid_prices": [2410, 2405, 2400, 2395, 2390],
        "bid_volumes": [978, 1150, 1399, 599, 924],
        "ask_prices": [2415, 2420, 2425, 2430, 2435],
        "ask_volumes": [2, 209, 209, 3, 1],
        "price_chg": 42.5 if trial else 40,
        "simtrade": 1 if trial else 0,
        "suspend": 0,
        "received_at": (
            "2026-06-30T00:59:00.100000+00:00"
            if trial
            else "2026-06-30T01:05:12.100000+00:00"
        ),
    }


def _mis_message(*, trial: bool = False) -> dict[str, str]:
    return {
        "c": "2330",
        "d": "20260630",
        "t": "08:59:00" if trial else "09:05:12",
        "z": "-" if trial else "2410",
        "y": "2370",
        "o": "-" if trial else "2380",
        "h": "-" if trial else "2420",
        "l": "-" if trial else "2375",
        "v": "0" if trial else "49540",
        "tv": "-" if trial else "750",
        "b": "2410_2405_2400_2395_2390_",
        "g": "978_1150_1399_599_924_",
        "a": "2415_2420_2425_2430_2435_",
        "f": "2_209_209_3_1_",
        "ts": "1" if trial else "0",
        "pz": "2412.5" if trial else "-",
        "ps": "2046" if trial else "-",
    }


def test_rollout_mode_defaults_off_and_reserved_modes_fail_closed() -> None:
    assert Settings(_env_file=None).canonical_market_data_mode == "off"
    assert Settings(_env_file=None).us_canonical_market_data_mode is None
    for supported in ("off", "shadow", "compare", "canary", "on"):
        assert (
            Settings(
                _env_file=None,
                us_canonical_market_data_mode=supported,
            ).us_canonical_market_data_mode
            == supported
        )
    for unsupported in ("canary", "on", "invalid"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, canonical_market_data_mode=unsupported)


def test_kgi_regular_and_trial_fixtures_match_canonical_semantics() -> None:
    for trial in (False, True):
        quote = _kgi_quote(trial=trial)
        phase = "preopen_auction" if trial else "regular_live"
        legacy = _snapshot_values_from_kgi_quote(
            stock=_stock(), session_phase=phase, quote=quote
        )
        canonical = canonical_snapshot_from_kgi(
            instrument=_instrument(), quote=quote, session=phase
        )
        result = compare_legacy_to_canonical(
            legacy=legacy,
            canonical=canonical,
            semantics={
                "trial": trial,
                "indicative_price": quote["close"] if trial else None,
                "indicative_volume_lots": quote["volume"] if trial else None,
                "suspend_hint": False,
            },
        )
        if trial:
            assert {item.field for item in result.mismatches} == {
                "open_price",
                "high_price",
                "low_price",
            }
            assert {
                item.reason_code for item in result.mismatches
            } == {"LEGACY_ZERO_NORMALIZED_TO_MISSING"}
        else:
            assert result.matched, result.model_dump()


def test_mis_regular_and_trial_fixtures_match_canonical_semantics() -> None:
    for trial in (False, True):
        message = _mis_message(trial=trial)
        phase = "preopen_auction" if trial else "regular_live"
        legacy = _snapshot_values_from_message(
            stock=_stock(),
            session_phase=phase,
            message=message,
            source_url="https://mis.twse.com.tw/fixture",
            payload={"msgArray": [message]},
            fetched_at=FETCHED_AT,
        )
        canonical = canonical_snapshot_from_twse_mis(
            instrument=_instrument(),
            message=message,
            session=phase,
            fetched_at=FETCHED_AT,
            expected_trade_date=legacy["trade_date"],
        )
        result = compare_legacy_to_canonical(
            legacy=legacy,
            canonical=canonical,
            semantics={
                "trial": trial,
                "indicative_price": message["pz"] if trial else None,
                "indicative_volume_lots": message["ps"] if trial else None,
            },
        )
        assert result.matched, result.model_dump()


def test_mismatch_taxonomy_is_deterministic_and_bounded() -> None:
    quote = _kgi_quote(trial=True)
    legacy = _snapshot_values_from_kgi_quote(
        stock=_stock(), session_phase="preopen_auction", quote=quote
    )
    canonical = canonical_snapshot_from_kgi(
        instrument=_instrument(), quote=quote, session="preopen_auction"
    )
    legacy.update(
        {
            "stock_id": "2317",
            "trade_date": None,
            "quote_time": FETCHED_AT,
            "session_phase": "regular_live",
            "last_price": 999,
            "previous_close": 999,
            "open_price": 999,
            "high_price": 999,
            "low_price": 999,
            "total_volume_lots": 999,
            "last_trade_volume_lots": 999,
            "bid_levels_json": "[]",
            "ask_levels_json": "[]",
            "provider": "wrong",
            "source": "wrong",
        }
    )
    result = compare_legacy_to_canonical(
        legacy=legacy,
        canonical=canonical,
        semantics={"trial": False, "suspend_hint": True},
    )
    assert len(result.mismatches) == MAX_MISMATCHES
    assert result.truncated is True
    categories = {mismatch.category for mismatch in result.mismatches}
    assert MismatchCategory.IDENTITY in categories
    assert MismatchCategory.PRICE in categories
    assert MismatchCategory.VOLUME_UNIT in categories
    assert MismatchCategory.DEPTH in categories


def test_metric_series_and_telemetry_payloads_are_bounded_and_sanitized() -> None:
    metrics = BoundedComparisonMetrics(max_series=2)
    for provider in ("a", "b", "c", "d"):
        event = build_telemetry_event(
            mode="shadow",
            provider=provider,
            market_phase="regular_live",
        )
        metrics.record(event)
        assert "raw_payload" not in event.model_dump_json()
    snapshot = metrics.snapshot()
    assert len(snapshot) <= 2
    assert any(item["provider"] == "overflow" for item in snapshot)


def test_shadow_telemetry_uses_runtime_logger() -> None:
    event = build_telemetry_event(
        mode="shadow",
        provider=KGI_SUPERPY_PROVIDER,
        market_phase="regular_live",
    )
    with patch("app.market.quote_depth.runtime_logger.info") as info:
        from app.market.quote_depth import _record_canonical_shadow_event

        _record_canonical_shadow_event(event)

    info.assert_called_once_with(
        "canonical_market_data_shadow %s",
        event.model_dump_json(),
    )


def test_off_mode_does_not_construct_canonical_observation() -> None:
    values = {"stock_id": "2330"}
    with (
        patch("app.market.quote_depth._canonical_market_data_mode", return_value="off"),
        patch("app.market.quote_depth.canonical_snapshot_from_kgi") as adapter,
    ):
        _run_canonical_quote_shadow(
            provider=KGI_SUPERPY_PROVIDER,
            stock=_stock(),
            session_phase="regular_live",
            raw_observation=_kgi_quote(),
            legacy_values=values,
        )
    adapter.assert_not_called()
    assert values == {"stock_id": "2330"}


def test_shadow_validates_same_payload_without_comparing_or_mutating_legacy() -> None:
    quote = _kgi_quote()
    legacy = _snapshot_values_from_kgi_quote(
        stock=_stock(), session_phase="regular_live", quote=quote
    )
    original = deepcopy(legacy)
    with (
        patch("app.market.quote_depth._canonical_market_data_mode", return_value="shadow"),
        patch(
            "app.market.quote_depth.canonical_snapshot_from_kgi",
            wraps=canonical_snapshot_from_kgi,
        ) as adapter,
        patch("app.market.quote_depth.compare_legacy_to_canonical") as comparator,
    ):
        _run_canonical_quote_shadow(
            provider=KGI_SUPERPY_PROVIDER,
            stock=_stock(),
            session_phase="regular_live",
            raw_observation=quote,
            legacy_values=legacy,
        )
    assert adapter.call_count == 1
    assert adapter.call_args.kwargs["quote"] is quote
    comparator.assert_not_called()
    assert legacy == original


def test_adapter_comparator_and_telemetry_failures_never_escape_shadow_seam() -> None:
    quote = _kgi_quote()
    legacy = _snapshot_values_from_kgi_quote(
        stock=_stock(), session_phase="regular_live", quote=quote
    )
    original = deepcopy(legacy)
    for failure_target in (
        "app.market.quote_depth.canonical_snapshot_from_kgi",
        "app.market.quote_depth.compare_legacy_to_canonical",
        "app.market.quote_depth._record_canonical_shadow_event",
    ):
        with (
            patch("app.market.quote_depth._canonical_market_data_mode", return_value="compare"),
            patch(failure_target, side_effect=RuntimeError("fault injection")),
        ):
            _run_canonical_quote_shadow(
                provider=KGI_SUPERPY_PROVIDER,
                stock=_stock(),
                session_phase="regular_live",
                raw_observation=quote,
                legacy_values=legacy,
            )
    assert legacy == original


def test_compare_mode_accepts_mis_same_payload_without_external_acquisition() -> None:
    message = _mis_message()
    legacy = _snapshot_values_from_message(
        stock=_stock(),
        session_phase="regular_live",
        message=message,
        source_url="https://mis.twse.com.tw/fixture",
        payload={"msgArray": [message]},
        fetched_at=FETCHED_AT,
    )
    with (
        patch("app.market.quote_depth._canonical_market_data_mode", return_value="compare"),
        patch(
            "app.market.quote_depth.canonical_snapshot_from_twse_mis",
            wraps=canonical_snapshot_from_twse_mis,
        ) as adapter,
        patch("app.market.quote_depth.http_get") as external_fetch,
    ):
        _run_canonical_quote_shadow(
            provider=TWSE_MIS_PROVIDER,
            stock=_stock(),
            session_phase="regular_live",
            raw_observation=message,
            legacy_values=legacy,
            fetched_at=FETCHED_AT,
        )
    assert adapter.call_count == 1
    assert adapter.call_args.kwargs["message"] is message
    external_fetch.assert_not_called()
    assert Decimal(str(legacy["last_price"])) == Decimal("2410")
