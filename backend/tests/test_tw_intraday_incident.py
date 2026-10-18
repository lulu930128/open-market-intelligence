"""Offline incident regressions; source/fixture proof is not live acceptance."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.db.models import StockMaster, TaiwanMarketMinuteState
from app.market import quote_depth
from app.market.providers import twse_mis_current_breadth as provider
from app.market.twse_mis_observation import resolve_twse_mis_observation
from test_tw_breadth_convergence import NOW, message
from test_tw_breadth_semantics import acquire
from test_tw_current_market_platform import _db


@pytest.mark.parametrize("present,volume,event,trial,phase,reason,instrument", [
    (False, None, None, None, "regular", "NO_SNAPSHOT", "unknown"),
    (False, None, None, None, "preopen", "NO_SNAPSHOT", "unknown"),
    (True, None, NOW, "0", "regular", "ACTUAL_TRADE_EVIDENCE_MISSING", "unknown"),
    (True, 0, NOW, "0", "regular", "AWAITING_FIRST_TRADE", "awaiting_first_trade"),
    (True, 5, NOW, "0", "regular", "ACTUAL_TRADE_PRICE_MISSING", "regular_traded"),
    (True, 0, NOW.replace(hour=8, minute=59), "1", "preopen", "AUCTION_INDICATIVE_OBSERVED", "preopen_auction"),
    (True, 0, NOW.replace(hour=8, minute=59), "1", "regular", "PROVIDER_EVENT_PRECEDES_OPEN", "preopen_auction"),
])
def test_observation_owner_separates_absence_zero_trade_and_auction(present, volume, event, trial, phase, reason, instrument):
    result = resolve_twse_mis_observation(
        request_now=NOW, market_calendar_phase=phase, legacy_clock_phase="regular_live",
        provider_event_time=event, trial_status=trial, indicative_price=105 if trial == "1" else None,
        indicative_volume_lots=3 if trial == "1" else None, last_trade_price=None,
        cumulative_volume_lots=volume, observation_available=present,
    )
    assert (result["reason_code"], result["instrument_phase"]) == (reason, instrument)
    assert result["actual_trade_price_available"] is False


def test_empty_snapshot_public_and_ai_projection_remain_unknown():
    from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
    db, engine = _db()
    try:
        db.add(StockMaster(stock_id="2881", stock_name="test", market="TWSE", instrument_type="stock"))
        db.commit()
        public = quote_depth.read_taiwan_quote_evidence_projection(db=db, stock_id="2881", requested_at=NOW)
        assert public["observation_reason_code"] == "NO_SNAPSHOT"
        assert public["instrument_phase"] == "unknown"
        assert not public.get("headline_decision_usable", False)
        compact = _compact_quote_snapshot(latest_daily=None, quote_depth=public, quote_error=None)
        assert compact["observation_reason_code"] == "NO_SNAPSHOT"
        assert compact["price_decision_usable"] is False
        from app.ai.realtime_contract import classify_observation
        assert not classify_observation(compact, market="TW", realtime_policy="require_live", now=NOW)["execution_grade_usable"]
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("volume", ["5", "6", "-"])
def test_old_price_never_uses_new_receipt_clock_or_becomes_decision_grade(volume):
    from app.market.public_quote_repository import read_current_stock_price_states
    db, engine = _db()
    try:
        db.add(StockMaster(stock_id="2330", stock_name="test", market="TWSE", instrument_type="stock"))
        db.commit()
        acquire(db, provider._build_payload("TWSE", ["2330"], [message()], 0))
        states = read_current_stock_price_states(db, venue="TWSE", requested_at=NOW)
        original = states["2330"]
        later = NOW + timedelta(minutes=20)
        payload = provider._build_payload("TWSE", ["2330"], [message(t="10:35:00", z="-", v=volume)], 0, prior_states=states)
        assert payload["price_states"]["2330"]["current_price_verified"] is (volume == "5")
        row = payload["component_stock_rows"][0]
        if volume == "5":
            assert row["price_source"] == "session_cache"
            assert row["price_as_of"] == NOW
            assert row["price_lineage"] == original["lineage"]
        else:
            assert row["current_price"] is None
            assert payload["classified_count"] == 0
        acquire(db, payload, later)
        retained = read_current_stock_price_states(db, venue="TWSE", requested_at=later)["2330"]
        assert retained["price_as_of"] == original["price_as_of"]
        assert retained["lineage"] == original["lineage"]
        public = quote_depth.read_taiwan_quote_evidence_projection(db=db, stock_id="2330", requested_at=later)
        assert public["last_trade_price"] == float(original["price"])
        assert public["last_trade_time"] == NOW
        assert public["freshness"]["is_stale"] is True
        assert public["headline_decision_usable"] is False
        from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
        from app.ai.realtime_contract import classify_observation
        compact = _compact_quote_snapshot(latest_daily=None, quote_depth=public, quote_error=None)
        assert compact["price_decision_usable"] is False
        assert classify_observation(compact, market="TW", realtime_policy="require_live", now=later)["execution_grade_usable"] is False
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("change", [
    {"headline_decision_usable": False},
    {"session_phase": "regular_live"},
    {"freshness": {"status": "stale", "is_stale": True}},
    {"official_close_status": "pending"},
    {"data_core_components": {"quote.official_close": {"decision_usable": False}}},
    {"last_trade_price": float("nan")},
])
def test_completed_close_compatibility_cannot_override_explicit_denial(change):
    from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
    payload = {
        "session_phase": "post_close_snapshot", "last_trade_price": 100,
        "price_available": True, "official_close_available": True,
        "official_close_status": "confirmed",
        "freshness": {"status": "official_close", "is_stale": False},
        **change,
    }
    assert not _compact_quote_snapshot(latest_daily=None, quote_depth=payload, quote_error=None)["price_decision_usable"]


@pytest.mark.parametrize("job,fail_stock,expected_count", [("index", False, 2), ("breadth", True, 0), ("breadth", False, 2)])
def test_scheduler_commits_index_and_atomically_publishes_breadth(monkeypatch, job, fail_stock, expected_count):
    from app.jobs import scheduler
    from test_taiwan_market_state import market_summary_payload
    db, engine = _db()
    payload = market_summary_payload(NOW.date(), hour=10, minute=15, twse_trade_value=100, tpex_trade_value=100)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "is_taiwan_index_live_refresh_window", lambda _: True)
    monkeypatch.setattr(scheduler, "refresh_current_market_breadth_snapshots", lambda **_: payload)
    monkeypatch.setattr(scheduler, "refresh_current_market_index_snapshots", lambda **_: payload)
    monkeypatch.setattr(scheduler, "materialize_index_minute_candidates", lambda *a, **k: SimpleNamespace(candidates=[]))
    monkeypatch.setattr(scheduler, "get_cached_current_breadth_stock_rows", lambda: [])
    monkeypatch.setattr(scheduler, "attach_current_market_lineage_to_stock_rows", lambda *a, **k: [])
    if fail_stock:
        def fail(*args, **kwargs):
            # Force pending market rows to SQLite before the failure. Rollback
            # must still remove them, not merely discard unflushed ORM objects.
            db.flush()
            raise RuntimeError("fixture stock persistence failed")
        monkeypatch.setattr(scheduler, "persist_taiwan_intraday_stock_states", fail)
    try:
        getattr(scheduler, f"collect_taiwan_market_{job}_summary")()
        with Session(engine) as reread:
            assert reread.query(TaiwanMarketMinuteState).count() == expected_count
    finally:
        db.close()
        engine.dispose()
