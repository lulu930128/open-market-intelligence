"""Truthful data-usability evaluation for technical research."""

from __future__ import annotations

from typing import Any

from app.research.technical.profiles import MarketAnalysisProfile


def evaluate_technical_usability(
    *,
    bar_count: int,
    profile: MarketAnalysisProfile,
    freshness_status: str,
    facts_usable: bool,
    corporate_action_coverage: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    corporate_action_satisfied = (
        corporate_action_coverage == "complete"
        or (
            profile.corporate_action_policy == "not_applicable"
            and corporate_action_coverage == "not_applicable"
        )
    )
    if not facts_usable:
        reasons.append("RESOLVED_BARS_NOT_FACTS_USABLE")
    if bar_count < profile.facts_minimum_bars:
        reasons.append("INSUFFICIENT_FACT_BARS")
    if freshness_status not in {"fresh", "current", "latest_completed_session"}:
        reasons.append("DAILY_BARS_NOT_CURRENT")
    if bar_count < profile.decision_minimum_bars:
        reasons.append("INSUFFICIENT_DECISION_BARS")
    if not corporate_action_satisfied:
        reasons.append("CORPORATE_ACTION_COVERAGE_INCOMPLETE")

    facts_ready = (
        facts_usable
        and bar_count >= profile.facts_minimum_bars
        and freshness_status in {"fresh", "current", "latest_completed_session"}
    )
    decision_ready = (
        facts_ready
        and bar_count >= profile.decision_minimum_bars
        and corporate_action_satisfied
    )
    status = "available" if decision_ready else "partial" if facts_ready else "missing"
    return {
        "status": status,
        "facts_usable": facts_ready,
        "decision_usable": decision_ready,
        "bar_count": bar_count,
        "facts_minimum_bars": profile.facts_minimum_bars,
        "decision_minimum_bars": profile.decision_minimum_bars,
        "corporate_action_coverage": corporate_action_coverage,
        "freshness_status": freshness_status,
        "reason_codes": reasons,
    }


__all__ = ["evaluate_technical_usability"]
