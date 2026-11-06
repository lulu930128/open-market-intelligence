"""Saved breadth companions feed the existing single-stock auction owner."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest
from sqlalchemy import event

from app.db.models import RawFetchResult, TaiwanCurrentBreadthSnapshot
from app.market.providers.tw_current_market import CurrentBreadthAdapter
from app.market.tw_current_market_acquisition import TaiwanCurrentBreadthAcquisitionExecutor
from app.market.tw_current_market_capabilities import TW_CURRENT_BREADTH_CAPABILITY_ID, TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR
from app.market.tw_current_market_platform import refresh_taiwan_current_breadth
from app.market.realtime_snapshot_repository import TaiwanAuctionRepository
from app.market.taiwan_realtime_platform import read_taiwan_auction
from app.market_data.contracts import AuctionType, InstrumentKey, QuantityUnit
from test_tw_current_market_platform import _binding, _payload_reader
from test_tw_realtime_persistence import db  # noqa: F401

TZ = timezone(timedelta(hours=8))
EVENT = datetime(2026, 11, 6, 8, 35, 45, tzinfo=TZ)
RECEIVED = EVENT + timedelta(seconds=8)
FETCHED = RECEIVED + timedelta(seconds=3)
NOW = EVENT.replace(minute=36, second=0)
INSTRUMENT = InstrumentKey(market="TW", symbol="2330", venue="TWSE", instrument_type="stock")


def seed(db, **overrides):
    item = dict(code="2330", market="TWSE", trade_date=EVENT.date().isoformat(),
        as_of=EVENT.isoformat(), observation_received_at=RECEIVED.isoformat(),
        indicative_match_available=True, indicative_price_source="pz",
        indicative_match_price=2020, indicative_match_volume_lots=3040,
        has_actual_trade=False, current_price=None)
    item.update(overrides)
    payload = dict(snapshot_as_of=EVENT.isoformat(), trade_date=EVENT.date().isoformat(),
        universe_count=1, advance_count=0, decline_count=0, unchanged_count=0,
        received_unclassified_count=1, not_received_count=0, component_stock_rows=[item])
    adapter = CurrentBreadthAdapter(
        _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        _payload_reader(payload, [], "mis-breadth"), clock=lambda: FETCHED)
    refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=FETCHED,
        descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
        acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
    return db.query(TaiwanCurrentBreadthSnapshot).one()


def read(db, **overrides):
    args = dict(max_candidates=2, auction_type=AuctionType.OPENING, as_of=NOW)
    args.update(overrides)
    return TaiwanAuctionRepository(db).load_candidates(INSTRUMENT, **args)


def test_saved_auction_keeps_receipt_clocks_units_and_gateway_semantics_without_writes(db):
    snapshot = seed(db)
    statements = []
    def trace(_conn, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", trace)
    try:
        result = read(db)[0]
        gateway = read_taiwan_auction(db, stock_id="2330", requested_at=NOW)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", trace)
    auction = result.observation
    assert auction is not None and auction.indicative_price == 2020
    assert auction.provisional and auction.state.value == "indicative"
    assert auction.indicative_quantity.value == 3040000
    assert auction.indicative_quantity.unit is QuantityUnit.SHARE
    assert auction.indicative_quantity.original_unit is QuantityUnit.BOARD_LOT
    assert auction.lineage.event_at == EVENT and auction.lineage.received_at == RECEIVED
    assert auction.lineage.fetched_at == FETCHED
    assert auction.lineage.source == "twse_mis_live_breadth"
    assert result.storage_row_id == snapshot.id
    assert gateway.resolved is not None
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)


@pytest.mark.parametrize("overrides", [
    {"indicative_match_available": False}, {"indicative_match_price": None},
    {"indicative_match_price": -1}, {"indicative_match_price": "NaN"},
    {"indicative_match_volume_lots": -1}, {"indicative_price_source": "z"},
    {"as_of": "2026-11-06T08:35:45"}, {"as_of": "2026-11-06T09:00:00+08:00"},
    {"observation_received_at": "2026-11-06T08:36:01+08:00"},
    {"trade_date": "2026-11-05"}, {"code": "2317"}, {"market": "TPEX"},
])
def test_invalid_companion_never_becomes_an_auction(db, overrides):
    seed(db, **overrides)
    assert all(item.observation is None for item in read(db))


@pytest.mark.parametrize("corruption", ["hash", "parser", "receipt", "future_receipt", "duplicate"])
def test_receipt_integrity_and_visibility_are_required(db, corruption):
    row = seed(db)
    raw = db.get(RawFetchResult, row.raw_result_id)
    if corruption == "hash": raw.content_hash = "tampered"
    if corruption == "parser": raw.parser_version = "unverified.v0"
    if corruption == "receipt": raw.status_code = 503
    if corruption == "future_receipt": raw.fetched_at = NOW + timedelta(seconds=1)
    if corruption == "duplicate":
        payload = json.loads(raw.raw_text)
        payload["component_stock_rows"] *= 2
        raw.raw_text = json.dumps(payload)
        raw.content_hash = sha256(raw.raw_text.encode()).hexdigest()
    db.commit()
    assert all(item.observation is None for item in read(db))


def test_opening_history_does_not_cross_cutoff_day_or_auction_type(db):
    seed(db)
    for overrides in ({"as_of": RECEIVED}, {"trade_date": EVENT.date()-timedelta(days=1)},
                      {"auction_type": AuctionType.CLOSING}, {"auction_type": AuctionType.INTRADAY}):
        assert all(item.observation is None for item in read(db, **overrides))
    assert read(db, as_of=NOW.replace(hour=10))[0].observation.lineage.event_at == EVENT


def test_http_history_forwards_typed_opening_and_keeps_closing_default(db):
    from app.routers.market import get_stock_auction_history
    seed(db)
    opening = get_stock_auction_history(stock_id="2330", trade_date=EVENT.date(),
        as_of=NOW, max_candidates=2, db=db, auction_type=AuctionType.OPENING)
    assert opening["capture_status"] == "captured"
    assert opening["price_semantics"] == "indicative"
    assert opening["decision_usable"] is False
    closing = get_stock_auction_history(stock_id="2330", trade_date=EVENT.date(),
        as_of=NOW, max_candidates=2, db=db)
    assert closing["auction_type"] == "closing" and closing["capture_status"] == "missing"
