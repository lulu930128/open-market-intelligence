"""G6 source integration: real F01/F03/F04 evaluators, offline HTTP/MCP relay."""
from copy import deepcopy
from decimal import Decimal, localcontext
import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlencode

from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import capability_contract, tools
from app.ai.market_context import taiwan_screening, taiwan_swing_research as wiring
from app.ai.query_plan import build_query_plan
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster
from app.db.session import get_db
from app.market.tw_swing_screening import screen_tw_swing_candidates
from app.routers.ai import router as ai_router
from app.routers.market import router as market_router
from test_tw_swing_screening import CUTOFF, REQUESTED_AT, _evidence


class OfflineHttpClient:
    """Exercise the ASGI HTTP boundary without optional httpx or a listener."""
    def __init__(self, app):
        self.app = app

    def post(self, path, *, json):
        return self.request("POST", path, body=json)

    def get(self, path, *, params):
        return self.request("GET", path, params=params)

    def request(self, method, path, *, body=None, params=None):
        messages = []
        async def run():
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode() if body else b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": urlencode(params or {}, doseq=True).encode(),
                "headers": [(b"content-type", b"application/json")], "client": ("offline", 1),
                "server": ("offline", 80)}, receive, send)
        asyncio.run(run())
        self.status_code = messages[0]["status"]
        self.text = b"".join(item.get("body", b"") for item in messages[1:]).decode()
        return self

    def json(self):
        return json.loads(self.text)


def swing_params(**changes):
    return {"stock_ids": ["2330", "6147"], "as_of_trade_date": CUTOFF.isoformat(),
            "requested_at": REQUESTED_AT.isoformat(), "horizon_sessions": 10,
            "mode": "confirmed", **changes}


def setup_params(**changes):
    return {"setup": {"symbol": "6770", "as_of_trade_date": CUTOFF.isoformat(),
                      "direction": "long", "entry": "69.2", "stop": "65.5",
                      "targets": ["75.1", "78.1"], "quantity": 1000},
            "horizon_sessions": 10, "costs": {"commission_rate": "0.001425",
                "minimum_commission": "0", "sell_tax_rate": "0.003",
                "entry_slippage_bps": "0", "exit_slippage_bps": "0"}, **changes}


def ask_body(parameters, **selection):
    return {"contract_version": "omi.decision.v4", "question": "Read explicit swing research evidence",
            "target": {"type": "market", "market": "TW"}, "mode": "data_only",
            "output": "evidence_only", "allow_write": False, "allow_llm": False,
            "allow_external_fetch": False, "realtime_policy": "cache_only",
            "refresh_policy": {"mode": "off", "before_answer": False},
            "selection": {"include": list(parameters), "parameters": parameters, **selection}}


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    StockMaster.__table__.create(engine)
    statements = []
    with Session(engine) as db:
        db.execute(text("PRAGMA query_only=ON"))
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        app = FastAPI()
        app.include_router(ai_router, prefix="/api/ai")
        app.include_router(market_router, prefix="/api/market")
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr(tools, "_now", lambda: REQUESTED_AT)
        forbidden = Mock(side_effect=AssertionError("Unselected broad market reader executed"))
        monkeypatch.setattr(tools.taiwan_market, "read_market_overview", forbidden)
        monkeypatch.setattr(taiwan_screening, "build_tw_screening_snapshot", forbidden)
        yield OfflineHttpClient(app), statements
        event.remove(engine, "before_cursor_execute", capture)
    engine.dispose()
    assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "REPLACE")) for sql in statements)


@pytest.fixture(scope="module")
def swing_inputs():
    return (_evidence("2330"), _evidence("6147", falling=True))


def ask(client, parameters, **selection):
    response = client[0].post("/api/ai/ask", json=ask_body(parameters, **selection))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["contract_version"] == "omi.decision.v4"
    return result


@pytest.mark.parametrize("horizon", [10, 15])
def test_http_get_ask_selection_same_owner_coverage_and_leading_candidates(client, monkeypatch, swing_inputs, horizon):
    owner = Mock(side_effect=lambda db, request: screen_tw_swing_candidates(request, swing_inputs))
    monkeypatch.setattr(wiring, "build_tw_swing_screening_snapshot", owner)
    monkeypatch.setattr("app.routers.market.build_tw_swing_screening_snapshot", owner)
    parameters = swing_params(horizon_sessions=horizon)
    response = ask(client, {"screening.swing": parameters})
    payload = response["evidence"]["data"]["screening.swing"]
    get = client[0].get("/api/market/screening/swing", params={
        **parameters, "stock_ids": parameters["stock_ids"], "direction": "both"})
    assert get.status_code == 200, get.text
    raw = get.json()
    assert payload["coverage"] == raw["coverage"]
    assert payload["candidates"] == raw["candidates"]
    assert payload["request"]["horizon_sessions"] == horizon
    assert {item["direction"] for item in payload["candidates"]} == {"long", "short"}
    assert payload["sample_only"] is True
    assert payload["coverage"]["scope"] == "selected_universe"
    assert payload["as_of"] == CUTOFF.isoformat()
    manifest = next(item for item in response["evidence"]["manifest"]["capabilities"] if item["capability"] == "screening.swing")
    assert manifest["status_class"] == "limited"
    assert response["evidence"]["quality"]["capabilities"]["screening.swing"]["decision_usable"] is False
    limited = ask(client, {"screening.swing": parameters}, fields={"screening.swing": ["candidates"]},
                  limits={"screening.swing": 1})["evidence"]["data"]["screening.swing"]
    assert limited["candidates"] == raw["candidates"][:1]
    assert limited["coverage"]["universe_count"] == 2
    assert limited["coverage"]["returned_count"] == 1
    assert limited["response_truncated"] is True
    assert limited["sample_only"] is True and limited["decision_usable"] is False
    offset = ask(client, {"screening.swing": swing_params(horizon_sessions=horizon, limit=1, offset=1)})
    assert offset["evidence"]["data"]["screening.swing"]["candidates"] == raw["candidates"][1:2]


def test_actual_missing_selected_universe_is_not_valid_empty(client, monkeypatch):
    import app.market.technical_parameters as parameters
    monkeypatch.setattr(parameters, "get_technical_analysis_setting_payload", lambda: {})
    response = ask(client, {"screening.swing": swing_params()})
    payload = response["evidence"]["data"]["screening.swing"]
    assert payload["candidates"] == []
    assert payload["empty_result_is_valid"] is False
    manifest = next(item for item in response["evidence"]["manifest"]["capabilities"] if item["capability"] == "screening.swing")
    assert response["evidence"]["quality"]["capabilities"]["screening.swing"]["decision_usable"] is False
    assert manifest["status_class"] != "ready"
    assert payload["coverage"]["universe_count"] == 2
    assert payload["coverage"]["complete"] is False
    assert "UNIVERSE_MEMBER_UNAVAILABLE" in payload["limitations"]


def test_partial_corporate_action_stays_limited(client, monkeypatch, swing_inputs):
    inputs = tuple(item.model_copy(update={"price_map": item.price_map.model_copy(update={
        "payload": {**item.price_map.payload, "corporate_action": {"coverage_status": "partial"}}})})
        for item in swing_inputs)
    monkeypatch.setattr(wiring, "build_tw_swing_screening_snapshot",
                        lambda db, request: screen_tw_swing_candidates(request, inputs))
    result = ask(client, {"screening.swing": swing_params()})
    payload = result["evidence"]["data"]["screening.swing"]
    assert payload["coverage"]["qualified"] == 0
    assert payload["facts_usable"] is False and payload["decision_usable"] is False
    assert "CORPORATE_ACTION_UNKNOWN" in payload["limitations"]
    assert payload["empty_result_is_valid"] is False


@pytest.mark.parametrize("fault", ["inverted_stop", "invalid_tick", "bool_allocation"])
def test_f03_invalid_scenario_is_rejected_without_writing(client, fault):
    parameters = setup_params()
    if fault == "inverted_stop":
        parameters["setup"]["stop"] = "75"
    elif fault == "invalid_tick":
        parameters["setup"]["entry"] = "69.23"
    else:
        parameters["setup"]["target_quantities"] = [True, 999]
    response = client[0].post("/api/ai/ask", json=ask_body({"research.trade_setup": parameters}))
    assert response.status_code in {400, 422}, response.text


@pytest.mark.parametrize("short", [False, True])
def test_real_pure_f03_net_rr_proposed_and_missing_cost_unknown(client, short):
    parameters = setup_params()
    if short:
        parameters["setup"].update(symbol="3481", direction="short", entry="48.5", stop="51.2", targets=["42.8", "39.15"])
        parameters["costs"]["short_borrow_cost"] = "100"
    result = ask(client, {"research.trade_setup": parameters})
    payload = result["evidence"]["data"]["research.trade_setup"]
    assert payload["status"] == "proposed" and payload["trigger_ready"] is False
    assert payload["execution_eligibility"] == "unknown" and payload["execution_ready"] is False
    manifest = next(item for item in result["evidence"]["manifest"]["capabilities"] if item["capability"] == "research.trade_setup")
    assert manifest["decision_usable"] is False
    assert Decimal(payload["gross_risk"]) == (Decimal("2700") if short else Decimal("3700"))
    target = payload["target_scenarios"][0]
    with localcontext() as context:
        context.prec = 34
        assert Decimal(target["net_rr"]) == Decimal(target["net_pnl"]) / Decimal(payload["net_stop_loss"])
    assert Decimal(target["net_rr"]) < Decimal(target["gross_rr"])
    unknown = ask(client, {"research.trade_setup": setup_params(costs={})},
                  fields={"research.trade_setup": ["target_scenarios"]})["evidence"]["data"]["research.trade_setup"]
    assert unknown["target_scenarios"][0]["net_rr"] is None
    assert unknown["missing_costs"] and unknown["cost_assumptions"]
    assert unknown["decision_usable"] is False


def test_f04_existing_cache_reader_event_regulation_and_unknown_borrow(client, monkeypatch):
    listing = Mock(return_value={"results": [{"stock_id": "2303", "market": "TWSE",
        "event_type": "investor_conference", "start_date": "2026-10-28", "end_date": "2026-10-28",
        "provider": "fixture", "source": "conference", "start_time": "14:00"}],
        "total_count": 1, "as_of": CUTOFF, "sources": {"conference": {"provider": "fixture", "source": "conference",
            "fetched_at": REQUESTED_AT.isoformat(), "status": "current"}}})
    monkeypatch.setattr("app.market.tw_corporate_events.list_taiwan_corporate_events", listing)
    monkeypatch.setattr("app.market.tw_disposition.get_taiwan_disposition_status", Mock(return_value={
        "is_active": False, "margin_trading_suspended": False, "status": "current",
        "fetched_at": REQUESTED_AT.isoformat()}))
    monkeypatch.setattr("app.market.service.list_stock_margin_trade_history", Mock(return_value=[]))
    parameters = {"stock_id": "2303", "market": "TWSE", "direction": "short",
        "as_of_trade_date": CUTOFF.isoformat(), "requested_at": REQUESTED_AT.isoformat(),
        "entry_trade_date": "2026-10-28", "horizon_sessions": 15, "quantity": 1000}
    payload = ask(client, {"research.trade_eligibility": parameters})["evidence"]["data"]["research.trade_eligibility"]
    assert payload["borrow_available"] == "unknown"
    assert payload["funding_sufficient"] == "unknown"
    assert payload["broker_execution_eligible"] == "unknown"
    assert len(payload["holding_sessions"]) == 15
    assert payload["event_risk"][0]["event"]["event_type"] == "investor_conference"
    assert payload["event_coverage_complete"] is False
    assert payload["evidence"]["regulation"]["disposition_active"] is False
    assert listing.call_args.kwargs["limit"] == 100
    assert "BORROW_UNKNOWN" in payload["limitations"]


@pytest.mark.parametrize("capability,parameters", [
    ("screening.swing", swing_params(stock_ids=[])),
    ("screening.swing", swing_params(stock_ids=[str(i) for i in range(101)])),
    ("screening.swing", swing_params(stock_ids=["2330", "2330"])),
    ("screening.swing", swing_params(horizon_sessions=11)),
    ("screening.swing", swing_params(requested_at="2026-10-27T18:00:00")),
    ("screening.swing", swing_params(offset=-1)),
    ("screening.swing", {}),
    ("research.trade_setup", setup_params(costs={"bogus": 0})),
    ("research.trade_setup", {}),
])
def test_parameter_validation_before_any_reader(client, monkeypatch, capability, parameters):
    reader = Mock(side_effect=AssertionError("Invalid parameters reached reader"))
    monkeypatch.setattr(taiwan_screening, "read_research_capability", reader)
    response = client[0].post("/api/ai/ask", json=ask_body({capability: parameters}))
    assert response.status_code in {400, 422}, response.text
    reader.assert_not_called()


def test_query_plan_and_resolution_have_no_fill_or_external_side_effect():
    for capability, parameters in (("screening.swing", swing_params()), ("research.trade_setup", setup_params())):
        payload = AiAskRequest(question="explicit research", mode="data_only", output="evidence_only",
            selection={"include": [capability], "parameters": {capability: parameters}})
        plan = build_query_plan(payload=payload, scope_type="market", question_intent="general",
                                effective_mode="data_only", target_market="TW")
        assert plan.external_refresh_allowed is False
        resolution = capability_contract.capability_resolution_for(scope_type="market", capability_id=capability)
        assert resolution.operation is None and resolution.side_effect_policy in {"pure_read_only", "cache_read_only_no_refresh"}


@pytest.mark.parametrize("capability", ["screening.swing", "research.trade_setup"])
def test_generated_mcp_schema_and_readonly_relay_match_http(client, monkeypatch, swing_inputs, capability):
    path = Path(__file__).resolve().parents[2] / "agents/omi_mcp_server/server.py"
    spec = importlib.util.spec_from_file_location("g6_mcp_server", path)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    if capability == "screening.swing":
        monkeypatch.setattr(wiring, "build_tw_swing_screening_snapshot",
                            lambda db, request: screen_tw_swing_candidates(request, swing_inputs))
    parameters = {capability: swing_params() if capability == "screening.swing" else setup_params()}
    expected = ask(client, parameters)
    forwarded = []
    def post(path, *, payload):
        forwarded.append((path, deepcopy(payload)))
        response = client[0].post(path, json=payload)
        assert response.status_code == 200, response.text
        return response.json()
    monkeypatch.setattr(server, "_api_post", post)
    result = server._call_tool("omi.ask", ask_body(parameters))
    assert result["evidence"]["data"] == expected["evidence"]["data"]
    assert forwarded[0][1]["selection"]["parameters"] == parameters
    assert forwarded[0][1]["allow_write"] is False
    snapshot = json.loads((path.parent / "public_contract_snapshot.json").read_text(encoding="utf-8"))
    schema = snapshot["ask_input_schema"]["properties"]["selection"]["properties"]["parameters"]["properties"]
    for capability in ("screening.swing", "research.trade_setup", "research.trade_eligibility"):
        assert schema[capability] == capability_contract.CAPABILITIES[capability].parameter_schema
        assert "$ref" not in json.dumps(schema[capability])


def test_combined_swing_and_setup_keep_independent_evidence_and_quality(client, monkeypatch, swing_inputs):
    monkeypatch.setattr(wiring, "build_tw_swing_screening_snapshot",
                        lambda db, request: screen_tw_swing_candidates(request, swing_inputs))
    result = ask(client, {"screening.swing": swing_params(), "research.trade_setup": setup_params()},
                 max_response_bytes=131072)
    data = result["evidence"]["data"]
    assert data["screening.swing"]["coverage"]["universe_count"] == 2
    assert data["research.trade_setup"]["status"] == "proposed"
    assert Decimal(data["research.trade_setup"]["gross_risk"]) == Decimal("3700")
    manifest = {item["capability"]: item for item in result["evidence"]["manifest"]["capabilities"]}
    assert manifest["screening.swing"]["returned_count"] == len(data["screening.swing"]["candidates"])
    assert manifest["screening.swing"]["canonical_available_count"] == data["screening.swing"]["coverage"]["candidate_count"]
    assert manifest["screening.swing"]["decision_usable"] is False
    assert manifest["research.trade_setup"]["decision_usable"] is False


def discovery_params(**changes):
    return {"as_of_trade_date": CUTOFF.isoformat(), "requested_at": REQUESTED_AT.isoformat(), **changes}


@pytest.fixture
def discovery_owner(monkeypatch, swing_inputs):
    from test_tw_swing_prefilter import _install
    return _install(monkeypatch, {item.stock_id: item for item in swing_inputs})[0]


@pytest.mark.parametrize("horizon", [10, 15])
def test_discovery_http_get_ask_same_owner_full_scope_partial_quality(client, discovery_owner, horizon):
    parameters = discovery_params(horizon_sessions=horizon)
    result = ask(client, {"screening.swing_discovery": parameters}, max_response_bytes=65536)
    payload = result["evidence"]["data"]["screening.swing_discovery"]
    response = client[0].get("/api/market/screening/swing-discovery", params=parameters)
    assert response.status_code == 200, response.text
    assert response.json() == payload
    assert payload["coverage"]["all_considered"] is True
    assert payload["coverage"]["is_full_market"] is True
    assert payload["sample_only"] is False
    assert payload["coverage"]["quality_complete"] is False
    assert payload["coverage"]["quality_status"] == "partial"
    assert payload["freshness_status"] == "partial" and payload["decision_usable"] is False
    assert payload["research_sample_only"] is True
    assert "checkpoint" not in payload and "detail_batches" not in payload
    assert "rows" not in payload and "universe_stock_ids" not in payload
    assert len(json.dumps(payload).encode()) < 32768
    assert len(discovery_owner["canonical"]) == 2  # one call per HTTP request
    assert all(len(call["symbols"]) <= 100 for call in discovery_owner["canonical"])
    assert result["evidence"]["quality"]["capabilities"]["screening.swing_discovery"]["decision_usable"] is False
    assert payload["request"]["max_batches"] == 20


def test_discovery_bounded_partial_stays_partial_without_public_checkpoint(client, discovery_owner):
    result = ask(client, {"screening.swing_discovery": discovery_params(batch_size=1, max_batches=1)})
    payload = result["evidence"]["data"]["screening.swing_discovery"]
    assert payload["status"] == "in_progress"
    assert payload["coverage"]["considered"] == 1 and payload["coverage"]["pending"] == 1
    assert payload["coverage"]["is_full_market"] is False and payload["sample_only"] is True
    assert "DISCOVERY_BOUNDED_READ_INCOMPLETE" in payload["missing"]
    assert payload["empty_result_is_valid"] is False
    assert len(discovery_owner["canonical"]) == 1 and not discovery_owner["detail"]


def test_discovery_narrow_projection_keeps_scope_quality_and_leading_summaries(client, discovery_owner):
    result = ask(client, {"screening.swing_discovery": discovery_params()},
        fields={"screening.swing_discovery": ["ranked_prefilter"]}, limits={"screening.swing_discovery": 1})
    payload = result["evidence"]["data"]["screening.swing_discovery"]
    assert len(payload["ranked_prefilter"]) == 1 and payload["returned_count"] == 1
    assert payload["available_count"] == 2 and payload["response_truncated"] is True
    assert payload["coverage"]["universe_count"] == payload["coverage"]["considered"] == 2
    assert payload["coverage"]["quality_status"] == "partial" and payload["sample_only"] is False
    assert payload["decision_usable"] is False and payload["limitations"]


@pytest.mark.parametrize("changes", [
    {"batch_size": 101}, {"max_batches": 21}, {"max_batches": True},
    {"checkpoint": {}}, {"horizon_sessions": 11}, {"limit": 101},
])
def test_discovery_parameters_reject_outside_native_bounds_before_read(client, monkeypatch, changes):
    reader = Mock(side_effect=AssertionError("Invalid discovery reached owner"))
    monkeypatch.setattr(wiring, "build_tw_swing_discovery_snapshot", reader)
    response = client[0].post("/api/ai/ask", json=ask_body({"screening.swing_discovery": discovery_params(**changes)}))
    assert response.status_code in {400, 422}, response.text
    reader.assert_not_called()


def test_discovery_mcp_relay_and_generated_schema_use_one_bounded_read(client, discovery_owner, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "agents/omi_mcp_server/server.py"
    spec = importlib.util.spec_from_file_location("g6_discovery_mcp", path)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    parameters = {"screening.swing_discovery": discovery_params(limit=1)}
    expected = ask(client, parameters)
    def post(path, *, payload):
        response = client[0].post(path, json=payload)
        assert response.status_code == 200, response.text
        return response.json()
    monkeypatch.setattr(server, "_api_post", post)
    result = server._call_tool("omi.ask", ask_body(parameters))
    assert result["evidence"]["data"] == expected["evidence"]["data"]
    snapshot = json.loads((path.parent / "public_contract_snapshot.json").read_text(encoding="utf-8"))
    schema = snapshot["ask_input_schema"]["properties"]["selection"]["properties"]["parameters"]["properties"]["screening.swing_discovery"]
    assert schema == capability_contract.CAPABILITIES["screening.swing_discovery"].parameter_schema
    assert schema["properties"]["max_batches"]["default"] == 20
    assert "checkpoint" not in schema["properties"]


def test_main_registers_original_journal_router_without_ask_write_capabilities():
    from app.main import app
    from app.routers.research_trade_journal import router
    prefix = "/api/research/trade-proposals"
    registered = [route for route in app.routes if getattr(route, "path", "").startswith(prefix)]
    assert len(registered) == len(router.routes)
    for route in router.routes:
        assert any(item.path == prefix + route.path and item.methods == route.methods
                   and item.endpoint is route.endpoint for item in registered)
    assert not any("journal" in capability or "proposal" in capability for capability in capability_contract.CAPABILITIES)
