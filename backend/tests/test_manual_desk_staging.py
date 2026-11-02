"""Local stage -> explicit pinned confirmation, isolated DB + Fake Native only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from app.research.candidate_control import ControlRejected, ControlUnavailable
from app.research.candidate_service import CandidateService
from app.jobs.candidate_monitor import run_cycle
from execution_runtime.tests.fake_sdk import NOW
from test_mcp_manual_desk import desk, draft_body, confirm, invoke, journal_rows
from test_conditional_candidates import raw


def offline(desk, monkeypatch):
    def unavailable(value):
        raise ControlUnavailable("EXECUTOR_UNAVAILABLE")
    monkeypatch.setitem(desk.state, "exchange", unavailable)


def test_local_stage_offline_saturday_persistent_and_separate_from_broker(desk, monkeypatch):
    offline(desk, monkeypatch)
    before = journal_rows(desk.runtime)
    # A local write does not consult the session clock, market/provider or Native.
    with desk.factory() as db:
        stage = CandidateService(db, control=lambda v: pytest.fail("Native on local stage"),
            evidence=lambda *a: pytest.fail("market on local stage"),
            clock=lambda: NOW.replace(day=31)).create(draft_body(), owner_id="MCP", manual_stage=True)
    assert stage["lifecycle"] == "STAGED" and stage["kind"] == "manual_stage"
    assert stage["owner_id"] == "MCP" and stage["space_id"] == "USER_SPACE" and stage["source"] == "MANUAL"
    assert not {"account_id", "trade_date", "conditions", "valid_from_date"} & stage["raw"].keys()
    assert stage["manual_stage"]["submission"] is None
    assert desk.calls == [] and journal_rows(desk.runtime) == before
    assert desk.client.get("/desk/staged").body == [stage]
    assert desk.client.get("/desk/staged/" + stage["id"]).body == stage
    assert desk.client.get("/desk/order-reports").status_code == 503
    assert desk.client.get("/desk/staged/" + stage["id"]).body == stage
    with desk.factory() as db:
        assert db.execute(text("SELECT count(*) FROM research_candidate_pending_revision")).scalar_one() == 0


def test_same_identity_idempotent_conflicting_and_numerically_equivalent_price(desk):
    stage = desk.client.post("/desk/draft", draft_body()).body
    assert desk.client.post("/desk/draft", draft_body(price="50.00")).body == stage
    assert desk.client.post("/desk/draft", draft_body(price="51")).status_code == 409
    assert desk.client.post("/desk/draft", draft_body(quantity_shares=11)).status_code == 409
    assert desk.client.get("/desk/staged").body == [stage] and desk.calls == []


def test_local_edit_cancel_and_stale_modal_never_native(desk):
    stage = desk.client.post("/desk/draft", draft_body()).body
    url = "/" + stage["id"]
    edited = desk.client.post(url + "/revisions", {"expected_revision": 1, "raw": draft_body(price="51")}).body
    assert edited["raw"]["price"] == "51" and edited["revision"] == 2
    assert confirm(desk.client, stage).status_code == 409 and desk.calls == []
    assert desk.client.post("/desk/draft", draft_body()).body == edited
    assert desk.client.post(url + "/revisions", {"expected_revision": 2,
        "raw": draft_body(client_intent_id="replacement")}).status_code == 409
    cancelled = desk.client.post(url + "/cancel", {"expected_revision": 2}).body
    assert cancelled["lifecycle"] == "CANCELLED" and cancelled["revision"] == 3
    assert confirm(desk.client, cancelled).status_code == 409 and desk.calls == []
    assert desk.client.post("/desk/draft", draft_body()).body == cancelled


@pytest.mark.parametrize("mode", ["unavailable", "disconnected", "expired", "wrong_date"])
def test_unavailable_confirm_keeps_exact_stage_pending(desk, monkeypatch, mode):
    stage = desk.client.post("/desk/draft", draft_body()).body
    def exchange(value):
        assert value == {"operation": "status"}
        if mode == "unavailable":
            raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
        return {"broker_session": "DISCONNECTED" if mode == "disconnected" else "CONNECTED",
            "trade_date": "2000-01-01" if mode == "wrong_date" else NOW.date().isoformat(),
            "session_date_matches": mode != "expired"}
    monkeypatch.setitem(desk.state, "exchange", exchange)
    assert confirm(desk.client, stage).status_code == 503
    assert desk.client.get("/desk/staged/" + stage["id"]).body == stage
    assert desk.app.list() == [] and desk.sdk.broker.attempts == []


def test_explicit_confirm_exact_chain_no_db_lock_during_ipc_and_no_retry(desk, monkeypatch):
    stage = desk.client.post("/desk/draft", draft_body()).body
    original = desk.state["exchange"]
    def exchange(value):
        with desk.factory.kw["bind"].begin() as connection:
            connection.exec_driver_sql("PRAGMA busy_timeout=50")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        return original(value)
    monkeypatch.setitem(desk.state, "exchange", exchange)
    response = confirm(desk.client, stage)
    assert response.status_code == 200 and response.body["lifecycle"] == "SUBMITTED", response.body
    assert [v.get("request", {}).get("argv", [v["operation"]])[0] for v in desk.calls] == ["status", "draft", "preview", "confirm"]
    submission = response.body["manual_stage"]["submission"]
    assert submission["pin"] == {"revision": stage["revision"], "digest": stage["digest"]}
    assert submission["receipt"]["draft"]["command"]["intent_id"] == submission["native_intent_id"]
    calls = list(desk.calls)
    assert confirm(desk.client, stage).body == response.body and desk.calls == calls
    for op in ("cancel", "pause", "revisions"):
        body = {"expected_revision": response.body["revision"]}
        if op == "revisions":
            body["raw"] = draft_body(price="51")
        assert desk.client.post("/" + stage["id"] + "/" + op, body).status_code == 409
    assert len(desk.sdk.broker.attempts) == 1 and desk.sdk.broker.cancels == []


@pytest.mark.parametrize("phase", ["draft", "preview", "confirm"])
def test_lost_phase_reply_locked_across_new_sessions_no_resend(desk, phase):
    stage = desk.client.post("/desk/draft", draft_body()).body
    desk.state["lost"] = phase
    assert confirm(desk.client, stage).status_code == 503
    value = desk.client.get("/desk/staged/" + stage["id"]).body
    assert value["lifecycle"] == "SUBMISSION_UNKNOWN"
    assert value["manual_stage"]["submission"]["phase"] == phase.upper()
    calls = list(desk.calls)
    assert confirm(desk.client, stage).body == value and desk.calls == calls
    assert desk.client.post("/desk/draft", draft_body()).body == value
    assert len(desk.sdk.broker.attempts) == int(phase == "confirm")


def test_native_unknown_receipt_not_promoted_to_submitted(desk):
    desk.sdk.submit_mode = "error_after"
    stage = desk.client.post("/desk/draft", draft_body()).body
    response = confirm(desk.client, stage)
    assert response.status_code == 200 and response.body["lifecycle"] == "SUBMISSION_UNKNOWN"
    assert response.body["manual_stage"]["submission"]["receipt"]["execution"]["state"] == "UNKNOWN"
    calls = list(desk.calls)
    confirm(desk.client, stage)
    assert desk.calls == calls and len(desk.sdk.broker.attempts) == 1


@pytest.mark.parametrize("native_state,stage_state", [
    ("REJECTED", "SUBMISSION_REJECTED"), ("CANCELLED", "SUBMISSION_CANCELLED"),
    ("PENDING", "SUBMISSION_PENDING"), ("UNKNOWN", "SUBMISSION_UNKNOWN"),
    ("RECONCILING", "SUBMISSION_UNKNOWN"), ("FUTURE_STATE", "SUBMISSION_UNKNOWN"),
    ("ACCEPTED", "SUBMITTED"), ("PARTIALLY_FILLED", "SUBMITTED"), ("FILLED", "SUBMITTED")])
def test_native_order_state_projection_retains_exact_receipt_no_resend(desk, monkeypatch, native_state, stage_state):
    stage = desk.client.post("/desk/draft", draft_body()).body
    original = desk.state["exchange"]
    receipts = []
    def exchange(value):
        result = original(value)
        if value.get("request", {}).get("argv", [None])[0] == "confirm":
            receipt = result["result"]
            receipt = {**receipt, "execution": {**receipt["execution"], "state": native_state}}
            receipts.append(receipt)
            result = {**result, "result": receipt}
        return result
    monkeypatch.setitem(desk.state, "exchange", exchange)
    response = confirm(desk.client, stage)
    assert response.status_code == 200 and response.body["lifecycle"] == stage_state, response.body
    assert response.body["manual_stage"]["submission"]["receipt"] == receipts[0]
    calls = list(desk.calls)
    assert confirm(desk.client, stage).body == response.body
    assert desk.calls == calls and len(desk.sdk.broker.attempts) == 1


def test_known_rejection_locks_identity_without_automatic_retry(desk, monkeypatch):
    stage = desk.client.post("/desk/draft", draft_body()).body
    original = desk.state["exchange"]
    def exchange(value):
        if value.get("request", {}).get("argv", [None])[0] == "confirm":
            raise ControlRejected("PRIVATE_FIXTURE_MESSAGE")
        return original(value)
    monkeypatch.setitem(desk.state, "exchange", exchange)
    assert confirm(desk.client, stage).status_code == 409
    current = desk.client.get("/desk/staged/" + stage["id"]).body
    assert current["lifecycle"] == "SUBMISSION_REJECTED"
    assert "PRIVATE_FIXTURE_MESSAGE" not in str(current)
    calls = list(desk.calls)
    response = confirm(desk.client, stage)
    assert response.status_code == 200 and response.body == current
    assert desk.calls == calls and desk.sdk.broker.attempts == []


def test_manual_stage_never_monitor_prepared_and_non_stage_excluded(desk):
    stage = desk.client.post("/desk/draft", draft_body()).body
    agent = invoke(desk, "create", raw(), owner_id="research-owner")
    assert desk.client.get("/desk/staged").body == [stage]
    assert desk.client.get("/desk/staged/" + agent["id"]).status_code == 409
    assert desk.client.get("").body[0]["id"] == agent["id"]
    assert invoke(desk, "observe", stage["id"])["reason"] == "MANUAL_STAGE_NOT_MONITORED"
    run_cycle(desk.factory, desk.candidate_service)
    assert invoke(desk, "pending", stage["id"]) == []
    assert len(desk.app.list()) == 1 and desk.app.list()[0]["draft"]["source"] == "AGENT_PROPOSAL"
    assert desk.sdk.broker.attempts == []


def test_concurrent_confirm_admits_single_native_chain(desk):
    stage = desk.client.post("/desk/draft", draft_body()).body
    entered, release = Event(), Event()
    original = desk.state["exchange"]
    def exchange(value):
        if value.get("request", {}).get("argv", [None])[0] == "draft":
            entered.set()
            assert release.wait(5)
        return original(value)
    desk.state["exchange"] = exchange
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(confirm, desk.client, stage)
        try:
            assert entered.wait(5)
            second = confirm(desk.client, stage)
            assert second.status_code == 200 and second.body["lifecycle"] == "SUBMITTING"
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
    assert len(desk.sdk.broker.attempts) == 1


def test_concurrent_local_creation_same_identity_has_one_revision(desk):
    def create():
        with desk.factory() as db:
            return CandidateService(db, control=lambda v: pytest.fail("local Native IO"),
                clock=lambda: NOW).create(draft_body(), owner_id="MCP", manual_stage=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert results[0] == results[1] and results[0]["revision"] == 1
    with desk.factory() as db:
        assert db.execute(text("SELECT count(*) FROM research_candidate_revision")).scalar_one() == 1
    assert desk.calls == []


def test_edit_during_executor_status_check_invalidates_old_modal(desk):
    stage = desk.client.post("/desk/draft", draft_body()).body
    original = desk.state["exchange"]
    def exchange(value):
        assert value == {"operation": "status"}
        invoke(desk, "change", stage["id"], expected_revision=stage["revision"],
            operation="revise", raw=draft_body(price="51"))
        return original(value)
    desk.state["exchange"] = exchange
    assert confirm(desk.client, stage).status_code == 409
    current = desk.client.get("/desk/staged/" + stage["id"]).body
    assert current["raw"]["price"] == "51" and current["lifecycle"] == "STAGED"
    assert desk.app.list() == [] and desk.sdk.broker.attempts == []


def test_interrupted_sender_leaves_durable_submitting_latch(desk):
    class Interrupted(BaseException):
        pass
    stage = desk.client.post("/desk/draft", draft_body()).body
    original = desk.state["exchange"]
    def exchange(value):
        result = original(value)
        if value.get("request", {}).get("argv", [None])[0] == "draft":
            raise Interrupted()
        return result
    desk.state["exchange"] = exchange
    with pytest.raises(Interrupted), desk.factory() as db:
        CandidateService(db, control=desk.control, clock=lambda: NOW).send_staged(stage["id"],
            expected_revision=stage["revision"], expected_digest=stage["digest"])
    value = desk.client.get("/desk/staged/" + stage["id"]).body
    assert value["lifecycle"] == "SUBMITTING"
    assert value["manual_stage"]["submission"]["native_intent_id"]
    calls = list(desk.calls)
    assert confirm(desk.client, stage).body == value and desk.calls == calls
    assert len(desk.app.list()) == 1 and desk.sdk.broker.attempts == []
