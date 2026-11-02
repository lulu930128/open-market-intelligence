"""Persistent stdin protocol. No listener, SDK, credentials, or persistence owner."""

import json
import re

from execution.validation import identifier, require
from .cli import json_value, run


MAX_LINE = 131072


def public_result(value):
    """Keep actionable receipts, but never export account IDs or private journal rows."""
    if isinstance(value, dict):
        return {k: ("SELECTED" if k == "account_id" else public_result(v))
                for k, v in value.items() if k not in {"audit", "execution_audit", "diagnostics"}}
    if isinstance(value, (list, tuple)):
        return [public_result(v) for v in value]
    return value


def dispatch(application, request, *, selected_account):
    require(type(request) is dict and set(request) == {"id", "argv"}, "INVALID_PROTOCOL_REQUEST")
    identifier(request["id"])
    argv = request["argv"]
    require(type(argv) is list and bool(argv) and all(type(v) is str for v in argv), "INVALID_PROTOCOL_ARGV")
    require(not any(v in {"--help", "-h"} for v in argv), "HELP_USE_ENTRYPOINT")
    result = run(application, argv, selected_account=selected_account)
    return {"id": request["id"], "ok": True, "result": public_result(result)}


def serve(application, incoming, outgoing, *, selected_account):
    """Each line is one explicit command. EOF closes; malformed input never replays."""
    while True:
        line = incoming.readline(MAX_LINE + 1)
        if not line:
            return
        request_id = None
        try:
            # Terminate oversized streams rather than interpreting their suffix.
            require(len(line) <= MAX_LINE, "PROTOCOL_LINE_TOO_LARGE")
            request = json_value(line)
            if type(request) is dict:
                identifier(request.get("id"))
                request_id = request["id"]
            response = dispatch(application, request, selected_account=selected_account)
        except (Exception, SystemExit) as exc:
            message = str(exc)
            code = message if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z][A-Z_]{2,80}", message) else "COMMAND_FAILED"
            response = {"id": request_id, "ok": False, "error": code,
                        "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}
        outgoing.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n")
        outgoing.flush()
        if len(line) > MAX_LINE:
            return
