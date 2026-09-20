from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import event

from app.db.models import StockMaster, TaiwanIntradayStockState
from app.market.public_quote_platform import acquire_taiwan_session_close, read_taiwan_session_closes, read_taiwan_session_close, project_taiwan_session_close
from app.market.tw_intraday_state import build_tw_intraday_screening_snapshot, build_tw_intraday_group_snapshots, persist_taiwan_intraday_stock_states
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from test_tw_public_quote_platform import db, _records, _raw_with_message_updates, _executor
import test_tw_intraday_market_capabilities as fixtures
from test_tw_breadth_convergence import (
    _build_payload, message, CurrentBreadthAdapter, CurrentMarketProviderPayload,
    TaiwanCurrentBreadthAcquisitionExecutor, TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,
    TW_CURRENT_BREADTH_CAPABILITY_ID, _binding,
)
from app.market.tw_current_market_platform import refresh_taiwan_current_breadth
from app.market.tw_current_market_repository import read_breadth_price_states

NOW = datetime.fromisoformat("2026-08-25T13:34:00+08:00")


def seed_close(db, symbol, price):
    raw = _raw_with_message_updates(_records()["2330"], c=symbol, z=str(price), y="100", h=str(price), l="99", o="100", v="20")
    acquire_taiwan_session_close(db, stock_id=symbol, requested_at=NOW, acquisition=_executor(raw, NOW))


def test_close_overlay_replaces_old_price_volume_and_supports_missing_rolling_rows(db):
    stocks = db.query(StockMaster).filter(StockMaster.market == "TWSE").all()
    stocks[0].industry = stocks[1].industry = "半導體業"
    db.add(StockMaster(stock_id="2454", stock_name="2454", market="TWSE", instrument_type="stock", industry="半導體業"))
    db.commit()
    old = NOW.replace(hour=12)
    case = fixtures.TaiwanIntradayMarketCapabilityTests()
    persist_taiwan_intraday_stock_states(db, rows=[case._stock_state_row("2330", "TWSE", 180, 100, old)], now=old)
    for symbol, price in (("2330", 101), ("3711", 103), ("2454", 102)):
        seed_close(db, symbol, price)
    before = db.query(TaiwanIntradayStockState).one().current_price
    snapshot = build_tw_intraday_screening_snapshot(db, generated_at=NOW)
    assert [row["stock_id"] for row in snapshot["rows"]] == ["3711", "2454", "2330"]
    assert snapshot["coverage"]["universe_count"] == 4
    assert snapshot["coverage"]["ranking_eligible_count"] == 3
    assert snapshot["rows"][-1]["current_price"] == 101
    assert snapshot["rows"][-1]["cumulative_volume_lots"] == 20
    assert snapshot["rows"][-1]["estimated_trade_value"] == 2020000
    assert snapshot["rows"][-1]["finalization"] == "session_final"
    assert db.query(TaiwanIntradayStockState).one().current_price == before
    assert not db.dirty
    groups = build_tw_intraday_group_snapshots(db, generated_at=NOW, include_watchlist_groups=False)["hot_groups"]
    assert groups["status"] == "partial"
    assert groups["facts_usable"] is True
    assert groups["decision_usable"] is False
    assert groups["is_complete"] is False
    assert abs(groups["groups"][0]["mean_return_pct"] - 2) < 1e-8


def test_batch_resolver_matches_single_and_query_count_does_not_scale_per_symbol(db):
    seed_close(db, "2330", 101)
    instrument = InstrumentKey(market=Market.TW, symbol="2330", venue="TWSE", instrument_type=InstrumentType.STOCK)
    single = project_taiwan_session_close(read_taiwan_session_close(db, stock_id="2330", requested_at=NOW))
    counts = []
    for count in (1, 40):
        statements = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            inputs = (instrument, *(instrument.model_copy(update={"symbol": str(3000+i)}) for i in range(count-1)))
            result = read_taiwan_session_closes(db, instruments=inputs, requested_at=NOW)
            assert project_taiwan_session_close(result["2330"]) == single
            assert all(not project_taiwan_session_close(value)["available"] for key, value in result.items() if key != "2330")
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)
        counts.append(len(statements))
    assert counts[1] <= counts[0] + 1
    assert counts[1] <= 5
    early = read_taiwan_session_closes(db, instruments=(instrument,), requested_at=NOW.replace(minute=32))
    assert project_taiwan_session_close(early["2330"])["available"] is False


def test_later_out_of_window_trade_cannot_hide_qualified_close(db):
    seed_close(db, "2330", 101)
    later = NOW.replace(hour=13, minute=40)
    raw = _raw_with_message_updates(_records()["2330"], c="2330", z="110", t="13:40:00", y="100")
    acquire_taiwan_session_close(db, stock_id="2330", requested_at=later, acquisition=_executor(raw, later))
    instrument = InstrumentKey(market=Market.TW, symbol="2330", venue="TWSE", instrument_type=InstrumentType.STOCK)
    single = project_taiwan_session_close(read_taiwan_session_close(db, stock_id="2330", requested_at=later))
    batch = project_taiwan_session_close(read_taiwan_session_closes(db, instruments=(instrument,), requested_at=later)["2330"])
    assert single["available"] is True and single["price"] == 101
    assert batch == single


FRIDAY = datetime.fromisoformat("2026-08-28T13:34:00+08:00")


def seed_breadth_closes(db, *, received_at=FRIDAY, price="101", quote_time="13:30:00"):
    symbols = ["2330", "3711", "2454"]
    payload = _build_payload("TWSE", symbols, [
        message(code, d="20260828", t=quote_time, z=price, y="100", v="20") for code in symbols
    ], 0)
    adapter = CurrentBreadthAdapter(
        _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        lambda *_: CurrentMarketProviderPayload(payload=payload, status="available", url="https://example.test", external_calls=0),
        clock=lambda: received_at,
    )
    refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=received_at,
        descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
        acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))


@pytest.mark.parametrize("elapsed_days", [1, 2])
def test_weekend_ranking_uses_completed_breadth_date_without_writes(db, elapsed_days):
    for stock in db.query(StockMaster).filter(StockMaster.market == "TWSE"):
        stock.industry = "半導體業"
    db.add(StockMaster(stock_id="2454", stock_name="2454", market="TWSE", instrument_type="stock", industry="半導體業"))
    db.commit()
    seed_breadth_closes(db)
    weekend = FRIDAY + timedelta(days=elapsed_days)
    instrument = InstrumentKey(market=Market.TW, symbol="2330", venue="TWSE", instrument_type=InstrumentType.STOCK)
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        friday = build_tw_intraday_screening_snapshot(db, generated_at=FRIDAY)
        later = build_tw_intraday_screening_snapshot(db, generated_at=weekend)
        assert friday["coverage"]["ranking_eligible_count"] == 3
        assert later["coverage"]["ranking_eligible_count"] == 3
        assert later["coverage"]["universe_count"] == friday["coverage"]["universe_count"] == 4
        assert [(r["stock_id"], r["current_price"], r["cumulative_volume_lots"]) for r in later["rows"]] == [
            (r["stock_id"], r["current_price"], r["cumulative_volume_lots"]) for r in friday["rows"]]
        single = project_taiwan_session_close(read_taiwan_session_close(db, stock_id="2330", requested_at=weekend))
        batch = project_taiwan_session_close(read_taiwan_session_closes(db, instruments=(instrument,), requested_at=weekend)["2330"])
        assert single["available"] is True and single["price"] == 101
        assert batch == single
        groups = build_tw_intraday_group_snapshots(db, generated_at=weekend, include_watchlist_groups=False)["hot_groups"]
        assert groups["facts_usable"] is True
        assert groups["decision_usable"] is False
        assert groups["ranking_scope"] == "qualified_sample_only"
        # Default live reads retain same-day semantics; a new completed session
        # cannot silently reuse Friday's prices either.
        assert read_breadth_price_states(db, venue="TWSE", requested_at=weekend) == {}
        monday = build_tw_intraday_screening_snapshot(db, generated_at=FRIDAY + timedelta(days=3))
        assert monday["coverage"]["ranking_eligible_count"] == 0
        assert not statements
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


def test_completed_breadth_date_does_not_change_receipt_visibility(db):
    from app.db.models import RawFetchResult, TaiwanCurrentBreadthSnapshot
    seed_breadth_closes(db)
    # This newer event was only received on Sunday. A Saturday replay must
    # still select Friday's visible snapshot instead of hiding it.
    sunday = FRIDAY + timedelta(days=2)
    seed_breadth_closes(db, received_at=FRIDAY + timedelta(minutes=1), price="102", quote_time="13:31:00")
    newest = db.query(TaiwanCurrentBreadthSnapshot).order_by(TaiwanCurrentBreadthSnapshot.id.desc()).first()
    newest.received_at = newest.fetched_at = sunday.astimezone(timezone.utc)
    raw = db.query(RawFetchResult).filter(RawFetchResult.id == newest.raw_result_id).one()
    raw.fetched_at = sunday.astimezone(timezone.utc)
    companion = json.loads(newest.price_states_json)
    for state in companion.values():
        state["lineage"]["received_at"] = state["lineage"]["fetched_at"] = sunday.isoformat()
    newest.price_states_json = json.dumps(companion)
    db.commit()
    saturday = FRIDAY + timedelta(days=1)
    states = read_breadth_price_states(db, venue="TWSE", trade_date=FRIDAY.date(), requested_at=saturday)
    assert float(states["2330"]["price"]) == 101
    assert states["2330"]["lineage"]["received_at"] == FRIDAY
    assert read_breadth_price_states(db, venue="TWSE", trade_date=FRIDAY.date(), requested_at=FRIDAY - timedelta(minutes=1)) == {}
    assert read_breadth_price_states(db, venue="TWSE", trade_date=sunday.date(), requested_at=saturday) == {}
    # A forged earlier wrapper receipt cannot bypass the raw-receipt bound.
    newest.received_at = newest.fetched_at = FRIDAY.astimezone(timezone.utc)
    db.commit()
    states = read_breadth_price_states(db, venue="TWSE", trade_date=FRIDAY.date(), requested_at=saturday)
    assert float(states["2330"]["price"]) == 101
    assert db.query(RawFetchResult).filter(RawFetchResult.id == newest.raw_result_id).one().fetched_at.date() == sunday.date()


def test_weekend_does_not_promote_an_old_actual_trade_to_session_close(db):
    seed_breadth_closes(db, quote_time="12:00:00")
    weekend = FRIDAY + timedelta(days=2)
    assert read_breadth_price_states(db, venue="TWSE", trade_date=FRIDAY.date(), requested_at=weekend)
    result = build_tw_intraday_screening_snapshot(db, generated_at=weekend)
    assert result["coverage"]["ranking_eligible_count"] == 0
