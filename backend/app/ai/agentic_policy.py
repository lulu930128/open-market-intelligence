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
US_DAILY_STALE_DAYS = 5
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
