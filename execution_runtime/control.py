"""One-shot local controller; closing it never closes the native service."""

import argparse
import json
from multiprocessing.connection import Client

from execution.validation import require
from .cli import json_value
from .headless import MAX_LINE
from .ipc import ADDRESS, authenticate


def request_control(value, *, expected_pid=None, timeout=60):
    encoded = json.dumps(value, ensure_ascii=True).encode("utf-8")
    require(len(encoded) <= MAX_LINE, "CONTROL_REQUEST_TOO_LARGE")
    with Client(ADDRESS, family="AF_PIPE", authkey=None) as connection:
        peer = authenticate(connection, server=False)
        require(expected_pid is None or peer == expected_pid, "CONTROL_OWNER_MISMATCH")
        connection.send_bytes(encoded)
        if not connection.poll(timeout):
            # A sent command can still finish in Native after this client exits.
            # This is not an ExecutionRejected response from that owner.
            raise TimeoutError("CONTROL_RESPONSE_UNKNOWN_DO_NOT_RESEND")
        return json_value(connection.recv_bytes(1024 * 1024).decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Control the same-user OMI native runtime; never auto-start/login")
    parser.add_argument("operation", choices=("status", "query", "readback", "reconnect", "stop", "command",
                                               "us-probe", "us-order", "us-status", "us-cancel"))
    parser.add_argument("--request-json", help="For command: existing id/argv JSON; never credentials")
    parser.add_argument("--symbol", help="Broker symbol for us-probe or us-order")
    parser.add_argument("--request-id", help="Stable user order ID; reuse it to query, cancel or recover a response")
    parser.add_argument("--action", choices=("Buy", "Sell"))
    parser.add_argument("--quantity", type=int, help="Whole shares")
    parser.add_argument("--price", help="USD limit price")
    parser.add_argument("--settlement", choices=("TWD", "MUT"), help="TWD or foreign-currency settlement")
    args = parser.parse_args(argv)
    if args.operation == "us-probe" and not args.symbol:
        parser.error("us-probe requires --symbol")
    if args.operation == "us-probe" and args.request_json is not None:
        parser.error("us-probe does not accept command payloads")
    if args.symbol is not None and args.operation not in {"us-probe", "us-order"}:
        parser.error("--symbol is only accepted for us-probe or us-order")
    manual = args.operation in {"us-order", "us-status", "us-cancel"}
    if manual and ((args.operation != "us-status" and not args.request_id) or args.request_json is not None):
        parser.error("US manual operations require --request-id and do not accept --request-json")
    order_fields = (args.action, args.quantity, args.price, args.settlement)
    if args.operation == "us-order" and (not args.symbol or any(v is None for v in order_fields)):
        parser.error("us-order requires --symbol --action --quantity --price --settlement --request-id")
    if args.operation != "us-order" and any(v is not None for v in order_fields):
        parser.error("order parameters are only accepted for us-order")
    if not manual and args.request_id is not None:
        parser.error("--request-id is only accepted for US manual operations")
    try:
        value = {"operation": args.operation}
        if args.operation == "us-probe":
            value["symbol"] = args.symbol
        if manual and args.request_id is not None:
            value["request_id"] = args.request_id
        if args.operation == "us-order":
            value.update(symbol=args.symbol, action=args.action, quantity=args.quantity,
                         price=args.price, settlement_mode=args.settlement)
        if args.operation == "command":
            value["request"] = json_value(args.request_json)
        result = request_control(value)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "code": "EXECUTOR_UNAVAILABLE" if isinstance(exc, FileNotFoundError)
                              else "EXECUTOR_RESPONSE_UNKNOWN",
                          "retry_policy": "CHECK_STATUS_DO_NOT_RESEND"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
