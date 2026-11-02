"""Offline regression for the October 23 daily revisions and quote references."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import Base, RawFetchResult, USDailyPrice
from app.market_data.contracts import BarFinalization, MarketSession
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor, USProviderPayload
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import build_us_daily_acquisition_rollout_state
from app.us_market.market_data.descriptors import YAHOO_DAILY_DESCRIPTOR, YAHOO_DAILY_RESOURCE_ID
from app.us_market import market_truth, service
from app.us_market.trading_calendar import US_MARKET_TIMEZONE as ET
from app.us_market.valuation import read_us_valuation_price
from app.us_market.watchlist_metrics import _latest_distinct_us_daily_rows, _close_value
from test_us_sector_distribution import stock, profile, bar
from test_us_market_truth_snapshot import _fake_components

DAY = date(2026, 10, 23)
NOW = datetime(2026, 10, 26, 8, tzinfo=ET)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("external IO forbidden")))
    with Session(engine) as session:
        yield session
    engine.dispose()


def payload(symbol, *, close=418.51, volume=9478300, day=DAY, open_price=None):
    price = close if open_price is None else open_price
    return {"chart": {"result": [{"meta": {"symbol": symbol, "previousClose": 412.35},
        "timestamp": [int(datetime.combine(day, time(9, 30), ET).timestamp())],
        "indicators": {"quote": [{"open": [price], "high": [max(price, close) + 1],
            "low": [min(price, close) - 1], "close": [close], "volume": [volume]}]}}]}}


def platform(db, symbol, *, now=NOW, data=None, calls=None):
    def fetch(route, requirement):
        if calls is not None:
            calls.append(route.resource_id)
        return USProviderPayload(payload=data or payload(symbol), url="https://fixture.invalid/chart")
    return USDailyOhlcvPlatform(db, descriptors=(YAHOO_DAILY_DESCRIPTOR,),
        rollout_state=build_us_daily_acquisition_rollout_state(mode="on", symbols="", changed_at=now),
        acquisition=USDailyOhlcvAcquisitionExecutor(fetchers={YAHOO_DAILY_RESOURCE_ID: fetch}, clock=lambda: now))


@pytest.mark.parametrize("symbol,field,early_value,early_volume,corrected_value,corrected_volume", [
    ("TSM", "close_price", 418.19, 8327513, 418.51, 9478300),
    ("MU", "open_price", 862.185, 20462749, 862.29, 21166800),
])
def test_early_receipt_never_ages_into_final_and_later_acquisition_revises(
    db, symbol, field, early_value, early_volume, corrected_value, corrected_volume,
):
    stock(db, symbol, exchange="NYSE" if symbol == "TSM" else "NASDAQ")
    # MU's incident is an opening-price revision; its close here is synthetic.
    early_close = early_value if field == "close_price" else 860
    corrected_close = corrected_value if field == "close_price" else 860
    bar(db, symbol, close=early_close, open_price=early_value, high_price=max(early_value, early_close) + 1, volume=early_volume,
        received=datetime(2026, 10, 23, 16, 7, tzinfo=ET))
    db.commit()
    original_raw_id = db.query(USDailyPrice).one().raw_result_id
    calls = []
    reader = platform(db, symbol, data=payload(symbol, close=corrected_close, open_price=corrected_value, volume=corrected_volume), calls=calls)
    before = reader.read(symbol=symbol, bars=1, now=NOW)
    assert not before.temporal_postcondition_satisfied
    assert not before.projection["decision_usable"]
    assert "US_DAILY_VENDOR_REVISION_UNVERIFIED" in before.projection["limitations"]
    from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
    coverage = US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(db, expected_trade_date=DAY)
    assert symbol in coverage.partial_symbols and symbol not in coverage.current_symbols
    assert calls == []
    after = reader.refresh(symbol=symbol, bars=1, now=NOW, max_provider_calls=1)
    assert after.temporal_postcondition_satisfied
    assert calls == [YAHOO_DAILY_RESOURCE_ID]
    selected = after.result.resolved.bars[-1]
    assert selected.close_price == Decimal(str(corrected_close))
    assert getattr(selected, field) == Decimal(str(corrected_value))
    assert selected.volume.value == Decimal(corrected_volume)
    assert selected.finalization is BarFinalization.CORRECTED
    assert selected.lineage.authority.value == "vendor"
    assert db.get(RawFetchResult, original_raw_id) is not None
    assert db.query(RawFetchResult).count() == 2
    assert "VENDOR_DAILY_NOT_OFFICIAL_CLOSE_PROOF" in after.projection["limitations"]


def test_next_session_revalidation_is_bounded_and_preserves_equal_payload_receipts(db):
    stock(db, "TSM", exchange="NYSE")
    db.commit()
    saturday = datetime(2026, 10, 24, 8, tzinfo=ET)
    first = platform(db, "TSM", now=saturday).refresh(symbol="TSM", bars=1, now=saturday, max_provider_calls=1)
    assert first.temporal_postcondition_satisfied
    calls = []
    reader = platform(db, "TSM", calls=calls)
    assert reader.read(symbol="TSM", bars=1, now=saturday + timedelta(days=1)).temporal_postcondition_satisfied
    due = reader.read(symbol="TSM", bars=1, now=NOW)
    assert due.projection["refresh_recommended"] and not due.projection["decision_usable"]
    assert due.projection["freshness_status"] == "stale"
    reader.refresh(symbol="TSM", bars=1, now=NOW, max_provider_calls=1)
    reader.refresh(symbol="TSM", bars=1, now=NOW + timedelta(seconds=1), max_provider_calls=1)
    assert calls == [YAHOO_DAILY_RESOURCE_ID]
    assert db.query(RawFetchResult).count() == 2
    assert len({raw.content_hash for raw in db.query(RawFetchResult)}) == 1


@pytest.mark.parametrize("day,hour", [(DAY, 16), (date(2026, 11, 27), 13)])
def test_yahoo_regular_and_early_close_do_not_imply_final(day, hour):
    from app.us_market.providers.canonical import canonical_yahoo_chart_payload
    from test_us_market_truth_snapshot import AAPL
    early = datetime.combine(day, time(hour, 7), ET)
    converted = canonical_yahoo_chart_payload(instrument=AAPL, payload=payload("AAPL", day=day),
        fetched_at=early, interval="1d")
    assert converted.bars[0].finalization is BarFinalization.PROVISIONAL
    assert converted.bars[0].end_at.hour == hour
    historical = canonical_yahoo_chart_payload(instrument=AAPL, payload=payload("AAPL", day=day),
        fetched_at=early + timedelta(days=1), interval="1d")
    assert historical.bars[0].finalization is BarFinalization.FINAL


def test_watchlist_portfolio_volume_use_one_raw_canonical_series(db):
    stock(db, "TSM", exchange="NYSE")
    for day in (date(2026, 10, 22), DAY):
        bar(db, "TSM", day, close=418.51, volume=9478300, provider="alpaca", adjusted_close=12)
        bar(db, "TSM", day, close=900, volume=99999999,
            received=datetime.combine(day, time(16, 7), ET))
    db.commit()
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, sql, *args: statements.append(sql))
    valuation = read_us_valuation_price(db, symbol="TSM", requested_at=NOW)
    rows = _latest_distinct_us_daily_rows(db, symbol="TSM", limit=2, now=NOW)
    volumes = service._us_daily_volume_totals(db, symbol="TSM", now=NOW)
    assert valuation.price == Decimal("418.51") and valuation.provider == "alpaca"
    assert valuation.currency == "USD"
    assert rows[0].instrument.venue == "NYSE"
    assert _close_value(rows[0]) == 418.51
    assert {item.lineage.provider for item in rows} == {"alpaca"}
    assert volumes[DAY] == 9478300
    assert "CORPORATE_ACTION_POSITION_ALIGNMENT_UNVERIFIED" in valuation.limitations
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)


def bundle_for(db, monkeypatch, *, symbol, now):
    daily = USDailyOhlcvPlatform(db).read(symbol=symbol, bars=3, now=now)
    quote, intraday, _ = _fake_components(intraday_available=False)
    identity = daily.identity
    observed = quote.quote.model_copy(update={"instrument": identity.instrument,
        "trade_date": now.date(), "previous_close": Decimal("412.35"),
        "lineage": quote.quote.lineage.model_copy(update={"event_at": now - timedelta(seconds=30), "fetched_at": now})})
    quote = quote.model_copy(update={"quote": observed,
        "health": quote.health.model_copy(update={"selected_event_at": observed.lineage.event_at,
            "selected_session": MarketSession.PRE_OPEN if now.hour < 9 else MarketSession.CONTINUOUS if now.hour < 16 else MarketSession.POST_CLOSE})})
    components = market_truth._USMarketTruthComponents(
        quote_read=SimpleNamespace(identity=identity, result=SimpleNamespace(resolved=quote, limitations=())),
        bars_read=SimpleNamespace(identity=identity, result=SimpleNamespace(resolved=intraday, limitations=())),
        daily_read=daily)
    monkeypatch.setattr(market_truth, "_read_components", lambda *args, **kwargs: components)
    return market_truth.read_us_market_truth_bundle(db, symbol=symbol, evaluated_at=now, requested_scope="all")


@pytest.mark.parametrize("symbol", ["AAPL", "AMD", "NVDA", "MSFT", "TSM", "MU"])
@pytest.mark.parametrize("hour,expected_date,expected_close", [(8, DAY, 418.51), (10, DAY, 418.51), (17, date(2026, 10, 26), 420)])
def test_six_symbols_quote_truth_api_and_ai_reference_parity(db, monkeypatch, symbol, hour, expected_date, expected_close):
    from app.routers.us_market import get_us_quote_snapshot_api
    from app.us_market.schemas import USResolvedQuoteSnapshotRead
    from app.ai.market_context.us_context import _us_resolved_quote
    from app.market.calendar_status import build_us_calendar_status
    stock(db, symbol, exchange="NYSE" if symbol == "TSM" else "NASDAQ")
    bar(db, symbol, date(2026, 10, 22), close=412.35, provider="alpaca")
    bar(db, symbol, DAY, close=418.51, provider="alpaca")
    now = NOW.replace(hour=hour)
    if hour == 17:
        bar(db, symbol, now.date(), close=420, provider="alpaca", received=now - timedelta(minutes=30))
    db.commit()
    bundle = bundle_for(db, monkeypatch, symbol=symbol, now=now)
    monkeypatch.setattr(service, "read_us_market_truth_bundle", lambda *args, **kwargs: bundle)
    result = USResolvedQuoteSnapshotRead.model_validate(get_us_quote_snapshot_api(symbol=symbol, db=db)).model_dump()
    reference = next(ref for ref in bundle.snapshot.comparison_references if ref.purpose.value == "headline_change")
    assert Decimal(str(result["quote"]["previous_close"])) == reference.price == Decimal(str(expected_close))
    assert result["quote"]["previous_close_trade_date"] == expected_date.isoformat()
    assert result["quote"]["provider_previous_close_hint"] == "412.35"
    assert result["quote"]["provider_previous_close_hint_trade_date"] is None
    assert result["quote"]["provider_previous_close_hint_price_basis"] == "provider_default"
    compat = service._market_truth_compat_intraday_payload(bundle=bundle, session_scope="all", interval="1m")
    ai = _us_resolved_quote(result, previous_close_reference=compat, calendar_status=build_us_calendar_status(now))
    assert ai["previous_close"] == expected_close
    assert ai["previous_close_trade_date"] == expected_date.isoformat()
    # Exercise the real v4 context/selection pipeline through the MCP adapter;
    # only its HTTP transport and clock are fixture ports.
    from app.ai import ask as ai_ask, agentic_tools
    from app.ai.schemas import AiAskRequest
    from test_omi_mcp_server import load_server_module
    monkeypatch.setattr(agentic_tools, "_now", lambda: now)
    monkeypatch.setattr(agentic_tools, "scan_us_stock_gaps", lambda *args, **kwargs: {})
    server = load_server_module()
    monkeypatch.setattr(server, "_api_post", lambda path, payload: ai_ask.ask(
        db=db, payload=AiAskRequest.model_validate(payload)))
    mcp = server._call_tool("omi.ask", {"question": "US quote fixture", "target": {
        "type": "us_stock", "id": symbol, "market": "US"}, "mode": "data_only", "output": "evidence_only",
        "realtime_policy": "cache_only", "allow_external_fetch": False, "allow_llm": False,
        "refresh_policy": {"mode": "off"}, "selection": {"include": ["quote.snapshot"]}})
    mcp_quote = mcp["evidence"]["data"]["quote.snapshot"]["quote"]
    assert Decimal(mcp_quote["previous_close"]) == Decimal(str(expected_close))
    assert mcp_quote["previous_close_trade_date"] == expected_date.isoformat()
    assert mcp_quote["provider_previous_close_hint_trade_date"] is None


@pytest.mark.parametrize("hour", [8, 10, 17])
def test_missing_exact_daily_is_null_instead_of_metadata(db, monkeypatch, hour):
    now = NOW.replace(hour=hour)
    stock(db, "TSM", exchange="NYSE")
    bar(db, "TSM", date(2026, 10, 22), close=412.35, provider="alpaca")
    if hour == 17:
        bar(db, "TSM", DAY, close=418.51, provider="alpaca")
    db.commit()
    bundle = bundle_for(db, monkeypatch, symbol="TSM", now=now)
    result = service._market_truth_compat_intraday_payload(bundle=bundle, session_scope="all", interval="1m")
    assert result["quote_snapshot"]["quote"]["previous_close"] is None
    assert result["quote_snapshot"]["quote"]["previous_close_reason_code"] == "COMPARISON_REFERENCE_UNAVAILABLE"
    from app.ai.market_context.us_context import _us_resolved_quote
    from app.market.calendar_status import build_us_calendar_status
    ai = _us_resolved_quote(result["quote_snapshot"], calendar_status=build_us_calendar_status(now),
        previous_close_reference={"previous_close": 412.35, "change_reference_price": 412.35})
    assert ai["previous_close"] is None and ai["change"] is None


def test_revision_invalidates_distribution_and_recomputes_chart_technical_truth(db, monkeypatch):
    from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
    from app.us_market.sector_distribution import read_us_sector_distribution
    from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
    from app.us_market.research_service import build_us_market_research
    from app.market_data.eod_coverage import persist_eod_coverage
    from app.us_market.intraday_read_model_cache import (
        us_intraday_cache_generation, get_us_intraday_read_cache, set_us_intraday_read_cache,
    )
    saturday = datetime(2026, 10, 24, 8, tzinfo=ET)
    stock(db, "TSM", exchange="NYSE")
    profile(db, "TSM")
    db.commit()
    initial = payload("TSM", close=418.19, volume=8327513)
    result = initial["chart"]["result"][0]
    result["timestamp"].insert(0, int(datetime(2026, 10, 22, 9, 30, tzinfo=ET).timestamp()))
    for key, value in {"open": 412.35, "high": 413, "low": 412, "close": 412.35, "volume": 1000}.items():
        result["indicators"]["quote"][0][key].insert(0, value)
    platform(db, "TSM", now=saturday, data=initial).refresh(
        symbol="TSM", bars=2, now=saturday, max_provider_calls=1)
    US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(db, now=saturday)
    before_snapshot = read_us_sector_distribution(db, now=saturday)
    assert before_snapshot.freshness_status == "current"
    assert read_us_sector_distribution(db, now=saturday + timedelta(days=1)).freshness_status == "current"
    due_snapshot = read_us_sector_distribution(db, now=NOW)
    assert due_snapshot.freshness_status == "stale"
    assert "US_DAILY_REVISION_CHECK_DUE" in due_snapshot.limitations
    before_chart = read_us_daily_ohlcv_chart(db, symbol="TSM", bars=2, now=saturday)
    before_research = build_us_market_research(db, symbol="TSM", bars=2, now=saturday, include_market_coverage=False)
    before_truth = bundle_for(db, monkeypatch, symbol="TSM", now=saturday).snapshot
    key = (id(db.get_bind()), "TSM", "all", "1m", "pre_market")
    generation = us_intraday_cache_generation("TSM")
    set_us_intraday_read_cache(key, {"previous_close": 418.19}, expected_generation=generation)
    assert get_us_intraday_read_cache(key) is not None
    platform(db, "TSM").refresh(symbol="TSM", bars=2, now=NOW, max_provider_calls=1)
    assert get_us_intraday_read_cache(key) is None
    set_us_intraday_read_cache(key, {"previous_close": 418.19}, expected_generation=generation)
    assert get_us_intraday_read_cache(key) is None  # stale concurrent publisher is fenced
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, sql, *args: statements.append(sql))
    invalidated = read_us_sector_distribution(db, now=NOW)
    assert invalidated.freshness_status == "stale"
    assert invalidated.provenance["daily_revision_invalidation"]["raw_result_ids"]
    assert "US_DAILY_EVIDENCE_REVISED_REBUILD_REQUIRED" in invalidated.limitations
    assert len(statements) == 1
    assert "us_daily_price" not in statements[0].lower()
    # Coverage-only reconciliation cannot erase the invalidation marker.
    persist_eod_coverage(db, US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(db, expected_trade_date=DAY))
    assert read_us_sector_distribution(db, now=NOW).freshness_status == "stale"
    after_chart = read_us_daily_ohlcv_chart(db, symbol="TSM", bars=2, now=NOW)
    after_research = build_us_market_research(db, symbol="TSM", bars=2, now=NOW, include_market_coverage=False)
    after_truth = bundle_for(db, monkeypatch, symbol="TSM", now=NOW).snapshot
    assert before_chart["points"][-1]["close"] == 418.19
    assert after_chart["points"][-1]["close"] == 418.51
    assert before_research["technical_indicators"] != after_research["technical_indicators"]
    assert before_truth.component_revisions.daily_revision != after_truth.component_revisions.daily_revision
    assert before_truth.evidence_revision != after_truth.evidence_revision
    US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(db, now=NOW)
    rebuilt = read_us_sector_distribution(db, now=NOW)
    assert rebuilt.freshness_status == "current"
    assert rebuilt.avg_return_pct != before_snapshot.avg_return_pct
    assert "daily_revision_invalidation" not in rebuilt.provenance


def test_older_acquisition_cannot_replace_newer_correction(db):
    from app.market_data.provider_catalog import plan_data_acquisition_v2
    from app.us_market.daily_price_transaction import USDailyPriceTransaction
    stock(db, "TSM", exchange="NYSE")
    db.commit()
    reader = platform(db, "TSM")
    reader.refresh(symbol="TSM", bars=1, now=NOW, max_provider_calls=1)
    requirement = reader._requirement(identity=reader.read(symbol="TSM", now=NOW).identity,
        expected_date=DAY, bars=1, requested_at=NOW, allow_acquisition=True,
        max_provider_calls=1, require_history_coverage=False)
    older = platform(db, "TSM", now=NOW - timedelta(days=1), data=payload("TSM", close=418.19))
    acquired = older._acquisition.acquire_bar_observations(requirement,
        plan_data_acquisition_v2(requirement, (YAHOO_DAILY_DESCRIPTOR,)))
    result = USDailyPriceTransaction(db).persist_bar_acquisition(requirement, acquired)
    assert result.observations_unchanged == 1 and result.observations_updated == 0
    assert db.query(USDailyPrice).one().close_price == 418.51


def test_same_day_yahoo_partial_falls_back_with_two_call_budget(db):
    from app.us_market.market_data.descriptors import ALPACA_SIP_DAILY_RESOURCE_ID
    stock(db, "TSM", exchange="NYSE")
    db.commit()
    now = datetime(2026, 10, 23, 16, 7, tzinfo=ET)
    calls = []
    def fetch(route, requirement):
        calls.append(route.resource_id)
        data = payload("TSM", close=418.19, volume=8327513) if route.resource_id == YAHOO_DAILY_RESOURCE_ID else {
            "symbol": "TSM", "bars": [{"t": "2026-10-23T04:00:00Z", "o": 418.51,
                "h": 420, "l": 417, "c": 418.51, "v": 9478300}], "next_page_token": None}
        return USProviderPayload(payload=data, url="https://fixture.invalid/bars")
    reader = USDailyOhlcvPlatform(db,
        rollout_state=build_us_daily_acquisition_rollout_state(mode="on", symbols="", changed_at=now),
        acquisition=USDailyOhlcvAcquisitionExecutor(clock=lambda: now,
            fetchers={YAHOO_DAILY_RESOURCE_ID: fetch, ALPACA_SIP_DAILY_RESOURCE_ID: fetch}))
    result = reader.refresh(symbol="TSM", bars=1, now=now, max_provider_calls=2)
    assert result.temporal_postcondition_satisfied
    assert result.projection["selected_provider"] == "alpaca"
    assert calls == [YAHOO_DAILY_RESOURCE_ID, ALPACA_SIP_DAILY_RESOURCE_ID]
    assert db.query(RawFetchResult).count() == 2
    assert db.query(USDailyPrice).one().provider == "alpaca"


@pytest.mark.parametrize("finalization", [BarFinalization.UNKNOWN, BarFinalization.PROVISIONAL])
def test_close_policy_rejects_nonfinal_daily(finalization):
    from app.us_market.close_resolution_policy import USCloseResolutionPolicy
    from test_us_market_truth_contracts import _close
    assert USCloseResolutionPolicy().evaluate(_close(finalization=finalization)).decision.value == "ineligible"


def test_unknown_identity_and_non_usd_do_not_produce_valuation(db):
    unknown = read_us_valuation_price(db, symbol="UNKNOWN", requested_at=NOW)
    assert unknown.price is None and not unknown.research_usable
    stock(db, "TSM", exchange="NYSE")
    bar(db, "TSM", close=418.51, provider="alpaca", currency="TWD")
    db.commit()
    denied = read_us_valuation_price(db, symbol="TSM", requested_at=NOW)
    assert denied.price is None
    assert "US_DAILY_CURRENCY_MISMATCH" in denied.limitations


def test_holiday_does_not_expire_completed_daily_and_historical_target_is_stable(db):
    from app.us_market.trading_calendar import us_daily_revision_check_due
    friday = datetime(2026, 9, 4, 23, tzinfo=ET)
    assert not us_daily_revision_check_due(fetched_at=friday, now=datetime(2026, 9, 7, 8, tzinfo=ET))
    stock(db, "TSM", exchange="NYSE")
    bar(db, "TSM", date(2026, 10, 22), close=412.35)
    db.commit()
    read = USDailyOhlcvPlatform(db).read(symbol="TSM", to_date=date(2026, 10, 22), bars=1, now=NOW)
    assert read.temporal_postcondition_satisfied


def test_concurrent_snapshot_publication_cannot_overwrite_correction(tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.us_market import sector_distribution
    from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
    engine = create_engine(f"sqlite:///{(tmp_path / 'snapshot-race.db').as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    saturday = datetime(2026, 10, 24, 8, tzinfo=ET)
    with Session(engine) as publisher, Session(engine) as writer:
        stock(publisher, "TSM", exchange="NYSE")
        profile(publisher, "TSM")
        publisher.commit()
        platform(publisher, "TSM", now=saturday, data=payload("TSM", close=418.19)).refresh(
            symbol="TSM", bars=1, now=saturday, max_provider_calls=1)
        US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(publisher, now=saturday)
        build = sector_distribution.build_us_sector_distribution
        def revise_after_build(*args, **kwargs):
            snapshot = build(*args, **kwargs)
            platform(writer, "TSM").refresh(symbol="TSM", bars=1, now=NOW, max_provider_calls=1)
            return snapshot
        monkeypatch.setattr(sector_distribution, "build_us_sector_distribution", revise_after_build)
        with pytest.raises(OperationalError, match="locked"):
            US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(publisher, now=saturday)
        publisher.rollback()
        latest = sector_distribution.read_us_sector_distribution(publisher, now=NOW)
        assert latest.freshness_status == "stale"
        assert "US_DAILY_EVIDENCE_REVISED_REBUILD_REQUIRED" in latest.limitations
    engine.dispose()
