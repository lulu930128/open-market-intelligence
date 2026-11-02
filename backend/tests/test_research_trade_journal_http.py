"""F05 HTTP source acceptance: in-process ASGI and isolated SQLite only."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import json
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import MarketDailyPrice, MarketDailyPriceLineage, MarketDailyPriceRevision, RawFetchResult, SourceRegistry, StockMaster
from app.db.session import get_db
from app.research import trade_journal_http_service as service
from app.research.trade_journal import proposal_versions
from app.routers.research_trade_journal import router
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from test_research_trade_journal import (
    AS_OF, DATES, DECISION, UTC, bar, costs, engine, evidence, path, strategy,
)


PREFIX = "/api/research/trade-proposals"


class OfflineClient:
    def __init__(self, app):
        self.app = app

    def request(self, method, url, *, body=None, params=None):
        messages = []

        async def run():
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"",
                        "more_body": False}

            async def send(message):
                messages.append(message)

            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                            "method": method, "scheme": "http", "path": url, "raw_path": url.encode(),
                            "query_string": urlencode(params or {}).encode(),
                            "headers": [(b"content-type", b"application/json")], "client": ("offline", 1),
                            "server": ("offline", 80)}, receive, send)

        asyncio.run(run())
        return SimpleNamespace(status_code=messages[0]["status"],
                               body=json.loads(b"".join(item.get("body", b"") for item in messages[1:])))

    def post(self, url, body):
        return self.request("POST", url, body=body)

    def get(self, url, **params):
        return self.request("GET", url, params=params)


@pytest.fixture
def api(engine, monkeypatch):
    state = {"now": DECISION, "readonly": False}
    monkeypatch.setattr(service, "utc_now", lambda: state["now"])
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    statements = []

    def get_fixture_db():
        with Session(engine) as db:
            if state["readonly"]:
                db.execute(text("PRAGMA query_only=ON"))
            yield db

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    app.dependency_overrides[get_db] = get_fixture_db
    event.listen(engine, "before_cursor_execute", capture)
    yield OfflineClient(app), state, statements
    event.remove(engine, "before_cursor_execute", capture)


def creation_body(price_basis="unadjusted:v1", **changes):
    ev = evidence().model_dump(mode="json")
    ev["price_basis"] = price_basis
    result = dict(symbol="2330", evidence=ev, strategy=strategy().model_dump(mode="json"),
                  costs=costs().model_dump(mode="json"), change_reason="Initial HTTP research")
    result.update(changes)
    return result


def create(api, **changes):
    response = api[0].post(PREFIX, creation_body(**changes))
    assert response.status_code == 201, response.body
    return response.body["proposal"]


def test_outcome_7_20_legacy_hash_ambiguity_unfilled_and_cutoff(api, engine):
    import inspect as python_inspect
    import pydantic
    from pydantic import Field
    from app.research import trade_journal
    from app.research.trade_proposal import content_hash
    from app.watchlists.radar_outcome_v2_service import trading_dates_after

    client, clock, statements = api
    assert "exclude_if" in python_inspect.signature(Field).parameters, pydantic.__version__
    legacy = create(api)
    with Session(engine) as db:
        legacy_row = db.execute(select(proposal_versions).where(
            proposal_versions.c.revision_id == legacy["revision_id"])).one()
        assert "outcome_horizon_sessions" not in json.loads(legacy_row.payload_json)
        decoded = trade_journal._decode(legacy_row)
        assert content_hash(decoded.model_dump(mode="json")) == legacy_row.payload_hash
        assert decoded.outcome_horizon_sessions is None
    saved20 = create(api, horizon_sessions=20, costs={"version": "unknown-cost"})
    saved7 = create(api, horizon_sessions=7,
        strategy=strategy(entry_rule="at_or_above", entry_price=105).model_dump(mode="json"))
    assert saved20["outcome_horizon_sessions"] == 20 and saved7["outcome_horizon_sessions"] == 7
    assert len(saved20["planned_trade_dates"]) == 20
    assert saved20["planned_trade_dates"] == [d.isoformat() for d in trading_dates_after(DECISION.date(), 20)]
    assert (datetime.fromisoformat(saved20["planned_trade_dates"][-1]).date() - DECISION.date()).days > 20
    dates20 = tuple(datetime.fromisoformat(day).date() for day in saved20["planned_trade_dates"])
    cutoff = datetime.combine(dates20[-1], time(10), UTC)
    clock.update(now=cutoff + timedelta(days=2), readonly=True)
    statements.clear()
    assert client.get(f"{PREFIX}/{legacy['creation_id']}").body["proposal"] == legacy
    assert len(client.get(f"{PREFIX}/{legacy['creation_id']}").body["proposal"]["planned_trade_dates"]) == 15
    bars = [bar(day) for day in dates20]

    def outcome(proposal, horizon=None, supplied=None, as_of=cutoff):
        body = {"decision_at": DECISION.isoformat(), "outcome_as_of": as_of.isoformat(),
                "bars": [item.model_dump(mode="json") for item in (bars if supplied is None else supplied)]}
        if horizon is not None:
            body["horizon_sessions"] = horizon
        response = client.post(f"{PREFIX}/{proposal['creation_id']}/paper-outcome", body)
        assert response.status_code == 200, response.body
        return response.body

    for saved in (legacy, saved20):
        assert [o["horizon_sessions"] for o in outcome(saved)["evaluation"]["outcomes"]] == [10, 15]
    unfilled = outcome(saved7, 7)
    assert unfilled["status"] == "unfilled"
    assert len(unfilled["evaluation"]["outcomes"][0]["expected_trade_dates"]) == 7
    ordinary = outcome(saved20, 20)
    assessed = ordinary["evaluation"]["outcomes"][0]
    assert ordinary["status"] == "insufficient_evidence" and "cost_unknown" in ordinary["insufficient_evidence"]
    assert assessed["coverage"] == "complete" and assessed["path_metrics"]["observed_sessions"] == 20
    assert assessed["paper"]["trade_r"] is not None and assessed["paper"]["net_trade_r"] is None
    assert ordinary["setup_evaluation"]["target_scenarios"][0]["gross_rr"] == "2"
    assert assessed["bar_receipts"][0]["source_available_at"] and assessed["bar_receipts"][0]["received_at"]
    ambiguous_bars = list(bars)
    ambiguous_bars[1] = bar(dates20[1], high_price=112, low_price=94)
    ambiguous = outcome(saved20, 20, ambiguous_bars)
    assert ambiguous["status"] == "ambiguous" and ambiguous["evaluation"]["outcomes"][0]["paper"]["trade_r"] is None
    limited = outcome(saved20, 20, bars, datetime.combine(dates20[6], time(10), UTC))
    assert limited["status"] == "insufficient_evidence"
    assert limited["evaluation"]["outcomes"][0]["path_metrics"]["observed_sessions"] == 7
    assert len(limited["evaluation"]["outcomes"][0]["missing_trade_dates"]) == 13
    late = list(bars)
    late[0] = bar(dates20[0], received_at=cutoff + timedelta(days=1))
    assert outcome(saved20, 20, late)["evaluation"]["outcomes"][0]["path_metrics"] == {}
    insufficient_calendar = outcome(legacy, 20)
    assert "frozen_calendar_insufficient:15/20" in insufficient_calendar["insufficient_evidence"]
    assert insufficient_calendar["evaluation"]["outcomes"][0]["horizon_end_trade_date"] is None
    assert insufficient_calendar["evaluation"]["outcomes"][0]["paper"]["state"] != "expired"
    replay = client.post(f"{PREFIX}/{saved20['creation_id']}/paper-outcome", ordinary["replay_request"])
    assert replay.body["evaluation"] == ordinary["evaluation"]
    with Session(engine) as db:
        assert db.execute(select(proposal_versions.c.payload_json, proposal_versions.c.payload_hash).where(
            proposal_versions.c.revision_id == legacy["revision_id"])).one() == (legacy_row.payload_json, legacy_row.payload_hash)
    assert_read_only(statements)


def test_research_candidate_list_latest_revision_pagination_and_read_only(api):
    client, clock, statements = api
    first = create(api)
    clock["now"] += timedelta(seconds=1)
    second = create(api, symbol="6147")
    clock["now"] += timedelta(seconds=1)
    revised = client.post(f"{PREFIX}/{first['creation_id']}/revisions", revision_body(first))
    assert revised.status_code == 201, revised.body
    clock["readonly"] = True
    statements.clear()
    page = client.get(PREFIX, limit=1, offset=0)
    assert page.status_code == 200, page.body
    assert page.body["has_more"] and len(page.body["items"]) == 1
    assert page.body["items"][0]["proposal"]["revision_id"] == revised.body["proposal"]["revision_id"]
    assert page.body["items"][0]["setup_evaluation"] == revised.body["setup_evaluation"]
    tail = client.get(PREFIX, limit=1, offset=1)
    assert not tail.body["has_more"] and tail.body["items"][0]["proposal"]["creation_id"] == second["creation_id"]
    assert client.get(PREFIX, limit=1, offset=2).body["items"] == []
    assert_read_only(statements)


def test_research_monitor_states_current_quote_rr_revision_and_read_only(api, engine, monkeypatch):
    from decimal import Decimal
    from app.research import proposal_monitor as monitor
    from app.market import public_quote_platform as quotes
    from app.market.trading_calendar import TAIWAN_TZ
    from app.market.tw_trade_eligibility import (
        EligibilityEvidence, EligibilityEvent, EvidenceStamp, EventCoverage, EventRiskPolicy, RegulationEvidence,
    )
    from app.market_data.contracts import TradeObservationState

    client, clock, statements = api
    original = create(api, strategy=strategy(mode="confirmed", entry_rule="at_or_below").model_dump(mode="json"))
    day = datetime.fromisoformat(original["planned_trade_dates"][0]).date()
    clock["now"] = datetime.combine(day, time(10), TAIWAN_TZ)
    monkeypatch.setattr(monitor, "utc_now", lambda: clock["now"])
    active = {"price": "101", "trade": TradeObservationState.TRADE_OBSERVED, "day": day,
              "freshness": "current", "confirmation": False, "daily_calls": 0, "events": True,
              "coverage_until": original["planned_trade_dates"][-1], "regulation": False, "suspension": False}
    quote_at = clock["now"] - timedelta(seconds=1)

    def read_quote(db, *, stock_id, requested_at):
        quote = SimpleNamespace(instrument=SimpleNamespace(symbol=stock_id, venue="TWSE"),
            trade_date=active["day"], trade_state=active["trade"], last_trade_price=Decimal(active["price"]),
            lineage=SimpleNamespace(source="fixture_actual_trade", event_at=quote_at,
                received_at=quote_at, fetched_at=quote_at, content_hash="quote-" + active["price"], observation_id="quote-v1"))
        return SimpleNamespace(resolved=SimpleNamespace(quote=quote, health=SimpleNamespace(facts_usable=True)),
                               requirement=SimpleNamespace(freshness=SimpleNamespace(max_age_seconds=30)))

    def project_quote(result):
        quote = result.resolved.quote
        return {"actual_trade_occurred": quote.trade_state is TradeObservationState.TRADE_OBSERVED,
            "last_trade_is_current_session": quote.trade_date == day, "trade_date": quote.trade_date,
            "quote_time": quote_at, "received_at": quote_at, "fetched_at": quote_at,
            "freshness": {"status": active["freshness"], "age_seconds": int((clock["now"] - quote_at).total_seconds())},
            "session_phase": "regular", "source": "fixture_actual_trade", "provider": "fixture"}

    def read_eligibility(request, db):
        stamp = EvidenceStamp(source="fixture_current", as_of=day, available_at=quote_at, status="current")
        return EligibilityEvidence(stock_id=request.stock_id, market=request.market,
            regulation=RegulationEvidence(evidence=stamp, disposition_active=active["regulation"]),
            events=(EligibilityEvent(event_type="suspension", start_date=day, end_date=day,
                evidence=stamp),) if active["suspension"] else (),
            event_coverage=EventCoverage(status="complete" if active["events"] else "partial", date_from=day,
                date_to=datetime.fromisoformat(active["coverage_until"]).date(),
                covered_event_types=tuple(k for k in EventRiskPolicy.model_fields if k not in {"version", "other"}),
                sources=(stamp,)))

    def read_daily(db, *, request):
        active["daily_calls"] += 1
        assert request.mode == "confirmed" and request.stock_ids == ("2330",)
        return SimpleNamespace(request=request, coverage=SimpleNamespace(complete=active["confirmation"] is not None),
            candidates=(SimpleNamespace(direction="long", mode="confirmed", stage="research_qualified"),)
                if active["confirmation"] else (), assessments=())

    monkeypatch.setattr(quotes, "read_taiwan_public_last_trade_quote", read_quote)
    monkeypatch.setattr(quotes, "project_taiwan_public_last_trade_quote", project_quote)
    monkeypatch.setattr(monitor, "read_tw_trade_eligibility_evidence", read_eligibility)
    monkeypatch.setattr(monitor, "build_tw_swing_screening_snapshot", read_daily)
    clock["readonly"] = True
    statements.clear()

    def observe():
        response = client.get(f"{PREFIX}/{original['creation_id']}/monitor")
        assert response.status_code == 200, response.body
        assert response.body["execution_ready"] is False
        return response.body

    assert observe()["status"] == "WAITING_PRICE"
    active["price"] = "99"
    assert observe()["status"] == "WAITING_CONFIRMATION"
    active["confirmation"] = None
    assert observe()["status"] == "DATA_UNKNOWN"
    active["confirmation"] = True
    ready = observe()
    assert ready["status"] == "REVIEWABLE" and ready["confirmation"] == "TRUE"
    assert Decimal(ready["setup_evaluation"]["gross_risk"]) == 4000  # Current 99 vs frozen entry 100.
    assert ready["eligibility"]["funding_sufficient"] == "unknown"  # Research, not broker readiness.
    clock["now"] += timedelta(seconds=1)
    assert observe()["observation_id"] == ready["observation_id"]
    active["trade"] = TradeObservationState.INDICATIVE_OBSERVED
    assert observe()["status"] == "DATA_UNKNOWN"
    active["trade"] = TradeObservationState.TRADE_OBSERVED
    active["day"] = day - timedelta(days=1)
    assert observe()["status"] == "DATA_UNKNOWN"
    active["day"], active["freshness"] = day, "stale"
    assert observe()["status"] == "DATA_UNKNOWN"
    active["freshness"], active["events"] = "current", False
    partial = observe()
    assert partial["status"] == "REVIEWABLE"
    assert partial["eligibility"]["event_coverage_complete"] is False
    assert partial["eligibility"]["broker_execution_eligible"] == "unknown"
    assert "EVENT_COVERAGE_INCOMPLETE" in partial["reason_codes"]
    active["regulation"] = None
    unknown_regulation = observe()
    assert unknown_regulation["status"] == "REVIEWABLE"
    assert unknown_regulation["eligibility"]["regulation_eligible"] == "unknown"
    assert "REGULATION_UNKNOWN" in unknown_regulation["reason_codes"]
    active["regulation"] = True
    assert observe()["status"] == "INVALIDATED"  # Known disposition remains a blocker.
    active["regulation"], active["suspension"] = False, True
    assert observe()["status"] == "INVALIDATED"  # Known suspension remains a blocker.
    active["suspension"] = False
    active["events"], active["price"] = True, "94"
    assert observe()["status"] == "INVALIDATED"
    assert_read_only(statements)
    clock["readonly"] = False
    engine.dispose()  # Drop the fixture connection carrying PRAGMA query_only=ON.
    revised = client.post(f"{PREFIX}/{original['creation_id']}/revisions", {
        "expected_revision_id": original["revision_id"], "strategy": {
            **original["strategy"], "mode": "aggressive", "stop_price": 96},
        "costs": original["costs"], "change_reason": "Price-only research scenario"})
    assert revised.status_code == 201, revised.body
    clock["readonly"], active["price"] = True, "99"
    statements.clear()
    calls = active["daily_calls"]
    assert observe()["status"] == "WAITING_PRICE"  # The new revision's outcome window begins prospectively.
    day = datetime.fromisoformat(revised.body["proposal"]["planned_trade_dates"][0]).date()
    clock["now"] = datetime.combine(day, time(10), TAIWAN_TZ)
    quote_at = clock["now"] - timedelta(seconds=1)
    active["day"], active["coverage_until"] = day, revised.body["proposal"]["planned_trade_dates"][-1]
    updated = observe()
    assert updated["revision_id"] == revised.body["proposal"]["revision_id"]
    assert updated["observation_id"] != ready["observation_id"]
    assert updated["status"] == "REVIEWABLE" and updated["confirmation_basis"] == "price_only_aggressive"
    assert active["daily_calls"] == calls  # No universal daily/5m dependency for price-only mode.
    clock["now"] = datetime.combine(datetime.fromisoformat(updated["valid_until_date"]).date() + timedelta(days=1), time(10), TAIWAN_TZ)
    assert observe()["status"] == "EXPIRED"
    assert_read_only(statements)


@pytest.mark.parametrize("interval,minutes", [(5, [45, 50, 55]), (10, [45, 55])])
def test_swing_cron_starts_1545_and_keeps_evening_weekday_window(monkeypatch, interval, minutes):
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler
    from app.market.trading_calendar import TAIWAN_TZ

    monkeypatch.setattr(scheduler.settings, "enable_taiwan_swing_research_scheduler", True)
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_interval_minutes", interval)
    jobs = BackgroundScheduler(timezone="UTC")
    assert scheduler._add_taiwan_swing_research_job(jobs)
    assert len(jobs.get_jobs()) == 1 and not jobs.running
    job = jobs.get_job("taiwan_swing_research")
    assert job.func is scheduler.run_taiwan_swing_research
    assert job.coalesce and job.max_instances == 1
    trigger = job.trigger
    first = trigger.get_next_fire_time(None, datetime(2026, 11, 2, 7, 14, tzinfo=UTC))
    assert first == datetime(2026, 11, 2, 15, 45, tzinfo=TAIWAN_TZ)
    actual = [first]
    for _ in range(len(minutes)):
        actual.append(trigger.get_next_fire_time(actual[-1], actual[-1] + timedelta(seconds=1)))
    assert [(tick.hour, tick.minute) for tick in actual] == [(15, minute) for minute in minutes] + [
        (16, 45 % interval)]
    last = datetime(2026, 11, 6, 23, 60 - interval + 45 % interval, tzinfo=TAIWAN_TZ)
    assert trigger.get_next_fire_time(last, last + timedelta(seconds=1)) == datetime(
        2026, 11, 9, 15, 45, tzinfo=TAIWAN_TZ)
    assert trigger.get_next_fire_time(None, datetime(2026, 11, 7, 12, tzinfo=TAIWAN_TZ)) == datetime(
        2026, 11, 9, 15, 45, tzinfo=TAIWAN_TZ)


def test_schedule_defaults_are_five_minutes_fifty_symbols_and_tw_900s(monkeypatch):
    from app.config import Settings
    from pydantic import ValidationError

    for name in ("TAIWAN_SWING_RESEARCH_BATCH_SIZE", "TAIWAN_SWING_RESEARCH_INTERVAL_MINUTES",
                 "SCHEDULER_EOD_COVERAGE_TW_ERROR_BACKOFF_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)
    assert configured.taiwan_swing_research_batch_size == 50
    assert configured.taiwan_swing_research_interval_minutes == 5
    assert configured.scheduler_eod_coverage_tw_error_backoff_seconds == 900
    with pytest.raises(ValidationError, match="scheduler_eod_coverage_tw_error_backoff_seconds"):
        Settings(_env_file=None, scheduler_eod_coverage_tw_error_backoff_seconds=899)


def test_swing_five_minute_ticks_resume_existing_same_day_checkpoint(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from app.jobs import scheduler, taiwan_price_map_snapshot_scheduler as producer
    from app.market import tw_swing_prefilter as prefilter, tw_universe
    from app.market.trading_calendar import TAIWAN_TZ
    from app.research import stock_nomination

    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(scheduler, "SessionLocal", Mock())
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_batch_size", 50)
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_interval_minutes", 5)
    ids = [str(1000 + index) for index in range(150)]
    path = tmp_path / "data/tw_swing_discovery_checkpoint/2026-11-02.json"
    path.parent.mkdir(parents=True)
    # The first 90 symbols were checked before this schedule was adopted.
    state = {"version": "tw.swing.rotation.v1", "basis_trade_date": "2026-11-02",
        "universe_stock_ids": ids, "cursor": 90, "recheck_cursor": 0,
        "checked_symbols": ids[:90], "completed_symbols": [], "repair_attempts": {}, "errors": [],
        "last_tick_at": "2026-11-02T15:25:00+08:00", "status": "waiting_data", "sample_only": True,
        "deferred": {symbol: {"reason": "CURRENT_OFFICIAL_DAILY_NOT_QUALIFIED",
            "next_check_at": "2026-11-02T15:45:00+08:00", "research_evaluated": False,
            "retryable": False} for symbol in ids[:90]}}
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(scheduler, "_taiwan_swing_source_versions", lambda basis, symbols: {s: "v1" for s in symbols})
    monkeypatch.setattr(scheduler, "_read_taiwan_swing_released", lambda *a: (set(), {}))
    universe = Mock(side_effect=AssertionError("must resume persisted universe"))
    monkeypatch.setattr(tw_universe, "list_taiwan_stock_universe", universe)
    cheap, publish, discover = Mock(), Mock(), Mock()
    monkeypatch.setattr(prefilter, "build_tw_swing_discovery_snapshot", cheap)
    monkeypatch.setattr(producer, "produce_taiwan_price_map_snapshots", publish)
    monkeypatch.setattr(stock_nomination, "discover_trade_proposals", discover)
    for hour, minute, cursor, new_ids in [(15, 45, 130, ids[90:130]), (15, 50, 150, ids[130:]), (15, 55, 150, [])]:
        result = scheduler.run_taiwan_swing_research(now=datetime(2026, 11, 2, hour, minute, tzinfo=TAIWAN_TZ))
        assert result["status"] == "WAIT_DATA"
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["cursor"] == cursor and saved["universe_stock_ids"] == ids
        assert saved["checked_symbols"][:90] == ids[:90] and saved["completed_symbols"] == []
        assert saved["last_batch"]["new_stock_ids"] == new_ids
        assert len(saved["last_batch"]["stock_ids"]) <= 50
        assert saved["deferred"]["1000"]["reason"] == "CURRENT_OFFICIAL_DAILY_NOT_QUALIFIED"
    for operation in (universe, cheap, publish, discover):
        operation.assert_not_called()
    before = path.read_bytes()
    assert scheduler.run_taiwan_swing_research(now=datetime(2026, 11, 2, 15, 56, tzinfo=TAIWAN_TZ))["status"] == "DEFER"
    assert path.read_bytes() == before
    assert scheduler.run_taiwan_swing_research(now=datetime(2026, 10, 9, 15, 45, tzinfo=TAIWAN_TZ))["status"] == "NO_SESSION"


def test_rolling_released_batches_cursor_retry_rollover_and_cron(tmp_path, monkeypatch, api, engine):
    from unittest.mock import MagicMock
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler, taiwan_price_map_snapshot_scheduler as producer, tw_technical_input_readiness as readiness
    from app.market import tw_swing_prefilter as prefilter
    from app.market.trading_calendar import TAIWAN_TZ
    from app.research import stock_nomination

    active = {"clock": None, "qualified": False, "versions": {}, "published_at": None}
    released_owner = scheduler._read_taiwan_swing_released
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return active["clock"].astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(scheduler, "SessionLocal", MagicMock())
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_batch_size", 50)
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_interval_minutes", 10)
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_detail_symbols", 2)
    ids = [str(1000 + i) for i in range(110)]
    from app.market import tw_universe
    monkeypatch.setattr(tw_universe, "list_taiwan_stock_universe",
        lambda *a, **kw: [SimpleNamespace(stock_id=s, market="TWSE") for s in ids])
    monkeypatch.setattr(scheduler, "_taiwan_swing_source_versions",
        lambda basis, symbols: {s: active["versions"].get(s, "v1") for s in symbols})
    reads, detailed, publications, seen = [], [], [], set()
    def released(symbols, basis, cutoff):
        reads.append(list(symbols))
        return (set(symbols) if active["qualified"] else set()), {}
    monkeypatch.setattr(scheduler, "_read_taiwan_swing_released", released)
    def cheap(db, *, request, with_detail):
        assert not with_detail and len(request.stock_ids) <= 100
        rows = [SimpleNamespace(stock_id=s, market="TWSE", reason_codes=()) for s in request.stock_ids]
        return SimpleNamespace(checkpoint=SimpleNamespace(rows=rows,
            model_dump=lambda **kw: {"universe_stock_ids": list(request.stock_ids)}), top_stock_ids=request.stock_ids[:2])
    monkeypatch.setattr(prefilter, "build_tw_swing_discovery_snapshot", cheap)
    monkeypatch.setattr(readiness, "repair_taiwan_middle_gaps", lambda *a, **kw: {"status": "ready"})
    def publish(**kwargs):
        publications.append(kwargs["stock_ids"])
        assert len(kwargs["stock_ids"]) == 1 and kwargs["timeframes"] == ("daily",)
        active["clock"] += timedelta(seconds=2)
        active["published_at"] = active["clock"]
        return {"published": 1, "failed": 0}
    monkeypatch.setattr(producer, "produce_taiwan_price_map_snapshots", publish)
    def discover(db, request):
        symbol = request.stock_ids[0]
        detailed.append(symbol)
        assert active["published_at"] <= request.requested_at <= active["clock"]
        if symbol == "1000":
            raise ValueError("fixture_single_stock_source_error")
        if symbol == "1010":
            return {"status": "ready", "coverage": {"quality_status": "complete"},
                "created": 0, "deduplicated": 0, "data_blocked": 0, "candidates": []}
        if symbol == "1020":
            return {"status": "partial", "coverage": {"quality_status": "partial"},
                "created": 0, "deduplicated": 0, "data_blocked": 1,
                "candidates": [{"proposal": None, "reason_codes": ["SNAPSHOT_NOT_COMPUTED"]}]}
        repeat = symbol in seen
        seen.add(symbol)
        return {"created": int(not repeat), "deduplicated": int(repeat), "data_blocked": 0,
            "candidates": [{"proposal": {"proposal": {"creation_id": symbol, "revision_id": "r1"}}, "reason_codes": []}]}
    monkeypatch.setattr(stock_nomination, "discover_trade_proposals", discover)
    def run(hour, minute, *, day=30, month=10):
        active["clock"] = datetime(2026, month, day, hour, minute, tzinfo=TAIWAN_TZ)
        return scheduler.run_taiwan_swing_research(now=active["clock"])
    path = tmp_path / "data/tw_swing_discovery_checkpoint/2026-10-30.json"
    assert run(15, 14)["status"] == "WAIT_RELEASE" and not reads and not publications
    assert run(15, 15)["status"] == "WAIT_DATA"
    pending = json.loads(path.read_text())
    assert pending["cursor"] == 50 and len(pending["checked_symbols"]) == 50 and pending["completed_symbols"] == [] and not detailed
    active["qualified"] = True
    second = run(15, 25)
    assert reads[-1] == ids[:10] + ids[50:90] and second["created"] == 1
    checkpoint = json.loads(path.read_text())
    assert checkpoint["cursor"] == 90 and checkpoint["last_batch"]["due_stock_ids"] == ids[:10]
    assert checkpoint["last_batch"]["new_stock_ids"] == ids[50:90]
    assert "fixture_single_stock_source_error" in checkpoint["deferred"]["1000"]["reason"]
    assert checkpoint["deferred"]["1000"]["retryable"] is False
    assert checkpoint["deferred"]["1000"]["next_check_at"] is None
    assert detailed[-1] == "1001"  # Permanent error does not suppress its neighbour.
    assert checkpoint["deferred"]["1010"]["next_check_at"] == pending["deferred"]["1010"]["next_check_at"]
    assert checkpoint["deferred"]["1001"]["claimed_cutoff"] == pending["deferred"]["1001"]["claimed_cutoff"]
    assert run(15, 26)["status"] == "DEFER" and json.loads(path.read_text())["cursor"] == 90
    run(15, 35)
    assert json.loads(path.read_text())["cursor"] == 110
    run(15, 45); run(15, 55); run(16, 5)
    finished = json.loads(path.read_text())
    progress = finished["progress"]
    assert finished["status"] == finished["scan_status"] == "completed" and finished["deferred"]
    assert progress["claimed"] == progress["considered"] == progress["official_eod_qualified"] == 110
    assert progress["detailed_research_evaluated"] == len(finished["completed_symbols"]) == 9
    assert progress["pending_recheck"] == progress["deferred_due"] == 0
    assert progress["research_status"] == "sampled" and progress["quality_status"] == "partial"
    assert finished["deferred"]["1010"]["reason"] == "NO_SETUP"
    assert finished["deferred"]["1020"]["reason"] == "DATA_BLOCKED"
    assert finished["deferred"]["1010"]["next_check_at"] is finished["deferred"]["1020"]["next_check_at"] is None
    assert progress["deferred_unknown"] == 0 and progress["quality_unknown"] > 0 and progress["sample_only"] is True
    count = len(detailed)
    assert run(16, 15)["status"] == "DEFER" and len(detailed) == count
    assert detailed.count("1000") == 1  # ValueError is not a transient retry.
    assert detailed.count("1010") == detailed.count("1020") == 1
    # A hard crash immediately after the durable claim preserves the new cursor
    # and due slots. Restart continues beyond those fresh stocks, not batch one.
    crash_root = tmp_path / "crash"
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", crash_root)
    crash_path = crash_root / "data/tw_swing_discovery_checkpoint/2026-10-30.json"
    crash_path.parent.mkdir(parents=True)
    crash_path.write_text(json.dumps(pending))
    writer = scheduler._write_taiwan_swing_checkpoint
    def crash_after_claim(target, value):
        writer(target, value)
        raise KeyboardInterrupt("fixture_crash_after_claim")
    monkeypatch.setattr(scheduler, "_write_taiwan_swing_checkpoint", crash_after_claim)
    with pytest.raises(KeyboardInterrupt, match="fixture_crash_after_claim"):
        run(15, 25)
    claimed = json.loads(crash_path.read_text())
    assert claimed["cursor"] == 90 and claimed["checked_symbols"] == pending["checked_symbols"]
    assert claimed["progress"]["claimed"] == 90 and claimed["progress"]["considered"] == 50
    assert claimed["deferred"]["1050"]["operation_pending"] is True
    assert claimed["deferred"]["1050"]["next_check_at"].endswith("15:35:00+08:00")
    monkeypatch.setattr(scheduler, "_write_taiwan_swing_checkpoint", writer)
    run(15, 35)
    resumed = json.loads(crash_path.read_text())
    assert resumed["cursor"] == 110 and resumed["last_batch"]["new_stock_ids"] == ids[90:]
    assert resumed["deferred"]["1050"]["claimed_cutoff"] == claimed["deferred"]["1050"]["claimed_cutoff"]
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path)
    assert run(15, 15, day=31)["status"] == "NO_SESSION"
    # Simulate a persisted incomplete day: new day rotates after its last cursor,
    # retaining the old dated evidence instead of retrying the first 50 forever.
    old = json.loads(path.read_text()); old["cursor"] = 50
    path.write_text(json.dumps(old))
    run(15, 15, day=2, month=11)
    new = json.loads((path.parent / "2026-11-02.json").read_text())
    assert new["universe_stock_ids"][0] == ids[50] and new["cursor"] == 50
    assert json.loads(path.read_text())["status"] == "ROLLED_OVER"
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_batch_size", 100)
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path / "hundred")
    run(15, 15)
    hundred = json.loads((tmp_path / "hundred/data/tw_swing_discovery_checkpoint/2026-10-30.json").read_text())
    assert hundred["cursor"] == 100 and len(hundred["last_batch"]["stock_ids"]) == 100
    monkeypatch.setattr(scheduler.settings, "enable_taiwan_swing_research_scheduler", True)
    jobs = BackgroundScheduler(timezone="Asia/Taipei")
    assert scheduler._add_taiwan_swing_research_job(jobs)
    assert len(jobs.get_jobs()) == 1 and jobs.running is False
    trigger = jobs.get_job("taiwan_swing_research").trigger
    first = trigger.get_next_fire_time(None, datetime(2026, 11, 2, 15, 14, tzinfo=TAIWAN_TZ))
    assert (first.hour, first.minute) == (15, 45)
    assert trigger.get_next_fire_time(first, first + timedelta(seconds=1)) == first + timedelta(minutes=10)
    # A transient response failure AFTER the real G3 write must use the original
    # automatic Journal identity on retry. A second persistent transient stops.
    from requests.exceptions import ReadTimeout
    from app.market.tw_trade_eligibility import EligibilityEvidence
    from test_tw_swing_screening import _evidence
    ids[:] = ["2330", "6147"]
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path / "transient")
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: Session(engine))
    active["qualified"] = True
    inputs = {symbol: _evidence(symbol) for symbol in ids}
    for symbol, item in inputs.items():
        zones = item.price_map.payload["zones"]
        extra = [{**zones[0], "zone_id": "support2", "lower_bound": 97, "upper_bound": 98},
                 {**zones[1], "zone_id": "resistance2", "lower_bound": 102, "upper_bound": 103}]
        inputs[symbol] = item.model_copy(update={"price_map": item.price_map.model_copy(update={"payload": {**item.price_map.payload, "zones": [*zones, *extra]}})})
    monkeypatch.setattr(stock_nomination, "utc_now", lambda: active["clock"])
    monkeypatch.setattr(stock_nomination, "read_tw_swing_evidence", lambda db, request: tuple(inputs[s] for s in request.stock_ids))
    monkeypatch.setattr(stock_nomination, "read_tw_trade_eligibility_evidence", lambda request, db: EligibilityEvidence(stock_id=request.stock_id, market=request.market))
    attempts = {s: 0 for s in ids}
    def journal_discover(db, request):
        symbol = request.stock_ids[0]
        result = stock_nomination.create_nominations(db, stock_nomination.StockNomination(
            stock_ids=(symbol,), direction="long", as_of_trade_date=request.as_of_trade_date,
            requested_at=request.requested_at, nomination_origin="OMI_SCREEN"), automatic=True,
            screen_request=request.detail_request((symbol,)))
        assert result["scenarios"][0]["proposal"] is not None
        repeat = result["scenarios"][0]["deduplicated"]
        return {"status": "partial", "coverage": {"quality_status": "partial"},
            "created": int(not repeat), "deduplicated": int(repeat), "data_blocked": 0, "candidates": result["scenarios"]}
    def transient_discover(db, request):
        symbol = request.stock_ids[0]
        attempts[symbol] += 1
        if symbol == "6147":
            raise ReadTimeout("fixture_transient_twice")
        result = journal_discover(db, request)
        if attempts[symbol] == 1:
            raise TimeoutError("fixture_response_lost_after_journal_commit")
        return result
    monkeypatch.setattr(stock_nomination, "discover_trade_proposals", transient_discover)
    run(18, 15, day=27)
    transient_path = tmp_path / "transient/data/tw_swing_discovery_checkpoint/2026-10-27.json"
    first_failure = json.loads(transient_path.read_text())
    assert first_failure["progress"]["detailed_research_evaluated"] == 0
    assert first_failure["progress"]["pending_recheck"] == 2
    with Session(engine) as db:
        original = db.execute(select(proposal_versions)).all()
    assert len(original) == 1
    retry = run(18, 25, day=27)
    assert retry["deduplicated"] == 1 and attempts == {"2330": 2, "6147": 2}
    after_retry = json.loads(transient_path.read_text())
    assert after_retry["deferred"]["2330"]["research_evaluated"] is True
    assert after_retry["deferred"]["6147"]["research_attempts"] == 2
    assert after_retry["progress"]["pending_recheck"] == 0 and after_retry["status"] == "completed"
    assert after_retry["quality_status"] == "partial" and after_retry["progress"]["detailed_research_evaluated"] == 1
    run(18, 35, day=27); run(18, 45, day=27)
    assert attempts == {"2330": 2, "6147": 2}
    with Session(engine) as db:
        assert db.execute(select(proposal_versions)).all() == original

    # R1.2: bounded stable-version rotation, durable changed-source due claim,
    # mixed WAIT_DATA/fresh work, and the same immutable automatic Journal IDs.
    ids[:] = ["2891", "3481"] + [str(7000+i) for i in range(12)]
    monkeypatch.setattr(scheduler, "PROJECT_ROOT", tmp_path / "versions")
    monkeypatch.setattr(scheduler.settings, "taiwan_swing_research_batch_size", 50)
    for symbol in ids[:2]:
        item = _evidence(symbol)
        zones = item.price_map.payload["zones"]
        extra = [{**zones[0], "zone_id": "support2", "lower_bound": 97, "upper_bound": 98},
                 {**zones[1], "zone_id": "resistance2", "lower_bound": 102, "upper_bound": 103}]
        inputs[symbol] = item.model_copy(update={"price_map": item.price_map.model_copy(update={"payload": {**item.price_map.payload, "zones": [*zones, *extra]}})})
    version_path = tmp_path / "versions/data/tw_swing_discovery_checkpoint/2026-10-27.json"
    version_reads, evaluations = [], {s: 0 for s in ids[:2]}
    def versions(basis, symbols):
        version_reads.append(list(symbols))
        return {s: active["versions"].get(s, "v1") for s in symbols}
    monkeypatch.setattr(scheduler, "_taiwan_swing_source_versions", versions)
    def successful_discover(db, request):
        symbol = request.stock_ids[0]
        evaluations[symbol] += 1
        if evaluations[symbol] == 2:
            assert json.loads(version_path.read_text())["deferred"][symbol]["input_revision"] == "v1"
        result = journal_discover(db, request)
        if evaluations[symbol] == 2:
            active["versions"][symbol] = "v2-after-evaluation"
        return result
    monkeypatch.setattr(stock_nomination, "discover_trade_proposals", successful_discover)
    assert run(19, 15, day=27)["created"] == 2
    with Session(engine) as db:
        frozen = db.execute(select(proposal_versions)).all()
    assert len(frozen) == 3  # Prior transient case + two first-time R1.2 proposals.
    saved = json.loads(version_path.read_text())
    # A prior checkpoint with >10 stable evaluations proves the header probe
    # rotates rather than repeatedly inspecting only its first ten records.
    for symbol in ids[2:]:
        saved["deferred"][symbol].update(reason="RESEARCH_EVALUATED", research_evaluated=True,
            research_attempts=1, input_revision="v1", quality_status="complete", next_check_at=None)
    version_path.write_text(json.dumps(saved))
    start = len(version_reads)
    run(19, 25, day=27); run(19, 35, day=27)
    probes = version_reads[start:]
    assert [len(p) for p in probes] == [10, 10] and set().union(*map(set, probes)) == set(ids)
    assert evaluations == {"2891": 1, "3481": 1}
    # Combine a source change with WAIT_DATA and fresh stock; a crash after
    # atomic claim retains BOTH probe progress and the changed-source work.
    saved = json.loads(version_path.read_text())
    ids.append("8999")
    saved["universe_stock_ids"] = list(ids)
    saved["deferred"]["3481"].update(reason="CURRENT_OFFICIAL_DAILY_NOT_QUALIFIED", next_check_at=None)
    version_path.write_text(json.dumps(saved))
    active["versions"]["2891"] = "v2"
    monkeypatch.setattr(scheduler, "_write_taiwan_swing_checkpoint", crash_after_claim)
    with pytest.raises(KeyboardInterrupt):
        run(19, 45, day=27)
    claimed = json.loads(version_path.read_text())
    assert len(claimed["last_version_probe"]["stock_ids"]) <= 10 and claimed["version_probe_cursor"] != saved["version_probe_cursor"]
    assert claimed["last_version_probe"]["examined"] <= 50
    assert "2891" in claimed["last_batch"]["due_stock_ids"] and "3481" in claimed["last_batch"]["due_stock_ids"]
    assert claimed["last_batch"]["new_stock_ids"] == ["8999"]
    assert len(claimed["last_batch"]["due_stock_ids"]) <= 10 and len(claimed["last_batch"]["stock_ids"]) <= 50
    assert claimed["deferred"]["2891"]["input_revision"] == "v1" and claimed["deferred"]["2891"]["source_change_pending"]
    assert claimed["deferred"]["2891"]["research_attempts"] == 1
    monkeypatch.setattr(scheduler, "_write_taiwan_swing_checkpoint", writer)
    monkeypatch.setattr(scheduler, "_read_taiwan_swing_released", lambda symbols, basis, cutoff: (set(symbols) & {"2891"}, {}))
    result = run(19, 55, day=27)
    assert result["deduplicated"] == 1 and evaluations == {"2891": 2, "3481": 1}
    processed = json.loads(version_path.read_text())
    assert processed["cursor"] == claimed["cursor"] and processed["deferred"]["2891"]["input_revision"] == "v2"
    assert not processed["deferred"]["2891"]["source_change_pending"]
    active["versions"]["2891"] = "v3"
    run(20, 5, day=27); run(20, 15, day=27)
    capped = json.loads(version_path.read_text())["deferred"]["2891"]
    assert capped["version_recheck_reason"] == "SOURCE_CHANGED_DAILY_LIMIT" and capped["research_attempts"] == 2
    assert capped["input_revision"] == "v2" and capped["probed_input_revision"] == "v3" and capped["next_check_at"] is None
    assert capped["quality_status"] == "unknown" and capped["eod_qualified"] is None
    assert evaluations == {"2891": 2, "3481": 1}
    with Session(engine) as db:
        assert db.execute(select(proposal_versions)).all() == frozen

    # The actual scheduler reader pins today's date/receipt cutoff at the
    # existing official repository, and rejects yesterday, future and partial.
    from app.market import daily_price_repository
    from app.market_data.contracts import BarFinalization
    cutoff = datetime(2026, 10, 30, 16, tzinfo=TAIWAN_TZ)
    def bar(symbol, day_offset=0, receipt_offset=0, final=BarFinalization.FINAL):
        return SimpleNamespace(instrument=SimpleNamespace(symbol=symbol), start_at=cutoff+timedelta(days=day_offset),
            finalization=final, lineage=SimpleNamespace(event_at=cutoff-timedelta(hours=2),
                received_at=cutoff+timedelta(seconds=receipt_offset), fetched_at=None, raw_receipt_id="fixture"))
    def repository(db, *, available_at):
        assert available_at == cutoff
        def load(**kwargs):
            assert kwargs["trade_date"] == cutoff.date() and kwargs["include_etf"] is False
            return SimpleNamespace(bars=[bar("2337"), bar("3481", day_offset=-1), bar("2891", receipt_offset=1),
                bar("2330", final=BarFinalization.PROVISIONAL)], rejection_reasons=())
        return SimpleNamespace(load_market_universe=load)
    monkeypatch.setattr(daily_price_repository, "TaiwanOfficialDailyBarRepository", repository)
    assert released_owner(["2337", "3481", "2891", "2330"], cutoff.date(), cutoff)[0] == {"2337"}
    from app.config import Settings
    monkeypatch.setenv("TAIWAN_SWING_RESEARCH_BATCH_SIZE", "100")
    monkeypatch.setenv("TAIWAN_SWING_RESEARCH_INTERVAL_MINUTES", "5")
    configured = Settings(_env_file=None)
    assert configured.taiwan_swing_research_batch_size == 100 and configured.taiwan_swing_research_interval_minutes == 5

    # On a fresh basis, limited gap inputs cannot consume both detail slots
    # ahead of eligible research inputs. Original budgets/checkpoint still apply.
    ids[:] = ["6000", "6001", "6002", "6003"]
    monkeypatch.setattr(scheduler, "_taiwan_swing_source_versions", lambda basis, symbols: {s: "v1" for s in symbols})
    monkeypatch.setattr(scheduler, "_read_taiwan_swing_released", lambda symbols, *a: (set(symbols), {}))
    def mixed_cheap(db, *, request, with_detail):
        rows = [SimpleNamespace(stock_id=s, market="TWSE", status="limited" if s < "6002" else "eligible",
            daily_usable=s >= "6002", reason_codes=(SimpleNamespace(value="DAILY_HISTORY_GAP"),) if s < "6002" else ()) for s in request.stock_ids]
        return SimpleNamespace(checkpoint=SimpleNamespace(rows=rows, model_dump=lambda **kw: {}), top_stock_ids=("6002", "6003"))
    monkeypatch.setattr(prefilter, "build_tw_swing_discovery_snapshot", mixed_cheap)
    evaluated = []
    def record_detail(db, request):
        evaluated.extend(request.stock_ids)
        return {"status": "ready", "coverage": {"quality_status": "complete"},
            "created": 0, "deduplicated": 0, "data_blocked": 0, "candidates": []}
    monkeypatch.setattr(stock_nomination, "discover_trade_proposals", record_detail)
    run(16, 15, day=2, month=11)
    assert evaluated == ["6002", "6003"]


def test_middle_gap_month_owner_bounds_recheck_and_failure(monkeypatch):
    from unittest.mock import MagicMock
    from time import monotonic
    from app.jobs import tw_technical_input_readiness as readiness
    from app.market import tw_bar_service
    from app.market.tw_daily_day_state import TaiwanDailyDayState, TaiwanDailyState
    from app.market_data.contracts import InstrumentKey, InstrumentType, InstrumentTradability, Market
    from app.market.trading_calendar import TAIWAN_TZ
    instrument = InstrumentKey(symbol="2337", market=Market.TW, venue="TWSE", instrument_type=InstrumentType.STOCK)
    basis = datetime(2026, 10, 30, 16, tzinfo=TAIWAN_TZ)
    gap = basis.date() - timedelta(days=2)
    def day(day, state, **kw):
        return TaiwanDailyDayState(instrument=instrument, trade_date=day, state=state,
            market_open=kw.pop("market_open", True), expected_session=kw.pop("expected_session", True),
            instrument_status=kw.pop("instrument_status", InstrumentTradability.TRADABLE), **kw)
    active = {"repaired": False, "fail": False}
    def read(**kwargs):
        missing = [] if active["repaired"] else [day(gap, TaiwanDailyState.MISSING_EVIDENCE,
            blockers=("OFFICIAL_DAILY_EVIDENCE_REQUIRED",))]
        states = [*missing,
            day(gap-timedelta(days=1), TaiwanDailyState.VERIFIED_NO_TRADE),
            day(gap-timedelta(days=2), TaiwanDailyState.MARKET_CLOSED, market_open=False, expected_session=False),
            day(gap-timedelta(days=3), TaiwanDailyState.INSTRUMENT_SUSPENDED, expected_session=False,
                instrument_status=InstrumentTradability.SUSPENDED),
            day(gap-timedelta(days=4), TaiwanDailyState.MISSING_EVIDENCE,
                instrument_status=InstrumentTradability.UNKNOWN,
                blockers=("OFFICIAL_DAILY_EVIDENCE_REQUIRED", "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN")),
            day(basis.date(), TaiwanDailyState.MISSING_EVIDENCE, blockers=("OFFICIAL_DAILY_EVIDENCE_REQUIRED",))]
        dates = [basis-timedelta(days=10), basis]
        return SimpleNamespace(bars=[SimpleNamespace(start_at=d) for d in dates], day_states=states)
    monkeypatch.setattr(tw_bar_service, "TaiwanBarService", lambda db: SimpleNamespace(read_bars=read))
    attempts, calls, persisted = {}, [], []
    def monthly(**kwargs):
        calls.append(kwargs)
        assert attempts and persisted  # Durable attempt claimed before provider call.
        assert kwargs["start_date"] == kwargs["end_date"] == gap
        assert 0 < kwargs["timeout_seconds"] <= 8 and kwargs["sleep_seconds"] == 0
        if active["fail"]:
            raise TimeoutError("fixture_provider_timeout")
        active["repaired"] = True
        return {"status": "success"}
    monkeypatch.setattr(readiness, "backfill_twse_stock_day", monthly)
    monkeypatch.setattr(readiness, "backfill_tpex_trading_stock", monthly)
    budget = {"remaining_calls": 2, "deadline": monotonic()+30}
    db = MagicMock()
    args = dict(stock_id="2337", market="TWSE", basis=basis.date(), cutoff=basis,
        attempts=attempts, budget=budget, persist=lambda: persisted.append(True), clock=lambda: basis)
    result = readiness.repair_taiwan_middle_gaps(db, **args)
    assert result["status"] == "repaired" and result["before"]["missing_dates"] == [str(gap)]
    assert result["after"]["missing_dates"] == [] and result["after"]["blocked"]
    active.update(repaired=False, fail=True)
    repeated = readiness.repair_taiwan_middle_gaps(db, **args)
    assert repeated["reason"] == "GAP_ALREADY_ATTEMPTED_TODAY" and repeated["next_action"] == "WAIT_NEXT_TRADING_DAY"
    assert len(calls) == 1
    args.update(stock_id="6147", market="TPEX")
    failed = readiness.repair_taiwan_middle_gaps(db, **args)
    assert failed["status"] == "error" and "fixture_provider_timeout" in failed["reason"]
    assert failed["next_action"] == "REVIEW_PROVIDER_FAILURE_OR_NEXT_TRADING_DAY"
    assert budget["remaining_calls"] == 0 and len(calls) == 2
    args.update(stock_id="3481")
    assert readiness.repair_taiwan_middle_gaps(db, **args)["reason"] == "GAP_IO_OR_TIME_BUDGET"
    assert len(calls) == 2


def test_post_close_discovery_resume_repeat_dedupe_and_partial(api, engine, monkeypatch):
    from app.research import stock_nomination as nomination
    from app.market.tw_swing_prefilter import SwingDiscoveryCheckpoint, SwingDiscoveryRequest
    from app.market.tw_trade_eligibility import EligibilityEvidence
    from test_tw_swing_prefilter import _install
    from test_tw_swing_screening import _evidence, CUTOFF, REQUESTED_AT

    _, clock, _ = api
    clock["now"] = REQUESTED_AT + timedelta(hours=1)
    monkeypatch.setattr(nomination, "utc_now", lambda: clock["now"])
    inputs = {symbol: _evidence(symbol, falling=symbol == "6147") for symbol in ("2330", "6147", "9999")}
    for symbol, item in inputs.items():
        zones = item.price_map.payload["zones"]
        extra = [{**zones[0], "zone_id": "support2", "lower_bound": 97, "upper_bound": 98},
                 {**zones[1], "zone_id": "resistance2", "lower_bound": 102, "upper_bound": 103}]
        inputs[symbol] = item.model_copy(update={"price_map": item.price_map.model_copy(update={
            "payload": {**item.price_map.payload, "zones": [*zones, *extra]}})})
    inputs["9999"] = inputs["9999"].model_copy(update={"price_map": None})
    calls, _ = _install(monkeypatch, inputs)
    monkeypatch.setattr(nomination, "read_tw_swing_evidence",
                        lambda db, request: tuple(inputs[symbol] for symbol in request.stock_ids))
    monkeypatch.setattr(nomination, "read_tw_trade_eligibility_evidence",
                        lambda request, db: EligibilityEvidence(stock_id=request.stock_id, market=request.market))
    request = SwingDiscoveryRequest(as_of_trade_date=CUTOFF, requested_at=REQUESTED_AT,
        batch_size=1, max_batches=1, top_n=3, detail_batch_size=3, mode="confirmed")

    def advance(checkpoint=None):
        with Session(engine) as db:
            return nomination.discover_trade_proposals(db, request, checkpoint=checkpoint)

    first = advance()
    assert first["status"] == "in_progress" and first["sample_only"] is True
    assert first["coverage"]["considered"] == 1 and first["created"] == 0
    second = advance(SwingDiscoveryCheckpoint.model_validate_json(json.dumps(first["checkpoint"])))
    result = advance(SwingDiscoveryCheckpoint.model_validate_json(json.dumps(second["checkpoint"])))
    assert result["status"] == "partial" and result["created"] == 2
    assert result["coverage"]["all_considered"] and result["sample_only"] is False
    assert result["coverage"]["quality_status"] == "partial" and result["research_sample_only"] is True
    missing = [r for r in result["candidates"] if r["stock_id"] == "9999"]
    assert missing and all(r["status"] == "DATA_BLOCKED" and r["proposal"] is None for r in missing)
    assert all("SNAPSHOT_NOT_COMPUTED" in r["reason_codes"] for r in missing)
    with Session(engine) as db:
        before = db.execute(select(proposal_versions).order_by(proposal_versions.c.creation_id)).all()
    repeat = advance(SwingDiscoveryCheckpoint.model_validate_json(json.dumps(result["checkpoint"])))
    assert repeat["created"] == 0 and repeat["deduplicated"] == 2 and repeat["status"] == "partial"
    assert len(calls["canonical"]) == 3  # Completed cheap prefix was resumed, not scanned again.
    assert [r["proposal"]["proposal"]["creation_id"] for r in repeat["candidates"] if r["proposal"]] == [
        r["proposal"]["proposal"]["creation_id"] for r in result["candidates"] if r["proposal"]]
    with Session(engine) as db:
        assert db.execute(select(proposal_versions).order_by(proposal_versions.c.creation_id)).all() == before
    for row in result["candidates"]:
        if row["proposal"]:
            saved = row["proposal"]["proposal"]
            snapshot = json.loads(saved["evidence"]["items"][0]["snapshot_json"])
            assert saved["change_reason"] == "OMI_SCREEN" and snapshot["discovery"]["research_sample_only"]


def test_selected_nomination_prices_rr_journal_revision_and_missing_timestamps(api, monkeypatch):
    from decimal import Decimal
    from app.research import stock_nomination as nomination
    from app.market.tw_trade_eligibility import EligibilityEvidence
    from test_tw_swing_screening import _evidence, CUTOFF, REQUESTED_AT

    client, clock, _ = api
    clock["now"] = REQUESTED_AT + timedelta(hours=1)
    monkeypatch.setattr(nomination, "utc_now", lambda: clock["now"])
    items = []
    for index, symbol in enumerate(("2330", "2337", "3481", "2891", "6147")):
        item = _evidence(symbol, falling=index >= 2)
        zones = item.price_map.payload["zones"]
        extra = [{**zones[0], "zone_id": "support2", "lower_bound": 97, "upper_bound": 98},
                 {**zones[1], "zone_id": "resistance2", "lower_bound": 102, "upper_bound": 103}]
        item = item.model_copy(update={"price_map": item.price_map.model_copy(update={
            "payload": {**item.price_map.payload, "zones": [*zones, *extra]}})})
        if index == 4:
            bars = tuple(b.model_copy(update={"lineage": b.lineage.model_copy(update={
                "event_at": None, "received_at": None, "fetched_at": None})}) for b in item.bars.bars)
            item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": bars})})
        items.append(item)
    monkeypatch.setattr(nomination, "read_tw_swing_evidence", lambda db, request: tuple(items))
    monkeypatch.setattr(nomination, "read_tw_trade_eligibility_evidence",
                        lambda request, db: EligibilityEvidence(stock_id=request.stock_id, market=request.market))
    body = {"stock_ids": [i.stock_id for i in items], "direction": "both", "horizon_sessions": 10,
            "as_of_trade_date": CUTOFF.isoformat(), "requested_at": REQUESTED_AT.isoformat()}
    response = client.post(PREFIX + "/nominations", body)
    assert response.status_code == 201, response.body
    rows = response.body["scenarios"]
    saved = [r for r in rows if r["proposal"]]
    assert len(saved) == 8
    assert len([r for r in saved if r["direction"] == "long"]) == 4
    assert len([r for r in saved if r["direction"] == "short"]) == 4
    for row in saved:
        read = row["proposal"]
        strategy = read["proposal"]["strategy"]
        from app.market.tw_swing_screening import SwingScreenRequest, screen_tw_swing_candidates
        expected_screen = screen_tw_swing_candidates(SwingScreenRequest(stock_ids=tuple(i.stock_id for i in items),
            as_of_trade_date=CUTOFF, requested_at=REQUESTED_AT), tuple(items))
        candidate = next((c for c in expected_screen.candidates if c.stock_id == row["stock_id"] and c.direction == row["direction"]), None)
        assert strategy["mode"] == (candidate.mode if candidate else "aggressive")
        if candidate:
            snapshot = json.loads(read["proposal"]["evidence"]["items"][0]["snapshot_json"])
            assert snapshot["candidate"]["mode"] == candidate.mode
        if row["direction"] == "long":
            assert strategy["entry_rule"] == "at_or_below" and strategy["entry_price"] < 100
        else:
            assert strategy["entry_rule"] == "at_or_above" and strategy["entry_price"] > 100
        assert Decimal(read["setup_evaluation"]["target_scenarios"][0]["gross_rr"]) == 2
        assert read["setup_evaluation"]["target_scenarios"][0]["net_rr"] is None
        assert read["setup_evaluation"]["execution_ready"] is False
        assert read["valid_until_date"] > read["valid_from_date"]
    blocked = [r for r in rows if r["stock_id"] == "6147"]
    assert all(r["status"] == "DATA_BLOCKED" and "SOURCE_TIME_UNKNOWN" in r["reason_codes"] for r in blocked)
    original = saved[0]["proposal"]["proposal"]
    clock["now"] += timedelta(seconds=1)
    revised_strategy = {**original["strategy"], "stop_price": 98.5}
    revised = client.post(f"{PREFIX}/{original['creation_id']}/revisions", {
        "expected_revision_id": original["revision_id"], "strategy": revised_strategy,
        "costs": original["costs"], "change_reason": "Revise nominated stop"})
    assert revised.status_code == 201, revised.body
    assert revised.body["proposal"]["revision"] == 2
    assert revised.body["setup_evaluation"]["gross_risk"] != saved[0]["proposal"]["setup_evaluation"]["gross_risk"]
    history = client.get(f"{PREFIX}/{original['creation_id']}/revisions")
    assert [r["proposal"]["revision"] for r in history.body["revisions"]] == [1, 2]
    assert history.body["revisions"][0]["proposal"] == original
    assert client.get(f"{PREFIX}/{original['creation_id']}").body == revised.body
    ai = client.post(PREFIX + "/nominations", {**body, "nomination_origin": "AI_NOMINATION"})
    assert ai.status_code == 201
    assert ai.body["scenarios"][0]["proposal"]["setup_evaluation"] == saved[0]["proposal"]["setup_evaluation"]
    # Source mode and all price levels survive Journal read/revision. Confirmed
    # research must not be silently downgraded to fit the existing price-only Candidate.
    confirmed = next(r["proposal"]["proposal"] for r in saved if r["proposal"]["proposal"]["strategy"]["mode"] == "confirmed"
        and r["proposal"]["proposal"]["creation_id"] != original["creation_id"])
    promoted = client.post(f"{PREFIX}/{confirmed['creation_id']}/promote", {
        "expected_revision_id": confirmed["revision_id"], "owner_id": "fixture-review"})
    assert promoted.status_code == 200
    assert promoted.body["candidate"] is None and promoted.body["execution_ready"] is False
    assert "COMPLETED_DAILY_CONFIRMATION_NOT_REPRESENTABLE" in promoted.body["reason_codes"]
    assert client.get(f"{PREFIX}/{confirmed['creation_id']}").body["proposal"]["strategy"] == confirmed["strategy"]

    # 1:2 remains a preference. A structurally valid lower R/R is saved honestly.
    from copy import deepcopy
    changed = deepcopy(items[0].price_map.payload)
    (entry, stop, tp1, tp2), zones = nomination._levels(items[0], "long")
    next(z for z in changed["zones"] if z["zone_id"] == zones[0]["zone_id"])["lower_bound"] = entry - 2 * (tp1 - entry)
    items[0] = items[0].model_copy(update={"price_map": items[0].price_map.model_copy(update={"payload": changed})})
    lower_rr = client.post(PREFIX + "/nominations", body)
    assert lower_rr.status_code == 201
    row = next(r for r in lower_rr.body["scenarios"] if r["stock_id"] == "2330" and r["direction"] == "long")
    assert row["proposal"] is not None and row["rr_preference_met"] is False
    assert Decimal(row["proposal"]["setup_evaluation"]["target_scenarios"][0]["gross_rr"]) < 2


def revision_body(proposal):
    return {"expected_revision_id": proposal["revision_id"],
            "strategy": strategy(version="v2", stop_price=98).model_dump(mode="json"),
            "costs": costs(version="cost-v2").model_dump(mode="json"), "change_reason": "Prospective revision"}


def evaluation_body(bars=None):
    return {"decision_at": DECISION.isoformat(), "outcome_as_of": AS_OF.isoformat(),
            "bars": [item.model_dump(mode="json") for item in path()] if bars is None else bars}


def assert_read_only(statements):
    assert statements
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"))
                   for sql in statements)


def seed_canonical(engine, *, late_first=False):
    # Only tables required by the existing daily owner, on the same fixture DB.
    created = set()

    def create_table(table):
        if table in created:
            return
        created.add(table)
        for foreign_key in table.foreign_keys:
            create_table(foreign_key.column.table)
        table.create(engine)

    for model in (SourceRegistry, RawFetchResult, StockMaster, MarketDailyPrice, MarketDailyPriceLineage, MarketDailyPriceRevision):
        create_table(model.__table__)
    with Session(engine) as db, db.begin():
        source = SourceRegistry(source_name=TWSE_DAILY_TRADING_SOURCE_NAME, source_type="official",
                                category="market_daily_price", reliability_level="official")
        db.add(source)
        db.add(StockMaster(stock_id="2330", stock_name="Fixture", market="TWSE", instrument_type="stock", is_active=True))
        db.flush()
        for index, day in enumerate(DATES):
            raw = RawFetchResult(source_id=source.id,
                                 fetched_at=AS_OF + timedelta(days=1) if late_first and index == 0 else
                                 datetime.combine(day, time(8), UTC), method="GET",
                                 content_hash=f"fixture-revision:{day}", parser_version="fixture-v1")
            db.add(raw)
            db.flush()
            db.add(MarketDailyPrice(source_id=source.id, raw_result_id=raw.id, trade_date=day,
                                    stock_id="2330", stock_name="Fixture", open_price=100, high_price=104,
                                    low_price=98, close_price=102, trade_volume=1000))


def test_create_revise_read_and_history_survive_separate_http_sessions(api, engine):
    client, clock, statements = api
    original = create(api)
    clock["now"] += timedelta(days=1)
    response = client.post(f"{PREFIX}/{original['creation_id']}/revisions", revision_body(original))
    assert response.status_code == 201, response.body
    revised = response.body["proposal"]
    assert revised["revision"] == 2
    assert revised["supersedes"] == original["revision_id"]
    assert revised["evidence_hash"] == original["evidence_hash"]
    assert revised["initial_risk_amount"] == original["initial_risk_amount"] == 5000
    clock["readonly"] = True
    statements.clear()
    original_read = client.get(f"{PREFIX}/{original['creation_id']}", decision_at=DECISION.isoformat())
    assert original_read.status_code == 200
    assert original_read.body["proposal"] == original
    current_read = client.get(f"{PREFIX}/{original['creation_id']}")
    assert current_read.body["proposal"] == revised
    history = client.get(f"{PREFIX}/{original['creation_id']}/revisions")
    assert [item["proposal"]["revision"] for item in history.body["revisions"]] == [1, 2]
    old_history = client.get(f"{PREFIX}/{original['creation_id']}/revisions", as_of=DECISION.isoformat())
    assert len(old_history.body["revisions"]) == 1
    assert_read_only(statements)
    with Session(engine) as db:
        assert len(db.execute(select(proposal_versions)).all()) == 2


def test_stale_revision_conflict_rolls_back_without_overwriting_history(api, engine):
    client, clock, _ = api
    original = create(api)
    clock["now"] += timedelta(days=1)
    assert client.post(f"{PREFIX}/{original['creation_id']}/revisions", revision_body(original)).status_code == 201
    clock["now"] += timedelta(minutes=1)
    stale = client.post(f"{PREFIX}/{original['creation_id']}/revisions", revision_body(original))
    assert stale.status_code == 409
    assert stale.body["detail"]["code"] == "REVISION_CONFLICT"
    with Session(engine) as db:
        assert len(db.execute(select(proposal_versions)).all()) == 2


def test_scheduled_revision_is_known_without_becoming_effective_early(api):
    client, clock, _ = api
    original = create(api)
    clock["now"] += timedelta(hours=1)
    request = revision_body(original)
    request["effective_at"] = (clock["now"] + timedelta(days=1)).isoformat()
    response = client.post(f"{PREFIX}/{original['creation_id']}/revisions", request)
    assert response.status_code == 201
    assert response.body["status"] == "scheduled"
    assert client.get(f"{PREFIX}/{original['creation_id']}").body["proposal"] == original
    assert client.get(f"{PREFIX}/{original['creation_id']}/revisions").body["revisions"][-1]["status"] == "scheduled"


@pytest.mark.parametrize("changes", [
    {"now": DECISION.isoformat()}, {"recorded_at": DECISION.isoformat()},
    {"effective_at": (DECISION - timedelta(seconds=1)).isoformat()},
    {"effective_at": "2026-10-27T08:00:00"},
])
def test_http_does_not_accept_backdated_or_naive_write_clocks(api, changes):
    response = api[0].post(PREFIX, creation_body(**changes))
    assert response.status_code == 422


def test_failed_revision_does_not_leak_an_open_write_transaction(api):
    client, clock, _ = api
    original = create(api)
    clock["now"] += timedelta(days=1)
    request = revision_body(original)
    request["effective_at"] = DECISION.isoformat()
    assert client.post(f"{PREFIX}/{original['creation_id']}/revisions", request).status_code == 422
    assert client.post(f"{PREFIX}/{original['creation_id']}/revisions", revision_body(original)).status_code == 201


def test_missing_proposals_have_predictable_404(api):
    client, _, _ = api
    assert client.get(PREFIX + "/missing").status_code == 404
    assert client.get(PREFIX + "/missing/revisions").status_code == 404
    response = client.post(PREFIX + "/missing/revisions", revision_body({"revision_id": "missing"}))
    assert response.status_code == 404


def test_supplied_paper_evaluation_and_replay_are_read_only_and_preserve_f05_contract(api, engine):
    client, clock, statements = api
    original = create(api)
    clock["now"] += timedelta(days=1)
    assert client.post(f"{PREFIX}/{original['creation_id']}/revisions", revision_body(original)).status_code == 201
    clock.update(now=AS_OF + timedelta(days=2), readonly=True)
    statements.clear()
    url = f"{PREFIX}/{original['creation_id']}/paper-outcome"
    response = client.post(url, evaluation_body())
    assert response.status_code == 200, response.body
    result = response.body
    assert result["status"] == "evaluated"
    assert result["proposal"] == original
    assert result["evaluation"]["contract_version"] == "research.paper_outcome.v1"
    assert [item["horizon_sessions"] for item in result["evaluation"]["outcomes"]] == [10, 15]
    assert result["evaluation"]["outcomes"][0]["path_metrics"]["mfe_trade_r"] == pytest.approx(0.8)
    assert result["evaluation"]["outcomes"][0]["paper"]["trade_r"] == 0.4
    assert result["evaluation"]["actual_fill"] is None
    assert result["evaluation"]["realized_trade_r"] is None
    replay = client.post(url, result["replay_request"])
    assert replay.body["evaluation"] == result["evaluation"]
    assert_read_only(statements)
    with Session(engine) as db:
        assert len(db.execute(select(proposal_versions)).all()) == 2


def test_stop_target_ambiguity_and_unknown_cost_survive_http_projection(api):
    client, clock, _ = api
    original = create(api, costs={"version": "unknown-cost"})
    clock["now"] = AS_OF
    bars = path()
    bars[1] = bar(DATES[1], high_price=112, low_price=94)
    response = client.post(f"{PREFIX}/{original['creation_id']}/paper-outcome",
                            evaluation_body([item.model_dump(mode="json") for item in bars]))
    assert response.body["status"] == "ambiguous"
    assert "cost_unknown" in response.body["insufficient_evidence"]
    assert response.body["evaluation"]["outcomes"][0]["paper"]["trade_r"] is None


@pytest.mark.parametrize("field", ["source_available_at", "received_at"])
def test_supplied_bars_require_both_evidence_timestamps(api, field):
    client, clock, _ = api
    original = create(api)
    clock["now"] = AS_OF
    request = evaluation_body()
    request["bars"][0].pop(field)
    assert client.post(f"{PREFIX}/{original['creation_id']}/paper-outcome", request).status_code == 422


def test_future_bar_receipts_and_explicit_empty_bars_are_insufficient_without_owner_fallback(api, monkeypatch):
    client, clock, _ = api
    original = create(api)
    clock["now"] = AS_OF + timedelta(days=2)
    monkeypatch.setattr(service, "read_taiwan_official_daily", lambda *args, **kwargs: pytest.fail("implicit fallback"))
    request = evaluation_body()
    request["bars"][0]["received_at"] = (AS_OF + timedelta(days=1)).isoformat()
    response = client.post(f"{PREFIX}/{original['creation_id']}/paper-outcome", request)
    assert response.body["status"] == "insufficient_evidence"
    assert response.body["evaluation"]["outcomes"][0]["path_metrics"] == {}
    empty = client.post(f"{PREFIX}/{original['creation_id']}/paper-outcome", evaluation_body([]))
    assert empty.body["status"] == "insufficient_evidence"


def test_canonical_get_post_and_snapshot_replay_use_same_owner_and_no_writes(api, engine, monkeypatch):
    seed_canonical(engine)
    client, clock, statements = api
    original = create(api, price_basis="raw")
    clock.update(now=AS_OF, readonly=True)
    statements.clear()
    owner = service.read_taiwan_official_daily
    calls = []

    def tracked(*args, **kwargs):
        calls.append(kwargs)
        return owner(*args, **kwargs)

    monkeypatch.setattr(service, "read_taiwan_official_daily", tracked)
    url = f"{PREFIX}/{original['creation_id']}/paper-outcome"
    params = dict(decision_at=DECISION.isoformat(), outcome_as_of=AS_OF.isoformat())
    get_response = client.get(url, **params)
    assert get_response.status_code == 200, get_response.body
    result = get_response.body
    assert result["bar_source"] == "canonical_cache"
    assert result["status"] == "insufficient_evidence"  # G1 corporate coverage is not invented.
    assert "corporate_action_coverage_unknown" in result["insufficient_evidence"]
    assert result["evaluation"]["outcomes"][0]["coverage"] == "complete"
    assert result["evaluation"]["outcomes"][0]["paper"]["trade_r"] == 0.4
    post_response = client.post(url, params)
    assert post_response.body == result
    replay = client.post(url, result["replay_request"])
    assert replay.body["evaluation"] == result["evaluation"]
    assert len(calls) == 2
    assert all(call["requested_at"] == AS_OF and call["limit"] == 15 for call in calls)
    assert_read_only(statements)


def test_canonical_receipt_after_cutoff_never_backfills_historical_outcome(api, engine):
    seed_canonical(engine, late_first=True)
    client, clock, _ = api
    original = create(api, price_basis="raw")
    clock.update(now=AS_OF, readonly=True)
    response = client.get(f"{PREFIX}/{original['creation_id']}/paper-outcome",
                           decision_at=DECISION.isoformat(), outcome_as_of=AS_OF.isoformat())
    assert response.status_code == 200, response.body
    result = response.body["evaluation"]["outcomes"][0]
    assert result["missing_trade_dates"] == [DATES[0].isoformat()]
    assert result["path_metrics"] == {}
    assert result["paper"]["trade_r"] is None


def test_canonical_missing_receipt_does_not_substitute_query_time(api, engine, monkeypatch):
    seed_canonical(engine)
    client, clock, _ = api
    original = create(api, price_basis="raw")
    clock.update(now=AS_OF, readonly=True)
    owner = service.read_taiwan_official_daily

    def missing_receipt(*args, **kwargs):
        result = owner(*args, **kwargs)
        bars = list(result.resolved.bars)
        bars[0] = bars[0].model_copy(update={"lineage": bars[0].lineage.model_copy(
            update={"received_at": None, "fetched_at": None})})
        return result.model_copy(update={"resolved": result.resolved.model_copy(update={"bars": tuple(bars)})})

    monkeypatch.setattr(service, "read_taiwan_official_daily", missing_receipt)
    response = client.get(f"{PREFIX}/{original['creation_id']}/paper-outcome",
                           decision_at=DECISION.isoformat(), outcome_as_of=AS_OF.isoformat())
    assert response.status_code == 200, response.body
    assert response.body["status"] == "insufficient_evidence"
    outcome = response.body["evaluation"]["outcomes"][0]
    assert outcome["missing_trade_dates"] == [DATES[0].isoformat()]
    assert outcome["paper"]["trade_r"] is None


def test_canonical_unavailable_returns_insufficient_evidence_without_refresh(api, monkeypatch):
    client, clock, _ = api
    original = create(api)
    clock["now"] = AS_OF

    def unavailable(*args, **kwargs):
        raise ValueError("No active canonical instrument")

    monkeypatch.setattr(service, "read_taiwan_official_daily", unavailable)
    response = client.get(f"{PREFIX}/{original['creation_id']}/paper-outcome",
                           decision_at=DECISION.isoformat(), outcome_as_of=AS_OF.isoformat())
    assert response.status_code == 200
    assert response.body["status"] == "insufficient_evidence"
    assert "canonical_daily_unavailable" in response.body["owner_limitations"]


def test_future_knowledge_invalid_cutoffs_and_wrong_pinned_revision_are_rejected(api):
    client, clock, _ = api
    original = create(api)
    url = f"{PREFIX}/{original['creation_id']}/paper-outcome"
    assert client.post(url, evaluation_body()).status_code == 422
    clock["now"] = AS_OF
    request = evaluation_body()
    request["outcome_as_of"] = (DECISION - timedelta(minutes=1)).isoformat()
    assert client.post(url, request).status_code == 422
    request = evaluation_body()
    request["expected_revision_id"] = "later-or-unrelated-revision"
    assert client.post(url, request).status_code == 409
    assert client.get(url, decision_at="2026-10-27T08:00:00", outcome_as_of=AS_OF.isoformat()).status_code == 422


def test_independent_router_has_documented_registration_and_no_clock_override(api):
    schema = api[0].get("/openapi.json").body
    assert set(schema["paths"][PREFIX]) == {"get", "post"}
    assert set(schema["paths"][PREFIX + "/{creation_id}/paper-outcome"]) == {"get", "post"}
    assert "now" not in schema["components"]["schemas"]["ProposalCreate"]["properties"]
    assert f"{PREFIX}/{{creation_id}}/monitor" in schema["paths"]
    assert f"{PREFIX}/{{creation_id}}/promote" in schema["paths"]


def test_unapplied_schema_reports_503_without_bootstrapping_database(api):
    empty = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def empty_db():
        with Session(empty) as db:
            yield db

    api[0].app.dependency_overrides[get_db] = empty_db
    try:
        response = api[0].post(PREFIX, creation_body())
        assert response.status_code == 503
        assert response.body["detail"]["code"] == "RESEARCH_JOURNAL_SCHEMA_UNAVAILABLE"
        assert api[0].get(PREFIX + "/missing").status_code == 503
        assert inspect(empty).get_table_names() == []
    finally:
        empty.dispose()
