from __future__ import annotations

from typing import Any


DECISION_CONTRACT_KIND = "omi_ai_decision_contract"
DECISION_CONTRACT_VERSION = "decision_contract.v1"
DECISION_SECTION_KEYS = (
    "summary",
    "action_plan",
    "scenarios",
    "counter_evidence",
    "risks",
    "data_limits",
)


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    for item in value:
        text = _text_value(item)
        if text is None or text in items:
            continue
        items.append(text)
        if limit is not None and len(items) >= limit:
            break
    return items


def _labeled_text_items(value: Any, *, limit: int | None = None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    items: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = _text_value(item.get("text"))
        if text is None:
            continue
        normalized = {"text": text}
        label = _text_value(item.get("label"))
        if label:
            normalized["label"] = label
        if normalized in items:
            continue
        items.append(normalized)
        if limit is not None and len(items) >= limit:
            break
    return items


def _target_summary(target: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "type",
        "id",
        "symbol",
        "stock_id",
        "market",
        "exchange",
        "label",
        "name",
    ):
        if key in target and target.get(key) is not None:
            summary[key] = target.get(key)
    return summary


def _freshness_summary(freshness_result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "is_current",
        "refresh_recommended",
        "status",
        "summary",
        "expected_trade_date",
        "latest_trade_date",
        "as_of",
    ):
        if key in freshness_result and freshness_result.get(key) is not None:
            summary[key] = freshness_result.get(key)
    return summary


def _cross_market_context_summary(
    human_answer: dict[str, Any],
) -> dict[str, Any] | None:
    context = human_answer.get("cross_market_context")
    if not isinstance(context, dict) or not context:
        return None
    coverage = context.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    return {
        "kind": context.get("kind") or "cross_market_decision_context_v1",
        "role": (
            human_answer.get("context_role")
            or context.get("role")
            or "confirmation_or_counter_evidence"
        ),
        "ranking_effect": (
            human_answer.get("ranking_effect")
            or context.get("ranking_effect")
            or "none"
        ),
        "technical_score_effect": (
            human_answer.get("technical_score_effect")
            or context.get("technical_score_effect")
            or "none"
        ),
        "status": context.get("status"),
        "decision_usable": context.get("decision_usable") is True,
        "stance": context.get("stance"),
        "confidence": context.get("confidence"),
        "title": context.get("title"),
        "as_of": context.get("as_of"),
        "decision_at": context.get("decision_at"),
        "snapshot_id": context.get("snapshot_id"),
        "methodology_version": context.get("methodology_version"),
        "relation_snapshot_version": context.get("relation_snapshot_version"),
        "coverage": {
            key: coverage.get(key)
            for key in (
                "configured_signal_count",
                "available_signal_count",
                "decision_usable_signal_count",
                "coverage_ratio",
                "excluded_by_reason",
            )
            if key in coverage
        },
        "missing": _text_list(context.get("missing"), limit=8),
        "warnings": _text_list(context.get("warnings"), limit=8),
        "limitations": _text_list(context.get("limitations"), limit=8),
    }


def build_decision_contract(
    *,
    question_intent: str,
    target: dict[str, Any],
    human_answer: dict[str, Any],
    freshness_result: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    answer_ready: bool,
    decision_ready: bool | None = None,
    blocked_sections: list[str] | None = None,
) -> dict[str, Any]:
    """Project the backend-owned human answer into a stable consumer contract."""

    headline = _text_value(human_answer.get("headline"))
    text = _text_value(human_answer.get("text"))
    summary = _text_list(human_answer.get("summary"), limit=6)
    action_plan = _labeled_text_items(human_answer.get("action_plan"), limit=6)
    scenarios = _labeled_text_items(human_answer.get("scenarios"), limit=6)
    counter_evidence = _text_list(human_answer.get("counter_evidence"), limit=6)
    risks = _text_list(human_answer.get("risks"), limit=6)
    data_limits = _text_list(human_answer.get("data_limits"), limit=6)
    missing_keys = _text_list(missing, limit=12)
    warning_texts = _text_list(warnings, limit=12)
    cross_market_context = _cross_market_context_summary(human_answer)

    sections = {
        "summary": summary,
        "action_plan": action_plan,
        "scenarios": scenarios,
        "counter_evidence": counter_evidence,
        "risks": risks,
        "data_limits": data_limits,
    }

    context = {}
    if cross_market_context is not None:
        context["cross_market"] = cross_market_context

    return {
        "kind": DECISION_CONTRACT_KIND,
        "version": DECISION_CONTRACT_VERSION,
        "intent": question_intent,
        "answer_source": _text_value(human_answer.get("source")),
        "answer_style": _text_value(human_answer.get("style")),
        "target": _target_summary(target),
        "headline": headline,
        "text": text,
        "sections": sections,
        "context": context,
        "readiness": {
            "answer_ready": bool(answer_ready),
            "decision_ready": bool(
                decision_ready if decision_ready is not None else answer_ready and action_plan
            ),
            "has_text": bool(text),
            "has_action_plan": bool(action_plan),
            "has_scenarios": bool(scenarios),
            "has_counter_evidence": bool(counter_evidence),
            "has_risks": bool(risks),
            "has_data_limits": bool(data_limits),
            "has_missing": bool(missing_keys),
            "has_warnings": bool(warning_texts),
            "has_context": bool(context),
        },
        "blocked_sections": list(dict.fromkeys(blocked_sections or [])),
        "freshness": _freshness_summary(freshness_result),
        "missing": missing_keys,
        "warnings": warning_texts,
    }
