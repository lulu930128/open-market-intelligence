from __future__ import annotations

from typing import Any


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    tool_list = [
            {
                "name": "omi.ask",
                "title": "Ask OMI",
                "description": (
                    "Single OMI entry point. It chooses data_only, brief, full, analysis, or report mode "
                    "from a question and policy flags."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "contract_version": {
                            "type": "string",
                            "enum": ["omi.decision.v3", "omi.ai.ask.v2"],
                            "default": "omi.decision.v3",
                            "description": (
                                "Canonical OMI decision envelope. "
                                "omi.ai.ask.v2 remains available for compatibility."
                            ),
                        },
                        "question": {"type": "string"},
                        "target": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
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
                                    ],
                                    "default": "auto",
                                },
                                "id": {"type": "string"},
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
                            "default": "kuro_readonly",
                            "description": "Caller label only. Server-side policy decides trust.",
                        },
                        "allow_llm": {
                            "type": "boolean",
                            "default": False,
                            "description": "Must be true for analysis/report mode and requires server-side trust.",
                        },
                        "allow_write": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required only for persisted report mode.",
                        },
                        "allow_external_fetch": {
                            "type": "boolean",
                            "default": False,
                            "description": "Allow trusted OMI backend to call configured external market APIs and update local evidence cache.",
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
                        "conversation_context": {
                            "type": "object",
                            "description": "Optional caller context such as prior OMI resolution.",
                        },
                        "market_data_params": {
                            "type": "object",
                            "description": (
                                "Optional bounded market-data parameters for readers, for example "
                                "provider, providers, symbols, symbol, instrument_type, interval, timeframe, bars, "
                                "include_intraday, payload_level, intraday_limit, observations, holding_limit, "
                                "health_limit, radar_limit, market, resource, target, or limit."
                            ),
                            "properties": {
                                "include_intraday": {"type": "boolean", "default": False},
                                "payload_level": {
                                    "type": "string",
                                    "enum": ["summary", "compact", "standard", "full"],
                                    "default": "compact",
                                },
                                "intraday_limit": {"type": "integer", "minimum": 1, "maximum": 500},
                                "observations": {"type": "integer", "minimum": 1, "maximum": 240},
                                "holding_limit": {"type": "integer", "minimum": 1, "maximum": 500},
                                "health_limit": {"type": "integer", "minimum": 1, "maximum": 500},
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
                                    "description": "Maximum number of strikes projected around the selected TXO expiry.",
                                },
                                "market": {"type": "string"},
                                "resource": {"type": "string"},
                                "target": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "omi.read_market_overview",
                "title": "Read Market Overview",
                "description": "Read latest local market breadth and top movers from OMI data.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "omi.read_stock_context",
                "title": "Read Stock Context",
                "description": "Read an evidence pack for one stock from local OMI data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
                        },
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
                "name": "omi.read_tw_index_context",
                "title": "Read Taiwan Index Context",
                "description": "Read an evidence pack for TAIEX/TPEX from market index, chip, and chart data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "index_id": {"type": "string", "enum": ["TAIEX", "TPEX"]},
                        "include_intraday": {"type": "boolean", "default": False},
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["index_id"],
                },
            },
            {
                "name": "omi.read_tw_futures_context",
                "title": "Read Taiwan Futures Context",
                "description": "Read an evidence pack for TXF/MXF/TMF from TAIFEX futures quote and bar data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": ["TXF", "MXF", "TMF"]},
                        "include_intraday": {"type": "boolean", "default": False},
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "market_data_params": {
                            "type": "object",
                            "properties": {
                                "option_contract_month": {
                                    "type": "string",
                                    "pattern": "^[0-9A-Z]+$",
                                },
                                "option_strike_limit": {
                                    "type": "integer",
                                    "minimum": 3,
                                    "maximum": 25,
                                    "default": 11,
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_us_stock_context",
                "title": "Read US Stock Context",
                "description": "Read an evidence pack for one US stock from local OMI data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "market_data_params": {"type": "object"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_jp_stock_context",
                "title": "Read Japan Stock Context",
                "description": "Read a Japan stock evidence pack from local OMI data, with optional bounded intraday provider evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "market_data_params": {"type": "object"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_jp_index_context",
                "title": "Read Japan Index Context",
                "description": "Read an OHLC-focused evidence pack for one Japan index or index proxy, with optional bounded intraday provider evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": ["^N225", "1306.T"]},
                        "market_data_params": {"type": "object"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_kr_stock_context",
                "title": "Read Korea Stock Context",
                "description": "Read a local-cache evidence pack for one Korea stock.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "market_data_params": {"type": "object"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_kr_index_context",
                "title": "Read Korea Index Context",
                "description": "Read a local-cache OHLC evidence pack for one Korea index.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": ["KOSPI", "KOSDAQ", "KOSPI200"]},
                        "market_data_params": {"type": "object"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_crypto_market_context",
                "title": "Read Crypto Market Context",
                "description": "Read bounded local-cache crypto market evidence, provider contract, and source health.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "market_data_params": {
                            "type": "object",
                            "description": "Optional provider/symbol/interval/limit filters.",
                        },
                        "context_limit": {"type": "integer", "minimum": 20, "maximum": 500},
                    },
                },
            },
            {
                "name": "omi.read_crypto_asset_context",
                "title": "Read Crypto Asset Context",
                "description": "Read bounded local-cache evidence for one crypto asset such as BTC or ETH.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "asset": {"type": "string"},
                        "market_data_params": {
                            "type": "object",
                            "description": "Optional provider/symbol/instrument_type/interval/limit filters.",
                        },
                        "context_limit": {"type": "integer", "minimum": 20, "maximum": 500},
                    },
                    "required": ["asset"],
                },
            },
            {
                "name": "omi.read_watchlist_context",
                "title": "Read Watchlist Context",
                "description": "Read ranking and signal context for a watchlist group.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "integer"},
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "radar_mode": {
                            "type": "string",
                            "enum": [
                                "action",
                                "surge",
                                "breakout",
                                "volume",
                                "overheat",
                                "weakness",
                                "risk",
                                "momentum",
                                "all",
                            ],
                            "default": "action",
                            "description": "Controls which watchlist radar signals are emphasized.",
                        },
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.read_data_freshness",
                "title": "Read Data Freshness",
                "description": "Read latest local data dates and row counts, optionally for one stock.",
                "input_schema": {
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
                "title": "Generate Stock Brief",
                "description": "Generate a prompt-ready stock brief envelope from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
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
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.generate_us_stock_brief",
                "title": "Generate US Stock Brief",
                "description": "Generate a prompt-ready US stock brief envelope from local OMI evidence.",
                "input_schema": {
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
                "name": "omi.generate_watchlist_brief",
                "title": "Generate Watchlist Brief",
                "description": "Generate a prompt-ready watchlist brief envelope from local OMI evidence.",
                "input_schema": {
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
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                        "radar_mode": {
                            "type": "string",
                            "enum": [
                                "action",
                                "surge",
                                "breakout",
                                "volume",
                                "overheat",
                                "weakness",
                                "risk",
                                "momentum",
                                "all",
                            ],
                            "default": "action",
                        },
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.generate_stock_llm_report",
                "title": "Generate Stock LLM Report",
                "description": "Generate and persist an OpenAI-backed stock research report from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
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
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.generate_us_stock_llm_report",
                "title": "Generate US Stock LLM Report",
                "description": "Generate and persist an OpenAI-backed US stock research report from local OMI evidence.",
                "input_schema": {
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
                "title": "Generate Watchlist LLM Report",
                "description": "Generate and persist an OpenAI-backed watchlist research report from local OMI evidence.",
                "input_schema": {
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
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                        "radar_mode": {
                            "type": "string",
                            "enum": [
                                "action",
                                "surge",
                                "breakout",
                                "volume",
                                "overheat",
                                "weakness",
                                "risk",
                                "momentum",
                                "all",
                            ],
                            "default": "action",
                        },
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.read_memories",
                "title": "Read AI Memories",
                "description": "Read OMI AI research memories by scope, type, status, or keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "status": {"type": "string"},
                        "keyword": {"type": "string"},
                    },
                },
            },
            {
                "name": "omi.write_memory",
                "title": "Write AI Memory",
                "description": "Create a correctable OMI AI research memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "required": ["memory_type", "title", "content"],
                },
            },
            {
                "name": "omi.update_memory",
                "title": "Update AI Memory",
                "description": "Update an existing OMI AI research memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                        "status": {"type": "string"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "omi.archive_memory",
                "title": "Archive AI Memory",
                "description": "Archive an OMI AI research memory without deleting it.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "omi.read_reports",
                "title": "Read AI Reports",
                "description": "List saved OMI AI reports.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "strategy_profile": {"type": "string"},
                    },
                },
            },
            {
                "name": "omi.read_report",
                "title": "Read AI Report",
                "description": "Read one saved OMI AI report by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_id": {"type": "integer"},
                    },
                    "required": ["report_id"],
                },
            },
            {
                "name": "omi.save_stock_brief",
                "title": "Save Stock Brief",
                "description": "Generate and persist a stock brief report in OMI.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
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
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.save_us_stock_brief",
                "title": "Save US Stock Brief",
                "description": "Generate and persist a US stock brief report in OMI.",
                "input_schema": {
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
                "title": "Save Watchlist Brief",
                "description": "Generate and persist a watchlist brief report in OMI.",
                "input_schema": {
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
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                        "radar_mode": {
                            "type": "string",
                            "enum": [
                                "action",
                                "surge",
                                "breakout",
                                "volume",
                                "overheat",
                                "weakness",
                                "risk",
                                "momentum",
                                "all",
                            ],
                            "default": "action",
                        },
                    },
                    "required": ["group_id"],
                },
            },
    ]

    if not include_internal:
        tool_list = tool_list[:1]

    return {"tools": tool_list}
