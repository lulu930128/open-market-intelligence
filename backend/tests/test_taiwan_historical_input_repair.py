"""G3.1: isolated JobRun/producer fixtures; no live DB, scheduler or provider IO."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import event, update

from app.db.models import JobRun, MarketDailyPrice, StockMaster, TaiwanPriceMapSnapshot
from app.jobs import service as jobs
from app.jobs import taiwan_historical_input_repair as repair
from app.jobs import taiwan_price_map_snapshot_scheduler as producer
from app.jobs import tw_technical_input_readiness as readiness
from app.market.tw_daily_day_state import resolve_taiwan_daily_day_state
from app.market_data.contracts import InstrumentKey, TradingStatusObservation, SourceLineage
from test_tw_price_map_screening import sessions, seed, payload, NOW, BASIS

INSTRUMENT = InstrumentKey(market="TW", venue="TWSE", symbol="2330", instrument_type="stock")


@pytest.fixture(autouse=True)
def offline_owners(monkeypatch):
    import socket
    from app.market import tw_corporate_events
    original_reader = tw_corporate_events.read_taiwan_corporate_event_cache
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("fixture network forbidden")))
    monkeypatch.setattr(tw_corporate_events, "read_taiwan_corporate_event_cache", lambda **kw: tw_corporate_events._empty_cache())
    return original_reader


def quality(days=("2026-08-20", "2026-07-20"), *, unknown=True):
    states = []
    for day in days:
        statuses = () if unknown else (TradingStatusObservation(instrument=INSTRUMENT, status="tradable",
            lineage=SourceLineage(provider="fixture", source="official", authority="exchange", fetched_at=NOW), official=True),)
        states.append(resolve_taiwan_daily_day_state(instrument=INSTRUMENT, trade_date=date.fromisoformat(day),
            market_open=True, statuses=statuses).model_dump(mode="json"))
    return {"coverage_status": "insufficient_history" if days else "complete",
        "available_bar_count": 47 if days else 90, "required_bars": 60,
        "technical_decision_usable": not days, "earliest_available_trade_date": "2026-05-12",
        "technical_reasons": ["TW_TECHNICAL_INSUFFICIENT_BARS", "TW_TECHNICAL_DECISION_WINDOW_GAP"] if days else [],
        "day_states": states, "day_state_blockers": [
            {"trade_date": state["trade_date"], "state": state["state"], "reasons": state["blockers"]} for state in states]}


def partial(symbol="2330"):
    return {**payload(stock_id=symbol), "decision_usable": False, "structure_input_usable": False,
        "missing": ["TW_TECHNICAL_INSUFFICIENT_BARS", "TW_TECHNICAL_DECISION_WINDOW_GAP"]}


def admit(db, *, now=NOW, symbol="2330"):
    return repair.admit_taiwan_historical_input_repair(db, stock_id=symbol, basis=BASIS, input_revision=1, now=now)


def step(sessions, job_id, *, now=NOW):
    with sessions() as db:
        jobs.start_job(db, job_id)
        result = repair.repair_taiwan_historical_input_job_step(db, job_id, clock=lambda: now)
        jobs.complete_job(db, job_id, result=result)
    return result


def test_cross_month_unknown_job_is_durable_and_only_continues_on_admission(sessions, monkeypatch):
    pending = ["2026-07-20", "2026-08-20"]
    calls = []
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality(pending))
    def execute(db, **kw):
        assert not db.in_transaction()  # Job checkpoint committed before IO.
        calls.append((kw["operation"], kw["days"]))
        if kw["operation"] == "daily_backfill":
            pending.remove(kw["days"][0])
        return {"status": "success", "months": [{"month": kw["days"][0][:7], "raw_result_id": 123}]}
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", execute)
    with patch.object(jobs, "submit_job_task") as submit:
        with sessions() as db:
            first = admit(db)
        assert submit.call_count == 1 and first["submitted"]
        with sessions() as db:
            assert not admit(db)["submitted"]  # Active target, across Sessions.
        for index in range(4):
            result = step(sessions, first["job_id"])
            assert len(calls) == index + 1
            assert submit.call_count == index + 1  # Completion did NOT chain IO.
            if index < 3:
                with sessions() as db:
                    resumed = admit(db)
                assert resumed["job_id"] == first["job_id"] and resumed["submitted"]
        assert result["status"] == "repaired"
        assert calls == [("instrument_event_refresh", ["2026-08-20"]), ("daily_backfill", ["2026-08-20"]),
                         ("instrument_event_refresh", ["2026-07-20"]), ("daily_backfill", ["2026-07-20"])]
        with sessions() as db:
            assert db.query(JobRun).count() == 1
            assert not admit(db)["submitted"]


@pytest.mark.parametrize("failure", [False, True])
def test_no_change_failure_cooldown_exhaustion_and_compact_receipts(sessions, monkeypatch, failure):
    value = quality(["2026-08-20"], unknown=False)
    value["day_states"] *= 400
    value["day_state_blockers"] *= 400
    for state in value["day_states"]:
        state["lineage"] = [{"raw_text": "fixture" * 10000}]
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: deepcopy(value))
    def execute(db, **kw):
        if failure:
            raise TimeoutError("fixture")
        return {"status": "success", "raw_text": "x" * 1000000,
                "months": [{"month": "2026-08", "status": "success", "raw_result_id": 7, "parsed_count": 0}]}
    owner = Mock(side_effect=execute)
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", owner)
    with patch.object(jobs, "submit_job_task"):
        with sessions() as db:
            job_id = admit(db)["job_id"]
        for attempt in range(3):
            now = NOW + attempt * (repair.RETRY_DELAY + timedelta(seconds=1))
            result = step(sessions, job_id, now=now)
            assert result["status"] == "partial" and result["after"]["available_bar_count"] == 47
            with sessions() as db:
                row = db.get(JobRun, job_id)
                assert len(row.result_json.encode()) < 16000
                assert "raw_text" not in row.result_json and '"lineage"' not in row.result_json
                assert not admit(db, now=now + timedelta(minutes=1))["submitted"]
                if attempt < 2:
                    assert admit(db, now=now + repair.RETRY_DELAY + timedelta(seconds=1))["submitted"]
        with sessions() as db:
            assert not admit(db, now=NOW + timedelta(days=5))["submitted"]
            assert db.query(JobRun).count() == 1
            assert db.query(MarketDailyPrice).count() == 0
        assert owner.call_count == 3
        assert result["next_action"] == "REVIEW_CANONICAL_BLOCKERS"


def test_interrupted_attempt_is_not_immediately_replayed(sessions, monkeypatch):
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality(["2026-08-20"], unknown=False))
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", Mock(side_effect=SystemExit("crash")))
    with patch.object(jobs, "submit_job_task"):
        with sessions() as db:
            job_id = admit(db)["job_id"]
            jobs.start_job(db, job_id)
            with pytest.raises(SystemExit):
                repair.repair_taiwan_historical_input_job_step(db, job_id, clock=lambda: NOW)
        with sessions() as db:
            assert jobs.mark_interrupted_jobs(db) == 1
        with sessions() as db:
            assert not admit(db, now=NOW + timedelta(minutes=1))["submitted"]
            assert json.loads(db.get(JobRun, job_id).result_json)["attempts"]["2026-08:daily_backfill"]["status"] == "attempting"


@pytest.mark.parametrize("outcome", [PermissionError("fixture deny"), {"status": "DENY"}, {"status": "unresolved", "error_type": "PermissionError"}])
def test_permission_denial_stops_all_steps_without_other_owner_workaround(sessions, monkeypatch, outcome):
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality())
    owner = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", owner)
    with patch.object(jobs, "submit_job_task"):
        with sessions() as db:
            job_id = admit(db)["job_id"]
        result = step(sessions, job_id)
        with sessions() as db:
            assert not admit(db, now=NOW + timedelta(days=10))["submitted"]
    assert result["next_action"] == "REVIEW_OWNER_PERMISSION_DENIED" and owner.call_count == 1


def test_producer_admits_only_repairable_partial_and_revisits_skipped_partial(sessions, monkeypatch):
    monkeypatch.setattr(producer, "_repair_after_stock", "")
    monkeypatch.setattr(producer, "read_price_map_external_revision", lambda: "corp")
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality())
    with sessions() as db:
        seed(db, 3)
    def build(**kw):
        symbol = kw["stock_id"]
        if symbol == "2330":
            return partial(symbol)
        if symbol == "2331":
            return payload(stock_id=symbol)
        return {**partial(symbol), "missing": ["corporate_action_unverified"]}
    with patch.object(jobs, "submit_job_task") as submit, patch.object(readiness, "execute_taiwan_historical_input_step") as owner:
        first = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: NOW)
        second = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: NOW)
        assert first["published"] == 3 and first["repair_submitted"] == 1
        assert second["attempted"] == 0 and second["repair_submitted"] == 0
        assert submit.call_count == 1 and owner.call_count == 0
        with sessions() as db:
            job = db.query(JobRun).one()
            assert json.loads(job.request_json)["stock_id"] == "2330"
        # Already published partial without a Job must be admitted on the same
        # header walk, without building/publishing that same revision again.
        with sessions() as db:
            db.query(JobRun).delete(); db.commit()
        third = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=Mock(side_effect=AssertionError("rebuilt")), clock=lambda: NOW)
        assert third["attempted"] == 0 and third["repair_submitted"] == 1


def test_producer_admission_budget_rotates_past_nonrepairable_prefix(sessions, monkeypatch):
    monkeypatch.setattr(producer, "_repair_after_stock", "")
    monkeypatch.setattr(producer, "read_price_map_external_revision", lambda: "corp")
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality())
    with sessions() as db:
        seed(db, 8)
    def build(**kw):
        symbol = kw["stock_id"]
        return {**partial(symbol), "missing": [] if symbol < "2334" else partial()["missing"]}
    with patch.object(jobs, "submit_job_task"):
        reports = [producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: NOW) for _ in range(5)]
    assert all(report["repair_inspected"] <= 2 and report["repair_submitted"] <= 2 for report in reports)
    assert [report["attempted"] for report in reports] == [8, 0, 0, 0, 0]
    with sessions() as db:
        assert db.query(JobRun).count() == 4


def test_ready_header_only_continues_existing_job_and_never_chains_from_worker(sessions, monkeypatch):
    monkeypatch.setattr(producer, "_repair_after_stock", "")
    monkeypatch.setattr(producer, "read_price_map_external_revision", lambda: "corp")
    monkeypatch.setattr(jobs, "SessionLocal", sessions)
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **k: quality())
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", Mock(return_value={"status": "unresolved"}))
    with sessions() as db:
        seed(db, 2)
    with patch.object(jobs, "submit_job_task") as submit:
        with sessions() as db:
            job_id = admit(db)["job_id"]
        repair.run_taiwan_historical_input_repair_job(job_id)
        assert submit.call_count == 1  # No completion-triggered continuation.
        report = producer.produce_taiwan_price_map_snapshots(session_factory=sessions,
            builder=lambda **kw: payload(stock_id=kw["stock_id"]), clock=lambda: NOW)
        assert report["published"] == 2 and report["repair_submitted"] == 1
        with sessions() as db:
            assert db.query(JobRun).count() == 1 and db.get(JobRun, job_id).status == "queued"


def test_1102_recent_state_projection_and_older_40_blockers_enqueue_only_1102(sessions, monkeypatch):
    from app.market.trading_calendar import is_taiwan_trading_day
    older = []
    day = date(2026, 6, 25)
    while day <= date(2026, 8, 20):
        if is_taiwan_trading_day(day):
            older.append(day.isoformat())
        day += timedelta(days=1)
    older = older[:39] + ["2026-08-20"]
    value = quality(older)
    value["day_states"] = [
        {"trade_date": str(date(2026, 9, 21) + timedelta(days=index)),
         "state": "TRADED_WITH_PRICE" if index < 23 else "MARKET_CLOSED", "blockers": []}
        for index in range(40)]
    monkeypatch.setattr(readiness, "read_taiwan_technical_input", lambda *a, **k: deepcopy(value))
    with sessions() as db:
        db.add(StockMaster(stock_id="1102", stock_name="1102", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
    with patch.object(jobs, "submit_job_task") as submit, \
            patch.object(readiness, "execute_taiwan_historical_input_step") as execute:
        with sessions() as db:
            result = repair.admit_taiwan_historical_input_repair(db, stock_id="1102",
                basis=date(2026, 10, 30), input_revision=1, now=NOW)
        with sessions() as db:
            row = db.query(JobRun).one()
            request = json.loads(row.request_json)
            assert request["stock_id"] == "1102" and len(request["dates"]) == 40
            assert all(actions == ["instrument_event_refresh", "daily_backfill"] for actions in request["dates"].values())
            assert db.query(MarketDailyPrice).count() == 0
        assert result["submitted"] and submit.call_count == 1
        execute.assert_not_called()


def test_real_official_backfill_canonical_ma60_revision_and_original_snapshot_rebuild(sessions, monkeypatch, tmp_path, offline_owners):
    from app.db.models import RawFetchResult, SourceRegistry, DataQualityCheck
    from app.market import backfill
    from app.market.price_map_snapshot_repository import read_input_revisions
    from app.market.trading_calendar import is_taiwan_trading_day, TAIWAN_TZ
    from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
    from app.config import settings
    from app.market import tw_corporate_events, exchange_calendar_cache
    from app.market.providers import tw_trading_status
    from app.market.price_map_snapshot_repository import read_price_map_external_revision
    from hashlib import sha256
    monkeypatch.setattr(tw_corporate_events, "read_taiwan_corporate_event_cache", offline_owners)
    monkeypatch.setattr(settings, "tw_corporate_event_cache_path", tmp_path / "events.json")
    monkeypatch.setattr(settings, "market_calendar_cache_path", tmp_path / "calendar.json")
    tw_corporate_events.invalidate_taiwan_corporate_event_cache()
    exchange_calendar_cache.invalidate_exchange_calendar_cache()
    basis = date(2026, 10, 30)
    now = datetime(2026, 11, 1, 12, tzinfo=TAIWAN_TZ)
    dates = []
    day = basis
    while len(dates) < 46:
        if is_taiwan_trading_day(day):
            dates.append(day)
        day -= timedelta(days=1)
    def rows(days):
        return [[f"{day.year-1911}/{day.month:02}/{day.day:02}", "100000", "10000000",
                 "100", "101", "99", "100", "0", "100"] for day in days]
    with sessions() as db:
        source = SourceRegistry(source_name=TWSE_DAILY_TRADING_SOURCE_NAME, source_type="official", category="market", reliability_level="official")
        db.add(source); db.flush()
        raw = RawFetchResult(source_id=source.id, fetched_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
            url="https://www.twse.com.tw/exchangeReport/STOCK_DAY", method="GET", status_code=200,
            content_hash="fixture-original", parser_version="twse_stock_day_v1", raw_text="{}")
        db.add(raw); db.flush()
        db.add(StockMaster(stock_id="1102", stock_name="1102", market="TWSE", instrument_type="stock", is_active=True))
        db.add(StockMaster(stock_id="1101", stock_name="1101", market="TWSE", instrument_type="stock", is_active=True))
        db.add(MarketDailyPrice(stock_id="1101", source_id=source.id, raw_result_id=raw.id, trade_date=basis, close_price=100))
        for day in [date(2026, 5, 12), *dates]:
            db.add(MarketDailyPrice(stock_id="1102", source_id=source.id, raw_result_id=raw.id, trade_date=day,
                open_price=100, high_price=101, low_price=99, close_price=100,
                trade_volume=100000, trade_value=10000000, transaction_count=100))
        db.commit()
        before = readiness.read_taiwan_historical_repair_input(db, stock_id="1102", to_date=basis)
        revision = read_input_revisions(db, ["1102"])["1102"]
    assert before["available_bar_count"] == 47 and not before["technical_decision_usable"]
    requests = []
    def http_get(url, **kw):
        from urllib.parse import parse_qs, urlparse
        month = parse_qs(urlparse(url).query)["date"][0]
        start = datetime.strptime(month, "%Y%m%d").date()
        days = []
        cursor = start
        while cursor.month == start.month:
            if is_taiwan_trading_day(cursor):
                days.append(cursor)
            cursor += timedelta(days=1)
        requests.append(month)
        assert kw["timeout"] == 8
        return SimpleNamespace(text=json.dumps({"stat": "OK", "data": rows(days)}),
            headers={"content-type": "application/json"}, status_code=200, ok=True)
    monkeypatch.setattr(backfill, "http_get", http_get)
    text = "<html>No historical status in the current announcements.</html>"
    monkeypatch.setattr(tw_trading_status, "fetch_taiwan_instrument_events", Mock(return_value={
        "status": "unresolved", "reason": "NOT_IN_RESPONSE", "entries": [], "evidence_windows": [],
        "raw_receipts": [{"receipt_id": "fixture:empty", "raw_text": text,
            "content_hash": sha256(text.encode()).hexdigest(), "url": tw_trading_status.TWSE_ANNOUNCEMENTS_URL,
            "fetched_at": now.isoformat()}]}))
    monkeypatch.setattr(producer, "_repair_after_stock", "")
    builds = []
    def build(**kw):
        builds.append(kw["stock_id"])
        if kw["stock_id"] == "1101":
            return {**payload(stock_id="1101"), "reference": {"trade_date": str(basis)}}
        ready = readiness.read_taiwan_historical_repair_input(kw["db"], stock_id="1102", to_date=basis)["technical_decision_usable"]
        return {**(payload(stock_id="1102") if ready else partial("1102")), "reference": {"trade_date": str(basis)}}
    with patch.object(jobs, "submit_job_task"):
        first = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: now)
        assert first["repair_submitted"] == 1
        with sessions() as db:
            job_id = db.query(JobRun).one().id
            neighbor_revision = db.get(TaiwanPriceMapSnapshot, ("1101", "daily")).corporate_revision
        counts = []
        for _ in range(10):
            result = step(sessions, job_id, now=now)
            counts.append(result["after"]["available_bar_count"])
            assert read_price_map_external_revision() == neighbor_revision
            assert len(requests) <= 3
            report = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: now)
            if result["status"] == "repaired":
                break
            assert report["repair_submitted"] == 1
        assert result["status"] == "repaired" and result["after"]["available_bar_count"] >= 90
        assert result["after"]["technical_decision_usable"]
        assert any(60 <= count < 90 for count in counts)
        assert requests == sorted(set(requests), reverse=True)
        assert builds.count("1101") == 1  # No market-wide churn during real event cache writes.
        with sessions() as db:
            assert db.query(JobRun).count() == 1
            assert read_input_revisions(db, ["1102"])["1102"] > revision
            snapshot = db.get(TaiwanPriceMapSnapshot, ("1102", "daily"))
            assert snapshot.status == "ready"
            assert snapshot.input_revision == read_input_revisions(db, ["1102"])["1102"]
            assert db.query(DataQualityCheck).count() == len(requests)
            assert db.query(RawFetchResult).count() == len(requests) + 1
        report = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: now)
        assert report["attempted"] == report["repair_submitted"] == 0


@pytest.mark.parametrize("state,blockers,market_open,expected", [
    ("MARKET_CLOSED", [], False, False),
    ("INSTRUMENT_SUSPENDED", [], True, False),
    ("CONFLICTED_EVIDENCE", ["OFFICIAL_EVIDENCE_CONFLICT"], True, True),
    ("TRADE_ACTIVITY_WITHOUT_PRICE", ["ALTERNATE_OFFICIAL_PRICE_REQUIRED"], True, True),
    ("MISSING_EVIDENCE", ["MARKET_CALENDAR_COVERAGE_UNKNOWN"], None, True),
    ("VERIFIED_NO_TRADE", [], True, True),
    ("VERIFIED_NO_TRADE", ["PRICE_BASIS_CHANGED"], True, True),
])
def test_nonrepairable_canonical_states_never_become_ohlc_jobs(state, blockers, market_open, expected):
    value = quality(["2026-08-20"])
    value["day_states"][0].update(state=state, blockers=blockers, market_open=market_open, expected_session=expected)
    assert not readiness.plan_taiwan_historical_input_repair(value, to_date=BASIS)["dates"]


def test_verified_no_trade_only_asks_event_owners_never_daily_price_backfill():
    value = quality(["2026-08-20"])
    value["day_states"][0].update(state="VERIFIED_NO_TRADE", blockers=["PRICE_BASIS_EVENT_COVERAGE_REQUIRED"])
    actions = readiness.plan_taiwan_historical_input_repair(value, to_date=BASIS)["dates"]["2026-08-20"]
    assert actions == ["instrument_event_refresh", "corporate_event_refresh"]


def test_concurrent_duplicate_admission_uses_existing_jobrun_writer_reservation(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base
    engine = create_engine("sqlite:///" + (tmp_path / "repair.sqlite").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(4)
    def read(*a, **kw):
        barrier.wait(timeout=10)
        return quality()
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", read)
    def call(index):
        with factory() as db:
            return admit(db, now=NOW + timedelta(days=index))
    try:
        with patch.object(jobs, "submit_job_task") as submit, ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(4)))
        assert sum(result["submitted"] for result in results) == 1
        assert len({result["job_id"] for result in results}) == submit.call_count == 1
        with factory() as db:
            assert db.query(JobRun).count() == 1
    finally:
        engine.dispose()


def test_canonical_postread_failure_retains_attempt_and_does_not_chain(sessions, monkeypatch):
    monkeypatch.setattr(jobs, "SessionLocal", sessions)
    reader = Mock(return_value=quality(["2026-08-20"], unknown=False))
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", reader)
    owner = Mock(return_value={"status": "success"})
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", owner)
    with patch.object(jobs, "submit_job_task") as submit:
        with sessions() as db:
            job_id = admit(db)["job_id"]
        reader.side_effect = [quality(["2026-08-20"], unknown=False), RuntimeError("canonical post-read failed")]
        repair.run_taiwan_historical_input_repair_job(job_id)
        assert submit.call_count == owner.call_count == 1
        with sessions() as db:
            state = json.loads(db.get(JobRun, job_id).result_json)
            assert state["attempts"]["2026-08:daily_backfill"]["count"] == 1
            assert state["next_action"] == "REVIEW_CANONICAL_READBACK_FAILURE"


def test_genuinely_new_gap_does_not_reset_older_exhausted_month_budget(sessions, monkeypatch):
    current = quality(["2026-08-20"], unknown=False)
    monkeypatch.setattr(readiness, "read_taiwan_historical_repair_input", lambda *a, **kw: current)
    owner = Mock(return_value={"status": "success", "months": []})
    monkeypatch.setattr(readiness, "execute_taiwan_historical_input_step", owner)
    with patch.object(jobs, "submit_job_task"):
        with sessions() as db:
            original = admit(db)["job_id"]
        result = step(sessions, original)
        result["attempts"]["2026-08:daily_backfill"]["count"] = 3
        with sessions() as db:
            jobs.complete_job(db, original, result=result)
        current = quality(["2026-08-20", "2026-07-20"], unknown=False)
        with sessions() as db:
            new = admit(db)["job_id"]
        assert new != original
        result = step(sessions, new)
        assert owner.call_args.kwargs["days"] == ["2026-07-20"]
        assert result["attempts"]["2026-08:daily_backfill"]["count"] == 3
        assert result["attempts"]["2026-08:daily_backfill"]["prior_job_id"] == original
