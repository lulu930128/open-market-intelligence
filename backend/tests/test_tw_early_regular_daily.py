"""Recorded free-source early receipt -> canonical/revision/read/coverage checks."""
from datetime import date, datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.db.models import MarketDailyPrice, MarketDailyPriceRevision, RawFetchResult, SourceRegistry, StockMaster, TaiwanPublishedBreadthSnapshot
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue, read_taiwan_official_daily, qualify_taiwan_eod_universe
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository, _receipt_is_release_qualified, taiwan_official_daily_release_qualified_filter
from app.market.providers.tw_official_daily import TWSE_RWD_DAILY_RESOURCE_ID, parse_twse_rwd_official_daily_payload
from app.market.taiwan_rules import expected_daily_price_date, expected_daily_research_date
from app.market.tw_daily_freshness import read_taiwan_daily_freshness, read_taiwan_daily_freshness_batch
from app.market.tw_price_map_screening import _read_completed_daily_observations
from app.market_data import eod_coverage as owner
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME
from test_tw_official_daily_platform import db, FakeResponse, FIXTURE_ROOT  # noqa: F401
from test_tw_daily_candidate_repository import _query

DAY = date(2026, 11, 3)
EARLY = datetime(2026, 11, 3, 6, 35, tzinfo=timezone.utc)
FINAL = datetime(2026, 11, 3, 7, 20, tzinfo=timezone.utc)


def payload():
    return json.loads((FIXTURE_ROOT / "twse_rwd_regular_excerpt_20261103.json").read_text(encoding="utf-8"))["payload"]


def seed(db):
    db.add_all([StockMaster(stock_id=symbol, stock_name=symbol, market=venue,
        instrument_type="stock", is_active=True) for symbol, venue in (
            ("2330", "TWSE"), ("2409", "TWSE"), ("3481", "TWSE"), ("6488", "TPEX"))])
    db.commit()


def acquire(db, *, now=EARLY, body=None, route_state=None, venue="TWSE", trade_date=DAY):
    calls = []
    def fetch(route):
        calls.append(route.resource_id)
        return FakeResponse(text=json.dumps(payload() if body is None else body, ensure_ascii=False))
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_RWD_DAILY_RESOURCE_ID: fetch}, clock=lambda: now)
    result = refresh_taiwan_official_daily_venue(db, venue=venue, trade_date=trade_date,
        requested_at=now, acquisition=executor, max_external_calls=2,
        refresh_published=False, route_state=route_state)
    return result, calls


def read(db, *, now=EARLY, research=True):
    return read_taiwan_official_daily(db, stock_id="2330", from_date=DAY - timedelta(days=1), to_date=DAY,
        requested_at=now, allow_early_regular=research).resolved


def test_recorded_scope_and_existing_final_expected_date_stay_separate():
    parsed = parse_twse_rwd_official_daily_payload(json.dumps(payload(), ensure_ascii=False))
    assert len(parsed.records) == 3 and not parsed.issues
    assert {r.trading_scope for r in parsed.records} == {"regular_session"}
    tsmc = next(r for r in parsed.records if r.symbol == "2330")
    assert (tsmc.trade_date, tsmc.trade_volume, tsmc.trade_value, tsmc.transaction_count) == (
        DAY, 36_567_000, 84_242_030_000, 17_745)
    assert expected_daily_price_date(now=EARLY) == date(2026, 11, 2)
    assert expected_daily_research_date(now=EARLY) == DAY
    assert owner.expected_eod_trade_date("TW", now=EARLY) == date(2026, 11, 2)
    assert owner.expected_eod_trade_date("TW", now=EARLY, include_early_regular=True) == DAY
    assert owner.taiwan_bulk_eod_refresh_window(expected_trade_date=DAY, now=EARLY) == (
        True, None, "early_regular_research_opportunity")


def test_early_regular_is_research_only_across_single_batch_sql_and_freshness(db):
    seed(db)
    result, calls = acquire(db)
    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID] and result["external_call_count"] == 1
    assert result["research_ready_count"] == 3 and result["release_status"] == "regular_research"
    assert {r.release_status for r in db.query(MarketDailyPrice)} == {"regular_research"}
    assert db.query(TaiwanPublishedBreadthSnapshot).count() == 0
    assert not read(db, research=False).bars
    assert not read(db, now=FINAL, research=False).bars  # clock passing cannot upgrade a receipt
    assert read(db).bars[0].volume.value == 36_567_000
    assert "OFFICIAL_FINAL_PENDING" in read(db).bars[0].limitations
    strict = TaiwanOfficialDailyBarRepository(db, available_at=EARLY)
    research = TaiwanOfficialDailyBarRepository(db, available_at=EARLY, allow_early_regular=True)
    assert not strict.load_market_universe(trade_date=DAY).bars
    assert len(research.load_market_universe(trade_date=DAY).bars) == 3
    assert len(research.load_daily_bars(_query(start_date=DAY, end_date=DAY)).series) == 1
    kwargs = dict(stock_id="2330", expected_date=DAY, checked_at=EARLY)
    assert read_taiwan_daily_freshness(db, **kwargs).latest_date is None
    assert read_taiwan_daily_freshness(db, **kwargs, allow_early_regular=True).latest_date == DAY
    batch = read_taiwan_daily_freshness_batch(db, stock_ids=["2330", "6488"], expected_date=DAY,
        checked_at=EARLY, allow_early_regular=True)
    assert batch["2330"].latest_date == DAY and batch["6488"].latest_date is None
    assert not owner.compute_eod_coverage(db, market="TW", expected_trade_date=DAY,
        taiwan_daily_qualifier=qualify_taiwan_eod_universe).postcondition_met
    whole = read_taiwan_daily_freshness(db, expected_date=DAY, checked_at=EARLY, allow_early_regular=True)
    assert whole.health.status.value == "partial"


@pytest.mark.parametrize("defect", ["before_window", "after_window", "date", "scope", "source", "parser", "volume", "trade_value", "finalization", "authority", "receipt_source", "http_failure", "receipt_error", "missing_hash"])
def test_research_qualification_sql_python_parity_rejects_unproven_rows(db, defect):
    seed(db)
    acquire(db)
    row = db.query(MarketDailyPrice).filter_by(stock_id="2330").one()
    raw = db.get(RawFetchResult, row.raw_result_id)
    source = db.get(SourceRegistry, row.source_id)
    if defect == "before_window": raw.fetched_at = EARLY.replace(minute=29)
    elif defect == "after_window": raw.fetched_at = FINAL
    elif defect == "date": row.trade_date = DAY + timedelta(days=1)
    elif defect == "scope": row.derivation_kind = None
    elif defect == "source": source.source_name = "unverified_source"
    elif defect == "parser": raw.parser_version = "twse_mi_index_allbut0999.v1"
    elif defect == "volume": row.trade_volume = None
    elif defect == "trade_value": row.trade_value = None
    elif defect == "finalization": row.finalization = "provisional"
    elif defect == "authority": row.authority = "vendor"
    elif defect == "receipt_source": raw.source_id = row.source_id + 100
    elif defect == "http_failure": raw.status_code = 503
    elif defect == "receipt_error": raw.error_message = "provider failed"
    elif defect == "missing_hash": raw.content_hash = None
    db.flush()
    python_qualified = _receipt_is_release_qualified(trade_date=row.trade_date, fetched_at=raw.fetched_at,
        price=row, source_name=source.source_name, receipt=raw, allow_early_regular=True)
    sql_qualified = db.query(MarketDailyPrice.id).join(RawFetchResult,
        RawFetchResult.id == MarketDailyPrice.raw_result_id).join(SourceRegistry,
        SourceRegistry.id == MarketDailyPrice.source_id).filter(MarketDailyPrice.id == row.id,
        taiwan_official_daily_release_qualified_filter(allow_early_regular=True)).first() is not None
    assert python_qualified is False and sql_qualified is False


@pytest.mark.parametrize("defect", ["no_scope", "wrong_date", "empty", "no_ohlc", "before_window"])
def test_unavailable_early_payload_preserves_receipt_without_publishing(db, defect):
    seed(db)
    body = payload()
    now = EARLY
    if defect == "no_scope": body["tables"][0]["notes"] = []
    elif defect == "wrong_date": body["date"] = "20261102"
    elif defect == "empty": body["tables"][0]["data"] = []
    elif defect == "no_ohlc":
        for row in body["tables"][0]["data"]: row[5] = "--"
    else: now = EARLY.replace(minute=29)
    result, calls = acquire(db, body=body, now=now)
    assert not db.query(MarketDailyPrice).count() and not result["research_ready_count"]
    assert result["external_call_count"] <= 1
    assert db.query(RawFetchResult).count() == len(calls)
    assert not read(db).bars


def test_final_reacquisition_resets_early_continuation_retains_scope_and_pit(db):
    seed(db)
    early, _ = acquire(db)
    early_raw = db.query(MarketDailyPrice).filter_by(stock_id="2330").one().raw_result_id
    later = payload()
    later["tables"][0]["notes"] = ["本統計資訊含一般、零股、盤後定價及鉅額交易，不含拍賣、標購。"]
    later["tables"][0]["data"][0][2] = "37,000,001"
    final, calls = acquire(db, now=FINAL, body=later, route_state=early["route_continuation"])
    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID] and final["release_status"] == "released"
    assert read(db, now=FINAL, research=False).bars[0].volume.value == 37_000_001
    assert read(db).bars[0].volume.value == 36_567_000
    assert not read(db, research=False).bars
    assert db.query(MarketDailyPriceRevision).filter_by(raw_result_id=early_raw).count() == 3
    assert read_taiwan_daily_freshness(db, stock_id="2330", checked_at=EARLY,
        expected_date=DAY, allow_early_regular=True).latest_date == DAY
    assert read_taiwan_daily_freshness_batch(db, stock_ids=["2330"], checked_at=EARLY,
        expected_date=DAY, allow_early_regular=True)["2330"].latest_date == DAY
    metadata = TaiwanOfficialDailyBarRepository(db, available_at=EARLY).outward_state_metadata(
        (read(db).bars[0].lineage.observation_id,))
    assert next(iter(metadata.values()))["release_status"] == "regular_research"


def test_scanner_uses_exact_daily_scope_without_1m_or_hidden_io(db, monkeypatch):
    seed(db)
    acquire(db)
    statements = []
    select_only = []
    def trace(_conn, _cursor, statement, _parameters, context, _executemany):
        statements.append(statement.strip().upper())
        # Canonical PIT reads may start with WITH; inspect the compiled operation
        # so a CTE SELECT passes while a CTE-backed mutation still fails.
        select_only.append(bool(context.compiled is not None and context.compiled.statement.is_select))
    def forbidden(*_args, **_kwargs): raise AssertionError("cache-only read attempted mutation/acquisition")
    monkeypatch.setattr(db, "commit", forbidden)
    monkeypatch.setattr("app.market.daily_ohlcv_acquisition._default_fetch", forbidden)
    event.listen(db.bind, "before_cursor_execute", trace)
    try:
        observations = _read_completed_daily_observations(db, stock_ids=["2330", "6488"], basis_date=DAY, now=EARLY)
        assert observations["2330"]["research_usable"] and not observations["2330"]["decision_usable"]
        assert observations["2330"]["price_semantics"] == "official_regular_session_research_close"
        assert observations["2330"]["release_status"] == "regular_research"
        assert not observations["6488"]["research_usable"]
        assert not _read_completed_daily_observations(db, stock_ids=["2330"], basis_date=DAY + timedelta(days=1), now=EARLY)["2330"]["research_usable"]
        read(db)
    finally:
        event.remove(db.bind, "before_cursor_execute", trace)
    assert statements and all(select_only)


def test_early_job_is_bounded_partial_and_unverified_tpex_does_no_io(db):
    seed(db)
    calls = []
    def refresh(**kwargs):
        result, used = acquire(kwargs.pop("db"), now=EARLY, venue=kwargs["venue"], route_state=kwargs.get("route_state"))
        calls.extend(used)
        return result
    with patch.object(owner, "utc_now", return_value=EARLY):
        result = owner.reconcile_eod_coverage(db, market="TW", expected_trade_date=DAY,
            max_symbols=2, max_runtime_seconds=120, sleep_seconds=0,
            taiwan_daily_qualifier=qualify_taiwan_eod_universe, taiwan_venue_refresher=refresh)
    assert result["postcondition_met"] is False and result["status"] == "partial"
    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID] and result["external_call_budget_used"] == 1
    assert db.query(MarketDailyPrice).count() == 3


def test_final_tpex_secondary_remains_readable_in_canonical_and_freshness(db):
    from test_tpex_daily_close_recovery import acquire as acquire_tpex, raw_payload, DAY as tpex_day, NOW
    seed(db)
    result, calls = acquire_tpex(db, FakeResponse(text="[]"), FakeResponse(text=raw_payload()))
    assert result["parsed_count"] == 1 and len(calls) == 2
    assert TaiwanOfficialDailyBarRepository(db).load_market_universe(trade_date=tpex_day).bars
    assert read_taiwan_daily_freshness(db, stock_id="6488", expected_date=tpex_day, checked_at=NOW).latest_date == tpex_day
