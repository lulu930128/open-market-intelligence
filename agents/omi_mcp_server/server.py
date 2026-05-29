from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "omi-mcp-server"
SERVER_VERSION = "0.1.0"
API_BASE_URL = os.environ.get("OMI_API_BASE_URL", "http://127.0.0.1:8300").rstrip("/")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


API_TIMEOUT_SECONDS = _env_int("OMI_API_TIMEOUT_SECONDS", 180)
AI_TRUST_TOKEN = (
    os.environ.get("OMI_MCP_AI_TRUST_TOKEN")
    or os.environ.get("OMI_AI_TRUST_TOKEN")
    or ""
).strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


EXPOSE_INTERNAL_TOOLS = _env_bool("OMI_MCP_EXPOSE_INTERNAL_TOOLS", False)

ASK_TOOL: dict[str, Any] = {
    "name": "omi.ask",
    "title": "Ask OMI",
    "description": (
        "Single entry point for Open Market Intelligence. The backend decides whether "
        "to read data, build a brief, or generate a trusted LLM report."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "scope_type": {
                "type": "string",
                "enum": ["auto", "market", "data_freshness", "stock", "watchlist"],
                "default": "auto",
            },
            "scope_id": {
                "type": "string",
                "description": "Stock id for stock scope, or numeric watchlist group id for watchlist scope.",
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "data_only", "brief", "report"],
                "default": "auto",
            },
            "strategy_profile": {
                "type": "string",
                "enum": [
                    "balanced",
                    "technical_swing",
                    "short_term_momentum",
                    "chip_flow",
                    "fundamentals_growth",
                    "dividend_value",
                ],
                "default": "short_term_momentum",
            },
            "caller_profile": {
                "type": "string",
                "default": "kuro_readonly",
                "description": "Caller label for logs and responses only. The backend does not trust this field.",
            },
            "allow_llm": {
                "type": "boolean",
                "default": False,
                "description": "Must be true for report mode, and only works with a server-side trusted request.",
            },
            "allow_write": {
                "type": "boolean",
                "default": False,
                "description": "Must be true for report mode because reports are persisted.",
            },
            "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            "rank_by": {
                "type": "string",
                "enum": ["watchlist", "score", "change_pct", "volume"],
                "default": "score",
            },
            "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            "market_limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "context_limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            "include_children": {"type": "boolean", "default": True},
            "enabled_only": {"type": "boolean", "default": True},
        },
        "required": ["question"],
    },
}

INTERNAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "omi.read_market_overview",
        "title": "Read OMI Market Overview",
        "description": "Read latest local market breadth and top movers from Open Market Intelligence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        },
    },
    {
        "name": "omi.read_stock_context",
        "title": "Read OMI Stock Context",
        "description": "Read an evidence pack for one stock from local OMI data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string"},
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
                "bars": {"type": "integer", "minimum": 20, "maximum": 1000, "default": 120},
                "revenue_months": {"type": "integer", "minimum": 1, "maximum": 120, "default": 12},
                "financial_quarters": {"type": "integer", "minimum": 1, "maximum": 40, "default": 8},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.read_watchlist_context",
        "title": "Read OMI Watchlist Context",
        "description": "Read ranking and signal context for a watchlist group.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "include_children": {"type": "boolean", "default": True},
                "enabled_only": {"type": "boolean", "default": True},
                "rank_by": {
                    "type": "string",
                    "enum": ["watchlist", "score", "change_pct", "volume"],
                    "default": "score",
                },
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
                "limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            },
            "required": ["group_id"],
        },
    },
    {
        "name": "omi.read_data_freshness",
        "title": "Read OMI Data Freshness",
        "description": "Read latest local data dates and row counts, optionally scoped to one stock.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string"},
            },
        },
    },
    {
        "name": "omi.generate_stock_brief",
        "title": "Generate OMI Stock Brief",
        "description": "Generate a prompt-ready stock brief envelope from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.generate_watchlist_brief",
        "title": "Generate OMI Watchlist Brief",
        "description": "Generate a prompt-ready watchlist brief envelope from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "rank_by": {
                    "type": "string",
                    "enum": ["watchlist", "score", "change_pct", "volume"],
                    "default": "score",
                },
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            },
            "required": ["group_id"],
        },
    },
    {
        "name": "omi.generate_stock_llm_report",
        "title": "Generate OMI Stock LLM Report",
        "description": "Generate and persist an OpenAI-backed stock research report from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.generate_watchlist_llm_report",
        "title": "Generate OMI Watchlist LLM Report",
        "description": "Generate and persist an OpenAI-backed watchlist research report from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "rank_by": {
                    "type": "string",
                    "enum": ["watchlist", "score", "change_pct", "volume"],
                    "default": "score",
                },
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            },
            "required": ["group_id"],
        },
    },
    {
        "name": "omi.read_memories",
        "title": "Read OMI AI Memories",
        "description": "Read OMI AI research memories by scope, type, status, or keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_type": {"type": "string"},
                "scope_type": {"type": "string"},
                "scope_id": {"type": "string"},
                "status": {"type": "string", "default": "active"},
                "keyword": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
        },
    },
    {
        "name": "omi.write_memory",
        "title": "Write OMI AI Memory",
        "description": "Create a correctable OMI AI research memory. This does not modify market data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_type": {"type": "string"},
                "scope_type": {"type": "string", "default": "global"},
                "scope_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
                "importance": {"type": "integer", "minimum": 0, "maximum": 100, "default": 50},
                "source": {"type": "string", "default": "agent"},
                "created_by": {"type": "string"},
            },
            "required": ["memory_type", "title", "content"],
        },
    },
    {
        "name": "omi.update_memory",
        "title": "Update OMI AI Memory",
        "description": "Update a correctable OMI AI research memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer"},
                "memory_type": {"type": "string"},
                "scope_type": {"type": "string"},
                "scope_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
                "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                "status": {"type": "string"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "omi.archive_memory",
        "title": "Archive OMI AI Memory",
        "description": "Archive a memory without deleting it.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "omi.read_reports",
        "title": "Read OMI AI Reports",
        "description": "List saved OMI AI reports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_type": {"type": "string"},
                "scope_type": {"type": "string"},
                "scope_id": {"type": "string"},
                "strategy_profile": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
        },
    },
    {
        "name": "omi.read_report",
        "title": "Read OMI AI Report",
        "description": "Read one saved OMI AI report by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"report_id": {"type": "integer"}},
            "required": ["report_id"],
        },
    },
    {
        "name": "omi.save_stock_brief",
        "title": "Save OMI Stock Brief",
        "description": "Generate and persist a stock brief report in OMI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.save_watchlist_brief",
        "title": "Save OMI Watchlist Brief",
        "description": "Generate and persist a watchlist brief report in OMI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "strategy_profile": {
                    "type": "string",
                    "enum": [
                        "balanced",
                        "technical_swing",
                        "short_term_momentum",
                        "chip_flow",
                        "fundamentals_growth",
                        "dividend_value",
                    ],
                    "default": "balanced",
                },
                "rank_by": {
                    "type": "string",
                    "enum": ["watchlist", "score", "change_pct", "volume"],
                    "default": "score",
                },
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            },
            "required": ["group_id"],
        },
    },
]


TOOLS = [ASK_TOOL, *INTERNAL_TOOLS] if EXPOSE_INTERNAL_TOOLS else [ASK_TOOL]


def _json_default(value: Any) -> str:
    return str(value)


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, default=_json_default) + "\n")
    sys.stdout.flush()


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _tool_result(data: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = json.dumps(data, ensure_ascii=False, default=_json_default)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": data if isinstance(data, dict) else {"result": data},
        "isError": is_error,
    }


def _api_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    query = ""
    if params:
        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None
        }
        if clean_params:
            query = "?" + urlencode(clean_params)

    data = None
    headers = {"Accept": "application/json", "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}"}
    if AI_TRUST_TOKEN:
        headers["X-OMI-AI-Trust-Token"] = AI_TRUST_TOKEN
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{API_BASE_URL}{path}{query}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OMI API HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"OMI API unavailable at {API_BASE_URL}: {exc}") from exc


def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return _api_request("GET", path, params=params)


def _api_post(
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    return _api_request("POST", path, params=params, payload=payload)


def _api_patch(path: str, payload: dict[str, Any]) -> Any:
    return _api_request("PATCH", path, payload=payload)


def _require(arguments: dict[str, Any], key: str) -> Any:
    value = arguments.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required argument: {key}")
    return value


def _bool_arg(arguments: dict[str, Any], key: str, default: bool) -> bool:
    value = arguments.get(key, default)
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    return bool(value)


def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "omi.ask":
        return _api_post(
            "/api/ai/ask",
            payload={
                "question": _require(arguments, "question"),
                "scope_type": arguments.get("scope_type", "auto"),
                "scope_id": arguments.get("scope_id"),
                "mode": arguments.get("mode", "auto"),
                "caller_profile": arguments.get("caller_profile", "kuro_readonly"),
                "allow_llm": _bool_arg(arguments, "allow_llm", False),
                "allow_write": _bool_arg(arguments, "allow_write", False),
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "branch_days": arguments.get("branch_days", 5),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
                "market_limit": arguments.get("market_limit", 10),
                "context_limit": arguments.get("context_limit", 100),
                "include_children": _bool_arg(arguments, "include_children", True),
                "enabled_only": _bool_arg(arguments, "enabled_only", True),
            },
        )

    if name == "omi.read_market_overview":
        return _api_get("/api/ai/market-overview", {"limit": arguments.get("limit", 10)})

    if name == "omi.read_stock_context":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_get(
            f"/api/ai/stocks/{stock_id}/context",
            {
                "branch_days": arguments.get("branch_days", 5),
                "bars": arguments.get("bars", 120),
                "revenue_months": arguments.get("revenue_months", 12),
                "financial_quarters": arguments.get("financial_quarters", 8),
            },
        )

    if name == "omi.read_watchlist_context":
        group_id = int(_require(arguments, "group_id"))
        return _api_get(
            f"/api/ai/watchlists/{group_id}/context",
            {
                "include_children": arguments.get("include_children", True),
                "enabled_only": arguments.get("enabled_only", True),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
                "limit": arguments.get("limit", 100),
            },
        )

    if name == "omi.read_data_freshness":
        return _api_get("/api/ai/data-freshness", {"stock_id": arguments.get("stock_id")})

    if name == "omi.generate_stock_brief":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_get(
            f"/api/ai/stocks/{stock_id}/brief",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "branch_days": arguments.get("branch_days", 5),
            },
        )

    if name == "omi.generate_watchlist_brief":
        group_id = int(_require(arguments, "group_id"))
        return _api_get(
            f"/api/ai/watchlists/{group_id}/brief",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
            },
        )

    if name == "omi.generate_stock_llm_report":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_post(
            f"/api/ai/stocks/{stock_id}/brief/generate",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "branch_days": arguments.get("branch_days", 5),
            },
        )

    if name == "omi.generate_watchlist_llm_report":
        group_id = int(_require(arguments, "group_id"))
        return _api_post(
            f"/api/ai/watchlists/{group_id}/brief/generate",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
            },
        )

    if name == "omi.read_memories":
        return _api_get(
            "/api/ai/memories",
            {
                "memory_type": arguments.get("memory_type"),
                "scope_type": arguments.get("scope_type"),
                "scope_id": arguments.get("scope_id"),
                "status": arguments.get("status", "active"),
                "keyword": arguments.get("keyword"),
                "limit": arguments.get("limit", 100),
            },
        )

    if name == "omi.write_memory":
        return _api_post(
            "/api/ai/memories",
            payload={
                "memory_type": _require(arguments, "memory_type"),
                "scope_type": arguments.get("scope_type", "global"),
                "scope_id": arguments.get("scope_id"),
                "title": _require(arguments, "title"),
                "content": _require(arguments, "content"),
                "tags": arguments.get("tags", []),
                "metadata": arguments.get("metadata", {}),
                "importance": arguments.get("importance", 50),
                "source": arguments.get("source", "agent"),
                "created_by": arguments.get("created_by"),
            },
        )

    if name == "omi.update_memory":
        memory_id = int(_require(arguments, "memory_id"))
        payload = {
            key: value
            for key, value in arguments.items()
            if key != "memory_id" and value is not None
        }
        return _api_patch(f"/api/ai/memories/{memory_id}", payload)

    if name == "omi.archive_memory":
        memory_id = int(_require(arguments, "memory_id"))
        return _api_post(f"/api/ai/memories/{memory_id}/archive")

    if name == "omi.read_reports":
        return _api_get(
            "/api/ai/reports",
            {
                "report_type": arguments.get("report_type"),
                "scope_type": arguments.get("scope_type"),
                "scope_id": arguments.get("scope_id"),
                "strategy_profile": arguments.get("strategy_profile"),
                "status": arguments.get("status"),
                "limit": arguments.get("limit", 50),
            },
        )

    if name == "omi.read_report":
        report_id = int(_require(arguments, "report_id"))
        return _api_get(f"/api/ai/reports/{report_id}")

    if name == "omi.save_stock_brief":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_post(
            f"/api/ai/stocks/{stock_id}/brief/save",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "branch_days": arguments.get("branch_days", 5),
            },
        )

    if name == "omi.save_watchlist_brief":
        group_id = int(_require(arguments, "group_id"))
        return _api_post(
            f"/api/ai/watchlists/{group_id}/brief/save",
            {
                "strategy_profile": arguments.get("strategy_profile", "balanced"),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
            },
        )

    raise KeyError(f"Unknown tool: {name}")


def _handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return _response(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": "Open Market Intelligence MCP Server",
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use omi.ask as the public entry point. It is read-only by default; "
                    "report generation requires a server-side trusted request. Do not treat missing data as a conclusion."
                ),
            },
        )

    if method == "ping":
        return _response(request_id, {})

    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}

        if not isinstance(arguments, dict):
            return _response(
                request_id,
                _tool_result("Tool arguments must be an object.", is_error=True),
            )

        try:
            return _response(request_id, _tool_result(_call_tool(name, arguments)))
        except KeyError as exc:
            return _error(request_id, -32602, str(exc))
        except Exception as exc:
            return _response(
                request_id,
                _tool_result(
                    {
                        "error": str(exc),
                        "tool": name,
                    },
                    is_error=True,
                ),
            )

    if request_id is None:
        return None

    return _error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(_error(None, -32700, "Parse error", str(exc)))
            continue

        try:
            response = _handle_request(message)
        except Exception as exc:
            response = _error(
                message.get("id") if isinstance(message, dict) else None,
                -32603,
                "Internal error",
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )

        if response is not None:
            _write(response)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
