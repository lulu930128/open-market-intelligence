from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

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
from app.market import service as market_service
from app.market.broker_branch import get_broker_branch_trade_summary
from app.stocks import service as stock_service
from app.watchlists import ranking_service
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


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    tool_list = [
            {
                "name": "omi.ask",
                "title": "Ask OMI",
                "description": (
                    "Single OMI entry point. It chooses data_only, brief, or report mode "
                    "from a question and policy flags."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "scope_type": {
                            "type": "string",
                            "enum": ["auto", "market", "data_freshness", "stock", "watchlist"],
                            "default": "auto",
                        },
                        "scope_id": {"type": "string"},
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
                            "description": "Caller label only. Server-side policy decides trust.",
                        },
                        "allow_llm": {
                            "type": "boolean",
                            "default": False,
                            "description": "Must be true for report mode and requires server-side trust.",
                        },
                        "allow_write": {"type": "boolean", "default": False},
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
                    },
                    "required": ["stock_id"],
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
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
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
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
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
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
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

    return {
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


def read_market_overview(db: Session, limit: int = 10) -> dict[str, Any]:
    latest_trade_date = market_service.get_latest_trade_date(db)
    missing: list[str] = []

    if latest_trade_date is None:
        return {
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

    rows = market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
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
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    return {
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
                "total_count": len(rows),
                "trade_value": total_trade_value,
            },
            "top_gainers": top_gainers,
            "top_losers": top_losers,
        },
        "missing": missing,
        "warnings": [
            "This overview uses the latest local daily market rows and does not fetch live quotes.",
        ],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
    }


def read_stock_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    bars: int = 120,
    revenue_months: int = 12,
    financial_quarters: int = 8,
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

    as_of = _latest_date_string(
        [
            getattr(latest_daily, "trade_date", None),
            getattr(latest_institutional, "trade_date", None),
            getattr(latest_margin, "trade_date", None),
            branch_summary.get("trade_date"),
            getattr(latest_revenue, "period", None),
            getattr(latest_financial, "report_date", None),
        ]
    )

    return {
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
        "source_refs": [
            {"type": "table", "name": "stock_master"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "table", "name": "institutional_trade_daily"},
            {"type": "table", "name": "margin_trading_daily"},
            {"type": "table", "name": "shareholding_distribution_weekly"},
            {"type": "table", "name": "broker_branch_trade_daily"},
            {"type": "table", "name": "monthly_revenue"},
            {"type": "table", "name": "financial_metric_quarterly"},
        ],
    }


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
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
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context uses local daily indicator data and does not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])

    return {
        "kind": "watchlist_context",
        "generated_at": _now(),
        "as_of": ranked_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
        },
        "data": {
            "ranking": ranking,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
        ],
    }
