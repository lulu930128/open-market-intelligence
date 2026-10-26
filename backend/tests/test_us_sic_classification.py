"""Offline SIC command contracts; production DB and provider IO are forbidden."""
from datetime import timedelta
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, USCompanyProfile
from app.observability.provider_http import ProviderHttpError, ProviderHttpFailure, ProviderRequestContext
from app.us_market import classification_sync as sync
from app.us_market.classification import read_us_classification
from app.us_market.providers import sec
from app.us_market.providers.sec_policy import SecRequestPolicy
from app.us_market.sector_distribution import build_us_sector_distribution as read_us_sector_distribution
from test_us_sector_distribution import stock, profile, bar, NOW, PREVIOUS


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("external IO forbidden")))
    monkeypatch.setattr("app.us_market.service._require_sec_user_agent", lambda: "OMI fixture test@example.invalid")


def payload(symbol="A", **changes):
    result = {"cik": "0000000123", "tickers": [symbol], "sic": "3674",
              "sicDescription": "Semiconductors", "name": "Fixture"}
    result.update(changes)
    return result


def request(*symbols):
    return sync.USSicSyncRequest(symbols=list(symbols))


@pytest.mark.parametrize("changes,reason", [
    ({"cik": 124}, "CIK_MISMATCH"), ({"cik": None}, "CIK_MISMATCH"),
    ({"tickers": ["A.B"]}, "TICKER_MISMATCH"), ({"tickers": "A"}, "TICKER_MISMATCH"),
    ({"tickers": ["a"]}, "TICKER_MISMATCH"), ({"sic": "123"}, "INVALID_SIC"),
    ({"sic": "0000"}, "INVALID_SIC"), ({"sic": "１２３４"}, "INVALID_SIC"),
    ({"sic": 3674.0}, "INVALID_SIC"), ({"sic": None}, "INVALID_SIC"),
    ({"sicDescription": " "}, "MISSING_SIC_DESCRIPTION"),
    ({"sicDescription": "unknown"}, "MISSING_SIC_DESCRIPTION"),
    ({"sicDescription": 10}, "MISSING_SIC_DESCRIPTION"),
])
def test_exact_identity_and_sic(changes, reason):
    with pytest.raises(ValueError, match=reason):
        sec.parse_sec_sic_classification(payload(**changes), cik="123", symbol="A")


def test_valid_sic_has_no_gics_mapping():
    value = sec.parse_sec_sic_classification(payload(sic=3674), cik="123", symbol="A")
    assert (value.sic, value.description) == ("3674", "Semiconductors")
    assert sec.parse_sec_sic_classification(payload(sic="0100"), cik="123", symbol="A").sic == "0100"


@pytest.mark.parametrize("symbols", [[], ["A"] * 17, ["a"], ["../A"], ["A/B"], [123], ["A" * 21]])
def test_server_bounds_before_io(symbols):
    with pytest.raises(ValidationError):
        sync.USSicSyncRequest(symbols=symbols)


def test_sync_once_idempotent_and_av_preserved(db, monkeypatch):
    stock(db, "A", cik="123"); profile(db, "A"); db.commit()
    before = db.query(USCompanyProfile).filter_by(provider="alphavantage").one()
    original = (before.sector, before.industry, before.fetched_at)
    fetch = Mock(return_value=(payload(), sec.SEC_SUBMISSIONS_URL_TEMPLATE.format(cik="0000000123")))
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", fetch)
    committed = Mock(wraps=db.commit); monkeypatch.setattr(db, "commit", committed)
    first = sync.sync_us_sic_classification(db, request=request("A", "A"))
    assert committed.call_count == 1 and fetch.call_count == 1
    assert (first.inserted_count, first.updated_count, first.unique_count, first.requested_count) == (1, 0, 1, 2)
    second = sync.sync_us_sic_classification(db, request=request("A"))
    assert second.updated_count == 1 and db.query(USCompanyProfile).count() == 2
    db.refresh(before)
    assert (before.sector, before.industry, before.fetched_at) == original
    sic = db.query(USCompanyProfile).filter_by(provider="sec_edgar_sic").one()
    assert sic.sector == "SIC 36xx" and sic.industry == "SIC 3674 · Semiconductors"
    assert sic.raw_payload_hash and len(sic.raw_payload_hash) == 64
    assert sic.source_url.endswith("CIK0000000123.json")
    assert read_us_classification(db, now=NOW)["profiles"]["A"]["provider"] == "alphavantage"


def test_skip_ineligible_missing_malformed_and_source_failure(db, monkeypatch):
    stock(db, "ETF", cik="123", is_etf=True)
    stock(db, "MISSING"); stock(db, "BAD", cik="123"); stock(db, "FAIL", cik="123")
    stock(db, "OK", cik="123"); db.commit()
    fetch = Mock(side_effect=[(payload("WRONG"), "fixture"), sync.USMarketDataFetchError("bad json"), (payload("OK"), "fixture")])
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", fetch)
    result = sync.sync_us_sic_classification(db, request=request("ETF", "MISSING", "BAD", "FAIL", "OK", "OUTSIDE"))
    assert result.status == "partial" and result.skipped_count == 5 and result.fetch_count == 3
    assert result.inserted_count == 1 and db.query(USCompanyProfile).one().symbol == "OK"
    assert [item.reason for item in result.items] == ["NOT_ELIGIBLE_ORDINARY_STOCK", "MISSING_OR_INVALID_CIK", "TICKER_MISMATCH", "SOURCE_FAILED:invalid_payload", "SEC_SIC_IDENTITY_VERIFIED", "NOT_ELIGIBLE_ORDINARY_STOCK"]


def test_failed_batch_rolls_back_all_rows_and_preserves_av(db, monkeypatch):
    for symbol in ("A", "B"):
        stock(db, symbol, cik="123")
    profile(db, "A"); db.commit()
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", Mock(side_effect=[(payload("A"), "fixture"), (payload("B"), "fixture")]))
    def fail_after_writes(*args):
        raise RuntimeError("injected failure after SQL writes")
    event.listen(db, "after_flush_postexec", fail_after_writes, once=True)
    with pytest.raises(RuntimeError, match="after SQL writes"):
        sync.sync_us_sic_classification(db, request=request("A", "B"))
    assert not db.in_transaction()
    assert db.query(USCompanyProfile).count() == 1
    assert db.query(USCompanyProfile).one().provider == "alphavantage"


def test_max_16_calls_32_attempts_existing_policy(db, monkeypatch):
    symbols = [f"A{i}" for i in range(16)]
    for symbol in symbols:
        stock(db, symbol, cik="123")
    db.commit()
    failure = ProviderHttpFailure(context=ProviderRequestContext(market="us", provider="sec_edgar", resource="sec_submissions"), status="timeout", source_url="fixture")
    provider_get = Mock(side_effect=ProviderHttpError("timeout", failure=failure))
    monkeypatch.setattr(sec, "provider_get", provider_get)
    clock = [0.0]
    def advance(seconds):
        clock[0] += seconds
    policy = SecRequestPolicy(monotonic=lambda: clock[0], sleep=advance)
    monkeypatch.setattr(sec, "DEFAULT_SEC_REQUEST_POLICY", policy)
    result = sync.sync_us_sic_classification(db, request=request(*symbols))
    assert result.status == "skipped" and result.skipped_count == 16
    assert provider_get.call_count == result.max_http_attempts == 32
    assert result.fetch_count == 16 and policy.min_interval_seconds == 0.25
    assert all(item.reason == "SOURCE_FAILED:timeout" for item in result.items)
    assert db.query(USCompanyProfile).count() == 0


def test_dirty_session_and_constructed_oversize_request_rejected_before_io(db, monkeypatch):
    fetch = Mock(side_effect=AssertionError("no fetch")); monkeypatch.setattr(sec, "fetch_sec_submissions_payload", fetch)
    with pytest.raises(ValidationError):
        sync.sync_us_sic_classification(db, request=sync.USSicSyncRequest.model_construct(symbols=["A"] * 17))
    stock(db, "A", cik="123")
    with pytest.raises(ValueError, match="clean Session"):
        sync.sync_us_sic_classification(db, request=request("A"))
    assert fetch.call_count == 0


def test_sic_fallback_taxonomy_groups_and_future_evidence(db, monkeypatch):
    for symbol in ("A", "B", "C"):
        stock(db, symbol); bar(db, symbol, PREVIOUS); bar(db, symbol)
        profile(db, symbol, provider="sec_edgar_sic", sector="SIC 36xx", industry="SIC 3674 · Semiconductors", fetched=NOW-timedelta(days=1))
    profile(db, "A")
    profile(db, "B", sector="unknown", industry=None)
    profile(db, "C", fetched=NOW+timedelta(days=1))
    db.commit()
    fetch=Mock(side_effect=AssertionError("GET must not fill")); monkeypatch.setattr(sec, "fetch_sec_submissions_payload", fetch)
    result=read_us_sector_distribution(db, now=NOW)
    assert result.counts.comparable == 3 and result.decision_usable is False
    assert {(g.provider,g.taxonomy,g.counts.universe) for g in result.sectors} == {("alphavantage","provider_reported",1),("sec_edgar_sic","SIC",2)}
    assert result.classification_coverage["taxonomies"] == ["SIC", "provider_reported"]
    assert result.provenance["effective_date"] is None and fetch.call_count == 0
    assert "raw_payload_hash" not in result.model_dump_json()
    assert "PROVIDER_TAXONOMIES_NOT_EQUIVALENT_NO_GICS_MAPPING" in result.limitations


def test_post_transport_validation_no_job_or_get_refresh(db, monkeypatch):
    import asyncio
    import json
    from fastapi import FastAPI
    from app.routers import us_market
    from app.db.session import get_db
    app=FastAPI(); app.include_router(us_market.router,prefix="/api/us-market")
    app.dependency_overrides[get_db]=lambda:db
    dispatch=Mock(return_value={"id":1,"job_type":"us_market.sec_sic_sync","status":"queued",
                               "progress_current":0,"progress_total":1,"created_at":NOW,"updated_at":NOW})
    monkeypatch.setattr(us_market,"enqueue_serialized_job",dispatch)
    def call(method, symbols):
        messages=[]
        async def receive():
            return {"type":"http.request","body":json.dumps({"symbols":symbols}).encode(),"more_body":False}
        async def send(message): messages.append(message)
        asyncio.run(app({"type":"http","http_version":"1.1","method":method,"scheme":"http","path":"/api/us-market/stocks/sync-sec-sic","query_string":b"","headers":[(b"content-type",b"application/json")]},receive,send))
        return next(m["status"] for m in messages if m["type"]=="http.response.start")
    assert call("POST",["A"]*17)==422 and dispatch.call_count==0
    assert call("POST",["A"])==202 and dispatch.call_count==1
    assert dispatch.call_args.kwargs["task_args"] == (["A"],)
    assert call("GET",["A"]) in (404,405) and dispatch.call_count==1


def test_existing_tracked_job_runs_typed_command(db, monkeypatch):
    from app.jobs import backfill_tasks
    stock(db, "A", cik="123"); db.commit()
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", Mock(return_value=(payload(), "fixture")))
    results=[]
    def tracked(job_id, worker):
        assert job_id == 123
        results.append(worker(db, Mock()))
    monkeypatch.setattr(backfill_tasks, "run_tracked_job", tracked)
    backfill_tasks.run_us_sec_sic_sync_job(123, ["A"])
    assert sync.USSicSyncResult.model_validate(results[0]).inserted_count == 1


def test_queued_resume_descriptor_and_durable_read_do_not_replay_started_io(db):
    import json
    from app.jobs import backfill_tasks, resumption, service
    task = backfill_tasks.run_us_sec_sic_sync_job
    descriptor = resumption.describe(task, (["A", "B"],), "default")
    descriptor.update(previous_status="queued", previous_result=None, checkpoint={"safe_point":"not_started"})
    assert resumption.validate(descriptor) == (task, (["A", "B"],))
    job = service.create_job(db, job_type="us_market.sec_sic_sync", target="A,B")
    job.status = "paused"
    job.result_json = json.dumps({resumption.RESUME_KEY: descriptor})
    db.commit()
    assert service.read_paused_job_obligations(db) == {job.id: descriptor}
    descriptor["previous_status"] = "running"
    with pytest.raises(ValueError, match="NOT_STARTED_PROVENANCE_INVALID"):
        resumption.validate(descriptor)


def test_real_tracked_job_progress_and_single_profile_transaction(db, monkeypatch):
    from app.jobs import backfill_tasks, service
    stock(db, "A", cik="123"); db.commit()
    job = service.create_job(db, job_type="us_market.sec_sic_sync", target="A", progress_total=1)
    job_id = job.id
    monkeypatch.setattr(service, "SessionLocal", lambda: Session(db.bind))
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", Mock(return_value=(payload(), "fixture")))
    backfill_tasks.run_us_sec_sic_sync_job(job_id, ["A"])
    db.expire_all()
    result = service.serialize_job(service.get_job(db, job_id))
    assert result["status"] == "success" and result["progress_current"] == 1
    assert sync.USSicSyncResult.model_validate(result["result"]).inserted_count == 1
    assert db.query(USCompanyProfile).count() == 1


@pytest.mark.parametrize("current_count", [0, 1, 3])
def test_coverage_low_no_and_all_current_keeps_canonical_eligibility(db, current_count):
    from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
    from test_us_sector_distribution import DAY
    symbols = ["A", "B", "C"]
    for index, symbol in enumerate(symbols):
        stock(db, symbol)
        bar(db, symbol, PREVIOUS)
        if index < current_count:
            bar(db, symbol)
    stock(db, "PARTIAL"); bar(db, "PARTIAL", finalization="provisional")
    stock(db, "BADHASH"); bar(db, "BADHASH", raw_payload_hash="bad")
    stock(db, "MISSING"); stock(db, "FUTURE"); bar(db, "FUTURE", DAY+timedelta(days=3))
    stock(db, "ETF", is_etf=True); bar(db, "ETF")
    db.commit()
    queries=[]
    event.listen(db.bind,"before_cursor_execute",lambda conn,cursor,sql,params,*args:queries.append((sql,params)))
    result=US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(db, expected_trade_date=DAY)
    assert set(result.current_symbols) == set(symbols[:current_count])
    assert set(result.stale_symbols) == set(symbols[current_count:])
    assert set(result.partial_symbols) == {"PARTIAL", "BADHASH"}
    assert set(result.missing_symbols) == {"MISSING", "FUTURE"}
    history=[(sql,params) for sql,params in queries if "max(us_daily_price.trade_date)" in sql]
    assert len(queries)==4 and len(history)==1
    assert history[0][0].count("us_daily_price.symbol IN") == 1
    for symbol in symbols[:current_count]:
        assert symbol not in history[0][1]


def test_universe_pages_cross_16_and_resume_without_refetching_written_profiles(db, monkeypatch):
    for index in range(40):
        stock(db, f"S{index:03d}", cik="123")
    db.commit()
    calls = []
    def fetch(*, cik, **kwargs):
        # One CIK can have multiple admitted tickers; identity still verifies.
        calls.append(cik)
        return payload(tickers=[f"S{i:03d}" for i in range(40)]), "fixture"
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", fetch)
    first = sync.sync_us_sic_coverage(db, request=sync.USSicCoverageSyncRequest(max_symbols=24))
    assert first["processed_count"] == first["fetch_count"] == 24
    assert first["coverage"]["mapped_count"] == 24 and first["continuation_required"]
    second = sync.sync_us_sic_coverage(db, request=sync.USSicCoverageSyncRequest(
        after_symbol=first["next_cursor"], universe_hash=first["universe_hash"], max_symbols=24))
    assert second["processed_count"] == 16 and not second["continuation_required"]
    assert second["coverage"]["mapped_count"] == 40 and len(calls) == 40
    replay = sync.sync_us_sic_coverage(db, request=sync.USSicCoverageSyncRequest())
    assert replay["fetch_count"] == 0 and replay["classification_complete"]
    assert replay["effective_date_status"] == "unknown"


def test_universe_cursor_change_and_failed_batch_do_not_skip_targets(db, monkeypatch):
    stock(db, "A", cik="123"); stock(db, "B", cik="123"); db.commit()
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", Mock(side_effect=sync.USMarketDataFetchError("offline")))
    result = sync.sync_us_sic_coverage(db, request=sync.USSicCoverageSyncRequest())
    assert result["next_cursor"] is None and result["retry_symbols"] == ["A"]
    assert result["coverage"]["unknown_count"] == 2
    stock(db, "C", cik="123"); db.commit()
    with pytest.raises(ValueError, match="UNIVERSE_CHANGED"):
        sync.sync_us_sic_coverage(db, request=sync.USSicCoverageSyncRequest(universe_hash=result["universe_hash"]))


def test_coverage_page_uses_existing_tracked_job(db, monkeypatch):
    from app.jobs import backfill_tasks
    stock(db, "A", cik="123"); db.commit()
    monkeypatch.setattr(sec, "fetch_sec_submissions_payload", Mock(return_value=(payload(), "fixture")))
    outcomes = []
    monkeypatch.setattr(backfill_tasks, "run_tracked_job", lambda job_id, worker: outcomes.append(worker(db, Mock())))
    backfill_tasks.run_us_sec_sic_sync_job(1, None, {"max_symbols": 32})
    assert outcomes[0]["coverage"]["mapped_count"] == 1 and outcomes[0]["fetch_count"] == 1
