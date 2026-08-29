"""Pure repository contracts for persisted canonical market-data candidates.

The Foundation defines read contracts only. SQL/ORM implementations live in a
market or infrastructure-owned module and must not perform provider I/O,
selection, refresh, commit, or rollback while serving these reads.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import Field, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    BarObservation,
    CanonicalModel,
    InstrumentKey,
)


MAX_DAILY_CANDIDATE_RANGE_DAYS = 36_600


class DailyBarCandidateQuery(CanonicalModel):
    contract_version: str = "omi.market.daily_bar_candidate_query.v1"
    instrument: InstrumentKey
    start_date: date
    end_date: date
    available_at: datetime | None = None
    max_rows: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def _validate_range(self) -> DailyBarCandidateQuery:
        if self.available_at is not None and (
            self.available_at.tzinfo is None
            or self.available_at.utcoffset() is None
        ):
            raise ValueError("available_at must be timezone-aware")
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        if (
            self.end_date - self.start_date
        ).days > MAX_DAILY_CANDIDATE_RANGE_DAYS:
            raise ValueError(
                "daily candidate range cannot exceed "
                f"{MAX_DAILY_CANDIDATE_RANGE_DAYS} days"
            )
        return self


class PersistedBarSeries(CanonicalModel):
    contract_version: str = "omi.market.persisted_bar_series.v1"
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    authority: AuthorityClass
    provider_priority: int = Field(ge=0)
    bars: tuple[BarObservation, ...]
    storage_row_ids: tuple[int, ...]
    raw_result_ids: tuple[int, ...]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_series(self) -> PersistedBarSeries:
        if not self.bars:
            raise ValueError("persisted bar series requires at least one bar")
        if len(self.storage_row_ids) != len(self.bars):
            raise ValueError("storage_row_ids must align with bars")
        if len(self.raw_result_ids) != len(self.bars):
            raise ValueError("raw_result_ids must align with bars")
        instrument = self.bars[0].instrument
        interval = self.bars[0].interval
        if any(bar.instrument != instrument for bar in self.bars):
            raise ValueError("persisted bars must share one instrument")
        if any(bar.interval != interval for bar in self.bars):
            raise ValueError("persisted bars must share one interval")
        if any(bar.lineage.provider != self.provider for bar in self.bars):
            raise ValueError("persisted bars must match declared provider lineage")
        if any(bar.lineage.source != self.source for bar in self.bars):
            raise ValueError("persisted bars must match declared source lineage")
        if any(bar.lineage.authority is not self.authority for bar in self.bars):
            raise ValueError("persisted bars must match declared authority lineage")
        if any(
            current.start_at >= following.start_at
            for current, following in zip(self.bars, self.bars[1:])
        ):
            raise ValueError("persisted bars must be strictly ordered")
        return self


class CandidateRowRejection(CanonicalModel):
    contract_version: str = "omi.market.candidate_row_rejection.v1"
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    storage_row_id: int = Field(ge=1)
    raw_result_id: int = Field(ge=1)
    event_date: date
    reason_code: str = Field(min_length=1, max_length=64)
    missing_fields: tuple[str, ...] = ()


class DailyBarCandidateRead(CanonicalModel):
    contract_version: str = "omi.market.daily_bar_candidate_read.v1"
    query: DailyBarCandidateQuery
    series: tuple[PersistedBarSeries, ...] = ()
    rejections: tuple[CandidateRowRejection, ...] = ()
    rows_examined: int = Field(ge=0)
    rows_accepted: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> DailyBarCandidateRead:
        accepted = sum(len(item.bars) for item in self.series)
        if accepted != self.rows_accepted:
            raise ValueError("rows_accepted must equal the number of canonical bars")
        if self.rows_accepted + len(self.rejections) != self.rows_examined:
            raise ValueError("every examined row must be accepted or explicitly rejected")
        return self


class DailyBarCandidateRepository(Protocol):
    """Read persisted daily candidates without acquisition or transactions."""

    def load_daily_bars(self, query: DailyBarCandidateQuery) -> DailyBarCandidateRead: ...


class CandidateReadLimitExceeded(ValueError):
    """Raised when a bounded repository read would silently truncate rows."""


__all__ = [
    "CandidateReadLimitExceeded",
    "CandidateRowRejection",
    "DailyBarCandidateQuery",
    "DailyBarCandidateRead",
    "DailyBarCandidateRepository",
    "MAX_DAILY_CANDIDATE_RANGE_DAYS",
    "PersistedBarSeries",
]
