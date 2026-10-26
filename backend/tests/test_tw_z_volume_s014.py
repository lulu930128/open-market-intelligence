"""S0/S1/S4 offline fixtures, independent of live receipts or production DB."""
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import socket

import pytest

from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
from app.db.models import TaiwanStockQuoteSnapshot, TaiwanMarketMinuteState
from app.market.quote_depth import project_taiwan_quote_evidence_bundle
from app.market.taiwan_quote_evidence import read_taiwan_quote_evidence_bundle
from app.market.taiwan_market_state import (
    persist_taiwan_market_minute_state, read_taiwan_market_volume_state,
    compose_taiwan_market_volume_state,
)
from app.market_data.contracts import Quantity, QuantityUnit
from test_tw_public_quote_platform import db  # noqa: F401
from test_tw_r4_last_confirmed_trade import START, _persist_mis
from test_taiwan_market_state import make_session, market_summary_payload
from test_tw_volume_composition import qualified_estimate


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("S014 fixtures cannot use network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def canonical_bundle(db, *, volume="24219", price="-", legacy=False, age=0):
    _persist_mis(db, START, price=price, volume=volume)
    bundle = read_taiwan_quote_evidence_bundle(db, stock_id="2330", requested_at=START + timedelta(seconds=age))
    assert bundle.quote.resolved.quote is not None
    if not legacy:
        db.query(TaiwanStockQuoteSnapshot).delete()
        db.commit()
    return bundle


@pytest.mark.parametrize("volume", ["24219", "9845", "22518", "0", "-"])
@pytest.mark.parametrize("legacy", [False, True])
def test_quote_volume_contract_and_ai_parity(db, volume, legacy):
    bundle = canonical_bundle(db, volume=volume, legacy=legacy)
    db.connection().exec_driver_sql("PRAGMA query_only=ON")
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    lots = None if volume == "-" else int(volume)
    assert projected["cumulative_volume_lots"] == lots
    assert projected["cumulative_volume_shares"] == (lots * 1000 if lots is not None else None)
    assert projected["volume_status"] == ("available" if lots is not None else "unavailable")
    assert projected["provider_volume_available"] is (lots is not None)
    assert projected["volume_source"] == "twse_mis"
    assert projected["volume_decision_usable"] is False
    assert projected["last_trade_price"] is None
    assert projected["last_trade_available"] is False
    assert projected["volume_reconciliation"]["snapshot_volume_shares"] == projected["cumulative_volume_shares"]
    compact = _compact_quote_snapshot(latest_daily=None, quote_depth=projected, quote_error=None)
    for key in ("cumulative_volume_lots", "cumulative_volume_shares", "volume_status", "volume_source", "provider_volume_available", "volume_reconciliation"):
        assert compact[key] == projected[key]


@pytest.mark.parametrize("quantity", [
    Quantity(value=Decimal("24219500"), unit=QuantityUnit.SHARE),
    Quantity(value=Decimal("24219"), unit=QuantityUnit.UNIT),
    Quantity(value=Decimal("24219"), unit=QuantityUnit.BOARD_LOT),
    Quantity(value=Decimal("1500"), unit=QuantityUnit.SHARE, original_value=Decimal("1.5"), original_unit=QuantityUnit.BOARD_LOT, scale=Decimal("1000")),
    Quantity(value=Decimal("1001"), unit=QuantityUnit.SHARE, original_value=Decimal("1"), original_unit=QuantityUnit.BOARD_LOT, scale=Decimal("1000")),
])
def test_unproven_board_lot_conversion_never_invents_volume(db, quantity):
    bundle = canonical_bundle(db)
    quote = bundle.quote.resolved.quote.model_copy(update={"cumulative_quantity": quantity})
    bundle = replace(bundle, quote=bundle.quote.model_copy(update={"resolved": bundle.quote.resolved.model_copy(update={"quote": quote})}))
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert projected["cumulative_volume_lots"] is None
    assert projected["volume_status"] == "unavailable"
    assert projected["volume_decision_usable"] is False


@pytest.mark.parametrize("age", [0, 16, 180])
def test_volume_does_not_relabel_stale_price_or_clock(db, age):
    bundle = canonical_bundle(db, price="2400", age=age)
    quote = bundle.quote.resolved.quote
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert projected["quote_time"] == quote.lineage.event_at == START
    assert projected["received_at"] == quote.lineage.received_at
    assert projected["cumulative_volume_shares"] == 24219000
    compact = _compact_quote_snapshot(latest_daily=None, quote_depth=projected, quote_error=None,
        session_phase="regular", current_session_date=START.date().isoformat(), is_trading_day=True)
    assert compact["price_decision_usable"] is (age <= 15)


def test_canonical_volume_reconciliation_uses_daily_bar_date(db):
    bundle = canonical_bundle(db)
    # BarObservation owns end_at, not a trade_date field.
    from app.market_data.contracts import BarObservation, BarFinalization
    quote = bundle.quote.resolved.quote
    bar = BarObservation(instrument=quote.instrument, lineage=quote.lineage,
        interval="1d", start_at=START.replace(hour=9), end_at=START.replace(hour=13, minute=30),
        open_price=Decimal("2400"), high_price=Decimal("2400"), low_price=Decimal("2400"), close_price=Decimal("2400"),
        volume=Quantity(value=Decimal("24219500"), unit=QuantityUnit.SHARE),
        finalization=BarFinalization.FINAL)
    bundle = replace(bundle, official_close=bundle.official_close.model_copy(update={
        "resolved": bundle.official_close.resolved.model_copy(update={"bars": (bar,)})}))
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert projected["official_daily_volume_trade_date"] == START.date().isoformat()
    assert projected["volume_reconciliation"]["status"] == "scope_different"
    assert projected["volume_reconciliation"]["difference_shares"] == -500


def test_public_omi_ask_quote_snapshot_volume_parity(db, monkeypatch):
    from app.ai import ask, tools
    from app.ai.schemas import AiAskRequest
    from app.config import settings
    bundle = canonical_bundle(db)
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    monkeypatch.setattr(tools, "read_taiwan_quote_evidence_projection", lambda **kwargs: projected)
    monkeypatch.setattr(tools, "_now", lambda: START)
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)
    db.connection().exec_driver_sql("PRAGMA query_only=ON")
    result = ask.ask(db=db, server_policy=ask.AiAskServerPolicy(can_external_fetch=False), payload=AiAskRequest(
        question="2330 成交量", target={"type": "tw_stock", "id": "2330"}, mode="data_only",
        output="decision_with_evidence", contract_version="omi.decision.v4", allow_llm=False,
        selection={"required": ["quote.snapshot"], "include": ["quote.snapshot"],
                   "fields": {"quote.snapshot": ["cumulative_volume_lots", "cumulative_volume_shares", "volume_status", "volume_source", "provider_volume_available"]}},
        allow_external_fetch=False, realtime_policy="cache_only",
    ))
    outward = result["evidence"]["data"]["quote.snapshot"]
    for key in ("cumulative_volume_lots", "cumulative_volume_shares", "volume_status", "volume_source", "provider_volume_available"):
        assert outward[key] == projected[key]


@pytest.mark.parametrize("legacy", [False, True])
def test_fugle_volume_and_timestamp_stay_provider_owned(db, legacy):
    from app.market.providers.fugle_realtime import FugleRealtimeBuffer, fugle_quote_acquisition
    from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
    from test_tw_r4_last_confirmed_trade import _fugle, _requirement
    message = _fugle(START, trade_time=int(START.timestamp() * 1_000_000))
    message["data"]["total"]["tradeVolume"] = 14223
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(message, received_at=START)
    acquisition = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), _requirement(START))
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(_requirement(START), acquisition)
    bundle = read_taiwan_quote_evidence_bundle(db, stock_id="2330", requested_at=START)
    if not legacy:
        db.query(TaiwanStockQuoteSnapshot).delete()
        db.commit()
    db.connection().exec_driver_sql("PRAGMA query_only=ON")
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert projected["cumulative_volume_lots"] == 14223
    assert projected["cumulative_volume_shares"] == 14223000
    assert projected["volume_status"] == "available"
    assert projected["volume_source"] == bundle.quote.resolved.quote.lineage.provider
    assert projected["quote_time"] == START


def test_preopen_quantity_cannot_become_actual_cumulative_volume(db):
    now = START.replace(hour=8, minute=45)
    _persist_mis(db, now, price="-", volume="0")
    bundle = read_taiwan_quote_evidence_bundle(db, stock_id="2330", requested_at=now)
    assert bundle.quote.resolved.quote is not None
    db.query(TaiwanStockQuoteSnapshot).delete()
    db.commit()
    projected = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert projected["cumulative_volume_lots"] is None
    assert projected["volume_status"] == "unavailable"
    assert projected["last_trade_price"] is None


def test_documented_raw866252_subset_has_missing_price_before_projection():
    # Deliberately a documented subset, not a claim to replay the full stored Raw.
    from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
    from app.market.twse_mis_observation import resolve_twse_mis_actual_trade
    from test_fugle_realtime_provider import _instrument
    received = datetime.fromisoformat("2026-10-22T12:55:13.295+08:00")
    event = datetime.fromisoformat("2026-10-22T12:54:25+08:00")
    message = dict(c="3105", d="20261022", t="12:54:25", z="-", v="20731", tv="-",
                   trade=dict(t="12:54:15", z="486.5000", v=1, ft=20))
    snapshot = canonical_snapshot_from_twse_mis(instrument=_instrument("3105", "TPEX"),
        message=message, session="regular", fetched_at=received)
    assert snapshot.quote.last_trade_price is None
    assert snapshot.quote.cumulative_quantity.value == 20731000
    assert snapshot.quote.lineage.event_at == event
    assert (received - event).total_seconds() == 48.295
    evidence = resolve_twse_mis_actual_trade(expected_trade_date=event.date(),
        observation_trade_date=event.date(), provider_event_time=event, trial_status=None,
        last_trade_price=None, last_trade_volume_lots=None, cumulative_volume_lots=20731)
    assert evidence["reason_code"] == "ACTUAL_TRADE_PRICE_MISSING"


def minute_payload(minute, value, *, qualified=True):
    payload = market_summary_payload(date(2026, 10, 22), hour=13, minute=minute,
                                     twse_trade_value=value - 100, tpex_trade_value=100)
    for item in payload["indices"]:
        qualified_estimate(item["breadth"])
        if not qualified:
            item["breadth"]["acquisition_diagnostics"]["acquisition_complete"] = False
            item["breadth"]["coverage_reason_counts"] = dict(advance=10, decline=10, unchanged=10, valid_no_trade=10, unknown=60)
    return payload


@pytest.mark.parametrize("current_ok,previous_ok", [(False, False), (False, True), (True, False), (True, True)])
def test_one_minute_delta_requires_both_qualified_endpoints(current_ok, previous_ok):
    with make_session() as session:
        persist_taiwan_market_minute_state(session, payload=minute_payload(29, 602713807, qualified=previous_ok))
        persist_taiwan_market_minute_state(session, payload=minute_payload(30, 234294363321, qualified=current_ok))
        session.commit()
        before = [(r.id, r.component_sources_json, r.cumulative_trade_value) for r in session.query(TaiwanMarketMinuteState).all()]
        session.connection().exec_driver_sql("PRAGMA query_only=ON")
        result = read_taiwan_market_volume_state(session)
        expected = 233691649514 if current_ok and previous_ok else None
        assert result["one_minute_trade_value_change"] == expected
        assert result["field_status"]["one_minute_trade_value_change"]["status"] == ("available" if expected is not None else "missing")
        assert compose_taiwan_market_volume_state(result, breadth=None)["one_minute_trade_value_change"] == expected
        from app.market.schemas import TaiwanMarketVolumeStateRead
        typed = TaiwanMarketVolumeStateRead.model_validate(result).model_dump(mode="json")
        assert compose_taiwan_market_volume_state(typed, breadth=None)["one_minute_trade_value_change"] == expected
        assert before == [(r.id, r.component_sources_json, r.cumulative_trade_value) for r in session.query(TaiwanMarketMinuteState).all()]


@pytest.mark.parametrize("defect", ["metadata", "gap", "scope", "source", "semantics", "authority", "lineage", "event_minute", "decrease", "venue", "date", "lineage_provider", "lineage_source"])
def test_one_minute_delta_fails_closed_on_missing_or_incomparable_evidence(defect):
    with make_session() as session:
        persist_taiwan_market_minute_state(session, payload=minute_payload(28 if defect == "gap" else 29, 1000))
        persist_taiwan_market_minute_state(session, payload=minute_payload(30, 2000))
        previous = session.query(TaiwanMarketMinuteState).filter_by(market="TWSE").order_by(TaiwanMarketMinuteState.minute_at).first()
        if defect == "metadata":
            components = json.loads(previous.component_sources_json)
            for component in components:
                component.pop("trade_value_evidence", None)
            previous.component_sources_json = json.dumps(components)
        elif defect in {"scope", "source", "semantics", "authority", "lineage", "date", "decrease"}:
            field, value = {"scope": ("breadth_scope", "other"), "source": ("source", "other"),
                "semantics": ("trade_value_semantics", "other"), "authority": ("trade_value_is_estimate", False),
                "lineage": ("lineage_complete", False), "date": ("trade_date", date(2026, 10, 21)),
                "decrease": ("cumulative_trade_value", 3000)}[defect]
            setattr(previous, field, value)
        elif defect in {"event_minute", "lineage_provider", "lineage_source"}:
            components = json.loads(previous.component_sources_json)
            for component in components:
                key = "event_at" if defect == "event_minute" else defect.removeprefix("lineage_")
                component[key] = "2026-10-22T13:28:00+08:00" if key == "event_at" else "different_origin"
            previous.component_sources_json = json.dumps(components)
        elif defect == "venue":
            session.delete(previous)
        session.commit()
        session.connection().exec_driver_sql("PRAGMA query_only=ON")
        result = read_taiwan_market_volume_state(session)
        assert result["one_minute_trade_value_change"] is None
        assert result["field_status"]["one_minute_trade_value_change"]["status"] != "available"
