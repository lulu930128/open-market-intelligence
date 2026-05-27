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


class AiReportEnvelope(AiDataEnvelope):
    strategy_profile: str
    prompt: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


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
