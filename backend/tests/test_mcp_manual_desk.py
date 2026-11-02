"""Fixed MCP HTTP -> real Native facade/session path, isolated SQLite + Fake SDK.

No app.main, native factory, real control subprocess, broker login or live data.
"""
import asyncio
from dataclasses import replace
import json
import os
from threading import Event, Thread
from types import SimpleNamespace as NS
from uuid import uuid4

from fastapi import FastAPI
import pytest

from app.research.candidate_control import ControlRejected, ControlUnavailable
from app.research.candidate_service import CandidateService
from app.research.manual_desk_service import ManualDeskService
from app.routers import conditional_candidates as api
from execution_runtime import control as native_control, service as native_service
from execution_runtime.application import ExecutionApplication
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.headless import public_result
from execution_runtime.tests.fake_sdk import ACCOUNT, DAY, NOW, FakeSession, Frame
from test_conditional_candidates import evidence, migration, raw
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PREFIX = "/api/research/conditional-candidates"


class OfflineClient:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, body=None):
        messages = []

        async def run():
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"",
                        "more_body": False}

            async def send(message):
                messages.append(message)

            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": PREFIX + path,
                "raw_path": (PREFIX + path).encode(), "query_string": b"",
                "headers": [(b"content-type", b"application/json")], "client": ("offline", 1),
                "server": ("offline", 80)}, receive, send)

        asyncio.run(run())
        return NS(status_code=messages[0]["status"],
                  body=json.loads(b"".join(m.get("body", b"") for m in messages[1:])))

    def post(self, path, body):
        return self.request("POST", path, body)

    def get(self, path):
        return self.request("GET", path)


def draft_body(**changes):
    return {"client_intent_id": "mcp-test-intent", "symbol": "2330", "action": "Buy", "condition": "CASH",
            "lot": "Odd", "quantity_shares": 10, "price": "50", **changes}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    sdk = FakeSession()
    inventory = {"rows": [{"Symbol": "2330", "NETQTY0": 1120, "NETQTY9": 120}]}
    original_report = sdk.account_report
    sdk.Account.OrderReport = lambda: Frame(original_report().rows,
        {"OrderNo", "TradeDate", "StockID", "Qty", "Side"})

    def inventory_sum(mode):
        assert mode == "B"
        if inventory.get("error"):
            raise TimeoutError("private vendor message must not leave owner")
        return Frame(inventory["rows"], {"Symbol", "NETQTY0", "NETQTY9"})

    sdk.Account.InventorySum = inventory_sum
    factories = []

    def binding():
        factories.append(True)
        return sdk.binding()

    runtime = ExecutionRuntime(tmp_path / "native.sqlite", account_id=ACCOUNT, trade_date=DAY,
        session_factory=binding, clock=lambda: NOW, strategy_effects=False)
    runtime.start()
    application = ExecutionApplication(runtime)
    engine = create_engine("sqlite:///" + (tmp_path / "research.sqlite").as_posix())
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration().upgrade()
    factory = sessionmaker(engine)
    calls = []
    state = {"lost": None}

    def exchange(value):
        return native_service.handle(runtime, application, value, simulation=True, loaded="fixture")[0]

    state["exchange"] = exchange

    def control(value):
        calls.append(value)
        try:
            result = state["exchange"](value)
        except ValueError as exc:
            raise ControlRejected(str(exc)) from exc
        route = value.get("request", {}).get("argv", [None])[0]
        if state["lost"] is not None and state["lost"] == route:
            state["lost"] = None
            raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
        return result

    def candidate_service(db, **kwargs):
        return CandidateService(db, control=kwargs.get("control", control), clock=lambda: NOW,
            evidence=lambda db, spec, now: evidence(spec, now=now, price="100"))

    from app.research import manual_desk_service
    monkeypatch.setattr(manual_desk_service, "CandidateService", candidate_service)
    monkeypatch.setattr(api, "ManualDeskService", lambda db=None: ManualDeskService(db, control=control))
    monkeypatch.setattr(api, "CandidateService", candidate_service)
    app = FastAPI()
    app.include_router(api.router, prefix=PREFIX)

    def db():
        with factory() as session:
            yield session

    app.dependency_overrides[api.get_db] = db
    value = NS(client=OfflineClient(app), sdk=sdk, runtime=runtime, app=application, calls=calls,
        control=control, state=state, inventory=inventory, factories=factories,
        factory=factory, candidate_service=candidate_service)
    yield value
    runtime.close()
    engine.dispose()


def confirm(client, review, **changes):
    if review.get("kind") == "manual_stage":
        return client.post("/desk/staged/" + review["id"] + "/confirm", {
            "expected_revision": review["revision"], "expected_digest": review["digest"], **changes})
    return client.post("/desk/reviews/" + review["review_id"] + "/confirm", {
        "expected_revision": review["review_revision"], "expected_digest": review["snapshot"]["digest"], **changes})


def invoke(desk, method, *args, **kwargs):
    with desk.factory() as db:
        return getattr(desk.candidate_service(db), method)(*args, **kwargs)


def journal_rows(runtime):
    with runtime._journal.connection(readonly=True) as con:
        return [tuple(row) for row in con.execute("SELECT * FROM journal ORDER BY seq")]


def native_review(desk):
    # Existing broker-read/legacy-review tests use a pre-existing isolated review.
    draft = {"owner_id": "MCP", "source": "MANUAL", "command": {
        "account_id": "SELECTED", "trade_date": DAY, "request_id": "existing-review", "intent_id": "existing-review",
        "symbol": "2330", "action": "Buy", "condition": "CASH", "lot": "Odd", "quantity": 10,
        "price": "50", "space_id": "USER_SPACE", "shares_per_unit": 1}}
    from app.research.candidate_control import command
    review = command(desk.control, ["draft", "--draft-json", json.dumps(draft)])
    return command(desk.control, ["preview", review["review_id"], "--expected-revision", "1"])


@pytest.mark.parametrize("condition,action,lot,shares,broker_qty", [
    ("CASH", "Buy", "Odd", 123, 123), ("CASH", "Sell", "Odd", 123, 123),
    ("CASH", "Buy", "Common", 2000, 2), ("CASH", "Sell", "Common", 1000, 1),
    ("MARGIN", "Buy", "Common", 1000, 1), ("CASH_SELLING", "Sell", "Common", 1000, 1),
    ("SHORT_SELLING", "Sell", "Common", 2000, 2)])
def test_fixed_draft_preview_confirm_mapping(desk, condition, action, lot, shares, broker_qty):
    client = desk.client
    result = client.post("/desk/draft", draft_body(condition=condition, action=action, lot=lot, quantity_shares=shares))
    assert result.status_code == 201, result.body
    stage = result.body
    assert stage["lifecycle"] == "STAGED" and stage["revision"] == 1
    assert stage["owner_id"] == "MCP" and stage["source"] == "MANUAL" and stage["space_id"] == "USER_SPACE"
    assert "trade_date" not in stage["raw"] and "account_id" not in stage["raw"]
    assert desk.calls == [] and desk.app.list() == []
    assert desk.sdk.broker.attempts == []  # Dismiss modal: no confirm request, zero broker effects.
    selected = confirm(client, stage)
    assert selected.status_code == 200, selected.body
    receipt = selected.body["manual_stage"]["submission"]["receipt"]
    assert receipt["execution"]["filled_shares"] == 0
    assert receipt["snapshot"]["order_semantics"]["broker_quantity"] == broker_qty
    assert receipt["draft"]["command"]["trade_date"] == DAY
    assert len(desk.sdk.broker.attempts) == 1
    submitted = desk.sdk.broker.attempts[0]
    assert (submitted["order_cond"], submitted["action"], submitted["odd_lot"], submitted["qty"]) == (
        condition, action, lot, broker_qty)
    before = len(desk.calls)
    assert confirm(client, stage).status_code == 200
    assert len(desk.calls) == before
    assert client.post("/desk/draft", draft_body(condition=condition, action=action, lot=lot,
        quantity_shares=shares)).body["id"] == stage["id"]
    assert len(desk.sdk.broker.attempts) == 1 and len(desk.factories) == 1
    assert desk.runtime.verify()


@pytest.mark.parametrize("changes", [
    {"client_intent_id": ""}, {"client_intent_id": "bad/id"}, {"symbol": "bad symbol"},
    {"quantity_shares": 0}, {"quantity_shares": True}, {"quantity_shares": 1.1},
    {"lot": "Common", "quantity_shares": 1500}, {"condition": "MARGIN"},
    {"condition": "MARGIN", "lot": "Common", "quantity_shares": 1000, "action": "Sell"},
    {"condition": "SHORT_SELLING", "lot": "Common", "quantity_shares": 1000},
    {"condition": "CASH_SELLING", "lot": "Common", "quantity_shares": 1000},
    {"price": "NaN"}, {"price": "0"}, {"source": "MCP"}, {"owner_id": "other"}, {"space_id": "AGENT_SPACE"}])
def test_http_validation_before_native(desk, changes):
    assert desk.client.post("/desk/draft", draft_body(**changes)).status_code == 422
    assert desk.calls == [] and desk.app.list() == []


def test_missing_stable_identity_and_invalid_confirmation(desk):
    body = draft_body()
    del body["client_intent_id"]
    assert desk.client.post("/desk/draft", body).status_code == 422
    review = desk.client.post("/desk/draft", draft_body()).body
    assert confirm(desk.client, review, expected_revision=2).body["detail"]["code"] == "STALE_STAGE_SELECTION"
    assert confirm(desk.client, review, expected_digest="0" * 64).body["detail"]["code"] == "STALE_STAGE_SELECTION"
    assert confirm(desk.client, review, expected_revision=True).status_code == 422
    assert confirm(desk.client, review, expected_digest="bad").status_code == 422
    assert desk.sdk.broker.attempts == []


@pytest.mark.parametrize("lost", ["draft", "preview"])
def test_lost_draft_reply_same_intent_finds_original_without_send(desk, lost):
    stage = desk.client.post("/desk/draft", draft_body()).body
    desk.state["lost"] = lost
    response = confirm(desk.client, stage)
    assert response.status_code == 503
    assert response.body["detail"]["retry_policy"] == "CHECK_STATUS_DO_NOT_RESEND"
    listed = desk.client.get("/desk/order-reports").body
    assert len(listed["reviews"]) == 1
    original = listed["reviews"][0]
    current = desk.client.post("/desk/draft", draft_body()).body
    assert current["id"] == stage["id"] and current["lifecycle"] == "SUBMISSION_UNKNOWN"
    assert original["draft"]["command"]["intent_id"] == current["manual_stage"]["submission"]["native_intent_id"]
    before = len(desk.calls)
    assert confirm(desk.client, stage).body["lifecycle"] == "SUBMISSION_UNKNOWN"
    assert len(desk.calls) == before
    assert len(desk.app.list()) == 1 and desk.sdk.broker.attempts == []
    conflict = desk.client.post("/desk/draft", draft_body(price="51"))
    assert conflict.status_code == 409 and conflict.body["detail"]["code"] == "STAGE_IDEMPOTENCY_CONFLICT"
    desk.runtime.close()
    desk.runtime.start()
    assert public_result(desk.app.list()[0])["review_id"] == original["review_id"]
    assert desk.sdk.broker.attempts == [] and desk.runtime.verify()


def test_unknown_submit_and_lost_confirm_never_resend(desk):
    desk.sdk.submit_mode = "error_after"
    review = desk.client.post("/desk/draft", draft_body()).body
    desk.state["lost"] = "confirm"
    assert confirm(desk.client, review).status_code == 503
    current = desk.client.get("/desk/staged/" + review["id"]).body
    native_id = current["manual_stage"]["submission"]["native"]["review_id"]
    assert desk.app.status(native_id)["execution"]["state"] == "UNKNOWN"
    before = len(desk.calls)
    assert confirm(desk.client, review).body["lifecycle"] == "SUBMISSION_UNKNOWN"
    assert len(desk.calls) == before
    assert desk.client.post("/desk/draft", draft_body()).body["lifecycle"] == "SUBMISSION_UNKNOWN"
    readback = desk.client.get("/desk/order-reports").body
    assert readback["reviews"][0]["execution"]["state"] == "UNKNOWN"
    assert readback["broker_orders"][0]["ownership"] == "EXTERNAL"  # No heuristic adoption.
    assert len(desk.sdk.broker.attempts) == 1 and desk.runtime.verify()


def test_exact_cancel_identity_and_ack(desk):
    review = native_review(desk)
    result = confirm(desk.client, review).body
    execution = result["execution"]
    url = "/desk/executions/" + execution["execution_id"] + "/cancel"
    assert desk.client.post(url, {"trade_date": DAY, "broker_order_id": "other"}).status_code == 409
    assert desk.client.post(url, {"trade_date": "yesterday", "broker_order_id": "O0001"}).status_code == 422
    assert desk.sdk.broker.cancels == []
    body = {"trade_date": DAY, "broker_order_id": execution["broker_order_id"]}
    for _ in range(2):
        response = desk.client.post(url, body)
        assert response.status_code == 200 and response.body["cancel_stage"] == "ACK_ONLY"
    assert desk.sdk.broker.cancels == [execution["broker_order_id"]]


def external(desk, *, lot="Odd", condition="CASH", qty=10, oid="PHONE-1"):
    return desk.sdk.broker.add({"symbol": "2330", "action": "Sell", "qty": qty,
        "price": 50, "odd_lot": lot, "order_cond": condition, "time_in_force": "ROD"},
        order_id=oid, channel="MOBILE")


def test_same_readback_external_orders_real_fills_inventory_and_no_writes(desk, monkeypatch):
    review = native_review(desk)
    oid = external(desk, lot="Common", qty=2)
    event = desk.sdk.broker.fill(oid, 1, "phone-fill")
    desk.sdk.event(event)  # Callback + ExecReport must dedupe by exact key/CNT.
    before = journal_rows(desk.runtime)
    monkeypatch.setattr(desk.runtime, "_wake_strategies", lambda **kw: pytest.fail("GET woke effects"))
    value = desk.client.get("/desk/order-reports").body
    assert value["contract"] == "omi.execution-desk.v1" and value["quality"] == "PARTIAL"
    assert value["reviews"][0]["review_id"] == review["review_id"] and value["reviews"][0]["state"] == "PREVIEW"
    assert len(value["broker_orders"]) == 1 and len(value["fills"]) == 1
    order, fill = value["broker_orders"][0], value["fills"][0]
    assert order["ownership"] == "EXTERNAL" and order["space_id"] == "USER_SPACE"
    assert order["quantity_shares"] == 2000 and order["known_filled_shares"] == 1000
    assert fill["quantity_shares"] == 1000 and fill["quality"] == "KNOWN"
    assert {e["source"] for e in fill["evidence"]} == {"Order.set_event", "Order.ExecReport"}
    assert all(e["source_at"].startswith(DAY + "T10:00:01") for e in fill["evidence"])
    assert not value["fill_history_complete"]
    cash = value["inventory"]["cash"]
    assert cash["quality"] == "PARTIAL" and cash["source_as_of"] is None
    assert cash["items"][0]["reported_total_shares"] == 1120
    assert cash["items"][0]["odd_shares"] == 120 and cash["items"][0]["sellable_shares"] is None
    for key in ("margin", "short_selling"):
        assert value["inventory"][key]["quality"] == "UNKNOWN" and value["inventory"][key]["items"] is None
    assert desk.client.get("/desk/fills").body["fills"] == value["fills"]
    assert desk.client.get("/desk/inventory").body["inventory"] == value["inventory"]
    assert journal_rows(desk.runtime) == before
    assert ACCOUNT not in json.dumps(value)
    assert desk.sdk.broker.attempts == [] and desk.sdk.broker.cancels == [] and len(desk.factories) == 1


def test_submitted_or_cache_filled_is_not_a_real_fill(desk, monkeypatch):
    oid = external(desk)
    original = desk.sdk.trade

    def trade(order_id):
        value = original(order_id)
        value.order_status.status = "Filled"
        value.order_status.deals = [NS(quantity=10, price=50, ts="100001")]
        return value

    monkeypatch.setattr(desk.sdk, "trade", trade)
    value = desk.client.get("/desk/order-reports").body
    assert value["fills"] == [] and value["broker_orders"][0]["known_filled_shares"] == 0
    assert value["broker_orders"][0]["broker_status"] == "Filled"
    assert value["broker_orders"][0]["fill_history_complete"] is False


def test_partial_reads_keep_external_report_and_quarantine_reasons(desk, monkeypatch):
    oid = external(desk)
    desk.sdk.broker.order_rows.append({**desk.sdk.broker.order_rows[0], "OrderNo": "0000"})
    monkeypatch.setattr(desk.sdk, "get_trades", lambda **kw: None)
    monkeypatch.setattr(desk.sdk, "ExecReport", lambda: (_ for _ in ()).throw(TimeoutError("private message")))
    desk.inventory["error"] = True
    value = desk.client.get("/desk/order-reports").body
    assert value["broker_orders"][0]["broker_key"]["order_id"] == oid
    assert {s["source"]: s["status"] for s in value["sources"]} == {
        "Account.OrderReport": "PARTIAL", "Order.get_trades(full=True)": "UNAVAILABLE", "Order.ExecReport": "UNAVAILABLE"}
    assert value["unparsed_reports"][0]["reason"] == "BROKER_ORDER_ID_UNAVAILABLE"
    assert value["inventory"]["cash"]["quality"] == "UNKNOWN" and value["inventory"]["cash"]["items"] is None
    assert "private message" not in json.dumps(value)


def test_cache_id_without_timestamp_is_visible_as_unknown(desk, monkeypatch):
    oid = external(desk)
    desk.sdk.broker.order_rows.clear()

    def undated(order_id):
        # Read a cache-shaped order with no report/event time. The source does
        # not justify substituting receipt time or claiming a known total.
        order = NS(**desk.sdk.broker.orders[order_id])
        return NS(order=order, order_status=NS(status="Submitted", deals=[], modified_time=None,
                                             modified_quantity=10))

    monkeypatch.setattr(desk.sdk, "trade", undated)
    value = desk.client.get("/desk/order-reports").body
    assert len(value["broker_orders"]) == 1
    order = value["broker_orders"][0]
    assert order["broker_key"]["order_id"] == oid and order["quality"] == "UNKNOWN"
    assert order["quantity_shares"] is None and order["facts"] == [] and value["fills"] == []


def test_partial_order_report_does_not_hide_cache_fill_or_inventory(desk, monkeypatch):
    oid = external(desk)
    desk.sdk.broker.fill(oid, 3, "external-only-fill")
    desk.sdk.query_error = True
    # Installed SDK may expose only Account.ExecReport; retain actual source.
    exec_report = desk.sdk.ExecReport
    desk.sdk.Account.ExecReport = exec_report
    monkeypatch.setattr(desk.sdk, "ExecReport", None)
    value = desk.client.get("/desk/order-reports").body
    assert value["broker_orders"][0]["broker_key"]["order_id"] == oid
    assert value["fills"][0]["quantity_shares"] == 3
    assert value["fills"][0]["evidence"][0]["source"] == "Account.ExecReport"
    assert value["inventory"]["cash"]["items"][0]["reported_total_shares"] == 1120
    assert "SDK_READ_FAILED" in value["inventory"]["cash"]["reasons"]


def test_conflicting_fill_id_preserves_unknown_instead_of_double_count(desk):
    oid = external(desk)
    desk.sdk.event(desk.sdk.broker.fill(oid, 3, "same-id"))
    # Fabricated inconsistent ExecReport for the exact same fill identity.
    desk.sdk.broker.deal_rows[0]["DealQty"] = 4
    value = desk.client.get("/desk/order-reports").body
    assert len(value["fills"]) == 1
    fill = value["fills"][0]
    assert fill["quality"] == "UNKNOWN" and fill["quantity_shares"] is None
    assert len(fill["evidence"]) == 2
    assert value["broker_orders"][0]["known_filled_shares"] is None


def test_source_failure_keeps_durable_external_callback_with_receipt_time(desk, monkeypatch):
    oid = external(desk)
    desk.sdk.event(desk.sdk.broker.fill(oid, 3, "durable-fill"))
    before = journal_rows(desk.runtime)
    monkeypatch.setattr(desk.runtime.session, "query", lambda **kw: (_ for _ in ()).throw(TimeoutError()))
    desk.inventory["error"] = True
    value = desk.client.get("/desk/order-reports").body
    assert value["quality"] == "UNKNOWN"
    fill = value["fills"][0]
    assert fill["quantity_shares"] == 3 and fill["evidence"][0]["current_read"] is False
    assert fill["evidence"][0]["received_at"] == NOW.isoformat()
    assert journal_rows(desk.runtime) == before


@pytest.mark.parametrize("condition,action,direction", [
    ("CASH", "Buy", "long"), ("CASH", "Sell", "short"), ("MARGIN", "Buy", "long"),
    ("CASH_SELLING", "Sell", "short"), ("SHORT_SELLING", "Sell", "short")])
def test_user_candidate_pending_prepare_approve_same_session(desk, condition, action, direction):
    body = raw(space_id="USER_SPACE", source="MANUAL", condition=condition, action=action,
        direction=direction, lot="Common", quantity=1000)
    created = desk.client.post("", {"owner_id": "MCP", "raw": body})
    assert created.status_code == 201 and created.body["lifecycle"] == "ACTIVE"
    candidate = created.body
    pending = invoke(desk, "observe", candidate["id"])["pending"]
    assert pending["qualification"]["send_ready"], pending["qualification"]
    assert pending["qualification"]["borrow_status"] == ("UNKNOWN" if condition == "SHORT_SELLING" else "NOT_APPLICABLE")
    prepared = desk.client.post("/pending/" + pending["id"] + "/prepare", {}).body
    assert prepared["state"] == "NATIVE_PREVIEW"
    assert desk.sdk.broker.attempts == []
    assert desk.client.get("/" + candidate["id"] + "/pending").body[0]["id"] == pending["id"]
    response = desk.client.post("/pending/" + pending["id"] + "/approve", {
        "expected_revision": prepared["revision"], "expected_digest": prepared["digest"]})
    assert response.status_code == 200 and response.body["state"] == "SELECTED", response.body
    review = response.body["execution_receipt"]
    assert review["draft"]["command"]["space_id"] == "USER_SPACE" and review["draft"]["source"] == "MANUAL"
    assert review["draft"]["owner_id"] == "MCP" and len(desk.sdk.broker.attempts) == 1
    assert desk.sdk.broker.attempts[0]["order_cond"] == condition
    assert desk.sdk.broker.attempts[0]["qty"] == 1
    # A normal order uses exactly the same session as the conditional order.
    normal = desk.client.post("/desk/draft", draft_body()).body
    assert confirm(desk.client, normal).status_code == 200
    assert len(desk.factories) == 1 and len(desk.sdk.broker.attempts) == 2
    assert desk.runtime.verify()


def test_user_monitor_prepares_without_confirm_and_agent_provenance_stays(desk):
    from app.jobs.candidate_monitor import run_cycle
    user = invoke(desk, "create", raw(space_id="USER_SPACE", source="MANUAL"), owner_id="MCP")
    agent = invoke(desk, "create", raw(), owner_id="old-agent")
    cycle = run_cycle(desk.factory, desk.candidate_service)
    assert cycle["errors"] == 0
    for candidate, space, source in ((user, "USER_SPACE", "MANUAL"), (agent, "AGENT_SPACE", "AGENT_PROPOSAL")):
        pending = invoke(desk, "pending", candidate["id"])[0]
        assert pending["state"] == "NATIVE_PREVIEW"
        native = desk.app.status(pending["native"]["review_id"])
        assert native["draft"]["command"]["space_id"] == space and native["draft"]["source"] == source
    assert desk.sdk.broker.attempts == []
    response = desk.client.post("/" + agent["id"] + "/revisions", {"expected_revision": 1,
        "raw": raw(space_id="USER_SPACE", source="MANUAL")})
    assert response.status_code == 409 and response.body["detail"]["code"] == "CANDIDATE_PROVENANCE_IMMUTABLE"


@pytest.mark.skipif(os.name != "nt", reason="Windows Native IPC contract")
def test_fixed_http_routes_through_actual_isolated_native_pipe(desk, tmp_path, monkeypatch):
    address = r"\\.\pipe\omi-mcp-desk-test-" + uuid4().hex
    monkeypatch.setattr(native_service, "ADDRESS", address)
    monkeypatch.setattr(native_control, "ADDRESS", address)
    errors = []
    ready = Event()
    original_record_state = native_service.record_state

    def record_state(path, value):
        original_record_state(path, value)
        ready.set()  # Listener exists before the first process receipt.

    monkeypatch.setattr(native_service, "record_state", record_state)

    def serve():
        try:
            native_service.serve_runtime(desk.runtime, desk.app, True, tmp_path / "pipe-state")
        except BaseException as exc:
            errors.append(type(exc).__name__)
            ready.set()

    thread = Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(5) and not errors, errors

    def exchange(value):
        response = native_control.request_control(value)
        if not response["ok"]:
            raise ControlRejected(response["code"])
        return response["result"]

    desk.state["exchange"] = exchange
    try:
        assert desk.client.get("/desk/status").body["broker_session"] == "CONNECTED"
        review = desk.client.post("/desk/draft", draft_body()).body
        assert desk.client.get("/desk/order-reports").body["reviews"] == []
        assert confirm(desk.client, review).status_code == 200
        assert len(desk.client.get("/desk/order-reports").body["reviews"]) == 1
        for endpoint in ("order-reports", "fills", "inventory"):
            assert desk.client.get("/desk/" + endpoint).status_code == 200
        assert len(desk.sdk.broker.attempts) == 1 and len(desk.factories) == 1
    finally:
        native_control.request_control({"operation": "stop"})
        thread.join(5)
    assert not thread.is_alive() and errors == []


def test_backend_control_cli_fixed_request_contract(monkeypatch):
    from app.research import candidate_control
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return NS(stdout=json.dumps({"ok": True, "result": {"fixture": True}}))

    monkeypatch.setattr(candidate_control.subprocess, "run", run)
    assert candidate_control.request_control({"operation": "readback"}) == {"fixture": True}
    request = {"id": "transport-receipt", "argv": ["list"]}
    candidate_control.request_control({"operation": "command", "request": request})
    assert calls[0][0][1:] == ["-B", "-m", "execution_runtime.control", "readback"]
    assert calls[0][0][0].replace("\\", "/").endswith("/.venv-kgi/Scripts/python.exe")
    assert json.loads(calls[1][0][-1]) == request
    assert calls[0][1]["timeout"] == 65 and calls[0][1]["capture_output"]


@pytest.mark.parametrize("operation", ["status", "readback"])
def test_backend_control_does_not_inherit_launcher_stdin(monkeypatch, operation):
    from app.research import candidate_control

    def run(argv, **kwargs):
        # A one-shot controller never consumes Backend stdin. Inheriting its
        # shutdown pipe can stall Windows Python before control IPC starts.
        assert kwargs["stdin"] == candidate_control.subprocess.DEVNULL
        assert kwargs["capture_output"] is True and kwargs["text"] is True
        assert kwargs["cwd"] == candidate_control.ROOT
        assert kwargs["creationflags"] == getattr(candidate_control.subprocess, "CREATE_NO_WINDOW", 0)
        return NS(stdout=json.dumps({"ok": True, "result": {"operation": operation}}))

    monkeypatch.setattr(candidate_control.subprocess, "run", run)
    assert candidate_control.request_control({"operation": operation}) == {"operation": operation}


@pytest.mark.parametrize("response", ["null", "[]", '"text"', "{}", '{"ok": "true"}', '{"ok": true}'])
def test_malformed_native_control_response_stays_unknown(monkeypatch, response):
    from app.research import candidate_control
    monkeypatch.setattr(candidate_control.subprocess, "run", lambda *a, **kw: NS(stdout=response))
    with pytest.raises(ControlUnavailable, match="EXECUTOR_RESPONSE_UNKNOWN"):
        candidate_control.request_control({"operation": "readback"})
