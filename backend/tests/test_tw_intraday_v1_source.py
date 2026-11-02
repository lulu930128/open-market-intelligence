"""2026-10-27 incident regression, synthetic receipts and in-memory DB only."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from threading import Event

import pytest

from app.market.providers import twse_mis_current_breadth as breadth
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.taiwan_market_state import (
    _eligible_session_trade_value, persist_taiwan_market_minute_state,
    read_taiwan_market_volume_state,
)
from app.market.trading_calendar import TAIWAN_TZ
from test_taiwan_market_state import market_summary_payload, make_session

NOW = datetime(2026, 10, 27, 9, 28, tzinfo=TAIWAN_TZ)


def message(code="2330", **values):
    return dict(dict(c=code, d="20261027", t="09:28:00", z="110", y="100",
                     v="5", tv="1", ts="0", pz="999", ps="5"), **values)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("network forbidden"))


def candidate():
    item = market_summary_payload(NOW.date(), hour=9, minute=28,
                                  twse_trade_value=1000, tpex_trade_value=200)["indices"][0]
    item.update(official=True, trade_value_is_estimate=False)
    item["breadth"].update(trade_value=500, official_flag=False, trade_value_is_estimate=True,
        trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots",
        scope="full_market_registered_stock_universe")
    return item


def select(item):
    return _eligible_session_trade_value(item=item, breadth=item["breadth"],
        trade_date=NOW.date(), finalized=False, minute_at=NOW)


def test_official_turnover_precedes_sample_without_mutating_evidence():
    item = candidate()
    original = deepcopy(item)
    selected = select(item)
    assert selected["value"] == 1000 and selected["is_estimate"] is False
    assert selected["source"] == "market_index_summary"
    assert item == original


@pytest.mark.parametrize("defect", ["date", "minute", "value_minute", "receipt", "provider", "source", "authority", "invalid_flag"])
def test_unqualified_official_does_not_override_explicit_sample(defect):
    item = candidate()
    index = item["current_data_core"]["index"]
    if defect == "date":
        item["time"] = "2026-10-26"
    elif defect == "minute":
        index["as_of"] = (NOW - timedelta(minutes=1)).isoformat()
    elif defect == "value_minute":
        item["as_of"] = (NOW - timedelta(minutes=1)).isoformat()
    elif defect in {"receipt", "provider", "source"}:
        index.pop("raw_result_id" if defect == "receipt" else defect)
    elif defect == "authority":
        item["official"] = False
    else:
        item["trade_value_is_estimate"] = "false"
    selected = select(item)
    assert selected["value"] == 500 and selected["is_estimate"] is True


@pytest.mark.parametrize("defect", ["venue", "date", "minute", "lineage"])
def test_invalid_sample_is_missing_not_an_official_substitute(defect):
    item = candidate()
    item["trade_value"] = None
    sample = item["breadth"]
    if defect == "venue":
        sample["market"] = "TPEX"
    elif defect == "date":
        sample["trade_date"] = "2026-10-26"
    elif defect == "minute":
        item["current_data_core"]["breadth"]["as_of"] = (NOW - timedelta(minutes=1)).isoformat()
    else:
        item["current_data_core"]["breadth"].pop("raw_result_id")
    assert select(item)["value"] is None


def test_official_value_independent_of_stale_breadth_and_prior_sample():
    db = make_session()
    try:
        previous = market_summary_payload(NOW.date(), hour=9, minute=27,
                                          twse_trade_value=9000, tpex_trade_value=9000)
        for item in previous["indices"]:
            item["breadth"].update(official_flag=False, trade_value_is_estimate=True,
                trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots")
        persist_taiwan_market_minute_state(db, payload=previous)
        payload = market_summary_payload(NOW.date(), hour=9, minute=28,
                                         twse_trade_value=1000, tpex_trade_value=200)
        for item in payload["indices"]:
            item.update(official=True, trade_value_is_estimate=False)
            item["breadth"].update(trade_date="2026-10-26", market_session="preopen",
                scope="full_market_registered_stock_universe", official_flag=False,
                trade_value_is_estimate=True)
            item["current_data_core"]["breadth"] = {}
        persist_taiwan_market_minute_state(db, payload=payload)
        result = read_taiwan_market_volume_state(db)
        assert result["current_cumulative_trade_value"] == 1200
        assert result["trade_value_authority_status"] == "official"
        assert result["one_minute_trade_value_change"] is None
        assert all(item["scope"] == "full_market" for item in result["markets"])
        assert all(item["advance_count"] is None and item["breadth_quality_status"] == "missing"
                   for item in result["markets"])
    finally:
        db.close()
        db.bind.dispose()


def test_breadth_rejects_wrong_session_and_missing_price_stays_unknown():
    payload = breadth._build_payload("TWSE", ["2330", "2454", "6488"],
        [message(), message("2454", z="-", pz="500"), message("6488", d="20261026")],
        0, expected_trade_date=NOW.date())
    assert payload["classified_count"] == 1
    assert payload["unknown_count"] == 2
    assert payload["trade_value_confidence"] == "low"
    assert payload["trade_value_is_estimate"] is True
    assert payload["decision_usable"] is False
    assert any("SESSION_ROWS_REJECTED" in warning for warning in payload["warnings"])


def test_auction_direction_is_provisional_and_separate_from_actual():
    payload = breadth._build_payload("TWSE", ["2330"],
        [message(t="08:59:00", ts="1", z="110", pz="120")], 0,
        expected_trade_date=NOW.date())
    assert payload["classified_count"] == 0 and payload["trade_value"] is None
    assert payload["auction_breadth"]["advance_count"] == 1
    assert payload["auction_breadth"]["is_provisional"] is True
    assert payload["auction_breadth"]["decision_usable"] is False


@pytest.mark.parametrize("second_price", ["110", "-"])
def test_sample_turnover_never_borrows_latest_receipt_minute(second_price):
    payload = breadth._build_payload("TWSE", ["2330", "2454"],
        [message(), message("2454", t="09:29:00", z=second_price)], 0)
    assert payload["trade_value"] is None
    assert "TWSE_MIS_ESTIMATE_COMPONENT_MINUTE_MISMATCH" in payload["warnings"]


@pytest.mark.parametrize("retry", [True, False])
def test_busy_single_gets_bounded_handoff_without_overlapping_transport(monkeypatch, retry):
    entered, release = Event(), Event()
    io.reset_io_slots()
    clock = [100.0]
    monkeypatch.setattr(io, "monotonic", lambda: clock[0])
    def busy(**kwargs):
        entered.set()
        assert release.wait(3)
        return "batch"
    try:
        with pytest.raises(io.AcquisitionDeadlineExceeded):
            io.bounded_fetch(busy, 0.01, exchange="tse")
        assert entered.is_set()
        for _ in range(3):
            with pytest.raises(io.AcquisitionInFlight, match="PREVIOUS_TRANSPORT"):
                io.bounded_fetch(lambda **kw: pytest.fail("overlap"), 1, interactive=True, exchange="tse")
        with pytest.raises(io.AcquisitionInFlight, match="RESET_REQUIRES_IDLE"):
            io.reset_io_slots()
        release.set()
        assert io._IN_FLIGHT["tse"].result(timeout=2) == "batch"
        with pytest.raises(io.AcquisitionInFlight, match="INTERACTIVE_HANDOFF"):
            io.bounded_fetch(lambda **kw: pytest.fail("batch overtook single"), 1, exchange="tse")
        assert io.bounded_fetch(lambda **kw: "other venue", 1, exchange="otc") == "other venue"
        if retry:
            assert io.bounded_fetch(lambda **kw: "single", 1, interactive=True, exchange="tse") == "single"
        else:
            clock[0] += io._HANDOFF_SECONDS
        assert io.bounded_fetch(lambda **kw: "next batch", 1, exchange="tse") == "next batch"
    finally:
        release.set()
        io._IN_FLIGHT["tse"].result(timeout=2)
        io.reset_io_slots()


def test_quote_receipt_cannot_create_ohlcv_or_technical_points():
    from app.db.models import MarketIntradayBar, TaiwanStockQuoteSnapshot
    from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
    from app.market.tw_chart_service import TaiwanChartService, TaiwanChartSessionScope
    from app.market_data.policies import RealtimePolicy
    from test_tw_bar_service import _db
    from test_twse_mis_realtime_acquisition import _adapter, _payload
    db, engine = _db()
    at = datetime(2026, 8, 26, 10, 0, tzinfo=TAIWAN_TZ)
    try:
        acquire_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=at,
            policy=RealtimePolicy.PREFER_LIVE, acquisition=_adapter(_payload(), at, []))
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
        assert db.query(MarketIntradayBar).count() == 0
        db.connection().exec_driver_sql("PRAGMA query_only=ON")
        chart = TaiwanChartService(db).read(instrument_id="2330", interval="1m",
            requested_at=at, session_scope=TaiwanChartSessionScope.CURRENT_SESSION)
        assert chart.quote_side["current_observation"]["value"] is not None
        assert chart.bars.bars == ()
        assert chart.technical.calculation_bar_count == 0
        assert chart.technical.response_point_count == 0
        assert chart.quote_side["price_diagnostics"]["current_price_applied_to_history"] is False
    finally:
        db.close()
        engine.dispose()
