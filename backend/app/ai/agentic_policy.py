from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai import agentic_common, freshness


DEFAULT_TOOL_BUDGET = {
    "max_calls": 5,
    "max_external_fetches": 3,
    "max_total_seconds": 25,
}
MAX_TOOL_CALLS = 12
MAX_EXTERNAL_FETCHES = 8
MAX_TOTAL_SECONDS = 90
PROFILE_STALE_DAYS = 30
TW_STOCK_REFRESH_KEYS = {
    freshness.STOCK_MASTER_DATASET["key"],
    *(spec.key for spec in freshness.DATASET_SPECS),
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    external_fetch: bool = False
    writes_cache: bool = False


ALLOWED_TOOLS: dict[str, ToolDefinition] = {
    "tw.refresh_stock_evidence": ToolDefinition(
        name="tw.refresh_stock_evidence",
        description=(
            "Refresh the selected Taiwan stock evidence pack: daily price, institutional trade, "
            "margin trading, broker branch, shareholding, monthly revenue, and financial metrics."
        ),
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_watchlist_evidence": ToolDefinition(
        name="tw.refresh_watchlist_evidence",
        description=(
            "Refresh the selected Taiwan watchlist/group daily price evidence used by ranking "
            "and sector breadth. Full institutional/fundamental evidence remains per-stock."
        ),
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_daily_price": ToolDefinition(
        name="tw.refresh_daily_price",
        description="Refresh daily OHLCV cache for one Taiwan stock.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_institutional": ToolDefinition(
        name="tw.refresh_institutional",
        description="Refresh institutional-flow cache for one Taiwan stock and one expected date.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_margin": ToolDefinition(
        name="tw.refresh_margin",
        description="Refresh margin-trading cache for one Taiwan stock and one expected date.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_broker_branch": ToolDefinition(
        name="tw.refresh_broker_branch",
        description="Refresh broker-branch evidence for one Taiwan stock and one expected date.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_shareholding": ToolDefinition(
        name="tw.refresh_shareholding",
        description="Refresh bounded shareholding history for one Taiwan stock.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_revenue": ToolDefinition(
        name="tw.refresh_revenue",
        description="Refresh bounded monthly-revenue history for one Taiwan stock.",
        external_fetch=True,
        writes_cache=True,
    ),
    "tw.refresh_financials": ToolDefinition(
        name="tw.refresh_financials",
        description="Refresh bounded quarterly financial metrics for one Taiwan stock.",
        external_fetch=True,
        writes_cache=True,
    ),
    "cross_market.refresh_context": ToolDefinition(
        name="cross_market.refresh_context",
        description=(
            "Refresh the bounded cross-market context source set for one Taiwan stock, "
            "including required US daily prices, proxy benchmarks, and USD/TWD when applicable."
        ),
        external_fetch=True,
        writes_cache=True,
    ),
    "us.read_intraday_trend": ToolDefinition(
        name="us.read_intraday_trend",
        description="Fetch same-day Yahoo chart intraday trend for one US symbol.",
        external_fetch=True,
    ),
    "us.refresh_daily_price": ToolDefinition(
        name="us.refresh_daily_price",
        description="Refresh local daily OHLCV cache for one US symbol from configured provider.",
        external_fetch=True,
        writes_cache=True,
    ),
    "us.refresh_company_profile": ToolDefinition(
        name="us.refresh_company_profile",
        description="Refresh local Alpha Vantage company overview/profile for one US symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "us.refresh_sec_facts": ToolDefinition(
        name="us.refresh_sec_facts",
        description="Refresh local SEC EDGAR company facts for one US symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "us.refresh_insider_transactions": ToolDefinition(
        name="us.refresh_insider_transactions",
        description=(
            "Refresh a bounded set of SEC Form 4 insider transaction filings "
            "for one US symbol."
        ),
        external_fetch=True,
        writes_cache=True,
    ),
    "us.read_sec_fundamentals": ToolDefinition(
        name="us.read_sec_fundamentals",
        description="Read normalized SEC fundamental summary from local cache.",
    ),
    "us.refresh_corporate_actions": ToolDefinition(
        name="us.refresh_corporate_actions",
        description="Refresh local dividends and splits for one US symbol from Alpha Vantage.",
        external_fetch=True,
        writes_cache=True,
    ),
    "jp.read_intraday_trend": ToolDefinition(
        name="jp.read_intraday_trend",
        description="Fetch a bounded same-session Japan intraday trend for one symbol.",
        external_fetch=True,
    ),
    "jp.refresh_daily_price": ToolDefinition(
        name="jp.refresh_daily_price",
        description="Refresh bounded Japan daily OHLCV cache for one symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "kr.read_stock_intraday_trend": ToolDefinition(
        name="kr.read_stock_intraday_trend",
        description="Fetch a bounded same-session Korea stock intraday trend.",
        external_fetch=True,
        writes_cache=True,
    ),
    "kr.read_index_intraday_trend": ToolDefinition(
        name="kr.read_index_intraday_trend",
        description="Fetch a bounded same-session Korea index intraday trend.",
        external_fetch=True,
    ),
    "kr.refresh_daily_price": ToolDefinition(
        name="kr.refresh_daily_price",
        description="Refresh bounded Korea stock daily OHLCV cache.",
        external_fetch=True,
        writes_cache=True,
    ),
    "kr.refresh_index_daily_price": ToolDefinition(
        name="kr.refresh_index_daily_price",
        description="Refresh bounded Korea index daily OHLCV cache.",
        external_fetch=True,
        writes_cache=True,
    ),
    "crypto.refresh_ticker": ToolDefinition(
        name="crypto.refresh_ticker",
        description="Refresh one crypto ticker from one selected provider and symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "crypto.refresh_order_book": ToolDefinition(
        name="crypto.refresh_order_book",
        description="Refresh bounded order-book depth for one crypto provider and symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "crypto.refresh_ohlcv": ToolDefinition(
        name="crypto.refresh_ohlcv",
        description="Refresh one bounded crypto OHLCV interval for one provider and symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
    "crypto.refresh_derivatives": ToolDefinition(
        name="crypto.refresh_derivatives",
        description="Refresh derivatives metrics for one crypto provider and symbol.",
        external_fetch=True,
        writes_cache=True,
    ),
}


def normalize_tool_budget(raw_budget: dict[str, Any] | None) -> dict[str, int]:
    raw_budget = raw_budget if isinstance(raw_budget, dict) else {}
    return {
        "max_calls": agentic_common._safe_int(
            raw_budget.get("max_calls"),
            DEFAULT_TOOL_BUDGET["max_calls"],
            minimum=0,
            maximum=MAX_TOOL_CALLS,
        ),
        "max_external_fetches": agentic_common._safe_int(
            raw_budget.get("max_external_fetches"),
            DEFAULT_TOOL_BUDGET["max_external_fetches"],
            minimum=0,
            maximum=MAX_EXTERNAL_FETCHES,
        ),
        "max_total_seconds": agentic_common._safe_int(
            raw_budget.get("max_total_seconds"),
            DEFAULT_TOOL_BUDGET["max_total_seconds"],
            minimum=1,
            maximum=MAX_TOTAL_SECONDS,
        ),
    }


def tool_definitions_for_llm(
    prefix: str | None = None,
    names: set[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "external_fetch": definition.external_fetch,
            "writes_cache": definition.writes_cache,
        }
        for definition in ALLOWED_TOOLS.values()
        if prefix is None or definition.name.startswith(prefix)
        if names is None or definition.name in names
    ]
