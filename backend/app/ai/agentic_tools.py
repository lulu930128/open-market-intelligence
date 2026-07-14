from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import agentic_common, agentic_execution, agentic_planning, agentic_policy, freshness
from app.ai import progress_events
from app.ai.market_context import crypto_context, jp_context, kr_context, regional_params, us_context
from app.db.models import (
    USDailyPrice,
    USCompanyProfile,
    USSecCompanyFact,
)
from app.crypto_market import service as crypto_market_service
from app.crypto_market.assets import get_crypto_asset
from app.crypto_market.source_health import build_crypto_source_health
from app.jp_market import service as jp_market_service
from app.kr_market import service as kr_market_service
from app.market.overnight_impact import scan_us_overnight_impact_gaps
from app.us_market import service as us_market_service
from app.us_market.sources import normalize_us_symbol


DEFAULT_TOOL_BUDGET = agentic_policy.DEFAULT_TOOL_BUDGET
MAX_TOOL_CALLS = agentic_policy.MAX_TOOL_CALLS
MAX_EXTERNAL_FETCHES = agentic_policy.MAX_EXTERNAL_FETCHES
MAX_TOTAL_SECONDS = agentic_policy.MAX_TOTAL_SECONDS
US_DAILY_STALE_DAYS = agentic_policy.US_DAILY_STALE_DAYS
PROFILE_STALE_DAYS = agentic_policy.PROFILE_STALE_DAYS
TW_STOCK_REFRESH_KEYS = agentic_policy.TW_STOCK_REFRESH_KEYS
ToolDefinition = agentic_policy.ToolDefinition
ALLOWED_TOOLS = agentic_policy.ALLOWED_TOOLS


_now = agentic_common._now
_today = agentic_common._today


_emit_tool_progress = agentic_execution._emit_tool_progress

_age_days = agentic_common._age_days
_json_value = agentic_common._json_value


normalize_tool_budget = agentic_policy.normalize_tool_budget
tool_definitions_for_llm = agentic_policy.tool_definitions_for_llm


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


_fallback_plan = agentic_planning._fallback_plan
_overnight_daily_refresh_steps = agentic_planning._overnight_daily_refresh_steps
_fallback_tw_stock_plan = agentic_planning._fallback_tw_stock_plan
_fallback_tw_watchlist_plan = agentic_planning._fallback_tw_watchlist_plan
_planner_input = agentic_planning._planner_input
_normalize_plan_step = agentic_planning._normalize_plan_step
_normalize_plan = agentic_planning._normalize_plan
plan_us_stock_tools = agentic_planning.plan_us_stock_tools
plan_tw_stock_tools = agentic_planning.plan_tw_stock_tools
plan_tw_watchlist_tools = agentic_planning.plan_tw_watchlist_tools

_compact_intraday_points = agentic_execution._compact_intraday_points
_compact_result = agentic_execution._compact_result
_empty_tool_run = agentic_execution._empty_tool_run
_execute_tool = agentic_execution._execute_tool
execute_tool_plan = agentic_execution.execute_tool_plan

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
    return kr_context.read_kr_stock_context(
        db=db,
        symbol=symbol,
        is_index=is_index,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
        dependencies=kr_context.KRContextDependencies(
            kr_market_service=kr_market_service,
            now=_now,
        ),
    )


def read_crypto_context(
    db: Session,
    *,
    asset: str | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    context_limit: int = 100,
) -> dict[str, Any]:
    return crypto_context.read_crypto_context(
        db=db,
        asset=asset,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
        context_limit=context_limit,
        dependencies=crypto_context.CryptoContextDependencies(
            crypto_market_service=crypto_market_service,
            get_crypto_asset=get_crypto_asset,
            build_crypto_source_health=build_crypto_source_health,
            now=_now,
        ),
    )
