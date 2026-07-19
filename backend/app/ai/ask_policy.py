from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai import agentic_tools, decision_core, scope_resolution
from app.ai.schemas import AiAskRequest


VALID_MODES = {"auto", "data_only", "brief", "analysis", "report", "full"}
VALID_RANK_BY = {"watchlist", "score", "change_pct", "volume"}
VALID_SORT_ORDER = {"asc", "desc"}
VALID_ANALYSIS_HORIZONS = {"auto", "intraday", "short", "swing", "long"}
SUPPORTED_CONTRACT_VERSIONS = {"omi.ai.ask.v2"}
VALID_TARGET_TYPES = scope_resolution.VALID_TARGET_TYPES
REPORT_HINTS = decision_core.REPORT_HINTS
ANALYSIS_HINTS = decision_core.ANALYSIS_HINTS
INTERNAL_SCOPE_TO_TARGET_TYPE = scope_resolution.INTERNAL_SCOPE_TO_TARGET_TYPE


@dataclass(frozen=True)
class AiAskServerPolicy:
    can_call_llm: bool = False
    can_write: bool = False
    can_external_fetch: bool = False
    trust_source: str = "untrusted"


_contains_hint = decision_core.contains_hint
_normalize_analysis_horizon = decision_core.normalize_analysis_horizon
_request_target = scope_resolution._request_target
_request_target_type = scope_resolution._request_target_type
_request_target_id = scope_resolution._request_target_id
_resolve_scope = scope_resolution._resolve_scope


def _validate_request(payload: AiAskRequest) -> None:
    if payload.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ValueError(
            "contract_version must be one of: "
            + ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
        )
    target = _request_target(payload)
    target_type = _request_target_type(payload)
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(f"target.type must be one of: {', '.join(sorted(VALID_TARGET_TYPES))}")

    target_id = _request_target_id(payload)
    if target_id is not None and len(target_id) > 120:
        raise ValueError("target.id must be less than or equal to 120 characters.")

    if any(key in target for key in {"scope_type", "scope_id"}):
        raise ValueError("target must use v2 fields: type and id.")

    if payload.mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    if payload.rank_by not in VALID_RANK_BY:
        raise ValueError(f"rank_by must be one of: {', '.join(sorted(VALID_RANK_BY))}")

    if payload.sort_order not in VALID_SORT_ORDER:
        raise ValueError(f"sort_order must be one of: {', '.join(sorted(VALID_SORT_ORDER))}")

    if _normalize_analysis_horizon(payload.analysis_horizon) not in VALID_ANALYSIS_HORIZONS:
        raise ValueError(
            f"analysis_horizon must be one of: {', '.join(sorted(VALID_ANALYSIS_HORIZONS))}"
        )

    if not isinstance(payload.tool_budget, dict):
        raise ValueError("tool_budget must be an object.")

    if not isinstance(payload.refresh_policy, dict):
        raise ValueError("refresh_policy must be an object.")

    if not isinstance(payload.market_data_params, dict):
        raise ValueError("market_data_params must be an object.")


def _infer_scope_type(payload: AiAskRequest) -> str:
    return _resolve_scope(db=None, payload=payload).selected_scope_type


def _policy(payload: AiAskRequest, server_policy: AiAskServerPolicy) -> dict[str, Any]:
    can_call_llm = bool(payload.allow_llm and server_policy.can_call_llm)
    can_write = bool(payload.allow_write and server_policy.can_write)
    can_external_fetch = bool(payload.allow_external_fetch and server_policy.can_external_fetch)
    tool_budget = agentic_tools.normalize_tool_budget(payload.tool_budget)
    return {
        "allow_llm": payload.allow_llm,
        "allow_write": payload.allow_write,
        "allow_external_fetch": payload.allow_external_fetch,
        "server_trust_source": server_policy.trust_source,
        "server_can_call_llm": server_policy.can_call_llm,
        "server_can_write": server_policy.can_write,
        "server_can_external_fetch": server_policy.can_external_fetch,
        "can_call_llm": can_call_llm,
        "can_write": can_write,
        "can_plan_tools": can_call_llm,
        "can_external_fetch": can_external_fetch,
        "can_generate_analysis": can_call_llm,
        "can_generate_report": bool(can_call_llm and can_write),
        "tool_budget": tool_budget,
        "refresh_policy": payload.refresh_policy,
    }


def _refresh_before_answer_enabled(payload: AiAskRequest) -> bool:
    policy = payload.refresh_policy if isinstance(payload.refresh_policy, dict) else {}
    mode = str(policy.get("mode") or "stale_first").strip().lower()
    if mode in {"off", "disabled", "none"}:
        return False
    return bool(policy.get("before_answer", True))


def _infer_mode(payload: AiAskRequest, scope_type: str, policy: dict[str, Any]) -> str:
    if payload.mode != "auto":
        return payload.mode

    if scope_type in {
        "market",
        "data_freshness",
        "resource_asset",
        "portfolio",
        "us_macro",
        "us_watchlist",
        "jp_watchlist",
        "kr_watchlist",
        "source_health",
        "capability_status",
    }:
        return "data_only"

    if policy["can_generate_report"] and _contains_hint(payload.question, REPORT_HINTS):
        return "report"

    if policy["can_generate_analysis"] and _contains_hint(payload.question, ANALYSIS_HINTS):
        return "analysis"

    if policy["can_generate_analysis"] and policy.get("question_intent") in {
        "entry_decision",
        "exit_decision",
        "position_risk_decision",
        "risk_check",
        "trend_view",
    }:
        return "analysis"

    return "brief"


def _effective_mode(
    requested_mode: str,
    scope_type: str,
    policy: dict[str, Any],
    warnings: list[str],
) -> str:
    answer_capable_scopes = {
        "stock",
        "watchlist",
        "market",
        "us_stock",
        "jp_stock",
        "jp_index",
        "kr_stock",
        "kr_index",
        "crypto_market",
        "crypto_asset",
        "tw_index",
        "tw_futures",
        "resource_asset",
        "portfolio",
        "us_macro",
        "us_watchlist",
        "jp_watchlist",
        "kr_watchlist",
        "source_health",
        "capability_status",
    }
    report_capable_scopes = {"stock", "watchlist", "us_stock"}
    data_context_only_scopes = {
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
    }

    if requested_mode == "full":
        return "full"

    if requested_mode in {"analysis", "report"} and scope_type in data_context_only_scopes:
        warnings.append(
            f"{scope_type} has a local evidence context reader but no dedicated AI analysis/report path yet; returned data_only."
        )
        return "data_only"

    if requested_mode == "report" and not policy["can_generate_report"]:
        if policy["can_generate_analysis"] and scope_type in report_capable_scopes:
            warnings.append(
                "Report mode requires allow_write=true and a server-side trusted request; returned non-persistent analysis instead."
            )
            return "analysis"

        warnings.append(
            "Report mode requires allow_llm=true, allow_write=true, and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in answer_capable_scopes else "data_only"

    if requested_mode == "analysis" and not policy["can_generate_analysis"]:
        warnings.append(
            "Analysis mode requires allow_llm=true and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in answer_capable_scopes else "data_only"

    if requested_mode in {"analysis", "report"} and scope_type == "market":
        warnings.append("market does not have an LLM analysis/report path yet; returned brief.")
        return "brief"

    if requested_mode in {"brief", "analysis", "report"} and scope_type == "data_freshness":
        warnings.append(f"{scope_type} does not have a brief/analysis/report path yet; returned data_only.")
        return "data_only"

    return requested_mode


def _require_scope_id(payload: AiAskRequest, scope_type: str) -> str:
    scope_id = _request_target_id(payload)
    if scope_id is None:
        raise ValueError(f"target.id is required for target.type={INTERNAL_SCOPE_TO_TARGET_TYPE.get(scope_type, scope_type)}")

    return scope_id


def _require_group_id(payload: AiAskRequest) -> int:
    scope_id = _require_scope_id(payload, "watchlist")
    try:
        return int(scope_id)
    except ValueError as exc:
        raise ValueError("scope_id must be a numeric watchlist group id.") from exc
