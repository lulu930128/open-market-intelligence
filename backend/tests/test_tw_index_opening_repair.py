"""Opening qualification and repair retain exact raw evidence across readback."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from app.db.models import MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_materializer import materialize_index_minute_candidates
from app.market.tw_bar_materialization_transaction import TaiwanBarMaterializationTransaction
from app.market.tw_bar_service import TaiwanBarService
from test_tw_index_bar_materialization import _db, _event, TRADE_DATE


def at(second=0):
    return datetime(2026, 9, 1, 9, 0, second, tzinfo=TAIWAN_TZ)


def opening_receipt(db, *, index_id="TAIEX", value=38915.76, **updates):
    _event(db, provider="fugle_marketdata", source_name="fugle_http_index_quote",
        event_at=at(5), close=value, index_id=index_id)
    db.flush()
    raw = db.query(RawFetchResult).order_by(RawFetchResult.id.desc()).first()
    payload = {"symbol": "IX0001", "exchange": "TWSE", "market": "TSE", "type": "INDEX",
        "date": str(TRADE_DATE), "openPrice": value,
        "openTime": int(at(5).timestamp() * 1000000),
        "closeTime": int(at(5).timestamp() * 1000000), **updates}
    raw.raw_text = json.dumps(payload)
    raw.content_hash = sha256(raw.raw_text.encode()).hexdigest()
    raw.status_code = 200
    return raw


def stream(db, second, value):
    _event(db, provider="fugle_marketdata", source_name="fugle_indices_stream",
        event_at=at(second), close=value)


def candidates(db, as_of=None):
    db.commit()
    return materialize_index_minute_candidates(db, index_id="TAIEX", trade_date=TRADE_DATE,
        as_of=as_of or at() + timedelta(minutes=2))


def read_bars(db):
    db.expire_all()
    return TaiwanBarService(db).read_bars(instrument_id="TAIEX", interval="1m",
        from_time=at(), to_time=at() + timedelta(minutes=2), requested_at=at() + timedelta(minutes=2))


def test_corrects_open_and_high_keeps_receipts_and_rejects_forged_proof():
    db, engine = _db()
    try:
        stream(db, 0, 41574.72)
        baseline_id = db.query(RawFetchResult.id).order_by(RawFetchResult.id.desc()).first()[0]
        opening = opening_receipt(db)
        stream(db, 10, 38577.32)
        stream(db, 55, 37837.05)
        batch = candidates(db)
        candidate = next(c for c in batch.candidates if c.observation.lineage.source == "fugle_indices_stream")
        assert candidate.observation.open_price == candidate.observation.high_price == Decimal("38915.76")
        assert candidate.observation.close_price == candidate.observation.low_price == Decimal("37837.05")
        assert candidate.component_raw_result_ids[0] == opening.id
        assert baseline_id not in candidate.component_raw_result_ids
        owner = TaiwanBarMaterializationTransaction(db)
        owner.persist_materialized_bars((candidate,))
        row = db.query(MarketIntradayBar).one()
        original_id = row.id
        # Simulate the previously materialized bad OHLC, then repair through owner.
        row.open_price = row.high_price = 41574.72
        db.commit()
        assert owner.persist_materialized_bars((candidate,)).observations_written == 1
        assert db.query(MarketIntradayBar).one().id == original_id
        assert owner.persist_materialized_bars((candidate,)).observations_unchanged == 1
        bars = read_bars(db).bars
        assert len(bars) == 1
        assert bars[0].open_price == bars[0].high_price == Decimal("38915.76")
        assert len(bars[0].lineage.component_content_hashes) == 3
        assert db.query(RawFetchResult).count() == 4
        with pytest.raises(ValueError, match="opening evidence mismatch"):
            owner.persist_materialized_bars((replace(candidate, opening_raw_result_id=baseline_id),))
        lineage = db.query(MarketIntradayBarLineage).one()
        lineage.component_raw_result_ids_json = json.dumps([baseline_id, *candidate.component_raw_result_ids[1:]])
        db.commit()
        assert not read_bars(db).bars
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("updates", [
    {"symbol": "IX0043"}, {"date": "2026-08-31"}, {"openPrice": 0},
    {"openTime": int(at().timestamp() * 1000000) - 1000000},
    {"openTime": int(at(10).timestamp() * 1000000)}, {"openTime": None},
])
def test_unqualified_opening_does_not_promote_nine_oclock_reference(updates):
    db, engine = _db()
    try:
        stream(db, 0, 41574.72)
        opening_receipt(db, **updates)
        stream(db, 55, 37837.05)
        batch = candidates(db)
        assert not any(c.observation.lineage.source == "fugle_indices_stream" for c in batch.candidates)
        assert "TW_INDEX_OPENING_REFERENCE_PENDING" in batch.limitations
    finally:
        db.close()
        engine.dispose()


def test_equal_previous_close_can_be_legitimate_open_and_future_receipt_not_used():
    db, engine = _db()
    try:
        stream(db, 0, 45000)
        raw = opening_receipt(db, value=45000)
        stream(db, 10, 45000)
        batch = candidates(db)
        candidate = next(c for c in batch.candidates if c.opening_raw_result_id == raw.id)
        assert candidate.observation.open_price == 45000
        # An earlier replay cannot consume a receipt from five seconds later.
        early = candidates(db, as_of=at(1))
        assert not early.candidates
    finally:
        db.close()
        engine.dispose()
