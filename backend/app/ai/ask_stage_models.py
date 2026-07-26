from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai import decision_core
from app.ai.schemas import AiAskRequest


@dataclass(frozen=True)
class QuestionStage:
    payload: AiAskRequest
    requested_horizon: str
    effective_horizon: str
    question_understanding: decision_core.QuestionUnderstanding
    position_context: dict[str, Any]
    question_intent: str
    policy: dict[str, Any]
    requested_mode: str
    auto_mode_requested: bool


@dataclass(frozen=True)
class ToolStageState:
    tool_plan: dict[str, Any]
    tool_runs: list[dict[str, Any]]
    freshness_result: dict[str, Any]
    warnings: list[Any]


@dataclass(frozen=True)
class ModeExecutionResult:
    effective_mode: str
    action: str
    result: dict[str, Any]
    warnings: list[str]


@dataclass(frozen=True)
class ResponseAssembly:
    response_analysis: dict[str, Any]
    reasoning_steps: list[dict[str, str]]
    combined_missing: list[Any]
    combined_warnings: list[Any]
    result_source_refs: list[dict[str, Any]]
    analysis_digest: dict[str, Any]
    next_actions: list[dict[str, Any]]
    clarification: dict[str, Any]
    answer_ready: bool
    position_decision: dict[str, Any]
    consumer_human_answer: dict[str, Any]
    analysis_ready: bool = False
    decision_ready: bool = False
    blocked_sections: list[str] = field(default_factory=list)
    available_sections: list[str] = field(default_factory=list)
