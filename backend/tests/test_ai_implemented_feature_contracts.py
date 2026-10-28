"""Offline public-contract regressions for the implemented-feature audit."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from app.ai import capability_contract as contract, decision_envelope, refresh_status
from app.ai.schemas import AiAskRequest
from test_ai_decision_envelope import _v2_response
from test_omi_mcp_server import load_server_module
from test_tw_free_intraday import NOW, db  # noqa: F401 -- shared isolated SQLite fixture


def response_for(capabilities, *, budget=350000, policy="cache_only", mode="data_only", fields=None):
    response = _v2_response(freshness_by_domain={"quote": "current", "intraday": "current", "technical": "current"})
    response["mode"] = {"requested": mode, "effective": mode, "response": mode, "payload_level": "compact"}
    response["report_level"] = mode
    response["analysis"] = {}
    response["query_plan"] = {"target_type": "stock", "payload_level": "compact",
        "selection": contract.normalize_selection(selection={"include": capabilities,
            "max_response_bytes": budget, **({"fields": fields} if fields else {})},
            output="evidence_only", realtime_policy=policy, payload_level="compact",
            scope_type="stock", target_market="TW", question_intent="quote")}
    return response


def public(response):
    return decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")


def pending_response(*, cached=False, policy="prefer_live", fallback=True, budget=350000, mode="data_only"):
    response = response_for(["intraday.bars"], budget=budget, policy=policy, mode=mode)
    response["request_status"] = "completed" if cached and policy == "prefer_live" and fallback else "background_in_progress"
    response["policy"] = {"allow_llm": False, "allow_write": False, "refresh_policy": {"fallback_to_cached": fallback}}
    job = {"job_id": 192927, "status": "running", "deduplicated": True,
        "poll_url": "/api/ai/refresh-status/192927", "status_url": "/api/ai/refresh-status/192927"}
    response["job"] = deepcopy(job) if response["request_status"] != "completed" else {}
    response["freshness"] = {"status": "partial" if cached else "missing"}
    response["facts_ready"] = cached
    response["analysis_ready"] = False
    response["result"]["data"]["compact"]["freshness_by_domain"] = {"intraday": "partial" if cached else "missing"}
    response["tool_runs"] = [{"tool": "tw.refresh_intraday_bars", "status": "background_running",
        "operation_status": "pending", "evidence_status": "pending", "request_status": "background_in_progress",
        "arguments": {"stock_id": "2330", "requested_capabilities": ["intraday.bars"]}, "job": job,
        "result_summary": {"message": "bounded pending progress"}}]
    response["result"]["data"]["compact"]["intraday_bars"] = {
        "status": "partial" if cached else "missing", "interval": "1m", "requested_interval": "1m",
        "volume_unit": "shares", "provider": "fugle_marketdata", "source": "fugle.intraday.1m",
        "point_count": 1 if cached else 0, "is_partial": True,
        "points": [{"time": "2026-10-28T09:00:00+08:00", "price": 100, "volume": 1000}] if cached else []}
    return response


@pytest.mark.parametrize("cached,policy,fallback", [
    (False, "prefer_live", True), (True, "prefer_live", True),
    (True, "require_live", True), (True, "prefer_live", False),
])
@pytest.mark.parametrize("budget,mode", [(350000, "data_only"), (16384, "data_only"), (16384, "brief")])
def test_f1_pending_public_v4_preserves_tracking_without_completed_claim(cached, policy, fallback, budget, mode):
    response = pending_response(cached=cached, policy=policy, fallback=fallback, budget=budget, mode=mode)
    result = public(response)
    assert result["request_valid"] is True
    assert result["execution_completed"] is False
    assert result["target"]["id"] == "2330" and result["target"].get("identity_status") != "unresolved"
    assert result["status"]["readiness"]["decision_ready"] is False
    if not cached or policy == "require_live" or not fallback:
        assert result["data_available"] is False
    jobs = result["continuation"]["fill_plan"]["jobs"]
    assert len(jobs) == 1 and jobs[0]["job_id"] == 192927
    assert jobs[0]["status_url"] == "/api/ai/refresh-status/192927"
    assert jobs[0]["operation_status"] == "pending" and jobs[0]["evidence_status"] == "pending"
    assert not result["continuation"]["fill_plan"]["actions"]
    run = result["execution"]["tool_runs"][0]
    assert run["job"]["job_id"] == 192927 and run["status"] == "background_running"
    if response["job"]:
        assert result["execution"]["job"] == response["job"]
    assert result["projection"]["budget_met"] is True
    assert result["projection"]["actual_response_bytes"] <= budget


@pytest.mark.parametrize("job_status,run_status,operation_status", [
    ("completed", "success", "succeeded"), ("failed", "error", "failed"),
])
def test_f1_terminal_jobs_are_not_background_waits(job_status, run_status, operation_status):
    response = pending_response()
    response["request_status"] = "completed"
    run = response["tool_runs"][0]
    run.update(status=run_status, operation_status=operation_status, evidence_status="rebuild_required", request_status="completed")
    run["job"]["status"] = job_status
    response["job"] = deepcopy(run["job"])
    result = public(response)
    assert result["request_valid"] is True and result["execution_completed"] is True
    assert result["data_available"] is False  # success still needs observed bars
    assert result["continuation"]["fill_plan"].get("jobs", []) == []
    assert result["execution"]["tool_runs"][0]["operation_status"] == operation_status


@pytest.mark.parametrize("failure", ["failed", "rejected", "clarification_required", "unresolved", "pending_error", "pending_clarification"])
def test_f1_invalid_requests_keep_rejection(failure):
    response = pending_response()
    if failure == "unresolved":
        response["target"] = {"type": "auto", "identity_status": "unresolved"}
        response["resolution"] = {}
    elif failure == "pending_error":
        response["error"] = {"code": "INVALID_PARAMETER"}
    elif failure == "pending_clarification":
        response["clarification"] = {"required": True}
    else:
        response.update(ok=False, request_status=failure)
    result = public(response)
    assert result["request_valid"] is False and result["execution_completed"] is False
    assert result["continuation"]["fill_plan"]["jobs"] == []


@pytest.mark.parametrize("value,method,freshness", [
    (27489035000, "provider_reported_cumulative", "stale"),
    (0, "provider_reported_cumulative", "fresh"),
    (None, "provider_reported_cumulative", "unknown"),
    (123000, "hlc3_times_volume_shares", "stale"),
])
@pytest.mark.parametrize("force_summary", [False, True])
def test_f2_public_quote_budget_preserves_amount_evidence(value, method, freshness, force_summary):
    response = response_for(["quote.snapshot"], budget=65536 if force_summary else 350000)
    amount = {"value": value, "currency": "TWD", "trade_date": "2026-10-28",
        "event_time": "2026-10-28T11:47:46.903235+08:00", "received_at": "2026-10-28T11:48:04+08:00",
        "provider": "fugle_marketdata", "source": "fugle_intraday_quote", "source_field": "total.tradeValue",
        "scope": "regular_session_board_lot_cumulative", "authority": "vendor", "official": False,
        "method": method, "estimated": method != "provider_reported_cumulative", "raw_result_id": 935562,
        "freshness": freshness, "freshness_basis": "cumulative_event_time",
        "checked_at": "2026-10-28T11:48:24+08:00", "fresh_amount_usable": value is not None and freshness == "fresh"}
    response["result"]["data"]["compact"]["quote"] = {
        "price": 2400, "volume_unit": "shares", "trade_date": "2026-10-28",
        "event_time": "2026-10-28T11:48:20+08:00", "freshness_status": "current",
        "cumulative_trade_value": value, "cumulative_trade_value_evidence": amount,
        "bid_levels": [{"price": 2400 - i, "volume": 1000,
            "source_evidence": {str(part): "x" * 4000 for part in range(4)}} for i in range(5)]}
    result = public(response)
    quote = result["evidence"]["data"]["quote.snapshot"]
    if force_summary:
        assert quote["projection_level"] == "summary"
        assert result["projection"]["pre_projection_bytes"] > 65536
    assert quote["cumulative_trade_value"] == value
    assert quote["cumulative_trade_value_evidence"] == amount
    assert quote["event_time"] != amount["event_time"]
    assert result["projection"]["budget_met"] is True


def test_f3_generated_intent_public_mcp_command_and_cache_only_resume(db, monkeypatch):
    from app.ai import ask as ask_module, agentic_common
    from app.jobs import taiwan_intraday_demand as demand
    from app.jobs import service as jobs
    from app.db.models import JobRun
    monkeypatch.setattr(ask_module.portfolio_service, "get_position_context_for_scope", lambda *a, **kw: None)
    monkeypatch.setattr(demand, "_now", lambda: NOW)
    monkeypatch.setattr(agentic_common, "_now", lambda: NOW)
    submitted = []
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda *a, **kw: submitted.append((a, kw)))
    request = AiAskRequest(contract_version="omi.decision.v4", question="6488 intraday evidence",
        target={"type": "tw_stock", "id": "6488", "market": "TW"}, mode="data_only", output="evidence_only",
        selection={"include": ["intraday.bars"], "max_response_bytes": 350000}, payload_level="full",
        realtime_policy="cache_only", allow_external_fetch=False, allow_write=False, allow_llm=False,
        refresh_policy={"before_answer": False})
    initial = ask_module.ask(db, request)
    invoke = initial["continuation"]["fill_plan"]["actions"][0]["invoke"]["arguments"]
    assert invoke["analysis_horizon"] == "intraday"
    assert submitted == [] and db.query(JobRun).count() == 0
    with patch.dict("os.environ", {}, clear=True):
        server = load_server_module()
    monkeypatch.setattr(server, "AI_TRUST_TOKEN", "offline-fixture")
    monkeypatch.setattr(server, "TRUSTED_DEFAULT_EXTERNAL_FETCH", True)
    args = {key: value for key, value in invoke.items() if key not in {"allow_external_fetch", "allow_llm", "allow_write"}}
    forwarded = server._ask_payload(args)
    assert forwarded["allow_external_fetch"] is True
    assert forwarded["allow_llm"] is False and forwarded["allow_write"] is False
    assert forwarded["continuation"] == invoke["continuation"]
    trusted = ask_module.AiAskServerPolicy(can_external_fetch=True)
    result = ask_module.ask(db, AiAskRequest(**forwarded), server_policy=trusted)
    assert len(submitted) == 1
    assert result["request_valid"] is True and result["execution_completed"] is False
    job_id = result["continuation"]["fill_plan"]["jobs"][0]["job_id"]
    jobs.complete_job(db, job_id, result={"status": "completed"})
    resume = refresh_status.read_refresh_status(db=db, job_id=job_id)["resume"]["arguments"]
    assert resume["analysis_horizon"] == "intraday"
    assert resume["market_data_params"]["trade_date"] == NOW.date().isoformat()
    assert resume["realtime_policy"] == "cache_only" and resume["allow_external_fetch"] is False
    resumed = ask_module.ask(db, AiAskRequest(**server._ask_payload({k: v for k, v in resume.items()
        if k not in {"allow_external_fetch", "allow_llm", "allow_write"}})), server_policy=trusted)
    assert len(submitted) == 1 and resumed["execution"]["tool_runs"] == []


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("date_source,explicit_clock", [("as_of", False), ("freshness", False), ("as_of", True), ("missing", False)])
def test_f4_technical_metadata_uses_analysis_clock_not_corporate_events(reverse, date_source, explicit_clock):
    payload = {"status": "current", "current": {"rsi14": 52}, "bar_count": 300,
        "corporate_action": {"affected_events": [{"trade_date": "2026-09-20",
            "event_time": "2026-09-21T13:30:00+08:00", "fetched_at": "2026-09-22T06:56:21Z"}]},
        "freshness": {"status": "current", "is_current": True},
        "quality": {"status": "current", "facts_usable": True, "decision_usable": True},
        "lineage": {"selected_source": "canonical_daily"}}
    if date_source == "as_of":
        payload["as_of"] = "2026-10-27"
    if date_source != "missing":
        payload["freshness"].update(latest_data_date="2026-10-27", finalized_daily_date="2026-10-27")
    if explicit_clock:
        payload["lineage"].update(event_at="2026-10-27T13:30:00+08:00", fetched_at="2026-10-27T06:56:21Z")
    fields = list(payload)
    if reverse:
        fields.reverse()
    response = response_for(["technical.indicators"], fields={"technical.indicators": fields})
    response["generated_at"] = "2026-10-28T04:00:00Z"
    response["result"]["data"]["compact"]["technical_indicators"] = dict((key, payload[key]) for key in fields)
    result = public(response)
    quality = result["evidence"]["capability_status"]["technical.indicators"]
    assert quality["trade_date"] == (None if date_source == "missing" else "2026-10-27")
    assert quality["as_of"] == (None if date_source == "missing" else "2026-10-27")
    assert quality["event_time"] == ("2026-10-27T13:30:00+08:00" if explicit_clock else None)
    assert quality["fetched_at"] == ("2026-10-27T06:56:21Z" if explicit_clock else None)
    assert quality["freshness_status"] == "current"
    assert quality["facts_usable"] is True
    assert result["evidence"]["data"]["technical.indicators"]["corporate_action"] == payload["corporate_action"]


def watchlist_response(compact, *, include, limits=None):
    response = response_for(include)
    response["target"] = {"type": "tw_watchlist", "id": "36", "market": "TW"}
    response["resolution"] = {"target": response["target"]}
    response["query_plan"] = {"target_type": "watchlist", "payload_level": "full",
        "selection": contract.normalize_selection(selection={"include": include,
            "limits": limits or {}, "max_response_bytes": 350000}, output="evidence_only",
            realtime_policy="cache_only", payload_level="full", scope_type="watchlist", target_market="TW",
            question_intent="ranking")}
    response["result"]["data"]["compact"] = compact
    return response


@pytest.mark.parametrize("capability", ["watchlist.ranking", "watchlist.radar"])
@pytest.mark.parametrize("limit,count", [(3, 27), (27, 27), (None, 3), (3, 0)])
def test_f5_public_ranked_results_keep_leaders_and_actual_returned_count(capability, limit, count):
    rows = [{"rank": rank, "stock_id": str(2300 + rank), "score": 0 if rank == 1 else None,
             "volume": 0 if rank == 1 else None, "volume_unit": "share"} for rank in range(1, count + 1)]
    payload = {"ranked_count": count, "matched_count": count, "returned_count": count,
               "results": rows, "is_current": True}
    result = public(watchlist_response({capability.split(".")[1]: payload}, include=[capability],
        limits={capability: limit} if limit is not None else None))
    projected = result["evidence"]["data"][capability]
    expected = rows[:limit] if limit is not None else rows
    assert projected["results"] == expected
    assert projected["returned_count"] == len(expected)
    assert projected["ranked_count"] == count
    if capability == "watchlist.radar":
        assert projected["matched_count"] == count
    assert payload["results"] == rows and payload["returned_count"] == count


@pytest.mark.parametrize("capability", ["watchlist.ranking", "watchlist.radar"])
def test_f5_missing_ranked_results_do_not_invent_counts(capability):
    result = public(watchlist_response({capability.split(".")[1]: {"ranked_count": None}}, include=[capability]))
    projected = result["evidence"]["data"][capability]
    assert projected["ranked_count"] is None
    assert "results" not in projected and "returned_count" not in projected


def test_f5_bar_selection_still_keeps_latest_tail():
    response = response_for(["intraday.bars"])
    response["query_plan"]["selection"]["limits"]["intraday.bars"] = 3
    points = [{"time": f"2026-10-28T09:{minute:02d}:00+08:00", "price": 100, "volume": 0} for minute in range(27)]
    response["result"]["data"]["compact"]["intraday_bars"] = {
        "points": points, "point_count": 27, "interval": "1m", "volume_unit": "shares"}
    projected = public(response)["evidence"]["data"]["intraday.bars"]
    assert projected["points"] == points[-3:]
    assert projected["point_count"] == 27 and projected["returned_point_count"] == 3


@pytest.mark.parametrize("volume,known_unit", [(1033911, True), (0, True), (None, True), (1033911, False)])
def test_f6_canonical_volume_unit_survives_signal_ranking_compact_and_quality(monkeypatch, volume, known_unit):
    from decimal import Decimal
    from app.market import technical_indicator_gateway as gateway
    from app.market import signal_service
    from app.market_data.contracts import Quantity, QuantityUnit
    from app.watchlists import ranking_service
    from app.ai.market_context.taiwan_watchlist import _build_watchlist_compact
    from test_tw_technical_service import _series

    series = _series()
    bars = tuple(bar.model_copy(update={"volume": Quantity(value=Decimal(volume), unit=QuantityUnit.SHARE)
        if volume is not None else None}) for bar in series.bars)
    series = series.model_copy(update={"bars": bars})
    reads = []
    def read_bars(self, **kwargs):
        reads.append(kwargs)
        return series
    monkeypatch.setattr(gateway.TaiwanBarService, "read_bars", read_bars)
    if not known_unit:
        # Legacy/untyped points cannot acquire a guessed market-wide unit.
        monkeypatch.setattr(signal_service, "calculate_active_daily_indicators", lambda **kw: [
            {"time": bars[-1].start_at.date(), "close": 100, "volume": volume}])
    monkeypatch.setattr(ranking_service, "_market_context_by_stock", lambda **kw: {})
    rows = ranking_service._build_watchlist_ranking_rows(db=None,
        items=[{"stock_id": "2330", "stock_name": "fixture"}], ma_windows=None,
        volume_ma_windows=None, limit=100, volume_ratio_threshold=None, use_intraday=False, intraday_limit=60)
    compact = _build_watchlist_compact(group_id=36, group_name="fixture", ranking={
        "ranked_count": 1, "is_current": True, "results": rows}, radar={}, payload_level_value="full")
    result = public(watchlist_response(compact, include=["watchlist.ranking"]))
    row = result["evidence"]["data"]["watchlist.ranking"]["results"][0]
    quality = result["evidence"]["quality"]["capabilities"]["watchlist.ranking"]
    assert row["volume"] == volume
    assert row.get("volume_unit") == ("share" if known_unit and volume is not None else None)
    assert ("volume_unit_missing" in quality["issues"]) is (volume is not None and not known_unit)
    if known_unit:
        assert len(reads) == 1 and reads[0]["interval"] == "1d" and reads[0]["include_partial"] is False


@pytest.mark.parametrize("receipt_status,receipt_error,activity,expected", [
    (200, None, 0, "VERIFIED_NO_TRADE"), (200, None, 5, "TRADE_ACTIVITY_WITHOUT_PRICE"),
    (500, None, 0, "MISSING_EVIDENCE"), (200, "fixture failure", 0, "MISSING_EVIDENCE"),
])
def test_f7_daily_day_state_query_projects_metadata_without_lazy_reads(db, monkeypatch, tmp_path,
        receipt_status, receipt_error, activity, expected):
    from datetime import date
    from sqlalchemy import event
    from app.config import settings
    from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
    from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
    from test_tw_daily_candidate_repository import _source_and_raw, _daily_row, _query
    monkeypatch.setattr(settings, "tw_corporate_event_cache_path", tmp_path / "missing-corporate.json")
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type="twse_daily", priority=10)
    raw.status_code, raw.error_message, raw.raw_text = receipt_status, receipt_error, "x" * 100000
    day = date(2026, 8, 21)
    row = _daily_row(source=source, raw=raw, trade_date=day, open_price=None, high_price=None,
        low_price=None, close_price=None, trade_volume=activity)
    row.trade_value = row.transaction_count = activity
    db.add(row)
    db.commit()
    db.expunge_all()
    statements = []
    def observe(_conn, _cursor, sql, _params, _ctx, _many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        states = TaiwanOfficialDailyBarRepository(db).resolve_daily_days(instrument=_query().instrument,
            start_date=day, end_date=day, resolved_bars=())
        assert len(states) == 1 and states[0].state.value == expected
        assert len(statements) == 2  # one candidate read + one metadata join, no lazy N+1
        assert all("raw_text" not in sql and "raw_file_path" not in sql and "raw_fetch_result.url" not in sql for sql in statements)
        assert "status_code" in statements[1] and "error_message" in statements[1]
        if receipt_status == 200 and receipt_error is None:
            assert states[0].lineage[0].content_hash.startswith("hash-")
            assert states[0].lineage[0].raw_receipt_id.startswith("raw_fetch_result:")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
