"""Isolated JP receipt/revision/Gateway acceptance; no external provider calls."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import Base, JPBarEvidence, JPStockMaster, RawFetchResult
from app.jp_market.bar_transaction import JPBarTransaction
from app.jp_market.daily_platform import JPDailyPlatform
from app.jp_market.daily_repository import JPDailyBarRepository
from app.jp_market.market_data.adapters import adapt_yahoo_daily, jp_daily_session_end
from app.jp_market.service import get_jp_intraday_trend
from app.market_data.candidate_repository import DailyBarCandidateQuery, CandidateReadLimitExceeded
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.routers.jp_market import get_jp_intraday_trend_api, get_jp_ohlc_chart_data


TOKYO = timezone(timedelta(hours=9))
DAY = date(2026, 9, 10)
FETCHED = datetime(2026, 9, 10, 17, tzinfo=TOKYO)
INSTRUMENT = InstrumentKey(market=Market.JP, symbol="7203.T", venue="XJPX", instrument_type=InstrumentType.STOCK)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def payload(close=105):
    return {"chart": {"result": [{
        "meta": {"symbol": "7203.T", "currency": "JPY", "gmtoffset": 32400, "exchangeTimezoneName": "Asia/Tokyo"},
        "timestamp": [int(datetime.combine(DAY, datetime.min.time(), tzinfo=TOKYO).replace(hour=9).timestamp())],
        "indicators": {"quote": [{"open": [100], "high": [110], "low": [95], "close": [close], "volume": [1000]}]},
    }], "error": None}}


def adapted(close=105, fetched=FETCHED):
    return adapt_yahoo_daily(payload(close), instrument=INSTRUMENT, fetched_at=fetched)


def query(available=FETCHED):
    return DailyBarCandidateQuery(instrument=INSTRUMENT, start_date=DAY, end_date=DAY, available_at=available)


def seed_master(db):
    db.add(JPStockMaster(symbol="7203.T", local_code="7203", security_name="Toyota",
                         exchange="Tokyo Stock Exchange", asset_type="stock", currency="JPY",
                         listing_source="test", is_active=True))
    db.commit()


def test_jp_identity_accepts_persisted_vendor_etf_type_case(db):
    from app.jp_market.identity import read_jp_instrument
    seed_master(db)
    master=db.query(JPStockMaster).one()
    master.asset_type="ETF"
    db.commit()
    assert read_jp_instrument(db,"7203.T").instrument_type is InstrumentType.ETF


def test_provider_attempt_failure_preserves_last_good_and_read_is_pure(db):
    from types import SimpleNamespace
    from app.jp_market.daily_health import publish_daily_attempts, read_daily_attempts, planning_daily_health
    from app.market_data.contracts import ProviderResourceHealth, EnablementStatus, ConnectionStatus, EntitlementStatus, OperationalStatus, EvidenceFreshness
    good = ProviderResourceHealth(provider="yahoo_chart", market=Market.JP, capability="daily.ohlcv", resource_id="yahoo.jp.daily", enablement=EnablementStatus.ENABLED, connection=ConnectionStatus.CONNECTED, entitlement=EntitlementStatus.ENTITLED, operational=OperationalStatus.HEALTHY, freshness=EvidenceFreshness.FRESH, checked_at=FETCHED)
    acquisition = SimpleNamespace(attempted=True, providers_attempted=("yahoo_chart",))
    publish_daily_attempts(db, symbol="7203.T", result=SimpleNamespace(acquisition=acquisition, provider_health=(good,)))
    later = FETCHED + timedelta(minutes=1)
    failed = good.model_copy(update={"operational":OperationalStatus.FAILED,"freshness":EvidenceFreshness.UNKNOWN,"checked_at":later,"detail_code":"PROVIDER_REQUEST_FAILED"})
    publish_daily_attempts(db, symbol="7203.T", result=SimpleNamespace(acquisition=acquisition, provider_health=(failed,)))
    attempts = read_daily_attempts(db, symbol="7203.T", now=later)
    assert attempts[0].latest_attempt == failed and attempts[0].last_good == good
    assert not read_daily_attempts(db, symbol="9984.T", now=later)
    assert planning_daily_health(db, symbol="7203.T", now=later) == (failed,)
    assert not planning_daily_health(db, symbol="7203.T", now=later+timedelta(minutes=16))


def test_canonical_consumers_share_price_identity_and_do_not_read_legacy(db):
    from app.config import settings
    from app.jp_market.daily_projection import read_daily_context_asset, read_daily_rows, read_overview_rows
    from app.jp_market.valuation import read_jp_valuation_price
    seed_master(db)
    JPBarTransaction(db).persist_daily(adapted())
    statements = []
    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        with patch.object(settings, "jp_canonical_daily_mode", "on"):
            rows = read_daily_rows(db, symbol="7203.T", requested_at=FETCHED)
            asset = read_daily_context_asset(db, symbol="7203.T", label="Toyota", now=FETCHED)
            valuation = read_jp_valuation_price(db, symbol="7203.T", requested_at=FETCHED)
            overview = read_overview_rows(db, expected_trade_date=DAY, requested_at=FETCHED)
        assert rows[0].close_price == asset["price"] == valuation.price == overview["7203.T"][0]["close_price"] == 105
        assert rows[0].evidence_id == asset["evidence_id"] == overview["7203.T"][0]["evidence_id"]
        assert asset["change_pct"] is None
        assert not any("jp_daily_price" in sql or "raw_fetch_result.raw_text" in sql for sql in statements)
        assert not any(sql.lstrip().startswith(("insert", "update", "delete")) for sql in statements)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


def test_source_health_read_never_flushes_or_publishes(db):
    from app.jp_market.source_health import build_jp_source_health
    from app.db.models import SourceHealthSnapshot
    pending = JPStockMaster(symbol="7203.T", local_code="7203", security_name="Toyota",
                             exchange="Tokyo Stock Exchange", asset_type="stock", currency="JPY",
                             listing_source="test", is_active=True)
    db.add(pending)
    writes = []
    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().lower().startswith(("insert", "update", "delete")):
            writes.append(statement)
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = build_jp_source_health(db, symbol="7203.T", now=FETCHED)
        assert result["generated_at"] == FETCHED.isoformat()
        assert pending.id is None and not writes
        with db.no_autoflush:
            assert db.query(SourceHealthSnapshot).count() == 0
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


def test_ai_context_preserves_canonical_identity_and_evaluation_clock(db):
    from app.config import settings
    from app.jp_market import service
    from app.ai.market_context.jp_context import JPContextDependencies, read_jp_stock_context
    seed_master(db)
    JPBarTransaction(db).persist_daily(adapted())
    with patch.object(settings, "jp_canonical_daily_mode", "on"), patch.object(service, "fetch_yahoo_chart_payload", side_effect=AssertionError("context acquired")):
        context = read_jp_stock_context(db, symbol="7203.T", dependencies=JPContextDependencies(jp_market_service=service, now=lambda: FETCHED))
    row = context["data"]["daily_prices"][0]
    assert row["close_price"] == context["summary"]["latest_close"] == 105
    assert row["price_basis"] == "raw" and row["evidence_id"]
    assert context["data"]["chart"]["latest_data_date"] == DAY.isoformat()
    assert context["data"]["chart"]["is_current"]
    assert any(ref.get("evidence_id") == row["evidence_id"] and ref.get("type") == "database" for ref in context["source_refs"])
    assert not any(ref.get("type") == "table" and ref.get("name") == "jp_daily_price" for ref in context["source_refs"])


def test_intraday_comparison_uses_exact_canonical_previous_session(db):
    from app.config import settings
    from app.jp_market.service import _apply_jp_intraday_previous_close_reference
    seed_master(db)
    JPBarTransaction(db).persist_daily(adapted())
    payload = {"previous_close":999.0,"previous_close_source":"yahoo_finance_chart",
               "points":[{"time":"2026-09-11T15:30:00+09:00","price":106.0}]}
    with patch.object(settings, "jp_canonical_daily_mode", "on"):
        result = _apply_jp_intraday_previous_close_reference(payload, db=db, symbol="7203.T")
    assert result["previous_close"] == 105.0
    assert result["provider_previous_close"] == 999.0
    assert result["previous_close_trade_date"] == "2026-09-10"
    assert result["change_reference"]["evidence_id"]
    assert result["change_reference"]["price_basis"] == "raw"
    payload["points"][0]["time"] = "2026-09-14T10:00:00+09:00"
    with patch.object(settings, "jp_canonical_daily_mode", "on"):
        missing = _apply_jp_intraday_previous_close_reference(payload, db=db, symbol="7203.T")
    assert missing["previous_close"] is None
    assert "PREVIOUS_SESSION_REFERENCE_UNAVAILABLE" in missing["warnings"]


def test_receipt_persistence_reread_gateway_and_replay(db):
    result = adapted()
    first = JPBarTransaction(db).persist_daily(result)
    second = JPBarTransaction(db).persist_daily(adapted(fetched=FETCHED + timedelta(minutes=1)))
    assert first.observations_inserted == 1
    assert second.observations_unchanged == 1 and second.receipts_written == 0
    assert db.query(JPBarEvidence).count() == db.query(RawFetchResult).count() == 1
    read = JPDailyPlatform(db).read(instrument=INSTRUMENT, start_date=DAY, end_date=DAY, requested_at=FETCHED)
    assert read.resolved.bars[0].close_price == 105
    assert read.resolved.bars[0].lineage.raw_receipt_id == str(first.raw_result_ids[0])
    assert read.acquisition.attempted is False


def test_revision_is_immutable_and_as_of_is_preserved(db):
    JPBarTransaction(db).persist_daily(adapted())
    later = FETCHED + timedelta(hours=1)
    JPBarTransaction(db).persist_daily(adapted(close=106, fetched=later))
    old = JPDailyBarRepository(db).load_daily_bars(query())
    new = JPDailyBarRepository(db).load_daily_bars(query(later))
    assert old.series[0].bars[0].close_price == 105
    assert new.series[0].bars[0].close_price == 106
    assert db.query(JPBarEvidence).count() == 2
    assert new.rejections[0].reason_code == "SUPERSEDED_REVISION"


def test_later_correction_can_return_to_an_earlier_price(db):
    JPBarTransaction(db).persist_daily(adapted())
    JPBarTransaction(db).persist_daily(adapted(close=106, fetched=FETCHED + timedelta(hours=1)))
    reverted_at = FETCHED + timedelta(hours=2)
    JPBarTransaction(db).persist_daily(adapted(close=105, fetched=reverted_at))
    read = JPDailyBarRepository(db).load_daily_bars(query(reverted_at))
    assert read.series[0].bars[0].close_price == 105
    assert db.query(JPBarEvidence).count() == 3


def test_jquants_raw_fields_no_trade_and_pagination_are_truthful():
    from app.jp_market.market_data.adapters import adapt_jquants_daily
    raw = {"data": [{"Date": DAY.isoformat(), "Code": "72030", "O": 100, "H": 110,
                     "L": 95, "C": 105, "Vo": 1000, "AdjC": 52.5}], "pagination_key": "next"}
    result = adapt_jquants_daily(raw, instrument=INSTRUMENT, fetched_at=FETCHED, start_date=DAY, end_date=DAY)
    assert result.bars[0].close_price == 105
    assert result.bars[0].price_basis == "raw"
    assert result.rejections == (("page", "PAGINATION_INCOMPLETE"),)
    raw["data"][0]["C"] = None
    missing = adapt_jquants_daily(raw, instrument=INSTRUMENT, fetched_at=FETCHED, start_date=DAY, end_date=DAY)
    assert not missing.bars
    assert (DAY.isoformat(), "INVALID_CANONICAL_BAR") in missing.rejections


def test_gateway_acquisition_persist_reread_and_idempotent_refresh(db):
    from app.jp_market.daily_acquisition import JPDailyAcquisition
    from app.jp_market.market_data.descriptors import JP_DAILY_DESCRIPTORS
    calls = []
    def fetch(route, requirement):
        calls.append(route.resource_id)
        return payload(), None
    acquisition = JPDailyAcquisition(fetchers={"yahoo_chart": fetch}, clock=lambda: FETCHED)
    platform = JPDailyPlatform(db)
    args = dict(instrument=INSTRUMENT, start_date=DAY, end_date=DAY, requested_at=FETCHED,
                descriptors=(JP_DAILY_DESCRIPTORS[1],), acquisition_port=acquisition)
    result = platform.refresh_daily_ohlcv(**args)
    assert result.resolved.bars[0].close_price == 105
    assert result.persistence.committed and result.acquisition.external_calls == 1
    again = platform.refresh_daily_ohlcv(**args)
    assert not again.acquisition.attempted and len(calls) == 1


def test_gateway_failed_provider_is_not_hidden_by_fallback(db):
    from app.jp_market.daily_acquisition import JPDailyAcquisition
    from app.jp_market.market_data.descriptors import JP_DAILY_DESCRIPTORS
    def failed(route, requirement):
        raise TimeoutError("private provider text must not reach output")
    acquisition = JPDailyAcquisition(
        fetchers={"jquants": failed, "yahoo_chart": lambda route, requirement: (payload(), None)},
        clock=lambda: FETCHED,
    )
    result = JPDailyPlatform(db).refresh_daily_ohlcv(
        instrument=INSTRUMENT, start_date=DAY, end_date=DAY, requested_at=FETCHED,
        acquisition_port=acquisition, descriptors=JP_DAILY_DESCRIPTORS,
    )
    assert result.resolved.bars[0].close_price == 105
    assert result.acquisition.external_calls == 2
    assert any(h.provider == "jquants" and h.detail_code == "PROVIDER_REQUEST_FAILED" for h in result.provider_health)
    assert "private provider text" not in result.model_dump_json()


def test_persistence_rolls_back_receipt_on_invalid_observation(db):
    result = adapted()
    bad = result.bars[0].model_copy(update={"instrument": INSTRUMENT.model_copy(update={"market": Market.US})})
    from dataclasses import replace
    with pytest.raises(ValueError, match="mismatch"):
        JPBarTransaction(db).persist_daily(replace(result, bars=(bad,)))
    assert db.query(JPBarEvidence).count() == db.query(RawFetchResult).count() == 0


def test_repository_fails_closed_for_tampered_receipt_and_bounds(db):
    JPBarTransaction(db).persist_daily(adapted())
    JPBarTransaction(db).persist_daily(adapted(close=106, fetched=FETCHED + timedelta(minutes=1)))
    with pytest.raises(CandidateReadLimitExceeded):
        JPDailyBarRepository(db).load_daily_bars(query(FETCHED + timedelta(hours=1)).model_copy(update={"max_rows": 1}))
    db.query(RawFetchResult).update({"content_hash": "f" * 64})
    db.commit()
    read = JPDailyBarRepository(db).load_daily_bars(query())
    assert not read.series and read.rejections[0].reason_code == "CANONICAL_STORAGE_IDENTITY_MISMATCH"


def test_repository_does_not_load_raw_payload_or_flush(db):
    JPBarTransaction(db).persist_daily(adapted())
    statements = []
    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", record)
    try:
        with patch.object(db, "flush", side_effect=AssertionError("read attempted flush")):
            JPDailyBarRepository(db).load_daily_bars(query())
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert statements and all("raw_text" not in sql for sql in statements)
    assert all(sql.lstrip().startswith("select") for sql in statements)


def test_adapter_rejects_identity_basis_and_incomplete_bar():
    wrong = payload()
    wrong["chart"]["result"][0]["meta"]["symbol"] = "9984.T"
    with pytest.raises(ValueError, match="symbol"):
        adapt_yahoo_daily(wrong, instrument=INSTRUMENT, fetched_at=FETCHED)
    missing = payload()
    missing["chart"]["result"][0]["indicators"]["quote"][0]["open"] = [None]
    result = adapt_yahoo_daily(missing, instrument=INSTRUMENT, fetched_at=FETCHED)
    assert not result.bars and result.rejections[0][1] == "INVALID_CANONICAL_BAR"
    provisional = adapted(fetched=FETCHED.replace(hour=14))
    assert not provisional.bars and provisional.rejections[0][1] == "SESSION_NOT_COMPLETED"


def test_historical_close_time_uses_effective_date():
    assert jp_daily_session_end(date(2024, 11, 1)).hour == 15
    assert jp_daily_session_end(date(2024, 11, 1)).minute == 0
    assert jp_daily_session_end(date(2024, 11, 5)).minute == 30


def test_get_cache_miss_never_acquires_and_get_flags_fail_closed(db):
    with patch("app.jp_market.service.fetch_yahoo_chart_payload", side_effect=AssertionError("GET acquired")), patch("app.jp_market.service._get_fresh_jp_intraday_cache", return_value=None):
        assert get_jp_intraday_trend(symbol="7203.T", db=db)["point_count"] == 0
        assert get_jp_intraday_trend_api(symbol="7203.T", db=db)["point_count"] == 0
        with pytest.raises(HTTPException) as exc:
            get_jp_intraday_trend_api(symbol="7203.T", refresh=True, db=db)
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException):
            get_jp_ohlc_chart_data(symbol="7203.T", ensure_history=True, db=db)
