from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def _configure_stdio() -> None:
    """Keep MCP stdio traffic UTF-8 on Windows and other non-UTF-8 shells."""
    for stream_name, errors in (
        ("stdin", "replace"),
        ("stdout", "strict"),
        ("stderr", "backslashreplace"),
    ):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors=errors)
            except Exception:
                pass


_configure_stdio()


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "omi-mcp-server"
SERVER_VERSION = "0.1.0"
API_BASE_URL = os.environ.get("OMI_API_BASE_URL", "http://127.0.0.1:8400").rstrip("/")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


API_TIMEOUT_SECONDS = _env_int("OMI_API_TIMEOUT_SECONDS", 180)
SCHEMA_TIMEOUT_SECONDS = _env_int("OMI_SCHEMA_TIMEOUT_SECONDS", 2)
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
TRUSTED_DEFAULT_EXTERNAL_FETCH = _env_bool("OMI_MCP_TRUSTED_DEFAULT_EXTERNAL_FETCH", True)
TRUSTED_DEFAULT_TOOL_BUDGET = {
    "max_calls": 5,
    "max_external_fetches": 3,
    "max_total_seconds": 25,
}
US_CONTEXT_HINTS = (
    "adr",
    "amex",
    "arca",
    "nasdaq",
    "nyse",
    "otc",
    "otcmkts",
    "ticker",
    "us stock",
    "u.s. stock",
    "美股",
    "美國股票",
    "美國個股",
    "美國上市",
    "納斯達克",
    "那斯達克",
    "紐交所",
)
US_EXCHANGE_SYMBOL_PATTERN = re.compile(
    r"\b(?:NASDAQ|NYSE|AMEX|NYSEARCA|ARCA|CBOE|OTC|OTCMKTS)[:：]\s*([A-Za-z][A-Za-z0-9.$-]{0,15})\b",
    flags=re.IGNORECASE,
)
US_DOLLAR_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_$.-])\$([A-Za-z][A-Za-z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)
US_UPPER_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.$-])([A-Z][A-Z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)
TW_INTRADAY_HINTS = (
    "intraday",
    "today",
    "live",
    "quote",
    "realtime",
    "real-time",
    "1m",
    "5m",
    "盤中",
    "即時",
    "今天",
    "今日",
    "現在",
    "報價",
    "分時",
    "分k",
    "1分",
    "5分",
)
TW_TARGET_TYPES = {"tw_stock", "tw_index", "tw_futures"}
TW_MARKETS = {"tw", "twse", "tpex", "taiwan"}
TW_STOCK_ID_PATTERN = re.compile(r"(?<!\d)\d{4,6}(?!\d)")
ASK_TARGET_TYPES = [
    "auto",
    "market",
    "data_freshness",
    "tw_stock",
    "tw_watchlist",
    "tw_index",
    "tw_futures",
    "us_stock",
    "jp_stock",
    "jp_index",
    "kr_stock",
    "kr_index",
    "crypto_market",
    "crypto_asset",
    "resource_asset",
    "portfolio",
    "us_macro",
    "us_watchlist",
    "jp_watchlist",
    "kr_watchlist",
    "source_health",
    "capability_status",
]

PAYLOAD_LEVEL_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["summary", "compact", "standard", "full"],
    "default": "compact",
    "description": "Controls bounded market-data density. Use summary for voice/quick answers, compact by default, standard/full only when detail is requested.",
}

CAPABILITY_IDS = [
    "target.identity",
    "quote.snapshot",
    "quote.order_book",
    "quote.auction",
    "quote.official_close",
    "intraday.bars",
    "daily.ohlcv",
    "technical.structure",
    "chips.institutional",
    "chips.margin",
    "broker_branch.summary",
    "ownership.distribution",
    "fundamentals.revenue",
    "fundamentals.financials",
    "cross_market.overnight",
    "company.profile",
    "corporate.actions",
    "market.short_volume",
    "market.breadth",
    "market.indices",
    "events.upcoming",
    "events.calendar",
    "events.history",
    "regulation.disposition",
    "regulation.trading_restrictions",
    "market.sectors",
    "market.index_contributions",
    "market.institutional_flow",
    "market.margin_short",
    "market.sample_ranking",
    "market.cross_market",
    "market.chips",
    "screening.ranking",
    "screening.coverage",
    "screening.intraday",
    "market.hot_groups",
    "market.volume_state",
    "derivatives.positioning",
    "derivatives.structure",
    "watchlist.ranking",
    "watchlist.radar",
    "watchlist.coverage",
    "portfolio.summary",
    "portfolio.holdings",
    "portfolio.valuation",
    "macro.series",
    "macro.observations",
    "resource.metadata",
    "crypto.order_book",
    "crypto.derivatives",
    "diagnostics.capabilities",
    "diagnostics.data_freshness",
    "diagnostics.source_health",
    "source.health",
    "data.freshness",
]

CAPABILITY_ID_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": CAPABILITY_IDS,
}

CAPABILITY_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Bounded OMI data selection. Choose registered capabilities, field allowlists, "
        "row/point limits, and a response byte ceiling."
    ),
    "properties": {
        "include": {"type": "array", "items": CAPABILITY_ID_SCHEMA, "uniqueItems": True},
        "required": {"type": "array", "items": CAPABILITY_ID_SCHEMA, "uniqueItems": True},
        "optional": {"type": "array", "items": CAPABILITY_ID_SCHEMA, "uniqueItems": True},
        "exclude": {"type": "array", "items": CAPABILITY_ID_SCHEMA, "uniqueItems": True},
        "fields": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
        "limits": {
            "type": "object",
            "additionalProperties": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
            },
        },
        "max_response_bytes": {
            "type": "integer",
            "minimum": 4096,
            "maximum": 1048576,
        },
    },
    "additionalProperties": False,
}

INTRADAY_LIMIT_SCHEMA: dict[str, Any] = {
    "type": "integer",
    "minimum": 1,
    "maximum": 500,
    "description": "Maximum intraday points to return per series. Backend still applies its own upper bound.",
}

INCLUDE_INTRADAY_SCHEMA: dict[str, Any] = {
    "type": "boolean",
    "default": False,
    "description": "Request bounded intraday evidence when the backend trust policy allows external/cache refresh.",
}

INTRADAY_INTERVAL_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["1m", "5m", "15m", "30m", "1h", "4h"],
    "description": (
        "Requested intraday bar interval. OMI responses expose requested_interval, "
        "source_interval, and effective_interval so provider aggregation or fallback "
        "is never silently relabeled."
    ),
}

INTERVAL_ALIAS_SCHEMA: dict[str, Any] = {
    **INTRADAY_INTERVAL_SCHEMA,
    "description": (
        "Compatibility alias for intraday_interval. Prefer intraday_interval for new callers."
    ),
}

SESSION_SCOPE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["regular", "extended", "all"],
    "default": "regular",
    "description": "US intraday session scope. Use all to include pre-market and after-hours bars.",
}

TRADE_DATE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": (
        "Target-market trade date. For US stocks this is the America/New_York "
        "exchange date; exact close requests never fall back to another date."
    ),
}

ASK_TOOL: dict[str, Any] = {
    "name": "omi.ask",
    "title": "Ask OMI",
    "description": (
        "Canonical Open Market Intelligence decision entry point. Send a natural-language question "
        "and optional target; OMI resolves the target, returns clarification when "
        "needed, and provides read-only evidence, brief, or trusted analysis. "
        "All consumers should read answer, decision, evidence, limitations, and status "
        "from the consumer-neutral omi.decision.v4 envelope."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "contract_version": {
                "type": "string",
                "enum": ["omi.decision.v4"],
                "default": "omi.decision.v4",
                "description": (
                    "The only public OMI decision contract. It provides selective evidence, "
                    "manifest, fill plan, and bounded response size."
                ),
            },
            "question": {"type": "string"},
            "intents": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
                "description": "Optional multi-intent request; target identity remains separate.",
            },
            "output": {
                "type": "string",
                "enum": ["evidence_only", "decision", "decision_with_evidence"],
                "description": "Requested information purpose, independent of the consumer.",
            },
            "realtime_policy": {
                "type": "string",
                "enum": ["cache_only", "prefer_live", "require_live"],
                "default": "prefer_live",
            },
            "selection": CAPABILITY_SELECTION_SCHEMA,
            "continuation": {
                "type": "object",
                "description": "Re-submit selected granular fill actions for backend revalidation.",
                "properties": {
                    "plan_id": {"type": "string"},
                    "plan_action_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 32,
                        "uniqueItems": True,
                    },
                    "selected_action_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    },
                },
                "additionalProperties": False,
            },
            "target": {
                "type": "object",
                "description": "Optional resolved or requested target. Use type=auto when Kuro wants OMI to resolve it.",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ASK_TARGET_TYPES,
                        "default": "auto",
                    },
                    "id": {
                        "type": "string",
                        "description": "Target id, for example Taiwan stock id 2330 or watchlist group id 1.",
                    },
                    "label": {"type": "string"},
                    "market": {"type": "string"},
                },
                "default": {"type": "auto"},
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "data_only", "brief", "full", "analysis", "report"],
                "default": "auto",
            },
            "include_raw": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Deprecated transport flag retained for caller compatibility. v4 always "
                    "returns the canonical envelope; use selection and max_response_bytes "
                    "to bound payload size."
                ),
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
            "analysis_horizon": {
                "type": "string",
                "enum": ["auto", "intraday", "short", "swing", "long"],
                "default": "auto",
                "description": "Analysis horizon. auto defaults to swing, meaning medium-short-term evidence.",
            },
            "caller_profile": {
                "type": "string",
                "default": "external_readonly",
                "description": "Caller label for logs and responses only. The backend does not trust this field.",
            },
            "allow_llm": {
                "type": "boolean",
                "default": False,
                "description": "Must be true for analysis/report mode, and only works with a server-side trusted request.",
            },
            "allow_write": {
                "type": "boolean",
                "default": False,
                "description": "Must be true only for report mode because reports are persisted.",
            },
            "allow_external_fetch": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Allow trusted OMI backend to call configured external market APIs and update local evidence cache. "
                    "If omitted, trusted MCP calls default this to true for clear US stock questions or explicit Taiwan/Japan intraday requests; callers may set it explicitly for bounded OMI-managed refresh."
                ),
            },
            "tool_budget": {
                "type": "object",
                "properties": {
                    "max_calls": {"type": "integer", "minimum": 0, "maximum": 12, "default": 5},
                    "max_external_fetches": {"type": "integer", "minimum": 0, "maximum": 8, "default": 3},
                    "max_total_seconds": {"type": "integer", "minimum": 1, "maximum": 90, "default": 25},
                },
            },
            "refresh_policy": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["stale_first", "off"], "default": "stale_first"},
                    "before_answer": {"type": "boolean", "default": True},
                    "fallback_to_cached": {"type": "boolean", "default": True},
                },
                "description": "Controls whether OMI should refresh stale local evidence before answering.",
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
            "include_intraday": INCLUDE_INTRADAY_SCHEMA,
            "payload_level": PAYLOAD_LEVEL_SCHEMA,
            "diagnostics_level": {
                "type": "string",
                "enum": ["none", "basic", "debug"],
                "default": "none",
                "description": "Independent diagnostic projection; it does not change answer mode.",
            },
            "intraday_limit": INTRADAY_LIMIT_SCHEMA,
            "intraday_interval": INTRADAY_INTERVAL_SCHEMA,
            "session_scope": SESSION_SCOPE_SCHEMA,
            "trade_date": TRADE_DATE_SCHEMA,
            "include_children": {"type": "boolean", "default": True},
            "enabled_only": {"type": "boolean", "default": True},
            "conversation_context": {
                "type": "object",
                "description": (
                    "Optional conversation context. Prefer last_target for follow-up turns; "
                    "legacy last_resolution and previous_resolution aliases remain accepted."
                ),
            },
            "position_context": {
                "type": "object",
                "description": "Optional caller-supplied position context; backend owns decision semantics.",
            },
            "market_data_params": {
                "type": "object",
                "description": (
                    "Optional bounded market-data parameters forwarded to OMI readers, "
                    "for example provider, providers, symbol, symbols, instrument_type, "
                    "intraday_interval, interval, timeframe, bars, daily_limit, "
                    "include_intraday, payload_level, "
                    "intraday_limit, session_scope, trade_date, or limit."
                ),
            },
        },
        "required": ["question"],
    },
}

ASK_STREAM_TOOL: dict[str, Any] = {
    **ASK_TOOL,
    "name": "omi.ask_stream",
    "title": "Ask OMI Stream",
    "description": (
        "Streaming variant of omi.ask. It calls OMI's text/event-stream endpoint "
        "and returns collected status/evidence/tool_run/delta/final events for "
        "MCP clients that cannot consume native HTTP SSE directly. Prefer direct "
        "HTTP SSE when the client UI needs live incremental updates."
    ),
}


def _load_public_contract_snapshot() -> dict[str, Any]:
    snapshot_path = Path(__file__).with_name(
        "public_contract_snapshot.json"
    )
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "omi.mcp.public_contract_snapshot.v1"
        or not isinstance(payload.get("ask_input_schema"), dict)
    ):
        return {}
    return payload


def _apply_public_contract_snapshot() -> None:
    snapshot = _load_public_contract_snapshot()
    if not snapshot:
        return
    target_types = [
        str(value)
        for value in snapshot.get("target_types") or []
        if str(value).strip()
    ]
    capability_ids = [
        str(value)
        for value in snapshot.get("capability_ids") or []
        if str(value).strip()
    ]
    if target_types:
        ASK_TARGET_TYPES[:] = target_types
    if capability_ids:
        CAPABILITY_IDS[:] = capability_ids
    schema = json.loads(
        json.dumps(snapshot["ask_input_schema"], ensure_ascii=False)
    )
    properties = schema.setdefault("properties", {})
    properties.setdefault(
        "include_raw",
        {
            "type": "boolean",
            "default": True,
            "description": (
                "Deprecated transport flag retained for caller "
                "compatibility. v4 always returns the canonical backend "
                "envelope."
            ),
        },
    )
    ASK_TOOL["inputSchema"] = schema
    ASK_STREAM_TOOL["inputSchema"] = json.loads(
        json.dumps(schema, ensure_ascii=False)
    )
    selection_schema = properties.get("selection")
    if isinstance(selection_schema, dict):
        CAPABILITY_SELECTION_SCHEMA.clear()
        CAPABILITY_SELECTION_SCHEMA.update(
            json.loads(
                json.dumps(selection_schema, ensure_ascii=False)
            )
        )


_apply_public_contract_snapshot()

MARKET_DATA_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional bounded market-data parameters forwarded to OMI readers, "
        "for example provider, providers, symbol, symbols, instrument_type, "
        "intraday_interval, interval, timeframe, bars, daily_limit, "
        "include_intraday, payload_level, "
        "intraday_limit, session_scope, trade_date, observations, holding_limit, health_limit, "
        "radar_limit, market, resource, target, or limit."
    ),
    "properties": {
        "include_intraday": INCLUDE_INTRADAY_SCHEMA,
        "payload_level": PAYLOAD_LEVEL_SCHEMA,
        "intraday_limit": INTRADAY_LIMIT_SCHEMA,
        "intraday_interval": INTRADAY_INTERVAL_SCHEMA,
        "interval": INTERVAL_ALIAS_SCHEMA,
        "session_scope": SESSION_SCOPE_SCHEMA,
        "trade_date": TRADE_DATE_SCHEMA,
        "observations": {"type": "integer", "minimum": 1, "maximum": 240},
        "holding_limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "health_limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "problems_only": {"type": "boolean", "default": False},
        "include_healthy": {"type": "boolean", "default": True},
        "status_filter": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
            ]
        },
        "radar_limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "option_contract_month": {
            "type": "string",
            "pattern": "^[0-9A-Z]+$",
            "description": "Optional TXO month/week bucket such as 202608 or 202607W4.",
        },
        "option_strike_limit": {
            "type": "integer",
            "minimum": 3,
            "maximum": 25,
            "default": 11,
            "description": "Maximum number of TXO strikes projected around the selected expiry.",
        },
        "market": {"type": "string"},
        "resource": {"type": "string"},
        "target": {"type": "string"},
        "provider": {"type": "string"},
        "capability_id": {"type": "string"},
        "status": {"type": "string"},
    },
    "additionalProperties": True,
}

MARKET_PAYLOAD_CONTROL_PROPERTIES: dict[str, Any] = {
    "include_intraday": INCLUDE_INTRADAY_SCHEMA,
    "payload_level": PAYLOAD_LEVEL_SCHEMA,
    "intraday_limit": INTRADAY_LIMIT_SCHEMA,
    "intraday_interval": INTRADAY_INTERVAL_SCHEMA,
    "session_scope": SESSION_SCOPE_SCHEMA,
    "trade_date": TRADE_DATE_SCHEMA,
    "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
}

CROSS_MARKET_READER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "omi.read_jp_stock_context",
        "title": "Read OMI Japan Stock Context",
        "description": "Read a Japan stock evidence pack through OMI ask; daily/resources stay local-cache and include_intraday enables a bounded provider read when trusted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.read_jp_index_context",
        "title": "Read OMI Japan Index Context",
        "description": "Read an OHLC-focused Japan index evidence pack through OMI ask; include_intraday enables a bounded provider read when trusted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "enum": ["^N225", "1306.T"]},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.read_kr_stock_context",
        "title": "Read OMI Korea Stock Context",
        "description": "Read a local-cache evidence pack for one Korea stock through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.read_kr_index_context",
        "title": "Read OMI Korea Index Context",
        "description": "Read a local-cache OHLC evidence pack for one Korea index through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "enum": ["KOSPI", "KOSDAQ", "KOSPI200"]},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.read_crypto_market_context",
        "title": "Read OMI Crypto Market Context",
        "description": "Read bounded local-cache crypto market evidence through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
                "context_limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            },
        },
    },
    {
        "name": "omi.read_crypto_asset_context",
        "title": "Read OMI Crypto Asset Context",
        "description": "Read bounded local-cache evidence for one crypto asset through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset": {"type": "string"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
                "context_limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            },
            "required": ["asset"],
        },
    },
]

CROSS_MARKET_BRIEF_TOOLS: list[dict[str, Any]] = [
    {
        "name": "omi.generate_jp_stock_brief",
        "title": "Generate OMI Japan Stock Brief",
        "description": "Generate a compact Japan stock brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.generate_jp_index_brief",
        "title": "Generate OMI Japan Index Brief",
        "description": "Generate a compact Japan index brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "enum": ["^N225", "1306.T"]},
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.generate_kr_stock_brief",
        "title": "Generate OMI Korea Stock Brief",
        "description": "Generate a compact Korea stock brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.generate_kr_index_brief",
        "title": "Generate OMI Korea Index Brief",
        "description": "Generate a compact Korea index brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "enum": ["KOSPI", "KOSDAQ", "KOSPI200"]},
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "omi.generate_crypto_market_brief",
        "title": "Generate OMI Crypto Market Brief",
        "description": "Generate a compact crypto market brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
                "context_limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            },
        },
    },
    {
        "name": "omi.generate_crypto_asset_brief",
        "title": "Generate OMI Crypto Asset Brief",
        "description": "Generate a compact crypto asset brief through OMI ask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset": {"type": "string"},
                "strategy_profile": {"type": "string", "default": "short_term_momentum"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
                "context_limit": {"type": "integer", "minimum": 20, "maximum": 500, "default": 100},
            },
            "required": ["asset"],
        },
    },
]

DIRECT_ASK_TOOL_TARGETS: dict[str, tuple[str, str | None, str, str]] = {
    "omi.read_jp_stock_context": ("jp_stock", "symbol", "data_only", "Read Japan stock context"),
    "omi.read_jp_index_context": ("jp_index", "symbol", "data_only", "Read Japan index context"),
    "omi.read_kr_stock_context": ("kr_stock", "symbol", "data_only", "Read Korea stock context"),
    "omi.read_kr_index_context": ("kr_index", "symbol", "data_only", "Read Korea index context"),
    "omi.read_crypto_market_context": ("crypto_market", None, "data_only", "Read crypto market context"),
    "omi.read_crypto_asset_context": ("crypto_asset", "asset", "data_only", "Read crypto asset context"),
    "omi.generate_jp_stock_brief": ("jp_stock", "symbol", "brief", "Generate Japan stock brief"),
    "omi.generate_jp_index_brief": ("jp_index", "symbol", "brief", "Generate Japan index brief"),
    "omi.generate_kr_stock_brief": ("kr_stock", "symbol", "brief", "Generate Korea stock brief"),
    "omi.generate_kr_index_brief": ("kr_index", "symbol", "brief", "Generate Korea index brief"),
    "omi.generate_crypto_market_brief": ("crypto_market", None, "brief", "Generate crypto market brief"),
    "omi.generate_crypto_asset_brief": ("crypto_asset", "asset", "brief", "Generate crypto asset brief"),
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
                **MARKET_PAYLOAD_CONTROL_PROPERTIES,
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
                **MARKET_PAYLOAD_CONTROL_PROPERTIES,
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.read_us_stock_context",
        "title": "Read OMI US Stock Context",
        "description": "Read an evidence pack for one US stock from local OMI data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    *CROSS_MARKET_READER_TOOLS,
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
                "market": {
                    "type": "string",
                    "enum": ["TW", "US", "JP", "KR", "CRYPTO", "ALL"],
                    "default": "TW",
                },
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
                    "default": "short_term_momentum",
                },
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
                **MARKET_PAYLOAD_CONTROL_PROPERTIES,
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.generate_us_stock_brief",
        "title": "Generate OMI US Stock Brief",
        "description": "Generate a prompt-ready US stock brief envelope from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
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
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
                "market_data_params": MARKET_DATA_PARAMS_SCHEMA,
            },
            "required": ["symbol"],
        },
    },
    *CROSS_MARKET_BRIEF_TOOLS,
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
                    "default": "short_term_momentum",
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
                    "default": "short_term_momentum",
                },
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
                "include_intraday": {"type": "boolean", "default": False},
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.generate_us_stock_llm_report",
        "title": "Generate OMI US Stock LLM Report",
        "description": "Generate and persist an OpenAI-backed US stock research report from local OMI evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
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
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
            },
            "required": ["symbol"],
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
                    "default": "short_term_momentum",
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
                    "default": "short_term_momentum",
                },
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
                "include_intraday": {"type": "boolean", "default": False},
                "branch_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "omi.save_us_stock_brief",
        "title": "Save OMI US Stock Brief",
        "description": "Generate and persist a US stock brief report in OMI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
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
                "analysis_horizon": {
                    "type": "string",
                    "enum": ["auto", "intraday", "short", "swing", "long"],
                    "default": "auto",
                },
            },
            "required": ["symbol"],
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
                    "default": "short_term_momentum",
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


MARKET_PAYLOAD_CONTROL_TOOL_NAMES = {
    "omi.ask",
    "omi.ask_stream",
    "omi.read_market_overview",
    "omi.read_stock_context",
    "omi.read_us_stock_context",
    "omi.generate_stock_brief",
    "omi.generate_us_stock_brief",
    *DIRECT_ASK_TOOL_TARGETS.keys(),
}


def _augment_market_payload_control_schema(tool: dict[str, Any]) -> dict[str, Any]:
    if tool.get("name") not in MARKET_PAYLOAD_CONTROL_TOOL_NAMES:
        return tool
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return tool
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return tool
    for key, value in MARKET_PAYLOAD_CONTROL_PROPERTIES.items():
        properties.setdefault(key, value)
    market_data_params = properties.get("market_data_params")
    if isinstance(market_data_params, dict):
        market_data_params.setdefault("properties", {})
        if isinstance(market_data_params["properties"], dict):
            for key, value in (
                ("include_intraday", INCLUDE_INTRADAY_SCHEMA),
                ("payload_level", PAYLOAD_LEVEL_SCHEMA),
                ("intraday_limit", INTRADAY_LIMIT_SCHEMA),
                ("intraday_interval", INTRADAY_INTERVAL_SCHEMA),
                ("interval", INTERVAL_ALIAS_SCHEMA),
                ("session_scope", SESSION_SCOPE_SCHEMA),
                ("trade_date", TRADE_DATE_SCHEMA),
            ):
                market_data_params["properties"].setdefault(key, value)
        market_data_params.setdefault("additionalProperties", True)
    return tool


PUBLIC_TOOLS = [_augment_market_payload_control_schema(tool) for tool in [ASK_TOOL, ASK_STREAM_TOOL]]
INTERNAL_TOOLS = [_augment_market_payload_control_schema(tool) for tool in INTERNAL_TOOLS]
TOOLS = [*PUBLIC_TOOLS, *INTERNAL_TOOLS] if EXPOSE_INTERNAL_TOOLS else PUBLIC_TOOLS


def _json_default(value: Any) -> str:
    return str(value)


def _replace_surrogates(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _replace_surrogates(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_json_value(str(key)): _sanitize_json_value(item)
            for key, item in value.items()
        }
    return value


def _write(message: dict[str, Any]) -> None:
    safe_message = _sanitize_json_value(message)
    text = json.dumps(safe_message, ensure_ascii=False, default=_json_default) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
        return

    sys.stdout.write(text)
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
    safe_data = _sanitize_json_value(data)
    text = json.dumps(safe_data, ensure_ascii=False, default=_json_default)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": safe_data if isinstance(safe_data, dict) else {"result": safe_data},
        "isError": is_error,
    }


def _api_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
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
        safe_payload = _sanitize_json_value(payload)
        data = json.dumps(safe_payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{API_BASE_URL}{path}{query}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(
            request,
            timeout=timeout_seconds or API_TIMEOUT_SECONDS,
        ) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OMI API HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"OMI API unavailable at {API_BASE_URL}: {exc}") from exc


def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return _api_request("GET", path, params=params)


def _backend_public_tools() -> list[dict[str, Any]]:
    payload = _api_request(
        "GET",
        "/api/ai/tools",
        timeout_seconds=SCHEMA_TIMEOUT_SECONDS,
    )
    backend_tools = (
        payload.get("tools")
        if isinstance(payload, dict) and isinstance(payload.get("tools"), list)
        else []
    )
    ask_source = next(
        (
            item
            for item in backend_tools
            if isinstance(item, dict) and item.get("name") == "omi.ask"
        ),
        None,
    )
    if ask_source is None:
        raise RuntimeError("OMI backend tool catalog did not expose omi.ask.")

    ask_tool = {
        "name": "omi.ask",
        "title": str(ask_source.get("title") or "Ask OMI"),
        "description": str(ask_source.get("description") or ""),
        "inputSchema": json.loads(
            json.dumps(ask_source.get("input_schema") or {})
        ),
    }
    properties = ask_tool["inputSchema"].setdefault("properties", {})
    properties.setdefault(
        "include_raw",
        {
            "type": "boolean",
            "default": True,
            "description": (
                "Deprecated transport flag retained for caller compatibility. "
                "v4 always returns the canonical backend envelope."
            ),
        },
    )
    ask_tool = _augment_market_payload_control_schema(ask_tool)
    stream_tool = json.loads(json.dumps(ask_tool))
    stream_tool.update(
        {
            "name": "omi.ask_stream",
            "title": "Ask OMI Stream",
            "description": ASK_STREAM_TOOL["description"],
        }
    )
    public_tools = [ask_tool, stream_tool]
    return (
        [*public_tools, *INTERNAL_TOOLS]
        if EXPOSE_INTERNAL_TOOLS
        else public_tools
    )


def _tools_for_client() -> list[dict[str, Any]]:
    try:
        return _backend_public_tools()
    except Exception:
        return TOOLS


def _api_post(
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    return _api_request("POST", path, params=params, payload=payload)


def _read_sse_events(response: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []

    def commit_event() -> None:
        nonlocal event_name, data_lines
        if not data_lines and event_name == "message":
            return

        data_text = "\n".join(data_lines)
        try:
            data: Any = json.loads(data_text) if data_text else {}
        except json.JSONDecodeError:
            data = {"text": data_text}

        events.append({"event": event_name, "data": data})
        event_name = "message"
        data_lines = []

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            commit_event()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())

    commit_event()
    return events


def _api_stream_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = _sanitize_json_value(payload)
    data = json.dumps(safe_payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}",
    }
    if AI_TRUST_TOKEN:
        headers["X-OMI-AI-Trust-Token"] = AI_TRUST_TOKEN

    request = Request(
        f"{API_BASE_URL}{path}",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            events = _read_sse_events(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OMI API HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"OMI API unavailable at {API_BASE_URL}: {exc}") from exc

    final = None
    evidence = None
    error = None
    done = None
    delta_parts: list[str] = []
    for event in events:
        event_type = event.get("event")
        event_data = event.get("data")
        if event_type == "final" and isinstance(event_data, dict):
            final = event_data
        elif event_type == "evidence" and isinstance(event_data, dict):
            evidence = event_data
        elif event_type == "error" and isinstance(event_data, dict):
            error = event_data
        elif event_type == "done" and isinstance(event_data, dict):
            done = event_data
        elif event_type == "delta" and isinstance(event_data, dict):
            text = event_data.get("text")
            if isinstance(text, str):
                delta_parts.append(text)

    ok = bool(done.get("ok")) if isinstance(done, dict) else bool(final and not error)
    return {
        "kind": "omi_stream_result",
        "ok": ok,
        "events": events,
        "final": final,
        "evidence": evidence,
        "delta_text": "".join(delta_parts),
        "error": error,
    }


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


def _dict_arg(arguments: dict[str, Any], key: str) -> dict[str, Any]:
    value = arguments.get(key)
    return value if isinstance(value, dict) else {}


def _merge_market_data_params(arguments: dict[str, Any]) -> dict[str, Any]:
    params = dict(_dict_arg(arguments, "market_data_params"))
    if "include_intraday" in arguments and "include_intraday" not in params:
        params["include_intraday"] = _bool_arg(arguments, "include_intraday", False)
    analysis_horizon = str(arguments.get("analysis_horizon") or "").strip().lower()
    if analysis_horizon == "intraday" and "include_intraday" not in params:
        params["include_intraday"] = True
    if "payload_level" in arguments and "payload_level" not in params:
        level = str(arguments.get("payload_level") or "").strip().lower()
        if level in {"summary", "compact", "standard", "full"}:
            params["payload_level"] = level
    if "intraday_limit" in arguments and "intraday_limit" not in params:
        try:
            params["intraday_limit"] = max(1, min(500, int(arguments["intraday_limit"])))
        except (TypeError, ValueError):
            pass
    if "intraday_interval" in arguments and "intraday_interval" not in params:
        interval = str(arguments.get("intraday_interval") or "").strip().lower()
        if interval in {"1m", "5m", "15m", "30m", "1h", "4h"}:
            params["intraday_interval"] = interval
    if "session_scope" in arguments and "session_scope" not in params:
        session_scope = str(arguments.get("session_scope") or "").strip().lower()
        if session_scope in {"regular", "extended", "all"}:
            params["session_scope"] = session_scope
    if "trade_date" in arguments and "trade_date" not in params:
        trade_date = str(arguments.get("trade_date") or "").strip()
        if trade_date:
            params["trade_date"] = trade_date
    return params


def _market_query_controls(arguments: dict[str, Any]) -> dict[str, Any]:
    params = _merge_market_data_params(arguments)
    query: dict[str, Any] = {}
    if "include_intraday" in params:
        query["include_intraday"] = bool(params["include_intraday"])
    if "payload_level" in params:
        query["payload_level"] = params["payload_level"]
    if "intraday_limit" in params:
        query["intraday_limit"] = params["intraday_limit"]
    if "intraday_interval" in params:
        query["intraday_interval"] = params["intraday_interval"]
    return query


def _target_from_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    target = arguments.get("target")
    return target if isinstance(target, dict) else {}


def _looks_like_us_symbol(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.isdecimal():
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9.$-]{0,15}", text))


def _looks_like_us_question(arguments: dict[str, Any]) -> bool:
    target = _target_from_arguments(arguments)
    target_type = str(target.get("type") or "").strip().lower()
    target_id = target.get("id") or target.get("symbol")
    if target_type == "us_stock":
        return True
    if target_type in {"", "auto"} and _looks_like_us_symbol(target_id):
        return True

    question = str(arguments.get("question") or "")
    lowered_question = question.lower()
    if any(hint in lowered_question for hint in US_CONTEXT_HINTS):
        return True
    if US_EXCHANGE_SYMBOL_PATTERN.search(question) or US_DOLLAR_SYMBOL_PATTERN.search(question):
        return True
    return bool(US_UPPER_SYMBOL_PATTERN.search(question))


def _looks_like_tw_intraday_question(arguments: dict[str, Any]) -> bool:
    target = _target_from_arguments(arguments)
    target_type = str(target.get("type") or "").strip().lower()
    target_market = str(target.get("market") or "").strip().lower()
    target_id = str(target.get("id") or target.get("symbol") or "").strip()
    question = str(arguments.get("question") or "")
    lowered_question = question.lower()

    has_tw_target = (
        target_type in TW_TARGET_TYPES
        or target_market in TW_MARKETS
        or target_id.isdecimal()
        or bool(TW_STOCK_ID_PATTERN.search(question))
    )
    if not has_tw_target:
        return False

    requested_horizon = str(arguments.get("analysis_horizon") or "").strip().lower()
    if requested_horizon == "intraday":
        return True

    return any(hint in lowered_question for hint in TW_INTRADAY_HINTS)


def _looks_like_jp_intraday_request(arguments: dict[str, Any]) -> bool:
    target = _target_from_arguments(arguments)
    target_type = str(target.get("type") or "").strip().lower()
    if target_type not in {"jp_stock", "jp_index"}:
        return False

    requested_horizon = str(arguments.get("analysis_horizon") or "").strip().lower()
    if requested_horizon == "intraday":
        return True

    return bool(_merge_market_data_params(arguments).get("include_intraday"))


def _default_allow_external_fetch(arguments: dict[str, Any]) -> bool:
    if "allow_external_fetch" in arguments:
        return _bool_arg(arguments, "allow_external_fetch", False)

    return bool(
        AI_TRUST_TOKEN
        and TRUSTED_DEFAULT_EXTERNAL_FETCH
        and (
            _looks_like_us_question(arguments)
            or _looks_like_tw_intraday_question(arguments)
            or _looks_like_jp_intraday_request(arguments)
        )
    )


def _tool_budget_arg(arguments: dict[str, Any], *, allow_external_fetch: bool) -> dict[str, Any]:
    tool_budget = arguments.get("tool_budget")
    if isinstance(tool_budget, dict) and tool_budget:
        return tool_budget
    if allow_external_fetch:
        return dict(TRUSTED_DEFAULT_TOOL_BUDGET)
    return {}


def _public_contract_version(arguments: dict[str, Any]) -> str:
    contract_version = str(
        arguments.get("contract_version") or "omi.decision.v4"
    ).strip()
    if contract_version != "omi.decision.v4":
        raise ValueError("contract_version must be omi.decision.v4.")
    return contract_version


def _ask_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    allow_external_fetch = _default_allow_external_fetch(arguments)
    market_data_params = _merge_market_data_params(arguments)
    return {
        "contract_version": _public_contract_version(arguments),
        "question": _require(arguments, "question"),
        "target": arguments.get("target") or {"type": "auto"},
        "mode": arguments.get("mode", "auto"),
        "intents": arguments.get("intents") or [],
        "output": arguments.get("output"),
        "realtime_policy": arguments.get("realtime_policy"),
        "selection": arguments.get("selection") or {},
        "continuation": arguments.get("continuation") or {},
        "payload_level": market_data_params.get("payload_level"),
        "diagnostics_level": arguments.get("diagnostics_level", "none"),
        "caller_profile": arguments.get("caller_profile", "external_readonly"),
        "allow_llm": _bool_arg(arguments, "allow_llm", False),
        "allow_write": _bool_arg(arguments, "allow_write", False),
        "allow_external_fetch": allow_external_fetch,
        "tool_budget": _tool_budget_arg(arguments, allow_external_fetch=allow_external_fetch),
        "refresh_policy": arguments.get("refresh_policy") or {
            "mode": "stale_first",
            "before_answer": True,
            "fallback_to_cached": True,
        },
        "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
        "analysis_horizon": arguments.get("analysis_horizon", "auto"),
        "branch_days": arguments.get("branch_days", 5),
        "rank_by": arguments.get("rank_by", "score"),
        "sort_order": arguments.get("sort_order", "desc"),
        "market_limit": arguments.get("market_limit", 10),
        "context_limit": arguments.get("context_limit", 100),
        "include_children": _bool_arg(arguments, "include_children", True),
        "enabled_only": _bool_arg(arguments, "enabled_only", True),
        "position_context": arguments.get("position_context") or {},
        "conversation_context": arguments.get("conversation_context") or {},
        "market_data_params": market_data_params,
    }


def _targeted_ask_payload(
    arguments: dict[str, Any],
    *,
    target_type: str,
    target_id: str | None = None,
    question: str,
    mode: str,
) -> dict[str, Any]:
    target = {"type": target_type}
    if target_id:
        target["id"] = target_id
    if arguments.get("label"):
        target["label"] = arguments["label"]
    if arguments.get("market"):
        target["market"] = arguments["market"]

    ask_arguments = dict(arguments)
    ask_arguments["question"] = arguments.get("question") or question
    ask_arguments["target"] = target
    ask_arguments["mode"] = mode
    return _ask_payload(ask_arguments)


def _post_targeted_ask(
    arguments: dict[str, Any],
    *,
    target_type: str,
    target_id: str | None = None,
    question: str,
    mode: str,
) -> Any:
    return _api_post(
        "/api/ai/ask",
        payload=_targeted_ask_payload(
            arguments,
            target_type=target_type,
            target_id=target_id,
            question=question,
            mode=mode,
        ),
    )


def _bounded_summary_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        if isinstance(value, list):
            return {"item_count": len(value), "truncated": True}
        if isinstance(value, dict):
            return {"field_count": len(value), "truncated": True}
        return value
    if isinstance(value, list):
        return [_bounded_summary_value(item, depth=depth + 1) for item in value[:5]]
    if isinstance(value, dict):
        omitted_keys = {
            "bars",
            "chart",
            "components",
            "data",
            "detail",
            "events",
            "financial_history",
            "history",
            "points",
            "prompt",
            "raw",
            "raw_response",
            "revenue_history",
            "rows",
            "source_refs",
            "technical_reports",
        }
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key in omitted_keys or len(output) >= 24:
                continue
            output[str(key)] = _bounded_summary_value(item, depth=depth + 1)
        return output
    return value


def _summarize_ask_response(response: Any) -> Any:
    if not isinstance(response, dict):
        return response
    if response.get("contract_version") == "omi.decision.v4":
        return response

    output: dict[str, Any] = {
        "kind": "omi_ask_summary",
        "raw_included": False,
    }
    for key in (
        "contract_version",
        "ok",
        "mode",
        "answer_ready",
        "facts_ready",
        "analysis_ready",
        "decision_ready",
        "blocked_sections",
        "available_sections",
        "request_status",
        "fallback_used",
        "cached_data_returned",
        "job",
        "cancellation",
        "target",
        "resolution",
        "clarification",
        "next_context",
        "next_actions",
        "error",
    ):
        if response.get(key) not in (None, {}, []):
            output[key] = _bounded_summary_value(response[key])

    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    if analysis:
        output["analysis"] = _bounded_summary_value(
            {
                key: analysis[key]
                for key in (
                    "kind",
                    "question_intent",
                    "requested_horizon",
                    "selected_horizon",
                    "selected_timeframe",
                    "selected_score",
                    "selected_title",
                    "selected_summary",
                    "selected_confidence",
                    "display",
                    "human_answer",
                    "decision_contract",
                    "price_level_validation",
                )
                if key in analysis
            }
        )

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact = result_data.get("compact") if isinstance(result_data.get("compact"), dict) else {}
    if result:
        output["result_summary"] = _bounded_summary_value(
            {
                key: result[key]
                for key in ("kind", "as_of", "status", "scope", "summary", "human_answer")
                if key in result
            }
        )
    if compact:
        output["compact_evidence"] = _bounded_summary_value(
            {
                key: compact[key]
                for key in (
                    "kind",
                    "version",
                    "payload_level",
                    "status",
                    "target",
                    "as_of",
                    "quote",
                    "technical",
                    "breadth",
                    "breadth_by_market",
                    "sample_breadth",
                    "sample_coverage",
                    "volume_state",
                    "sample_top_gainers",
                    "sample_top_losers",
                    "sample_value_leaders",
                    "freshness_by_domain",
                    "data_quality",
                    "slots",
                )
                if key in compact
            }
        )

    freshness = response.get("freshness")
    if isinstance(freshness, dict) and freshness:
        output["freshness"] = _bounded_summary_value(freshness)
    passport = response.get("evidence_passport")
    if isinstance(passport, dict) and passport:
        output["evidence_passport"] = _bounded_summary_value(
            {
                key: passport[key]
                for key in (
                    "kind",
                    "data_freshness",
                    "coverage",
                    "completeness",
                    "confidence",
                    "decision_readiness",
                )
                if key in passport
            }
        )
    tool_runs = response.get("tool_runs") if isinstance(response.get("tool_runs"), list) else []
    notable_runs = [
        run
        for run in tool_runs
        if isinstance(run, dict)
        and (
            run.get("status") not in {None, "completed", "success"}
            or run.get("fallback_used")
            or run.get("cached_data_returned")
        )
    ]
    if notable_runs:
        output["notable_tool_runs"] = _bounded_summary_value(notable_runs)
    for key in ("missing", "warnings"):
        if isinstance(response.get(key), list) and response[key]:
            output[key] = _bounded_summary_value(response[key])
    return output


def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "omi.ask":
        response = _api_post("/api/ai/ask", payload=_ask_payload(arguments))
        if not isinstance(response, dict) or response.get("contract_version") != "omi.decision.v4":
            raise RuntimeError("OMI backend returned a non-v4 public ask response.")
        return response

    if name == "omi.ask_stream":
        response = _api_stream_post("/api/ai/ask/stream", payload=_ask_payload(arguments))
        final = response.get("final") if isinstance(response, dict) else None
        if isinstance(final, dict) and final.get("contract_version") != "omi.decision.v4":
            raise RuntimeError("OMI backend returned a non-v4 public stream response.")
        return response

    if name == "omi.read_market_overview":
        return _api_get(
            "/api/ai/market-overview",
            {
                "limit": arguments.get("limit", 10),
                **_market_query_controls(arguments),
            },
        )

    if name == "omi.read_stock_context":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_get(
            f"/api/ai/stocks/{stock_id}/context",
            {
                "branch_days": arguments.get("branch_days", 5),
                "bars": arguments.get("bars", 120),
                "revenue_months": arguments.get("revenue_months", 12),
                "financial_quarters": arguments.get("financial_quarters", 8),
                "include_intraday": _bool_arg(arguments, "include_intraday", False),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
                **_market_query_controls(arguments),
            },
        )

    if name == "omi.read_us_stock_context":
        symbol = quote(str(_require(arguments, "symbol")).upper(), safe="")
        if _merge_market_data_params(arguments):
            return _post_targeted_ask(
                arguments,
                target_type="us_stock",
                target_id=str(_require(arguments, "symbol")).upper(),
                question=f"Read US stock context {str(_require(arguments, 'symbol')).upper()}",
                mode="data_only",
            )
        return _api_get(f"/api/ai/us-stocks/{symbol}/context")

    if name in DIRECT_ASK_TOOL_TARGETS:
        target_type, id_key, mode, question_prefix = DIRECT_ASK_TOOL_TARGETS[name]
        target_id = str(_require(arguments, id_key)).strip() if id_key else None
        return _post_targeted_ask(
            arguments,
            target_type=target_type,
            target_id=target_id,
            question=f"{question_prefix} {target_id or ''}".strip(),
            mode=mode,
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
        return _api_get(
            "/api/ai/data-freshness",
            {
                "stock_id": arguments.get("stock_id"),
                "market": arguments.get("market", "TW"),
            },
        )

    if name == "omi.generate_stock_brief":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_get(
            f"/api/ai/stocks/{stock_id}/brief",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "branch_days": arguments.get("branch_days", 5),
                "include_intraday": _bool_arg(arguments, "include_intraday", False),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
                **_market_query_controls(arguments),
            },
        )

    if name == "omi.generate_us_stock_brief":
        symbol = quote(str(_require(arguments, "symbol")).upper(), safe="")
        if _merge_market_data_params(arguments):
            return _post_targeted_ask(
                arguments,
                target_type="us_stock",
                target_id=str(_require(arguments, "symbol")).upper(),
                question=f"Generate US stock brief {str(_require(arguments, 'symbol')).upper()}",
                mode="brief",
            )
        return _api_get(
            f"/api/ai/us-stocks/{symbol}/brief",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
            },
        )

    if name == "omi.generate_watchlist_brief":
        group_id = int(_require(arguments, "group_id"))
        return _api_get(
            f"/api/ai/watchlists/{group_id}/brief",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "rank_by": arguments.get("rank_by", "score"),
                "sort_order": arguments.get("sort_order", "desc"),
            },
        )

    if name == "omi.generate_stock_llm_report":
        stock_id = quote(str(_require(arguments, "stock_id")), safe="")
        return _api_post(
            f"/api/ai/stocks/{stock_id}/brief/generate",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "branch_days": arguments.get("branch_days", 5),
                "include_intraday": _bool_arg(arguments, "include_intraday", False),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
            },
        )

    if name == "omi.generate_us_stock_llm_report":
        symbol = quote(str(_require(arguments, "symbol")).upper(), safe="")
        return _api_post(
            f"/api/ai/us-stocks/{symbol}/brief/generate",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
            },
        )

    if name == "omi.generate_watchlist_llm_report":
        group_id = int(_require(arguments, "group_id"))
        return _api_post(
            f"/api/ai/watchlists/{group_id}/brief/generate",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
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
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "branch_days": arguments.get("branch_days", 5),
                "include_intraday": _bool_arg(arguments, "include_intraday", False),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
            },
        )

    if name == "omi.save_us_stock_brief":
        symbol = quote(str(_require(arguments, "symbol")).upper(), safe="")
        return _api_post(
            f"/api/ai/us-stocks/{symbol}/brief/save",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
                "analysis_horizon": arguments.get("analysis_horizon", "auto"),
            },
        )

    if name == "omi.save_watchlist_brief":
        group_id = int(_require(arguments, "group_id"))
        return _api_post(
            f"/api/ai/watchlists/{group_id}/brief/save",
            {
                "strategy_profile": arguments.get("strategy_profile", "short_term_momentum"),
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
                    "Use omi.ask as the public entry point, or omi.ask_stream when collected stream events are useful. "
                    "It is read-only by default; "
                    "report generation requires a server-side trusted request. Do not treat missing data as a conclusion. "
                    "Read omi.decision.v4 through answer, decision, evidence, limitations, status, "
                    "and continuation.fill_plan; "
                    "do not reconstruct market semantics in the MCP client."
                ),
            },
        )

    if method == "ping":
        return _response(request_id, {})

    if method == "tools/list":
        return _response(request_id, {"tools": _tools_for_client()})

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}

        if not isinstance(arguments, dict):
            return _response(
                request_id,
                _tool_result("Tool arguments must be an object.", is_error=True),
            )

        try:
            tool_payload = _call_tool(name, arguments)
            return _response(
                request_id,
                _tool_result(tool_payload, is_error=False),
            )
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
