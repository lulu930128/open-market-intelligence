"""Bounded offline reproductions of the 11/03 transport/amount regressions."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from sqlalchemy import event

from app.market.providers import twse_mis_current_breadth as provider
from app.market.tw_breadth_acquisition_contract import BreadthAcquisitionEvidence
from app.market.tw_current_market_capabilities import TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR
from app.market.taiwan_market_state import (
    compose_taiwan_market_volume_state, persist_taiwan_market_minute_state,
    read_taiwan_market_volume_state,
)
from app.market.trading_calendar import TAIWAN_TZ
from test_tw_breadth_acquisition_evidence import clock, offline, message
from test_taiwan_market_state import make_session, market_summary_payload

NOW = datetime(2026, 11, 3, 10, 45, 5, tzinfo=TAIWAN_TZ)


@pytest.mark.parametrize("venue,count", [("TWSE", 1080), ("TPEX", 887)])
def test_scan_socket_and_route_budgets_recover_without_merging_receipts(clock, monkeypatch, venue, count):
    codes = [str(6000 + i) for i in range(count)]
    calls = []

    def fetch(batch, *, timeout_seconds, phase_timing, **kwargs):
        # Synthetic latency envelope, bounded by measured 11/03 transports.
        duration = 5.2 if len(calls) % 11 == 0 else 3.0
        calls.append((list(batch), timeout_seconds))
        clock.seconds += min(duration, timeout_seconds)
        phase_timing.update(transport_seconds=min(duration, timeout_seconds), decode_seconds=0.001)
        if duration > timeout_seconds:
            raise requests.ReadTimeout("isolated first-byte delay")
        return [message(code) for code in batch]

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    # Retain the old failure as an explicit comparison, without touching source.
    with monkeypatch.context() as old:
        old.setattr(provider, "_BATCH_SOCKET_TIMEOUT_SECONDS", 4.0)
        baseline = provider.read_twse_mis_current_breadth(venue, 20, universe_reader=lambda _: codes)
    assert baseline.status == "partial"
    assert baseline.payload["decision_usable"] is False
    assert baseline.payload["message_count"] < count
    assert baseline.payload["failed_batch_count"] > 0
    original = deepcopy(baseline.payload)
    calls.clear()
    provider._CACHE[venue]["expires_at"] = 0
    started = clock.seconds
    recovered = provider.read_twse_mis_current_breadth(
        venue, TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR.max_timeout_seconds, universe_reader=lambda _: codes,
    )
    assert recovered.payload["message_count"] == count
    assert recovered.payload["not_received_count"] == 0
    assert recovered.payload["failed_batch_count"] == 0
    assert recovered.external_calls == len(calls) <= 20
    assert clock.seconds - started <= 40
    receipt = BreadthAcquisitionEvidence.model_validate(recovered.payload["acquisition_diagnostics"])
    assert receipt.budget_total_seconds == 40
    assert receipt.scan_start_code == original["scan_next_code"]
    assert all(batch.receipt_at and batch.event_max for batch in receipt.batches)
    assert all(batch.socket_timeout_seconds <= 8 for batch in receipt.batches)
    assert recovered.payload["acquisition_diagnostics"]["acquisition_id"] != original["acquisition_diagnostics"]["acquisition_id"]
    assert baseline.payload == original


def vendor_payload(minute, *, twse, tpex):
    payload = market_summary_payload(date(2026, 11, 3), hour=10, minute=minute,
                                    twse_trade_value=twse, tpex_trade_value=tpex)
    for item in payload["indices"]:
        item["trade_value_observation"] = dict(
            market=item["market"], trade_date="2026-11-03", as_of=item["as_of"],
            trade_value=item["trade_value"], currency="TWD", trade_value_unit="TWD",
            scope="venue_regular_market", trade_value_semantics="vendor_cumulative_trade_value",
            trade_value_is_estimate=False, official_flag=False,
            provider="fugle_marketdata", source="fugle_http_index_quote",
            raw_result_id=f"raw_fetch_result:{item['market']}:{minute}",
            lineage=dict(provider="fugle_marketdata", source="fugle_http_index_quote",
                         raw_receipt_id=f"raw_fetch_result:{item['market']}:{minute}",
                         content_hash="a" * 64, event_at=item["as_of"]),
        )
        item["breadth"]["trade_value"] = None
        item["current_data_core"]["trade_value"] = {
            **item["trade_value_observation"],
            "raw_result_id": item["trade_value_observation"]["lineage"]["raw_receipt_id"],
        }
    return payload


@pytest.mark.parametrize("attempt", ["one_venue", "minute_skew", "no_fresh_components"])
def test_vendor_qualified_minute_survives_partial_then_converges_read_only(monkeypatch, attempt):
    from app.market import tw_current_market_platform as platform
    from app.market import taiwan_market_state
    monkeypatch.setattr(taiwan_market_state, "utc_now", lambda: NOW.astimezone(timezone.utc))
    db = make_session()
    writes = []
    try:
        first = vendor_payload(40, twse=355321298650, tpex=97237143360)
        persist_taiwan_market_minute_state(db, payload=first, now=NOW - timedelta(minutes=4))
        db.commit()
        later = vendor_payload(45, twse=364521118840, tpex=0)
        later["indices"] = later["indices"][:1]
        persist_taiwan_market_minute_state(db, payload=later, now=NOW)
        db.commit()
        latest = {"TWSE": later["indices"][0]["trade_value_observation"]}
        if attempt == "minute_skew":
            old_tpex = deepcopy(first["indices"][1]["trade_value_observation"])
            latest["TPEX"] = old_tpex
        elif attempt == "no_fresh_components":
            latest.clear()
        monkeypatch.setattr(platform, "read_taiwan_current_index", lambda *a, **kw: kw["index_id"])
        monkeypatch.setattr(platform, "project_taiwan_current_trade_value", lambda key: latest.get("TWSE" if key == "TAIEX" else "TPEX", {}))
        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)
        event.listen(db.get_bind(), "before_cursor_execute", capture)
        state = read_taiwan_market_volume_state(db, requested_at=NOW + timedelta(minutes=1))
        assert state["current_cumulative_trade_value"] == 452558442010
        assert state["comparison_minute"] == "10:40"
        assert state["trade_value_complete"] is True
        assert state["trade_value_freshness"] == "stale"
        assert state["trade_value_qualification"]["decision_usable"] is False
        assert state["current_value_source"] == "taiwan_market_minute_state"
        assert state["vendor_reported_cumulative_trade_value"] == 452558442010
        assert state["latest_trade_value_attempt"]["current_cumulative_trade_value"] is None
        assert state["one_minute_trade_value_change"] is None
        assert all(item["lineage"]["raw_receipt_id"].endswith(":40") for item in state["markets"])
        assert all(item["lineage"]["event_at"].startswith("2026-11-03T10:40:") for item in state["markets"])
        from app.ai.market_context.taiwan_market import _volume_state_with_breadth_current_value
        assert _volume_state_with_breadth_current_value(state, breadth=None) == state
        from app.ai import capability_contract
        from test_ai_implemented_feature_contracts import response_for, public
        response = response_for(["market.volume_state"])
        response["scope"] = {"type": "market", "market": "TW"}
        response["query_plan"]["selection"] = capability_contract.normalize_selection(
            selection={"include": ["market.volume_state"], "max_response_bytes": 350000},
            output="evidence_only", realtime_policy="cache_only", payload_level="full",
            scope_type="market", target_market="TW", question_intent="analysis")
        response["result"]["data"]["compact"]["volume_state"] = deepcopy(state)
        projected = public(response)["evidence"]["data"]["market.volume_state"]
        for key in ("as_of", "comparison_identity", "current_value_source", "trade_value_freshness",
                    "latest_trade_value_attempt", "markets", "trade_value_qualification"):
            assert projected[key] == state[key]
        assert not writes
        # Matching canonical components recover without borrowing old TPEX.
        complete = vendor_payload(45, twse=364521118840, tpex=100000000000)
        latest.update({item["market"]: item["trade_value_observation"] for item in complete["indices"]})
        fresh = read_taiwan_market_volume_state(db, requested_at=NOW + timedelta(minutes=1))
        assert fresh["current_cumulative_trade_value"] == 464521118840
        assert fresh["comparison_minute"] == "10:45"
        assert fresh.get("trade_value_freshness") != "stale"
        assert fresh["trade_value_authority_status"] == "vendor_reported"
        for days in (5, 20):
            assert fresh[f"same_time_baseline_{days}d"]["sample_days"] == 0
            assert fresh[f"same_time_baseline_{days}d"]["pace_ratio"] is None
        assert not writes
    finally:
        db.close()
        db.get_bind().dispose()


@pytest.mark.parametrize("defect", ["lineage", "event_minute", "semantics", "authority", "previous_date"])
def test_ineligible_persisted_snapshot_cannot_be_a_qualified_fallback(monkeypatch, defect):
    import json
    from app.market import taiwan_market_state, tw_current_market_platform as platform
    from app.db.models import TaiwanMarketMinuteState
    monkeypatch.setattr(taiwan_market_state, "utc_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(platform, "read_taiwan_current_index", lambda *a, **kw: kw["index_id"])
    latest = vendor_payload(45, twse=364521118840, tpex=0)["indices"][0]["trade_value_observation"]
    monkeypatch.setattr(platform, "project_taiwan_current_trade_value", lambda key: latest if key == "TAIEX" else {})
    db = make_session()
    try:
        persist_taiwan_market_minute_state(db, payload=vendor_payload(40, twse=355321298650, tpex=97237143360))
        row = db.query(TaiwanMarketMinuteState).filter_by(market="TPEX").one()
        if defect == "lineage":
            row.lineage_complete = False
        elif defect == "event_minute":
            sources = json.loads(row.component_sources_json)
            next(item for item in sources if item.get("owns_trade_value"))["event_at"] = "2026-11-03T10:39:45+08:00"
            row.component_sources_json = json.dumps(sources)
        elif defect == "semantics":
            row.trade_value_semantics = "estimated_latest_price_x_cumulative_volume_lots"
        elif defect == "authority":
            row.trade_value_is_estimate = True
        else:
            for row in db.query(TaiwanMarketMinuteState).all():
                row.trade_date = date(2026, 11, 2)
                row.minute_at -= timedelta(days=1)
        db.commit()
        state = read_taiwan_market_volume_state(db, requested_at=NOW + timedelta(minutes=1))
        assert state["current_cumulative_trade_value"] is None
        assert state["trade_value_complete"] is False
        assert state["trade_value_qualification"]["decision_usable"] is False
        assert state.get("trade_value_freshness") != "stale"
    finally:
        db.close()
        db.get_bind().dispose()


def test_older_authority_samples_never_fill_vendor_baseline(monkeypatch):
    from app.market import taiwan_market_state, tw_current_market_platform as platform
    from app.db.models import TaiwanMarketMinuteState
    monkeypatch.setattr(taiwan_market_state, "utc_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(platform, "read_taiwan_current_index", lambda *a, **kw: None)
    monkeypatch.setattr(platform, "project_taiwan_current_trade_value", lambda result: {})
    db = make_session()
    try:
        day = NOW.date() - timedelta(days=1)
        for _ in range(18):
            while day.weekday() >= 5:
                day -= timedelta(days=1)
            persist_taiwan_market_minute_state(db, payload=market_summary_payload(
                day, hour=10, minute=40, twse_trade_value=300, tpex_trade_value=100))
            day -= timedelta(days=1)
        persist_taiwan_market_minute_state(db, payload=vendor_payload(40, twse=355321298650, tpex=97237143360))
        before = [(row.id, row.component_sources_json) for row in db.query(TaiwanMarketMinuteState).all()]
        assert len(before) == 38
        state = read_taiwan_market_volume_state(db, requested_at=NOW)
        assert state["current_cumulative_trade_value"] == 452558442010
        for days in (5, 20):
            baseline = state[f"same_time_baseline_{days}d"]
            assert baseline["sample_days"] == baseline["qualified_sample_days"] == 0
            assert baseline["pace_ratio"] is None and baseline["decision_usable"] is False
        assert before == [(row.id, row.component_sources_json) for row in db.query(TaiwanMarketMinuteState).all()]
    finally:
        db.close()
        db.get_bind().dispose()


@pytest.mark.parametrize("read_at", [
    "2026-11-04T10:46:00+08:00",  # next trading day, regular session
    "2026-11-03T17:00:00+00:00",  # next Taiwan date, before rollover
    "2026-11-04T08:45:00+08:00",  # next trading day's preopen
    "2026-11-07T10:46:00+08:00",  # closed weekend
])
def test_no_fresh_components_never_retain_previous_day_as_current(monkeypatch, read_at):
    from app.market import taiwan_market_state, tw_current_market_platform as platform
    from app.db.models import TaiwanMarketMinuteState
    monkeypatch.setattr(taiwan_market_state, "utc_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(platform, "read_taiwan_current_index", lambda *a, **kw: None)
    monkeypatch.setattr(platform, "project_taiwan_current_trade_value", lambda result: {})
    db = make_session()
    try:
        persist_taiwan_market_minute_state(db, payload=vendor_payload(40, twse=355321298650, tpex=97237143360))
        before = [(row.id, row.component_sources_json, row.cumulative_trade_value)
                  for row in db.query(TaiwanMarketMinuteState).all()]
        state = read_taiwan_market_volume_state(db, requested_at=datetime.fromisoformat(read_at))
        assert state["current_cumulative_trade_value"] is None
        assert state["vendor_reported_cumulative_trade_value"] is None
        assert state["trade_value_complete"] is False
        assert state.get("trade_value_freshness") != "stale"
        assert state["trade_value_qualification"]["decision_usable"] is False
        assert state["included_markets"] == []
        assert set(state["missing_markets"]) == {"TWSE", "TPEX"}
        for days in (5, 20):
            assert state[f"same_time_baseline_{days}d"]["pace_ratio"] is None
        assert before == [(row.id, row.component_sources_json, row.cumulative_trade_value)
                          for row in db.query(TaiwanMarketMinuteState).all()]
    finally:
        db.close()
        db.get_bind().dispose()


@pytest.mark.parametrize("hour,minute", [(8, 0), (8, 45)])
def test_same_date_cache_cannot_bypass_requested_session_gate(monkeypatch, hour, minute):
    from app.market import taiwan_market_state, tw_current_market_platform as platform
    monkeypatch.setattr(taiwan_market_state, "utc_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(platform, "read_taiwan_current_index", lambda *a, **kw: None)
    monkeypatch.setattr(platform, "project_taiwan_current_trade_value", lambda result: {})
    db = make_session()
    try:
        persist_taiwan_market_minute_state(db, payload=vendor_payload(40, twse=355321298650, tpex=97237143360))
        cached = taiwan_market_state._read_taiwan_market_minute_volume_state(db, requested_at=NOW)
        assert cached["current_cumulative_trade_value"] == 452558442010
        # Even a cached same-date qualified projection cannot lend its session
        # to a preopen request. The public reader must gate its own retention.
        monkeypatch.setattr(taiwan_market_state, "_read_taiwan_market_minute_volume_state", lambda *a, **kw: deepcopy(cached))
        state = read_taiwan_market_volume_state(db, requested_at=NOW.replace(hour=hour, minute=minute))
        assert state["current_cumulative_trade_value"] is None
        assert state["trade_value_complete"] is False
        assert state.get("trade_value_freshness") != "stale"
    finally:
        db.close()
        db.get_bind().dispose()
