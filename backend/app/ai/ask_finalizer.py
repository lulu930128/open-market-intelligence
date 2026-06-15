from __future__ import annotations

from typing import Any

from app.ai import ask_response_support, scope_resolution
from app.ai.evidence_passport import build_evidence_passport
from app.ai.schemas import AiAskRequest


def finalize_ask_response(
    *,
    payload: AiAskRequest,
    resolution: scope_resolution.ScopeResolution,
    requested_mode: str,
    effective_mode: str,
    action: str,
    result: dict[str, Any],
    response_target: dict[str, Any],
    assembled: Any,
    policy: dict[str, Any],
    tool_plan: dict[str, Any],
    tool_runs: list[dict[str, Any]],
    freshness_result: dict[str, Any],
    progress: Any,
) -> dict[str, Any]:
    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        as_of=ask_response_support._result_as_of(result, assembled.analysis_digest),
        source_refs=assembled.result_source_refs,
        missing=assembled.combined_missing,
        warnings=assembled.combined_warnings,
        freshness=freshness_result,
        tool_runs=tool_runs,
        analysis=assembled.analysis_digest,
    )
    report_level = ask_response_support._report_level(effective_mode, freshness_result)
    progress.evidence_passport(evidence_passport)
    progress.answer_ready(
        answer_ready=assembled.answer_ready,
        report_level=report_level,
    )

    return {
        "kind": "ai_ask",
        "contract_version": ask_response_support.CONTRACT_VERSION,
        "question": payload.question,
        "target": response_target,
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
        },
        "action": action,
        "strategy_profile": result.get("strategy_profile") or payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": scope_resolution._scope_resolution_dict(resolution),
        "clarification": assembled.clarification,
        "next_actions": assembled.next_actions,
        "answer_ready": assembled.answer_ready,
        "report_level": report_level,
        "analysis": assembled.response_analysis,
        "reasoning_steps": assembled.reasoning_steps,
        "policy": policy,
        "tool_plan": tool_plan,
        "tool_runs": tool_runs,
        "result": result,
        "freshness": freshness_result,
        "missing": assembled.combined_missing,
        "warnings": assembled.combined_warnings,
        "source_refs": assembled.result_source_refs,
        "evidence_passport": evidence_passport,
    }
