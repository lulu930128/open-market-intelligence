from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import agentic_common, agentic_execution, agentic_planning, agentic_policy, freshness, llm
from app.ai import progress_events
from app.ai.question_capabilities import required_us_capabilities, tool_capability
from app.ai.market_context import (
    capability_context,
    crypto_context,
    jp_context,
    kr_context,
    macro_context,
    portfolio_context,
    regional_params,
    regional_watchlist_context,
    resource_context,
    source_health_context,
    us_context,
)
from app.ai.market_context import common as market_context_common
from app.db.models import (
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
)
from app.crypto_market import service as crypto_market_service
from app.crypto_market.assets import get_crypto_asset
from app.crypto_market.source_health import build_crypto_source_health
from app.jp_market import service as jp_market_service
from app.jp_market.sources import normalize_jp_symbol
from app.kr_market import service as kr_market_service
from app.kr_market.sources import normalize_kr_index_id, normalize_kr_symbol
from app.market import stock_selection_refresh
from app.market.cross_market import refresh as cross_market_refresh
from app.market.overnight_impact import scan_us_overnight_impact_gaps
from app.portfolio import service as portfolio_service
from app.portfolio.valuation import read_portfolio_market_valuation
from app.resource_market import service as resource_market_service
from app.resource_market.source_health import build_resource_source_health
from app.us_market import service as us_market_service
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.sources import normalize_us_symbol
from app.us_market.symbols import us_instrument_type
from app.watchlists import backfill_service as watchlist_backfill_service


DEFAULT_TOOL_BUDGET = agentic_policy.DEFAULT_TOOL_BUDGET
MAX_TOOL_CALLS = agentic_policy.MAX_TOOL_CALLS
MAX_EXTERNAL_FETCHES = agentic_policy.MAX_EXTERNAL_FETCHES
MAX_TOTAL_SECONDS = agentic_policy.MAX_TOTAL_SECONDS
PROFILE_STALE_DAYS = agentic_policy.PROFILE_STALE_DAYS
TW_STOCK_REFRESH_KEYS = agentic_policy.TW_STOCK_REFRESH_KEYS
ToolDefinition = agentic_policy.ToolDefinition
ALLOWED_TOOLS = agentic_policy.ALLOWED_TOOLS


_now = agentic_common._now
_today = agentic_common._today


_emit_tool_progress = agentic_execution._emit_tool_progress

_age_days = agentic_common._age_days
_json_value = agentic_common._json_value
_append_source_ref_once = market_context_common.append_source_ref_once
_compact_market_context = market_context_common.compact_market_context
_latest_timestamp_from_rows = market_context_common.latest_timestamp_from_rows


normalize_tool_budget = agentic_policy.normalize_tool_budget
tool_definitions_for_llm = agentic_policy.tool_definitions_for_llm


def _fallback_to_cached(policy: dict[str, Any]) -> bool:
    refresh_policy = policy.get("refresh_policy")
    if not isinstance(refresh_policy, dict):
        return True
    return bool(refresh_policy.get("fallback_to_cached", True))


def _freshness_has_cached_data(value: dict[str, Any]) -> bool:
    for dataset in value.get("datasets") or []:
        if isinstance(dataset, dict) and dataset.get("latest") is not None:
            return True
    return False


def _annotate_timeout_fallback(
    runs: list[dict[str, Any]],
    *,
    cached_data_available: bool,
) -> None:
    for run in runs:
        if run.get("status") != "timeout" or not run.get("fallback_used"):
            continue
        run["cached_data_returned"] = cached_data_available
        summary = run.get("result_summary") if isinstance(run.get("result_summary"), dict) else {}
        summary.update(
            {
                "status": "timeout",
                "fallback_used": True,
                "cached_data_returned": cached_data_available,
            }
        )
        run["result_summary"] = summary


def _latest_profile(db: Session, symbol: str) -> USCompanyProfile | None:
    return us_market_service.get_us_company_profile(db=db, symbol=symbol)


def _sec_metric_count(db: Session, symbol: str) -> int:
    return int(
        db.query(func.count(USSecCompanyFact.id))
        .filter(USSecCompanyFact.symbol == symbol)
        .scalar()
        or 0
    )


def _corporate_action_summary(
    db: Session,
    symbol: str,
) -> tuple[int, Any]:
    count, fetched_at = (
        db.query(
            func.count(USCorporateAction.id),
            func.max(USCorporateAction.fetched_at),
        )
        .filter(USCorporateAction.symbol == symbol)
        .one()
    )
    return int(count or 0), fetched_at


def scan_us_stock_gaps(
    db: Session,
    symbol: str,
    *,
    question: str = "",
    satisfied_capabilities: set[str] | None = None,
    requested_capabilities: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    instrument_type = us_instrument_type(normalized_symbol)
    required_capabilities = (
        {
            requirement
            for capability in requested_capabilities
            for requirement in agentic_planning.US_CAPABILITY_REQUIREMENTS.get(
                capability,
                (),
            )
        }
        if requested_capabilities is not None
        else set(required_us_capabilities(question, instrument_type=instrument_type))
    )
    satisfied_capabilities = satisfied_capabilities or set()
    needs_daily = "us_daily_price" in required_capabilities
    needs_profile = "us_company_profile" in required_capabilities
    needs_sec = "us_sec_company_fact" in required_capabilities
    needs_corporate_actions = "us_corporate_action" in required_capabilities
    daily_platform_result = (
        USDailyOhlcvPlatform(db).read(
            symbol=normalized_symbol,
            bars=2,
            now=_now(),
        )
        if needs_daily
        else None
    )
    profile = _latest_profile(db, normalized_symbol) if needs_profile else None
    sec_metric_count = _sec_metric_count(db, normalized_symbol) if needs_sec else 0
    corporate_action_count, corporate_action_fetched_at = (
        _corporate_action_summary(db, normalized_symbol)
        if needs_corporate_actions
        else (0, None)
    )
    missing: list[str] = []
    warnings: list[str] = []
    expected_dates: dict[str, Any] = {}

    daily_projection = (
        daily_platform_result.projection if daily_platform_result is not None else {}
    )
    latest_daily_date = daily_projection.get("latest_trade_date")
    expected_dates["us_daily_price_latest"] = latest_daily_date
    expected_dates["us_daily_price_expected"] = daily_projection.get(
        "expected_trade_date"
    )
    if (
        "us_daily_price" in required_capabilities
        and (
            daily_platform_result is None
            or not daily_platform_result.postcondition_satisfied
        )
    ):
        missing.append("us_daily_price")
        warnings.append(
            "US daily price does not satisfy the canonical expected-session, lineage, and research-usability postcondition."
        )

    profile_fetched_at = profile.fetched_at if profile else None
    expected_dates["us_company_profile_fetched_at"] = _json_value(profile_fetched_at)
    if instrument_type != "index" and "us_company_profile" in required_capabilities and profile is None:
        missing.append("us_company_profile")
    elif (
        instrument_type != "index"
        and "us_company_profile" in required_capabilities
        and profile_fetched_at
        and _age_days(profile_fetched_at) > PROFILE_STALE_DAYS
    ):
        missing.append("us_company_profile")
        warnings.append("US company profile cache is older than the configured freshness window.")

    expected_dates["us_sec_fact_count"] = sec_metric_count
    if (
        instrument_type != "index"
        and "us_sec_company_fact" in required_capabilities
        and sec_metric_count <= 0
    ):
        missing.append("us_sec_company_fact")
    elif (
        instrument_type != "index"
        and "us_sec_company_fact" in required_capabilities
        and sec_metric_count > 0
    ):
        try:
            financial_contract = us_market_service.get_us_sec_financial_contract(
                db=db,
                symbol=normalized_symbol,
                periods=8,
            )
            quality = (
                financial_contract.get("quality")
                if isinstance(financial_contract.get("quality"), dict)
                else {}
            )
            filing_freshness = (
                quality.get("filing_freshness")
                if isinstance(quality.get("filing_freshness"), dict)
                else {}
            )
            expected_dates["us_sec_filing_freshness"] = filing_freshness
            freshness_status = str(quality.get("freshness") or "unknown")
            if freshness_status in {"missing", "stale", "blocked", "failed"}:
                missing.append("us_sec_company_fact")
                warnings.append(
                    "US SEC filing cache is not current for the requested symbol."
                )
            elif quality.get("decision_usable") is not True:
                issues = [
                    str(issue)
                    for issue in quality.get("issues") or []
                    if str(issue).strip()
                ]
                warnings.append(
                    "US SEC facts are cached but the normalized financial contract is partial"
                    + (f": {', '.join(issues[:6])}" if issues else ".")
                )
        except Exception as exc:
            missing.append("us_sec_company_fact")
            warnings.append(f"US SEC financial contract check failed: {exc}")

    if (
        instrument_type != "index"
        and "us_sec_insider_transactions" in required_capabilities
    ):
        try:
            insider_contract = us_market_service.get_us_sec_insider_transactions(
                db,
                symbol=normalized_symbol,
                limit=1,
            )
            insider_status = str(insider_contract.get("status") or "missing")
            expected_dates["us_sec_insider_transactions"] = {
                "status": insider_status,
                "as_of": insider_contract.get("as_of"),
            }
            if insider_status in {"missing", "stale", "blocked", "failed"}:
                missing.append("us_sec_insider_transactions")
                warnings.append(
                    "US SEC Form 4 observation is not current for the requested symbol."
                )
            elif insider_status == "partial":
                warnings.append(
                    "US SEC Form 4 evidence is available with visible partial failures."
                )
        except Exception as exc:
            missing.append("us_sec_insider_transactions")
            warnings.append(f"US SEC Form 4 contract check failed: {exc}")

    expected_dates["us_corporate_action_count"] = corporate_action_count
    expected_dates["us_corporate_action_fetched_at"] = _json_value(
        corporate_action_fetched_at
    )
    if (
        instrument_type != "index"
        and "us_corporate_action" in required_capabilities
        and corporate_action_count <= 0
    ):
        missing.append("us_corporate_action")

    if (
        "us_intraday_trend" in required_capabilities
        and "us_intraday_trend" not in satisfied_capabilities
    ):
        missing.append("us_intraday_trend")

    is_current = not missing
    return {
        "kind": "us_stock_freshness",
        "scope": {
            "target": {
                "type": "us_stock",
                "id": normalized_symbol,
                "market": "US",
                "instrument_type": instrument_type,
            }
        },
        "instrument_type": instrument_type,
        "required_capabilities": sorted(required_capabilities),
        "not_applicable": (
            [
                "us_company_profile",
                "us_sec_company_fact",
                "us_sec_insider_transactions",
                "us_corporate_action",
                "us_short_volume",
            ]
            if instrument_type == "index"
            else []
        ),
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

    if not overnight_gaps.get("is_current", True):
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

    if overnight_gaps.get("refresh_recommended"):
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
    requested_capabilities: tuple[str, ...] | None = None,
    requested_trade_date: str | None = None,
    session_scope: str = "regular",
    intraday_interval: str = "1m",
    force_selected_capabilities: bool = False,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    budget = normalize_tool_budget(raw_budget)
    gaps = scan_us_stock_gaps(
        db,
        normalized_symbol,
        question=question,
        requested_capabilities=requested_capabilities,
    )
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
        requested_capabilities=requested_capabilities,
        requested_trade_date=requested_trade_date,
        session_scope=session_scope,
        intraday_interval=intraday_interval,
        force_selected_capabilities=force_selected_capabilities,
    )
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        fallback_to_cached=_fallback_to_cached(policy),
        progress_callback=progress_callback,
    )
    _annotate_timeout_fallback(
        runs,
        cached_data_available=_freshness_has_cached_data(gaps),
    )
    satisfied_capabilities = {
        capability
        for run in runs
        if run.get("status") == "success"
        and (capability := tool_capability(run.get("tool"))) is not None
    }
    refreshed_gaps = scan_us_stock_gaps(
        db,
        normalized_symbol,
        question=question,
        satisfied_capabilities=satisfied_capabilities,
        requested_capabilities=requested_capabilities,
    )
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": plan_warnings + run_warnings,
        "freshness": refreshed_gaps,
    }


def run_crypto_asset_tool_session(
    *,
    db: Session,
    asset: str,
    target: dict[str, Any],
    policy: dict[str, Any],
    raw_budget: dict[str, Any] | None,
    requested_capabilities: tuple[str, ...],
    selection: dict[str, Any],
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_asset = str(asset or "").strip().upper()
    budget = normalize_tool_budget(raw_budget)
    plan, plan_warnings = agentic_planning.plan_crypto_asset_tools(
        asset=normalized_asset,
        target=target,
        requested_capabilities=requested_capabilities,
        selection=selection,
    )
    plan["budget"] = budget

    if budget["max_calls"] <= 0:
        plan.update(
            {
                "provider": "disabled",
                "reason": "OMI tool budget max_calls is 0.",
                "tool_plan": [],
            }
        )
        return {
            "tool_plan": plan,
            "tool_runs": [],
            "warnings": plan_warnings,
            "freshness": {
                "kind": "crypto_asset_refresh_freshness",
                "is_current": False,
                "missing": list(requested_capabilities),
                "warnings": ["Crypto refresh was disabled by the tool budget."],
            },
        }

    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        fallback_to_cached=_fallback_to_cached(policy),
        progress_callback=progress_callback,
    )
    attempted_capabilities = {
        str(capability)
        for run in runs
        for capability in (
            (run.get("arguments") or {}).get("requested_capabilities") or []
        )
    }
    successful_capabilities = {
        str(capability)
        for run in runs
        if run.get("status") == "success"
        for capability in (
            (run.get("arguments") or {}).get("requested_capabilities") or []
        )
    }
    refresh_capabilities = {
        capability
        for capability in requested_capabilities
        if capability in agentic_planning.CRYPTO_CAPABILITY_REFRESH_TOOLS
    }
    missing = sorted(refresh_capabilities - successful_capabilities)
    if refresh_capabilities - attempted_capabilities:
        missing = sorted(
            set(missing) | (refresh_capabilities - attempted_capabilities)
        )
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": plan_warnings + run_warnings,
        "freshness": {
            "kind": "crypto_asset_refresh_freshness",
            "scope": {
                "target": {
                    "type": "crypto_asset",
                    "id": normalized_asset,
                    "market": "crypto",
                }
            },
            "is_current": not missing,
            "missing": missing,
            "warnings": plan_warnings + run_warnings,
            "refresh_recommended": bool(missing),
        },
    }


def scan_regional_market_gaps(
    db: Session,
    *,
    market: str,
    target_id: str,
    is_index: bool,
) -> dict[str, Any]:
    normalized_market = str(market or "").strip().upper()
    if normalized_market == "JP":
        normalized_id = normalize_jp_symbol(target_id)
        source_health = jp_market_service.build_jp_source_health(
            db=db,
            symbol=normalized_id,
            is_index=is_index,
            now=_now(),
        )
        daily_resources = {"daily_price"}
    elif normalized_market == "KR":
        normalized_id = (
            normalize_kr_index_id(target_id)
            if is_index
            else normalize_kr_symbol(target_id)
        )
        source_health = kr_market_service.build_kr_source_health(
            db=db,
            index_id=normalized_id if is_index else None,
            symbol=None if is_index else normalized_id,
            now=_now(),
        )
        daily_resources = {"index_daily_price" if is_index else "daily_price"}
    else:
        raise ValueError("market must be JP or KR.")

    daily_entries = [
        entry
        for entry in source_health.get("entries") or []
        if isinstance(entry, dict)
        and str(entry.get("resource") or "") in daily_resources
    ]
    ready_statuses = {"available", "current", "fresh", "ready"}
    daily_current = any(
        str(entry.get("status") or "").strip().lower() in ready_statuses
        for entry in daily_entries
    )
    latest_dates = [
        str(entry.get("latest_data_date"))
        for entry in daily_entries
        if entry.get("latest_data_date")
    ]
    expected_dates = [
        str(entry.get("expected_data_date"))
        for entry in daily_entries
        if entry.get("expected_data_date")
    ]
    warnings = [
        str(entry.get("reason") or "")
        for entry in daily_entries
        if str(entry.get("status") or "").strip().lower()
        not in ready_statuses
        and str(entry.get("reason") or "").strip()
    ]
    return {
        "kind": f"{normalized_market.lower()}_regional_freshness",
        "scope": {
            "target": {
                "type": (
                    f"{normalized_market.lower()}_index"
                    if is_index
                    else f"{normalized_market.lower()}_stock"
                ),
                "id": normalized_id,
                "market": normalized_market,
            }
        },
        "is_current": daily_current,
        "refresh_recommended": not daily_current,
        "missing": [] if daily_entries else ["daily.ohlcv"],
        "warnings": warnings,
        "latest_data_date": max(latest_dates) if latest_dates else None,
        "expected_data_date": max(expected_dates) if expected_dates else None,
        "source_health": source_health,
    }


def run_regional_market_tool_session(
    *,
    db: Session,
    market: str,
    target_id: str,
    is_index: bool,
    target: dict[str, Any],
    policy: dict[str, Any],
    raw_budget: dict[str, Any] | None,
    existing_freshness: dict[str, Any],
    requested_capabilities: tuple[str, ...] | None = None,
    include_intraday: bool = False,
    force_selected_capabilities: bool = False,
    progress_callback: progress_events.ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_market = str(market or "").strip().upper()
    budget = normalize_tool_budget(raw_budget)
    requested = set(requested_capabilities or ())
    wants_daily = not requested or "daily.ohlcv" in requested
    wants_intraday = include_intraday or (
        force_selected_capabilities
        and bool(requested & {"quote.snapshot", "intraday.bars"})
    )
    steps: list[dict[str, Any]] = []
    if normalized_market == "JP":
        normalized_id = normalize_jp_symbol(target_id)
        if wants_daily and existing_freshness.get("refresh_recommended"):
            steps.append(
                {
                    "tool": "jp.refresh_daily_price",
                    "args": {
                        "symbol": normalized_id,
                        "provider": "auto",
                        "outputsize": "compact",
                    },
                    "reason": "Japan daily evidence is missing or stale.",
                }
            )
        if wants_intraday:
            steps.append(
                {
                    "tool": "jp.read_intraday_trend",
                    "args": {"symbol": normalized_id},
                    "reason": "A bounded current-session Japan quote was selected.",
                }
            )
    elif normalized_market == "KR":
        normalized_id = (
            normalize_kr_index_id(target_id)
            if is_index
            else normalize_kr_symbol(target_id)
        )
        if wants_daily and existing_freshness.get("refresh_recommended"):
            steps.append(
                {
                    "tool": (
                        "kr.refresh_index_daily_price"
                        if is_index
                        else "kr.refresh_daily_price"
                    ),
                    "args": (
                        {"index_id": normalized_id, "outputsize": "compact"}
                        if is_index
                        else {
                            "symbol": normalized_id,
                            "provider": "auto",
                            "outputsize": "compact",
                        }
                    ),
                    "reason": "Korea daily evidence is missing or stale.",
                }
            )
        if wants_intraday:
            steps.append(
                {
                    "tool": (
                        "kr.read_index_intraday_trend"
                        if is_index
                        else "kr.read_stock_intraday_trend"
                    ),
                    "args": (
                        {"index_id": normalized_id}
                        if is_index
                        else {"symbol": normalized_id}
                    ),
                    "reason": "A bounded current-session Korea quote was selected.",
                }
            )
    else:
        raise ValueError("market must be JP or KR.")

    plan = {
        "provider": "deterministic",
        "reason": (
            "Bounded regional refresh selected from canonical freshness and "
            "capability requirements."
        ),
        "target": target,
        "tool_plan": steps[: budget["max_calls"]],
        "budget": budget,
    }
    if budget["max_calls"] <= 0:
        plan.update(
            {
                "provider": "disabled",
                "reason": "OMI tool budget max_calls is 0.",
                "tool_plan": [],
            }
        )
        return {
            "tool_plan": plan,
            "tool_runs": [],
            "warnings": [],
            "freshness": existing_freshness,
        }

    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        fallback_to_cached=_fallback_to_cached(policy),
        progress_callback=progress_callback,
    )
    refreshed = scan_regional_market_gaps(
        db,
        market=normalized_market,
        target_id=normalized_id,
        is_index=is_index,
    )
    return {
        "tool_plan": plan,
        "tool_runs": runs,
        "warnings": run_warnings,
        "freshness": refreshed,
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
    requested_capabilities: tuple[str, ...] | None = None,
    force_selected_capabilities: bool = False,
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
        requested_capabilities=requested_capabilities,
        force_selected_capabilities=force_selected_capabilities,
    )
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        fallback_to_cached=_fallback_to_cached(policy),
        progress_callback=progress_callback,
    )
    _annotate_timeout_fallback(
        runs,
        cached_data_available=_freshness_has_cached_data(gaps),
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
    requested_capabilities: tuple[str, ...] | None = None,
    force_selected_capabilities: bool = False,
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
        requested_capabilities=requested_capabilities,
        force_selected_capabilities=force_selected_capabilities,
    )
    if gaps.get("refresh_recommended") and not plan.get("tool_plan"):
        plan_warnings.append(plan.get("reason") or "No Taiwan watchlist refresh tool was selected.")
    plan["budget"] = budget
    runs, run_warnings = execute_tool_plan(
        db=db,
        plan=plan,
        budget=budget,
        can_external_fetch=bool(policy.get("can_external_fetch")),
        fallback_to_cached=_fallback_to_cached(policy),
        progress_callback=progress_callback,
    )
    _annotate_timeout_fallback(
        runs,
        cached_data_available=_freshness_has_cached_data(gaps),
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


def read_resource_asset_context(
    db: Session,
    *,
    symbol: str,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return resource_context.read_resource_asset_context(
        db=db,
        symbol=symbol,
        market_data_params=market_data_params,
        dependencies=resource_context.ResourceContextDependencies(
            resource_service=resource_market_service,
            build_resource_source_health=build_resource_source_health,
            now=_now,
        ),
    )


def read_us_macro_context(
    db: Session,
    *,
    series_id: str,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return macro_context.read_us_macro_context(
        db=db,
        series_id=series_id,
        market_data_params=market_data_params,
        dependencies=macro_context.MacroContextDependencies(
            us_market_service=us_market_service,
            now=_now,
        ),
    )


def read_portfolio_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None = None,
    trusted: bool = False,
) -> dict[str, Any]:
    return portfolio_context.read_portfolio_context(
        db=db,
        market_data_params=market_data_params,
        trusted=trusted,
        dependencies=portfolio_context.PortfolioContextDependencies(
            portfolio_service=portfolio_service,
            read_market_valuation=read_portfolio_market_valuation,
            now=_now,
        ),
    )


def read_regional_watchlist_context(
    db: Session,
    *,
    market: str,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "desc",
    radar_mode: str = "action",
    market_data_params: dict[str, Any] | None = None,
    context_limit: int = 100,
) -> dict[str, Any]:
    return regional_watchlist_context.read_regional_watchlist_context(
        db=db,
        market=market,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
        market_data_params=market_data_params,
        context_limit=context_limit,
        dependencies=regional_watchlist_context.RegionalWatchlistDependencies(
            us_market_service=us_market_service,
            jp_market_service=jp_market_service,
            kr_market_service=kr_market_service,
            now=_now,
        ),
    )


def read_unified_source_health_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return source_health_context.read_unified_source_health_context(
        db=db,
        market_data_params=market_data_params,
        now=_now,
    )


def read_capability_status(
    *,
    capability_id: str | None = None,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return capability_context.read_capability_status(
        capability_id=capability_id,
        market_data_params=market_data_params,
        now=_now(),
    )
