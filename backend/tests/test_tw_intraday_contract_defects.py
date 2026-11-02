"""Saved synthetic evidence only; no provider, dotenv or live database access."""
from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, TaiwanStockQuoteSnapshot, TaiwanIntradayStockState
from app.market.quote_depth import _row_to_response, _trade_price_provenance
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states, build_tw_intraday_group_snapshots
import test_tw_intraday_market_capabilities as fixtures


NOW = datetime(2026, 10, 27, 10, 35, tzinfo=TAIWAN_TZ)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("kind", ["top", "nested", "kgi", "unverified", "auction", "no_trade"])
@pytest.mark.parametrize("cached", [False, True])
def test_saved_quote_source_tracks_selected_raw_and_event(db, kind, cached):
    db.add(StockMaster(stock_id="2330", stock_name="fixture", market="TWSE", instrument_type="stock"))
    event = NOW - timedelta(minutes=2)
    message = dict(c="2330", d="20261027", t="10:33:00", z="110", tv="1", v="100", ts="0")
    provider, raw, price = "twse_mis", {"msgArray": [message]}, 110
    if kind == "nested":
        message.update(z="-", tv="-", t="10:34:00", trade=dict(z="110", v=1, t="10:33:00"))
    elif kind == "kgi":
        provider = "kgi_superpy"
        raw = dict(symbol="2330", datetime="20261027103300", close=110, volume=1, total_volume=100, simtrade=0)
    elif kind == "auction":
        message.update(ts="1", z="-", pz="110", trade=dict(z="110", v=1, t="10:33:00"))
        price = None
    elif kind == "no_trade":
        message.update(z="-", tv="0", v="0")
        price = None
    elif kind == "unverified":
        raw = {}
    original = TaiwanStockQuoteSnapshot(
        stock_id="2330", provider=provider, source="fixture", trade_date=NOW.date(),
        session_phase="regular_live", quote_time=event, fetched_at=NOW,
        last_price=price, total_volume_lots=100 if kind != "no_trade" else 0,
        raw_payload_json=json.dumps(raw), raw_result_id=741,
    )
    db.add(original)
    db.flush()
    latest = original
    if cached:
        latest = TaiwanStockQuoteSnapshot(
            stock_id="2330", provider=provider, source="fixture", trade_date=NOW.date(),
            session_phase="regular_live", quote_time=NOW, fetched_at=NOW,
            last_price=None, total_volume_lots=100, raw_payload_json='{}', raw_result_id=742,
        )
        db.add(latest)
    db.commit()
    result = _row_to_response(db, latest, phase="regular_live", now=NOW)
    if kind in {"auction", "no_trade"}:
        assert not result["last_trade_available"]
        assert result["actual_trade_price_source"] is None
        return
    assert result["last_trade_price"] == 110
    assert result["actual_trade_price_as_of"] == event
    lineage = result["actual_trade_price_lineage"]
    assert lineage["raw_result_id"] == 741
    assert lineage["observation_id"] == f"taiwan_stock_quote_snapshot:{original.id}"
    assert lineage["event_at"] == event
    assert lineage["selection"] == ("same_session_cache" if cached else "current_snapshot")
    field = {"top": "z", "nested": "trade.z", "kgi": "close", "unverified": None}[kind]
    assert lineage["price_field"] == field
    assert lineage["field_verified"] is (field is not None)
    assert result["actual_trade_price_source"] == (
        f"{'same_session' if cached else 'current'}_snapshot_{field}" if field else
        "same_session_cache" if cached else None)


@pytest.mark.parametrize("values,methods,expected,status,method", [
    ([None, None, None], [None, None, None], None, "unavailable", "unavailable"),
    ([100, 200, 300], ["unavailable"] * 3, None, "unavailable", "unavailable"),
    ([100, 200, None], ["a", "unavailable", None], 100, "partial", "a"),
    ([100, 200, 300], ["a"] * 3, 600, "ready", "a"),
    ([100, 200, 300], ["a", "b", "unavailable"], 300, "partial", "mixed_member_estimates"),
    ([100, 200, 300], ["a", "b", "a"], 600, "ready", "mixed_member_estimates"),
    ([-1, None, None], ["a", "unavailable", "unavailable"], None, "unavailable", "unavailable"),
])
def test_group_estimates_require_method_and_preserve_coverage(db, values, methods, expected, status, method):
    aliases = {"a": "estimated_actual_trade_price_x_cumulative_volume_lots", "b": "last_price_times_cumulative_volume_shares"}
    codes = ["2330", "2317", "2454"]
    for code in codes:
        db.add(StockMaster(stock_id=code, stock_name=code, market="TWSE", instrument_type="stock", industry="fixture", is_active=True))
    db.commit()
    persist_taiwan_intraday_stock_states(db, now=NOW, rows=[
        fixtures.TaiwanIntradayMarketCapabilityTests._stock_state_row(code, "TWSE", 110, 100, NOW) for code in codes])
    states = db.query(TaiwanIntradayStockState).order_by(TaiwanIntradayStockState.stock_id).all()
    for state, value, semantics in zip(states, values, methods):
        state.estimated_trade_value = value
        state.trade_value_semantics = aliases.get(semantics, semantics) or "unavailable"
    db.commit()
    result = build_tw_intraday_group_snapshots(db, generated_at=NOW)
    for group in [result["hot_groups"]["groups"][0], result["sectors"]["items"][0]]:
        assert group["estimated_trade_value"] == expected
        assert group["trade_value_method"] == aliases.get(method, method)
        coverage = group["trade_value_coverage"]
        assert coverage["status"] == status
        assert coverage["estimated_member_count"] == sum(value is not None and value >= 0 and semantics in aliases for value, semantics in zip(values, methods))
        assert coverage["unavailable_member_count"] + coverage["estimated_member_count"] == 3
        assert coverage["scope"] == "eligible_member_estimates"
        assert coverage["official_total"] is False
        assert group["trade_value_is_estimate"] is True


@pytest.mark.parametrize("provider,override", [
    ("twse_mis", {"c": "2317"}), ("twse_mis", {"d": "20261026"}),
    ("twse_mis", {"t": "10:34:00"}), ("twse_mis", {"z": "111"}),
    ("twse_mis", {"ts": "1"}),
    ("kgi_superpy", {"symbol": "2317"}),
    ("kgi_superpy", {"datetime": "20261026103300"}),
    ("kgi_superpy", {"close": 111}), ("kgi_superpy", {"simtrade": 1}),
    ("kgi_superpy", {"volume": 0}), ("kgi_superpy", {"volume": None}),
    ("kgi_superpy", {"total_volume": 0}), ("kgi_superpy", {"total_volume": None}),
    ("kgi_superpy", {"volume": "NaN"}), ("kgi_superpy", {"volume": "Infinity"}),
    ("kgi_superpy", {"total_volume": "NaN"}), ("kgi_superpy", {"total_volume": "Infinity"}),
])
def test_saved_raw_identity_clock_and_trade_evidence_must_match(provider, override):
    raw = (dict(c="2330", d="20261027", t="10:33:00", z="110", tv="1", v="100", ts="0")
           if provider == "twse_mis" else
           dict(symbol="2330", datetime="20261027103300", close=110, volume=1, total_volume=100, simtrade=0))
    raw.update(override)
    row = TaiwanStockQuoteSnapshot(id=1, stock_id="2330", provider=provider, source="fixture",
        trade_date=NOW.date(), quote_time=NOW - timedelta(minutes=2), fetched_at=NOW,
        last_price=110, total_volume_lots=100, raw_result_id=741,
        raw_payload_json=json.dumps({"msgArray": [raw]} if provider == "twse_mis" else raw))
    lineage = _trade_price_provenance(row)
    assert lineage["field_verified"] is False
    assert lineage["price_field"] is None
    assert lineage["raw_result_id"] == 741
