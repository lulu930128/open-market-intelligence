from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.market.providers.kgi_canonical import canonical_snapshot_from_kgi
from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
from app.market_data.comparison import BoundedComparisonMetrics, build_telemetry_event
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    TradeObservationState,
)


FETCHED_AT = datetime(2026, 6, 30, 1, 5, 13, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey(
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
    for unsupported in ("canary", "on", "invalid"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, canonical_market_data_mode=unsupported)


def test_kgi_canonical_converter_keeps_trial_separate_from_actual_trade() -> None:
    regular = canonical_snapshot_from_kgi(
        instrument=INSTRUMENT,
        quote=_kgi_quote(),
        session="regular_live",
    )
    trial = canonical_snapshot_from_kgi(
        instrument=INSTRUMENT,
        quote=_kgi_quote(trial=True),
        session="preopen_auction",
    )

    assert regular.quote is not None
    assert regular.quote.trade_state is TradeObservationState.TRADE_OBSERVED
    assert trial.quote is not None
    assert trial.quote.trade_state is TradeObservationState.INDICATIVE_OBSERVED
    assert trial.quote.last_trade_price is None
    assert trial.auction is not None
    assert trial.auction.indicative_price is not None


def test_mis_canonical_converter_keeps_trial_separate_from_actual_trade() -> None:
    regular = canonical_snapshot_from_twse_mis(
        instrument=INSTRUMENT,
        message=_mis_message(),
        session="regular_live",
        fetched_at=FETCHED_AT,
        expected_trade_date=FETCHED_AT.astimezone(timezone.utc).date(),
    )
    trial = canonical_snapshot_from_twse_mis(
        instrument=INSTRUMENT,
        message=_mis_message(trial=True),
        session="preopen_auction",
        fetched_at=FETCHED_AT,
        expected_trade_date=FETCHED_AT.astimezone(timezone.utc).date(),
    )

    assert regular.quote is not None
    assert regular.quote.trade_state is TradeObservationState.TRADE_OBSERVED
    assert trial.quote is not None
    assert trial.quote.trade_state is TradeObservationState.INDICATIVE_OBSERVED
    assert trial.quote.last_trade_price is None


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
