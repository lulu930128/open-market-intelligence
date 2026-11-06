"""Bounded public TW EOD -> actual venue/acquisition/transaction replay."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from app.db.models import MarketDailyPrice, RawFetchResult, StockMaster
from app.db.session import SessionLocal
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe, read_taiwan_official_daily, refresh_taiwan_official_daily_venue
from app.market.official_breadth_platform import read_taiwan_official_breadth
from app.market.tw_universe import list_taiwan_stock_universe
from app.market_data import eod_coverage as owner
from test_tw_etf_daily_collection import DAY, NOW, db, payload
from test_tpex_postclose_replay import FIXTURE
from test_tw_official_daily_platform import FakeResponse


RESOURCES = ["MI_INDEX_ALLBUT0999", "STOCK_DAY_ALL", "tpex_mainboard_quotes",
             "tpex_mainboard_daily_close_quotes", "tpex_dated_daily_quotes", "tpex_after_trading_highlight"]


def replay(db, monkeypatch, *, budget=6, deadline=False, seed=True, calls=None, now=NOW):
    if seed:
        db.add_all([StockMaster(stock_id=s, market=v, instrument_type=t) for s, v, t in (
            ("2330", "TWSE", "stock"), ("0050", "TWSE", "etf"),
            ("3105", "TPEx", "stock"), ("6182", "TPEx", "stock"),
            ("6488", "TPEx", "stock"), ("00679B", "TPEx", "etf"))])
        db.commit()
    calls, seconds = calls if calls is not None else [], [0]
    bodies = {"MI_INDEX_ALLBUT0999": deepcopy(FIXTURE["twse"]),
              "STOCK_DAY_ALL": payload("STOCK_DAY_ALL", ["0050"]),
              "tpex_mainboard_quotes": FIXTURE["primary"],
              "tpex_mainboard_daily_close_quotes": FIXTURE["close"],
              "tpex_dated_daily_quotes": payload("tpex_dated_daily_quotes", ["3105", "6182", "6488", "00679B"]),
              "tpex_after_trading_highlight": FIXTURE["highlight"]}
    def fetch(route):
        calls.append(route.resource_id)
        if deadline:
            seconds[0] += 31
        return FakeResponse(text=json.dumps(bodies[route.resource_id], ensure_ascii=False))
    acquisition = TaiwanOfficialDailyAcquisitionExecutor(fetchers={r: fetch for r in RESOURCES},
        clock=lambda: now, monotonic=lambda: seconds[0])
    monkeypatch.setattr(owner, "utc_now", lambda: now)
    monkeypatch.setattr(owner, "monotonic", lambda: seconds[0])
    result = owner.reconcile_eod_coverage(db, market="TW", expected_trade_date=DAY,
        max_symbols=budget, max_runtime_seconds=30 if deadline else 120, error_backoff_seconds=60,
        taiwan_daily_qualifier=qualify_taiwan_eod_universe,
        taiwan_venue_refresher=lambda **kwargs: refresh_taiwan_official_daily_venue(
            **kwargs, requested_at=now, acquisition=acquisition))
    return result, calls


def test_one_final_run_walks_existing_six_resources_and_publishes(db, monkeypatch):
    result, calls = replay(db, monkeypatch)
    assert calls == RESOURCES
    assert result["external_call_budget_used"] == 6 and result["postcondition_met"]
    assert result["current_count"] == result["universe_count"] == 4
    assert result["etf_coverage"]["current_count"] == result["etf_coverage"]["universe_count"] == 2
    assert len(list_taiwan_stock_universe(db)) == 4
    assert db.query(MarketDailyPrice).count() == 6 and db.query(RawFetchResult).count() == 6
    read = read_taiwan_official_daily(db, stock_id="00679B", from_date=DAY, to_date=DAY, requested_at=NOW)
    bar = read.resolved.bars[0]
    assert bar.instrument.instrument_type.value == "etf" and bar.instrument.venue == "TPEX"
    assert bar.lineage.raw_contract_version == "tpex_dated_daily_quotes.v1"
    breadth = read_taiwan_official_breadth(db, venue="TPEX", trade_date=DAY, requested_at=NOW)
    assert breadth.resolved.health.facts_usable
    assert breadth.resolved.breadth.lineage.raw_receipt_id != bar.lineage.raw_receipt_id


@pytest.mark.parametrize("budget", [1, 2])
def test_public_lower_request_budget_keeps_unattempted_routes_pending(db, monkeypatch, budget):
    result, calls = replay(db, monkeypatch, budget=budget)
    assert len(calls) == result["external_call_budget_used"] == budget
    assert not result["postcondition_met"]
    states = result["checkpoint"]["detail"]["venue_route_states"]
    attempted = {r for state in states.values() for r in state["attempted_resources"]}
    assert attempted == set(calls)
    assert "tpex_dated_daily_quotes" not in attempted and "tpex_after_trading_highlight" not in attempted
    assert "tpex_mainboard_quotes" not in calls if budget == 1 else "tpex_mainboard_quotes" in calls
    assert result["checkpoint"]["next_retry_at"] is not None


def test_deadline_stops_admission_and_retains_pending_without_sleep(db, monkeypatch):
    result, calls = replay(db, monkeypatch, deadline=True)
    assert calls == ["MI_INDEX_ALLBUT0999"] and result["external_call_budget_used"] == 1
    assert not result["postcondition_met"]
    states = result["checkpoint"]["detail"]["venue_route_states"]
    assert states["TWSE"]["attempted_resources"] == calls
    assert states["TWSE"]["pending_resources"] == ["STOCK_DAY_ALL"]
    assert "TPEX" not in states


def test_lower_budget_continuation_rereads_fresh_session_after_backoff(db, monkeypatch):
    first, calls = replay(db, monkeypatch, budget=1)
    assert not first["postcondition_met"] and calls == ["MI_INDEX_ALLBUT0999"]
    row = db.query(MarketDailyPrice).filter_by(stock_id="2330").one()
    original = (row.id, row.raw_result_id, row.updated_at)
    engine = db.get_bind()
    db.close()
    with SessionLocal(bind=engine) as fresh:
        resumed, calls = replay(fresh, monkeypatch, budget=6, seed=False, calls=calls,
            now=NOW + timedelta(seconds=61))
        assert resumed["postcondition_met"] and resumed["external_call_budget_used"] == 5
        assert len(calls) == len(set(calls)) == 6 and set(calls) == set(RESOURCES)
        assert resumed["current_count"] == resumed["universe_count"] == 4
        assert resumed["etf_coverage"]["current_count"] == 2
        fresh.expire_all()
        row = fresh.query(MarketDailyPrice).filter_by(stock_id="2330").one()
        assert (row.id, row.raw_result_id, row.updated_at) == original
        breadth = read_taiwan_official_breadth(fresh, venue="TPEX", trade_date=DAY,
            requested_at=NOW + timedelta(seconds=61))
        assert breadth.resolved.health.facts_usable


def test_constant_one_call_rotates_full_venue_order_despite_unfillable_twse(db, monkeypatch):
    db.add(StockMaster(stock_id="9998", market="TWSE", instrument_type="stock"))
    db.commit()
    first, calls = replay(db, monkeypatch, budget=1)
    assert first["checkpoint"]["cursor_symbol"] == "TWSE"
    assert not first["postcondition_met"] and "9998" in first["checkpoint"]["detail"]["missing_sample"]
    engine = db.get_bind()
    db.close()
    with SessionLocal(bind=engine) as fresh:
        second, calls = replay(fresh, monkeypatch, budget=1, seed=False, calls=calls,
            now=NOW + timedelta(seconds=61))
        assert calls == ["MI_INDEX_ALLBUT0999", "tpex_mainboard_quotes"]
        assert second["external_call_budget_used"] == 1
        assert second["checkpoint"]["cursor_symbol"] == "TPEX"
        assert not second["postcondition_met"]
