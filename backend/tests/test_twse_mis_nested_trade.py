"""Synthetic MIS nested execution fixtures; no live provider or database IO."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from app.market.providers import twse_mis_current_breadth as breadth
from app.market.providers.tw_public_quote import quote_observation_from_twse_mis
from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
from app.market.trading_calendar import TAIWAN_TZ
from app.market.twse_mis_observation import resolve_twse_mis_actual_trade
from app.market_data.contracts import InstrumentKey, InstrumentType, Market, MarketSession


NOW = datetime(2026, 10, 27, 10, 35, tzinfo=TAIWAN_TZ)


@pytest.fixture
def message():
    # User-supplied field example, reconstructed synthetically (not a raw receipt).
    return dict(c="2330", d="20261027", t="10:34:15", z="-", tv="-",
                trade=dict(z="2400.0000", t="10:32:43", v=1),
                v=16443, y=2385, ts=0, b="2395_", g="2_", a="2400_", f="3_")


def normalize(message, *, now=NOW, expected=None):
    return resolve_twse_mis_actual_trade(
        expected_trade_date=expected or now.date(), observation_trade_date=message.get("d"),
        provider_event_time=breadth._snapshot_time(message), trial_status=message.get("ts"),
        last_trade_price=message.get("z"), last_trade_volume_lots=message.get("tv"),
        cumulative_volume_lots=message.get("v"), nested_trade=message.get("trade"),
        observed_at=now,
    )


def snapshot(message, now=NOW):
    return canonical_snapshot_from_twse_mis(
        instrument=InstrumentKey(market=Market.TW, symbol=message["c"], venue="TWSE", instrument_type=InstrumentType.STOCK),
        message=message, session=MarketSession.CONTINUOUS, fetched_at=now,
        expected_trade_date=now.date(),
    )


@pytest.mark.parametrize("top,nested", [
    ({"ts": 1}, {}), ({"ts": "-"}, {}), ({"ts": None}, {}),
    ({"d": "20261026"}, {}), ({"d": "bad"}, {}),
    ({}, {"d": "20261026"}), ({}, {"d": "bad"}),
    ({"t": "10:35:01"}, {}), ({"t": "bad"}, {}),
    ({"t": "08:59:59"}, {"t": "08:59:58"}),
    ({"t": "14:30:00"}, {"t": "14:29:59"}),
    ({}, {"t": "10:34:16"}), ({}, {"t": "08:59:59"}),
    ({}, {"t": "24:00:00"}), ({}, {"t": "10:61:00"}),
    ({}, {"t": "bad"}), ({}, {"t": None}), ({}, {"t": 103243}),
    ({}, {"z": "-"}), ({}, {"z": "NaN"}), ({}, {"z": "Infinity"}),
    ({}, {"z": "1e10000"}), ({}, {"z": 0}), ({}, {"z": -1}), ({}, {"z": True}),
    ({}, {"v": 0}), ({}, {"v": -1}), ({}, {"v": True}),
    ({}, {"v": "NaN"}), ({}, {"v": "Infinity"}), ({}, {"v": "1.5"}),
    ({}, {"v": None}), ({}, {"v": 16444}),
    ({"v": 0}, {}), ({"v": "-"}, {}), ({"v": None}, {}),
    ({"v": "1.5"}, {}), ({"v": True}, {}), ({"v": "Infinity"}, {}),
])
def test_nested_rejects_unproven_execution(message, top, nested):
    message.update(top)
    message["trade"].update(nested)
    result = normalize(message)
    assert not result["actual_trade_price_available"]
    assert result["actual_trade_price"] is None
    assert result["actual_trade_price_as_of"] is None
    assert snapshot(message).quote.last_trade_price is None
    row = breadth._classify_message(message, "TWSE", observed_at=NOW)
    assert row["current_price"] is None
    assert row["direction"] is None


@pytest.mark.parametrize("nested", [None, [], "malformed", {}, {"pz": 2400, "t": "10:32:43", "v": 1}])
def test_nested_absent_or_malformed_never_uses_pz(message, nested):
    message.update(trade=nested, pz=2400, ps=1)
    assert not normalize(message)["actual_trade_price_available"]


def test_top_z_precedence_and_input_immutability(message):
    message.update(z="2401", tv="3")
    before = deepcopy(message)
    result = normalize(message)
    assert message == before
    assert result["actual_trade_price"] == 2401
    assert result["actual_trade_price_as_of"] == breadth._snapshot_time(message)
    assert result["actual_trade_price_source"] == "twse_mis_snapshot_z"
    quote = snapshot(message).quote
    assert quote.last_trade_quantity.original_value == 3


@pytest.mark.parametrize("venue,code,price,trade_time,volume,last_volume,snapshot_time", [
    ("TWSE", "2330", "2400.0000", "10:32:43", 16443, 1, "10:34:15"),
    ("TPEX", "8299", "1920.0000", "10:25:55", 1253, 5, "10:34:48"),
])
def test_breadth_canonical_public_quote_share_real_event(message, venue, code, price, trade_time, volume, last_volume, snapshot_time):
    message.update(c=code, t=snapshot_time, v=volume,
                   trade=dict(z=price, t=trade_time, v=last_volume))
    before = deepcopy(message)
    actual_at = datetime.fromisoformat(f"2026-10-27T{trade_time}+08:00")
    raw_at = breadth._snapshot_time(message)
    row = breadth._classify_message(message, venue, observed_at=NOW)
    assert row["current_price"] == float(price)
    assert row["price_source"] == "trade.z"
    assert row["price_as_of"] == actual_at < row["as_of"] == raw_at
    assert row["direction"] == ("advance" if float(price) > message["y"] else "decline")
    canonical = snapshot(message)
    assert canonical.quote.lineage.event_at == actual_at
    assert canonical.depth.lineage.event_at == canonical.session.observed_at == raw_at
    assert canonical.quote.last_trade_quantity.value == last_volume * 1000
    assert canonical.quote.cumulative_quantity.value == volume * 1000
    quote = quote_observation_from_twse_mis(
        instrument=InstrumentKey(market=Market.TW, symbol=code, venue=venue, instrument_type=InstrumentType.STOCK),
        message=message, session=MarketSession.CONTINUOUS,
        received_at=NOW, fetched_at=NOW, content_hash="synthetic-receipt",
    )
    assert quote.last_trade_price == Decimal(price)
    assert quote.lineage.event_at == actual_at
    assert quote.lineage.provider == "twse_mis"
    assert quote.lineage.content_hash == "synthetic-receipt"
    assert quote.lineage.received_at == NOW
    assert message == before


@pytest.mark.parametrize("price,direction", [(2386, "advance"), (2385, "unchanged"), (2384, "decline")])
def test_nested_breadth_directions(message, price, direction):
    message["trade"]["z"] = price
    assert breadth._classify_message(message, "TWSE", observed_at=NOW)["direction"] == direction


def test_nested_wrong_expected_date_and_receipt_date(message):
    assert not normalize(message, expected=NOW.date() - timedelta(days=1))["actual_trade_price_available"]
    assert not normalize(message, now=NOW + timedelta(days=1))["actual_trade_price_available"]


@pytest.mark.parametrize("value", ["0", "0.5", "-", None])
def test_legacy_top_z_without_whole_lot_evidence_remains_missing(message, value):
    message.update(z="2400", v=value, tv="-", trade=None)
    assert snapshot(message).quote.last_trade_price is None
    assert breadth._classify_message(message, "TWSE")["current_price"] is None


def test_nested_execution_cannot_replace_newer_cached_execution(message):
    prior = dict(trade_date=NOW.date(), price=2401, has_actual_trade=True,
                 price_as_of=NOW.replace(minute=33), cumulative_volume_lots=16443)
    assert breadth._classify_message(message, "TWSE", cached_state=prior, observed_at=NOW) is None


@pytest.fixture
def clock():
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)
    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    breadth.reset_twse_mis_current_breadth_provider()
    with patch.object(breadth, "datetime", Clock):
        yield
    breadth.reset_twse_mis_current_breadth_provider()


@pytest.mark.parametrize("venue", ["TWSE", "TPEX"])
def test_five_synthetic_rows_before_after_counts_and_no_rescue(message, venue, clock):
    rows = [{**deepcopy(message), "c": str(6000 + i)} for i in range(5)]
    codes = [row["c"] for row in rows]
    legacy = [{k: v for k, v in row.items() if k != "trade"} for row in rows]
    before = breadth._build_payload(venue, codes, legacy, 0)
    assert before["classified_count"] == 0
    calls = []
    def fetch(selected, **kwargs):
        calls.append(selected)
        return rows
    diagnostics = {}
    with patch.object(breadth.twse_mis, "fetch_stock_messages", side_effect=fetch):
        received, failed, call_count = breadth._fetch_messages(codes, venue, 20, diagnostics=diagnostics)
        payload = breadth._build_payload(venue, codes, received, failed)
        payload, rescue_calls = breadth._rescue_missing_z(
            venue, codes, received, payload, prior_states=None, remaining_seconds=4,
        )
    assert calls == [codes]
    assert call_count == 1 and rescue_calls == 0
    assert payload["classified_count"] == 5
    assert payload["coverage_reason_counts"]["actual_trade_unavailable"] == 0
    assert payload["missing_z_rescue"]["candidate_count"] == 0
    assert diagnostics["batches"][0]["actual_z"] == 5
    assert diagnostics["batches"][0]["missing_z"] == 0
    assert payload["oldest_price_as_of"] < payload["as_of"]
    incomplete = breadth._build_payload(venue, codes + ["6999"], received, failed)
    assert incomplete["decision_usable"] is False


def test_rescue_accepts_valid_nested_and_preserves_trade_time(message, clock):
    original = {**deepcopy(message), "trade": None}
    payload = breadth._build_payload("TWSE", ["2330"], [original], 0)
    with patch.object(breadth.twse_mis, "fetch_stock_messages", return_value=[message]):
        result, calls = breadth._rescue_missing_z(
            "TWSE", ["2330"], [original], payload, prior_states=None, remaining_seconds=4,
        )
    assert calls == 1
    assert result["missing_z_rescue"]["candidate_count"] == 1
    assert result["missing_z_rescue"]["resolved_count"] == 1
    row = result["component_stock_rows"][0]
    assert row["price_source"] == "trade.z"
    assert row["price_as_of"].strftime("%H:%M:%S") == "10:32:43"


def test_realtime_acquisition_keeps_old_trade_stale_and_current_depth_live():
    from test_twse_mis_realtime_acquisition import _db, _adapter, _payload, TAIPEI
    from app.market.taiwan_realtime_platform import refresh_taiwan_realtime_snapshot
    from app.market.quote_depth import get_taiwan_stock_quote_depth
    now = datetime(2026, 8, 26, 10, 2, tzinfo=TAIPEI)
    raw = json.loads(_payload(event_time="10:02:00"))
    raw["msgArray"][0].update(z="-", tv="-", trade=dict(z="2400", t="10:00:00", v=1))
    db, engine = _db()
    try:
        refresh_taiwan_realtime_snapshot(db, stock_id="2330", requested_at=now,
            acquisition=_adapter(json.dumps(raw), now, []))
        db.connection().exec_driver_sql("PRAGMA query_only=ON")
        outward = get_taiwan_stock_quote_depth(db=db, stock_id="2330", now=now)
        components = outward["data_core_components"]
        assert components["quote.snapshot"]["freshness"]["status"] == "stale"
        assert not components["quote.snapshot"]["resolved_health"]["research_usable"]
        assert components["quote.order_book"]["freshness"]["is_live"]
        assert outward["depth_live_available"]
    finally:
        db.close()
        engine.dispose()


def test_public_acquisition_persistence_readback_and_no_bars(message):
    from test_twse_mis_realtime_acquisition import _db
    from test_tw_public_quote_platform import _executor
    from app.market.public_quote_platform import (
        acquire_taiwan_public_last_trade_quote, project_taiwan_public_last_trade_quote,
        read_taiwan_public_last_trade_quote,
    )
    from app.db.models import MarketDailyPrice, RawFetchResult, TaiwanStockQuoteSnapshot
    from app.market_data.policies import RealtimePolicy
    raw = json.dumps({"rtcode": "0000", "msgArray": [message]})
    db, engine = _db()
    try:
        result = acquire_taiwan_public_last_trade_quote(
            db, stock_id="2330", requested_at=NOW,
            policy=RealtimePolicy.PREFER_LIVE, acquisition=_executor(raw, NOW),
        )
        assert result.persistence.committed
        assert db.query(TaiwanStockQuoteSnapshot).count() == 1
        assert db.query(RawFetchResult).count() == 1
        assert db.query(MarketDailyPrice).count() == 0
        db.connection().exec_driver_sql("PRAGMA query_only=ON")
        reread = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
        quote = reread.resolved.quote
        assert quote.last_trade_price == Decimal("2400")
        assert quote.lineage.event_at == NOW.replace(minute=32, second=43)
        assert quote.lineage.raw_receipt_id
        assert quote.lineage.received_at == NOW
        projected = project_taiwan_public_last_trade_quote(reread)
        assert projected["cumulative_volume_lots"] == 16443
        assert projected["last_trade_volume_lots"] == 1
        assert projected["freshness"]["status"] == "stale"
        assert not projected["resolved_health"]["research_usable"]
    finally:
        db.close()
        engine.dispose()


def test_breadth_persistence_retains_old_execution_recency(message):
    from test_twse_mis_realtime_acquisition import _db
    from test_tw_breadth_semantics import acquire
    from app.market.tw_current_market_platform import (
        project_taiwan_current_breadth, read_taiwan_current_breadth,
    )
    from app.market.public_quote_platform import read_taiwan_public_last_trade_quote
    raw = breadth._build_payload("TWSE", ["2330"], [message], 0)
    db, engine = _db()
    try:
        result = acquire(db, raw, now=NOW)
        assert result.resolved.breadth is not None
        db.connection().exec_driver_sql("PRAGMA query_only=ON")
        projected = project_taiwan_current_breadth(
            read_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW))
        assert projected["observation_received_freshness"] == "current"
        # Breadth's existing policy uses 90s/600s; quote freshness is separate.
        assert projected["last_trade_recency"] == "delayed"
        assert projected["directional_coverage_ratio"] == 1
        quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
        assert quote.resolved.quote.last_trade_price == Decimal("2400")
        assert quote.resolved.quote.lineage.event_at == NOW.replace(minute=32, second=43)
        assert not quote.resolved.health.research_usable
    finally:
        db.close()
        engine.dispose()
