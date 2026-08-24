from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EODCoverageCheckpointRead(BaseModel):
    checkpoint_version: str
    id: int
    dataset_id: str
    market: str
    scope_kind: str
    scope_key: str
    expected_trade_date: date
    latest_data_date: date | None = None
    universe_source: str
    universe_hash: str
    universe_count: int
    current_count: int
    partial_count: int
    stale_count: int
    missing_count: int
    coverage_ratio: float
    observed_ratio: float
    status: str
    repair_status: str
    repair_provider: str | None = None
    cursor_symbol: str | None = None
    attempted_count: int
    succeeded_count: int
    failed_count: int
    consecutive_error_count: int
    last_job_id: int | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    next_retry_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime
    created_at: datetime
    updated_at: datetime


class EODCoverageListRead(BaseModel):
    contract_version: str = "omi.market.eod_coverage.v1"
    status: str
    cache_only: bool = True
    checkpoint_count: int
    checkpoints: list[EODCoverageCheckpointRead]
    limitations: list[str] = Field(default_factory=list)


class EODCoverageReconcileRequest(BaseModel):
    market: Literal["TW", "US"]
    repair: bool = True
    expected_trade_date: date | None = None
    max_symbols: int = Field(default=250, ge=1, le=500)
    max_runtime_seconds: int = Field(default=600, ge=30, le=1800)
    sleep_seconds: float = Field(default=1.0, ge=0, le=30)
    max_consecutive_errors: int = Field(default=5, ge=1, le=20)


__all__ = [
    "EODCoverageCheckpointRead",
    "EODCoverageListRead",
    "EODCoverageReconcileRequest",
]
