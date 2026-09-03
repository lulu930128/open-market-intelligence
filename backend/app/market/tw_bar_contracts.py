"""Taiwan-owned contracts for canonical and derived Bar series.

The shared market-data foundation remains provider-neutral. Session policy,
bucket applicability, history depth, and Taiwan outward revision semantics live
here so consumers cannot recreate them.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    CanonicalModel,
    InstrumentKey,
)
from app.market_data.integration_contracts import BarSeriesResolutionMode


TAIWAN_BASE_BAR_INTERVALS = frozenset({"1m", "1d"})
TAIWAN_INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})
TAIWAN_DAILY_INTERVALS = frozenset({"1d", "1w", "1mo"})
TAIWAN_BAR_INTERVALS = TAIWAN_INTRADAY_INTERVALS | TAIWAN_DAILY_INTERVALS

TAIWAN_CANONICAL_1M_MIN_RETENTION_DAYS = 100
TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION = "tw.index.minute.materialize.v1"
TAIWAN_INDEX_MINUTE_RAW_CONTRACT = "tw.index.minute.candidate.v1"
TAIEX_OFFICIAL_DAILY_PROVIDER = "twse_index_daily_ohlc"
TAIEX_OFFICIAL_DAILY_SOURCE = "twse_indices_report_mi_5mins_hist"
TPEX_DERIVED_DAILY_PROVIDER = "tpex_index_5s"
TPEX_DERIVED_DAILY_SOURCE = "tpex_index_5s_components"
TPEX_OFFICIAL_5S_COMPONENT_SOURCE = "tpex_index_5s"
TPEX_OFFICIAL_5S_PARSER_VERSION = "tpex.index_5s.v1"
TAIWAN_DAILY_MATERIALIZATION_VERSION = "tw.daily.materialize.v1"
TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION = "tw.tpex.daily.materialize.v2"
TPEX_DERIVED_DAILY_KIND = "exchange_intraday_components_to_completed_daily"
TAIWAN_HISTORY_SLO_CALENDAR_DAYS = {
    "5m": 31,
    "15m": 31,
    "30m": 31,
    "1h": 93,
    "4h": 93,
}
TAIWAN_1M_HISTORY_SLO_TRADING_SESSIONS = 5


class BarBucketCoverageStatus(str, Enum):
    OBSERVED_TRADE = "observed_trade"
    VERIFIED_NO_TRADE = "verified_no_trade"
    MISSING_EVIDENCE = "missing_evidence"
    NOT_APPLICABLE = "not_applicable"


class TaiwanHistoryStatus(str, Enum):
    READY = "ready"
    WARMING_UP = "warming_up"
    PARTIAL = "partial"
    MISSING = "missing"


class TaiwanCurrentSessionCoverageStatus(str, Enum):
    COMPLETE_PREFIX = "complete_prefix"
    COMPLETE_SESSION = "complete_session"
    TRAILING_WINDOW = "trailing_window"
    PARTIAL_PREFIX = "partial_prefix"
    PARTIAL_WINDOW = "partial_window"
    SPARSE = "sparse"
    MISSING = "missing"


class TaiwanCurrentSessionSnapshotPhase(str, Enum):
    WARMING = "warming"
    READY = "ready"
    DEGRADED = "degraded"


class TaiwanReleaseStatus(str, Enum):
    PENDING_RELEASE = "pending_release"
    RELEASED = "released"
    NOT_APPLICABLE = "not_applicable"


class TaiwanReconciliationStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    NOT_APPLICABLE = "not_applicable"


class TaiwanDerivedBucketCoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"


class BarBucketCoverage(CanonicalModel):
    contract_version: str = "tw.bar.bucket_coverage.v1"
    bucket_start: datetime
    bucket_end: datetime
    status: BarBucketCoverageStatus
    expected_by_trading_policy: bool
    evidence_refs: tuple[str, ...] = ()
    source_observation_count: int = Field(default=0, ge=0)
    reason_code: str = Field(min_length=1, max_length=96)
    qualification_method: str | None = Field(default=None, max_length=96)
    verified_by: str | None = Field(default=None, max_length=96)
    trading_policy_version: str = Field(min_length=1, max_length=96)
    coverage_algorithm_version: str = Field(min_length=1, max_length=96)

    @field_validator("bucket_start", "bucket_end")
    @classmethod
    def _require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bucket timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_qualification(self) -> BarBucketCoverage:
        if self.bucket_end <= self.bucket_start:
            raise ValueError("bucket_end must be after bucket_start")
        if self.status is BarBucketCoverageStatus.OBSERVED_TRADE:
            if self.source_observation_count < 1 or not self.evidence_refs:
                raise ValueError("observed_trade requires positive evidence")
        if self.status is BarBucketCoverageStatus.VERIFIED_NO_TRADE:
            if not self.evidence_refs or not self.qualification_method or not self.verified_by:
                raise ValueError(
                    "verified_no_trade requires qualified positive evidence and owner"
                )
        if self.status is BarBucketCoverageStatus.NOT_APPLICABLE:
            if self.expected_by_trading_policy:
                raise ValueError("not_applicable cannot be expected by trading policy")
        return self


class TaiwanSessionResolutionManifest(CanonicalModel):
    contract_version: str = "tw.bar.session_resolution.v2"
    trade_date: date
    resolution_mode: BarSeriesResolutionMode
    current_session: bool
    selected_candidate_id: str | None = Field(default=None, max_length=160)
    contributor_candidate_ids: tuple[str, ...] = ()
    rejected_candidate_reasons: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    filled_bucket_count: int = Field(default=0, ge=0)
    conflict_bucket_count: int = Field(default=0, ge=0)
    coverage_status: TaiwanHistoryStatus

    @model_validator(mode="after")
    def _validate_resolution_mode(self) -> TaiwanSessionResolutionManifest:
        if self.current_session:
            if self.resolution_mode is not BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP:
                raise ValueError(
                    "current Taiwan session must use COMPOSE_BY_TIMESTAMP"
                )
            if self.selected_candidate_id is not None:
                raise ValueError(
                    "composed current Taiwan session cannot expose one selected candidate"
                )
        return self


class TaiwanMissingBarRange(CanonicalModel):
    start_at: datetime
    end_at: datetime
    bucket_count: int = Field(ge=1, le=500)

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_aware_range_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("missing range timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> TaiwanMissingBarRange:
        if self.end_at <= self.start_at:
            raise ValueError("missing range end_at must be after start_at")
        return self


class TaiwanCurrentSessionCoverage(CanonicalModel):
    contract_version: str = "tw.bar.current_session_coverage.v2"
    trade_date: date
    status: TaiwanCurrentSessionCoverageStatus
    snapshot_phase: TaiwanCurrentSessionSnapshotPhase
    snapshot_revision: str = Field(min_length=64, max_length=64)
    snapshot_bar_count: int = Field(ge=0, le=5000)
    snapshot_available_from: datetime | None = None
    snapshot_available_to: datetime | None = None
    snapshot_reason_codes: tuple[str, ...] = ()
    expected_from: datetime
    expected_to: datetime
    expected_bucket_count: int = Field(ge=0, le=500)
    observed_bucket_count: int = Field(ge=0, le=500)
    missing_bucket_count: int = Field(ge=0, le=500)
    missing_ranges: tuple[TaiwanMissingBarRange, ...] = Field(
        default=(), max_length=32
    )
    repair_recommended: bool = False
    repair_operation_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_counts(self) -> TaiwanCurrentSessionCoverage:
        if self.expected_to < self.expected_from:
            raise ValueError("current-session expected_to cannot precede expected_from")
        if self.observed_bucket_count + self.missing_bucket_count != self.expected_bucket_count:
            raise ValueError("current-session coverage counts must partition expected buckets")
        if self.repair_recommended != bool(self.repair_operation_id):
            raise ValueError("repair recommendation requires an operation id")
        if self.missing_bucket_count == 0 and self.missing_ranges:
            raise ValueError("complete coverage cannot expose missing ranges")
        if self.snapshot_bar_count == 0:
            if self.snapshot_available_from is not None or self.snapshot_available_to is not None:
                raise ValueError("empty snapshot cannot expose available bounds")
        else:
            if self.snapshot_available_from is None or self.snapshot_available_to is None:
                raise ValueError("non-empty snapshot requires available bounds")
            if self.snapshot_available_to <= self.snapshot_available_from:
                raise ValueError("snapshot available_to must follow available_from")
        for value in (self.snapshot_available_from, self.snapshot_available_to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("snapshot bounds must be timezone-aware")
        if not self.snapshot_reason_codes:
            raise ValueError("snapshot phase requires at least one reason code")
        return self


class TaiwanHistoryCoverage(CanonicalModel):
    contract_version: str = "tw.bar.history_coverage.v1"
    requested_from: datetime
    requested_to: datetime
    available_from: datetime | None = None
    available_to: datetime | None = None
    requested_session_count: int = Field(ge=0)
    covered_session_count: int = Field(ge=0)
    history_status: TaiwanHistoryStatus
    requested_coverage_satisfied: bool
    limitations: tuple[str, ...] = ()

    @field_validator("requested_from", "requested_to", "available_from", "available_to")
    @classmethod
    def _require_aware_history_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("history timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_history_range(self) -> TaiwanHistoryCoverage:
        if self.requested_to <= self.requested_from:
            raise ValueError("requested_to must be after requested_from")
        if self.covered_session_count > self.requested_session_count:
            raise ValueError("covered_session_count cannot exceed requested_session_count")
        if (self.available_from is None) != (self.available_to is None):
            raise ValueError("available_from and available_to must be provided together")
        if self.available_from is not None and self.available_to < self.available_from:
            raise ValueError("available_to cannot be before available_from")
        return self


class TaiwanDerivedBucketCoverage(CanonicalModel):
    contract_version: str = "tw.bar.derived_bucket_coverage.v1"
    bucket_start: datetime
    bucket_end: datetime
    status: TaiwanDerivedBucketCoverageStatus
    component_count: int = Field(ge=0)
    expected_component_count: int = Field(ge=0)
    observed_trade_count: int = Field(ge=0)
    verified_no_trade_count: int = Field(ge=0)
    missing_evidence_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    session_truncated: bool = False

    @field_validator("bucket_start", "bucket_end")
    @classmethod
    def _require_aware_bucket_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("derived bucket timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_partition(self) -> TaiwanDerivedBucketCoverage:
        if self.bucket_end <= self.bucket_start:
            raise ValueError("bucket_end must be after bucket_start")
        partition = (
            self.observed_trade_count
            + self.verified_no_trade_count
            + self.missing_evidence_count
            + self.not_applicable_count
        )
        if partition != self.expected_component_count:
            raise ValueError("derived coverage counts must partition expected components")
        if self.component_count != self.observed_trade_count:
            raise ValueError("component_count must equal observed_trade_count")
        if self.status is TaiwanDerivedBucketCoverageStatus.COMPLETE:
            if self.missing_evidence_count:
                raise ValueError("complete derived coverage cannot contain missing evidence")
        if self.status is TaiwanDerivedBucketCoverageStatus.MISSING:
            if self.component_count:
                raise ValueError("missing derived coverage cannot contain observed bars")
        return self


class TaiwanBarSeriesIdentity(CanonicalModel):
    contract_version: str = "tw.bar.series_identity.v1"
    series_fingerprint: str = Field(min_length=64, max_length=64)
    lineage_digest: str = Field(min_length=64, max_length=64)
    state_digest: str = Field(min_length=64, max_length=64)
    series_revision: str = Field(min_length=64, max_length=64)


class TaiwanBarOutwardState(CanonicalModel):
    contract_version: str = "tw.bar.outward_state.v1"
    start_at: datetime
    finalization: BarFinalization
    authority: AuthorityClass
    official: bool
    release_status: TaiwanReleaseStatus
    reconciliation_status: TaiwanReconciliationStatus
    persisted: bool
    source_interval: str
    technical_eligible: bool = True


class TaiwanBarSeriesRead(CanonicalModel):
    contract_version: str = "tw.bar.series_read.v1"
    instrument: InstrumentKey
    requested_interval: str
    base_interval: str
    derived: bool
    aggregation_version: str | None = None
    bars: tuple[BarObservation, ...] = ()
    bar_states: tuple[TaiwanBarOutwardState, ...] = ()
    bucket_coverage: tuple[BarBucketCoverage | TaiwanDerivedBucketCoverage, ...] = ()
    history: TaiwanHistoryCoverage
    session_resolution: tuple[TaiwanSessionResolutionManifest, ...] = ()
    current_session_coverage: TaiwanCurrentSessionCoverage | None = None
    identity: TaiwanBarSeriesIdentity
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _align_bar_states(self) -> TaiwanBarSeriesRead:
        if len(self.bar_states) != len(self.bars):
            raise ValueError("bar_states must align with bars")
        if any(
            state.start_at != bar.start_at
            or state.finalization is not bar.finalization
            or state.authority is not bar.lineage.authority
            for bar, state in zip(self.bars, self.bar_states)
        ):
            raise ValueError("bar_states identity must match bars")
        return self

    @model_validator(mode="after")
    def _validate_intervals(self) -> TaiwanBarSeriesRead:
        requested = normalize_taiwan_bar_interval(self.requested_interval)
        base = require_taiwan_base_bar_interval(self.base_interval)
        if requested != self.requested_interval or base != self.base_interval:
            raise ValueError("bar series intervals must already be canonical")
        expected_base = "1m" if requested in TAIWAN_INTRADAY_INTERVALS else "1d"
        if base != expected_base:
            raise ValueError("requested interval uses the wrong canonical base")
        if self.derived != (requested != base):
            raise ValueError("derived flag must match requested/base interval")
        if self.bars and any(bar.interval != requested for bar in self.bars):
            raise ValueError("outward bars must match requested_interval")
        return self


def normalize_taiwan_bar_interval(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    aliases = {"daily": "1d", "weekly": "1w", "monthly": "1mo", "1wk": "1w"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in TAIWAN_BAR_INTERVALS:
        raise ValueError(
            "Taiwan interval must be one of: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo"
        )
    return normalized


def require_taiwan_base_bar_interval(value: Any) -> str:
    normalized = normalize_taiwan_bar_interval(value)
    if normalized not in TAIWAN_BASE_BAR_INTERVALS:
        raise ValueError("TW_BASE_BAR_INTERVAL_REQUIRED")
    return normalized


__all__ = [
    "BarBucketCoverage",
    "BarBucketCoverageStatus",
    "TAIWAN_1M_HISTORY_SLO_TRADING_SESSIONS",
    "TAIWAN_BAR_INTERVALS",
    "TAIWAN_BASE_BAR_INTERVALS",
    "TAIWAN_CANONICAL_1M_MIN_RETENTION_DAYS",
    "TAIWAN_DAILY_INTERVALS",
    "TAIWAN_HISTORY_SLO_CALENDAR_DAYS",
    "TAIWAN_INTRADAY_INTERVALS",
    "TPEX_OFFICIAL_5S_COMPONENT_SOURCE",
    "TPEX_OFFICIAL_5S_PARSER_VERSION",
    "TaiwanHistoryCoverage",
    "TaiwanHistoryStatus",
    "TaiwanCurrentSessionCoverage",
    "TaiwanCurrentSessionCoverageStatus",
    "TaiwanCurrentSessionSnapshotPhase",
    "TaiwanMissingBarRange",
    "TaiwanBarSeriesIdentity",
    "TaiwanBarSeriesRead",
    "TaiwanDerivedBucketCoverage",
    "TaiwanDerivedBucketCoverageStatus",
    "TaiwanReconciliationStatus",
    "TaiwanReleaseStatus",
    "TaiwanSessionResolutionManifest",
    "normalize_taiwan_bar_interval",
    "require_taiwan_base_bar_interval",
]
