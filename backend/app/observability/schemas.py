from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ProviderEventRead(BaseModel):
    id: int
    market: str
    provider: str
    resource: str
    target: str
    status: str
    severity: str
    event_type: str
    event_time: datetime
    observed_at: datetime
    http_status_code: int | None = None
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    duration_ms: int | None = None
    source_url: str | None = None
    message: str | None = None
    error_message: str | None = None
    job_run_id: int | None = None
    fetch_log_id: int | None = None
    raw_result_id: int | None = None
    created_at: datetime


class SourceHealthSnapshotRead(BaseModel):
    id: int
    market: str
    resource: str
    target: str
    provider: str
    status: str
    ok: bool
    row_count: int
    required: bool
    data_quality: str
    latest_data_date: date | None = None
    latest_data_key: str | None = None
    latest_observed_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    release_status: str | None = None
    reason: str | None = None
    latest_event_id: int | None = None
    latest_event_at: datetime | None = None
    latest_event_status: str | None = None
    latest_event_severity: str | None = None
    latest_event_message: str | None = None
    recent_event_count: int = 0
    recent_error_count: int = 0
    consecutive_error_count: int = 0
    checked_at: datetime
    snapshot_age_seconds: int = 0
    snapshot_is_stale: bool = False
    created_at: datetime
    updated_at: datetime
