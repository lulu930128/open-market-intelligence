from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DispatchTemplateKey = Literal["market_overview", "watchlist_brief"]
DispatchScopeType = Literal["market", "watchlist"]
DispatchContentDepth = Literal["standard", "deep"]
DispatchCalendarMode = Literal["calendar_days", "weekdays", "tw_trading_days"]
DispatchCatchupMode = Literal["latest_only", "all_slots"]
DispatchMisfirePolicy = Literal["catch_up", "skip"]
DispatchReadinessProfile = Literal[
    "generic",
    "tw_preopen",
    "tw_post_close",
    "watchlist_radar",
]
DispatchReadinessPolicy = Literal[
    "immediate",
    "wait_until_ready",
    "skip_if_incomplete",
]


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
    include_radar: bool = False
    radar_group_id: int | None = Field(default=None, ge=1)
    radar_mode: str = "action"
    content_depth: DispatchContentDepth = "standard"
    radar_limit: int = Field(default=8, ge=1, le=24)


class DispatchSendRequest(DispatchPreviewRequest):
    recipient_group_id: int


class DispatchScheduleCreate(DispatchPreviewRequest):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    recipient_group_id: int = Field(..., ge=1)
    enabled: bool = True
    send_time: str = Field(default="08:55", min_length=4, max_length=5)
    day_of_week: str = Field(default="mon-fri", min_length=3, max_length=80)
    timezone: str = Field(default="Asia/Taipei", min_length=1, max_length=80)
    calendar_mode: DispatchCalendarMode = "weekdays"
    catchup_mode: DispatchCatchupMode = "latest_only"
    misfire_policy: DispatchMisfirePolicy = "catch_up"
    misfire_grace_minutes: int = Field(default=15, ge=0, le=1440)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_interval_seconds: int = Field(default=300, ge=10, le=3600)
    readiness_profile: DispatchReadinessProfile = "generic"
    readiness_policy: DispatchReadinessPolicy = "immediate"
    readiness_deadline_minutes: int = Field(default=60, ge=0, le=1440)
    readiness_retry_interval_seconds: int = Field(default=300, ge=10, le=3600)


class DispatchScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    recipient_group_id: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    send_time: str | None = Field(default=None, min_length=4, max_length=5)
    day_of_week: str | None = Field(default=None, min_length=3, max_length=80)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    calendar_mode: DispatchCalendarMode | None = None
    catchup_mode: DispatchCatchupMode | None = None
    misfire_policy: DispatchMisfirePolicy | None = None
    misfire_grace_minutes: int | None = Field(default=None, ge=0, le=1440)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    readiness_profile: DispatchReadinessProfile | None = None
    readiness_policy: DispatchReadinessPolicy | None = None
    readiness_deadline_minutes: int | None = Field(default=None, ge=0, le=1440)
    readiness_retry_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    template_key: DispatchTemplateKey | None = None
    scope_type: DispatchScopeType | None = None
    scope_id: str | int | None = None
    strategy_profile: str | None = None
    rank_by: str | None = None
    sort_order: str | None = None
    include_radar: bool | None = None
    radar_group_id: int | None = Field(default=None, ge=1)
    radar_mode: str | None = None
    content_depth: DispatchContentDepth | None = None
    radar_limit: int | None = Field(default=None, ge=1, le=24)


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
    message_id: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DispatchSendRead(BaseModel):
    job: dict[str, Any]
    delivery: DispatchDeliveryRead


class DispatchScheduleRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    recipient_group_id: int | None = None
    recipient_group_name: str | None = None
    enabled: bool
    send_time: str
    day_of_week: str
    timezone: str
    template_key: str
    scope_type: str
    scope_id: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    next_run_at: datetime | None = None
    calendar_mode: str = "weekdays"
    catchup_mode: str = "latest_only"
    misfire_policy: str = "catch_up"
    misfire_grace_minutes: int = 15
    max_retries: int = 2
    retry_interval_seconds: int = 300
    readiness_profile: str = "generic"
    readiness_policy: str = "immediate"
    readiness_deadline_minutes: int = 60
    readiness_retry_interval_seconds: int = 300
    last_queued_at: datetime | None = None
    last_sent_at: datetime | None = None
    last_skipped_at: datetime | None = None
    last_status: str = "never_run"
    archived_at: datetime | None = None
    last_run_key: str | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None
    last_delivery_id: int | None = None
    last_job_run_id: int | None = None
    created_at: datetime
    updated_at: datetime


class DispatchScheduleRunRead(BaseModel):
    id: int
    run_token: str
    schedule_id: int
    schedule_name: str | None = None
    retry_of_run_id: int | None = None
    trigger_type: str
    scheduled_for: datetime
    scheduled_slot_key: str | None = None
    status: str
    schedule_snapshot: dict[str, Any] = Field(default_factory=dict)
    readiness: dict[str, Any] | None = None
    readiness_check_count: int = 0
    delivery_attempt_count: int = 0
    max_delivery_attempts: int = 1
    next_action_at: datetime | None = None
    retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None
    delivery_id: int | None = None
    job_run_id: int | None = None
    claimed_at: datetime | None = None
    queued_at: datetime | None = None
    sending_at: datetime | None = None
    sent_at: datetime | None = None
    skipped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DispatchDeleteResultRead(BaseModel):
    id: int
    deleted: bool
