"""Thin persistent transport over the existing Runtime, not a second manager."""

from datetime import datetime, timezone
import hashlib
import json
from multiprocessing.connection import Listener
import os
import sys

from execution.validation import require
from execution.contracts import ExecutionRejected
from .cli import json_value
from .headless import MAX_LINE, dispatch, public_result
from .ipc import ADDRESS, ROOT, authenticate


def source_identity():
    paths = sorted((ROOT / "execution_runtime").glob("*.py"))
    paths += [ROOT / "execution" / name for name in ("contracts.py", "order_reducer.py", "validation.py")]
    body = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def receipt(runtime, simulation, loaded):
    return {"status": "RUNNING", "pid": os.getpid(), "interpreter": sys.executable,
            "project_root": str(ROOT), "loaded_source": loaded,
            "source_matches": source_identity() == loaded,
            "environment": "SIMULATION" if simulation else "PRODUCTION",
            "trade_date": runtime.trade_date, "session_date_matches": runtime.session.date_matches(),
            "strategy_effects": runtime.strategy_effects, "callback_registered": True,
            "callback_error": runtime.callback_error, "strategy_error": runtime.strategy_error,
            "broker_session": "CONNECTED" if runtime.session.connected else "DISCONNECTED",
            "callback_counts": dict(runtime.session.callback_counts),
            "price_source": runtime.price_source_status(),
            "cash_inventory": runtime.cash_inventory_status(),
            "observed_at": datetime.now(timezone.utc).isoformat()}


def record_state(state_path, value):
    # Sanitized process receipt only. All trading facts remain in Runtime/Journal.
    state_path.mkdir(parents=True, exist_ok=True)
    temporary = state_path / "process-status.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    temporary.replace(state_path / "process-status.json")


def handle(runtime, application, request, *, simulation, loaded):
    require(type(request) is dict, "INVALID_CONTROL_REQUEST")
    operation = request.get("operation")
    if operation == "status" and set(request) == {"operation"}:
        return receipt(runtime, simulation, loaded), False
    if operation == "stop" and set(request) == {"operation"}:
        return {"status": "STOPPING", "pid": os.getpid()}, True
    if operation == "query" and set(request) == {"operation"}:
        result = application.query()
        return {"status": result["status"], "fill_history_complete": result.get("fill_history_complete", False),
                "callback_counts": dict(runtime.session.callback_counts), "order_effects": "NOT_REQUESTED"}, False
    if operation == "readback" and set(request) == {"operation"}:
        return public_result(application.readback()), False
    if operation == "reconnect" and set(request) == {"operation"}:
        result = runtime.reconnect()
        return {"status": result["status"], "resend": False}, False
    require(operation == "command" and set(request) == {"operation", "request"}, "INVALID_CONTROL_REQUEST")
    return dispatch(application, request["request"], selected_account=runtime.account_id), False


def serve_runtime(runtime, application, simulation, state_path):
    loaded = source_identity()
    with Listener(ADDRESS, family="AF_PIPE", authkey=None) as listener:
        record_state(state_path, receipt(runtime, simulation, loaded))
        stopping = False
        while not stopping:
            with listener.accept() as connection:
                try:
                    authenticate(connection, server=True)
                    require(connection.poll(5), "CONTROL_READ_TIMEOUT")
                    request = json_value(connection.recv_bytes(MAX_LINE).decode("utf-8"))
                    result, stopping = handle(runtime, application, request, simulation=simulation, loaded=loaded)
                    response = {"ok": True, "result": result}
                except Exception as exc:
                    response = {"ok": False, "error_type": type(exc).__name__,
                                "code": exc.code if isinstance(exc, ExecutionRejected) else "CONTROL_FAILED",
                                "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}
                try:
                    connection.send_bytes(json.dumps(response, ensure_ascii=True).encode("utf-8"))
                except (OSError, EOFError):
                    pass  # A lost response never rolls back/replays a Runtime claim.
        record_state(state_path, {"status": "STOPPING", "pid": os.getpid(), "loaded_source": loaded})
