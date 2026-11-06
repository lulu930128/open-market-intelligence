"""Real app.main ASGI middleware/routes, isolated DB + Fake Native owner only."""
import asyncio
from threading import Event, Thread
import time
import json
from types import SimpleNamespace

import pytest

from app.research.candidate_control import ControlUnavailable
from app.research.candidate_service import CandidateService
from execution_runtime import control as native_control, service as native_service
from execution_runtime.tests.fake_sdk import NOW
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.application import ExecutionApplication
from execution_runtime.tests.test_connection_lifecycle import eventually
from test_mcp_manual_desk import desk, draft_body, invoke


@pytest.fixture
def pipeline(desk, monkeypatch):
    # Import actual composition; do not enter lifespan (no runtime startup).
    from app.main import app
    from app.db.session import get_db
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: None)
    def database():
        with desk.factory() as db:
            yield db
    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    def request(method, path, body=None):
        async def run():
            messages, delivered, finished = [], False, asyncio.Event()
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": json.dumps(body).encode() if body else b"", "more_body": False}
                await finished.wait()
                return {"type": "http.disconnect"}
            async def send(message):
                messages.append(message)
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    finished.set()
            await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": "/api/research/conditional-candidates" + path,
                "raw_path": ("/api/research/conditional-candidates" + path).encode(), "query_string": b"",
                "headers": [(b"content-type", b"application/json"), (b"x-request-id", b"synthetic-envelope-test")],
                "client": ("127.0.0.1", 1), "server": ("fixture", 80)}, receive, send)
            text = b"".join(m.get("body", b"") for m in messages).decode()
            return SimpleNamespace(status_code=messages[0]["status"], text=text, json=lambda: json.loads(text),
                headers={k.decode(): v.decode() for k, v in messages[0]["headers"]})
        return asyncio.run(run())
    return request


def selection(stage):
    return {"expected_revision": stage["revision"], "expected_digest": stage["digest"]}


@pytest.mark.parametrize("response", [
    {"ok": False, "error_type": "ExecutionRejected"},  # Legacy CLI timeout has no Native code.
    {"ok": False, "error_type": "ExecutionRejected", "code": "EXECUTOR_RESPONSE_UNKNOWN"},
    {"ok": False, "error_type": "TimeoutError", "code": "EXECUTOR_RESPONSE_UNKNOWN"},
    {"ok": False, "error_type": "EOFError", "code": "EXECUTOR_RESPONSE_UNKNOWN"},
])
def test_backend_local_control_failure_is_not_known_native_rejection(monkeypatch, response):
    from app.research import candidate_control
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(response))
    monkeypatch.setattr(candidate_control.subprocess, "run", run)
    with pytest.raises(ControlUnavailable) as failed:
        candidate_control.request_control({"operation": "status"})
    assert not isinstance(failed.value, candidate_control.ControlRejected)
    assert str(failed.value) == "EXECUTOR_RESPONSE_UNKNOWN"
    assert failed.value.detail()["retry_policy"] == "CHECK_STATUS_DO_NOT_RESEND"
    assert len(calls) == 1


def test_backend_preserves_explicit_native_rejection(monkeypatch):
    from app.research import candidate_control
    response = {"ok": False, "error_type": "ExecutionRejected", "code": "EXECUTOR_BUSY"}
    monkeypatch.setattr(candidate_control.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(response)))
    with pytest.raises(candidate_control.ControlRejected, match="EXECUTOR_BUSY"):
        candidate_control.request_control({"operation": "readback"})


def test_actual_asgi_not_attempted_envelope_and_exact_pin_without_revision_write(desk, pipeline):
    stage = pipeline("POST", "/desk/draft", draft_body()).json()
    def missing(request):
        assert request == {"operation": "status"}
        raise ControlUnavailable("EXECUTOR_UNAVAILABLE", error_type="FileNotFoundError")
    desk.state["exchange"] = missing
    result = pipeline("POST", "/desk/staged/" + stage["id"] + "/confirm", selection(stage))
    assert result.status_code == 503
    assert result.headers["x-request-id"] == "synthetic-envelope-test"
    assert result.json() == {"error": {"code": "EXECUTOR_UNAVAILABLE", "message": "Request failed.",
        "request_id": "synthetic-envelope-test", "detail": {"error_type": "FileNotFoundError",
        "retry_policy": "EXPLICIT_RETRY_SAME_STAGE", "submission_attempt": {
            "contract": "omi.execution.submission-attempt.v1", "outcome": "NOT_ATTEMPTED",
            "candidate_id": stage["id"], "candidate_revision": stage["revision"], "candidate_digest": stage["digest"],
            "phase": "READINESS", "native_command_started": False}}}}
    assert pipeline("GET", "/desk/staged/" + stage["id"]).json() == stage
    assert desk.sdk.broker.attempts == [] and desk.app.list() == []


@pytest.mark.parametrize("race", ["revise", "claim"])
def test_status_failure_after_stage_changed_never_emits_not_attempted(desk, pipeline, race):
    stage = pipeline("POST", "/desk/draft", draft_body()).json()
    original = desk.state["exchange"]
    def exchange(request):
        desk.state["exchange"] = original
        if race == "revise":
            invoke(desk, "change", stage["id"], expected_revision=1, operation="revise", raw=draft_body(price="51"))
        else:
            # A second explicit request owns the chain before the first status fails.
            with desk.factory() as db:
                CandidateService(db, control=desk.control, clock=lambda: NOW).send_staged(stage["id"], **selection(stage))
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
    desk.state["exchange"] = exchange
    response = pipeline("POST", "/desk/staged/" + stage["id"] + "/confirm", selection(stage))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_STAGE_SELECTION"
    assert "NOT_ATTEMPTED" not in response.text
    assert len(desk.sdk.broker.attempts) == (1 if race == "claim" else 0)


@pytest.mark.parametrize("phase", ["draft", "preview", "confirm"])
def test_real_pipe_staged_chain_waits_for_periodic_health_read_without_busy_latch(desk, pipeline, tmp_path, monkeypatch, phase):
    from uuid import uuid4
    address = r"\\.\pipe\omi-staged-health-fixture-" + uuid4().hex
    monkeypatch.setattr(native_service, "ADDRESS", address)
    monkeypatch.setattr(native_control, "ADDRESS", address)
    desk.runtime.close()
    runtime = ExecutionRuntime(desk.runtime.path, account_id=desk.runtime.account_id, trade_date=desk.runtime.trade_date,
        session_factory=desk.sdk.binding, clock=lambda: NOW, strategy_effects=False)
    runtime.start_managed(retry_base=0.03, retry_cap=0.1, heartbeat=0.15)
    eventually(lambda: runtime.connection_status()["ready"])
    server = Thread(target=native_service.serve_runtime, args=(runtime, ExecutionApplication(runtime), True, tmp_path), daemon=True)
    server.start()
    deadline = time.monotonic() + 5
    while not (tmp_path / "process-status.json").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    # The canonical health loop is exercised at a deterministic point between
    # Backend's status check and the selected stage command, through the real pipe.
    original_report = desk.sdk.Account.OrderReport
    entered, release = Event(), Event()
    def slow_report():
        entered.set()
        assert release.wait(5)
        return original_report()
    def exchange(value):
        if value.get("request", {}).get("argv", [None])[0] == phase:
            desk.sdk.Account.OrderReport = slow_report
            assert entered.wait(2)
            view = native_control.request_control({"operation": "status"})["result"]
            assert view["connection"]["busy"] is not None
            Thread(target=lambda: (time.sleep(0.1), release.set()), daemon=True).start()
        response = native_control.request_control(value)
        assert response["ok"], response
        return response["result"]
    desk.state["exchange"] = exchange
    try:
        stage = pipeline("POST", "/desk/draft", draft_body()).json()
        response = pipeline("POST", "/desk/staged/" + stage["id"] + "/confirm", selection(stage))
        assert response.status_code == 200, response.text
        assert response.json()["lifecycle"] == "SUBMITTED"
        assert len(desk.sdk.broker.attempts) == 1
        # Repeating the exact stage returns the original receipt, no second pipe effect.
        assert pipeline("POST", "/desk/staged/" + stage["id"] + "/confirm", selection(stage)).json() == response.json()
        assert len(desk.sdk.broker.attempts) == 1
    finally:
        release.set()
        native_control.request_control({"operation": "stop"})
        server.join(5)
        runtime.close()
        assert not server.is_alive()


def test_real_pipe_timeout_after_broker_acceptance_stays_unknown_without_resend(desk, pipeline, tmp_path, monkeypatch):
    from uuid import uuid4
    from app.research import candidate_control
    address = r"\\.\pipe\omi-lost-response-fixture-" + uuid4().hex
    monkeypatch.setattr(native_service, "ADDRESS", address)
    monkeypatch.setattr(native_control, "ADDRESS", address)
    actual_request = native_control.request_control
    def bounded_request(value):
        confirm = value.get("request", {}).get("argv", [None])[0] == "confirm"
        return actual_request(value, timeout=0.1 if confirm else 3)
    monkeypatch.setattr(native_control, "request_control", bounded_request)
    def cli(argv, **kwargs):
        # Exercise the real CLI envelope and Backend decoder, substituting only
        # the process boundary so this fixture cannot reach the production pipe.
        output = []
        with monkeypatch.context() as local:
            local.setattr(native_control, "print", output.append, raising=False)
            code = native_control.main(argv[4:])
        return SimpleNamespace(stdout="\n".join(output), returncode=code)
    monkeypatch.setattr(candidate_control.subprocess, "run", cli)
    desk.state["exchange"] = candidate_control.request_control
    entered, release = Event(), Event()
    def after_create():
        entered.set()  # Fake broker already accepted before the response is lost.
        assert release.wait(5)
    desk.sdk.after_create = after_create
    server = Thread(target=native_service.serve_runtime, args=(desk.runtime, desk.app, True, tmp_path), daemon=True)
    server.start()
    try:
        eventually(lambda: (tmp_path / "process-status.json").exists())
        stage = pipeline("POST", "/desk/draft", draft_body()).json()
        path = "/desk/staged/" + stage["id"] + "/confirm"
        response = pipeline("POST", path, selection(stage))
        assert entered.is_set() and len(desk.sdk.broker.attempts) == 1
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "EXECUTOR_RESPONSE_UNKNOWN"
        assert response.json()["error"]["detail"]["retry_policy"] == "CHECK_STATUS_DO_NOT_RESEND"
        assert "submission_attempt" not in response.json()["error"]["detail"]
        current = pipeline("GET", "/desk/staged/" + stage["id"]).json()
        assert current["lifecycle"] == "SUBMISSION_UNKNOWN"
        assert current["manual_stage"]["submission"]["pin"] == {"revision": stage["revision"], "digest": stage["digest"]}
        release.set()
        eventually(lambda: desk.runtime.connection_status()["busy"] is None)
        calls = list(desk.calls)
        assert pipeline("POST", path, selection(stage)).json() == current
        assert desk.calls == calls and len(desk.sdk.broker.attempts) == 1
        assert actual_request({"operation": "status"})["ok"]  # Client timeout did not kill the service.
    finally:
        release.set()
        eventually(lambda: desk.runtime.connection_status()["busy"] is None)
        actual_request({"operation": "stop"})
        server.join(5)
        assert not server.is_alive()
