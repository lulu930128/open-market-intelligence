from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from requests.exceptions import HTTPError, Timeout

from app.market.providers import twse_mis_current_breadth as mis
from app.market.tw_current_market_platform import read_taiwan_completed_auction_breadth, refresh_taiwan_current_breadth, read_taiwan_current_breadth, project_taiwan_current_breadth
from app.market.providers.tw_current_market import CurrentBreadthAdapter
from app.market.tw_current_market_acquisition import TaiwanCurrentBreadthAcquisitionExecutor
from app.market.tw_current_market_capabilities import TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR, TW_CURRENT_BREADTH_CAPABILITY_ID
from app.observability import provider_health
import test_tw_current_market_platform as fixtures


def test_429_preserves_success_and_separates_unattempted_batches(monkeypatch):
    mis.reset_twse_mis_current_breadth_provider()
    monkeypatch.setattr(mis, "_BATCH_SIZE", 1)
    calls = []
    def fetch(codes, **kwargs):
        calls.append(codes)
        if len(calls) == 2:
            raise HTTPError(response=SimpleNamespace(status_code=429, headers={"Retry-After": "60"}))
        return [{"c": codes[0]}]
    monkeypatch.setattr(mis.twse_mis, "fetch_stock_messages", fetch)
    diagnostics = {}
    try:
        messages, failed, attempts = mis._fetch_messages(["2330", "3711", "2454"], "TWSE", 10, diagnostics=diagnostics)
        assert messages == [{"c": "2330"}]
        assert failed == 1 and attempts == 2
        assert diagnostics["skipped_batch_count"] == 1
        assert diagnostics["attempted_batch_count"] == 2
        assert diagnostics["batch_failures"] == [{"batch_ordinal": 2, "attempted": True, "reason": "rate_limited", "http_status": 429}]
    finally:
        mis.reset_twse_mis_current_breadth_provider()


@pytest.mark.parametrize("error,reason", [(Timeout(), "timeout"), (ValueError("malformed"), "parse_error")])
def test_failure_reason_is_safe_and_specific(monkeypatch, error, reason):
    mis.reset_twse_mis_current_breadth_provider()
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(mis.twse_mis, "fetch_stock_messages", fail)
    diagnostics = {}
    try:
        assert mis._fetch_messages(["2330"], "TWSE", 10, diagnostics=diagnostics) == ([], 1, 1)
        assert diagnostics["batch_failures"][0]["reason"] == reason
        assert "2330" not in str(diagnostics)
    finally:
        mis.reset_twse_mis_current_breadth_provider()


def test_completed_auction_read_is_same_day_phase_specific_and_receipt_visible(monkeypatch):
    db, engine = fixtures._db()
    day = datetime.fromisoformat("2026-09-03T08:58:00+08:00")
    calls = []
    try:
        for at in (day, day.replace(hour=13, minute=28)):
            raw = {"as_of": at.isoformat(), "trade_date": at.date().isoformat(), "universe_count": 3,
                "advance_count": 0, "decline_count": 0, "unchanged_count": 0, "received_unclassified_count": 3,
                "not_received_count": 0, "auction_breadth": {"status": "provisional", "as_of": at.isoformat(),
                    "trade_date": at.date().isoformat(), "universe_count": 3, "advance_count": 2,
                    "decline_count": 1, "unchanged_count": 0, "unknown_count": 0}}
            adapter = CurrentBreadthAdapter(fixtures._binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
                fixtures._payload_reader(raw, calls, "mis"), clock=lambda: at)
            refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=at,
                descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
        after = day.replace(hour=13, minute=34)
        current = project_taiwan_current_breadth(read_taiwan_current_breadth(db, venue="TWSE", requested_at=after))
        assert current["auction_breadth"]["status"] == "not_applicable"
        historical = read_taiwan_completed_auction_breadth(db, venue="TWSE", requested_at=after)
        from app.market.schemas import TaiwanCompletedAuctionBreadthRead
        assert all(TaiwanCompletedAuctionBreadthRead.model_validate(item) for item in historical)
        from app.market import tw_current_market_platform as platform
        from app.market.indices import _shared_current_market_summary
        from app.market.schemas import MarketIndexSummaryRead
        with monkeypatch.context() as patcher:
            patcher.setattr(platform, "project_taiwan_current_breadth", lambda result: {
                "status": "missing", "market": result.requirement.target.scope_key, "source": "unavailable"})
            summary = MarketIndexSummaryRead.model_validate(_shared_current_market_summary(db, requested_at=after))
            twse = next(item for item in summary.indices if item.market == "TWSE")
            assert twse.breadth is None
            assert len(twse.latest_completed_auctions) == 2
        assert {item["market_session"] for item in historical} == {"opening_auction", "closing_auction"}
        assert all(item["decision_usable"] is False and item["freshness"]["is_current"] is False for item in historical)
        assert len(read_taiwan_completed_auction_breadth(db, venue="TWSE", requested_at=day.replace(hour=13, minute=27))) == 1
        assert read_taiwan_completed_auction_breadth(db, venue="TWSE", requested_at=after+timedelta(days=1)) == []
        assert not db.dirty
    finally:
        db.close()
        engine.dispose()


def test_malformed_provider_diagnostic_does_not_erase_other_entries(monkeypatch):
    def summary(db, **kwargs):
        if kwargs["resource"] == "broken":
            raise ValueError("malformed stored metadata")
        return {"recent_event_count": 0, "recent_error_count": 0, "consecutive_error_count": 0}
    monkeypatch.setattr(provider_health, "provider_event_summary", summary)
    entries = [{"provider": "example", "resource": resource, "status": "current", "ok": True} for resource in ("broken", "healthy")]
    result = provider_health.enrich_source_health_entries(None, market="tw", entries=entries)
    assert len(result) == 2
    assert result[0]["status"] == "current"
    assert result[0]["provider_event_diagnostics"]["status"] == "unavailable"
    assert result[1]["recent_error_count"] == 0


def test_last_good_receipt_is_not_advanced_by_a_failed_attempt():
    from app.db.models import TaiwanCurrentBreadthSnapshot
    db, engine = fixtures._db()
    old = datetime.fromisoformat("2026-09-03T10:00:00+08:00")
    later = old + timedelta(minutes=5)
    raw = {"as_of": old.isoformat(), "trade_date": old.date().isoformat(), "universe_count": 3,
        "advance_count": 2, "decline_count": 1, "unchanged_count": 0,
        "acquisition_fallback": True, "observation_received_at": old.isoformat()}
    adapter = CurrentBreadthAdapter(fixtures._binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        fixtures._payload_reader(raw, [], "mis"), clock=lambda: later)
    try:
        refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=later,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
        row = db.query(TaiwanCurrentBreadthSnapshot).one()
        from datetime import timezone
        assert row.received_at.replace(tzinfo=timezone.utc) == old.astimezone(timezone.utc)
        result = read_taiwan_current_breadth(db, venue="TWSE", requested_at=later)
        projected = project_taiwan_current_breadth(result)
        assert projected["decision_usable"] is False
        assert raw["observation_received_at"] == old.isoformat()
    finally:
        db.close()
        engine.dispose()


def test_historical_auction_survives_ai_projection_when_actual_breadth_is_missing():
    from app.ai.market_context.taiwan_market import _market_breadth_from_index_summary
    history = [{"status": "historical", "market_session": "opening_auction", "decision_usable": False}]
    dependencies = SimpleNamespace(get_market_index_summary=lambda *args, **kwargs: {
        "indices": [{"index_id": "TAIEX", "breadth": None, "latest_completed_auctions": history}]})
    value = _market_breadth_from_index_summary(db=None, dependencies=dependencies, warnings=[], source_refs=[])
    assert value["latest_completed_auctions"][0]["status"] == "historical"
    assert value["facts_usable"] is False and value["decision_usable"] is False
    assert "advance_count" not in value


def test_failed_attempt_diagnostics_are_retained_alongside_last_good_snapshot():
    import json
    from app.market.providers.tw_current_market import CurrentMarketProviderPayload, _raw_text
    old = datetime.fromisoformat("2026-09-03T10:00:00+08:00")
    later = old + timedelta(minutes=5)
    diagnostics = {"attempted_batch_count": 1, "failed_batch_count": 1, "skipped_batch_count": 2,
        "batch_failures": [{"batch_ordinal": 1, "attempted": True, "reason": "rate_limited", "http_status": 429}]}
    payload = CurrentMarketProviderPayload(payload={"as_of": old.isoformat(), "trade_date": old.date().isoformat(),
        "universe_count": 3, "advance_count": 2, "decline_count": 1, "unchanged_count": 0,
        "failed_batch_count": 0, "acquisition_fallback": True, "observation_received_at": old.isoformat()},
        status="stale", url="https://example.test/mis", diagnostics=diagnostics)
    assert json.loads(_raw_text(payload))["acquisition_diagnostics"] == diagnostics
    adapter = CurrentBreadthAdapter(fixtures._binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        lambda *_: payload, clock=lambda: later)
    db, engine = fixtures._db()
    try:
        result = refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=later,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
        from app.db.models import TaiwanCurrentBreadthSnapshot
        stored = db.query(TaiwanCurrentBreadthSnapshot).one()
        recorded = json.loads(stored.acquisition_diagnostics_json)
        assert recorded["attempted_batch_count"] == 1
        assert recorded["skipped_batch_count"] == 2
        assert recorded["latest_attempt_failed_batch_count"] == 1
        assert recorded["batch_failures"][0]["http_status"] == 429
        assert recorded["fallback_used"] is True
    finally:
        db.close()
        engine.dispose()
