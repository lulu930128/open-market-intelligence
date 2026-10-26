"""Offline grouped EOD -> canonical persistence -> US snapshot acceptance."""
from datetime import date, datetime, time, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import event, create_engine, inspect, text
from sqlalchemy.orm import Session
from alembic import command

from app.config import Settings
from app.db.models import Base, USDailyPrice, RawFetchResult
from app.db.migrations import create_alembic_config
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor, USProviderPayload
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE as owner
from app.us_market.market_data.descriptors import MASSIVE_GROUPED_DAILY_RESOURCE_ID
from app.us_market.providers import massive
from app.us_market.providers.errors import USProviderDataError
from app.us_market.providers.canonical import canonical_massive_grouped_daily_payload
from app.us_market.sector_distribution import read_us_sector_distribution
from app.us_market.trading_calendar import US_MARKET_TIMEZONE
from test_us_sector_distribution import stock, profile, NOW, DAY, PREVIOUS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("network forbidden")))


def payload(day=DAY, symbols=("A",), volume=123.125, **changes):
    result = {"status": "OK", "adjusted": False, "resultsCount": len(symbols), "results": [
        {"T": symbol, "o": 100, "h": 120, "l": 90, "c": 110, "v": volume, "vw": 106.25,
         "t": int(datetime.combine(day, time(), tzinfo=US_MARKET_TIMEZONE).timestamp() * 1000), "n": 8}
        for symbol in symbols]}
    result.update(changes)
    return result


def executor(body, now=NOW):
    fetch = Mock(return_value=USProviderPayload(body, f"https://api.massive.com/grouped/{DAY}"))
    return USDailyOhlcvAcquisitionExecutor(fetchers={MASSIVE_GROUPED_DAILY_RESOURCE_ID: fetch},
        settings=Settings(massive_api_key="fixture"), clock=lambda: now), fetch


@pytest.mark.parametrize("now,day,allowed", [
    ("2026-10-24T03:59:59+00:00", DAY, False),
    ("2026-10-24T04:00:00+00:00", DAY, True),
    ("2026-11-03T04:59:59+00:00", date(2026,11,2), False),
    ("2026-11-03T05:00:00+00:00", date(2026,11,2), True),
    ("2026-10-26T12:00:00+00:00", date(2026,10,25), False),
    ("2026-12-26T12:00:00+00:00", date(2026,12,25), False),
])
def test_et_release_dst_weekend_holiday(now, day, allowed):
    if allowed:
        massive.require_grouped_daily_available(trade_date=day, now=datetime.fromisoformat(now))
    else:
        with pytest.raises(USProviderDataError):
            massive.require_grouped_daily_available(trade_date=day, now=datetime.fromisoformat(now))


def test_request_raw_only_no_retry_and_403_non_json(monkeypatch):
    response = Mock(status_code=200, url="fixture")
    response.json.return_value = payload()
    http = Mock(return_value=response)
    monkeypatch.setattr(massive, "provider_get", http)
    massive.fetch_massive_grouped_daily_payload(trade_date=DAY, now=NOW, api_key="fixture", timeout_seconds=3)
    assert http.call_args.kwargs["params"] == {"adjusted": "false", "include_otc": "false"}
    response.status_code = 403
    response.json.side_effect = ValueError("html")
    with pytest.raises(USProviderDataError, match="MASSIVE_NOT_ENTITLED"):
        massive.fetch_massive_grouped_daily_payload(trade_date=DAY, now=NOW, api_key="fixture", timeout_seconds=3)
    assert http.call_count == 2


def test_http_fractional_shares_keeps_decimal_token_through_persistence(db, monkeypatch):
    import json
    import requests
    stock(db, "A"); db.commit()
    response = requests.Response()
    response.status_code = 200
    response.url = "https://api.massive.com/fixture"
    exact = "123.1234567890123456789"
    response._content = json.dumps(payload()).replace("123.125", exact).encode()
    monkeypatch.setattr(massive, "provider_get", Mock(return_value=response))
    body, _ = massive.fetch_massive_grouped_daily_payload(
        trade_date=DAY, now=NOW, api_key="fixture", timeout_seconds=3)
    assert body["results"][0]["v"] == Decimal(exact)
    acquisition, _ = executor(body)
    result = owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert result["status"] == "complete"
    assert db.query(USDailyPrice).one().trade_volume_decimal == exact
    assert exact in db.query(RawFetchResult).one().raw_text


@pytest.mark.parametrize("adjusted", [True, None, "false", 0])
def test_adjusted_response_rejected_not_relabelled(adjusted):
    with pytest.raises(ValueError, match="RAW_BASIS"):
        canonical_massive_grouped_daily_payload(payload=payload(adjusted=adjusted), instruments={}, trade_date=DAY, fetched_at=NOW)


def test_fractional_roundtrip_batch_idempotency_and_snapshot(db):
    for symbol in ("A", "B"):
        stock(db, symbol); profile(db, symbol)
    stock(db, "ETF", is_etf=True)
    stock(db, "PREFERRED", security_name="Fixture Preferred Shares")
    db.commit()
    for day in (PREVIOUS, DAY):
        acquired, fetch = executor(payload(day, ("A", "B", "ETF", "PREFERRED", "OUTSIDE")))
        result = owner.refresh_grouped_daily(db, trade_date=day, now=NOW, acquisition=acquired)
        assert result["status"] == "complete" and result["accepted_count"] == 2
        assert result["rejected_counts"] == {"OUTSIDE_ELIGIBLE_STOCKMASTER_UNIVERSE": 3}
        repeated = owner.refresh_grouped_daily(db, trade_date=day, now=NOW, acquisition=acquired)
        assert repeated["persistence"]["observations_unchanged"] == 2
        assert repeated["persistence"]["receipts_written"] == 0
    assert db.query(USDailyPrice).count() == 4 and db.query(RawFetchResult).count() == 2
    assert all(r.trade_volume is None and r.trade_volume_decimal == "123.125" for r in db.query(USDailyPrice))
    assert USDailyOhlcvPlatform(db).read(symbol="A", bars=2, now=NOW).result.resolved.bars[-1].volume.value == Decimal("123.125")
    owner.publish_distribution(db, now=NOW)
    queries = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, sql, *args: queries.append(sql))
    result = read_us_sector_distribution(db, now=NOW)
    assert result.counts.comparable == 2 and result.counts.flat == 2
    assert result.is_full_market and not result.sample_only and not result.decision_usable
    assert result.data_mode == "eod_market_snapshot"
    assert len(queries) == 1 and "us_daily_price" not in queries[0]
    assert result.coverage["comparable_coverage_ratio"] == 1
    assert result.industries[0].relative_strength_pct == 0
    assert result.industries[0].turnover_value is None


def test_partial_malformed_duplicate_wrong_day_and_missing(db):
    for symbol in ("A", "B", "C", "D", "E"):
        stock(db, symbol)
    db.commit()
    body = payload(symbols=("A", "B", "C", "D"))
    body["results"][1]["v"] = None
    body["results"][2]["t"] += 86400 * 1000
    body["results"].append(body["results"][3])
    body["resultsCount"] = 99
    acquisition, _ = executor(body)
    result = owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert result["status"] == "partial" and result["accepted_count"] == 1
    assert result["missing_count"] == 4 and not result["provider_count_matches"]
    assert result["rejected_counts"] == {"INVALID_OHLC_OR_SHARES": 1, "INVALID_ET_SESSION_TIMESTAMP": 1, "DUPLICATE_SYMBOL": 2}
    assert db.query(USDailyPrice).one().symbol == "A"
    assert "partial" in db.query(RawFetchResult).one().error_message


@pytest.mark.parametrize("category,code", [("entitlement", "MASSIVE_NOT_ENTITLED"), ("rate_limit", "MASSIVE_RATE_LIMITED")])
def test_failures_have_receipt_and_stop_without_fallback(db, category, code):
    stock(db, "A"); db.commit()
    acquisition, fetch = executor(payload())
    fetch.side_effect = USProviderDataError(provider="massive", category=category, code=code, message="sensitive discarded")
    result = owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert result["reason"] == code and result["external_call_count"] == fetch.call_count == 1
    assert db.query(USDailyPrice).count() == 0
    receipt = db.query(RawFetchResult).one()
    assert receipt.status_code == (403 if category == "entitlement" else 429)
    assert "sensitive" not in receipt.raw_text


def test_no_key_or_release_no_call(db):
    stock(db, "A"); db.commit()
    acquisition = USDailyOhlcvAcquisitionExecutor(settings=Settings(massive_api_key=""), clock=lambda: NOW)
    result = owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert result["reason"] == "MASSIVE_API_KEY_NOT_CONFIGURED" and result["external_call_count"] == 0
    assert db.query(RawFetchResult).count() == 0


def test_missing_snapshot_is_unknown_and_old_snapshot_stays_stale(db):
    missing = read_us_sector_distribution(db, now=NOW)
    assert missing.status == "unavailable" and missing.coverage["universe_count"] is None
    assert missing.classification_coverage["mapped_count"] is None
    stock(db, "A"); profile(db, "A"); db.commit()
    for day in (PREVIOUS, DAY):
        acquisition, _ = executor(payload(day))
        owner.refresh_grouped_daily(db, trade_date=day, now=NOW, acquisition=acquisition)
    owner.publish_distribution(db, now=NOW)
    old = read_us_sector_distribution(db, now=datetime(2026,10,27,12,tzinfo=timezone.utc))
    assert old.freshness_status == "stale" and old.as_of == DAY.isoformat()
    assert old.expected_trade_date == "2026-10-26" and not old.decision_usable
    assert "SNAPSHOT_BEHIND_EXPECTED_SESSION" in old.limitations


def test_grouped_job_uses_existing_owner_and_no_symbol_repair(db, monkeypatch):
    from app.jobs import eod_coverage as jobs
    acquired = Mock(return_value={"status": "complete", "external_call_count": 1})
    published = Mock(return_value={"status": "partial"})
    monkeypatch.setattr(owner, "refresh_grouped_daily", acquired)
    monkeypatch.setattr(owner, "publish_distribution", published)
    monkeypatch.setattr(jobs, "reconcile_eod_coverage", Mock(side_effect=AssertionError("no per-symbol fallback")))
    outcomes = []
    monkeypatch.setattr(jobs.job_service, "run_tracked_job", lambda job_id, worker: outcomes.append(worker(db, Mock())))
    jobs.run_eod_coverage_reconcile_job(1, "US", True, DAY, 250, 60, 0, 1, 60, True)
    assert acquired.call_count == published.call_count == 1
    assert outcomes[0]["external_call_count"] == 1


def test_grouped_job_wont_replay_forbidden_or_unknown_date(db, monkeypatch):
    import json
    from app.db.models import JobRun
    from app.jobs import eod_coverage as jobs
    from app.jobs.job_types import MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE
    db.add(JobRun(job_type=MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
        target="US:full_market_stock_universe", status="failed",
        request_json=json.dumps({"grouped_daily": True, "expected_trade_date": DAY.isoformat()}),
        result_json=json.dumps({"reason": "MASSIVE_NOT_ENTITLED", "external_call_count": 1}),
        started_at=datetime(2026,10,24,12,tzinfo=timezone.utc)))
    db.commit()
    acquire = Mock(side_effect=AssertionError("no retry"))
    monkeypatch.setattr(owner, "refresh_grouped_daily", acquire)
    def tracked(job_id, worker):
        with pytest.raises(jobs.job_service.JobExecutionError) as caught:
            worker(db, Mock())
        assert caught.value.result["external_call_count"] == 0
    monkeypatch.setattr(jobs.job_service, "run_tracked_job", tracked)
    jobs.run_eod_coverage_reconcile_job(999, "US", True, DAY, 250, 60, 0, 1, 60, True)
    assert acquire.call_count == 0


def test_grouped_request_rejects_tw_or_read_only():
    from app.market_data.eod_coverage_schemas import EODCoverageReconcileRequest
    from pydantic import ValidationError
    for args in ({"market": "TW"}, {"market": "US", "repair": False}):
        with pytest.raises(ValidationError):
            EODCoverageReconcileRequest(grouped_daily=True, **args)


def test_uncertain_commit_without_rows_stays_unknown(db, monkeypatch):
    from app.utils.owner_checkpoint import OwnerOutcomeUnknown
    stock(db, "A"); db.commit()
    acquisition, fetch = executor(payload())
    monkeypatch.setattr(db, "commit", Mock(side_effect=OSError("unacknowledged")))
    with pytest.raises(OwnerOutcomeUnknown):
        owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert fetch.call_count == 1 and db.query(USDailyPrice).count() == 0


def test_commit_ack_lost_reconciles_without_refetch(db, monkeypatch):
    stock(db, "A"); db.commit()
    acquisition, fetch = executor(payload())
    original = db.commit
    def lost_ack():
        original()
        raise OSError("commit acknowledgement lost")
    monkeypatch.setattr(db, "commit", lost_ack)
    result = owner.refresh_grouped_daily(db, trade_date=DAY, now=NOW, acquisition=acquisition)
    assert result["reconciliation"] == "committed" and fetch.call_count == 1
    assert db.query(USDailyPrice).count() == 1


def test_0092_to_0093_isolated_sqlite_preserves_legacy_rows(tmp_path):
    url = f"sqlite:///{(tmp_path / 'g1-volume.db').as_posix()}"
    config = create_alembic_config(url)
    engine = create_engine(url)
    # Isolate the requested 0092 -> 0093 boundary. The pre-existing baseline
    # uses current metadata and 0092 re-creates its already-present job index,
    # so an empty -> head chain has an unrelated duplicate-index failure.
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE us_daily_price DROP COLUMN trade_volume_decimal"))
    command.stamp(config, "20261009_0092")
    with engine.begin() as connection:
        assert "trade_volume_decimal" not in {c["name"] for c in inspect(connection).get_columns("us_daily_price")}
        connection.execute(text("INSERT INTO us_daily_price(provider,symbol,trade_date,currency,trade_volume,fetched_at,created_at,updated_at) VALUES ('fixture','A','2026-10-23','USD',123,'2026-10-24','2026-10-24','2026-10-24')"))
    command.upgrade(config, "20261025_0093")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261025_0093"
        assert connection.execute(text("SELECT trade_volume,trade_volume_decimal FROM us_daily_price")).one() == (123, None)
        connection.execute(text("UPDATE us_daily_price SET trade_volume=NULL,trade_volume_decimal='123.125'"))
    with pytest.raises(RuntimeError, match="retention plan"):
        command.downgrade(config, "20261009_0092")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT trade_volume_decimal FROM us_daily_price")).scalar_one() == "123.125"
    engine.dispose()


@pytest.mark.parametrize("change", [None, "universe", "date", "qualification"])
def test_materialized_snapshot_lifecycle_on_normal_coverage_reconcile(db, change):
    from dataclasses import replace
    from app.market_data.eod_coverage import persist_eod_coverage
    stock(db, "A"); profile(db, "A"); db.commit()
    for day in (PREVIOUS, DAY):
        acquisition, _ = executor(payload(day))
        owner.refresh_grouped_daily(db, trade_date=day, now=NOW, acquisition=acquisition)
    owner.publish_distribution(db, now=NOW)
    original = read_us_sector_distribution(db, now=NOW)
    coverage = owner.compute_coverage(db, expected_trade_date=DAY)
    query_time = NOW
    if change == "universe":
        stock(db, "B"); db.commit()
        coverage = owner.compute_coverage(db, expected_trade_date=DAY)
    elif change == "date":
        coverage = owner.compute_coverage(db, expected_trade_date=date(2026, 10, 26))
        query_time = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    elif change == "qualification":
        coverage = replace(coverage, current_symbols=frozenset(), missing_symbols=frozenset({"A"}))
    persist_eod_coverage(db, coverage)
    actual = read_us_sector_distribution(db, now=query_time)
    if change is None:
        assert actual == original
    else:
        assert actual.status == "unavailable" and actual.as_of is None
        assert "US_EOD_SNAPSHOT_NOT_MATERIALIZED" in actual.limitations
