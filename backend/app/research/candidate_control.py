"""Fixed OMI control CLI -> existing local named pipe. No native imports/login."""
import json
from pathlib import Path
import subprocess
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]


class ControlUnavailable(RuntimeError):
    def __init__(self, code, *, error_type=None):
        super().__init__(code)
        self.error_type = error_type or type(self).__name__

    def detail(self):
        return {"code": str(self), "error_type": self.error_type, "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}


class SubmissionNotAttempted(ControlUnavailable):
    """This exact request terminated before any Native command was invoked."""
    def __init__(self, cause, identity, pin):
        super().__init__(str(cause), error_type=cause.error_type)
        self.attempt = {"contract": "omi.execution.submission-attempt.v1", "outcome": "NOT_ATTEMPTED",
            "candidate_id": identity, "candidate_revision": pin["revision"], "candidate_digest": pin["digest"],
            "phase": "READINESS", "native_command_started": False}

    def detail(self):
        return {**super().detail(), "retry_policy": "EXPLICIT_RETRY_SAME_STAGE", "submission_attempt": self.attempt}


class ControlRejected(ControlUnavailable):
    """Known native validation rejection, distinct from a lost IPC response."""


def request_control(value):
    arguments = [str(ROOT / ".venv-kgi/Scripts/python.exe"), "-B", "-m", "execution_runtime.control", value["operation"]]
    if value["operation"] == "command":
        arguments += ["--request-json", json.dumps(value["request"], ensure_ascii=True, allow_nan=False)]
    try:
        # Control uses argv and the named pipe; never inherit the Backend's
        # launcher-owned stdin, which can block Windows Python initialization.
        result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=65,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        response = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN", error_type=type(exc).__name__) from None
    if type(response) is not dict or type(response.get("ok")) is not bool:
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
    if not response.get("ok"):
        kind = response.get("error_type")
        error_type = kind if kind in {"ExecutionRejected", "FileNotFoundError", "PermissionError",
            "TimeoutError", "ConnectionError", "OSError", "EOFError", "ValueError", "RuntimeError"} else "ControlError"
        code = response.get("code")
        if not isinstance(code, str) or not code:
            # Legacy control clients reported local timeout/identity failures as
            # ExecutionRejected without a Native code. Never infer rejection.
            code = "EXECUTOR_RESPONSE_UNKNOWN" if kind == "ExecutionRejected" else "EXECUTOR_UNAVAILABLE"
        if kind == "ExecutionRejected" and code not in {"EXECUTOR_RESPONSE_UNKNOWN", "EXECUTOR_UNAVAILABLE"}:
            raise ControlRejected(code, error_type=error_type)
        raise ControlUnavailable(code, error_type=error_type)
    if "result" not in response:
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
    return response["result"]


def command(control, argv):
    response = control({"operation": "command", "request": {"id": str(uuid4()), "argv": argv}})
    if not response.get("ok"):
        raise ControlRejected(response.get("error", "EXECUTOR_COMMAND_FAILED"))
    return response["result"]
