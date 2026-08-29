"""Additive application contracts for the common Market Data Gateway.

These contracts express consumer intent without provider names, SQL, URLs, or
internal function names. Read requirements and mutation/repair requirements are
separate so cache-only consumers cannot accidentally own provider work.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    AuctionType,
    AuthorityClass,
    CanonicalModel,
    DatasetHealth,
    InstrumentKey,
    Market,
    MarketSession,
    ProviderResourceHealth,
    ResolvedAuction,
    ResolvedBarSeries,
    ResolvedDepth,
    ResolvedMarketBreadth,
    ResolvedMarketIndex,
    ResolvedQuote,
    ResolvedTradingStatus,
)
from app.market_data.policies import (
    DataPurpose,
    DataRequirement,
    RealtimePolicy,
)


_REQUIRED_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _normalize_required_fields(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        return value
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("required_fields entries must be strings")
        field_path = item.strip()
        if len(field_path) > 128 or not _REQUIRED_FIELD_PATH.fullmatch(field_path):
            raise ValueError("required_fields entries must be valid field paths")
        normalized.append(field_path)
    if len(normalized) != len(set(normalized)):
        raise ValueError("required_fields entries must be unique")
    return tuple(normalized)


class InstrumentTarget(CanonicalModel):
    kind: Literal["instrument"] = "instrument"
    instrument: InstrumentKey


class DatasetTarget(CanonicalModel):
    kind: Literal["dataset"] = "dataset"
    market: Market
    dataset_id: str = Field(min_length=1, max_length=128)
    scope_key: str = Field(min_length=1, max_length=128)


RequirementTarget = Annotated[InstrumentTarget | DatasetTarget, Field(discriminator="kind")]


class SnapshotCapabilityRequest(CanonicalModel):
    kind: Literal["snapshot"] = "snapshot"
    capability_id: str = Field(min_length=1, max_length=128)
    required_fields: tuple[str, ...] = Field(default=(), max_length=32)
    depth_levels: int | None = Field(default=None, ge=1, le=20)
    auction_type: AuctionType | None = None

    @field_validator("required_fields", mode="before")
    @classmethod
    def _validate_required_fields(cls, value: object) -> object:
        return _normalize_required_fields(value)


class BarSeriesResolutionMode(str, Enum):
    """Provider-neutral bar-series selection semantics.

    Timestamp composition is explicit so a market-specific requirement cannot
    silently change whole-series selection for other markets.
    """

    SINGLE_CANDIDATE = "single_candidate"
    COMPOSE_BY_TIMESTAMP = "compose_by_timestamp"


class BarCoverageRequirement(CanonicalModel):
    """Provider-neutral minimum depth required by an explicit bar operation."""

    contract_version: str = "omi.market.bar_coverage_requirement.v1"
    minimum_bar_count: int = Field(ge=1, le=5000)


class BarCapabilityRequest(CanonicalModel):
    kind: Literal["bars"] = "bars"
    capability_id: str = Field(min_length=1, max_length=128)
    interval: str = Field(min_length=1, max_length=16)
    start_at: datetime
    end_at: datetime
    max_bars: int = Field(default=500, ge=1, le=5000)
    completed_only: bool = False
    price_basis: Literal["raw", "adjusted", "provider_default"] = "raw"
    series_resolution: BarSeriesResolutionMode = (
        BarSeriesResolutionMode.SINGLE_CANDIDATE
    )
    coverage: BarCoverageRequirement | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_aware_range(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bar request timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> BarCapabilityRequest:
        if self.start_at >= self.end_at:
            raise ValueError("bar request start_at must be before end_at")
        return self


class DatasetCapabilityRequest(CanonicalModel):
    kind: Literal["dataset"] = "dataset"
    capability_id: str = Field(min_length=1, max_length=128)
    from_date: date | None = None
    to_date: date | None = None
    minimum_coverage_ratio: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_date_range(self) -> DatasetCapabilityRequest:
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("dataset from_date cannot be after to_date")
        return self


CapabilityRequest = Annotated[
    SnapshotCapabilityRequest | BarCapabilityRequest | DatasetCapabilityRequest,
    Field(discriminator="kind"),
]


class FreshnessBasis(str, Enum):
    WALL_CLOCK = "wall_clock"
    COMPLETED_SESSION_DATE = "completed_session_date"


class FreshnessRequirement(CanonicalModel):
    max_age_seconds: int = Field(ge=1, le=2_678_400)
    basis: FreshnessBasis = FreshnessBasis.WALL_CLOCK


class QualityRequirement(CanonicalModel):
    required_fields: tuple[str, ...] = Field(default=(), max_length=32)
    minimum_authority: AuthorityClass | None = None
    allow_partial: bool = False
    require_canonical_lineage: bool = False

    @field_validator("required_fields", mode="before")
    @classmethod
    def _validate_required_fields(cls, value: object) -> object:
        return _normalize_required_fields(value)


class RequestBounds(CanonicalModel):
    max_provider_attempts: int = Field(default=0, ge=0, le=8)
    max_external_calls: int = Field(default=0, ge=0, le=20)
    max_subscriptions: int = Field(default=0, ge=0, le=8)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_candidates: int = Field(default=8, ge=1, le=8)
    max_rows: int = Field(default=500, ge=1, le=5000)


class DataRequirementV2(CanonicalModel):
    contract_version: str = "omi.market.data_requirement.v2"
    target: RequirementTarget
    request: CapabilityRequest
    purpose: DataPurpose
    realtime_policy: RealtimePolicy
    session: MarketSession
    requested_at: datetime
    freshness: FreshnessRequirement
    quality: QualityRequirement = QualityRequirement()
    bounds: RequestBounds = RequestBounds()

    @field_validator("requested_at")
    @classmethod
    def _require_aware_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_requirement(self) -> DataRequirementV2:
        if isinstance(self.target, InstrumentTarget) and isinstance(
            self.request, DatasetCapabilityRequest
        ):
            raise ValueError("dataset capability requests require a dataset target")
        if isinstance(self.target, DatasetTarget) and not isinstance(
            self.request, DatasetCapabilityRequest
        ):
            raise ValueError("dataset targets require a dataset capability request")
        if self.realtime_policy in {
            RealtimePolicy.CACHE_ONLY,
            RealtimePolicy.COMPLETED_SESSION,
        } and any(
            (
                self.bounds.max_provider_attempts,
                self.bounds.max_external_calls,
                self.bounds.max_subscriptions,
            )
        ):
            raise ValueError(
                "cache_only/completed_session read bounds must forbid external acquisition"
            )
        if (
            self.realtime_policy is RealtimePolicy.COMPLETED_SESSION
            and isinstance(self.request, BarCapabilityRequest)
            and not self.request.completed_only
        ):
            raise ValueError("completed_session bar requests require completed_only=true")
        if isinstance(self.request, BarCapabilityRequest):
            if self.request.max_bars > self.bounds.max_rows:
                raise ValueError("bar max_bars cannot exceed bounds.max_rows")
            if (
                self.request.coverage is not None
                and self.request.coverage.minimum_bar_count > self.request.max_bars
            ):
                raise ValueError("bar coverage minimum cannot exceed max_bars")
            if (
                self.request.series_resolution
                is BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP
                and self.realtime_policy is not RealtimePolicy.COMPLETED_SESSION
            ):
                raise ValueError(
                    "compose_by_timestamp currently requires completed_session policy"
                )
        return self


def adapt_v1_requirement(requirement: DataRequirement) -> DataRequirementV2:
    """Adapt the bounded v1 single-instrument vocabulary without adding powers."""

    request = SnapshotCapabilityRequest(capability_id=requirement.capability_id)
    return DataRequirementV2(
        target=InstrumentTarget(instrument=requirement.instrument),
        request=request,
        purpose=requirement.purpose,
        realtime_policy=requirement.realtime_policy,
        session=requirement.session,
        requested_at=requirement.requested_at,
        freshness=FreshnessRequirement(max_age_seconds=requirement.max_age_seconds),
        bounds=RequestBounds(
            max_provider_attempts=(
                0
                if requirement.realtime_policy
                in {RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION}
                else 2
            ),
            max_external_calls=(
                0
                if requirement.realtime_policy
                in {RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION}
                else 2
            ),
            max_subscriptions=(
                1
                if requirement.realtime_policy is RealtimePolicy.REQUIRE_LIVE
                else 0
            ),
            max_candidates=requirement.max_candidates,
        ),
    )


class RefreshCoverageScopeV1(CanonicalModel):
    """Bounded coverage intent for a mutation without provider routing details."""

    contract_version: str = "omi.market.refresh_coverage_scope.v1"
    scope_key: str = Field(min_length=1, max_length=192)
    target_count: int | None = Field(default=None, ge=0, le=100_000)
    requested_symbols: tuple[str, ...] = Field(default=(), max_length=5_000)
    minimum_observation_count: int | None = Field(default=None, ge=1, le=5000)

    @model_validator(mode="after")
    def _validate_target_count(self) -> RefreshCoverageScopeV1:
        if self.target_count is not None and self.requested_symbols:
            if self.target_count != len(self.requested_symbols):
                raise ValueError(
                    "coverage target_count must match requested_symbols when both are set"
                )
        return self


class RefreshCursorV1(CanonicalModel):
    """Opaque, dataset-owned continuation identity safe for shared dispatch."""

    contract_version: str = "omi.market.refresh_cursor.v1"
    cursor: str | None = Field(default=None, max_length=512)
    checkpoint_id: str | None = Field(default=None, max_length=192)

    @model_validator(mode="after")
    def _require_identity(self) -> RefreshCursorV1:
        if self.cursor is None and self.checkpoint_id is None:
            raise ValueError("refresh cursor requires cursor or checkpoint_id")
        return self


class RefreshRequirementV1(CanonicalModel):
    contract_version: str = "omi.market.refresh_requirement.v1"
    dataset_id: str = Field(min_length=1, max_length=128)
    target: RequirementTarget
    from_date: date | None = None
    to_date: date | None = None
    requested_at: datetime
    purpose: Literal[DataPurpose.REPAIR, DataPurpose.BACKGROUND_COLLECTOR]
    reason_code: str = Field(
        default="LEGACY_UNSPECIFIED_REFRESH_REASON", min_length=1, max_length=64
    )
    coverage: RefreshCoverageScopeV1 | None = None
    continuation: RefreshCursorV1 | None = None
    max_provider_attempts: int = Field(ge=1, le=8)
    max_external_calls: int = Field(ge=1, le=20)
    timeout_seconds: int = Field(ge=1, le=120)
    max_symbols: int = Field(ge=1, le=5_000)
    max_range_days: int = Field(ge=1, le=3650)
    postcondition: str = Field(min_length=1, max_length=256)

    @field_validator("requested_at")
    @classmethod
    def _require_aware_refresh_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("refresh requested_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_refresh_range(self) -> RefreshRequirementV1:
        if self.from_date and self.to_date:
            if self.from_date > self.to_date:
                raise ValueError("refresh from_date cannot be after to_date")
            if (self.to_date - self.from_date).days + 1 > self.max_range_days:
                raise ValueError("refresh range exceeds max_range_days")
        if self.coverage is not None:
            if (
                self.coverage.target_count is not None
                and self.coverage.target_count > self.max_symbols
            ):
                raise ValueError("coverage target_count exceeds max_symbols")
            if len(self.coverage.requested_symbols) > self.max_symbols:
                raise ValueError("coverage requested_symbols exceeds max_symbols")
        return self


class AcquisitionStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class AcquisitionResourceAttempt(CanonicalModel):
    provider: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=128)


class AcquisitionSummary(CanonicalModel):
    contract_version: str = "omi.market.acquisition_summary.v1"
    attempted: bool = False
    status: AcquisitionStatus = AcquisitionStatus.NOT_ATTEMPTED
    providers_attempted: tuple[str, ...] = ()
    resource_attempts: tuple[AcquisitionResourceAttempt, ...] = Field(
        default=(), max_length=8
    )
    external_calls: int = Field(default=0, ge=0, le=20)
    subscriptions_created: int = Field(default=0, ge=0, le=8)
    elapsed_ms: int | None = Field(default=None, ge=0)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_attempt(self) -> AcquisitionSummary:
        if not self.attempted:
            if self.status is not AcquisitionStatus.NOT_ATTEMPTED:
                raise ValueError("non-attempted acquisition must use not_attempted status")
            if (
                self.providers_attempted
                or self.resource_attempts
                or self.external_calls
                or self.subscriptions_created
            ):
                raise ValueError("non-attempted acquisition cannot report provider work")
        elif self.status is AcquisitionStatus.NOT_ATTEMPTED:
            raise ValueError("attempted acquisition requires an attempted status")
        resource_keys = [
            (item.provider, item.resource_id) for item in self.resource_attempts
        ]
        if len(resource_keys) != len(set(resource_keys)):
            raise ValueError("acquisition resource attempts must be unique")
        attempt_providers = tuple(
            dict.fromkeys(item.provider for item in self.resource_attempts)
        )
        if self.resource_attempts and attempt_providers != self.providers_attempted:
            raise ValueError(
                "providers_attempted must match ordered resource-attempt providers"
            )
        return self


class RawFetchReceiptV1(CanonicalModel):
    """Bounded provider receipt handed to the transaction owner unchanged."""

    contract_version: str = "omi.market.raw_fetch_receipt.v1"
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    fetched_at: datetime
    method: str = Field(min_length=1, max_length=20)
    url: str | None = Field(default=None, max_length=2048)
    status_code: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=120)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_text: str | None = Field(default=None, max_length=20_000_000)
    parser_version: str = Field(min_length=1, max_length=64)
    error_message: str | None = Field(default=None, max_length=2048)

    @field_validator("fetched_at")
    @classmethod
    def _require_aware_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt fetched_at must be timezone-aware")
        return value

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, value: str) -> str:
        return value.strip().upper()


class PersistenceSummary(CanonicalModel):
    contract_version: str = "omi.market.persistence_summary.v1"
    attempted: bool = False
    committed: bool = False
    receipts_written: int = Field(default=0, ge=0, le=20)
    observations_written: int = Field(default=0, ge=0, le=5000)
    observations_inserted: int = Field(default=0, ge=0, le=5000)
    observations_updated: int = Field(default=0, ge=0, le=5000)
    observations_unchanged: int = Field(default=0, ge=0, le=5000)
    raw_result_ids: tuple[int, ...] = Field(default=(), max_length=20)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_persistence(self) -> PersistenceSummary:
        has_work = any(
            (
                self.receipts_written,
                self.observations_written,
                self.observations_inserted,
                self.observations_updated,
                self.observations_unchanged,
                len(self.raw_result_ids),
            )
        )
        if not self.attempted and (self.committed or has_work):
            raise ValueError("non-attempted persistence cannot report committed work")
        if self.committed and not self.attempted:
            raise ValueError("committed persistence must be attempted")
        if len(set(self.raw_result_ids)) != len(self.raw_result_ids):
            raise ValueError("raw_result_ids must be unique")
        if self.observations_inserted + self.observations_updated > self.observations_written:
            raise ValueError(
                "inserted and updated observation counts cannot exceed observations_written"
            )
        return self


ResolvedPayload = (
    ResolvedQuote
    | ResolvedDepth
    | ResolvedAuction
    | ResolvedBarSeries
    | ResolvedMarketBreadth
    | ResolvedMarketIndex
    | ResolvedTradingStatus
)


class MarketDataResultV1(CanonicalModel):
    contract_version: str = "omi.market.data_result.v1"
    requirement: DataRequirementV2
    result_kind: Literal[
        "quote",
        "depth",
        "auction",
        "bar_series",
        "market_breadth",
        "market_index",
        "trading_status",
    ]
    resolved: ResolvedPayload
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    dataset_health: DatasetHealth | None = None
    acquisition: AcquisitionSummary = AcquisitionSummary()
    persistence: PersistenceSummary = PersistenceSummary()
    candidate_rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_result_kind(self) -> MarketDataResultV1:
        expected_type = {
            "quote": ResolvedQuote,
            "depth": ResolvedDepth,
            "auction": ResolvedAuction,
            "bar_series": ResolvedBarSeries,
            "market_breadth": ResolvedMarketBreadth,
            "market_index": ResolvedMarketIndex,
            "trading_status": ResolvedTradingStatus,
        }[self.result_kind]
        if not isinstance(self.resolved, expected_type):
            raise ValueError("result_kind does not match resolved payload")
        return self


__all__ = [
    "AcquisitionStatus",
    "AcquisitionSummary",
    "AcquisitionResourceAttempt",
    "BarCapabilityRequest",
    "BarCoverageRequirement",
    "BarSeriesResolutionMode",
    "CapabilityRequest",
    "DataRequirementV2",
    "DatasetCapabilityRequest",
    "DatasetTarget",
    "FreshnessBasis",
    "FreshnessRequirement",
    "InstrumentTarget",
    "MarketDataResultV1",
    "PersistenceSummary",
    "QualityRequirement",
    "RawFetchReceiptV1",
    "RefreshCoverageScopeV1",
    "RefreshCursorV1",
    "RefreshRequirementV1",
    "RequestBounds",
    "RequirementTarget",
    "SnapshotCapabilityRequest",
    "adapt_v1_requirement",
]
