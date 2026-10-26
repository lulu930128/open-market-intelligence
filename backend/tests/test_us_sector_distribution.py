"""G3 offline contracts: bounded canonical reads, never the production database."""

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import Base, RawFetchResult, SourceRegistry, USDailyPrice, USStockMaster, USCompanyProfile
from app.us_market.classification import read_us_classification, _classification_label, _aware_utc
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from app.us_market.research_service import _coverage_gate
from app.us_market.sector_distribution import build_us_sector_distribution as read_us_sector_distribution

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
DAY = date(2026, 10, 23)
PREVIOUS = date(2026, 10, 22)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def stock(db, symbol, **kwargs):
    values = dict(symbol=symbol, exchange="NASDAQ", asset_type="stock", is_active=True,
                  is_etf=False, is_test_issue=False)
    values.update(kwargs)
    db.add(USStockMaster(**values))


def profile(db, symbol, provider="alphavantage", sector="TECHNOLOGY", industry="SEMICONDUCTORS", fetched=None):
    db.add(USCompanyProfile(symbol=symbol, provider=provider, sector=sector, industry=industry,
                            fetched_at=fetched or datetime(2026, 8, 1, tzinfo=timezone.utc)))


def bar(db, symbol, day=DAY, close=100, volume=100, provider="yahoo_chart", finalization="final", received=None, **kwargs):
    source = db.query(SourceRegistry).filter_by(source_name=f"{provider}.daily").first()
    if source is None:
        source = SourceRegistry(source_name=f"{provider}.daily", source_type="fixture", category="market_data")
        db.add(source)
        db.flush()
    received = received or datetime.combine(day, time(21), tzinfo=timezone.utc)
    raw = RawFetchResult(source_id=source.id, fetched_at=received, content_hash="a" * 64,
                         raw_text="fixture", parser_version="fixture.v1")
    db.add(raw)
    db.flush()
    values = dict(provider=provider, symbol=symbol, trade_date=day, open_price=close,
                  high_price=close + 1, low_price=close - 1, close_price=close,
                  trade_volume=volume, fetched_at=received, source_id=source.id,
                  raw_result_id=raw.id, raw_contract_version="fixture.v1", authority="vendor",
                  raw_payload_hash=raw.content_hash, event_at=datetime.combine(day, time(20), tzinfo=timezone.utc),
                  finalization=finalization, price_basis="raw", volume_unit="shares", volume_status="observed")
    values.update(kwargs)
    db.add(USDailyPrice(**values))


def test_classification_same_universe_deterministic_and_unknown(db):
    for symbol in ("A", "B", "C", "D"):
        stock(db, symbol)
    for symbol, values in [("ETF", {"is_etf": True}), ("FUND", {"asset_type": "etf"}),
                           ("TEST", {"is_test_issue": True}), ("OLD", {"is_active": False})]:
        stock(db, symbol, **values)
        profile(db, symbol)
    profile(db, "A", provider="zeta")
    profile(db, "A", provider="alpha", sector=" TECHNOLOGY ")
    profile(db, "B")
    profile(db, "B", provider="new", sector=" unknown ", fetched=NOW - timedelta(days=1))
    profile(db, "C", sector=" ", industry="N/A")
    profile(db, "OUTSIDE")
    profile(db, "D", fetched=NOW + timedelta(days=1))
    db.commit()
    result = read_us_classification(db, now=NOW)
    assert result["symbols"] == ["A", "B", "C", "D"]
    assert result["profiles"]["A"]["provider"] == "alpha"
    assert result["profiles"]["A"]["sector"] == "TECHNOLOGY"
    assert result["profiles"]["A"]["raw_sector"] == " TECHNOLOGY "
    assert result["profiles"]["B"]["sector"] == "TECHNOLOGY"
    assert result["profiles"]["B"]["provider"] == "alphavantage"
    assert result["coverage"]["mapped_count"] == 2
    assert result["coverage"]["coverage_ratio"] == 0.5
    assert result["coverage"]["unknown_count"] == 2
    coverage = US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(db, expected_trade_date=DAY)
    assert {member.symbol for member in coverage.members} == set(result["symbols"])
    assert _coverage_gate(db, expected_trade_date=DAY, now=NOW)["classification_coverage"] == result["coverage"]


@pytest.mark.parametrize("label", [None, "", " ", "unknown", " Unknown ", "N/A", "None", "null", "-"])
def test_unknown_labels(label):
    assert _classification_label(label) is None


def test_utc_normalization_preserves_instant():
    local = datetime(2026, 10, 23, 20, tzinfo=timezone(timedelta(hours=8)))
    assert _aware_utc(local) == datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    assert _aware_utc(datetime(2026, 10, 23, 12)).isoformat() == "2026-10-23T12:00:00+00:00"


def test_math_reconciliation_missing_partial_zero_stale_and_provider_duplicates(db, monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("no provider IO")))
    symbols = ["UP", "DOWN", "FLAT", "ZERO", "GAP", "STALE", "MISSING", "PARTIAL", "UNCLASSIFIED"]
    for symbol in symbols:
        stock(db, symbol)
        if symbol != "UNCLASSIFIED":
            profile(db, symbol)
    for symbol, close in [("UP", 110), ("DOWN", 80), ("FLAT", 100), ("ZERO", 100)]:
        bar(db, symbol, PREVIOUS)
        bar(db, symbol, close=close, volume=0 if symbol == "ZERO" else 100)
    # Duplicate provider observations must produce one selected coherent series.
    bar(db, "UP", PREVIOUS, provider="alphavantage")
    bar(db, "UP", close=110, provider="alphavantage")
    bar(db, "GAP", PREVIOUS - timedelta(days=1))
    bar(db, "GAP", close=130)
    bar(db, "STALE", date(2026, 8, 28))
    bar(db, "PARTIAL", finalization="provisional")
    bar(db, "UNCLASSIFIED")
    db.commit()
    statements = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, sql, *args: statements.append(sql))
    monkeypatch.setattr(db, "commit", Mock(side_effect=AssertionError("read must not commit")))
    from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "__init__", lambda self: None)
    result = read_us_sector_distribution(db, now=NOW)
    counts = result.counts
    assert (counts.up, counts.down, counts.flat, counts.no_trade, counts.unknown) == (1, 1, 1, 1, 5)
    assert counts.universe == 9 and counts.comparable == 3 and counts.stale == 1
    assert counts.fresh == 6
    assert result.status == "partial" and not result.sample_only and not result.decision_usable
    known = next(g for g in result.sectors if g.sector == "TECHNOLOGY")
    assert known.avg_return_pct == pytest.approx(-10 / 3)
    assert known.median_return_pct == 0
    for groups in (result.sectors, result.industries):
        assert sum(group.counts.universe for group in groups) == counts.universe
        assert sum(group.counts.comparable for group in groups) == 3
    serialized = result.model_dump_json()
    assert "raw_receipt_id" not in serialized and "content_hash" not in serialized
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER")) for sql in statements)


@pytest.mark.parametrize("now,expected,reference", [
    (NOW, "2026-10-23", "2026-10-22"),
    (datetime(2026, 10, 23, 19, tzinfo=timezone.utc), "2026-10-22", "2026-10-21"),
    (datetime(2026, 11, 27, 18, 4, tzinfo=timezone.utc), "2026-11-25", "2026-11-24"),
    (datetime(2026, 11, 27, 18, 6, tzinfo=timezone.utc), "2026-11-27", "2026-11-25"),
])
def test_empty_uses_expected_calendar_not_historical_checkpoint(db, now, expected, reference):
    result = read_us_sector_distribution(db, now=now)
    assert result.expected_trade_date == expected and result.reference_trade_date == reference
    assert result.status == "unavailable" and result.as_of is None
    assert result.classification_coverage["coverage_ratio"] is None
    assert result.sectors == []


def test_old_profiles_without_price_intersection_are_truthful(db):
    for symbol in ("NVDA", "SPCX", "TSM"):
        stock(db, symbol)
        profile(db, symbol)
        bar(db, symbol, date(2026, 8, 28))
    db.commit()
    result = read_us_sector_distribution(db, now=NOW)
    assert result.status == "unavailable" and result.counts.comparable == 0
    assert result.coverage["inventory_current_ratio"] == 0
    assert result.counts.stale == 3 and result.counts.unknown == 3
    assert result.hot_groups == [] and result.as_of is None


def test_pre_release_receipt_cannot_supply_return(db):
    stock(db, "A"); profile(db, "A")
    bar(db, "A", PREVIOUS)
    bar(db, "A", close=110, received=datetime(2026, 10, 23, 19, tzinfo=timezone.utc))
    db.commit()
    result = read_us_sector_distribution(db, now=NOW)
    assert result.counts.comparable == 0 and result.counts.unknown == 1


def test_read_budget_never_scales_to_universe(db, monkeypatch):
    for index in range(7427):
        stock(db, f"S{index:04d}")
    for index in range(71):
        symbol = f"S{index:04d}"
        profile(db, symbol)
        bar(db, symbol, PREVIOUS)
        bar(db, symbol)
    db.commit()
    from app.us_market.sector_distribution import USDailyOhlcvPlatform
    original = USDailyOhlcvPlatform.read
    calls = []
    def counted(self, **kwargs):
        calls.append(kwargs["symbol"])
        return original(self, **kwargs)
    monkeypatch.setattr(USDailyOhlcvPlatform, "read", counted)
    queries = []
    event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, sql, *args: queries.append(sql))
    result = read_us_sector_distribution(db, now=NOW)
    assert len(calls) == 0
    assert result.coverage["over_budget_count"] == 0
    assert result.counts.not_covered == 0
    assert result.counts.comparable == 71
    assert result.counts.universe == 7427 and result.is_full_market
    assert len(queries) <= 8  # Budget bounds query amplification, not only output rows.


def test_official_get_pure_and_same_payload(db, monkeypatch):
    from fastapi import FastAPI
    import asyncio
    import json
    from app.routers import us_market
    from app.db.session import get_db
    expected = read_us_sector_distribution(db, now=NOW)
    read = Mock(return_value=expected)
    monkeypatch.setattr(us_market, "read_us_sector_distribution", read)
    app = FastAPI()
    app.include_router(us_market.router, prefix="/api/us-market")
    app.dependency_overrides[get_db] = lambda: db
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    asyncio.run(app({"type": "http", "http_version": "1.1", "method": "GET",
                     "scheme": "http", "path": "/api/us-market/sectors",
                     "query_string": b"", "headers": []}, receive, send))
    assert next(m["status"] for m in messages if m["type"] == "http.response.start") == 200
    body = json.loads(b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))
    assert body == expected.model_dump(mode="json")
    assert read.call_count == 1


@pytest.mark.parametrize("mode", ["data_only", "brief"])
def test_formal_us_ask_and_tw_schema_unchanged(db, monkeypatch, mode):
    from app.ai import ask as ai_ask, ask_execution
    from app.ai.capability_contract import CAPABILITIES
    from app.ai.schemas import AiAskRequest
    snapshot = read_us_sector_distribution(db, now=NOW)
    read = Mock(return_value=snapshot)
    monkeypatch.setattr(ask_execution, "read_us_sector_distribution", read)
    monkeypatch.setattr(ask_execution.agentic_tools, "read_us_stock_context", Mock(side_effect=AssertionError("no representative reads")))
    caps = ["market.sectors", "market.hot_groups", "market.breadth"]
    request = AiAskRequest(
        question="US sector distribution", contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"}, mode=mode, output="evidence_only",
        selection={"include": caps, "max_response_bytes": 64000}, realtime_policy="cache_only", allow_external_fetch=False, allow_llm=False,
        refresh_policy={"mode": "off"},
    )
    response = ai_ask.ask(db=db, payload=request)
    assert response["contract_version"] == "omi.decision.v4"
    assert read.call_count == 1
    assert response["target"]["market"] == "US"
    for cap in caps:
        value = response["evidence"]["data"][cap]
        assert value["schema_version"] == f"us.{cap}.v1"
        assert value["status"] == "unavailable" and value["decision_usable"] is False
        manifest = next(item for item in response["evidence"]["manifest"]["capabilities"] if item["capability"] == cap)
        assert manifest["schema_version"] == f"us.{cap}.v1"
        assert manifest["decision_usable"] is False
        assert manifest["refresh_strategy"] == "cache_only"
        assert manifest["fill_operation"] is None and manifest["estimated_calls"] == 0
        assert manifest["writes_market_cache"] is False
        assert response["execution"]["capability_schema_versions"][cap] == f"us.{cap}.v1"
    assert CAPABILITIES["market.hot_groups"].schema_version_for_market("TW") == "tw.market.hot_groups.v1"
    assert not response["continuation"]["fill_plan"]["actions"]


def test_market_dispatch_provider_ids_and_negative_markets():
    from app.ai.capability_contract import capability_resolution_for, capability_supported_for_target
    for cap in ("market.sectors", "market.hot_groups", "market.breadth"):
        us = capability_resolution_for(scope_type="market", capability_id=cap, target_market="US")
        tw = capability_resolution_for(scope_type="market", capability_id=cap, target_market="TW")
        assert us.provider_contract_ids == () and us.operation is None and us.resolution_mode == "cache_only"
        assert tw == capability_resolution_for(scope_type="market", capability_id=cap)
        assert not capability_supported_for_target(cap, scope_type="market", target_market="EU")
        assert not capability_supported_for_target(cap, scope_type="us_stock", target_market="US")


def test_nonempty_formal_ask_preserves_counts_quality_and_no_refresh(db, monkeypatch):
    from app.ai import ask as ai_ask, ask_execution
    from app.ai.schemas import AiAskRequest
    stock(db, "A"); profile(db, "A"); bar(db, "A", PREVIOUS); bar(db, "A", close=110)
    db.commit()
    snapshot = read_us_sector_distribution(db, now=NOW)
    monkeypatch.setattr(ask_execution, "read_us_sector_distribution", Mock(return_value=snapshot))
    caps = ["market.sectors", "market.hot_groups", "market.breadth"]
    result = ai_ask.ask(db=db, payload=AiAskRequest(
        question="US EOD sector sample", contract_version="omi.decision.v4",
        target={"type": "market", "market": "US"}, mode="data_only", output="evidence_only",
        selection={"include": caps, "max_response_bytes": 64000}, realtime_policy="cache_only",
        allow_external_fetch=False, allow_llm=False, refresh_policy={"mode": "off"},
    ))
    for cap in caps:
        value = result["evidence"]["data"][cap]
        assert value["counts"]["up"] == 1 and value["counts"]["unknown"] == 0
        assert value["status"] == "partial" and value["sample_only"] is False
        assert value["decision_usable"] is False
        assert result["evidence"]["capability_status"][cap]["decision_usable"] is False
    assert not result["continuation"]["fill_plan"]["actions"]


def test_read_never_autoflushes_pending_write_or_erases_other_symbols(db):
    stock(db, "MISSING_VENUE", exchange=None); profile(db, "MISSING_VENUE")
    bar(db, "MISSING_VENUE", PREVIOUS); bar(db, "MISSING_VENUE")
    db.commit()
    stock(db, "PENDING_WRITE")
    result = read_us_sector_distribution(db, now=NOW)
    assert result.counts.universe == 1 and result.counts.unknown == 1
    assert len(db.new) == 1
    assert result.sectors[0].members[0]["reason"] == "USInstrumentIdentityUnavailableError"


def test_us_projection_limit_keeps_leading_groups_and_complete_safety_metadata(db):
    from app.ai.capability_contract import project_selected_data
    from app.ai.market_context.us_distribution import merge_us_distribution_context
    for symbol, sector, close in [("UP", "A", 110), ("DOWN", "B", 80)]:
        stock(db, symbol); profile(db, symbol, sector=sector, industry=sector)
        bar(db, symbol, PREVIOUS); bar(db, symbol, close=close)
    db.commit()
    snapshot = read_us_sector_distribution(db, now=NOW)
    result = merge_us_distribution_context({}, snapshot, {"market.hot_groups"})
    projected, missing = project_selected_data(response={"result": result}, selection={
        "required": ["market.hot_groups"], "limits": {"market.hot_groups": 1},
        "fields": {"market.hot_groups": ["groups"]},
    })
    value = projected["market.hot_groups"]
    assert not missing and value["groups"][0]["industry"] == "A"
    assert value["group_projection"]["groups"] == {"available_count": 2, "returned_count": 1, "truncated": True}
    assert len(value["groups"][0]["members"][0]["price_lineage"]) == 2
    assert value["schema_version"] == "us.market.hot_groups.v1"
    assert "CORPORATE_ACTION_INTERVAL_PROOF_MISSING" in value["limitations"]


def test_mcp_ask_forwards_the_same_v4_without_new_market_logic(db, monkeypatch):
    from test_omi_mcp_server import load_server_module
    from app.ai import ask as ai_ask, ask_execution
    from app.ai.schemas import AiAskRequest
    server = load_server_module()
    snapshot = read_us_sector_distribution(db, now=NOW)
    monkeypatch.setattr(ask_execution, "read_us_sector_distribution", Mock(return_value=snapshot))
    forwarded = []
    def api_post(path, *, payload):
        assert path == "/api/ai/ask"
        response = ai_ask.ask(db=db, payload=AiAskRequest.model_validate(payload))
        forwarded.append(response)
        return response
    monkeypatch.setattr(server, "_api_post", api_post)
    result = server._call_tool("omi.ask", {
        "question": "US sector distribution", "target": {"type": "market", "market": "US"},
        "mode": "data_only", "output": "evidence_only", "realtime_policy": "cache_only",
        "allow_external_fetch": False, "allow_llm": False, "refresh_policy": {"mode": "off"},
        "selection": {"include": ["market.sectors", "market.hot_groups", "market.breadth"], "max_response_bytes": 64000},
    })
    assert result is forwarded[0]
    assert result["evidence"]["data"]["market.hot_groups"]["schema_version"] == "us.market.hot_groups.v1"


@pytest.mark.parametrize("budget", [64000, 1000000])
@pytest.mark.parametrize("selection_limit", [1, 100])
def test_large_us_snapshot_stays_nonempty_within_v4_budget(db, monkeypatch, budget, selection_limit):
    import json
    from test_omi_mcp_server import load_server_module
    from app.ai import ask as ai_ask, ask_execution
    from app.ai.schemas import AiAskRequest
    from app.ai.market_context.us_distribution import merge_us_distribution_context
    stock(db, "A"); profile(db, "A"); bar(db, "A", PREVIOUS); bar(db, "A", close=110)
    db.commit()
    snapshot = read_us_sector_distribution(db, now=NOW)
    groups = [snapshot.industries[0].model_copy(update={
        "group_id": f"SIC-{index}", "industry": f"Industry {index}",
        "members": snapshot.industries[0].members * 5,
    }) for index in range(150)]
    snapshot = snapshot.model_copy(update={"sectors": groups, "industries": groups, "hot_groups": groups,
        "counts": snapshot.counts.model_copy(update={"universe": 7427}),
        "coverage": {**snapshot.coverage, "universe_count": 7427}})
    caps = ["market.sectors", "market.hot_groups", "market.breadth"]
    limits = {cap: selection_limit for cap in caps}
    intermediate = merge_us_distribution_context({}, snapshot, set(caps), limits=limits)
    assert len(json.dumps(intermediate, ensure_ascii=False).encode()) < 64000
    assert len(snapshot.industries) == 150 and len(snapshot.industries[0].members) == 5
    monkeypatch.setattr(ask_execution, "read_us_sector_distribution", Mock(return_value=snapshot))
    server = load_server_module()
    monkeypatch.setattr(server, "_api_post", lambda path, payload: ai_ask.ask(
        db=db, payload=AiAskRequest.model_validate(payload)))
    result = server._call_tool("omi.ask", {
        "question": "US EOD groups", "target": {"type": "market", "market": "US"},
        "mode": "data_only", "output": "evidence_only", "realtime_policy": "cache_only",
        "allow_external_fetch": False, "allow_llm": False, "refresh_policy": {"mode": "off"},
        "selection": {"include": caps, "limits": limits, "max_response_bytes": budget},
    })
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= budget
    for cap in caps:
        value = result["evidence"]["data"][cap]
        assert value["counts"]["universe"] == 7427
        assert value["coverage"]["universe_count"] == 7427
        assert value["limitations"] and not value["decision_usable"]
    value = result["evidence"]["data"]["market.hot_groups"]
    assert 0 < len(value["groups"]) <= min(selection_limit, 5)
    assert value["group_count"] == 150
    assert value["group_projection"]["groups"]["available_count"] == 150
    assert value["group_projection"]["groups"]["truncated"]
    assert value["groups"][0]["members_truncated"]
    assert len(value["groups"][0]["members"][0]["price_lineage"]) == 2
