"""Negative and lifecycle acceptance for the single Base-1m command owner."""
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, JobRun, StockMaster
from app.jobs import taiwan_intraday_demand as demand
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_capabilities import TW_INTRADAY_DESCRIPTORS, YAHOO_INTRADAY_PROVIDER
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2

NOW = datetime(2026, 9, 21, 15, 0, tzinfo=TAIWAN_TZ)
INSTRUMENT = InstrumentKey(market=Market.TW, symbol="2330", venue="TWSE", instrument_type=InstrumentType.STOCK)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'convergence.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE",
            instrument_type=kind, is_active=active)
            for symbol, kind, active in (("2330", "stock", True), ("0050", "etf", True), ("2317", "stock", False))])
        db.commit()
    dispatched = []
    monkeypatch.setattr(demand.jobs, "SessionLocal", factory)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: dispatched.append(job_id))
    monkeypatch.setattr(demand, "_now", lambda: NOW)
    yield SimpleNamespace(factory=factory, dispatched=dispatched)
    engine.dispose()


def requirement(day, now=NOW):
    return build_taiwan_intraday_requirement(instrument=INSTRUMENT, interval="1m", range_value="1d",
        policy=RealtimePolicy.PREFER_LIVE, requested_at=now, acquiring=True, target_trade_date=day)


def test_dated_route_uses_historical_reach_not_query_span():
    recent = requirement(date(2026, 9, 18))
    plan = plan_data_acquisition_v2(recent, TW_INTRADAY_DESCRIPTORS)
    assert [route.provider_key for route in plan.routes] == [YAHOO_INTRADAY_PROVIDER]
    assert recent.request.acquisition_window == "dated"
    old = requirement(date(2026, 9, 15))
    assert (old.request.end_at - old.request.start_at).total_seconds() == 4.5 * 3600
    assert not plan_data_acquisition_v2(old, TW_INTRADAY_DESCRIPTORS).routes


def test_completed_today_allows_current_date_source_but_never_previous_date():
    same_day = plan_data_acquisition_v2(requirement(NOW.date()), TW_INTRADAY_DESCRIPTORS)
    assert [route.provider_key for route in same_day.routes] == ["nstock", YAHOO_INTRADAY_PROVIDER]
    previous = plan_data_acquisition_v2(requirement(date(2026, 9, 18)), TW_INTRADAY_DESCRIPTORS)
    assert "nstock" not in [route.provider_key for route in previous.routes]


def test_yahoo_http_receives_exact_target_window(monkeypatch):
    from app.market.providers import tw_intraday_bars as adapter
    captured = []
    monkeypatch.setattr(adapter, "http_get", lambda url, **kw: (
        captured.append(kw) or SimpleNamespace(text='{"chart":{"result":[]}}', url=url, status_code=200, headers={})))
    req = requirement(date(2026, 9, 18))
    window, interval, _ = adapter._provider_query(req)
    adapter._default_yahoo_reader("2330", "TWSE", window, interval, 5)
    params = captured[0]["params"]
    assert "range" not in params
    assert datetime.fromtimestamp(params["period1"], TAIWAN_TZ) == datetime(2026, 9, 18, 9, tzinfo=TAIWAN_TZ)
    assert datetime.fromtimestamp(params["period2"], TAIWAN_TZ) == datetime(2026, 9, 18, 13, 30, tzinfo=TAIWAN_TZ)


def test_completed_etf_admitted_and_inactive_rejected(env):
    with env.factory() as db:
        job, created = demand.enqueue_intraday_materialization_demand(db, stock_id="0050",
            requested_at=NOW, consumer="scheduler")
        request = demand.materialization_request(job)
        assert created and request["instrument_type"] == "etf"
        assert request["mode"] == "completed_session_repair"
        assert "2026-09-21" in job.target
        with pytest.raises(ValueError, match="active"):
            demand.enqueue_intraday_materialization_demand(db, stock_id="2317", requested_at=NOW, consumer="viewer")
        with pytest.raises(ValueError, match="NOT_LIVE"):
            demand.enqueue_intraday_materialization_demand(db, stock_id="0050", requested_at=NOW,
                consumer="ai", policy="require_live")


def test_success_revalidated_for_new_minute_without_reusing_episode_ttl(env, monkeypatch):
    state = {"ready": True}
    monkeypatch.setattr(demand, "_reread", lambda *args: {"reread_ready": state["ready"], "current_session_bar_count": 60})
    now = NOW.replace(hour=10)
    with env.factory() as db:
        first, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=now, consumer="viewer")
        assert first.status == "success" and not env.dispatched
        first_id = first.id
        state["ready"] = False
        next_job, created = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=now + timedelta(minutes=1), consumer="viewer")
        assert created and next_job.id != first_id and next_job.status == "running"
        assert len(env.dispatched) == 1


def test_active_goal_merge_never_expands_budget_or_deadline(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *args: {"reread_ready": False, "current_session_bar_count": 0})
    now = NOW.replace(hour=10)
    with env.factory() as db:
        first, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=now,
            consumer="ai", max_external_calls=1, timeout_seconds=60)
        original = demand.materialization_request(first)
        same, created = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=now + timedelta(seconds=30),
            consumer="viewer", policy="require_live")
        merged = demand.materialization_request(same)
        assert not created and same.id == first.id
        assert merged["expires_at"] == original["expires_at"]
        assert merged["max_external_calls"] == 1 and merged["max_attempts"] == 1
        assert merged["realtime_policy"] == "require_live"
        assert len(env.dispatched) == 1


def test_success_backoff_blocks_acquisition_but_cannot_claim_new_goal_ready(env, monkeypatch):
    state = {"ready": True}
    monkeypatch.setattr(demand, "_reread", lambda *args: {"reread_ready": state["ready"], "current_session_bar_count": 5})
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai")
        result = json.loads(job.result_json)
        result["retry_not_before_at"] = (NOW + timedelta(minutes=10)).isoformat()
        job.result_json = json.dumps(result)
        db.commit()
        state["ready"] = False
        newer, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW + timedelta(seconds=1), consumer="ai")
        assert newer.status == "error" and newer.id != job.id
        assert json.loads(newer.result_json)["reason_code"] == "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF"
        assert not env.dispatched


def test_terminal_cas_cannot_lose_goal_from_other_connection(env, monkeypatch):
    monkeypatch.setattr(demand, "_reread", lambda *args: {"reread_ready": False, "current_session_bar_count": 5})
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai")
        expected = job.request_json
        with env.factory() as other:
            winner = other.get(JobRun, job.id)
            request = json.loads(winner.request_json)
            request["postcondition_version"] = "stronger-test-goal"
            winner.request_json = json.dumps(request)
            other.commit()
        assert job.request_json == expected
        demand._finish(db, job, {"reread_ready": True, "current_session_bar_count": 5}, "OLD_GOAL_READY")
        assert job.status != "success"
        assert json.loads(job.result_json)["reread_ready"] is False


def test_historical_reread_pins_date_and_real_receipt_cutoff(env, monkeypatch):
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(session_resolution=[SimpleNamespace(trade_date=date(2026,9,18),
            coverage_status=SimpleNamespace(value="partial"))], bars=(), identity=SimpleNamespace(series_revision="a"*64))
    monkeypatch.setattr(demand, "TaiwanBarService", lambda db: SimpleNamespace(read_bars=read))
    with env.factory() as db:
        result = demand._reread(db, {"stock_id":"2330", "trade_date":"2026-09-18"}, NOW)
    assert result["reread_ready"] is False
    assert calls[0]["from_time"].date() == date(2026,9,18)
    assert calls[0]["requested_at"] == NOW


def test_chart_command_preserves_range_interval_and_exposes_pending(env, monkeypatch):
    from app.jobs import taiwan_intraday_commands as command
    monkeypatch.setattr(command, "get_market_intraday_history", lambda **kw: {
        "interval": kw["interval"], "range": kw["range_value"], "point_count":0, "limitations":[]})
    with env.factory() as db:
        result = command.refresh_intraday_history_command(db, stock_id="2330", interval="5m",
            range_value="1mo", policy="prefer_live", requested_at=NOW, wait_seconds=0)
        assert result["interval"] == "5m" and result["range"] == "1mo"
        assert result["acquisition_status"] == "pending"
        assert len(result["materialization_jobs"]) <= 3
        assert result["repair_scope"]["unattempted_trade_dates"]
        assert "TW_INTRADAY_REPAIR_WINDOW_BOUNDED" in result["limitations"]
        requests = [demand.materialization_request(row) for row in db.query(JobRun).all()]
        assert sum(row["max_external_calls"] for row in requests) <= 6


def test_historical_policy_requires_target_date_snapshot(monkeypatch):
    from app.market import tw_disposition as disposition
    current = {"fetched_at": NOW.isoformat(), "entries": [], "last_error": None}
    payload = {"providers": {"twse": current}}
    monkeypatch.setattr(disposition, "read_taiwan_disposition_cache", lambda **kw: payload)
    unknown = disposition.get_taiwan_disposition_status("2330", market="TWSE", now=NOW, trade_date=date(2026,9,18))
    assert unknown["cache_status"] == "historical_unknown" and unknown["is_active"] is None
    payload["daily_snapshots"] = {"2026-09-18": {"twse": {**current, "fetched_at": "2026-09-18T14:00:00+08:00"}}}
    known = disposition.get_taiwan_disposition_status("2330", market="TWSE", now=NOW, trade_date=date(2026,9,18))
    assert known["cache_status"] == "current" and known["is_active"] is False
    assert known["checked_at"] == NOW


def test_dated_provider_persists_then_exact_day_canonical_read_completes(env, monkeypatch):
    from app.market import tw_disposition as disposition
    from app.market.providers.tw_intraday_bars import IntradayProviderPayload, YahooIntradayAdapter
    from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
    day = date(2026,9,18)
    start = datetime(2026,9,18,9,tzinfo=TAIWAN_TZ)
    timestamps = [int((start + timedelta(minutes=i)).timestamp()) for i in range(265)]
    raw = json.dumps({"chart":{"result":[{"timestamp":timestamps,"indicators":{"quote":[{
        "open":[100]*265,"high":[101]*265,"low":[99]*265,"close":[100]*265,"volume":[1000]*265}]}}]}})
    monkeypatch.setattr(disposition, "read_taiwan_disposition_cache", lambda **kw: {
        "providers":{"twse":{"fetched_at":"2026-09-18T14:00:00+08:00", "entries":[], "last_error":None}}})
    yahoo = YahooIntradayAdapter(lambda *args: IntradayProviderPayload(raw_text=raw,status="available",
        url="https://fixture.invalid",status_code=200), clock=lambda: NOW)
    monkeypatch.setattr(demand, "TaiwanIntradayAcquisitionExecutor", lambda **kw:
        TaiwanIntradayAcquisitionExecutor(yahoo=yahoo, **kw))
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW,
            consumer="ai", trade_date=day.isoformat())
        job_id = job.id
    demand.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == "success", result
        assert result["reread_trade_date"] == day.isoformat()
        assert result["current_session_bar_count"] == 265
        assert result["external_call_count"] == 1
        from sqlalchemy import text
        db.execute(text("PRAGMA query_only=ON"))
        assert demand._reread(db, demand.materialization_request(job), NOW)["reread_ready"]


def test_projection_cache_observes_storage_revision_without_ttl_wait(monkeypatch):
    from app.market import intraday
    state = {"revision": "before", "calls": 0}
    monkeypatch.setattr(intraday, "_get_stock", lambda **kw: SimpleNamespace(market="TWSE"))
    monkeypatch.setattr(intraday, "TaiwanIntradayBarRepository", lambda db: SimpleNamespace(
        current_session_storage_revision=lambda **kw: state["revision"]))
    def project(db, **kw):
        state["calls"] += 1
        return intraday._cache_set(kw["cache_key"], {"revision": state["revision"]})
    monkeypatch.setattr(intraday, "_load_intraday_trend_uncached", project)
    assert intraday.get_intraday_trend(object(), "revision-test")["revision"] == "before"
    intraday.get_intraday_trend(object(), "revision-test")
    state["revision"] = "after"
    assert intraday.get_intraday_trend(object(), "revision-test")["revision"] == "after"
    assert state["calls"] == 2


@pytest.mark.parametrize("complete", [False, True])
def test_tw_completed_fill_survives_public_projection_and_normalized_scope(monkeypatch, complete):
    from app.ai import capability_contract as contract
    from app.market import tw_intraday_platform as platform
    monkeypatch.setattr(platform, "completed_taiwan_intraday_repair_eligibility", lambda *a, **kw:
        {"completed": True, "eligible": True, "reason_code": "TW_COMPLETED_SESSION_REPAIR_ELIGIBLE"})
    selection = contract.normalize_selection(selection={"required": ["intraday.bars"]},
        output="evidence_only", realtime_policy="prefer_live", payload_level="full",
        scope_type="stock", question_intent="quote")
    value = {"kind": "intraday_bars", "expected_trade_date": "2026-09-21",
        "is_partial": not complete, "points": [], "point_count": 265 if complete else 0,
        "series_coverage": {"requested_coverage_satisfied": complete},
        "freshness": {"snapshot_phase": "ready" if complete else "degraded"}}
    projected, _ = contract.project_selected_data(
        response={"result": {"data": {"intraday_bars": value}}}, selection=selection)
    assert projected["intraday.bars"]["series_coverage"] == value["series_coverage"]
    manifest = contract.build_manifest(canonical={"ok": True, "request_status": "completed",
        "target": {"type": "tw_stock", "id": "2330"}, "evidence": {}},
        selection=selection, projected_data=projected)
    item = next(row for row in manifest["capabilities"] if row["capability"] == "intraday.bars")
    assert item["fill_state"]["satisfied"] is complete
    assert item["refresh_possible_now"] is not complete
    assert item["refresh_requires_market_open"] is False


def test_sparse_completed_session_keeps_more_than_32_missing_ranges():
    from app.market.tw_bar_contracts import TaiwanCurrentSessionCoverage, TaiwanMissingBarRange
    start = NOW.replace(hour=9, minute=0)
    gaps = tuple(TaiwanMissingBarRange(start_at=start + timedelta(minutes=i * 2),
        end_at=start + timedelta(minutes=i * 2 + 1), bucket_count=1) for i in range(48))
    coverage = TaiwanCurrentSessionCoverage(trade_date=NOW.date(), status="sparse",
        session_completed=True, snapshot_phase="degraded", snapshot_revision="a" * 64,
        snapshot_reason_codes=("TW_CHART_SNAPSHOT_SPARSE",),
        snapshot_bar_count=48, snapshot_available_from=start, snapshot_available_to=start + timedelta(minutes=96),
        expected_from=start, expected_to=start + timedelta(minutes=96), expected_bucket_count=96,
        observed_bucket_count=48, missing_bucket_count=48, missing_ranges=gaps,
        repair_recommended=True, repair_operation_id="tw.refresh_intraday_bars")
    assert len(coverage.missing_ranges) == 48
    assert sum(gap.bucket_count for gap in coverage.missing_ranges) == coverage.missing_bucket_count


def test_reread_failure_preserves_external_call_ledger(env, monkeypatch):
    reads = []
    def reread(*args):
        reads.append(True)
        if len(reads) == 3:
            raise ValueError("canonical read failed")
        return {"reread_ready": False, "current_session_bar_count": 0}
    monkeypatch.setattr(demand, "_reread", reread)
    monkeypatch.setattr(demand, "refresh_taiwan_intraday_bars", lambda *a, **kw: SimpleNamespace(
        acquisition=SimpleNamespace(external_calls=1, limitations=()),
        persistence=SimpleNamespace(observations_written=73, attempted=True, committed=True)))
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id="2330", requested_at=NOW, consumer="ai")
        job_id = job.id
    demand.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert job.status == "error" and result["reread_ready"] is False
        assert result["external_call_budget_used"] == 2
        assert result["external_call_count"] == 1 and result["bars_written_count"] == 73


def test_tw_continuation_binds_exact_date_and_interval():
    from app.ai import capability_contract as contract
    target = {"type": "tw_stock", "id": "2704", "market": "TW"}
    params = {"trade_date": "2026-09-21", "intraday_interval": "5m"}
    selection = contract.normalize_selection(selection={"required": ["intraday.bars"]},
        output="evidence_only", realtime_policy="prefer_live", payload_level="full",
        scope_type="stock", question_intent="quote")
    action = contract.fill_action_id(capability_id="intraday.bars", target=target, market_data_params=params)
    continuation = {"plan_id": contract.fill_plan_id(target=target, action_ids=[action]),
        "plan_action_ids": [action], "selected_action_ids": [action]}
    assert contract.selected_fill_capabilities(continuation=continuation, selection=selection,
        target=target, scope_type="stock", market_data_params=params) == ("intraday.bars",)
    for invalid in ({**params, "trade_date": "2026-09-18"}, {**params, "intraday_interval": "1m"}):
        with pytest.raises(ValueError, match="unknown or non-executable"):
            contract.selected_fill_capabilities(continuation=continuation, selection=selection,
                target=target, scope_type="stock", market_data_params=invalid)


@pytest.mark.parametrize("policy,allow_fetch,before_answer,expected", [
    ("prefer_live", True, True, 1), ("cache_only", True, True, 0),
    ("prefer_live", False, True, 0), ("prefer_live", True, False, 0),
])
def test_quote_only_read_allows_only_authorized_intraday_command(policy, allow_fetch, before_answer, expected):
    from app.ai.ask_tool_stage import execute_tool_stages
    from app.ai.schemas import AiAskRequest
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return {"tool_plan": {}, "tool_runs": [], "freshness": {"is_current": True}}
    execute_tool_stages(scope_type="stock", payload=AiAskRequest(question="2704 1分K", contract_version="omi.decision.v4",
        allow_external_fetch=allow_fetch, market_data_params={"trade_date": "2026-09-21"}),
        resolution=None, policy={}, query_plan={"reader_profile": "quote_only",
            "external_refresh_allowed": False, "realtime_policy": policy,
            "selected_capabilities": ["target.identity", "intraday.bars", "data.freshness", "daily.ohlcv"]},
        freshness_result={"is_current": True},
        progress=SimpleNamespace(run_tool_session=lambda **kw: kw["operation"]()), progress_callback=None,
        resolution_target=lambda value: {"type": "tw_stock", "id": "2704", "market": "TW"},
        require_scope_id=lambda *args: "2704", require_group_id=lambda *args: 1,
        refresh_before_answer_enabled=lambda value: before_answer,
        run_us_stock_tool_session=run, run_tw_stock_tool_session=run, run_tw_watchlist_tool_session=run)
    assert len(calls) == expected
    if calls:
        assert calls[0]["requested_capabilities"] == ("intraday.bars",)
        assert calls[0]["trade_date"] == "2026-09-21"


def test_interactive_materialization_is_not_starved_by_general_or_background_work(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import BoundedSemaphore, Event
    from app.jobs import service
    release = Event()
    interactive_done = Event()
    monkeypatch.setattr(service, "_executor", ThreadPoolExecutor(max_workers=1))
    monkeypatch.setattr(service, "_materialization_executors", {})
    monkeypatch.setattr(service, "_materialization_slots", {
        "market_interactive": BoundedSemaphore(2), "market_background": BoundedSemaphore(1)})
    try:
        service.submit_job_task(lambda job_id: release.wait(5), 1)
        service.submit_job_task(lambda job_id: release.wait(5), 2, execution_lane="market_background")
        with pytest.raises(RuntimeError, match="QUEUE_FULL"):
            service.submit_job_task(lambda job_id: None, 3, execution_lane="market_background")
        service.submit_job_task(lambda job_id: interactive_done.set(), 4, execution_lane="market_interactive")
        assert interactive_done.wait(2), "interactive command was starved by another lane"
    finally:
        release.set()
        service.shutdown_job_executor(wait=True)
