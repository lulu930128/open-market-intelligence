"""Explicit native composition root; never imported by ordinary OMI services."""

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import json
import logging
import os
from pathlib import Path
import struct
import sys

from execution.validation import require
from execution.contracts import ExecutionRejected
from .application import ExecutionApplication
from .headless import serve
from .native import NativeSessionFactory, NativeSettings, load_sdk
from .runtime import ExecutionRuntime
from .storage import OwnerLease


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "execution-runtime"


@contextmanager
def private_sdk_output(*, process_lifetime=False):
    """Dedicated process only: keep vendor prints out of the JSON protocol.

    Duplicate the protocol output before redirecting fd 1/2 (including C prints).
    This is not a promise about the vendor's native private file logging.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    old_level = logging.root.manager.disable
    saved = [os.dup(1), os.dup(2)]
    with os.fdopen(os.dup(saved[0]), "w", encoding="utf-8", buffering=1) as protocol:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            try:
                os.dup2(sink.fileno(), 1)
                os.dup2(sink.fileno(), 2)
                logging.disable(sys.maxsize)
                with redirect_stdout(sink), redirect_stderr(sink):
                    yield protocol
            finally:
                for target, descriptor in zip((1, 2), saved):
                    if not process_lifetime:
                        os.dup2(descriptor, target)
                    os.close(descriptor)
                if not process_lifetime:
                    logging.disable(old_level)
                else:
                    # Native worker threads/destructors can print after logout
                    # and after Python atexit. Keep OS descriptors suppressed
                    # until process teardown, not just until context exit.
                    sys.stdout = open(os.devnull, "w", encoding="utf-8")
                    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def emit(output, value):
    output.write(json.dumps(value, ensure_ascii=True) + "\n")
    output.flush()


def native_run(output, *, strategy_effects=False, probe=False, persistent=False):
    # A fixed OMI execution lease is acquired BEFORE login/account discovery.
    # A second invocation cannot evade ownership with another journal or mode.
    lease = OwnerLease(STATE / "native-session")
    lease.acquire()
    factory, runtime = None, None
    try:
        settings = NativeSettings.from_environment()
        factory = NativeSessionFactory(settings, owner_lease=lease)
        binding = factory.prepare()
        journal = STATE / ("simulation.sqlite" if settings.simulation else "production.sqlite")
        runtime = ExecutionRuntime(journal, account_id=binding.account_id, trade_date=binding.trade_date,
                                   session_factory=factory, strategy_effects=strategy_effects, native_prices=True)
        startup = runtime.start()
        app = ExecutionApplication(runtime)
        emit(output, {"event": "STARTED", "environment": "SIMULATION" if settings.simulation else "PRODUCTION",
                      "account": "SELECTED", "trade_date": binding.trade_date,
                      "query_status": startup["status"], "strategy_effects": strategy_effects,
                      "broker_session": "CONNECTED", "live_order": "UNVERIFIED" if strategy_effects else "NOT_SENT_BY_STARTUP",
                      "protocol": "omi.execution.stdin.v1"})
        if probe:
            result = app.query()
            emit(output, {"event": "READONLY_PROBE", "query_status": result["status"],
                          "callback_registered": True, "fill_history_complete": False,
                          "order_effects": "NOT_SENT", "account_selected": True})
        elif persistent:
            from .service import serve_runtime
            serve_runtime(runtime, app, settings.simulation, STATE)
        else:
            serve(app, sys.stdin, output, selected_account=binding.account_id)
    finally:
        # Failed close must not advertise a release/reconnect or open another session.
        if runtime is not None:
            runtime.close()
        if factory is not None:
            factory.close_unclaimed()
        lease.release()
        if persistent:
            from .service import record_state
            record_state(STATE, {"status": "STOPPED", "pid": os.getpid(), "owner_released": True})


def main(argv=None):
    parser = argparse.ArgumentParser(description="OMI native execution; no default login. See execution_runtime/README.md")
    routes = parser.add_subparsers(dest="route")
    routes.add_parser("native-check", help="Import SDK only; never log in or read credentials")
    native = routes.add_parser("native", help="Persistent JSON-lines application on stdin/stdout")
    native.add_argument("--connect", action="store_true", help="Explicitly log in using KGI_SUPERPY_* environment")
    mode = native.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="Login, read reports, logout; no strategy effects or orders")
    mode.add_argument("--persistent", action="store_true", help="Same-user Windows pipe; independent of controller lifetime")
    native.add_argument("--enable-strategy-effects", action="store_true",
                        help="Explicitly resume existing CASH long strategy effects, including cancel/exit")
    args = parser.parse_args(argv)
    if args.route is None:
        parser.print_help()
        return 0
    if args.route == "native" and not args.connect:
        parser.error("native requires --connect; no login attempted")
    if args.route == "native" and args.probe and args.enable_strategy_effects:
        parser.error("probe forbids strategy effects")
    # Enforce the OMI-local interpreter, never fall back to another project/SDK.
    expected = ROOT / ".venv-kgi" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != expected.resolve():
        emit(sys.stdout, {"status": "BLOCKED", "error": "USE_OMI_VENV_KGI", "broker_session": "NOT_STARTED"})
        return 2
    with private_sdk_output(process_lifetime=True) as output:
        try:
            if args.route == "native-check":
                # Drop inherited broker credentials without inspecting their values.
                for name in tuple(os.environ):
                    if name.startswith("KGI_SUPERPY_"):
                        del os.environ[name]
                def no_external_effect(event, arguments):
                    if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system"}:
                        raise RuntimeError("IMPORT_CHECK_EXTERNAL_EFFECT_BLOCKED")
                sys.addaudithook(no_external_effect)
                sdk = load_sdk()
                require(callable(getattr(sdk, "login", None)), "KGI_LOGIN_INTERFACE_UNAVAILABLE")
                emit(output, {"native_import": "PASS", "python": ".".join(map(str, sys.version_info[:3])),
                              "bits": struct.calcsize("P") * 8, "broker_session": "NOT_STARTED", "live_order": "NOT_SENT"})
            else:
                native_run(output, strategy_effects=args.enable_strategy_effects,
                           probe=args.probe, persistent=args.persistent)
        except KeyboardInterrupt:
            emit(output, {"status": "STOPPED", "reason": "INTERRUPTED_CHECK_STATUS_BEFORE_RETRY"})
            return 130
        except BaseException as exc:
            # Never print SDK exception strings/tracebacks, credentials or accounts.
            emit(output, {"status": "BLOCKED", "stage": args.route, "error_type": type(exc).__name__,
                          "code": exc.code if isinstance(exc, ExecutionRejected) else "NATIVE_OPERATION_FAILED",
                          "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"})
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
