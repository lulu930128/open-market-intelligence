from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DispatchTemplateKey = Literal["market_overview", "watchlist_brief"]
DispatchScopeType = Literal["market", "watchlist"]


class DispatchRecipientGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    emails: list[str] = Field(default_factory=list)
    enabled: bool = True


class DispatchRecipientGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    emails: list[str] | None = None
    enabled: bool | None = None


class DispatchRecipientGroupRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    emails: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DispatchPreviewRequest(BaseModel):
    template_key: DispatchTemplateKey = "market_overview"
    scope_type: DispatchScopeType = "market"
    scope_id: str | int | None = None
    strategy_profile: str = "short_term_momentum"
    rank_by: str = "score"
    sort_order: str = "desc"
    radar_mode: str = "action"


class DispatchSendRequest(DispatchPreviewRequest):
    recipient_group_id: int


class DispatchPreviewRead(BaseModel):
    template_key: str
    scope_type: str
    scope_id: str | None = None
    subject: str
    body_text: str
    body_html: str
    generated_at: datetime
    as_of: str | None = None
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchDeliveryRead(BaseModel):
    id: int
    job_run_id: int | None = None
    recipient_group_id: int | None = None
    recipient_group_name: str | None = None
    template_key: str
    scope_type: str
    scope_id: str | None = None
    subject: str
    status: str
    recipient_count: int
    recipients: list[str] = Field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    preview: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DispatchSendRead(BaseModel):
    job: dict[str, Any]
    delivery: DispatchDeliveryRead


class DispatchDeleteResultRead(BaseModel):
    id: int
    deleted: bool
