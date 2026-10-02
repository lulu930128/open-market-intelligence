"""US Round 1: real canonical persistence/resolution, isolated provider fixture."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import agentic_execution, agentic_planning, agentic_tools, capability_contract, data_quality_contract
from app.ai import ask as ai_ask
from app.ai.ask_policy import AiAskServerPolicy
from app.ai.schemas import AiAskV4Request
from app.ai.capability_resolution_registry import capability_dependency_closure
from app.ai.market_context.us_context import USContextDependencies, read_us_stock_context
from app.config import settings
from app.db.models import Base, RawFetchResult, SourceRegistry, USDailyPrice, USStockMaster
from app.us_market import daily_ohlcv_acquisition, daily_ohlcv_platform, service
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor, USProviderPayload
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_rollout import build_us_daily_operation_rollout_state, us_daily_full_market_acquisition_enabled
from app.us_market.errors import USMarketConfigurationError
from app.us_market.market_data.descriptors import YAHOO_DAILY_RESOURCE_ID
from app.us_market.research_service import build_us_market_research
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, is_us_trading_day, us_session_close_time


NOW = datetime(2026, 9, 30, 4, tzinfo=timezone.utc)
EXPECTED = date(2026, 9, 29)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "us_canonical_market_data_mode", "canary")
    monkeypatch.setattr(settings, "us_canonical_shadow_symbols", "AAPL")
    monkeypatch.setattr(settings, "us_canonical_canary_max_symbols", 1)
    monkeypatch.setattr(settings, "enable_market_refresh_priority", False)
    monkeypatch.setattr(agentic_tools, "_now", lambda: NOW)
    # Fix only the platform's clock; no resolver/gateway/transaction mocks.
    monkeypatch.setattr(daily_ohlcv_platform, "datetime", type("Clock", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}))
    monkeypatch.setattr(daily_ohlcv_acquisition, "datetime", daily_ohlcv_platform.datetime)
    with Session(engine) as session:
        session.add_all([USStockMaster(symbol=s, exchange="NASDAQ", is_etf=False, is_active=True) for s in ("AMD", "AAPL")])
        session.commit()
        yield session
    engine.dispose()


def seed(db, *, symbol="AMD", latest=EXPECTED, count=220):
    dates = []
    cursor = latest
    while len(dates) < count:
        if is_us_trading_day(cursor):
            dates.append(cursor)
        cursor -= timedelta(days=1)
    source = SourceRegistry(source_name=f"fixture.{symbol}", source_type="fixture", category="market_data", enabled=True)
    db.add(source)
    db.flush()
    raw = RawFetchResult(source_id=source.id, fetched_at=NOW - timedelta(minutes=1), content_hash="a" * 64, raw_text="fixture", parser_version="yahoo.chart.v8")
    db.add(raw)
    db.flush()
    for i, day in enumerate(reversed(dates)):
        close = 100 + i * 0.25
        db.add(USDailyPrice(
            provider="yahoo_chart", symbol=symbol, trade_date=day, open_price=close - .5,
            high_price=close + 1, low_price=close - 1, close_price=close, trade_volume=1_000_000 + i,
            fetched_at=NOW - timedelta(minutes=1), source_id=source.id, raw_result_id=raw.id,
            authority="vendor", raw_contract_version="yahoo.chart.v8",
            event_at=datetime.combine(day, us_session_close_time(day), tzinfo=US_MARKET_TIMEZONE),
            finalization="final", price_basis="raw", volume_unit="shares", volume_status="observed", raw_payload_hash=raw.content_hash,
        ))
    db.commit()


def session(db, capability, *, allow=True, trade_date=None):
    return agentic_tools.run_us_stock_tool_session(
        db=db, question="technical research", symbol="AMD", target={"type": "us_stock", "id": "AMD"},
        policy={"can_external_fetch": allow, "can_plan_tools": False},
        raw_budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 10},
        requested_capabilities=(capability,), requested_trade_date=trade_date,
    )


def forbid(*args, **kwargs):
    raise AssertionError("unexpected external IO or write")


def quality(payload, capability):
    canonical = {"target": {"type": "us_stock", "id": "AMD", "market": "US"}, "evidence": {}}
    selection = {"required": [capability], "optional": []}
    projected = {capability: payload}
    manifest = capability_contract.build_manifest(canonical=canonical, selection=selection, projected_data=projected)
    return data_quality_contract.build_quality_contract(
        canonical=canonical, selection=selection, manifest=manifest, projected_data=projected,
        realtime_assessments={}, scope_type="us_stock",
    )["capabilities"][capability]


@pytest.mark.parametrize("capability", ["technical.indicators", "technical.structure"])
def test_dependency_and_healthy_no_refresh(db, monkeypatch, capability):
    seed(db)
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    monkeypatch.setattr(agentic_execution, "refresh_us_daily_ohlcv", forbid)
    result = session(db, capability)
    assert result["tool_plan"]["tool_plan"] == []
    assert result["tool_runs"] == []
    assert result["freshness"]["missing"] == []
    assert agentic_planning.us_capability_requirements(capability) == ("us_daily_price",)
    assert "technical.structure" not in agentic_planning.US_CAPABILITY_REQUIREMENTS
    closure = capability_dependency_closure((capability,), scope_type="us_stock")
    assert "daily.ohlcv" in closure
    assert not {"quote.snapshot", "intraday.bars"} & closure
    assert {"quote.snapshot", "intraday.bars"} <= capability_dependency_closure(("technical.structure",), scope_type="stock")


@pytest.mark.parametrize("capability,requested", [
    ("daily.ohlcv", None), ("technical.indicators", None),
    ("technical.structure", None), ("technical.indicators", date(2026, 9, 24)),
])
def test_stale_bounded_fill_persists_and_rereads(db, monkeypatch, capability, requested):
    expected = requested or EXPECTED
    seed(db, latest=date(2026, 9, 23) if requested else date(2026, 9, 25))
    calls = []

    def fetch(self, route, requirement):
        calls.append((route, requirement))
        assert route.resource_id == YAHOO_DAILY_RESOURCE_ID
        assert requirement.target.instrument.symbol == "AMD"
        assert requirement.request.end_at.astimezone(US_MARKET_TIMEZONE).date() == expected
        assert requirement.bounds.max_external_calls <= 2
        assert route.timeout_seconds <= 30
        timestamp = int(datetime.combine(expected, time(9, 30), tzinfo=US_MARKET_TIMEZONE).timestamp())
        return USProviderPayload(payload={"chart": {"result": [{"meta": {"symbol": "AMD", "currency": "USD"},
            "timestamp": [timestamp], "indicators": {"quote": [{"open": [155.], "high": [157.], "low": [154.], "close": [156.], "volume": [1200000]}]}}], "error": None}}, url="https://example.invalid/AMD")

    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "_fetch", fetch)
    before = build_us_market_research(db, symbol="AMD", now=NOW, include_market_coverage=False)
    assert "DAILY_BARS_NOT_CURRENT" in before["technical_indicators"]["quality"]["reason_codes"]
    if capability == "technical.structure":
        monkeypatch.setattr(service, "build_us_source_health", lambda **kwargs: {"entries": []})
        monkeypatch.setattr(service, "get_us_quote_snapshot", forbid)
        monkeypatch.setattr(service, "get_us_intraday_trend", forbid)
        response = ai_ask.ask(db=db, payload=AiAskV4Request(
            question="AMD technical structure", target={"type": "us_stock", "id": "AMD"},
            output="evidence_only", mode="data_only", realtime_policy="prefer_live",
            selection={"required": [capability]}, allow_external_fetch=True,
            payload_level="full", diagnostics_level="debug",
        ), server_policy=AiAskServerPolicy(can_external_fetch=True, trust_source="test"))
        result = {
            **response["execution"],
            "freshness": agentic_tools.scan_us_stock_gaps(db, "AMD", requested_capabilities=(capability,)),
        }
        assert response["evidence"]["data"][capability]["quality"]["decision_usable"] is False
    else:
        result = session(db, capability, trade_date=requested.isoformat() if requested else None)
    assert [s["tool"] for s in result["tool_plan"]["tool_plan"]] == ["us.refresh_daily_price"]
    assert result["tool_runs"][0]["status"] == "success", result
    assert len(calls) == 1
    assert result["freshness"]["missing"] == []
    reread = USDailyOhlcvPlatform(db).read(symbol="AMD", now=NOW, bars=260, to_date=requested)
    assert reread.postcondition_satisfied
    assert reread.projection["latest_trade_date"] == expected.isoformat()
    assert db.query(USDailyPrice).filter_by(symbol="AMD", trade_date=expected).count() == 1
    research = build_us_market_research(db, symbol="AMD", now=NOW, to_date=requested, include_market_coverage=False)
    reasons = research["technical_indicators"]["quality"]["reason_codes"]
    assert "DAILY_BARS_NOT_CURRENT" not in reasons
    assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" in reasons
    assert research["technical_indicators"]["quality"]["decision_usable"] is False
    assert "RELATIVE_STRENGTH_BENCHMARK_NOT_CONFIGURED" in research["technical_structure"]["limitations"]
    assert settings.us_canonical_shadow_symbols == "AAPL"
    assert not us_daily_full_market_acquisition_enabled()
    with pytest.raises(USMarketConfigurationError, match="ROLLOUT_DISABLED"):
        USDailyOhlcvPlatform(db).refresh(symbol="AMD", now=NOW)
    assert len(calls) == 1


def test_cache_only_session_does_not_write_or_acquire(db, monkeypatch):
    seed(db, latest=date(2026, 9, 25))
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda conn, cursor, statement, *rest: statements.append(statement))
    result = session(db, "technical.indicators", allow=False)
    assert result["tool_runs"][0]["status"] == "blocked"
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)


@pytest.mark.parametrize("realtime,trusted", [("cache_only", True), ("prefer_live", False)])
def test_public_ask_read_only_purity_even_when_caller_requests_fetch(db, monkeypatch, realtime, trusted):
    seed(db, latest=date(2026, 9, 25))
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    monkeypatch.setattr(service, "get_us_quote_snapshot", forbid)
    monkeypatch.setattr(service, "get_us_intraday_trend", forbid)
    monkeypatch.setattr(service, "build_us_source_health", lambda **kwargs: {"entries": []})
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda conn, cursor, statement, *rest: statements.append(statement))
    response = ai_ask.ask(db=db, payload=AiAskV4Request(
        question="AMD technical indicators", target={"type": "us_stock", "id": "AMD"},
        output="evidence_only", mode="data_only", realtime_policy=realtime,
        selection={"required": ["technical.indicators"]}, allow_external_fetch=True,
        diagnostics_level="debug",
    ), server_policy=AiAskServerPolicy(can_external_fetch=trusted, trust_source="test"))
    assert response["contract_version"] == "omi.decision.v4"
    assert response["evidence"]["data"]["technical.indicators"]["quality"]["decision_usable"] is False
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)


@pytest.mark.parametrize("symbols,limit", [([], 1), (["AMD", "AAPL"], 1), (["AMD,AAPL"], 1), (["AMD*"], 1)])
def test_operation_scope_rejects_unbounded_targets(symbols, limit):
    with pytest.raises(USMarketConfigurationError):
        build_us_daily_operation_rollout_state(symbols=symbols, max_symbols=limit)


def test_operation_scope_cannot_authorize_another_symbol_or_be_forged_in_args(db):
    scope = build_us_daily_operation_rollout_state(symbols=("AMD",), max_symbols=1)
    with pytest.raises(USMarketConfigurationError, match="target=US:AAPL"):
        USDailyOhlcvPlatform(db, rollout_state=scope).refresh(symbol="AAPL", now=NOW)
    with pytest.raises(USMarketConfigurationError, match="target=US:AMD"):
        agentic_execution._execute_tool(db, "us.refresh_daily_price", {"symbol": "AMD", "us_daily_rollout": scope, "allow_external_fetch": True})


@pytest.mark.parametrize("timeframe", ["weekly", "monthly"])
def test_historical_aggregate_timeframe_is_explicitly_unsupported(db, timeframe):
    seed(db)
    result = build_us_market_research(
        db, symbol="AMD", now=NOW, to_date=date(2026, 9, 1), timeframe=timeframe,
        include_market_coverage=False,
    )
    indicators = result["technical_indicators"]
    assert indicators["request_status"] == "unsupported"
    assert indicators["as_of"] is None
    assert indicators["current"] == {}
    assert "US_HISTORICAL_TECHNICAL_TIMEFRAME_UNSUPPORTED" in indicators["quality"]["reason_codes"]


@pytest.mark.parametrize("requested,reason", [
    (date(2026, 9, 26), "US_DAILY_REQUESTED_DATE_NOT_TRADING_SESSION"),
    (date(2026, 9, 30), "US_DAILY_REQUESTED_SESSION_NOT_RELEASED"),
    (date(2026, 9, 29), "US_DAILY_REQUESTED_SESSION_EVIDENCE_MISSING"),
])
def test_historical_missing_pending_has_typed_reason_and_no_fallback(db, requested, reason):
    seed(db, latest=date(2026, 9, 25))
    result = build_us_market_research(db, symbol="AMD", now=NOW, to_date=requested, include_market_coverage=False)
    for key, capability in (("technical_indicators", "technical.indicators"), ("technical_structure", "technical.structure")):
        payload = result[key]
        assert payload["as_of"] is None
        assert payload["status"] == "missing"
        assert reason in payload["quality"]["reason_codes"]
        outward = quality(payload, capability)
        assert "semantic_payload_empty" not in outward["issues"]
        assert reason in outward["reason_codes"]
    if reason != "US_DAILY_REQUESTED_SESSION_EVIDENCE_MISSING":
        assert session(db, "technical.indicators", trade_date=requested.isoformat())["tool_plan"]["tool_plan"] == []


def test_historical_context_uses_same_engine_pinned_to_requested_completed_session(db, monkeypatch):
    seed(db)
    requested = date(2026, 9, 1)
    monkeypatch.setattr(service, "build_us_source_health", lambda **kwargs: {"entries": []})
    monkeypatch.setattr(service, "get_us_quote_snapshot", forbid)
    monkeypatch.setattr(service, "get_us_intraday_trend", forbid)
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    deps = USContextDependencies(us_market_service=service, latest_profile=forbid, scan_us_stock_gaps=agentic_tools.scan_us_stock_gaps, now=lambda: NOW)
    context = read_us_stock_context(db=db, symbol="AMD", dependencies=deps, market_data_params={"requested_capabilities": ["technical.indicators", "technical.structure"], "trade_date": requested.isoformat()})
    research = context["data"]["resolved_research"]
    expected = build_us_market_research(db, symbol="AMD", now=NOW, to_date=requested, include_market_coverage=False)
    for key in ("technical_indicators", "technical_structure"):
        assert research[key] == expected[key]
        assert research[key]["as_of"] == requested.isoformat()
        assert research[key]["requested_trade_date"] == requested.isoformat()
    indicators = research["technical_indicators"]
    assert all(str(p["time"])[:10] <= requested.isoformat() for p in indicators["series"])
    assert indicators["current"]["moving_averages"]["ma20"] is not None
    assert indicators["current"]["rsi"] is not None
    assert indicators["current"]["macd"] is not None
    assert indicators["current"]["atr"] is not None
    assert session(db, "technical.indicators", trade_date=requested.isoformat())["tool_plan"]["tool_plan"] == []


@pytest.mark.parametrize("requested,status,reason", [
    ("2026-09-01", "available", None),
    ("2026-09-26", "unsupported", "US_DAILY_REQUESTED_DATE_NOT_TRADING_SESSION"),
    ("2026-09-30", "pending", "US_DAILY_REQUESTED_SESSION_NOT_RELEASED"),
])
def test_public_ask_preserves_historical_technical_semantics(db, monkeypatch, requested, status, reason):
    seed(db)
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    monkeypatch.setattr(service, "build_us_source_health", lambda **kwargs: {"entries": []})
    response = ai_ask.ask(db=db, payload=AiAskV4Request(
        question="AMD technical indicators", target={"type": "us_stock", "id": "AMD"},
        output="evidence_only", mode="data_only", realtime_policy="cache_only",
        selection={"required": ["technical.indicators", "technical.structure"]},
        market_data_params={"trade_date": requested},
    ), server_policy=AiAskServerPolicy())
    for capability in ("technical.indicators", "technical.structure"):
        payload = response["evidence"]["data"][capability]
        assert payload.get("request_status") == status, payload
        assert payload["requested_trade_date"] == requested
        assert payload["as_of"] == (requested if reason is None else None)
        if reason:
            assert reason in payload["quality"]["reason_codes"]
