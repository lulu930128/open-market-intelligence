"""Synthetic price qualifications: no provider IO or production database."""
from datetime import datetime

import pytest

from app.ai.decision_engine import build_position_math, build_position_decision, latest_price_snapshot
from app.ai.ask_finalizer import _market_live_summary
from app.ai.taiwan_intraday_contract import resolve_taiwan_current_price
from app.market.quote_depth import project_taiwan_decision_price

NOW = datetime.fromisoformat("2026-10-12T13:10:00+08:00")
POSITION = {"has_position_context": True, "entry_price": 1500, "decision_topic": "stop_loss"}


def quote(**overrides):
    return dict(
        trade_date="2026-10-12", headline_trade_date="2026-10-12",
        headline_price=1565, headline_basis="actual_trade", last_trade_price=1565,
        last_trade_available=True, headline_event_time="2026-10-12T13:09:55+08:00",
        last_trade_time="2026-10-12T13:09:55+08:00", headline_decision_usable=True,
        price_decision_usable=True, provider="twse_mis", source="twse_mis_quote_depth",
        freshness={"status": "live", "is_stale": False, "is_live": True},
    ) | overrides


def result(raw, bars=None, *, checked_at=NOW):
    resolved = resolve_taiwan_current_price(quote=raw, intraday_bars=bars or {},
                                          current_session_date=checked_at.date(), checked_at=checked_at)
    return {"data": {"compact": {"target": {"type": "tw_stock", "id": "3324"},
        "quote": {**raw, "current_price": resolved, "decision_price": resolved["decision_price"],
                  "last_price": 1565, "latest_price": 1565},
        "intraday_bars": {"series": {"1m": {"latest": {"close": 1565}}}}},
        "latest_daily": {"close_price": 1565}, "technical_reports": {"daily": {"latest_close": 1565}},
        "chart": {"points": [{"close": 1565}]}}}


@pytest.mark.parametrize("raw,bars", [
    (quote(headline_price=None, last_trade_price=None, last_trade_available=False,
           headline_decision_usable=False, price_decision_usable=False,
           best_bid_price=1560, best_ask_price=1570), {}),
    (quote(headline_price=37.65, last_trade_price=37.65,
           headline_event_time="2026-10-12T09:12:00+08:00", last_trade_time="2026-10-12T09:12:00+08:00",
           headline_decision_usable=False, price_decision_usable=False,
           freshness={"status": "stale", "is_stale": True}), {}),
    # Fresh receipt/contradictory owner flags cannot erase the original old event.
    (quote(headline_event_time="2026-10-12T09:12:00+08:00"), {}),
    (quote(headline_basis="auction_indicative"), {}),
    (quote(is_estimate=True), {}),
    (quote(price_decision_usable=False), {}),
    (quote(headline_price=None, last_trade_price=None, last_trade_available=False,
           headline_decision_usable=False, price_decision_usable=False),
     {"series": {"1m": {"trade_date": "2026-10-12", "points": [
         {"time": "2026-10-12T09:12:00+08:00", "close": 1565, "finalized": True}]}}}),
    (quote(headline_price=None, last_trade_price=None, last_trade_available=False,
           headline_decision_usable=False, price_decision_usable=False, previous_close=1565), {}),
    (quote(headline_event_time="2026-10-12T13:11:00+08:00"), {}),
    (quote(headline_trade_date="2026-10-09"), {}),
])
def test_non_decision_prices_cannot_escape_through_any_position_fallback(raw, bars):
    data = result(raw, bars)
    current = data["data"]["compact"]["quote"]["current_price"]
    assert current["value"] is None
    assert not current["decision_usable"] and not current["execution_usable"]
    assert latest_price_snapshot(data) == {}
    math = build_position_math(position_context=POSITION, result=data)
    assert math["latest_price"] is None and math["unrealized_return_pct"] is None
    assert not math["ready"] and not math["execution_usable"]
    decision = build_position_decision(question="成本1500，現在該停損嗎？", position_context=POSITION,
        target={"label": "3324"}, result=data, analysis_digest={})
    assert decision["latest_price"] is None
    assert decision["action_plan"] == [{"label": "價格待確認", "text": "缺少合格決策價格；先確認成交時間與品質，暫不產生停損執行建議。"}]
    summary = _market_live_summary(compact=data["data"]["compact"],
        quote=data["data"]["compact"]["quote"],
        intraday={"latest_point": {"close": 1565}, "freshness_status": "current", "status": "ok"})
    assert summary["display_price"] is None and not summary["is_live"]


def test_midpoint_is_explicit_research_only_and_original_stale_time_survives():
    raw = quote(headline_price=None, last_trade_price=None, last_trade_available=False,
                headline_decision_usable=False, price_decision_usable=False,
                best_bid_price=1560, best_ask_price=1570, snapshot_time=NOW.isoformat())
    current = result(raw)["data"]["compact"]["quote"]["current_price"]
    research = current["research_price"]
    assert research["value"] == 1565 and research["is_estimate"] is True
    assert research["event_time"] == NOW.isoformat()
    assert research["usage"] == "display_reference_only" and not research["decision_usable"]
    stale = result(quote(headline_price=37.65, last_trade_price=37.65,
                        headline_event_time="2026-10-12T09:12:00+08:00"))
    decision = stale["data"]["compact"]["quote"]["decision_price"]
    assert decision["event_time"] == "2026-10-12T09:12:00+08:00"
    assert decision["age_seconds"] == 14280


@pytest.mark.parametrize("basis", ["session_close", "official_close"])
def test_close_full_market_projection_to_calculator_path(basis):
    from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
    from app.ai.market_context.taiwan_stock import _apply_taiwan_current_price_contract
    checked = NOW.replace(hour=14)
    raw = quote(headline_basis=basis, session_phase="post_close_snapshot",
                headline_event_time="2026-10-12T13:30:00+08:00",
                freshness={"status": "session_final", "is_stale": False, "is_live": False})
    compact = _compact_quote_snapshot(latest_daily=None, quote_depth=raw, quote_error=None)
    _apply_taiwan_current_price_contract(quote=compact, intraday_bars={}, latest_daily=None,
        calendar_status={"date": "2026-10-12", "phase": "post_close_snapshot"}, checked_at=checked)
    data = {"data": {"compact": {"target": {"type": "tw_stock"}, "quote": compact}}}
    math = build_position_math(position_context=POSITION, result=data)
    assert compact["current_price"]["value"] == 1565
    assert compact["decision_price"]["event_time"] == "2026-10-12T13:30:00+08:00"
    assert math["latest_price"] == 1565 and math["unrealized_return_pct"] == 4.3333
    assert math["execution_usable"] is False


@pytest.mark.parametrize("basis", ["session_close", "official_close"])
def test_selected_close_quality_is_independent_of_stale_sibling_quote(basis):
    raw = quote(headline_basis=basis, headline_event_time="2026-10-12T13:30:00+08:00",
                freshness={"status": "stale", "is_stale": True},
                data_core_components={f"quote.{basis}": {
                    "decision_usable": True, "freshness": {"status": "fresh", "is_stale": False}}})
    data = result(raw, checked_at=NOW.replace(hour=14))
    math = build_position_math(position_context=POSITION, result=data)
    assert math["latest_price"] == 1565 and math["unrealized_return_pct"] == 4.3333
    raw["data_core_components"][f"quote.{basis}"]["decision_usable"] = False
    assert build_position_math(position_context=POSITION, result=result(raw, checked_at=NOW.replace(hour=14)))["latest_price"] is None


@pytest.mark.parametrize("basis", ["actual_trade", "session_close", "official_close"])
def test_current_trade_and_confirmed_close_remain_usable(basis):
    raw = quote(headline_basis=basis)
    if basis != "actual_trade":
        raw.update(headline_event_time="2026-10-12T13:30:00+08:00",
                   freshness={"status": "session_final", "is_stale": False, "is_live": False})
    checked = NOW if basis == "actual_trade" else NOW.replace(hour=14)
    price = project_taiwan_decision_price(raw, checked_at=checked, session_date=NOW.date())
    assert price.value == 1565 and price.decision_usable
    assert price.execution_usable is (basis == "actual_trade")
    data = result(raw, checked_at=checked)
    assert data["data"]["compact"]["quote"]["current_price"]["value"] == 1565
    math = build_position_math(position_context=POSITION, result=data)
    assert math["latest_price"] == 1565 and math["unrealized_return_pct"] == 4.3333


@pytest.mark.parametrize("target", ["us_stock", "jp_stock", "crypto"])
def test_non_taiwan_current_price_keeps_original_reader_behavior(target):
    data = {"data": {"compact": {"target": {"type": target},
        "quote": {"current_price": {"value": 2290, "event_time": NOW.isoformat()}}}}}
    math = build_position_math(position_context={**POSITION, "entry_price": 2380}, result=data)
    assert math["latest_price"] == 2290 and math["unrealized_return_pct"] == -3.7815
    summary = _market_live_summary(compact=data["data"]["compact"],
                                  quote=data["data"]["compact"]["quote"], intraday={})
    assert summary["display_price"] == 2290


@pytest.mark.parametrize("raw", [
    {"latest_price": 2290},
    {"current_price": {"value": 2290}},
    {"current_price": {"value": 2290, "is_estimate": True, "decision_usable": True}},
    {"price_decision_usable": False, "latest_price": 2290},
])
def test_identified_taiwan_without_qualified_contract_never_falls_back(raw):
    data = {"target": {"type": "tw_stock"}, "data": {"compact": {"quote": raw},
                                                       "latest_daily": {"close_price": 2290}}}
    assert latest_price_snapshot(data) == {}


def test_nested_trade_remains_unverified_in_single_and_batch_parsers():
    from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
    from app.market.providers.twse_mis_current_breadth import _classify_message
    from app.market_data.contracts import InstrumentKey, Market
    raw = dict(c="3324", d="20261012", t="13:10:00", z="-", tv="-", v="200", ts="0",
               trade={"t": "09:15:35", "v": 3, "z": 1470, "ft": 12})
    row = _classify_message(raw, "TPEX")
    assert row["current_price"] is None and not row["has_actual_trade"]
    snapshot = canonical_snapshot_from_twse_mis(
        message=raw, instrument=InstrumentKey(market=Market.TW, symbol="3324", instrument_type="stock", venue="TPEX"),
        fetched_at=NOW, session="regular", expected_trade_date=NOW.date(),
    )
    assert snapshot.quote.last_trade_price is None
