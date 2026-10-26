"""Offline lightweight discovery and point-in-time candidate acceptance."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import socket

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.models import StockMaster, TaiwanIntradayStockState
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_discovery import read_tw_intraday_discovery, build_tw_intraday_radar_snapshot
from app.market.tw_intraday_radar import evaluate_intraday_candidates
from app.market.tw_intraday_radar_contracts import IntradayCandidateConfig, IntradayFeature
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states, build_tw_intraday_screening_snapshot


START = datetime(2026, 10, 7, 9, 0, tzinfo=TAIWAN_TZ)
FIXTURE = Path(__file__).parent / "fixtures/intraday_radar/6442_20261007.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source acceptance cannot access network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in (StockMaster.__table__, TaiwanIntradayStockState.__table__):
        table.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def universe(db, count=1):
    symbols = ["6442", *(str(1000 + i) for i in range(count - 1))]
    db.add_all([StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE" if i % 2 == 0 else "TPEX",
                           instrument_type="stock", is_active=True) for i, symbol in enumerate(symbols)])
    db.commit()
    return symbols


def observation(symbol, at, price=105, previous=100, volume=200, market="TWSE"):
    receipt_id = f"fixture:{symbol}:{at.isoformat()}"
    return dict(code=symbol, market=market, trade_date=at.date(), as_of=at, price_as_of=at if price else None,
                observation_received_at=at, current_price=price, previous_close=previous,
                open_price=previous, high_price=max(price, previous) if price else None,
                low_price=min(price, previous) if price else None, cumulative_volume_lots=volume,
                estimated_trade_value=price * volume * 1000 if price and volume is not None else None,
                has_actual_trade=price is not None, price_semantics="actual_trade" if price else "unavailable",
                provider="replay", source="fixture_lightweight_observation", raw_result_id=receipt_id,
                component_raw_result_ids=[receipt_id], component_sources=[dict(provider="replay",
                source="fixture_lightweight_observation", raw_result_id=receipt_id,
                event_at=at.isoformat(), received_at=at.isoformat())])


def seed_momentum(db):
    universe(db)
    for minute, price in ((1, 103), (4, 106)):
        at = START + timedelta(minutes=minute)
        persist_taiwan_intraday_stock_states(db, rows=[observation("6442", at, price)], now=at)
    return START + timedelta(minutes=4)


def test_6442_golden_full_universe_discovers_before_0910_without_known_symbol_request(db):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["provenance"]["kind"] == "bar_derived_replay"
    symbols = universe(db, 1967)
    first_candidate = None
    cumulative = 0
    high, low = 0, float("inf")
    for bar in fixture["bars"]:
        # A 09:00 candle close is unavailable at 09:00; release at 09:01.
        at = datetime.fromisoformat(bar["bar_time"]).replace(tzinfo=TAIWAN_TZ) + timedelta(minutes=1)
        cumulative += bar["trade_volume"]
        high, low = max(high, bar["high_price"]), min(low, bar["low_price"])
        rows = [observation(symbol, at, price=None, volume=0, market="TWSE" if i % 2 == 0 else "TPEX")
                for i, symbol in enumerate(symbols)]
        for row in rows:
            # Synthetic verified no-trade observations, not missing prices.
            row["actual_trade_reason_code"] = "ACTUAL_TRADE_EVIDENCE_MISSING"
        rows[0] = observation(fixture["stock_id"], at, bar["close_price"], fixture["previous_close"], cumulative / 1000)
        rows[0].update(high_price=high, low_price=low, open_price=fixture["bars"][0]["open_price"])
        persist_taiwan_intraday_stock_states(db, rows=rows, now=at)
        result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
        assert result.coverage.universe_count == 1967
        assert result.coverage.coverage_count == 1967
        assert result.coverage.is_full_market
        if any(candidate.observation.stock_id == "6442" for candidate in result.candidates) and first_candidate is None:
            first_candidate = at
            assert result.candidates[0].observation.features.change_pct.value < 10
            assert result.candidates[0].observation.features.return_15m.value is None
            screening = build_tw_intraday_screening_snapshot(db, generated_at=at)
            assert "6442" in [row["stock_id"] for row in screening["rows"]]
    assert first_candidate is not None
    assert first_candidate <= START.replace(minute=10), f"late discovery: {first_candidate}"
    assert first_candidate < START.replace(minute=15)
    assert first_candidate == START.replace(minute=4)


@pytest.mark.parametrize("available,status,full", [(0, "blocked", False), (18, "partial", False), (19, "ready", False), (20, "ready", True)])
def test_coverage_95_percent_boundary_and_missing_reasons(db, available, status, full):
    symbols = universe(db, 20)
    at = START + timedelta(minutes=5)
    rows = [observation(symbol, at, market="TWSE" if i % 2 == 0 else "TPEX") for i, symbol in enumerate(symbols[:available])]
    persist_taiwan_intraday_stock_states(db, rows=rows, now=at)
    coverage = read_tw_intraday_discovery(db, evaluated_at=at).coverage
    assert coverage.status == status and coverage.is_full_market is full
    assert coverage.observed_count == coverage.coverage_count == coverage.ranking_eligible_count == available
    assert coverage.coverage_ratio == available / 20
    assert len(coverage.missing_reasons) == 20 - available


def test_received_traded_but_price_missing_is_not_coverage_or_candidate(db):
    universe(db)
    at = START + timedelta(minutes=5)
    persist_taiwan_intraday_stock_states(db, rows=[observation("6442", at, price=None, volume=2482)], now=at)
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert result.coverage.observed_count == 1
    assert result.coverage.coverage_count == result.coverage.ranking_eligible_count == 0
    assert result.coverage.status == "blocked" and not result.candidates
    assert "ACTUAL_TRADE_UNAVAILABLE" in result.coverage.exclusion_reasons["6442"]


def test_returns_are_exact_deterministic_and_null_without_baseline(db):
    universe(db)
    for minute in range(17):
        at = START + timedelta(minutes=minute)
        persist_taiwan_intraday_stock_states(db, rows=[observation("6442", at, 100 + minute)], now=at)
    snapshot = read_tw_intraday_discovery(db, evaluated_at=at)
    features = snapshot.observations[0].features
    for minutes in (1, 3, 5, 15):
        value = getattr(features, f"return_{minutes}m")
        assert value.value == pytest.approx((116 / (116 - minutes) - 1) * 100)
        assert value.reference_time == at - timedelta(minutes=minutes)
    assert features.change_pct.value == pytest.approx(16)
    assert features.distance_from_high_pct.value == 0
    assert features.rebound_from_low_pct.value == pytest.approx(16)
    assert features.intraday_range_pct.value == pytest.approx(16)
    assert features.rvol_at_time.value is None and features.rvol_at_time.reason
    assert features.volume_velocity.value is None and features.volume_velocity.reason


def test_read_is_cache_only_and_does_not_autoflush_caller_changes(db):
    at = seed_momentum(db)
    db.add(StockMaster(stock_id="9001", stock_name="pending", market="TWSE", instrument_type="stock", is_active=True))
    db.execute(text("PRAGMA query_only=ON"))
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert result.candidates and result.coverage.universe_count == 1
    assert db.new  # caller mutation remains pending, never flushed by the read


@pytest.mark.parametrize("mutation", ["future_receipt", "prior_day", "lineage", "stale", "invalid_range", "indicative"])
def test_invalid_evidence_cannot_produce_candidate(db, mutation):
    at = seed_momentum(db)
    state = db.query(TaiwanIntradayStockState).one()
    if mutation == "future_receipt":
        components = json.loads(state.component_sources_json)
        components[0]["received_at"] = (at + timedelta(minutes=1)).isoformat()
        state.component_sources_json = json.dumps(components)
    elif mutation == "prior_day":
        state.trade_date -= timedelta(days=1)
    elif mutation == "lineage":
        state.lineage_complete = False
    elif mutation == "invalid_range":
        state.high_price = 1
    elif mutation == "indicative":
        state.price_semantics = "indicative_match"
    else:
        at += timedelta(minutes=11)
    db.commit()
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert not result.candidates


def test_point_in_time_no_future_or_late_reference_leakage(db):
    at = seed_momentum(db)
    state = db.query(TaiwanIntradayStockState).one()
    samples = json.loads(state.samples_json)
    samples[0]["received_at"] = (at + timedelta(minutes=1)).isoformat()
    state.samples_json = json.dumps(samples)
    db.commit()
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert not result.candidates
    earlier = read_tw_intraday_discovery(db, evaluated_at=at - timedelta(minutes=1))
    assert earlier.coverage.observed_count == 0
    assert earlier.coverage.missing_reasons["6442"] == "OBSERVATION_NOT_AVAILABLE_AT_EVALUATION"


def test_replay_identity_config_and_evidence_hashes(db):
    at = seed_momentum(db)
    discovery = read_tw_intraday_discovery(db, evaluated_at=at)
    result = evaluate_intraday_candidates(discovery)
    assert result == evaluate_intraday_candidates(discovery)
    stricter = evaluate_intraday_candidates(discovery, config=IntradayCandidateConfig(min_return_3m=99))
    assert stricter.config_hash != result.config_hash and stricter.evaluation_id != result.evaluation_id
    assert not stricter.candidates
    state = db.query(TaiwanIntradayStockState).one()
    state.source = "corrected_source"
    db.commit()
    corrected = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert corrected.config_hash == result.config_hash and corrected.evaluation_id != result.evaluation_id


@pytest.mark.parametrize("corruption", ["bad_json", "bad_lineage", "old_reference", "missing_reference", "nonfinite", "legacy_receipt"])
def test_malformed_or_missing_inputs_stay_null_with_reason(db, corruption):
    at = seed_momentum(db)
    state = db.query(TaiwanIntradayStockState).one()
    samples = json.loads(state.samples_json)
    if corruption == "bad_json":
        state.samples_json = "{"
    elif corruption == "bad_lineage":
        samples[0]["raw_result_ids"] = 123
        state.samples_json = json.dumps(samples)
    elif corruption == "old_reference":
        samples[0]["price_as_of"] = (START - timedelta(minutes=1)).isoformat()
        state.samples_json = json.dumps(samples)
    elif corruption == "missing_reference":
        state.previous_close = None
    elif corruption == "legacy_receipt":
        samples[0]["sample_contract_version"] = "tw.trade_sample.v1"
        state.samples_json = json.dumps(samples)
    else:
        state.high_price = float("inf")
    db.commit()
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert not result.candidates
    observation = read_tw_intraday_discovery(db, evaluated_at=at).observations[0]
    feature = observation.features.change_pct if corruption == "missing_reference" else observation.features.distance_from_high_pct if corruption == "nonfinite" else observation.features.return_3m
    assert feature.value is None and feature.reason


def test_partial_scan_retains_candidate_and_explicit_limitations(db):
    at = seed_momentum(db)
    db.add(StockMaster(stock_id="2330", stock_name="2330", market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    result = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    assert result.status == "partial" and result.coverage.coverage_ratio == 0.5
    assert len(result.candidates) == 1
    assert "DISCOVERY_COVERAGE_BELOW_95_PERCENT" in result.candidates[0].limitations
    assert result.candidates[0].observation.features.return_3m.reference_raw_result_ids


def test_sample_v2_preserves_real_receipt_clock(db):
    universe(db)
    event = START + timedelta(minutes=1)
    receipt = event + timedelta(seconds=40)
    row = observation("6442", event)
    row["observation_received_at"] = receipt
    row["component_sources"][0]["received_at"] = receipt.isoformat()
    persist_taiwan_intraday_stock_states(db, rows=[row], now=receipt)
    sample = json.loads(db.query(TaiwanIntradayStockState).one().samples_json)[0]
    assert sample["sample_contract_version"] == "tw.trade_sample.v2"
    assert sample["received_at"] == receipt.isoformat()
    assert sample["price_as_of"] == event.isoformat()


def test_out_of_order_ingestion_cannot_erase_newer_momentum(db):
    at = seed_momentum(db)
    before = build_tw_intraday_radar_snapshot(db, evaluated_at=at)
    old = observation("6442", at - timedelta(minutes=2), 1)
    result = persist_taiwan_intraday_stock_states(db, rows=[old], now=at)
    assert result["skipped_count"] == 1
    assert build_tw_intraday_radar_snapshot(db, evaluated_at=at) == before


def test_empty_universe_and_non_session_are_blocked(db):
    assert read_tw_intraday_discovery(db, evaluated_at=START).coverage.status == "blocked"
    at = seed_momentum(db)
    assert not build_tw_intraday_radar_snapshot(db, evaluated_at=at.replace(hour=8)).candidates
    with pytest.raises(ValueError, match="timezone aware"):
        read_tw_intraday_discovery(db, evaluated_at=at.replace(tzinfo=None))


def test_active_stock_universe_excludes_etf_inactive_and_other_markets(db):
    universe(db)
    db.add_all([StockMaster(stock_id=symbol, stock_name=symbol, market=market, instrument_type=kind, is_active=active)
                for symbol, market, kind, active in (("9001", "TWSE", "etf", True), ("9002", "TWSE", "stock", False), ("9003", "US", "stock", True))])
    db.commit()
    assert read_tw_intraday_discovery(db, evaluated_at=START).coverage.universe_count == 1


@pytest.mark.parametrize("config", [{"min_change_pct": float("nan")}, {"min_return_3m": -1}, {"min_cumulative_volume_lots": 0}])
def test_config_rejects_invalid_thresholds(config):
    with pytest.raises(ValidationError):
        IntradayCandidateConfig(**config)
    with pytest.raises(ValidationError):
        IntradayFeature()
