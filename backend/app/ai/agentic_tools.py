from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import llm, progress_events
from app.db.models import (
    JPStockMaster,
    USDailyPrice,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USShortVolumeDaily,
    USStockMaster,
)
from app.ai.evidence_passport import build_evidence_passport
from app.ai import freshness
from app.jp_market import service as jp_market_service
from app.jp_market.sources import normalize_jp_symbol
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now().date()


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


def _age_days(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (_now() - value).days


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return _json_value(value)


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if row is None:
        return None
    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _list_rows(rows: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [item for row in rows if (item := _row_dict(row, fields)) is not None]


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"", "none", "null"}:
            return None
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return bool(value)


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
        "metric_count",
        "message",
    )
    summary = {key: _json_value(value.get(key)) for key in keys if key in value}
    if "points" in value and "point_count" not in summary and isinstance(value["points"], list):
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


def _latest_tool_result(tool_runs: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for run in reversed(tool_runs):
        if run.get("tool") == tool_name and run.get("status") == "success":
            summary = run.get("result_summary")
            if isinstance(summary, dict):
                return summary
    return None


def _append_source_ref_once(source_refs: list[dict[str, Any]], ref: dict[str, Any]) -> None:
    ref_key = ref.get("name") or ref.get("kind")
    if any((item.get("name") or item.get("kind")) == ref_key for item in source_refs):
        return
    source_refs.append(ref)


def read_us_stock_context(
    db: Session,
    *,
    symbol: str,
    tool_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    tool_runs = tool_runs or []
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )
    daily_rows = us_market_service.list_us_daily_prices(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    profile = _latest_profile(db, normalized_symbol)
    sec_summary: dict[str, Any] | None = None
    sec_warning: str | None = None
    try:
        sec_summary = us_market_service.get_us_sec_fundamental_summary(
            db=db,
            symbol=normalized_symbol,
        )
    except Exception as exc:
        sec_warning = str(exc)

    corporate_actions = us_market_service.list_us_corporate_actions(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    short_volume_rows = us_market_service.list_us_short_volumes(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    gaps = scan_us_stock_gaps(db, normalized_symbol)
    source_health = us_market_service.build_us_source_health(
        db=db,
        symbol=normalized_symbol,
    )
    latest_daily = daily_rows[0] if daily_rows else None
    warnings = list(gaps.get("warnings") or [])
    missing = list(gaps.get("missing") or [])
    if sec_warning and "us_sec_company_fact" not in missing:
        missing.append("us_sec_company_fact")
    if sec_warning:
        warnings.append(sec_warning)
    for entry in source_health.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("status") != "stale":
            continue
        warnings.append(
            f"US source health stale: {entry.get('resource')} via {entry.get('provider')} - {entry.get('reason')}"
        )

    source_refs: list[dict[str, Any]] = []
    for row in daily_rows[:3]:
        if row.source_url:
            source_refs.append(
                {
                    "kind": "us_daily_price",
                    "provider": row.provider,
                    "symbol": row.symbol,
                    "date": row.trade_date.isoformat(),
                    "url": row.source_url,
                }
            )
    if profile and profile.source_url:
        source_refs.append(
            {
                "kind": "us_company_profile",
                "provider": profile.provider,
                "symbol": profile.symbol,
                "fetched_at": profile.fetched_at.isoformat(),
                "url": profile.source_url,
            }
        )

    _append_source_ref_once(source_refs, {"type": "table", "name": "us_daily_price"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "us_company_profile"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "us_sec_company_fact"})
    if corporate_actions:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_corporate_action"})
    if short_volume_rows:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_short_volume_daily"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.us_market.source_health"})

    intraday_summary = _latest_tool_result(tool_runs, "us.read_intraday_trend")
    envelope = {
        "kind": "us_stock_context",
        "generated_at": _now().isoformat(),
        "as_of": latest_daily.trade_date.isoformat() if latest_daily else None,
        "scope": {
            "target": {
                "type": "us_stock",
                "id": normalized_symbol,
                "label": (profile.company_name if profile else None) or (stock.security_name if stock else None),
                "market": "US",
            }
        },
        "summary": {
            "latest_close": latest_daily.close_price if latest_daily else None,
            "latest_trade_date": latest_daily.trade_date.isoformat() if latest_daily else None,
            "latest_volume": latest_daily.trade_volume if latest_daily else None,
            "intraday": intraday_summary,
            "profile": _row_dict(
                profile,
                (
                    "provider",
                    "symbol",
                    "company_name",
                    "exchange",
                    "sector",
                    "industry",
                    "market_cap",
                    "pe_ratio",
                    "eps",
                    "revenue_ttm",
                    "profit_margin",
                    "latest_quarter",
                    "fetched_at",
                ),
            ),
            "sec_metric_count": (sec_summary or {}).get("metric_count") if sec_summary else 0,
            "source_health": source_health.get("summary"),
        },
        "data": {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "security_name",
                    "exchange",
                    "asset_type",
                    "cik",
                    "sec_company_name",
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
                    "trade_volume",
                    "fetched_at",
                ),
            ),
            "sec_fundamentals": sec_summary,
            "corporate_actions": _list_rows(
                corporate_actions,
                (
                    "provider",
                    "symbol",
                    "action_type",
                    "event_date",
                    "amount",
                    "split_ratio",
                    "fetched_at",
                ),
            ),
            "short_volume": _list_rows(
                short_volume_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "market_center",
                    "short_volume",
                    "total_volume",
                    "short_ratio",
                    "fetched_at",
                ),
            ),
            "source_health": source_health,
            "tool_runs": tool_runs,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind="us_stock_context",
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=gaps,
        tool_runs=tool_runs,
    )
    return envelope


def read_jp_stock_context(
    db: Session,
    *,
    symbol: str,
    is_index: bool = False,
    tool_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_jp_symbol(symbol)
    tool_runs = tool_runs or []
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
        if normalized_symbol
        else None
    )
    daily_rows: list[Any] = []
    chart: dict[str, Any] = {}
    fundamental: Any = None
    resource_summary: dict[str, Any] | None = None
    warnings: list[str] = [
        "Japan AI context is local-cache only; it does not fetch external data on the read path.",
    ]
    missing: list[str] = []

    if is_index:
        warnings.append(
            "Japan index context is OHLC-only; company fundamentals and chip resources are skipped."
        )
    elif stock is None:
        missing.append("jp_stock_master")
        warnings.append("JP stock master row is missing; symbol-level cached evidence is still returned when available.")

    try:
        daily_rows = jp_market_service.list_jp_daily_prices(
            db=db,
            symbol=normalized_symbol,
            limit=10,
        )
    except Exception as exc:
        missing.append("jp_daily_price")
        warnings.append(f"JP daily prices unavailable: {exc}")

    try:
        chart = jp_market_service.list_jp_ohlc_chart_data(
            db=db,
            symbol=normalized_symbol,
            timeframe="daily",
            bars=90,
            ensure_history=False,
            outputsize="compact",
            provider="auto",
        )
    except Exception as exc:
        if "jp_daily_price" not in missing:
            missing.append("jp_daily_price")
        warnings.append(f"JP OHLC chart unavailable: {exc}")

    if not is_index:
        try:
            fundamental = jp_market_service.get_jp_company_fundamental(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            missing.append("jp_company_fundamental")
            warnings.append(f"JP company fundamental summary unavailable: {exc}")

        try:
            resource_summary = jp_market_service.get_jp_resource_summary(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            warnings.append(f"JP resource summary unavailable: {exc}")

    if not daily_rows and not (chart.get("points") if isinstance(chart, dict) else None):
        if "jp_daily_price" not in missing:
            missing.append("jp_daily_price")

    if not is_index and fundamental is None and "jp_company_fundamental" not in missing:
        missing.append("jp_company_fundamental")

    unavailable_resources: list[str] = []
    planned_resources: list[str] = []
    if resource_summary:
        for slot in resource_summary.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            key = str(slot.get("key") or "").strip()
            if not key:
                continue
            if slot.get("status") == "planned":
                planned_resources.append(key)
                continue
            if not slot.get("available"):
                unavailable_resources.append(key)
                missing.append(f"jp_resource.{key}")

    if unavailable_resources:
        warnings.append(
            "JP resource slots are empty in local cache: " + ", ".join(sorted(set(unavailable_resources)))
        )
    if planned_resources:
        warnings.append(
            "JP resource slots are planned but not implemented yet: " + ", ".join(sorted(set(planned_resources)))
        )

    latest_daily = daily_rows[0] if daily_rows else None
    chart_points = chart.get("points") if isinstance(chart, dict) else []
    latest_point = chart_points[-1] if chart_points else None
    latest_trade_date = (
        latest_daily.trade_date.isoformat()
        if latest_daily is not None
        else _json_value(latest_point.get("time")) if isinstance(latest_point, dict) else None
    )
    latest_close = (
        latest_daily.close_price
        if latest_daily is not None
        else latest_point.get("close") if isinstance(latest_point, dict) else None
    )
    latest_volume = (
        latest_daily.trade_volume
        if latest_daily is not None
        else latest_point.get("volume") if isinstance(latest_point, dict) else None
    )

    source_refs: list[dict[str, Any]] = []
    for row in daily_rows[:3]:
        if row.source_url:
            source_refs.append(
                {
                    "kind": "jp_daily_price",
                    "provider": row.provider,
                    "symbol": row.symbol,
                    "date": row.trade_date.isoformat(),
                    "url": row.source_url,
                }
            )
    if fundamental is not None and getattr(fundamental, "source_url", None):
        source_refs.append(
            {
                "kind": "jp_company_fundamental",
                "provider": getattr(fundamental, "provider", None),
                "symbol": getattr(fundamental, "symbol", normalized_symbol),
                "fetched_at": _json_value(getattr(fundamental, "fetched_at", None)),
                "url": getattr(fundamental, "source_url", None),
            }
        )

    _append_source_ref_once(source_refs, {"type": "table", "name": "jp_daily_price"})
    if not is_index:
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_stock_master"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_company_fundamental"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_margin_interest"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "jp_investor_type"})
        _append_source_ref_once(source_refs, {"type": "derived", "name": "app.jp_market.resource_summary"})

    target_type = "jp_index" if is_index else "jp_stock"
    label = (
        "Nikkei 225"
        if normalized_symbol == "^N225"
        else "TOPIX ETF"
        if normalized_symbol == "1306.T" and is_index
        else stock.security_name
        if stock and stock.security_name
        else normalized_symbol
    )
    resource_slots = resource_summary.get("slots") if isinstance(resource_summary, dict) else []
    envelope = {
        "kind": "jp_index_context" if is_index else "jp_stock_context",
        "generated_at": _now().isoformat(),
        "as_of": latest_trade_date,
        "scope": {
            "target": {
                "type": target_type,
                "id": normalized_symbol,
                "label": label,
                "market": "JP",
            }
        },
        "summary": {
            "latest_close": latest_close,
            "latest_trade_date": latest_trade_date,
            "latest_volume": latest_volume,
            "resource_status": {
                "available": [
                    slot.get("key")
                    for slot in resource_slots
                    if isinstance(slot, dict) and slot.get("available")
                ],
                "empty": sorted(set(unavailable_resources)),
                "planned": sorted(set(planned_resources)),
            },
        },
        "data": {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "local_code",
                    "security_name",
                    "exchange",
                    "market_segment",
                    "sector_33_name",
                    "sector_17_name",
                    "size_name",
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
                    "trade_volume",
                    "fetched_at",
                ),
            ),
            "chart": _json_ready(chart),
            "fundamental": _row_dict(
                fundamental,
                (
                    "provider",
                    "symbol",
                    "company_name",
                    "exchange",
                    "sector",
                    "industry",
                    "currency",
                    "market_cap",
                    "enterprise_value",
                    "trailing_pe",
                    "forward_pe",
                    "price_to_book",
                    "dividend_yield",
                    "eps_ttm",
                    "forward_eps",
                    "revenue_ttm",
                    "net_sales",
                    "operating_profit",
                    "ordinary_profit",
                    "profit",
                    "forecast_net_sales",
                    "forecast_operating_profit",
                    "forecast_profit",
                    "return_on_equity",
                    "return_on_assets",
                    "profit_margin",
                    "debt_to_equity",
                    "current_ratio",
                    "book_value",
                    "earnings_date",
                    "ex_dividend_date",
                    "fetched_at",
                ),
            ),
            "resource_summary": _json_ready(resource_summary),
            "tool_runs": tool_runs,
        },
        "data_limitations": [
            "No JP-specific AI decision adapter or persisted LLM report path is enabled yet.",
            "Company fundamentals and chip resources depend on local cache coverage and free/provider availability.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    freshness_result = {
        "kind": "jp_index_freshness" if is_index else "jp_stock_freshness",
        "scope": {"target": envelope["scope"]["target"]},
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
