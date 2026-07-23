from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AiToolRead(BaseModel):
    name: str
    title: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AiToolListRead(BaseModel):
    tools: list[AiToolRead]


class StrategyProfileRead(BaseModel):
    key: str
    label: str
    description: str
    focus_points: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class AiDataEnvelope(BaseModel):
    kind: str
    generated_at: datetime
    as_of: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)
    evidence_passport: dict[str, Any] = Field(default_factory=dict)


class AiReportEnvelope(AiDataEnvelope):
    strategy_profile: str
    prompt: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class AiAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=4000)
    contract_version: str = Field(default="omi.ai.ask.v2", min_length=1, max_length=80)
    target: dict[str, Any] = Field(default_factory=lambda: {"type": "auto"})
    mode: str = Field(default="auto", min_length=1, max_length=50)
    payload_level: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="summary, compact, standard, or full. Kept separate from answer mode.",
    )
    diagnostics_level: str = Field(
        default="none",
        min_length=1,
        max_length=20,
        description="none, basic, or debug. Diagnostics do not change answer semantics.",
    )
    caller_profile: str = Field(
        default="kuro_readonly",
        min_length=1,
        max_length=80,
        description="Caller label only. Server-side policy decides trust.",
    )
    allow_llm: bool = False
    allow_write: bool = False
    allow_external_fetch: bool = False
    tool_budget: dict[str, Any] = Field(default_factory=dict)
    refresh_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "mode": "stale_first",
            "before_answer": True,
            "fallback_to_cached": True,
        }
    )
    strategy_profile: str = Field(default="short_term_momentum", min_length=1, max_length=80)
    analysis_horizon: str = Field(
        default="auto",
        min_length=1,
        max_length=50,
        description="auto, intraday, short, swing, or long. auto defaults to swing for Taiwan stock analysis.",
    )
    branch_days: int = Field(default=5, ge=1, le=120)
    rank_by: str = Field(default="score", min_length=1, max_length=50)
    sort_order: str = Field(default="desc", min_length=1, max_length=10)
    market_limit: int = Field(default=10, ge=1, le=50)
    context_limit: int = Field(default=100, ge=20, le=500)
    include_children: bool = True
    enabled_only: bool = True
    market_data_params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional bounded data-shape parameters for market-specific readers, "
            "for example provider, providers, symbols, interval, timeframe, bars, limit, "
            "include_intraday, payload_level, or intraday_limit. payload_level supports "
            "summary, compact, standard, and full."
        ),
    )
    position_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional caller-supplied position context. The backend may also attach "
            "saved portfolio context for the resolved stock target."
        ),
    )
    conversation_context: dict[str, Any] = Field(default_factory=dict)


class AiAskResponse(BaseModel):
    kind: str = "ai_ask"
    contract_version: str = "omi.ai.ask.v2"
    ok: bool = True
    question: str
    target: dict[str, Any] = Field(default_factory=dict)
    mode: dict[str, Any] = Field(default_factory=dict)
    action: str
    strategy_profile: str
    caller_profile: str
    resolution: dict[str, Any] = Field(default_factory=dict)
    next_context: dict[str, Any] = Field(default_factory=dict)
    clarification: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    answer_ready: bool = True
    facts_ready: bool = True
    analysis_ready: bool = False
    decision_ready: bool = False
    blocked_sections: list[str] = Field(default_factory=list)
    available_sections: list[str] = Field(default_factory=list)
    request_status: str = "completed"
    fallback_used: bool = False
    cached_data_returned: bool = False
    job: dict[str, Any] = Field(default_factory=dict)
    cancellation: dict[str, Any] = Field(default_factory=dict)
    report_level: str = "data_only"
    analysis: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    tool_plan: dict[str, Any] = Field(default_factory=dict)
    tool_runs: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_passport: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)


class AiDecisionEnvelope(BaseModel):
    kind: str = "omi_decision"
    contract_version: str = "omi.decision.v3"
    ok: bool = True
    request_status: str = "completed"
    question: str
    target: dict[str, Any] = Field(default_factory=dict)
    mode: dict[str, Any] = Field(default_factory=dict)
    action: str = "omi.ask"
    caller_profile: str = "unknown"
    status: dict[str, Any] = Field(default_factory=dict)
    answer: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    limitations: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    continuation: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)


class AiMemoryCreate(BaseModel):
    memory_type: str = Field(..., min_length=1, max_length=50)
    scope_type: str = Field(default="global", min_length=1, max_length=50)
    scope_id: str | None = Field(default=None, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance: int = Field(default=50, ge=0, le=100)
    source: str = Field(default="user", min_length=1, max_length=80)
    created_by: str | None = Field(default=None, max_length=120)


class AiMemoryUpdate(BaseModel):
    memory_type: str | None = Field(default=None, min_length=1, max_length=50)
    scope_type: str | None = Field(default=None, min_length=1, max_length=50)
    scope_id: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    importance: int | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    source: str | None = Field(default=None, min_length=1, max_length=80)


class AiMemoryRead(BaseModel):
    id: int
    memory_type: str
    scope_type: str
    scope_id: str | None = None
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    importance: int
    status: str
    source: str
    created_by: str | None = None
    last_used_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiToolCallRead(BaseModel):
    id: int
    report_id: int | None = None
    tool_name: str
    status: str
    source: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiStoredReportRead(BaseModel):
    id: int
    report_type: str
    scope_type: str
    scope_id: str | None = None
    strategy_profile: str
    title: str | None = None
    as_of: str | None = None
    status: str
    model_name: str | None = None
    job_run_id: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    prompt: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    memory_refs: list[int] = Field(default_factory=list)
    tool_calls: list[AiToolCallRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
