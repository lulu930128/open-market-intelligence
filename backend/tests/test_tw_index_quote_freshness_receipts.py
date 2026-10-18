"""Offline production-owner regressions for the 2026-10-14 quote incident."""

from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.ai import ask as ai_ask, capability_contract, decision_envelope
from app.ai.market_context.taiwan_projection import _compact_index_quote, _build_tw_index_compact_evidence
from app.ai.schemas import AiAskRequest
from app.market.index_resolution import resolve_taiwan_index_truth
from app.market.quote_depth import project_taiwan_quote_evidence_bundle
from app.market.taiwan_quote_evidence import acquire_taiwan_quote_evidence_bundle
from app.market.trading_calendar import TAIWAN_TZ
from test_ai_decision_envelope import _v2_response
from test_twse_mis_realtime_acquisition import _adapter, _db, _payload


NOW = datetime(2026, 10, 14, 10, 1, tzinfo=TAIWAN_TZ)


def calendar():
    return {"timezone": "Asia/Taipei", "checked_at": NOW.isoformat(),
            "date": "2026-10-14", "previous_trading_day": "2026-10-13",
            "is_trading_day": True, "phase": "regular"}


def candidates(summary_age=0):
    return ({"source": "fugle_indices_stream", "provider": "fugle",
             "points": [{"time": (NOW - timedelta(seconds=120)).isoformat(),
                         "price": 48891.15}]},
            {"source": "fugle_indices_stream", "provider": "fugle",
             "as_of": (NOW - timedelta(seconds=summary_age)).isoformat(),
             "close": 48931.75, "previous_close": 48600})


def test_newer_same_session_summary_wins_and_fugle_is_live_without_lineage_invention():
    intraday, summary = candidates()
    truth = resolve_taiwan_index_truth(intraday=intraday, index_snapshot=summary,
        calendar_status=calendar(), index_id="TAIEX")
    assert truth.selected_candidate == "index_summary"
    assert truth.selected_value == 48931.75
    assert truth.selected_finalization == "intraday"
    assert truth.selected_previous_close_trade_date is None
    assert truth.selected_previous_close_status == "unknown"
    assert truth.warnings
    quote = _compact_index_quote(index_id="TAIEX", intraday=intraday,
        index_snapshot={**summary, "resolution": truth.model_dump(mode="json")},
        calendar_status=calendar())
    assert quote["status"] == "live"
    assert quote["delivery_status"] == "live"
    assert quote["freshness"]["is_live"] is True
    assert quote["quote_time"] == NOW.isoformat()
    assert quote["provider"] == "fugle"
    assert quote["source"] == "fugle_indices_stream"
    assert quote["provider"] != quote["source"]


def test_index_projection_does_not_invent_unknown_provider_from_source():
    _, summary = candidates()
    summary.pop("provider")
    quote = _compact_index_quote(index_id="TAIEX", intraday=None,
        index_snapshot=summary, calendar_status=calendar())
    assert quote["provider"] is None
    assert quote["source"] == "fugle_indices_stream"


def test_current_index_quote_does_not_promote_58_of_61_bar_coverage():
    intraday, summary = candidates()
    start = NOW.replace(hour=9, minute=0)
    coverage = {"status": "partial_prefix", "expected_bucket_count": 61,
        "observed_bucket_count": 58, "missing_bucket_count": 3,
        "missing_ranges": [{"from": "09:10", "to": "09:11"}, {"from": "09:59", "to": "10:01"}]}
    intraday.update(points=[{"time": (start + timedelta(minutes=i)).isoformat(),
        "close": 48891.15, "price": 48891.15} for i in range(61) if i not in {10, 59, 60}],
        point_count=58, series_coverage=coverage, coverage_status="partial_prefix", is_partial=True)
    compact = _build_tw_index_compact_evidence(index_id="TAIEX", as_of=NOW.isoformat(),
        index_snapshot=summary, daily_chart=None, intraday=intraday, include_intraday=True,
        market_data_params={}, market_chip=None, contributions=None, technical_reports={},
        technical_analysis={}, missing=[], warnings=[], source_refs=[], calendar_status=calendar())
    assert compact["quote"]["status"] == "live"
    bars = compact["intraday_bars"]["series"]["1m"]
    assert bars["status"] == "partial" and bars["is_partial"]
    assert bars["series_coverage"] == coverage
    assert compact["freshness_by_capability"]["quote.snapshot"]["status"] == "live"
    assert compact["freshness_by_capability"]["intraday.bars"]["status"] == "partial"
    assert compact["slots"]["intraday"]["status"] == "partial"


@pytest.mark.parametrize("changes", [
    {"finalization": "final"}, {"freshness_status": "stale"},
    {"authority": "derived_proxy"},
    {"as_of": (NOW + timedelta(minutes=1)).isoformat()},
    {"as_of": (NOW - timedelta(days=1)).isoformat()},
    {"as_of": (NOW - timedelta(seconds=241)).isoformat()},
])
def test_newer_timestamp_cannot_override_semantics_authority_or_age(changes):
    intraday, summary = candidates()
    summary.update(changes)
    truth = resolve_taiwan_index_truth(intraday=intraday, index_snapshot=summary,
        calendar_status=calendar(), index_id="TAIEX")
    assert truth.selected_candidate == "intraday_last_trade"


def test_live_estimate_does_not_displace_eligible_delayed_direct_observation():
    intraday, summary = candidates()
    intraday["points"][0]["time"] = (NOW - timedelta(seconds=200)).isoformat()
    summary["authority"] = "derived_proxy"
    truth = resolve_taiwan_index_truth(intraday=intraday, index_snapshot=summary,
        calendar_status=calendar(), index_id="TAIEX")
    assert truth.selected_candidate == "intraday_last_trade"
    assert truth.delivery_status == "delayed_current_session"


@pytest.mark.parametrize("age,status,delivery", [
    (0, "live", "live"), (180, "live", "live"),
    (181, "delayed", "delayed_current_session"),
    (240, "delayed", "delayed_current_session"),
    (241, "stale", "unavailable"),
])
def test_summary_without_bars_uses_canonical_age_bound(age, status, delivery):
    _, summary = candidates(age)
    quote = _compact_index_quote(index_id="TAIEX", intraday=None,
        index_snapshot=summary, calendar_status=calendar())
    assert quote["status"] == status
    assert quote["freshness"]["status"] == status
    assert quote["delivery_status"] == delivery
    assert quote["freshness"]["is_live"] == (status == "live")


@pytest.mark.parametrize("status,attempted", [
    ("not_attempted", False), ("unverified", False),
    ("failed", True), ("completed", True),
])
def test_receipt_survives_v4_projection_without_promoting_stale_trade(status, attempted):
    response = _v2_response()
    response["result"]["data"]["compact"]["quote"] = {
        "status": "stale", "latest_price": 100, "quote_time": "2026-10-14T09:12:00+08:00",
        "is_realtime": False, "freshness": {"status": "stale", "is_stale": True},
    }
    receipt = {"requested": True, "attempted": attempted, "status": status,
        "providers_attempted": ["twse_mis"] if attempted else [],
        "resource_attempts": [{"provider": "twse_mis", "resource_id": "quote",
            "status": status, "attempted": True}] if attempted else [],
        "persistence": {"committed": status == "completed", "raw_result_ids": [7] if status == "completed" else []}}
    response["result"]["data"]["provider_contract"] = {
        "provider_attempts_by_capability": {"quote.snapshot": receipt}}
    selection = capability_contract.normalize_selection(
        selection={"include": ["quote.snapshot"], "max_response_bytes": 65536},
        output="evidence_only", realtime_policy="require_live", payload_level="compact",
        scope_type="stock", question_intent="quote")
    response["query_plan"]["selection"] = selection
    response["query_plan"]["target_type"] = "stock"
    result = decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")
    outcome = result["execution"]["refresh_reconciliation"]["capabilities"]["quote.snapshot"]
    assert outcome["primary_reader_acquisition"] == receipt
    assert outcome["provider_fetch_requested"] is True
    assert outcome["provider_fetch_attempted"] is attempted
    assert outcome["provider_succeeded"] == (status == "completed")
    assert outcome["tool_run_attempted"] is False
    assert outcome["final_status"] == "live_requirement_not_satisfied"
    assert outcome["resolution_type"] == ("already_attempted" if attempted else "deferred_action")
    assert result["evidence"]["realtime"]["quote.snapshot"]["decision_usable"] is False


def test_real_bundle_receipt_retains_resource_and_persistence_but_old_trade_stays_stale():
    # Real adapter/parser/canonical persistence with a deterministic fake HTTP receipt.
    now = datetime(2026, 8, 26, 10, 2, tzinfo=TAIWAN_TZ)
    db, engine = _db()
    calls = []
    try:
        bundle = acquire_taiwan_quote_evidence_bundle(db, stock_id="2330", requested_at=now,
            requested_capabilities=("quote.snapshot",),
            acquisition=_adapter(_payload(event_time="10:00:00"), now, calls))
        result = project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
        receipt = result["provider_attempts_by_capability"]["quote.snapshot"]
        assert len(calls) == 1
        assert receipt["requested"] and receipt["attempted"]
        assert receipt["status"] == "partial"
        assert receipt["resource_attempts"][0]["resource_id"]
        assert receipt["resource_attempts"][0]["acquisition_status"] == "partial"
        assert receipt["persistence"]["committed"]
        assert receipt["persistence"]["raw_result_ids"]
        assert result["freshness"]["is_stale"]
        assert not result["headline_decision_usable"]
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("policy,status", [("cache_only", None), ("require_live", "not_attempted"),
    ("require_live", "failed"), ("require_live", "completed"), ("require_live", "unverified")])
def test_ask_explicit_acquisition_receipt_survives_cache_reread(policy, status):
    db, engine = _db()
    receipt = {"requested": True, "attempted": status in {"failed", "completed"},
        "status": status, "providers_attempted": ["twse_mis"] if status in {"failed", "completed"} else [],
        "resource_attempts": []}
    try:
        payload = AiAskRequest(question="2330 即時報價", target={"type": "tw_stock", "id": "2330"},
            contract_version="omi.decision.v4", output="evidence_only", mode="data_only",
            selection={"include": ["quote.snapshot"], "max_response_bytes": 65536},
            realtime_policy=policy, refresh_policy={"before_answer": True}, allow_external_fetch=True,
            allow_llm=False, tool_budget={"max_calls": 1, "max_external_fetches": 1})
        with patch.object(ai_ask.tools, "acquire_taiwan_quote_evidence_projection",
                return_value={"provider_attempts_by_capability": {"quote.snapshot": deepcopy(receipt)}},
                side_effect=RuntimeError("fixture") if status == "unverified" else None) as acquire:
            result = ai_ask.ask(db=db, payload=payload,
                server_policy=ai_ask.AiAskServerPolicy(can_external_fetch=True, trust_source="token"))
        outcome = result["execution"]["refresh_reconciliation"]["capabilities"]["quote.snapshot"]
        if policy == "cache_only":
            acquire.assert_not_called()
            assert not outcome["provider_fetch_requested"]
            assert not outcome["provider_fetch_attempted"]
        else:
            acquire.assert_called_once()
            assert outcome["provider_fetch_requested"]
            assert outcome["provider_fetch_attempted"] == receipt["attempted"]
            assert outcome["primary_reader_acquisition"]["status"] == status
        assert not outcome["provider_succeeded"] or status == "completed"
        assert not outcome["tool_run_attempted"]
    finally:
        db.close()
        engine.dispose()
