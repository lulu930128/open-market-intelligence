from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import agentic_common, freshness
from app.ai import llm, progress_events
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import (
    intraday_point_limit as _market_intraday_point_limit,
    payload_level as _market_payload_level,
)
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
    latest_timestamp_from_rows as _latest_timestamp_from_rows,
)
from app.ai.market_context import jp_context, regional_params, us_context
from app.db.models import (
    JPStockMaster,
    KRStockMaster,
    USDailyPrice,
    USCompanyProfile,
    USSecCompanyFact,
    USStockMaster,
)
from app.crypto_market import service as crypto_market_service
from app.crypto_market.assets import get_crypto_asset
from app.crypto_market.contract import PERPETUAL, SPOT, list_provider_instruments, normalize_symbol as normalize_crypto_symbol
from app.crypto_market.source_health import build_crypto_source_health
from app.jp_market import service as jp_market_service
from app.jp_market.sources import normalize_jp_symbol
from app.kr_market import service as kr_market_service
from app.kr_market.sources import KR_INDEX_CONFIG_BY_ID, normalize_kr_index_id, normalize_kr_symbol
from app.market.overnight_impact import scan_us_overnight_impact_gaps
from app.market import stock_selection_refresh
from app.us_market import service as us_market_service
from app.us_market.sources import normalize_us_symbol
from app.watchlists import backfill_service as watchlist_backfill_service


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


_now = agentic_common._now
_today = agentic_common._today


def _emit_tool_progress(
    progress_callback: progress_events.ProgressCallback | None,
    *,
    tool_name: str,
    status: str,
    reason: Any = None,
    external_fetch: bool | None = None,
    writes_cache: bool | None = None,
    error: Any = None,
    duration_ms: int | None = None,
) -> None:
    status_text = {
        "running": "執行中",
        "success": "已完成",
        "blocked": "已阻擋",
        "skipped": "已略過",
        "error": "失敗",
    }.get(status, status)
    progress_events.emit_progress(
        progress_callback,
        stage="tool_execution",
        message=f"{tool_name} {status_text}。",
        phase={
            "running": "running",
            "success": "completed",
            "blocked": "blocked",
            "skipped": "skipped",
            "error": "failed",
        }.get(status, "completed"),
        dedupe_key=f"tool:{tool_name}:{status}",
        tool=tool_name,
        status=status,
        reason=reason,
        external_fetch=external_fetch,
        writes_cache=writes_cache,
        error=str(error) if error else None,
        duration_ms=duration_ms,
    )


_age_days = agentic_common._age_days
_json_value = agentic_common._json_value
_json_ready = agentic_common._json_ready
_row_dict = agentic_common._row_dict
_list_rows = agentic_common._list_rows
_safe_int = agentic_common._safe_int
_safe_float = agentic_common._safe_float
_optional_bool = agentic_common._optional_bool


def normalize_tool_budget(raw_budget: dict[str, Any] | None) -> dict[str, int]:
    raw_budget = raw_budget if isinstance(raw_budget, dict) else {}
    return {
        "max_calls": _safe_int(
            raw_budget.get("max_calls"),
            DEFAULT_TOOL_BUDGET["max_calls"],
            minimum=0,
            maximum=MAX_TOOL_CALLS,
        ),
        "max_external_fetches": _safe_int(
            raw_budget.get("max_external_fetches"),
            DEFAULT_TOOL_BUDGET["max_external_fetches"],
            minimum=0,
            maximum=MAX_EXTERNAL_FETCHES,
        ),
        "max_total_seconds": _safe_int(
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


def _latest_us_daily_price(db: Session, symbol: str) -> USDailyPrice | None:
    return (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol == symbol)
        .order_by(USDailyPrice.trade_date.desc(), USDailyPrice.id.desc())
        .first()
    )


def _latest_profile(db: Session, symbol: str) -> USCompanyProfile | None:
    return us_market_service.get_us_company_profile(db=db, symbol=symbol)


def _sec_metric_count(db: Session, symbol: str) -> int:
    return int(
        db.query(func.count(USSecCompanyFact.id))
        .filter(USSecCompanyFact.symbol == symbol)
        .scalar()
        or 0
    )


def scan_us_stock_gaps(db: Session, symbol: str, *, question: str = "") -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    latest_daily = _latest_us_daily_price(db, normalized_symbol)
    profile = _latest_profile(db, normalized_symbol)
    sec_metric_count = _sec_metric_count(db, normalized_symbol)
    missing: list[str] = []
    warnings: list[str] = []
    expected_dates: dict[str, Any] = {}

    today = _today()
    latest_daily_date = latest_daily.trade_date if latest_daily else None
    expected_dates["us_daily_price_latest"] = _json_value(latest_daily_date)
    if latest_daily_date is None:
        missing.append("us_daily_price")
    elif (today - latest_daily_date).days > US_DAILY_STALE_DAYS:
        missing.append("us_daily_price")
        warnings.append("US daily price cache is stale for the requested symbol.")

    profile_fetched_at = profile.fetched_at if profile else None
    expected_dates["us_company_profile_fetched_at"] = _json_value(profile_fetched_at)
    if profile is None:
        missing.append("us_company_profile")
    elif profile_fetched_at and _age_days(profile_fetched_at) > PROFILE_STALE_DAYS:
        missing.append("us_company_profile")
        warnings.append("US company profile cache is older than the configured freshness window.")

    expected_dates["us_sec_fact_count"] = sec_metric_count
    if sec_metric_count <= 0:
        missing.append("us_sec_company_fact")

    lowered_question = question.lower()
    if any(hint in lowered_question for hint in ("intraday", "premarket", "after-hours", "盤中", "即時", "最新", "adr")):
        missing.append("us_intraday_trend")

    is_current = "us_daily_price" not in missing and "us_company_profile" not in missing and "us_sec_company_fact" not in missing
    return {
        "kind": "us_stock_freshness",
        "scope": {"target": {"type": "us_stock", "id": normalized_symbol, "market": "US"}},
        "is_current": is_current,
        "stale_stock_count": 0 if is_current else 1,
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "expected_dates": expected_dates,
        "refresh_recommended": bool(missing),
        "refresh_endpoint": "/api/ai/ask",
        "refresh_params": {
            "target": {"type": "us_stock", "id": normalized_symbol},
            "allow_external_fetch": True,
        },
    }


def attach_us_overnight_gaps_to_tw_stock_freshness(
    db: Session,
    *,
    stock_id: str,
    stock_freshness: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(stock_freshness)
    try:
        overnight_gaps = scan_us_overnight_impact_gaps(db=db, stock_id=stock_id)
    except Exception as exc:
        warnings = list(merged.get("warnings") or [])
        warnings.append(f"美股隔夜影響 freshness 檢查失敗：{exc}")
        merged["warnings"] = list(dict.fromkeys(warnings))
        return merged

    cross_market = dict(merged.get("cross_market") or {})
    cross_market["us_overnight_impact"] = overnight_gaps
    merged["cross_market"] = cross_market

    if overnight_gaps.get("refresh_recommended"):
        missing = list(merged.get("missing") or [])
        missing.append("us_overnight_tw_impact")
        merged["missing"] = list(dict.fromkeys(missing))
        warnings = list(merged.get("warnings") or [])
        warnings.extend(overnight_gaps.get("warnings") or [])
        merged["warnings"] = list(dict.fromkeys(warnings))
        expected_dates = dict(merged.get("expected_dates") or {})
        expected_dates["us_overnight_impact"] = (
            overnight_gaps.get("expected_dates") or {}
        ).get("us_daily_price")
        merged["expected_dates"] = expected_dates
        merged["is_current"] = False
        merged["refresh_recommended"] = True

    return merged


def _fallback_plan(*, symbol: str, gaps: dict[str, Any], question: str) -> dict[str, Any]:
    missing = set(gaps.get("missing") or [])
    lowered_question = question.lower()
    steps: list[dict[str, Any]] = []

    if "us_intraday_trend" in missing:
        steps.append(
            {
                "tool": "us.read_intraday_trend",
                "args": {"symbol": symbol},
                "reason": "The question asks for ADR/latest trading context.",
            }
        )

    if "us_daily_price" in missing:
        steps.append(
            {
                "tool": "us.refresh_daily_price",
                "args": {"symbol": symbol, "provider": "auto", "outputsize": "compact", "adjusted": False},
                "reason": "Local US daily price evidence is missing or stale.",
            }
        )

    if "us_company_profile" in missing:
        steps.append(
            {
                "tool": "us.refresh_company_profile",
                "args": {"symbol": symbol},
                "reason": "Local US company profile evidence is missing or stale.",
            }
        )

    if "us_sec_company_fact" in missing or any(hint in lowered_question for hint in ("fundamental", "sec", "財報", "基本面")):
        steps.append(
            {
                "tool": "us.refresh_sec_facts",
                "args": {"symbol": symbol},
                "reason": "Local SEC facts are missing or the question needs fundamentals.",
            }
        )
        steps.append(
            {
                "tool": "us.read_sec_fundamentals",
                "args": {"symbol": symbol},
                "reason": "Read normalized fundamentals after SEC fact refresh.",
            }
        )

    if any(hint in lowered_question for hint in ("dividend", "split", "股利", "拆股", "除息")):
        steps.append(
            {
                "tool": "us.refresh_corporate_actions",
                "args": {"symbol": symbol},
                "reason": "The question asks about dividends or splits.",
            }
        )

    return {
        "provider": "fallback",
        "reason": "Deterministic fallback selected tools from local freshness gaps.",
        "tool_plan": steps,
    }


def _overnight_daily_refresh_steps(overnight_gaps: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(overnight_gaps, dict):
        return []

    steps: list[dict[str, Any]] = []
    for symbol in overnight_gaps.get("refresh_symbols") or []:
        normalized_symbol = normalize_us_symbol(symbol)
        if not normalized_symbol:
            continue
        steps.append(
            {
                "tool": "us.refresh_daily_price",
                "args": {
                    "symbol": normalized_symbol,
                    "provider": "auto",
                    "outputsize": "compact",
                    "adjusted": False,
                },
                "reason": "美股隔夜影響核心因素資料缺漏或過期，先刷新本機美股日線快取。",
            }
        )

    return steps


def _fallback_tw_stock_plan(
    *,
    stock_id: str,
    gaps: dict[str, Any],
    overnight_gaps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    missing = set(gaps.get("missing") or [])
    tw_refresh_needed = bool(missing & TW_STOCK_REFRESH_KEYS)
    if gaps.get("refresh_recommended") and tw_refresh_needed:
        steps.append(
            {
                "tool": "tw.refresh_stock_evidence",
                "args": {
                    "stock_id": stock_id,
                    "include_today": None,
                    "sleep_seconds": 0.05,
                },
                "reason": "Local Taiwan stock evidence is stale or incomplete before answering.",
            }
        )

    steps.extend(_overnight_daily_refresh_steps(overnight_gaps))
    reason = "Deterministic fallback selected Taiwan stock refresh from local freshness gaps."
    if overnight_gaps and overnight_gaps.get("refresh_recommended"):
        reason = (
            "Deterministic fallback selected Taiwan stock refresh and US overnight factor refresh "
            "from local freshness gaps."
        )

    return {
        "provider": "fallback",
        "reason": reason,
        "tool_plan": steps,
    }


def _fallback_tw_watchlist_plan(
    *,
    group_id: int,
    gaps: dict[str, Any],
    include_children: bool,
    enabled_only: bool,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    refresh_params = gaps.get("refresh_params") if isinstance(gaps.get("refresh_params"), dict) else {}
    missing = set(gaps.get("missing") or [])
    if gaps.get("refresh_recommended") and "market_daily_price" in missing:
        steps.append(
            {
                "tool": "tw.refresh_watchlist_evidence",
                "args": {
                    "group_id": group_id,
                    "lookback_days": refresh_params.get("lookback_days", 14),
                    "include_today": refresh_params.get("include_today", False),
                    "include_children": refresh_params.get("include_children", include_children),
                    "enabled_only": refresh_params.get("enabled_only", enabled_only),
                    "sleep_seconds": min(float(refresh_params.get("sleep_seconds", 0.3) or 0.3), 0.3),
                    "skip_existing_months": refresh_params.get("skip_existing_months", True),
                },
                "reason": "Local Taiwan watchlist daily price evidence is stale or incomplete before answering.",
            }
        )

    reason = "Deterministic fallback selected Taiwan watchlist daily refresh from local freshness gaps."
    if gaps.get("refresh_recommended") and not steps:
        reason = (
            "Watchlist freshness gaps do not include daily price; skipped group daily refresh "
            "because full institutional/fundamental evidence is refreshed per stock."
        )

    return {
        "provider": "fallback",
        "reason": reason,
        "tool_plan": steps,
    }


def _planner_input(
    *,
    question: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    budget: dict[str, int],
    allowed_tool_prefix: str | None = None,
    allowed_tool_names: set[str] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "target": target,
        "freshness_gaps": {
            "missing": gaps.get("missing") or [],
            "warnings": gaps.get("warnings") or [],
            "expected_dates": gaps.get("expected_dates") or {},
        },
        "budget": budget,
        "allowed_tools": tool_definitions_for_llm(
            prefix=allowed_tool_prefix,
            names=allowed_tool_names,
        ),
        "rules": [
            "Use only allowed tool names.",
            "Prefer local evidence when current enough.",
            "Do not request broad market-wide refreshes from a single-stock question.",
            "Keep tool count within budget and avoid duplicate calls.",
        ],
    }


def _normalize_plan_step(step: dict[str, Any], *, default_symbol: str) -> dict[str, Any] | None:
    tool_name = str(step.get("tool") or "").strip()
    if not tool_name:
        return None

    raw_args = step.get("args") if isinstance(step.get("args"), dict) else {}
    args = dict(raw_args)
    symbol_source = args.get("symbol") or step.get("symbol")
    if not symbol_source and tool_name.startswith("us."):
        symbol_source = default_symbol
    symbol = normalize_us_symbol(symbol_source)
    if symbol:
        args["symbol"] = symbol
    stock_id = str(args.get("stock_id") or step.get("stock_id") or "").strip()
    if not stock_id and tool_name == "tw.refresh_stock_evidence":
        stock_id = str(args.get("symbol") or step.get("symbol") or default_symbol).strip()
    if stock_id:
        args["stock_id"] = stock_id
    group_id = str(args.get("group_id") or step.get("group_id") or "").strip()
    if group_id:
        args["group_id"] = group_id
    if step.get("provider") is not None and "provider" not in args:
        args["provider"] = str(step["provider"])
    if step.get("outputsize") is not None and "outputsize" not in args:
        args["outputsize"] = str(step["outputsize"])
    if step.get("adjusted") is not None and "adjusted" not in args:
        args["adjusted"] = bool(step["adjusted"])
    if step.get("series_id") is not None and "series_id" not in args:
        args["series_id"] = str(step["series_id"])
    if step.get("include_today") is not None and "include_today" not in args:
        args["include_today"] = bool(step["include_today"])
    if step.get("sleep_seconds") is not None and "sleep_seconds" not in args:
        args["sleep_seconds"] = step["sleep_seconds"]

    return {
        "tool": tool_name,
        "args": args,
        "reason": str(step.get("reason") or "").strip(),
    }


def _normalize_plan(raw_plan: dict[str, Any], *, default_symbol: str, provider: str) -> dict[str, Any]:
    raw_steps = raw_plan.get("tool_plan") if isinstance(raw_plan.get("tool_plan"), list) else []
    steps = [
        normalized
        for step in raw_steps
        if isinstance(step, dict)
        if (normalized := _normalize_plan_step(step, default_symbol=default_symbol)) is not None
    ]
    plan = {
        "provider": raw_plan.get("provider") or provider,
        "reason": str(raw_plan.get("reason") or "").strip(),
        "tool_plan": steps,
    }
    for key in ("response_id", "model", "usage"):
        if key in raw_plan:
            plan[key] = raw_plan[key]
    return plan


def plan_us_stock_tools(
    *,
    question: str,
    symbol: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    budget: dict[str, int],
    can_call_llm: bool,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized_symbol = normalize_us_symbol(symbol)

    if can_call_llm:
        try:
            raw_plan = llm.generate_tool_plan(
                _planner_input(
                    question=question,
                    target=target,
                    gaps=gaps,
                    budget=budget,
                    allowed_tool_prefix="us.",
                )
            )
            return _normalize_plan(raw_plan, default_symbol=normalized_symbol, provider="openai"), warnings
        except llm.OpenAILLMError as exc:
            warnings.append(f"OMI LLM tool planner failed; used deterministic fallback. Error: {exc}")

    return _normalize_plan(
        _fallback_plan(symbol=normalized_symbol, gaps=gaps, question=question),
        default_symbol=normalized_symbol,
        provider="fallback",
    ), warnings


def plan_tw_stock_tools(
    *,
    question: str,
    stock_id: str,
    target: dict[str, Any],
    gaps: dict[str, Any],
    overnight_gaps: dict[str, Any] | None = None,
    budget: dict[str, int],
    can_call_llm: bool,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized_stock_id = str(stock_id or "").strip()

    def with_overnight_steps(plan: dict[str, Any]) -> dict[str, Any]:
        overnight_steps = _overnight_daily_refresh_steps(overnight_gaps)
        if not overnight_steps:
            return plan
        existing = {
            (
                step.get("tool"),
                tuple(sorted((str(k), str(v)) for k, v in (step.get("args") or {}).items())),
            )
            for step in plan.get("tool_plan") or []
            if isinstance(step, dict)
        }
        for step in overnight_steps:
            key = (
                step.get("tool"),
                tuple(sorted((str(k), str(v)) for k, v in (step.get("args") or {}).items())),
            )
            if key not in existing:
                plan.setdefault("tool_plan", []).append(step)
                existing.add(key)
        if overnight_gaps and overnight_gaps.get("refresh_recommended"):
            plan["reason"] = (
                (plan.get("reason") or "Taiwan stock refresh plan.")
                + " Added deterministic US overnight factor refresh."
            )
        return plan

    if can_call_llm:
        try:
            raw_plan = llm.generate_tool_plan(
                _planner_input(
                    question=question,
                    target=target,
                    gaps=gaps,
                    budget=budget,
                    allowed_tool_prefix="tw.",
                    allowed_tool_names={"tw.refresh_stock_evidence"},
                )
            )
            return with_overnight_steps(
                _normalize_plan(raw_plan, default_symbol=normalized_stock_id, provider="openai")
            ), warnings
        except llm.OpenAILLMError as exc:
            warnings.append(f"OMI LLM tool planner failed; used deterministic fallback. Error: {exc}")

    return with_overnight_steps(
        _normalize_plan(
            _fallback_tw_stock_plan(
                stock_id=normalized_stock_id,
                gaps=gaps,
                overnight_gaps=overnight_gaps,
            ),
            default_symbol=normalized_stock_id,
            provider="fallback",
        )
    ), warnings


def plan_tw_watchlist_tools(
    *,
    group_id: int,
    gaps: dict[str, Any],
    budget: dict[str, int],
    include_children: bool,
    enabled_only: bool,
) -> tuple[dict[str, Any], list[str]]:
    del budget
    return _normalize_plan(
        _fallback_tw_watchlist_plan(
            group_id=group_id,
            gaps=gaps,
            include_children=include_children,
            enabled_only=enabled_only,
        ),
        default_symbol=str(group_id),
        provider="fallback",
    ), []


def _compact_intraday_points(points: list[Any], *, max_points: int = 80) -> list[dict[str, Any]]:
    valid_points = [_json_ready(point) for point in points if isinstance(point, dict)]
    valid_points = [point for point in valid_points if isinstance(point, dict)]
    if len(valid_points) <= max_points:
        return valid_points

    last_index = len(valid_points) - 1
    indexes = {
        round(index * last_index / (max_points - 1))
        for index in range(max_points)
    }
    return [valid_points[index] for index in sorted(indexes)]


def _compact_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"value": _json_value(value)}

    keys = (
        "status",
        "provider",
        "symbol",
        "stock_id",
        "series_id",
        "trade_date",
        "daily_price_date",
        "institutional_trade_date",
        "margin_trade_date",
        "fetched_count",
        "inserted_count",
        "updated_count",
        "requested_count",
        "requested_stock_count",
        "refreshed_count",
        "current_count",
        "success_count",
        "warning_count",
        "skipped_count",
        "error_count",
        "target_date",
        "lookback_days",
        "point_count",
        "previous_close",
        "previous_close_source",
        "previous_close_trade_date",
        "previous_close_provider",
        "session_scope",
        "session_phase",
        "has_extended_hours",
        "regular_point_count",
        "extended_point_count",
        "regular_session_close",
        "regular_session_close_time",
        "source",
        "source_url",
        "metric_count",
        "message",
    )
    summary = {key: _json_value(value.get(key)) for key in keys if key in value}
    if "points" in value and isinstance(value["points"], list):
        points = _compact_intraday_points(value["points"])
        summary["returned_point_count"] = len(points)
        summary["points"] = points
        if points:
            summary["latest_point"] = points[-1]
        if "point_count" not in summary:
            summary["point_count"] = len(value["points"])
    if "metrics" in value and "metric_count" not in summary and isinstance(value["metrics"], list):
        summary["metric_count"] = len(value["metrics"])
    return summary


def _empty_tool_run(
    *,
    step: dict[str, Any],
    definition: ToolDefinition | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    now = _now().isoformat()
    return {
        "tool": step.get("tool"),
        "status": status,
        "reason": step.get("reason"),
        "arguments": step.get("args") or {},
        "external_fetch": bool(definition.external_fetch) if definition else False,
        "writes_cache": bool(definition.writes_cache) if definition else False,
        "result_summary": {},
        "error": error,
        "started_at": now,
        "ended_at": now,
        "duration_ms": 0,
    }


def _execute_tool(db: Session, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    symbol = normalize_us_symbol(args.get("symbol"))
    stock_id = str(args.get("stock_id") or "").strip()
    group_id_text = str(args.get("group_id") or "").strip()
    if tool_name == "tw.refresh_stock_evidence" and not stock_id:
        raise ValueError("stock_id is required for Taiwan stock tools.")
    if tool_name == "tw.refresh_watchlist_evidence" and not group_id_text:
        raise ValueError("group_id is required for Taiwan watchlist tools.")

    if tool_name.startswith("us.") and not symbol and tool_name != "us.refresh_macro_series":
        raise ValueError("symbol is required for US stock tools.")

    if tool_name == "tw.refresh_stock_evidence":
        sleep_seconds = _safe_float(args.get("sleep_seconds"), default=0.05, minimum=0.0, maximum=3.0)
        return stock_selection_refresh.refresh_selected_stock_data(
            db=db,
            stock_id=stock_id,
            include_today=_optional_bool(args.get("include_today")),
            sleep_seconds=sleep_seconds,
        )

    if tool_name == "tw.refresh_watchlist_evidence":
        sleep_seconds = _safe_float(args.get("sleep_seconds"), default=0.05, minimum=0.0, maximum=3.0)
        lookback_days = _safe_int(args.get("lookback_days"), default=14, minimum=1, maximum=365)
        include_today = _optional_bool(args.get("include_today"))
        include_children = _optional_bool(args.get("include_children"))
        enabled_only = _optional_bool(args.get("enabled_only"))
        skip_existing_months = _optional_bool(args.get("skip_existing_months"))
        return watchlist_backfill_service.refresh_watchlist_group_daily_prices(
            db=db,
            group_id=int(group_id_text),
            lookback_days=lookback_days,
            include_today=include_today if include_today is not None else False,
            include_children=include_children if include_children is not None else True,
            enabled_only=enabled_only if enabled_only is not None else True,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months if skip_existing_months is not None else True,
        )

    if tool_name == "us.read_intraday_trend":
        return us_market_service.get_us_intraday_trend(symbol=symbol)

    if tool_name == "us.refresh_daily_price":
        return us_market_service.refresh_us_daily_prices(
            db=db,
            symbol=symbol,
            provider=str(args.get("provider") or "auto"),
            outputsize=str(args.get("outputsize") or "compact"),
            adjusted=bool(args.get("adjusted", False)),
        )

    if tool_name == "us.refresh_company_profile":
        return us_market_service.refresh_us_company_profile_from_alphavantage(
            db=db,
            symbol=symbol,
        )

    if tool_name == "us.refresh_sec_facts":
        return us_market_service.refresh_us_sec_companyfacts(db=db, symbol=symbol)

    if tool_name == "us.read_sec_fundamentals":
        return us_market_service.get_us_sec_fundamental_summary(db=db, symbol=symbol)

    if tool_name == "us.refresh_corporate_actions":
        return us_market_service.refresh_us_corporate_actions_from_alphavantage(
            db=db,
            symbol=symbol,
        )

    raise ValueError(f"Unsupported OMI tool: {tool_name}")


def execute_tool_plan(
    *,
    db: Session,
    plan: dict[str, Any],
    budget: dict[str, int],
    can_external_fetch: bool,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    external_fetches = 0
    started = perf_counter()

    for step in plan.get("tool_plan") or []:
        if len(runs) >= budget["max_calls"]:
            warnings.append("OMI tool budget reached max_calls; remaining planned tools were skipped.")
            break

        if not isinstance(step, dict):
            continue

        tool_name = str(step.get("tool") or "").strip()
        definition = ALLOWED_TOOLS.get(tool_name)
        if definition is None:
            run = _empty_tool_run(
                step=step,
                definition=None,
                status="skipped",
                error=f"Tool is not in OMI allowlist: {tool_name}",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name or "unknown",
                status="skipped",
                reason=step.get("reason"),
                error=run.get("error"),
            )
            continue

        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        key = (
            tool_name,
            tuple(sorted((str(k), str(v)) for k, v in args.items())),
        )
        if key in seen:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="skipped",
                error="Duplicate tool call skipped.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="skipped",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue
        seen.add(key)

        if definition.external_fetch and not can_external_fetch:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="blocked",
                error="External fetch is not allowed by request/server policy.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="blocked",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue

        if definition.external_fetch and external_fetches >= budget["max_external_fetches"]:
            run = _empty_tool_run(
                step=step,
                definition=definition,
                status="skipped",
                error="External fetch budget reached.",
            )
            runs.append(run)
            _emit_tool_progress(
                progress_callback,
                tool_name=tool_name,
                status="skipped",
                reason=step.get("reason"),
                external_fetch=definition.external_fetch,
                writes_cache=definition.writes_cache,
                error=run.get("error"),
            )
            continue

        if perf_counter() - started > budget["max_total_seconds"]:
            warnings.append("OMI tool budget reached max_total_seconds; remaining planned tools were skipped.")
            break

        started_at = _now()
        started_tick = perf_counter()
        if definition.external_fetch:
            external_fetches += 1

        _emit_tool_progress(
            progress_callback,
            tool_name=tool_name,
            status="running",
            reason=step.get("reason"),
            external_fetch=definition.external_fetch,
            writes_cache=definition.writes_cache,
        )
        try:
            result = _execute_tool(db, tool_name, args)
            status = "success"
            error = None
        except Exception as exc:
            result = {}
            status = "error"
            error = str(exc)

        ended_at = _now()
        duration_ms = int((perf_counter() - started_tick) * 1000)
        run = {
            "tool": tool_name,
            "status": status,
            "reason": step.get("reason"),
            "arguments": args,
            "external_fetch": definition.external_fetch,
            "writes_cache": definition.writes_cache,
            "result_summary": _compact_result(result),
            "error": error,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": duration_ms,
        }
        runs.append(run)
        _emit_tool_progress(
            progress_callback,
            tool_name=tool_name,
            status=status,
            reason=step.get("reason"),
            external_fetch=definition.external_fetch,
            writes_cache=definition.writes_cache,
            error=error,
            duration_ms=duration_ms,
        )

    return runs, warnings


def run_us_stock_tool_session(
    *,
    db: Session,
    question: str,
    symbol: str,
    target: dict[str, Any],
    policy: dict[str, Any],
    raw_budget: dict[str, Any] | None,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    budget = normalize_tool_budget(raw_budget)
    gaps = scan_us_stock_gaps(db, normalized_symbol, question=question)
    plan_warnings: list[str] = []

    if budget["max_calls"] <= 0:
        return {
            "tool_plan": {
                "provider": "disabled",
                "reason": "OMI tool budget max_calls is 0.",
                "tool_plan": [],
                "budget": budget,
            },
            "tool_runs": [],
            "warnings": [],
            "freshness": gaps,
        }

    plan, plan_warnings = plan_us_stock_tools(
        question=question,
        symbol=normalized_symbol,
        target=target,
        gaps=gaps,
        budget=budget,
        can_call_llm=bool(policy.get("can_plan_tools")),
    )
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        progress_callback=progress_callback,
    )
    refreshed_gaps = scan_us_stock_gaps(db, normalized_symbol, question=question)
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": plan_warnings + run_warnings,
        "freshness": refreshed_gaps,
    }


def run_tw_stock_tool_session(
    *,
    db: Session,
    question: str,
    stock_id: str,
    target: dict[str, Any],
    policy: dict[str, Any],
    raw_budget: dict[str, Any] | None,
    existing_freshness: dict[str, Any] | None = None,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_stock_id = str(stock_id or "").strip()
    budget = normalize_tool_budget(raw_budget)
    gaps = existing_freshness or freshness.check_stock_data_freshness(
        db=db,
        stock_id=normalized_stock_id,
    )
    gaps = attach_us_overnight_gaps_to_tw_stock_freshness(
        db,
        stock_id=normalized_stock_id,
        stock_freshness=gaps,
    )
    overnight_gaps = (
        (gaps.get("cross_market") or {}).get("us_overnight_impact")
        if isinstance(gaps.get("cross_market"), dict)
        else None
    )

    if budget["max_calls"] <= 0:
        return {
            "tool_plan": {
                "provider": "disabled",
                "reason": "OMI tool budget max_calls is 0.",
                "tool_plan": [],
                "budget": budget,
            },
            "tool_runs": [],
            "warnings": [],
            "freshness": gaps,
        }

    plan, plan_warnings = plan_tw_stock_tools(
        question=question,
        stock_id=normalized_stock_id,
        target=target,
        gaps=gaps,
        overnight_gaps=overnight_gaps,
        budget=budget,
        can_call_llm=bool(policy.get("can_plan_tools")),
    )
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        progress_callback=progress_callback,
    )
    refreshed_gaps = freshness.check_stock_data_freshness(
        db=db,
        stock_id=normalized_stock_id,
    )
    refreshed_gaps = attach_us_overnight_gaps_to_tw_stock_freshness(
        db,
        stock_id=normalized_stock_id,
        stock_freshness=refreshed_gaps,
    )
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": plan_warnings + run_warnings,
        "freshness": refreshed_gaps,
    }


def run_tw_watchlist_tool_session(
    *,
    db: Session,
    group_id: int,
    target: dict[str, Any],
    policy: dict[str, Any],
    raw_budget: dict[str, Any] | None,
    existing_freshness: dict[str, Any] | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    del target
    budget = normalize_tool_budget(raw_budget)
    gaps = existing_freshness or freshness.check_watchlist_data_freshness(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )

    if budget["max_calls"] <= 0:
        return {
            "tool_plan": {
                "provider": "disabled",
                "reason": "OMI tool budget max_calls is 0.",
                "tool_plan": [],
                "budget": budget,
            },
            "tool_runs": [],
            "warnings": [],
            "freshness": gaps,
        }

    plan, plan_warnings = plan_tw_watchlist_tools(
        group_id=group_id,
        gaps=gaps,
        budget=budget,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    if gaps.get("refresh_recommended") and not plan.get("tool_plan"):
        plan_warnings.append(plan.get("reason") or "No Taiwan watchlist refresh tool was selected.")
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        progress_callback=progress_callback,
    )
    refreshed_gaps = freshness.check_watchlist_data_freshness(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": plan_warnings + run_warnings,
        "freshness": refreshed_gaps,
    }




def _market_data_param(params: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return regional_params._market_data_param(params, key, default)


def _market_data_int(params: dict[str, Any] | None, key: str, default: int, *, minimum: int, maximum: int) -> int:
    return regional_params._market_data_int(
        params,
        key,
        default,
        minimum=minimum,
        maximum=maximum,
    )


def _market_data_str(params: dict[str, Any] | None, key: str, default: str | None = None) -> str | None:
    return regional_params._market_data_str(params, key, default)


def _market_data_bool(params: dict[str, Any] | None, key: str, default: bool = False) -> bool:
    return regional_params._market_data_bool(params, key, default)


def read_us_stock_context(
    db: Session,
    *,
    symbol: str,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return us_context.read_us_stock_context(
        db=db,
        symbol=symbol,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
        dependencies=us_context.USContextDependencies(
            us_market_service=us_market_service,
            latest_profile=_latest_profile,
            scan_us_stock_gaps=scan_us_stock_gaps,
            now=_now,
        ),
    )


def read_jp_stock_context(
    db: Session,
    *,
    symbol: str,
    is_index: bool = False,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return jp_context.read_jp_stock_context(
        db=db,
        symbol=symbol,
        is_index=is_index,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
        dependencies=jp_context.JPContextDependencies(
            jp_market_service=jp_market_service,
            now=_now,
        ),
    )


def read_kr_stock_context(
    db: Session,
    *,
    symbol: str,
    is_index: bool = False,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_runs = tool_runs or []
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
    provider = _market_data_str(market_data_params, "provider", "auto") or "auto"
    payload_level = _market_payload_level(market_data_params)
    warnings: list[str] = [
        "Korea AI context is local-cache only; it does not fetch external data on the read path.",
    ]
    missing: list[str] = []
    source_refs: list[dict[str, Any]] = []
    stock: KRStockMaster | None = None
    daily_rows: list[Any] = []
    chart: dict[str, Any] = {}
    fundamentals: list[Any] = []
    investor_rows: list[Any] = []
    resource_summary: dict[str, Any] | None = None
    source_health: dict[str, Any] = {}

    if is_index:
        normalized_id = normalize_kr_index_id(symbol)
        index_config = KR_INDEX_CONFIG_BY_ID.get(normalized_id)
        if index_config is None:
            missing.append("kr_market_index")
            warnings.append(f"Unsupported KR index id: {symbol}.")
        try:
            chart = kr_market_service.list_kr_index_ohlc_chart_data(
                db=db,
                index_id=normalized_id,
                timeframe=timeframe,
                bars=bars,
                ensure_history=False,
                outputsize="compact",
            )
        except Exception as exc:
            missing.append("kr_index_daily_price")
            warnings.append(f"KR index OHLC chart unavailable: {exc}")

        chart_points = chart.get("points") if isinstance(chart, dict) else []
        if not chart_points and "kr_index_daily_price" not in missing:
            missing.append("kr_index_daily_price")
        latest_point = chart_points[-1] if chart_points else None
        latest_trade_date = _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
        latest_close = latest_point.get("close") if isinstance(latest_point, dict) else None
        latest_volume = latest_point.get("volume") if isinstance(latest_point, dict) else None
        label = (
            index_config.short_name or index_config.name
            if index_config is not None
            else normalized_id
        )
        target = {"type": "kr_index", "id": normalized_id, "label": label, "market": "KR"}
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_market_index"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_index_daily_price"})
        data = {
            "stock": None,
            "daily_prices": [],
            "chart": _json_ready(chart),
            "fundamentals": [],
            "investor_trading": [],
            "resource_summary": None,
            "source_health": {},
            "tool_runs": tool_runs,
        }
    else:
        normalized_id = normalize_kr_symbol(symbol)
        stock = (
            db.query(KRStockMaster)
            .filter(KRStockMaster.symbol == normalized_id)
            .first()
        )
        if stock is None:
            missing.append("kr_stock_master")
            warnings.append("KR stock master row is missing; symbol-level cached evidence is still returned when available.")

        try:
            daily_rows = kr_market_service.list_kr_daily_prices(
                db=db,
                symbol=normalized_id,
                provider=None if provider == "auto" else provider,
                limit=10,
            )
        except Exception as exc:
            missing.append("kr_daily_price")
            warnings.append(f"KR daily prices unavailable: {exc}")

        try:
            chart = kr_market_service.list_kr_ohlc_chart_data(
                db=db,
                symbol=normalized_id,
                timeframe=timeframe,
                bars=bars,
                ensure_history=False,
                outputsize="compact",
                provider=provider,
            )
        except Exception as exc:
            if "kr_daily_price" not in missing:
                missing.append("kr_daily_price")
            warnings.append(f"KR OHLC chart unavailable: {exc}")

        try:
            fundamentals = kr_market_service.list_kr_company_fundamentals(
                db=db,
                symbol=normalized_id,
                limit=20,
            )
        except Exception as exc:
            missing.append("kr_company_fundamental")
            warnings.append(f"KR company fundamentals unavailable: {exc}")

        try:
            investor_rows = kr_market_service.list_kr_investor_trades(
                db=db,
                symbol=normalized_id,
                limit=10,
            )
        except Exception as exc:
            missing.append("kr_investor_trade_daily")
            warnings.append(f"KR investor trading unavailable: {exc}")

        try:
            resource_summary = kr_market_service.get_kr_resource_summary(
                db=db,
                symbol=normalized_id,
            )
        except Exception as exc:
            warnings.append(f"KR resource summary unavailable: {exc}")

        try:
            source_health = kr_market_service.build_kr_source_health(
                db=db,
                symbol=normalized_id,
            )
        except Exception as exc:
            warnings.append(f"KR source health unavailable: {exc}")

        if not daily_rows and not (chart.get("points") if isinstance(chart, dict) else None):
            if "kr_daily_price" not in missing:
                missing.append("kr_daily_price")
        if not fundamentals and "kr_company_fundamental" not in missing:
            missing.append("kr_company_fundamental")
        if not investor_rows and "kr_investor_trade_daily" not in missing:
            missing.append("kr_investor_trade_daily")

        latest_daily = daily_rows[0] if daily_rows else None
        chart_points = chart.get("points") if isinstance(chart, dict) else []
        latest_point = chart_points[-1] if chart_points else None
        latest_trade_date = (
            latest_daily.trade_date.isoformat()
            if latest_daily is not None
            else _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
        )
        latest_close = (
            latest_daily.adjusted_close if latest_daily and latest_daily.adjusted_close is not None
            else latest_daily.close_price if latest_daily is not None
            else latest_point.get("close") if isinstance(latest_point, dict) else None
        )
        latest_volume = (
            latest_daily.trade_volume
            if latest_daily is not None
            else latest_point.get("volume") if isinstance(latest_point, dict) else None
        )
        label = (
            stock.security_name
            if stock and stock.security_name
            else stock.security_name_kr
            if stock and stock.security_name_kr
            else normalized_id
        )
        target = {"type": "kr_stock", "id": normalized_id, "label": label, "market": "KR"}
        for row in daily_rows[:3]:
            if row.source_url:
                source_refs.append(
                    {
                        "kind": "kr_daily_price",
                        "provider": row.provider,
                        "symbol": row.symbol,
                        "date": row.trade_date.isoformat(),
                        "url": row.source_url,
                    }
                )
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_stock_master"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_daily_price"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_company_fundamental"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "kr_investor_trade_daily"})
        _append_source_ref_once(source_refs, {"type": "derived", "name": "app.kr_market.source_health"})
        data = {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "local_code",
                    "security_name",
                    "security_name_kr",
                    "exchange",
                    "market_segment",
                    "sector",
                    "industry",
                    "asset_type",
                    "currency",
                    "exchange_timezone_name",
                    "is_active",
                    "last_seen_at",
                    "updated_at",
                ),
            ),
            "daily_prices": _list_rows(
                daily_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "currency",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "adjusted_close",
                    "price_change",
                    "change_pct",
                    "trade_volume",
                    "trade_value",
                    "market_cap",
                    "fetched_at",
                ),
            ),
            "chart": _json_ready(chart),
            "fundamentals": _list_rows(
                fundamentals,
                (
                    "provider",
                    "symbol",
                    "corp_code",
                    "stock_code",
                    "company_name",
                    "fiscal_year",
                    "report_code",
                    "report_name",
                    "statement_name",
                    "account_name",
                    "current_amount",
                    "previous_amount",
                    "currency",
                    "disclosed_date",
                    "fetched_at",
                ),
            ),
            "investor_trading": _list_rows(
                investor_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "investor_type",
                    "buy_value",
                    "sell_value",
                    "net_buy_value",
                    "buy_volume",
                    "sell_volume",
                    "net_buy_volume",
                    "fetched_at",
                ),
            ),
            "resource_summary": _json_ready(resource_summary),
            "source_health": _json_ready(source_health),
            "tool_runs": tool_runs,
        }

    data["compact"] = _compact_market_context(
        kind="kr_index_compact_evidence" if is_index else "kr_stock_compact_evidence",
        target=target,
        quote={
            "source": "kr_index_daily_price" if is_index else "kr_daily_price",
            "price": latest_close,
            "volume": latest_volume,
            "quote_time": latest_trade_date,
            "is_realtime": False,
            "provider": provider,
        },
        resources={
            "daily_rows": len(daily_rows),
            "chart_points": len(chart.get("points") or []) if isinstance(chart, dict) else 0,
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "fundamental_rows": len(fundamentals),
            "investor_trade_rows": len(investor_rows),
            "source_health": (source_health.get("summary") if isinstance(source_health, dict) else {}),
        },
        freshness={
            "price": "current" if latest_trade_date else "missing",
            "fundamentals": "current" if fundamentals else "missing" if not is_index else "not_applicable",
            "investor_trading": "current" if investor_rows else "missing" if not is_index else "not_applicable",
        },
        payload_level=payload_level,
    )
    envelope = {
        "kind": "kr_index_context" if is_index else "kr_stock_context",
        "generated_at": _now().isoformat(),
        "as_of": latest_trade_date,
        "scope": {"target": target},
        "summary": {
            "latest_close": latest_close,
            "latest_trade_date": latest_trade_date,
            "latest_volume": latest_volume,
            "source_health": source_health.get("summary") if isinstance(source_health, dict) else {},
        },
        "data": data,
        "data_limitations": [
            "No KR-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "KR context is based on bounded local-cache evidence unless a separate refresh endpoint is called.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    freshness_result = {
        "kind": "kr_index_freshness" if is_index else "kr_stock_freshness",
        "scope": {"target": target},
        "is_current": latest_trade_date is not None,
        "refresh_recommended": latest_trade_date is None,
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": latest_trade_date,
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=freshness_result,
        tool_runs=tool_runs,
    )
    return envelope


def _crypto_supported_symbols_for_asset(asset: str, *, instrument_type: str | None = None, resource: str = "ticker") -> list[str]:
    symbols: list[str] = []
    for instrument in list_provider_instruments(instrument_type=instrument_type, resource=resource):
        if instrument.base_asset != asset:
            continue
        if instrument.symbol in symbols:
            continue
        symbols.append(instrument.symbol)
    return symbols


def _crypto_asset_from_symbol(symbol: str | None) -> str | None:
    normalized = normalize_crypto_symbol(symbol)
    if "-" not in normalized:
        return normalized if get_crypto_asset(normalized) is not None else None
    base = normalized.split("-", maxsplit=1)[0]
    return base if get_crypto_asset(base) is not None else None


def _crypto_requested_symbols(
    *,
    asset: str | None,
    market_data_params: dict[str, Any] | None,
    instrument_type: str | None,
) -> list[str] | None:
    symbols_value = _market_data_param(market_data_params, "symbols")
    if symbols_value is None:
        symbols_value = _market_data_param(market_data_params, "symbol")
    if symbols_value:
        if isinstance(symbols_value, str):
            return [normalize_crypto_symbol(part) for part in symbols_value.split(",") if part.strip()]
        if isinstance(symbols_value, (list, tuple)):
            return [normalize_crypto_symbol(part) for part in symbols_value if str(part).strip()]

    if asset:
        supported = _crypto_supported_symbols_for_asset(
            asset,
            instrument_type=instrument_type,
            resource="ticker",
        )
        return supported or [f"{asset}-USDT"]
    return None


def read_crypto_context(
    db: Session,
    *,
    asset: str | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    context_limit: int = 100,
) -> dict[str, Any]:
    tool_runs = tool_runs or []
    requested_asset = str(asset or "").strip().upper() or None
    params_symbol = _market_data_str(market_data_params, "symbol")
    if requested_asset is None and params_symbol:
        requested_asset = _crypto_asset_from_symbol(params_symbol)
    asset_definition = get_crypto_asset(requested_asset) if requested_asset else None
    if requested_asset and asset_definition is None:
        warnings = [f"Unsupported crypto asset: {requested_asset}."]
        target = {"type": "crypto_asset", "id": requested_asset, "label": requested_asset, "market": "crypto"}
        payload_level = _market_payload_level(market_data_params)
        envelope = {
            "kind": "crypto_asset_context",
            "generated_at": _now().isoformat(),
            "as_of": None,
            "scope": {"target": target},
            "summary": {},
            "data": {"compact": _compact_market_context(kind="crypto_asset_compact_evidence", target=target, quote={}, resources={}, freshness={}, payload_level=payload_level)},
            "missing": ["crypto_asset"],
            "warnings": warnings,
            "source_refs": [],
        }
        envelope["evidence_passport"] = build_evidence_passport(
            kind="crypto_asset_context",
            missing=envelope["missing"],
            warnings=warnings,
            confidence="low",
            tool_runs=tool_runs,
        )
        return envelope

    normalized_asset = asset_definition.asset if asset_definition else None
    instrument_type = _market_data_str(market_data_params, "instrument_type")
    provider = _market_data_str(market_data_params, "provider")
    interval = _market_data_str(market_data_params, "interval", "1m") or "1m"
    limit = _market_data_int(market_data_params, "limit", min(context_limit, 100), minimum=1, maximum=500)
    payload_level = _market_payload_level(market_data_params)
    history_limit = min(limit, 100)
    requested_symbols = _crypto_requested_symbols(
        asset=normalized_asset,
        market_data_params=market_data_params,
        instrument_type=instrument_type,
    )
    derivative_symbols = (
        _crypto_supported_symbols_for_asset(normalized_asset, instrument_type=PERPETUAL, resource="derivatives")
        if normalized_asset
        else None
    )
    if normalized_asset and not derivative_symbols and normalized_asset != "USDT":
        derivative_symbols = [f"{normalized_asset}-USDT"]

    warnings: list[str] = [
        "Crypto AI context is read-only local-cache evidence; refresh endpoints are separate bounded POST operations.",
    ]
    missing: list[str] = []
    source_refs: list[dict[str, Any]] = []

    tickers = crypto_market_service.list_latest_crypto_tickers(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=limit,
    )
    order_books = crypto_market_service.list_latest_crypto_order_books(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=limit,
    )
    ohlcv_rows = crypto_market_service.list_latest_crypto_ohlcv_bars(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type or SPOT,
        interval=interval,
        limit=limit,
    )
    coverage = crypto_market_service.list_crypto_ohlcv_coverage(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
    )
    derivatives = crypto_market_service.list_latest_crypto_derivatives(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        limit=limit,
    )
    market_caps = crypto_market_service.list_latest_crypto_market_caps(db, vs_currency="usd", limit=100)
    if normalized_asset:
        market_caps = [row for row in market_caps if row.symbol.upper() == normalized_asset]
    spreads = crypto_market_service.list_latest_crypto_spreads(
        db,
        base=normalized_asset,
        global_provider=provider,
        limit=limit,
    )
    ticker_history = crypto_market_service.list_crypto_ticker_history(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=history_limit,
        ascending=False,
    )
    liquidity_history = crypto_market_service.list_crypto_liquidity_history(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=history_limit,
        ascending=False,
    )
    derivatives_history = crypto_market_service.list_crypto_derivatives_history(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=history_limit,
        ascending=False,
    )
    long_short_history = crypto_market_service.list_crypto_long_short_ratio_history(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=history_limit,
        ascending=False,
    )
    liquidation_heatmap = crypto_market_service.list_crypto_liquidation_heatmap_cells(
        db,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=min(history_limit, 200),
        ascending=False,
    )
    provider_contract = crypto_market_service.get_crypto_provider_contract()
    source_health = build_crypto_source_health(
        db,
        provider=provider,
        base=normalized_asset,
        required_only=False,
        include_events=False,
        max_entries=min(max(limit, 20), 100),
    )

    if not tickers:
        missing.append("crypto_ticker")
    if not order_books:
        missing.append("crypto_order_book")
    if not ohlcv_rows:
        missing.append("crypto_ohlcv")
    if normalized_asset and not market_caps and asset_definition and asset_definition.market_cap:
        missing.append("crypto_market_cap")

    for entry in source_health.get("entries") or []:
        if isinstance(entry, dict) and not entry.get("ok", True):
            warnings.append(
                f"Crypto source health {entry.get('status')}: {entry.get('resource')} {entry.get('provider')} {entry.get('target')} - {entry.get('reason')}"
            )

    primary_ticker = tickers[0] if tickers else None
    as_of = _latest_timestamp_from_rows(
        [*tickers, *order_books, *ohlcv_rows, *derivatives, *market_caps, *spreads],
        ("fetched_at", "event_time", "bar_time", "last_updated", "observed_at"),
    )
    target_id = normalized_asset if normalized_asset else "market"
    target_label = asset_definition.name if asset_definition else "Crypto Market"
    target_type = "crypto_asset" if normalized_asset else "crypto_market"
    target = {"type": target_type, "id": target_id, "label": target_label, "market": "crypto"}

    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_ticker_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_order_book_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_ohlcv_bar"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_derivatives_metric"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_market_cap_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_spread_snapshot"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.crypto_market.source_health"})
    data = {
        "provider_contract": {
            "kind": provider_contract.get("kind"),
            "execution_enabled": provider_contract.get("execution_enabled"),
            "ai_execution_enabled": provider_contract.get("ai_execution_enabled"),
            "notes": provider_contract.get("notes") or [],
            "ohlcv_intervals": provider_contract.get("ohlcv_intervals") or {},
            "selected_asset": asset_definition.to_dict() if asset_definition else None,
        },
        "latest_tickers": _list_rows(
            tickers,
            (
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "last_price",
                "bid_price",
                "ask_price",
                "high_24h",
                "low_24h",
                "price_change_24h",
                "price_change_pct_24h",
                "base_volume_24h",
                "quote_volume_24h",
                "event_time",
                "fetched_at",
            ),
        ),
        "order_books": _list_rows(
            order_books,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "depth_limit",
                "best_bid_price",
                "best_bid_size",
                "best_ask_price",
                "best_ask_size",
                "spread",
                "spread_pct",
                "event_time",
                "fetched_at",
            ),
        ),
        "ohlcv": _list_rows(
            ohlcv_rows,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "interval",
                "bar_time",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "base_volume",
                "quote_volume",
                "fetched_at",
            ),
        ),
        "ohlcv_coverage": _json_ready(coverage),
        "derivatives": _list_rows(
            derivatives,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "mark_price",
                "index_price",
                "funding_rate",
                "next_funding_time",
                "open_interest",
                "open_interest_value",
                "event_time",
                "fetched_at",
            ),
        ),
        "market_caps": _list_rows(
            market_caps,
            (
                "provider",
                "coin_id",
                "symbol",
                "name",
                "vs_currency",
                "current_price",
                "market_cap",
                "market_cap_rank",
                "total_volume",
                "price_change_pct_24h",
                "last_updated",
                "fetched_at",
            ),
        ),
        "spreads": _list_rows(
            spreads,
            (
                "base_asset",
                "local_provider",
                "global_provider",
                "local_symbol",
                "global_symbol",
                "fx_symbol",
                "local_price",
                "global_price",
                "fx_rate",
                "implied_twd_price",
                "spread",
                "spread_pct",
                "observed_at",
            ),
        ),
        "history": {
            "tickers": _list_rows(
                ticker_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "last_price",
                    "bid_price",
                    "ask_price",
                    "price_change_pct_24h",
                    "base_volume_24h",
                    "quote_volume_24h",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "liquidity": _list_rows(
                liquidity_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "depth_limit",
                    "best_bid_price",
                    "best_ask_price",
                    "spread",
                    "spread_pct",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "derivatives": _list_rows(
                derivatives_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "mark_price",
                    "funding_rate",
                    "open_interest",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "long_short_ratio": _list_rows(
                long_short_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "ratio_scope",
                    "long_ratio",
                    "short_ratio",
                    "long_short_ratio",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "liquidation_heatmap": _list_rows(
                liquidation_heatmap,
                (
                    "provider",
                    "source_kind",
                    "method",
                    "symbol",
                    "instrument_type",
                    "time_bucket",
                    "bucket_seconds",
                    "price_bucket",
                    "liquidation_side",
                    "liquidation_notional",
                    "event_count",
                    "intensity",
                    "fetched_at",
                ),
            ),
        },
        "source_health": _json_ready(source_health),
        "tool_runs": tool_runs,
    }
    data["compact"] = _compact_market_context(
        kind="crypto_asset_compact_evidence" if normalized_asset else "crypto_market_compact_evidence",
        target=target,
        quote={
            "source": "crypto_ticker_snapshot",
            "provider": primary_ticker.provider if primary_ticker else None,
            "symbol": primary_ticker.symbol if primary_ticker else None,
            "instrument_type": primary_ticker.instrument_type if primary_ticker else None,
            "price": primary_ticker.last_price if primary_ticker else None,
            "bid": primary_ticker.bid_price if primary_ticker else None,
            "ask": primary_ticker.ask_price if primary_ticker else None,
            "change_pct_24h": primary_ticker.price_change_pct_24h if primary_ticker else None,
            "quote_time": primary_ticker.event_time.isoformat() if primary_ticker and primary_ticker.event_time else None,
            "is_realtime": False,
        },
        resources={
            "ticker_rows": len(tickers),
            "order_book_rows": len(order_books),
            "ohlcv_rows": len(ohlcv_rows),
            "ohlcv_coverage_rows": len(coverage),
            "derivatives_rows": len(derivatives),
            "market_cap_rows": len(market_caps),
            "spread_rows": len(spreads),
            "history_rows": {
                "ticker": len(ticker_history),
                "liquidity": len(liquidity_history),
                "derivatives": len(derivatives_history),
                "long_short_ratio": len(long_short_history),
                "liquidation_heatmap": len(liquidation_heatmap),
            },
            "provider": provider,
            "symbols": requested_symbols,
            "interval": interval,
            "limit": limit,
            "payload_level": payload_level,
        },
        freshness={
            "quote": "current" if tickers else "missing",
            "order_book": "current" if order_books else "missing",
            "ohlcv": "current" if ohlcv_rows else "missing",
            "source_health": source_health.get("summary"),
        },
        payload_level=payload_level,
    )
    envelope = {
        "kind": "crypto_asset_context" if normalized_asset else "crypto_market_context",
        "generated_at": _now().isoformat(),
        "as_of": as_of,
        "scope": {"target": target},
        "summary": {
            "latest_price": primary_ticker.last_price if primary_ticker else None,
            "latest_symbol": primary_ticker.symbol if primary_ticker else None,
            "latest_provider": primary_ticker.provider if primary_ticker else None,
            "latest_fetched_at": primary_ticker.fetched_at.isoformat() if primary_ticker else None,
            "source_health": source_health.get("summary"),
        },
        "data": data,
        "data_limitations": [
            "GET/read paths use local cache only; POST refresh endpoints are required for external data fetch.",
            "Crypto contract is watch/research only and exposes no order placement endpoint.",
            "Event-driven resources such as liquidations can be empty without implying provider failure.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    freshness_result = {
        "kind": "crypto_asset_freshness" if normalized_asset else "crypto_market_freshness",
        "scope": {"target": target},
        "is_current": bool(tickers or ohlcv_rows or market_caps),
        "refresh_recommended": bool(missing),
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": as_of,
        "source_health": source_health.get("summary"),
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=freshness_result,
        tool_runs=tool_runs,
    )
    return envelope
