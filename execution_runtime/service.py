"""Thin persistent transport over the existing Runtime, not a second manager."""

from datetime import datetime, timezone
import hashlib
import json
from multiprocessing.connection import Listener
import os
import sys
import time
from threading import BoundedSemaphore, Event, Lock, Thread

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
            "strategy_effects": runtime.strategy_effects, "callback_registered": runtime.session.order_callback_registered,
            "callback_error": runtime.callback_error, "strategy_error": runtime.strategy_error,
            "broker_session": "CONNECTED" if runtime.session.connected else "DISCONNECTED",
            "callback_counts": dict(runtime.session.callback_counts),
            "price_source": runtime.price_source_status(),
            "cash_inventory": runtime.cash_inventory_status(),
            "connection": runtime.connection_status(),
            "observed_at": datetime.now(timezone.utc).isoformat()}


def record_state(state_path, value):
    # Sanitized process receipt only. All trading facts remain in Runtime/Journal.
    state_path.mkdir(parents=True, exist_ok=True)
    temporary = state_path / "process-status.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    replace_receipt(temporary, state_path / "process-status.json")


def replace_receipt(temporary, target):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as W
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.ReplaceFileW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.LPVOID, W.LPVOID]
        kernel.ReplaceFileW.restype = W.BOOL
        # MoveFileEx (os.replace) rejects an existing open destination even with
        # shared deletion. ReplaceFile preserves atomicity for our shared readers.
        deadline = time.monotonic() + 0.5
        while True:
            if kernel.ReplaceFileW(os.path.abspath(target), os.path.abspath(temporary), None, 0, None, None):
                return
            error = ctypes.get_last_error()
            if error == 2:  # Only a first publication has no target to replace.
                break
            # ERROR_UNABLE_TO_REMOVE_REPLACED (1175) leaves both original names
            # intact, so retry the same publication as for a sharing violation.
            # Access denial and partial-move failures must still fail closed.
            if error not in {32, 1175} or time.monotonic() >= deadline:
                raise ctypes.WinError(error)
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    temporary.replace(target)


def record_startup(state_path, startup_id, value):
    require(len(startup_id) == 32 and all(c in "0123456789abcdef" for c in startup_id), "INVALID_STARTUP_ID")
    state_path.mkdir(parents=True, exist_ok=True)
    target = state_path / ("startup-" + startup_id + ".json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({**value, "startup_id": startup_id}, ensure_ascii=True), encoding="utf-8")
    replace_receipt(temporary, target)


def handle(runtime, application, request, *, simulation, loaded):
    require(type(request) is dict, "INVALID_CONTROL_REQUEST")
    operation = request.get("operation")
    if operation == "status" and set(request) == {"operation"}:
        return receipt(runtime, simulation, loaded), False
    if operation == "stop" and set(request) == {"operation"}:
        runtime.request_offline(reason="OPERATOR_STOP")
        return {"status": "STOPPING", "pid": os.getpid()}, True
    # Commands wait behind an admitted health/read operation. A benign heartbeat
    # racing Backend readiness must not become a terminal staged rejection.
    # A caller timeout does NOT abort this lane or prove zero external effects.
    with runtime.operation(str(operation), blocking=operation in {"command", "us-order", "us-status", "us-cancel"}):
        require(runtime.connection_status()["desired"] == "ONLINE", "EXECUTOR_OFFLINE")
        require(runtime._started, "EXECUTOR_NOT_READY")
        return _command(runtime, application, request, operation)


def _command(runtime, application, request, operation):
    if operation == "us-status" and set(request) == {"operation"}:
        return application.manual_us_status(), False
    if operation == "us-order" and set(request) == {"operation", "request_id", "symbol", "action", "quantity", "price", "settlement_mode"}:
        return application.manual_us_order(**{k: v for k, v in request.items() if k != "operation"}), False
    if operation in {"us-status", "us-cancel"} and set(request) == {"operation", "request_id"}:
        method = application.manual_us_status if operation == "us-status" else application.manual_us_cancel
        return method(request["request_id"]), False
    if operation == "us-probe" and set(request) == {"operation", "symbol"}:
        return runtime.probe_us(request["symbol"]), False
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


def serve_runtime(runtime, application, simulation, state_path, *, startup=None):
    loaded = source_identity()
    stopping = Event()
    slots = BoundedSemaphore(8)
    effects = BoundedSemaphore(4)  # Leave room for status/stop while SDK calls wait.
    startup_lock = Lock()

    def publish(value, *, stop=False):
        # One monotone receipt writer: READY can never overwrite an accepted stop.
        with startup_lock:
            if stopping.is_set() and not stop:
                return
            if startup is not None:
                startup(value)
            if stop:
                stopping.set()  # Only after the durable OFFLINE receipt.

    def respond(connection):
        effect_slot = False
        with connection:
            try:
                authenticate(connection, server=True)
                require(connection.poll(5), "CONTROL_READ_TIMEOUT")
                request = json_value(connection.recv_bytes(MAX_LINE).decode("utf-8"))
                if isinstance(request, dict) and request.get("operation") not in {"status", "stop"}:
                    effect_slot = effects.acquire(blocking=False)
                    require(effect_slot, "EXECUTOR_BUSY")
                result, stop = handle(runtime, application, request, simulation=simulation, loaded=loaded)
                if stop:
                    publish({"status": "STOPPING", "pid": os.getpid(), "reason": "OPERATOR_STOP",
                             "desired": "OFFLINE", "loaded_source": loaded}, stop=True)
                response = {"ok": True, "result": result}
            except Exception as exc:
                response = {"ok": False, "error_type": type(exc).__name__,
                            "code": exc.code if isinstance(exc, ExecutionRejected) else "CONTROL_FAILED",
                            "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}
            try:
                connection.send_bytes(json.dumps(response, ensure_ascii=True).encode("utf-8"))
            except (OSError, EOFError):
                pass  # A lost response never rolls back/replays a Runtime claim.
            finally:
                if effect_slot:
                    effects.release()
                slots.release()

    with Listener(ADDRESS, family="AF_PIPE", authkey=None) as listener:
        record_state(state_path, receipt(runtime, simulation, loaded))
        publish({"status": "STARTING", "pid": os.getpid(), "loaded_source": loaded})
        def accept():
            while True:
                try:
                    connection = listener.accept()
                except (OSError, EOFError, TypeError):
                    return
                if not slots.acquire(blocking=False):
                    connection.close()
                    continue
                Thread(target=respond, args=(connection,), name="execution-control", daemon=True).start()
        Thread(target=accept, name="execution-pipe", daemon=True).start()
        announced = False
        while True:
            state = runtime.connection_status()
            if startup is not None and not announced and state["actual"] in {"ONLINE", "BLOCKED"} and state["busy"] is None:
                publish({"status": "READY" if state["ready"] else "BLOCKED", "pid": os.getpid(),
                         "loaded_source": loaded, "code": state["last_error"], "connection": state})
                announced = True
            # Leave the pipe observable while an uncancellable SDK call finishes.
            if stopping.is_set() and state["busy"] is None and (not runtime._managed or state["actual"] == "OFFLINE"):
                break
            time.sleep(0.1)
        record_state(state_path, {"status": "STOPPING", "pid": os.getpid(), "loaded_source": loaded})
