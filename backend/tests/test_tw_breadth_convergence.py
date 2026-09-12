from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.market.tw_breadth_projection import project_breadth_coverage
from app.market.providers.twse_mis_current_breadth import _build_payload, _classify_message
from app.market.providers.tw_current_market import CurrentBreadthAdapter, CurrentMarketProviderPayload
from app.market.tw_current_market_acquisition import TaiwanCurrentBreadthAcquisitionExecutor
from app.market.tw_current_market_operations import read_breadth_price_states
from app.market.tw_current_market_platform import refresh_taiwan_current_breadth, read_taiwan_current_breadth, project_taiwan_current_breadth
from app.market.tw_current_market_capabilities import TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR, TW_CURRENT_BREADTH_CAPABILITY_ID
from app.market_data.contracts import BreadthLimitObservation
from test_tw_current_market_platform import _db, _binding

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 15, tzinfo=TZ)


def message(code="2330", **values):
    return {"c": code, "d": "20260826", "t": "10:15:00", "z": "110", "y": "100",
            "v": "5", "tv": "1", "ts": "0", "u": "110", "w": "90", **values}


def test_summary_detail_and_ratios_reconcile_independently():
    raw = dict(advance_count=263, decline_count=657, unchanged_count=75, total_count=1080,
               not_received_count=3, received_unclassified_count=82,
               coverage_reason_counts=dict(advance=263, decline=657, unchanged=75,
                                           mapping_error=79, valid_no_trade=3, provider_missing=3))
    result = project_breadth_coverage(raw)
    assert sum(result["classification_summary"].values()) == 1080
    assert sum(result["classification_reason_counts"].values()) == 1080
    assert result["received_coverage_ratio"] == 1077 / 1080
    assert result["classified_coverage_ratio"] == 995 / 1080
    with pytest.raises(ValueError):
        project_breadth_coverage({**raw, "not_received_count": 4})
    with pytest.raises(ValueError):
        project_breadth_coverage({**raw, "coverage_reason_counts": {"mapping_error": 1080}})
    empty = project_breadth_coverage(dict(total_count=0, missing_count=0))
    assert empty["received_coverage_ratio"] is None
    assert empty["classified_coverage_ratio"] is None


def test_limit_unknown_is_not_zero_and_duplicates_are_not_counted():
    payload = _build_payload("TWSE", ["2330", "2454", "3711"],
                             [message(), message(t="10:14:00", z="100"), message("2454", u="-", w="-")], 0)
    assert payload["classified_count"] == 2
    limits = BreadthLimitObservation.model_validate(payload["limits"])
    assert limits.up.observed_count == 1
    assert limits.up.evaluated_count == 1
    assert limits.up.unknown_count == 2
    assert payload["limit_up_count"] is None
    full = _build_payload("TWSE", ["2330"], [message(z="100")], 0)
    assert full["limit_up_count"] == 0
    assert full["limit_down_count"] == 0
    with pytest.raises(ValueError):
        BreadthLimitObservation.model_validate({"universe_count": 1, "up": {"observed_count": 2, "evaluated_count": 1, "unknown_count": 0}, "down": full["limits"]["down"]})


def test_limit_does_not_require_direction_reference_and_mapping_is_explained():
    payload = _build_payload("TWSE", ["2330", "2454"], [message(y="-"), message("2454", z="-")], 0)
    assert payload["advance_count"] == 0
    assert payload["limits"]["up"]["observed_count"] == 1
    assert payload["classification_diagnostics"]["reference_price_missing"] == 1
    assert sum(payload["classification_diagnostics"].values()) == payload["coverage_reason_counts"]["mapping_error"] == 2


def test_future_and_previous_day_states_cannot_supply_a_price():
    state = dict(trade_date=NOW.date(), price=110, price_as_of=NOW + timedelta(minutes=5), has_actual_trade=True)
    assert _classify_message(message(z="-"), "TWSE", cached_state=state) is None
    state.update(trade_date=(NOW - timedelta(days=1)).date(), price_as_of=NOW - timedelta(days=1))
    assert _classify_message(message(z="-"), "TWSE", cached_state=state)["current_price"] is None


def test_persisted_state_survives_new_reader_and_preserves_original_receipt():
    db, engine = _db()
    def acquire(payload, now):
        adapter = CurrentBreadthAdapter(
            _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
            lambda *_: CurrentMarketProviderPayload(payload=payload, status="available", url="https://example.test", external_calls=0),
            clock=lambda: now,
        )
        return refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=now,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
            acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
    try:
        first = _build_payload("TWSE", ["2330", "2454"], [message(), message("2454", z="100")], 0)
        acquire(first, NOW)
        db.expire_all()
        states = read_breadth_price_states(db, venue="TWSE", requested_at=NOW + timedelta(minutes=5))
        original = states["2330"]["lineage"]["raw_receipt_id"]
        assert original
        from app.market.public_quote_platform import read_taiwan_public_last_trade_quote
        from app.db.models import StockMaster
        if db.query(StockMaster).filter(StockMaster.stock_id == "2330").first() is None:
            db.add(StockMaster(stock_id="2330", stock_name="TSMC", market="TWSE", instrument_type="stock"))
            db.commit()
        quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
        assert quote.resolved.quote is not None, quote.resolved.model_dump()
        assert quote.resolved.quote.last_trade_price == states["2330"]["price"]
        assert quote.resolved.quote.lineage.raw_receipt_id == original
        from app.market.quote_depth import read_taiwan_quote_evidence_projection
        public_quote = read_taiwan_quote_evidence_projection(db=db, stock_id="2330", requested_at=NOW)
        assert public_quote["last_trade_price"] == float(states["2330"]["price"])
        assert public_quote["headline_price"] == float(states["2330"]["price"])
        next_payload = _build_payload("TWSE", ["2330", "2454"], [message(z="-", tv="0", t="10:20:00")], 0, prior_states=states)
        acquire(next_payload, NOW + timedelta(minutes=5))
        recovered = read_breadth_price_states(db, venue="TWSE", requested_at=NOW + timedelta(minutes=6))
        assert recovered["2330"]["price_as_of"] == NOW
        assert recovered["2330"]["lineage"]["raw_receipt_id"] == original
        assert "2454" in recovered  # an absent quote must not erase same-day state
        assert read_breadth_price_states(db, venue="TWSE", requested_at=NOW + timedelta(days=1)) == {}
        writes = []
        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        projected = project_taiwan_current_breadth(read_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW + timedelta(minutes=5)))
        assert projected["limits"]["up"]["unknown_count"] == 1
        assert projected["limit_up_count"] is None
        assert not writes
    finally:
        db.close()
        engine.dispose()


def test_completed_breadth_legacy_entry_cannot_fetch_or_estimate_limits():
    from app.market import indices
    db, engine = _db()
    try:
        with patch.object(indices, "_fetch_market_quote_breadth", side_effect=AssertionError("provider IO")):
            assert indices._resolve_market_breadth(db, "TPEX", target_trade_date=NOW.date()) is None
        assert indices._market_quote_breadth_from_rows(
            market="TPEX", rows=[{"code": "2330", "close": 110, "change": 10, "date": "20260826", "value": 10}],
            code_key="code", close_key="close", change_key="change", date_key="date", trade_value_key="value", source="test",
        )["limit_up_count"] is None
    finally:
        db.close()
        engine.dispose()


def test_official_shadow_lane_never_replaces_different_scope():
    from app.market.tw_current_market_platform import read_taiwan_breadth_lanes
    db, engine = _db()
    try:
        with patch("app.market.official_breadth_platform.read_taiwan_official_breadth", side_effect=AssertionError("not needed intraday")):
            assert read_taiwan_breadth_lanes(db, venue="TWSE", requested_at=NOW)["status"] == "not_applicable"
        lane = read_taiwan_breadth_lanes(db, venue="TWSE", requested_at=NOW.replace(hour=18))
        assert lane["selected_lane"] == "current_registered"
        assert lane["reason"] == "DISTINCT_UNIVERSE_SCOPES"
        assert lane["official_daily"]["status"] == "missing"
    finally:
        db.close()
        engine.dispose()
