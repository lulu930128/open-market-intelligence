"""Fixed OMI control CLI -> existing local named pipe. No native imports/login."""
import json
from pathlib import Path
import subprocess
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]


class ControlUnavailable(RuntimeError):
    pass


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
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN") from None
    if type(response) is not dict or type(response.get("ok")) is not bool:
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
    if not response.get("ok"):
        if response.get("error_type") == "ExecutionRejected":
            raise ControlRejected(response.get("code", "EXECUTOR_COMMAND_REJECTED"))
        raise ControlUnavailable(response.get("code", "EXECUTOR_UNAVAILABLE"))
    if "result" not in response:
        raise ControlUnavailable("EXECUTOR_RESPONSE_UNKNOWN")
    return response["result"]


def command(control, argv):
    response = control({"operation": "command", "request": {"id": str(uuid4()), "argv": argv}})
    if not response.get("ok"):
        raise ControlRejected(response.get("error", "EXECUTOR_COMMAND_FAILED"))
    return response["result"]
