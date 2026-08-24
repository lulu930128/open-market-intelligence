from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "agents" / "omi_mcp_server" / "server.py"


def _request(request_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _notification(method: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "method": method},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_by_id(lines: list[str], request_id: int) -> dict[str, Any]:
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            return payload
    raise RuntimeError(f"MCP response id={request_id} was not returned.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded initialize/tools-list smoke against the OMI stdio MCP adapter."
    )
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    if not SERVER_PATH.is_file():
        raise RuntimeError(f"OMI MCP server is missing: {SERVER_PATH}")

    env = os.environ.copy()
    env["OMI_API_BASE_URL"] = args.backend_url.rstrip("/")
    env["PYTHONUTF8"] = "1"
    messages = [
        _request(
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "omi-m5-preflight", "version": "1.0"},
            },
        ),
        _notification("notifications/initialized"),
        _request(2, "tools/list", {}),
    ]
    completed = subprocess.run(
        [sys.executable, str(SERVER_PATH)],
        cwd=REPO_ROOT,
        env=env,
        input="\n".join(messages) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=args.timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(
            f"OMI MCP process exited with code {completed.returncode}: {stderr[:500]}"
        )

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    initialize = _response_by_id(lines, 1)
    tools_list = _response_by_id(lines, 2)
    if "error" in initialize:
        raise RuntimeError(f"MCP initialize failed: {initialize['error']}")
    if "error" in tools_list:
        raise RuntimeError(f"MCP tools/list failed: {tools_list['error']}")

    initialize_result = initialize.get("result")
    tools_result = tools_list.get("result")
    if not isinstance(initialize_result, dict) or not isinstance(tools_result, dict):
        raise RuntimeError("MCP smoke returned malformed result objects.")
    tools = tools_result.get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("MCP tools/list did not return a tools array.")
    tool_names = {
        str(item.get("name"))
        for item in tools
        if isinstance(item, dict) and item.get("name")
    }
    if "omi.ask" not in tool_names:
        raise RuntimeError("MCP tools/list did not expose omi.ask.")

    print(
        json.dumps(
            {
                "result": "passed",
                "protocol_version": initialize_result.get("protocolVersion"),
                "server_name": (initialize_result.get("serverInfo") or {}).get("name"),
                "tool_count": len(tools),
                "omi_ask_present": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
