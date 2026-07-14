from __future__ import annotations

from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import agentic_common, agentic_policy, freshness
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
from app.ai.market_context import crypto_context, jp_context, kr_context, regional_params, us_context
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
