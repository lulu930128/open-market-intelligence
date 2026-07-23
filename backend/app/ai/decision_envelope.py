from __future__ import annotations

from copy import deepcopy
from typing import Any


LEGACY_CONTRACT_VERSION = "omi.ai.ask.v2"
CONTRACT_VERSION = "omi.decision.v3"
KIND = "omi_decision"

DECISION_INTENTS = {
    "entry_decision",
    "exit_decision",
    "position_risk_decision",
    "risk_check",
}

READY_DOMAIN_STATUSES = {
    "available",
    "current",
    "daily_close",
    "fresh",
    "healthy",
    "latest_completed_session",
    "latest_session_close",
    "live",
    "ok",
    "ready",
}
LIMITED_DOMAIN_STATUSES = {
    "cached",
    "delayed",
    "partial",
    "waiting",
}
NEUTRAL_DOMAIN_STATUSES = {
    "not_applicable",
    "not_requested",
}
BLOCKING_DOMAIN_STATUSES = {
    "blocked",
    "credential_required",
    "disabled",
    "error",
    "failed",
    "failure",
    "missing",
    "not_available",
    "not_connected",
    "provider_error",
    "provider_failure",
    "provider_not_connected",
    "rate_limited",
    "stale",
    "timeout",
    "unavailable",
    "unknown",
}

DOMAIN_STATUS_ALIASES = {
    "closed": "latest_session_close",
    "closed_session": "latest_session_close",
    "degraded": "partial",
    "empty": "missing",
    "expired": "stale",
    "latest_close": "latest_completed_session",
}

SLOT_DOMAIN_MAP = {
    "quote": "quote",
    "intraday": "intraday",
    "index_intraday": "intraday",
    "technical": "technical",
    "chips_flows": "chips",
    "fundamentals": "fundamentals",
    "cross_market": "cross_market",
    "market_breadth": "breadth",
    "market_volume": "volume",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_strings(values: Any) -> list[str]:
    output: list[str] = []
    for value in _list(values):
        text = _text(value)
        if text and text not in output:
            output.append(text)
    return output


def normalize_domain_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    normalized = str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    return DOMAIN_STATUS_ALIASES.get(normalized, normalized)


def domain_status_class(value: Any) -> str:
    status = normalize_domain_status(value)
    if status in READY_DOMAIN_STATUSES:
        return "ready"
    if status in LIMITED_DOMAIN_STATUSES:
        return "limited"
    if status in NEUTRAL_DOMAIN_STATUSES:
        return "neutral"
    if status in BLOCKING_DOMAIN_STATUSES:
        return "blocked"
    return "blocked"


def build_domain_passport(
    *,
    compact: dict[str, Any],
    query_plan: dict[str, Any],
) -> dict[str, Any]:
    raw_domains = _dict(compact.get("freshness_by_domain"))
    requested_domains = [
        str(value)
        for value in query_plan.get("requested_domains") or []
        if str(value).strip()
    ]
    required_domains = [
        str(value)
        for value in query_plan.get("required_domains") or requested_domains
        if str(value).strip()
    ]
    if not required_domains:
        required_domains = list(raw_domains)

    domains: dict[str, dict[str, Any]] = {}
    for domain, raw_status in raw_domains.items():
        status = normalize_domain_status(raw_status)
        status_class = domain_status_class(status)
        required = str(domain) in required_domains
        facts_usable = status_class in {"ready", "limited"} or (
            status_class == "neutral" and not required
        )
        decision_usable = status_class == "ready" or (
            status_class == "neutral" and not required
        )
        trust_level = (
            "high"
            if status_class == "ready"
            else "medium"
            if status_class in {"limited", "neutral"}
            else "low"
            if status != "unknown"
            else "unknown"
        )
        domains[str(domain)] = {
            "status": status,
            "status_class": status_class,
            "trust_level": trust_level,
            "required": required,
            "usable": facts_usable,
            "decision_usable": decision_usable,
        }

    blocked_domains = [
        domain
        for domain in required_domains
        if domain in domains and not domains[domain]["decision_usable"]
    ]
    missing_domains = [domain for domain in required_domains if domain not in domains]
    decision_status = (
        "blocked"
        if required_domains
        and len(blocked_domains) + len(missing_domains) == len(required_domains)
        else "partial"
        if blocked_domains or missing_domains
        else "ready"
    )
    explicit_trust = {
        f"{domain}_trust": domains.get(
            domain,
            {
                "status": "not_requested",
                "status_class": "neutral",
                "trust_level": "medium",
                "required": domain in required_domains,
                "usable": domain not in required_domains,
                "decision_usable": domain not in required_domains,
            },
        )
        for domain in (
            "quote",
            "intraday",
            "technical",
            "chips",
            "fundamentals",
            "cross_market",
        )
    }
    return {
        "domains": domains,
        **explicit_trust,
        "decision_readiness": {
            "status": decision_status,
            "required_domains": required_domains,
            "blocked_domains": blocked_domains,
            "missing_domains": missing_domains,
        },
    }


def _decision_intent(response: dict[str, Any]) -> str:
    analysis = _dict(response.get("analysis"))
    contract = _dict(analysis.get("decision_contract"))
    return str(
        contract.get("intent")
        or analysis.get("question_intent")
        or _dict(analysis.get("question_understanding")).get("intent")
        or "general"
    )


def evaluate_readiness(response: dict[str, Any]) -> dict[str, Any]:
    passport = _dict(response.get("evidence_passport"))
    passport_decision = _dict(passport.get("decision_readiness"))
    evidence_status = str(passport_decision.get("status") or "unknown").lower()
    trust_level = str(passport.get("trust_level") or "unknown").lower()
    request_status = str(response.get("request_status") or "completed").lower()
    response_mode = str(_dict(response.get("mode")).get("response") or "").lower()
    intent = _decision_intent(response)
    decision_required = intent in DECISION_INTENTS

    facts_ready = bool(response.get("facts_ready"))
    analysis_ready = bool(response.get("analysis_ready"))
    answer_ready = bool(response.get("answer_ready"))
    legacy_decision_candidate = bool(response.get("decision_ready"))
    evidence_decision_ready = (
        evidence_status == "ready"
        if evidence_status != "unknown"
        else trust_level in {"high", "medium"}
    )
    decision_ready = bool(
        response.get("ok") is not False
        and request_status == "completed"
        and response_mode != "data_only"
        and decision_required
        and legacy_decision_candidate
        and evidence_decision_ready
        and trust_level in {"high", "medium"}
    )

    blocked_sections = _unique_strings(response.get("blocked_sections"))
    if decision_required and not decision_ready and "decision" not in blocked_sections:
        blocked_sections.append("decision")
    available_sections = _unique_strings(response.get("available_sections"))
    if decision_ready:
        if "decision" not in available_sections:
            available_sections.append("decision")
    else:
        available_sections = [
            section
            for section in available_sections
            if section not in {"decision", "decision_contract"}
        ]

    return {
        "facts_ready": facts_ready,
        "analysis_ready": analysis_ready,
        "answer_ready": answer_ready,
        "decision_ready": decision_ready,
        "decision_required": decision_required,
        "evidence_status": evidence_status,
        "trust_level": trust_level,
        "blocked_sections": blocked_sections,
        "available_sections": available_sections,
    }


def apply_readiness_to_v2(response: dict[str, Any]) -> dict[str, Any]:
    readiness = evaluate_readiness(response)
    response["decision_ready"] = readiness["decision_ready"]
    response["blocked_sections"] = readiness["blocked_sections"]
    response["available_sections"] = readiness["available_sections"]

    analysis = _dict(response.get("analysis"))
    contract = _dict(analysis.get("decision_contract"))
    if contract:
        contract_readiness = _dict(contract.get("readiness"))
        contract_readiness["decision_ready"] = readiness["decision_ready"]
        contract_readiness["evidence_status"] = readiness["evidence_status"]
        contract_readiness["trust_level"] = readiness["trust_level"]
        contract["readiness"] = contract_readiness
        contract["blocked_sections"] = readiness["blocked_sections"]
    return response


def _result_data(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _dict(response.get("result"))
    data = _dict(result.get("data"))
    compact = _dict(data.get("compact"))
    return data, compact


def _freshness_by_domain(response: dict[str, Any]) -> dict[str, Any]:
    data, compact = _result_data(response)
    raw = compact.get("freshness_by_domain")
    if not isinstance(raw, dict):
        raw = data.get("freshness_by_domain")
    return deepcopy(_dict(raw))


def _slots(response: dict[str, Any]) -> dict[str, Any]:
    data, compact = _result_data(response)
    raw = data.get("slots")
    if not isinstance(raw, dict):
        raw = compact.get("slots")
    return deepcopy(_dict(raw))


def canonical_slots(response: dict[str, Any]) -> dict[str, Any]:
    slots = _slots(response)
    freshness_by_domain = _freshness_by_domain(response)
    response_missing = _unique_strings(response.get("missing"))
    response_warnings = _unique_strings(response.get("warnings"))

    for slot_key, raw_slot in list(slots.items()):
        if not isinstance(raw_slot, dict):
            slots[slot_key] = {
                "status": "missing",
                "freshness": {"status": "unknown"},
                "usability": "unusable",
            }
            continue
        slot = raw_slot
        domain = SLOT_DOMAIN_MAP.get(str(slot_key))
        domain_freshness = freshness_by_domain.get(domain) if domain else None
        domain_status = normalize_domain_status(domain_freshness)
        domain_class = domain_status_class(domain_status)
        slot_status = str(slot.get("status") or "missing").lower()

        if domain is not None:
            existing_freshness = _dict(slot.get("freshness"))
            slot["freshness"] = {
                **existing_freshness,
                "status": domain_status,
                "domain": domain,
            }
            if domain_class == "blocked":
                slot["status"] = "missing" if domain_status == "missing" else "blocked"
                slot["usability"] = "unusable"
            elif domain_class == "limited":
                if slot_status not in {"missing", "blocked", "not_requested", "not_applicable"}:
                    slot["status"] = "partial"
                slot["usability"] = "limited"
            elif domain_class == "ready":
                if slot_status == "ready":
                    slot["usability"] = "usable"

        if slot_key == "data_quality":
            problem_domains = [
                domain_name
                for domain_name, domain_value in freshness_by_domain.items()
                if domain_status_class(domain_value) in {"limited", "blocked"}
            ]
            if response_missing or response_warnings or problem_domains:
                slot["status"] = "partial"
                slot["usability"] = "limited"
                slot["freshness"] = {
                    "status": "partial",
                    "problem_domains": problem_domains,
                }
                slot["missing"] = list(
                    dict.fromkeys(_unique_strings(slot.get("missing")) + response_missing)
                )[:12]
                slot["warnings"] = list(
                    dict.fromkeys(_unique_strings(slot.get("warnings")) + response_warnings)
                )[:12]

    return slots


def _answer(response: dict[str, Any]) -> dict[str, Any]:
    analysis = _dict(response.get("analysis"))
    human_answer = deepcopy(_dict(analysis.get("human_answer")))
    decision_contract = _dict(analysis.get("decision_contract"))
    result_answer = _dict(_dict(response.get("result")).get("human_answer"))
    if not human_answer:
        human_answer = deepcopy(result_answer)

    clarification = _dict(response.get("clarification"))
    error = _dict(response.get("error"))
    headline = (
        human_answer.get("headline")
        or decision_contract.get("headline")
        or clarification.get("question")
        or error.get("message")
    )
    text = human_answer.get("text") or decision_contract.get("text")
    answer = dict(human_answer)
    answer.update(
        {
            "headline": headline,
            "text": text,
            "detail": human_answer.get("detail") or text,
            "summary": _list(
                human_answer.get("summary")
                or _dict(decision_contract.get("sections")).get("summary")
            ),
            "stance": human_answer.get("stance")
            or human_answer.get("stance_label"),
            "confidence": human_answer.get("confidence")
            or human_answer.get("confidence_label"),
            "source": human_answer.get("source")
            or decision_contract.get("answer_source"),
            "style": human_answer.get("style")
            or decision_contract.get("answer_style"),
        }
    )
    return answer


def _decision(response: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    analysis = _dict(response.get("analysis"))
    contract = _dict(analysis.get("decision_contract"))
    sections = _dict(contract.get("sections"))
    return {
        "intent": _decision_intent(response),
        "action_plan": _list(sections.get("action_plan")),
        "scenarios": _list(sections.get("scenarios")),
        "counter_evidence": _list(sections.get("counter_evidence")),
        "risks": _list(sections.get("risks")),
        "data_limits": _list(sections.get("data_limits")),
        "price_levels": deepcopy(
            _dict(analysis.get("technical_levels"))
            or _dict(analysis.get("price_level_validation"))
        ),
        "position": deepcopy(
            _dict(analysis.get("position_decision"))
            or _dict(analysis.get("position_math"))
        ),
        "blocked_sections": readiness["blocked_sections"],
    }


def _evidence_result(response: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(_dict(response.get("result")))
    result.pop("human_answer", None)
    result.pop("decision_contract", None)
    return result


def _provider_failures(response: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for run in _list(response.get("tool_runs")):
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "").lower()
        if status not in {
            "blocked",
            "error",
            "failed",
            "rate_limited",
            "timeout",
            "unavailable",
        }:
            continue
        failures.append(
            {
                key: deepcopy(run[key])
                for key in (
                    "tool",
                    "provider",
                    "status",
                    "error",
                    "error_code",
                    "message",
                    "duration_ms",
                    "retryable",
                )
                if key in run
            }
        )
    return failures


def build(response: dict[str, Any]) -> dict[str, Any]:
    response = apply_readiness_to_v2(deepcopy(response))
    readiness = evaluate_readiness(response)
    passport = deepcopy(_dict(response.get("evidence_passport")))
    target = deepcopy(_dict(response.get("target")))
    resolution = deepcopy(_dict(response.get("resolution")))
    resolved_target = _dict(resolution.get("target"))
    for key, value in resolved_target.items():
        target.setdefault(key, value)

    status = {
        "ok": response.get("ok") is not False,
        "request_status": str(response.get("request_status") or "completed"),
        "readiness": readiness,
        "fallback_used": bool(response.get("fallback_used")),
        "cached_data_returned": bool(response.get("cached_data_returned")),
    }
    return {
        "kind": KIND,
        "contract_version": CONTRACT_VERSION,
        "ok": status["ok"],
        "request_status": status["request_status"],
        "question": str(response.get("question") or ""),
        "target": target,
        "mode": deepcopy(_dict(response.get("mode"))),
        "action": str(response.get("action") or "omi.ask"),
        "caller_profile": str(response.get("caller_profile") or "unknown"),
        "status": status,
        "answer": _answer(response),
        "decision": _decision(response, readiness),
        "evidence": {
            "passport": passport,
            "freshness": deepcopy(_dict(response.get("freshness"))),
            "freshness_by_domain": _freshness_by_domain(response),
            "slots": canonical_slots(response),
            "result": _evidence_result(response),
            "source_refs": deepcopy(_list(response.get("source_refs"))),
        },
        "limitations": {
            "missing": _unique_strings(response.get("missing")),
            "warnings": _unique_strings(response.get("warnings")),
            "provider_failures": _provider_failures(response),
        },
        "execution": {
            "strategy_profile": response.get("strategy_profile"),
            "policy": deepcopy(_dict(response.get("policy"))),
            "query_plan": deepcopy(_dict(response.get("query_plan"))),
            "tool_plan": deepcopy(_dict(response.get("tool_plan"))),
            "tool_runs": deepcopy(_list(response.get("tool_runs"))),
            "reasoning_steps": deepcopy(_list(response.get("reasoning_steps"))),
            "diagnostics": deepcopy(_dict(response.get("diagnostics"))),
            "report_level": response.get("report_level"),
            "job": deepcopy(_dict(response.get("job"))),
            "cancellation": deepcopy(_dict(response.get("cancellation"))),
        },
        "continuation": {
            "resolution": resolution,
            "next_context": deepcopy(_dict(response.get("next_context"))),
            "clarification": deepcopy(_dict(response.get("clarification"))),
            "next_actions": deepcopy(_list(response.get("next_actions"))),
        },
        "error": deepcopy(_dict(response.get("error"))),
        "compatibility": {
            "source_contract_version": str(
                response.get("contract_version") or LEGACY_CONTRACT_VERSION
            ),
        },
    }


def for_requested_contract(
    response: dict[str, Any],
    *,
    requested_contract_version: str,
) -> dict[str, Any]:
    response = apply_readiness_to_v2(response)
    if requested_contract_version == CONTRACT_VERSION:
        return build(response)
    return response
