"""Finite inherited-environment fixture: no app startup, registry, network or DB."""
import ast
import hashlib
import hmac
import os
from pathlib import Path
import sys


def main() -> None:
    source = Path(__file__).resolve().parents[2] / "app/runtime_control.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    verifier = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "token_authorized")
    namespace = {"os": os, "hashlib": hashlib, "hmac": hmac,
                 "TOKEN_ENV": "OMI_RUNTIME_CONTROL_TOKEN_SHA256"}
    exec(compile(ast.Module(body=[verifier], type_ignores=[]), str(source), "exec"), namespace)
    token = chr(97) * 64
    configured = os.environ.get(namespace["TOKEN_ENV"])
    enabled = sys.argv[1] == "enabled"
    expected = hashlib.sha256(token.encode("ascii")).hexdigest() if enabled else None
    if configured != expected or namespace["token_authorized"](token) != enabled:
        raise RuntimeError("INHERITED_CREDENTIAL_MISMATCH")
    if namespace["token_authorized"](chr(98) * 64):
        raise RuntimeError("FOREIGN_CREDENTIAL_ACCEPTED")
    print("CREDENTIAL_CHILD_PASS")


if __name__ == "__main__":
    main()
