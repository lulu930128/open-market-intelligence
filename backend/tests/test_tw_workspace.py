from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base, StockMaster, WatchlistGroup, WatchlistItem, SourceRegistry, RawFetchResult,
    MarketDailyPrice, TaiwanStockQuoteSnapshot, TaiwanIntradayStockState,
    TaiwanCurrentBreadthSnapshot,
)
from app.db.session import get_db
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import TW_REALTIME_SOURCE_BINDINGS, TW_QUOTE_SNAPSHOT_CAPABILITY_ID
from app.market.tw_intraday_state import INTRADAY_STATE_VERSION
from app.market.tw_market_dashboard import build_tw_stock_chart, build_tw_stock_research, _load_state_by_stock, _state_as_of
from app.market.tw_market_dashboard_schemas import TaiwanStockChartRead, TaiwanStockResearchRead, TaiwanWorkspaceHeaderRead
from app.market.tw_workspace import build_tw_workspace_header, build_tw_workspace_watchlist, build_tw_workspace_hot_groups
from app.market.tw_watchlist_state import read_taiwan_watchlist_instrument_state, read_taiwan_watchlist_instrument_states
from app.market.tw_current_market_repository import read_breadth_price_states
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.contracts import BreadthPriceState, SourceLineage, AuthorityClass
from app.routers.tw_market_dashboard import router
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


DAY = date(2026, 8, 25)


def at(hour, minute=0, day=25):
    return datetime(2026, 8, day, hour, minute, tzinfo=TAIWAN_TZ)


@pytest.fixture
def db(monkeypatch):
    def forbidden_io(*_args, **_kwargs):
        raise AssertionError("workspace attempted external I/O")
    monkeypatch.setattr("socket.create_connection", forbidden_io)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden_io)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, count=20):
    symbols = tuple(str(2000 + i) for i in range(count))
    group = WatchlistGroup(group_name="Workspace", sort_order=1, is_active=True)
    db.add(group)
    db.flush()
    for i, symbol in enumerate(symbols):
        db.add(StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE",
                           instrument_type="ETF" if i == 0 else "stock", is_active=True))
        db.add(WatchlistItem(group_id=group.id, stock_id=symbol, priority=i, enabled=True))
    binding = next(b for b in TW_REALTIME_SOURCE_BINDINGS if
                   b.descriptor.capability_id == TW_QUOTE_SNAPSHOT_CAPABILITY_ID and b.descriptor.provider_key == "twse_mis")
    source = SourceRegistry(source_name=binding.source, source_type=binding.source_type,
                            category="market_data", parser_type=binding.parser_version, reliability_level="official")
    daily_source = SourceRegistry(source_name=TWSE_DAILY_TRADING_SOURCE_NAME, source_type="api",
                                  category="market_data", parser_type="twse_daily_trading", reliability_level="official", priority=10)
    db.add_all([source, daily_source])
    db.flush()
    for clock, trade, price in [(at(10), "trade_observed", 102), (at(10, 1), "awaiting_first_trade", None),
                                (at(13, 30), "trade_observed", 103)]:
        raw = RawFetchResult(source_id=source.id, fetched_at=(clock + timedelta(minutes=3)).astimezone(timezone.utc),
                             parser_version=binding.parser_version, content_hash=str(clock), raw_text="{}")
        db.add(raw)
        db.flush()
        for symbol in symbols:
            db.add(TaiwanStockQuoteSnapshot(
                source_id=source.id, raw_result_id=raw.id, provider="twse_mis", source=binding.source,
                market="TWSE", stock_id=symbol, trade_date=DAY, quote_time=clock,
                received_at=raw.fetched_at, raw_contract_version=binding.parser_version,
                observation_state="available", market_session="closing_auction" if clock.hour == 13 else "continuous",
                session_phase="post_close" if clock.hour == 13 else "regular_live",
                trade_state=trade, last_price=price, previous_close=100, total_volume_lots=20,
            ))
    for day, hour, close in [(24, 8, 100), (25, 8, 104)]:
        raw = RawFetchResult(source_id=daily_source.id, fetched_at=datetime(2026, 8, day, hour, tzinfo=timezone.utc),
                             parser_version="twse.stock_day_all.v1", content_hash=f"daily-{day}-{hour}", raw_text="[]")
        db.add(raw)
        db.flush()
        for symbol in symbols:
            db.add(MarketDailyPrice(source_id=daily_source.id, raw_result_id=raw.id, stock_id=symbol,
                trade_date=date(2026, 8, day), open_price=close, high_price=close, low_price=close,
                close_price=close, price_change=1, trade_volume=10000))
    db.commit()
    return symbols


@pytest.mark.parametrize("clock", [at(8, 30), at(10, 4), at(14), at(16, 30), at(10, day=26), at(10, day=29)])
def test_batch_matches_canonical_single_reads_and_is_read_pure(db, clock):
    symbols = seed(db, 3)
    expected = {symbol: read_taiwan_watchlist_instrument_state(db, instrument_id=symbol, requested_at=clock) for symbol in symbols}
    db.expire_all()
    db.execute(text("PRAGMA query_only=ON"))
    with patch("app.market.tw_watchlist_state.read_taiwan_watchlist_instrument_state", side_effect=AssertionError("N+1")):
        actual = read_taiwan_watchlist_instrument_states(db, instrument_ids=symbols, requested_at=clock)
    assert actual == expected


def test_selected_watchlist_sql_budget_does_not_grow_per_symbol(db):
    symbols = seed(db, 100)
    db.execute(text("PRAGMA query_only=ON"))
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        assert statement.lstrip().upper().startswith(("SELECT", "PRAGMA", "WITH"))
    event.listen(db.bind, "before_cursor_execute", record)
    try:
        counts = []
        for limit in [1, 20, 100]:
            db.expire_all()
            statements.clear()
            result = build_tw_workspace_watchlist(db, watchlist_limit=limit, now=at(14))
            assert len(result["items"]) == limit
            counts.append(len(statements))
        assert max(counts) <= counts[0] + 2, counts
        assert max(counts) <= 30, counts
        assert [item["stock_id"] for item in result["items"]] == list(symbols)
        assert result["items"][0]["instrument_type"] == "etf"
        print(f"watchlist SQL statements (1/20/100 symbols): {counts}")
    finally:
        event.remove(db.bind, "before_cursor_execute", record)


def test_header_uses_summary_and_aggregate_without_materializing_universe(db):
    for provider, clock in [("first", at(10)), ("second", at(10, 4))]:
        db.add(TaiwanIntradayStockState(provider=provider, market="TWSE", stock_id="2330", trade_date=DAY,
            event_time=clock, snapshot_as_of=clock, source="test", state_contract_version=INTRADAY_STATE_VERSION))
    db.commit()
    newest = max(_state_as_of(row) for row in _load_state_by_stock(db, trade_date=DAY).values())
    db.expunge_all()
    db.execute(text("PRAGMA query_only=ON"))
    statements = []
    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", record)
    try:
        result = TaiwanWorkspaceHeaderRead.model_validate(build_tw_workspace_header(db, now=at(10, 5)))
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert result.freshness.newest_as_of == newest
    assert result.freshness.oldest_as_of == newest
    assert result.freshness.status == "current"
    assert not any("stock_master" in statement.lower() for statement in statements)
    assert not any(isinstance(item, (StockMaster, TaiwanIntradayStockState)) for item in db.identity_map.values())
    assert not any("cache is unavailable" in warning for warning in result.warnings), result.warnings


@pytest.mark.parametrize("defect", ["premature", "missing_ohlc", "broken_lineage", "untrusted", "tpex", "missing"])
def test_batch_keeps_invalid_and_missing_evidence_semantics(db, defect):
    symbol = seed(db, 1)[0]
    if defect == "tpex":
        db.query(StockMaster).filter_by(stock_id=symbol).one().market = "TPEX"
    elif defect == "missing":
        db.query(TaiwanStockQuoteSnapshot).delete()
        db.query(MarketDailyPrice).delete()
    else:
        daily = db.query(MarketDailyPrice).filter_by(stock_id=symbol, trade_date=DAY).one()
        if defect == "premature":
            db.get(RawFetchResult, daily.raw_result_id).fetched_at = datetime(2026, 8, 25, 6, tzinfo=timezone.utc)
        elif defect == "missing_ohlc":
            daily.close_price = None
        elif defect == "broken_lineage":
            daily.raw_result_id = None
            db.query(TaiwanStockQuoteSnapshot).update({"raw_result_id": None})
        elif defect == "untrusted":
            db.get(SourceRegistry, daily.source_id).reliability_level = "unknown"
    db.commit()
    expected = read_taiwan_watchlist_instrument_state(db, instrument_id=symbol, requested_at=at(16, 30))
    db.expire_all()
    db.execute(text("PRAGMA query_only=ON"))
    actual = read_taiwan_watchlist_instrument_states(db, instrument_ids=(symbol,), requested_at=at(16, 30))
    assert actual[symbol] == expected


def test_batch_bound_empty_unknown_and_dirty_session_do_not_write(db):
    assert read_taiwan_watchlist_instrument_states(db, instrument_ids=(), requested_at=at(14)) == {}
    with pytest.raises(ValueError, match="100"):
        read_taiwan_watchlist_instrument_states(db, instrument_ids=("2330",) * 101, requested_at=at(14))
    db.execute(text("PRAGMA query_only=ON"))
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    assert read_taiwan_watchlist_instrument_states(db, instrument_ids=("absent",), requested_at=at(14)) == {}
    assert db.new


def test_selected_breadth_companion_batch_matches_single_json_projection(db):
    symbols = seed(db, 3)
    clock = at(13, 33)
    source = SourceRegistry(source_name="twse_mis_live_breadth", source_type="http",
                            category="market_data", parser_type="test")
    db.add(source)
    db.flush()
    raw = RawFetchResult(source_id=source.id, fetched_at=clock.astimezone(timezone.utc),
                         content_hash="breadth", parser_version="test", raw_text="{}")
    db.add(raw)
    db.flush()
    states = {symbol: BreadthPriceState(
        trade_date=DAY, price=110, price_as_of=at(13, 30), previous_close=100,
        lineage=SourceLineage(provider="twse_mis", source=source.source_name, authority=AuthorityClass.EXCHANGE,
            raw_contract_version="test", event_at=at(13, 30), received_at=clock.astimezone(timezone.utc),
            fetched_at=clock.astimezone(timezone.utc), raw_receipt_id=f"raw_fetch_result:{raw.id}", content_hash="breadth"),
    ).model_dump(mode="json") for symbol in symbols}
    db.add(TaiwanCurrentBreadthSnapshot(
        source_id=source.id, raw_result_id=raw.id, provider="twse_mis", source=source.source_name,
        authority="exchange", raw_contract_version="test", venue="TWSE", trade_date=DAY,
        event_at=at(13, 30), received_at=clock.astimezone(timezone.utc), fetched_at=clock.astimezone(timezone.utc),
        session="closing_auction", scope="full_market", universe_source="test", universe_count=3,
        advance_count=3, decline_count=0, unchanged_count=0, observation_state="available",
        price_semantics="current_last_trade_vs_reference", price_states_json=json.dumps(states),
    ))
    db.commit()
    db.execute(text("PRAGMA query_only=ON"))
    selected = (symbols[0], symbols[2], "absent")
    batch = read_breadth_price_states(db, venue="TWSE", requested_at=at(14), symbols=selected)
    singles = {}
    for symbol in selected:
        singles.update(read_breadth_price_states(db, venue="TWSE", requested_at=at(14), symbols=(symbol,)))
    assert batch == singles
    assert set(batch) == {symbols[0], symbols[2]}
    expected = {symbol: read_taiwan_watchlist_instrument_state(db, instrument_id=symbol, requested_at=at(14)) for symbol in symbols}
    assert read_taiwan_watchlist_instrument_states(db, instrument_ids=symbols, requested_at=at(14)) == expected


@pytest.mark.parametrize("count", [1, 20, 100])
@pytest.mark.parametrize("visible", [False, True])
def test_breadth_companion_reads_json_only_after_receipt_visibility(db, count, visible):
    """Count real SQLite JSON work, not just statements or tiny-fixture latency."""
    symbols = seed(db, count)
    source = SourceRegistry(source_name="twse_mis_live_breadth", source_type="http",
                            category="market_data", parser_type="test")
    db.add(source)
    db.flush()

    def add_snapshot(clock, *, payload=None, received=None, fetched=None, raw_fetched=None):
        raw = RawFetchResult(source_id=source.id, fetched_at=raw_fetched or clock.astimezone(timezone.utc),
                             content_hash=str(clock), parser_version="test", raw_text="{}")
        db.add(raw)
        db.flush()
        if payload is None:
            states = {symbol: BreadthPriceState(
                trade_date=clock.date(), price=110, price_as_of=clock, previous_close=100,
                lineage=SourceLineage(provider="twse_mis", source=source.source_name,
                    authority=AuthorityClass.EXCHANGE, raw_contract_version="test", event_at=clock,
                    received_at=clock.astimezone(timezone.utc), fetched_at=raw.fetched_at,
                    raw_receipt_id=f"raw_fetch_result:{raw.id}", content_hash=raw.content_hash),
            ).model_dump(mode="json") for symbol in symbols}
            payload = json.dumps(states)
        db.add(TaiwanCurrentBreadthSnapshot(
            source_id=source.id, raw_result_id=raw.id, provider="twse_mis", source=source.source_name,
            authority="exchange", raw_contract_version="test", venue="TWSE", trade_date=clock.date(),
            event_at=clock, received_at=received or clock.astimezone(timezone.utc),
            fetched_at=fetched or clock.astimezone(timezone.utc), session="continuous", scope="full_market",
            universe_source="test", universe_count=count, advance_count=count, decline_count=0,
            unchanged_count=0, observation_state="available", price_semantics="current_last_trade_vs_reference",
            price_states_json=payload,
        ))
        return payload

    # Large previous-session payloads must not even be decoded. Distinct gates
    # also exclude future events and each of the three receipt timestamps.
    history = json.dumps({str(8000+i): {"padding": "x" * 512} for i in range(250)})
    for i in range(40):
        add_snapshot(at(9, day=24) + timedelta(minutes=i), payload=history)
    for i, gate in enumerate(("received", "fetched", "raw_fetched")):
        add_snapshot(at(10, 10+i), payload=history, **{gate: at(15).astimezone(timezone.utc)})
    add_snapshot(at(15), payload=history)
    expected_json = None
    if visible:
        for minute in range(10):
            expected_json = add_snapshot(at(10, minute))
        # Latest malformed JSON must still fall back to the latest valid
        # visible receipt; the metadata boundary must not LIMIT candidates to 1.
        add_snapshot(at(10, 20), payload="{malformed")
    db.commit()
    db.expunge_all()
    db.execute(text("PRAGMA query_only=ON"))
    decoded = []
    native = sqlite3.connect(":memory:")
    connection = db.connection().connection.driver_connection

    def count_json(value):
        decoded.append(value)
        return native.execute("SELECT json_valid(?)", (value,)).fetchone()[0]

    connection.create_function("json_valid", 1, count_json)
    try:
        result = read_breadth_price_states(db, venue="TWSE", requested_at=at(11), symbols=symbols)
        assert set(result) == (set(symbols) if visible else set())
        assert decoded == (["{malformed", expected_json] if visible else [])
        if visible:
            assert all(item["price_as_of"] == at(10, 9) for item in result.values())
            assert all(item["price"] == 110 for item in result.values())
        decoded.clear()
        workspace = build_tw_workspace_watchlist(db, watchlist_limit=count, now=at(11))
        assert len(workspace["items"]) == count
        assert decoded == (["{malformed", expected_json] if visible else [])
    finally:
        connection.create_function("json_valid", 1, None)
        native.close()


@pytest.mark.parametrize("bound", [1, 2, 8])
def test_quote_batch_preserves_candidate_bound_and_provider_roles(db, bound):
    symbol = seed(db, 1)[0]
    original = db.query(TaiwanStockQuoteSnapshot).filter_by(stock_id=symbol, quote_time=at(10)).one()
    values = {column.name: getattr(original, column.name) for column in TaiwanStockQuoteSnapshot.__table__.columns
              if column.name != "id"}
    for binding in TW_REALTIME_SOURCE_BINDINGS:
        if binding.descriptor.capability_id != TW_QUOTE_SNAPSHOT_CAPABILITY_ID or binding.descriptor.provider_key == "twse_mis":
            continue
        source = SourceRegistry(source_name=binding.source, source_type=binding.source_type,
                                category="market_data", parser_type=binding.parser_version)
        db.add(source)
        db.flush()
        raw = RawFetchResult(source_id=source.id, fetched_at=at(10, 3).astimezone(timezone.utc),
                             content_hash=binding.source, parser_version=binding.parser_version)
        db.add(raw)
        db.flush()
        db.add(TaiwanStockQuoteSnapshot(**{**values, "provider": binding.descriptor.provider_key,
            "source": binding.source, "source_id": source.id, "raw_result_id": raw.id,
            "raw_contract_version": binding.parser_version, "quote_time": at(10, 2), "last_price": 105}))
    db.commit()
    instrument = resolve_taiwan_instrument(db, symbol)
    expected = TaiwanPublicQuoteRepository(db).load_quote_candidates(instrument, requested_at=at(10, 4), max_candidates=bound)
    db.execute(text("PRAGMA query_only=ON"))
    batch = TaiwanPublicQuoteRepository(db)
    batch.preload_quote_candidates((instrument,), requested_at=at(10, 4))
    assert batch.load_quote_candidates(instrument, requested_at=at(10, 4), max_candidates=bound) == expected


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
def test_chart_never_builds_report_and_research_is_independent(db, timeframe):
    symbol = seed(db, 1)[0]
    db.execute(text("PRAGMA query_only=ON"))
    with patch("app.market.tw_market_dashboard.build_stock_technical_report", side_effect=AssertionError("chart waited for research")):
        chart = TaiwanStockChartRead.model_validate(build_tw_stock_chart(db, stock_id=symbol, timeframe=timeframe))
        assert chart.stock_id == symbol
        assert "technical" not in chart.model_dump()
    with patch("app.market.tw_market_dashboard.list_stock_ohlc_chart_data", side_effect=AssertionError("research waited for workspace chart")):
        research = TaiwanStockResearchRead.model_validate(build_tw_stock_research(db, stock_id=symbol, timeframe=timeframe))
        assert research.technical.stock_id == symbol


def test_routes_validate_and_preserve_legacy_paths_without_startup(db):
    app = FastAPI()
    app.include_router(router, prefix="/api/market/tw-dashboard")
    app.dependency_overrides[get_db] = lambda: db
    async def request(suffix):
        path, _, query = ("/api/market/tw-dashboard/" + suffix).partition("?")
        messages = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
                   "query_string": query.encode(), "headers": [], "server": ("test", 80),
                   "client": ("test", 123), "root_path": ""}, receive, send)
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, json.loads(body)
    db.execute(text("PRAGMA query_only=ON"))
    for suffix in ["header", "watchlist", "hot-groups"]:
        status, body = asyncio.run(request(suffix))
        assert status == 200, body
        assert body["cache_only"] is True
    for suffix in ["stocks/absent/chart", "stocks/absent/research", "watchlist?watchlist_group_id=999"]:
        assert asyncio.run(request(suffix))[0] == 404
    for suffix in ["watchlist?watchlist_limit=101", "hot-groups?group_limit=31", "stocks/2000/chart?bars=501", "stocks/2000/research?timeframe=invalid"]:
        assert asyncio.run(request(suffix))[0] == 422
    paths = app.openapi()["paths"]
    assert "/api/market/tw-dashboard/snapshot" in paths
    assert "/api/market/tw-dashboard/stocks/{stock_id}" in paths


def test_generated_snapshot_and_adapter_are_mechanical_relays():
    root = Path(__file__).resolve().parents[2]
    def load(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    generator = load(root / "scripts/generate-tw-dashboard-mcp-contract-snapshot.py", "workspace_generator")
    generated = generator._load_snapshot()
    assert generated == json.loads((root / "agents/omi_mcp_server/tw_market_dashboard_contract_snapshot.json").read_text(encoding="utf-8"))
    server = load(root / "agents/omi_mcp_server/server.py", "workspace_adapter")
    for tool in generated["workspace_tools"]:
        arguments = {"stock_id": "2330"} if tool["path_parameters"] else {}
        sentinel = {"status": "missing", "warnings": ["cache unavailable"]}
        with patch.object(server, "_api_get", return_value=sentinel) as read:
            assert server._call_tool(tool["name"], arguments) is sentinel
            read.assert_called_once_with(tool["path"].replace("{stock_id}", "2330"), {})
        with patch.object(server, "_api_get", side_effect=RuntimeError("404 missing")):
            with pytest.raises(RuntimeError, match="404 missing"):
                server._call_tool(tool["name"], arguments)
        schema = tool["outputSchema"]
        route = next(route for route in router.routes if "omi." + route.name == tool["name"])
        assert schema == route.response_model.model_json_schema()
        for variant in schema.get("anyOf", [schema]):
            if "$ref" in variant:
                assert variant["$ref"].startswith("#/$defs/")
                variant = schema["$defs"][variant["$ref"].removeprefix("#/$defs/")]
            properties = variant["properties"]
            assert properties["cache_only"]["const"] is True
            assert properties["kind"]["const"] == properties["kind"]["default"]
            assert properties["version"]["const"] == properties["version"]["default"]
