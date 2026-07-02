from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import evidence_builder, technical_analysis
from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.ai.evidence_passport import build_evidence_passport
from app.market import service as market_service
from app.market.broker_branch import get_broker_branch_trade_summary
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.technical_report import build_stock_technical_report
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.market_chips import get_latest_market_chip_daily, market_chip_daily_to_dict
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.source_health import build_taiwan_source_health
from app.market.tw_futures import (
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    normalize_taiwan_futures_symbols,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
from app.market.taiwan_industries import normalize_tw_industry_label
from app.stocks import service as stock_service
from app.watchlists import radar_service, ranking_service
from app.watchlists import service as watchlist_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if row is None:
        return None

    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _stock_dict(stock: StockMaster | None) -> dict[str, Any] | None:
    return _row_dict(
        stock,
        (
            "stock_id",
            "stock_name",
            "market",
            "instrument_type",
            "industry",
            "category",
            "is_active",
            "notes",
            "last_seen_at",
            "updated_at",
        ),
    )


def _latest_financial_period(row: FinancialMetricQuarterly | None) -> str | None:
    if row is None:
        return None

    return row.period or f"{row.fiscal_year}Q{row.quarter}"


def _latest_date_string(values: list[Any]) -> str | None:
    valid_values = [_json_value(value) for value in values if value is not None]

    if not valid_values:
        return None

    return str(max(valid_values))


def _broker_branch_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {key: _json_value(value) for key, value in row.items()}

    return _row_dict(
        row,
        (
            "trade_date",
            "stock_id",
            "stock_name",
            "branch_code",
            "branch_name",
            "buy_lots",
            "sell_lots",
            "net_lots",
            "buy_avg_price",
            "sell_avg_price",
            "buy_rank",
            "sell_rank",
            "source_label",
        ),
    ) or {}


def _add_missing(missing: list[str], key: str, value: Any) -> None:
    if value is None or value == []:
        missing.append(key)


def _with_evidence_passport(
    envelope: dict[str, Any],
    *,
    freshness: dict[str, Any] | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    envelope["evidence_passport"] = build_evidence_passport(
        kind=str(envelope.get("kind") or "ai_data"),
        as_of=envelope.get("as_of"),
        source_refs=envelope.get("source_refs") or [],
        missing=envelope.get("missing") or [],
        warnings=envelope.get("warnings") or [],
        freshness=freshness,
        tool_runs=tool_runs,
        analysis=analysis or data.get("analysis"),
        confidence=confidence,
    )
    return envelope



normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_report_score = technical_analysis._report_score
TECHNICAL_FACTOR_ROW_KEYS = technical_analysis.TECHNICAL_FACTOR_ROW_KEYS
TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON = technical_analysis.TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON
_score_direction = technical_analysis._score_direction
_factor_score_from_row = technical_analysis._factor_score_from_row
_timeframe_factor_scores = technical_analysis._timeframe_factor_scores
_weighted_factor_score = technical_analysis._weighted_factor_score
_technical_factor_score_model = technical_analysis._technical_factor_score_model
_weighted_score = technical_analysis._weighted_score
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_finite_number = technical_analysis._finite_number
_first_value = technical_analysis._first_value
_moving_average = technical_analysis._moving_average
_pct_change = technical_analysis._pct_change
_format_number = technical_analysis._format_number
_format_pct = technical_analysis._format_pct
_source_value = technical_analysis._source_value
_round_price = technical_analysis._round_price
_price_zone = technical_analysis._price_zone
_price_level = technical_analysis._price_level
_indicator_from_report = technical_analysis._indicator_from_report
_indicator_level_values = technical_analysis._indicator_level_values
_donchian_position = technical_analysis._donchian_position
_technical_price_levels = technical_analysis._technical_price_levels
_normalize_technical_points = technical_analysis._normalize_technical_points
_technical_report_from_points = technical_analysis._technical_report_from_points
_serialized_chart = technical_analysis._serialized_chart
_chart_from_points = technical_analysis._chart_from_points


def _stock_decision_evidence(
    *,
    latest_daily: Any,
    chart: dict[str, Any],
    latest_revenue: Any,
    latest_financial: Any,
    technical_reports: dict[str, Any],
    calendar_status: dict[str, Any] | None = None,
    missing: list[str],
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    return evidence_builder.build_stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=calendar_status,
        missing=missing,
        source_refs=source_refs,
    )


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    tool_list = [
            {
                "name": "omi.ask",
                "title": "Ask OMI",
                "description": (
                    "Single OMI entry point. It chooses data_only, brief, analysis, or report mode "
                    "from a question and policy flags."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "contract_version": {
                            "type": "string",
                            "default": "omi.ai.ask.v2",
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
                            "enum": ["auto", "data_only", "brief", "analysis", "report"],
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
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_jp_stock_context",
                "title": "Read Japan Stock Context",
                "description": "Read an evidence pack for one Japan stock from local OMI data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_jp_index_context",
                "title": "Read Japan Index Context",
                "description": "Read an OHLC-only evidence pack for one Japan index or index proxy.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": ["^N225", "1306.T"]},
                    },
                    "required": ["symbol"],
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


def read_data_freshness(db: Session, stock_id: str | None = None) -> dict[str, Any]:
    def latest(model: Any, column: Any) -> Any:
        query = db.query(func.max(column))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return query.scalar()

    def count(model: Any) -> int:
        query = db.query(func.count(model.id))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return int(query.scalar() or 0)

    financial_latest = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
        if stock_id
        else db.query(FinancialMetricQuarterly)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )

    tables = {
        "market_daily_price": {
            "latest": _json_value(latest(MarketDailyPrice, MarketDailyPrice.trade_date)),
            "row_count": count(MarketDailyPrice),
        },
        "institutional_trade_daily": {
            "latest": _json_value(latest(InstitutionalTradeDaily, InstitutionalTradeDaily.trade_date)),
            "row_count": count(InstitutionalTradeDaily),
        },
        "margin_trading_daily": {
            "latest": _json_value(latest(MarginTradingDaily, MarginTradingDaily.trade_date)),
            "row_count": count(MarginTradingDaily),
        },
        "broker_branch_trade_daily": {
            "latest": _json_value(latest(BrokerBranchTradeDaily, BrokerBranchTradeDaily.trade_date)),
            "row_count": count(BrokerBranchTradeDaily),
        },
        "shareholding_distribution_weekly": {
            "latest": _json_value(
                latest(ShareholdingDistributionWeekly, ShareholdingDistributionWeekly.data_date)
            ),
            "row_count": count(ShareholdingDistributionWeekly),
        },
        "monthly_revenue": {
            "latest": _json_value(latest(MonthlyRevenue, MonthlyRevenue.period)),
            "row_count": count(MonthlyRevenue),
        },
        "financial_metric_quarterly": {
            "latest": _latest_financial_period(financial_latest),
            "row_count": count(FinancialMetricQuarterly),
        },
    }

    missing = [name for name, info in tables.items() if not info["latest"] or info["row_count"] == 0]

    envelope = {
        "kind": "data_freshness",
        "generated_at": _now(),
        "as_of": _latest_date_string([info["latest"] for info in tables.values()]),
        "scope": {"stock_id": stock_id},
        "data": {"tables": tables},
        "missing": missing,
        "warnings": [
            "Freshness is based on the local OMI database, not direct exchange availability.",
        ],
        "source_refs": [{"type": "database", "name": "open_market_intelligence.db"}],
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_market_overview(db: Session, limit: int = 10) -> dict[str, Any]:
    latest_trade_date = market_service.get_latest_trade_date(db)
    missing: list[str] = []

    if latest_trade_date is None:
        envelope = {
            "kind": "market_overview",
            "generated_at": _now(),
            "as_of": None,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": {},
                "top_gainers": [],
                "top_losers": [],
            },
            "missing": ["market_daily_price"],
            "warnings": ["No market daily rows are available in the local database."],
            "source_refs": [{"type": "table", "name": "market_daily_price"}],
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
    stock_industries: dict[str, str | None] = {}
    for index in range(0, len(stock_ids), 500):
        chunk = stock_ids[index : index + 500]
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(chunk)).all():
            stock_industries[stock.stock_id] = normalize_tw_industry_label(
                stock.industry or stock.category,
                fallback="未分類",
            )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
            "industry": stock_industries.get(row.stock_id),
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]
    value_leaders = sorted(
        [row for row in ranked if row["trade_value"] is not None],
        key=lambda row: row["trade_value"] or 0,
        reverse=True,
    )[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None
    total_count = len(rows)
    average_change_pct = (
        sum(row["change_pct"] for row in ranked_with_change) / len(ranked_with_change)
        if ranked_with_change
        else None
    )
    positive_ratio = advance_count / len(ranked_with_change) if ranked_with_change else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    top_value_sum = sum(row["trade_value"] or 0 for row in value_leaders)
    top_value_share = (
        top_value_sum / total_trade_value
        if total_trade_value and value_leaders
        else None
    )
    distribution = {
        "limit_up_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) >= 9.5
        ),
        "strong_up_count": sum(
            1 for row in ranked_with_change if 5 <= (row["change_pct"] or 0) < 9.5
        ),
        "mild_up_count": sum(
            1 for row in ranked_with_change if 0 < (row["change_pct"] or 0) < 5
        ),
        "flat_count": unchanged_count,
        "mild_down_count": sum(
            1 for row in ranked_with_change if -5 < (row["change_pct"] or 0) < 0
        ),
        "strong_down_count": sum(
            1 for row in ranked_with_change if -9.5 < (row["change_pct"] or 0) <= -5
        ),
        "limit_down_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) <= -9.5
        ),
    }
    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_with_change:
        industry = normalize_tw_industry_label(row.get("industry"), fallback="未分類")
        industry_groups.setdefault(industry, []).append(row)

    industry_summary = []
    for industry, group_rows in industry_groups.items():
        changes = [
            row["change_pct"]
            for row in group_rows
            if isinstance(row.get("change_pct"), (int, float))
        ]
        if not changes:
            continue
        trade_value = sum(row.get("trade_value") or 0 for row in group_rows) or None
        top_row = max(
            group_rows,
            key=lambda row: (
                row.get("trade_value") or 0,
                row.get("change_pct") or 0,
            ),
        )
        industry_summary.append(
            {
                "industry": industry,
                "count": len(group_rows),
                "advance_count": sum(1 for value in changes if value > 0),
                "decline_count": sum(1 for value in changes if value < 0),
                "average_change_pct": sum(changes) / len(changes),
                "trade_value": trade_value,
                "top_stock_id": top_row.get("stock_id"),
                "top_stock_name": top_row.get("stock_name"),
            }
        )
    top_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            row.get("trade_value") or 0,
        ),
        reverse=True,
    )[:6]
    weak_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            -(row.get("trade_value") or 0),
        ),
    )[:6]

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    envelope = {
        "kind": "market_overview",
        "generated_at": _now(),
        "as_of": latest_trade_date.isoformat(),
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": {
                "advance_count": advance_count,
                "decline_count": decline_count,
                "unchanged_count": unchanged_count,
                "total_count": total_count,
                "trade_value": total_trade_value,
                "average_change_pct": average_change_pct,
                "positive_ratio": positive_ratio,
                "advance_decline_ratio": advance_decline_ratio,
                "top_value_share": top_value_share,
            },
            "distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "value_leaders": value_leaders,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
        },
        "missing": missing,
        "warnings": [
            "This overview uses the latest local daily market rows and does not fetch live quotes.",
        ],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_tw_index_context(
    db: Session,
    index_id: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_index_id = index_id.strip().upper()
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan index context uses market index evidence, not stock_master or individual stock daily tables.",
    ]
    charts: dict[str, Any] = {}
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            chart = get_market_index_ohlc_chart_data(
                index_id=normalized_index_id,
                timeframe=timeframe,
                bars=max(bars, 1),
                db=db,
            )
        except ValueError:
            raise
        except Exception as exc:
            warnings.append(f"{timeframe.title()} index chart unavailable: {exc}")
            missing.append(f"market_index_ohlc.{timeframe}")
            continue

        serialized = _serialized_chart(chart)
        charts[timeframe] = serialized
        points = _normalize_technical_points(serialized.get("points", []))
        technical_reports[timeframe] = _technical_report_from_points(
            points=points,
            timeframe=timeframe,
            asset_label=normalized_index_id,
        )
        if not points:
            missing.append(f"market_index_ohlc.{timeframe}")
        backfill = chart.get("backfill") if isinstance(chart.get("backfill"), dict) else {}
        if backfill.get("status") == "error":
            warnings.append(str(backfill.get("message") or "Index daily stat refresh failed."))

    intraday: dict[str, Any] | None = None
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    if include_intraday or normalized_horizon == "intraday":
        try:
            intraday = get_market_index_intraday(normalized_index_id)
            intraday_points = _normalize_technical_points(intraday.get("points", []))
            technical_reports["today"] = _technical_report_from_points(
                points=intraday_points,
                timeframe="today",
                asset_label=normalized_index_id,
            )
            if not intraday_points:
                missing.append("market_index_intraday")
        except Exception as exc:
            warnings.append(f"Index intraday unavailable: {exc}")
            missing.append("market_index_intraday")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    summary_payload: dict[str, Any] = {}
    index_snapshot: dict[str, Any] | None = None
    try:
        summary_payload = get_market_index_summary(db, force_refresh=False)
        for item in summary_payload.get("indices", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("index_id") or item.get("stock_id") or "").upper() == normalized_index_id:
                index_snapshot = {key: _json_value(value) for key, value in item.items()}
                break
        if index_snapshot is None:
            missing.append("market_index_summary")
    except Exception as exc:
        warnings.append(f"Index summary unavailable: {exc}")
        missing.append("market_index_summary")

    market_chip: dict[str, Any] | None = None
    try:
        chip_row = get_latest_market_chip_daily(db, index_id=normalized_index_id)
        market_chip = _json_dict(market_chip_daily_to_dict(chip_row)) if chip_row is not None else None
        if market_chip is None:
            missing.append("market_chip_daily")
    except Exception as exc:
        warnings.append(f"Market chip context unavailable: {exc}")
        missing.append("market_chip_daily")

    contributions: dict[str, Any] | None = None
    try:
        contributions_payload = get_market_index_contributions(normalized_index_id, limit=10)
        contributions = {
            key: _json_value(value)
            for key, value in contributions_payload.items()
            if key not in {"positive", "negative"}
        }
        contributions["positive"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("positive", [])
            if isinstance(item, dict)
        ]
        contributions["negative"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("negative", [])
            if isinstance(item, dict)
        ]
    except Exception as exc:
        warnings.append(f"Index contribution context unavailable: {exc}")

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    as_of = _latest_date_string(
        [
            (charts.get("daily") or {}).get("to_date"),
            (index_snapshot or {}).get("time"),
            (index_snapshot or {}).get("as_of"),
            (market_chip or {}).get("trade_date"),
        ]
    )

    envelope = {
        "kind": "tw_index_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"index_id": normalized_index_id},
        "data": {
            "index": index_snapshot,
            "charts": charts,
            "intraday": intraday,
            "market_chip": market_chip,
            "contributions": contributions,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "market_index_daily_stat"},
            {"type": "table", "name": "market_chip_daily"},
            {"type": "derived", "name": "app.market.indices"},
            {"type": "external_or_cache", "name": "yahoo_finance_chart"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan futures context uses TAIFEX futures quote and bar tables, not stock_master or stock daily tables.",
    ]

    quote_rows = get_latest_taiwan_futures_quotes(db, symbols=[normalized_symbol], refresh=False)
    quote_dicts = [_json_dict(taiwan_futures_quote_to_dict(row)) for row in quote_rows]
    latest_quote = quote_dicts[0] if quote_dicts else None
    if latest_quote is None:
        missing.append("taiwan_futures_quote_snapshot")

    daily_rows = list_taiwan_futures_daily_bars(
        db=db,
        symbol=normalized_symbol,
        limit=max(bars, 1),
        active_only=True,
    )
    daily_dicts = [
        _json_dict(taiwan_futures_daily_bar_to_dict(row))
        for row in daily_rows
    ]
    daily_points = _normalize_technical_points([row for row in daily_dicts if isinstance(row, dict)])
    if not daily_points:
        missing.append("taiwan_futures_daily_bar")

    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    intraday_dicts: list[dict[str, Any]] = []
    intraday_points: list[dict[str, Any]] = []
    if include_intraday or normalized_horizon == "intraday":
        intraday_rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=normalized_symbol,
            limit=390,
        )
        intraday_dicts = [
            _json_dict(taiwan_futures_intraday_bar_to_dict(row))
            for row in intraday_rows
        ]
        intraday_points = _normalize_technical_points(
            [row for row in intraday_dicts if isinstance(row, dict)]
        )
        if not intraday_points:
            missing.append("taiwan_futures_intraday_bar")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily futures evidence is used as fallback context."
        )

    technical_reports: dict[str, Any] = {
        "daily": _technical_report_from_points(
            points=daily_points,
            timeframe="daily",
            asset_label=normalized_symbol,
        ),
    }
    if intraday_points:
        technical_reports["today"] = _technical_report_from_points(
            points=intraday_points,
            timeframe="today",
            asset_label=normalized_symbol,
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    daily_chart = _chart_from_points(timeframe="daily", points=daily_points)
    intraday_chart = _chart_from_points(timeframe="today", points=intraday_points)
    as_of = _latest_date_string(
        [
            (latest_quote or {}).get("quote_time"),
            daily_chart.get("to_date"),
            intraday_chart.get("to_date"),
        ]
    )

    envelope = {
        "kind": "tw_futures_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"symbol": normalized_symbol},
        "data": {
            "latest_quote": latest_quote,
            "quotes": quote_dicts,
            "daily_chart": daily_chart,
            "intraday_chart": intraday_chart if intraday_points else None,
            "daily_bars": daily_dicts,
            "intraday_bars": intraday_dicts,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "taiwan_futures_quote_snapshot"},
            {"type": "table", "name": "taiwan_futures_daily_bar"},
            {"type": "table", "name": "taiwan_futures_intraday_bar"},
            {"type": "derived", "name": "app.market.tw_futures"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_stock_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    bars: int = 120,
    revenue_months: int = 12,
    financial_quarters: int = 8,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []

    try:
        stock = stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = market_service.get_latest_stock_daily_price(db, normalized_stock_id)
    latest_institutional = market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    latest_revenue = market_service.get_latest_stock_monthly_revenue(db, normalized_stock_id)
    latest_financial = market_service.get_latest_stock_financial_metric(db, normalized_stock_id)
    shareholding = market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = market_service.list_stock_monthly_revenue_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(revenue_months, 1),
    )
    financial_history = market_service.list_stock_financial_metric_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(financial_quarters, 1),
    )
    chart = market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
    )
    branch_summary = get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=timeframe,
                include_intraday=False,
            )
        except Exception as exc:
            warnings.append(f"{timeframe.title()} technical report unavailable: {exc}")
            missing.append(f"technical_report.{timeframe}")

    if include_intraday or normalized_horizon == "intraday":
        try:
            technical_reports["today"] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe="today",
                include_intraday=include_intraday,
            )
        except Exception as exc:
            warnings.append(f"Today technical report unavailable: {exc}")
            missing.append("technical_report.today")

    if normalized_horizon == "intraday" and not include_intraday:
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
    )
    overnight_impact: dict[str, Any] | None = None

    if stock is not None:
        try:
            overnight_impact = build_us_overnight_impact_report(
                db=db,
                stock_id=normalized_stock_id,
            )
            for warning in overnight_impact.get("warnings") or []:
                warnings.append(f"US overnight impact warning: {warning}")
            if overnight_impact.get("missing"):
                warnings.append(
                    "US overnight impact is partial: "
                    + ", ".join(str(value) for value in overnight_impact.get("missing", [])[:5])
                )
        except Exception as exc:
            warnings.append(f"US overnight impact unavailable: {exc}")
            missing.append("us_overnight_tw_impact")

    if branch_summary.get("is_partial"):
        warnings.append(
            "Broker branch data is partial for the requested window: "
            f"{branch_summary.get('available_days')} / {branch_summary.get('requested_days')} days."
        )

    _add_missing(missing, "market_daily_price", latest_daily)
    _add_missing(missing, "institutional_trade_daily", latest_institutional)
    _add_missing(missing, "margin_trading_daily", latest_margin)
    _add_missing(missing, "shareholding_distribution_weekly", shareholding)
    _add_missing(missing, "monthly_revenue", latest_revenue)
    _add_missing(missing, "financial_metric_quarterly", latest_financial)
    _add_missing(missing, "broker_branch_trade_daily", branch_summary.get("buy_top") or branch_summary.get("sell_top"))
    _add_missing(missing, "us_overnight_tw_impact", overnight_impact)

    as_of = _latest_date_string(
        [
            getattr(latest_daily, "trade_date", None),
            getattr(latest_institutional, "trade_date", None),
            getattr(latest_margin, "trade_date", None),
            branch_summary.get("trade_date"),
            getattr(latest_revenue, "period", None),
            getattr(latest_financial, "report_date", None),
            overnight_impact.get("as_of") if isinstance(overnight_impact, dict) else None,
        ]
    )

    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "institutional_trade_daily"},
        {"type": "table", "name": "margin_trading_daily"},
        {"type": "table", "name": "shareholding_distribution_weekly"},
        {"type": "table", "name": "broker_branch_trade_daily"},
        {"type": "table", "name": "monthly_revenue"},
        {"type": "table", "name": "financial_metric_quarterly"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.calendar_status"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    market_calendar_status = build_taiwan_calendar_status()
    source_health = build_taiwan_source_health(
        db=db,
        stock_id=normalized_stock_id,
    )
    source_refs.append({"type": "derived", "name": "app.market.source_health"})
    decision_evidence = _stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=market_calendar_status,
        missing=missing,
        source_refs=source_refs,
    )

    envelope = {
        "kind": "stock_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "latest_daily": _row_dict(
                latest_daily,
                (
                    "trade_date",
                    "stock_id",
                    "stock_name",
                    "trade_volume",
                    "trade_value",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "price_change",
                    "transaction_count",
                ),
            ),
            "chart": {
                **chart,
                "from_date": _json_value(chart.get("from_date")),
                "to_date": _json_value(chart.get("to_date")),
                "points": [
                    {key: _json_value(value) for key, value in point.items()}
                    for point in chart.get("points", [])
                ],
            },
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "market_calendar_status": market_calendar_status,
            "source_health": source_health,
            "decision_evidence": decision_evidence,
            "overnight_impact": overnight_impact,
            "latest_institutional": _row_dict(
                latest_institutional,
                (
                    "trade_date",
                    "foreign_investor_net",
                    "investment_trust_net",
                    "dealer_net",
                    "total_institutional_net",
                ),
            ),
            "latest_margin": _row_dict(
                latest_margin,
                (
                    "trade_date",
                    "margin_buy",
                    "margin_sell",
                    "margin_today_balance",
                    "short_sale",
                    "short_covering",
                    "short_today_balance",
                ),
            ),
            "latest_shareholding": [
                _row_dict(
                    row,
                    (
                        "data_date",
                        "holding_level",
                        "holder_count",
                        "share_count",
                        "share_ratio",
                    ),
                )
                for row in shareholding
            ],
            "broker_branch": {
                **branch_summary,
                "trade_date": _json_value(branch_summary.get("trade_date")),
                "trade_dates": [_json_value(value) for value in branch_summary.get("trade_dates", [])],
                "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])],
                "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])],
            },
            "latest_revenue": _row_dict(
                latest_revenue,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            ),
            "revenue_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "monthly_revenue",
                        "month_over_month_pct",
                        "year_over_year_pct",
                        "cumulative_revenue",
                        "cumulative_year_over_year_pct",
                    ),
                )
                for row in revenue_history
            ],
            "latest_financial": _row_dict(
                latest_financial,
                (
                    "period",
                    "report_date",
                    "revenue",
                    "gross_profit",
                    "operating_income",
                    "net_income",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            ),
            "financial_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "report_date",
                        "revenue",
                        "gross_profit",
                        "operating_income",
                        "net_income",
                        "eps",
                        "book_value_per_share",
                        "roe",
                        "roa",
                    ),
                )
                for row in financial_history
            ],
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
    radar_mode: str = "action",
    radar_limit: int = 12,
) -> dict[str, Any]:
    group = watchlist_service.get_group(db=db, group_id=group_id)
    ranking = ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        use_intraday=False,
    )
    radar = radar_service.build_watchlist_radar_from_ranking(
        ranking=ranking,
        include_children=include_children,
        mode=radar_mode,
        max_results=max(1, min(int(radar_limit or 12), 200)),
    )
    radar["group_id"] = group_id
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context and radar use local daily indicator data and do not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")
    if radar.get("error_count"):
        missing.append("watchlist_radar_error_items")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])
    radar_as_of = _latest_date_string(
        [item.get("time") or item.get("trade_date") for item in radar.get("results", [])]
    )

    envelope = {
        "kind": "watchlist_context",
        "generated_at": _now(),
        "as_of": ranked_as_of or radar_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
            "radar_mode": radar.get("mode") or radar_mode,
        },
        "data": {
            "ranking": ranking,
            "radar": radar,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "service", "name": "watchlist_radar"},
        ],
    }
    return _with_evidence_passport(envelope)
