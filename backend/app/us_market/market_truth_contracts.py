"""Typed US Market Truth contracts.

This module is deliberately pure.  It owns no database session, provider IO,
resolver selection, clock, HTTP projection, or persistence.  Cross-capability
composition lives in ``market_truth.py`` and must provide immutable evidence
versions plus referentially complete outward snapshots.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    CanonicalModel,
    CapabilityExpectation,
    EvidenceFreshness,
    InstrumentKey,
    MarketSession,
    PriceUnit,
    ResolvedEvidenceHealth,
)
from app.us_market.temporal_expectedness import USMarketPhase, USTradeRecency
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


USPriceBasis = Literal["raw", "adjusted", "provider_default"]


class USMarketTruthAvailability(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    VALID_EMPTY = "valid_empty"


class USMarketTruthApplicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class USEvidenceRelease(str, Enum):
    PENDING = "pending"
    RELEASED = "released"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class USCloseEvidenceKind(str, Enum):
    COMPLETED_DAILY = "completed_daily"
    OFFICIAL_CLOSING_EVENT = "official_closing_event"
    FINALIZED_REGULAR_INTERVAL_CLOSE = "finalized_regular_interval_close"
    PROVIDER_PREVIOUS_CLOSE_HINT = "provider_previous_close_hint"
    UNVERIFIED_CLOSE_BOUNDARY_BAR = "unverified_close_boundary_bar"


class USOfficialCloseProof(str, Enum):
    NONE = "none"
    EXCHANGE_MARKER = "exchange_marker"
    PROVIDER_SALE_CONDITION = "provider_sale_condition"
    INDEX_OFFICIAL_VALUE = "index_official_value"


class USObservationKind(str, Enum):
    QUOTE = "quote"
    BAR = "bar"
    CLOSE = "close"


class USComparisonPurpose(str, Enum):
    REGULAR_SESSION_CHANGE = "regular_session_change"
    EXTENDED_SESSION_CHANGE = "extended_session_change"
    HEADLINE_CHANGE = "headline_change"
    RESEARCH_CHANGE = "research_change"


class USChangeCalculationStatus(str, Enum):
    CALCULATED = "calculated"
    LIMITED = "limited"
    MISSING = "missing"
    INCOMPATIBLE_EVIDENCE = "incompatible_evidence"
    UNAVAILABLE = "unavailable"


class USCloseReconciliationState(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    DIVERGED = "diverged"
    MISMATCHED = "mismatched"
    NOT_APPLICABLE = "not_applicable"


class USCloseComparisonSemantics(str, Enum):
    OFFICIAL_VS_OFFICIAL = "official_vs_official"
    OFFICIAL_VS_REGULAR_INTERVAL = "official_vs_regular_interval"
    OFFICIAL_VS_PROVIDER_HINT = "official_vs_provider_hint"
    INTERVAL_VS_PROVIDER_HINT = "interval_vs_provider_hint"
    SAME_SEMANTICS = "same_semantics"


class USCloseEvidence(CanonicalModel):
    """One immutable version of close-related evidence.

    ``evidence_key`` is the stable logical key. ``evidence_id`` identifies the
    immutable canonical version and must change when the underlying observation
    is corrected or superseded. ``semantic_fingerprint`` protects truth
    revisions even if an upstream system accidentally reuses an ID.
    """

    contract_version: str = "omi.market.us_close_evidence.v1"
    evidence_key: str = Field(min_length=1, max_length=256)
    evidence_id: str = Field(min_length=1, max_length=256)
    observation_id: str = Field(min_length=1, max_length=256)
    semantic_fingerprint: str = Field(min_length=16, max_length=128)
    instrument: InstrumentKey
    trade_date: date
    price: Decimal = Field(gt=0)
    price_unit: PriceUnit
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price_basis: USPriceBasis
    evidence_kind: USCloseEvidenceKind
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    authority: AuthorityClass
    session: MarketSession
    event_at: datetime
    fetched_at: datetime
    interval_start_at: datetime | None = None
    interval_end_at: datetime | None = None
    official_close_proof: USOfficialCloseProof = USOfficialCloseProof.NONE
    proof_source: str | None = Field(default=None, min_length=1, max_length=128)
    proof_semantics: str | None = Field(default=None, min_length=1, max_length=128)
    applicability: USMarketTruthApplicability = USMarketTruthApplicability.APPLICABLE
    availability: USMarketTruthAvailability = USMarketTruthAvailability.AVAILABLE
    finalization: BarFinalization
    release: USEvidenceRelease
    freshness: EvidenceFreshness
    expectedness: CapabilityExpectation
    display_usable: bool
    research_usable: bool
    limitations: tuple[str, ...] = ()

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "event_at", "fetched_at", "interval_start_at", "interval_end_at"
    )
    @classmethod
    def _require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("US close evidence timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_close_evidence(self) -> "USCloseEvidence":
        has_start = self.interval_start_at is not None
        has_end = self.interval_end_at is not None
        if has_start != has_end:
            raise ValueError("close interval start/end must be provided together")
        if has_start and self.interval_start_at >= self.interval_end_at:
            raise ValueError("close interval start must be before end")

        if self.evidence_kind is USCloseEvidenceKind.OFFICIAL_CLOSING_EVENT:
            if self.official_close_proof is USOfficialCloseProof.NONE:
                raise ValueError("official closing event requires explicit proof")
            if self.proof_source is None or self.proof_semantics is None:
                raise ValueError("official closing event requires proof source and semantics")
            if self.release is not USEvidenceRelease.RELEASED:
                raise ValueError("official closing event must be released")
            if self.finalization is BarFinalization.PROVISIONAL:
                raise ValueError("official closing event cannot be provisional")
        elif (
            self.official_close_proof is not USOfficialCloseProof.NONE
            or self.proof_source is not None
            or self.proof_semantics is not None
        ):
            raise ValueError("only official closing events may carry official proof")

        if self.evidence_kind is USCloseEvidenceKind.UNVERIFIED_CLOSE_BOUNDARY_BAR:
            if self.official_close_proof is not USOfficialCloseProof.NONE:
                raise ValueError("unverified close boundary cannot carry official proof")
            if self.research_usable:
                raise ValueError("unverified close boundary is not research usable")

        if self.evidence_kind is USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE:
            if not has_start or self.session is not MarketSession.CONTINUOUS:
                raise ValueError("regular interval close requires a continuous interval")
            if self.finalization is BarFinalization.PROVISIONAL:
                raise ValueError("regular interval close must be finalized")

        if self.evidence_kind is USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT:
            if self.research_usable:
                raise ValueError("provider previous-close hint is never research usable")
            if self.authority is AuthorityClass.EXCHANGE:
                raise ValueError("provider previous-close hint cannot claim exchange authority")

        if self.availability is not USMarketTruthAvailability.AVAILABLE:
            raise ValueError("materialized close evidence must be available")
        if self.price_unit is PriceUnit.CURRENCY and self.currency is None:
            raise ValueError("currency price evidence requires currency")
        if self.price_unit is PriceUnit.INDEX_POINT and self.currency is not None:
            raise ValueError("index-point evidence cannot claim currency")
        return self


class USObservation(CanonicalModel):
    contract_version: str = "omi.market.us_truth_observation.v1"
    observation_id: str = Field(min_length=1, max_length=256)
    kind: USObservationKind
    instrument: InstrumentKey
    trade_date: date
    price: Decimal = Field(gt=0)
    price_unit: PriceUnit
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price_basis: USPriceBasis
    session: MarketSession
    event_at: datetime
    fetched_at: datetime
    selected_provider: str = Field(min_length=1, max_length=64)
    selected_source: str = Field(min_length=1, max_length=128)
    selection_reason: str = Field(min_length=1, max_length=256)
    fallback_used: bool = False
    availability: USMarketTruthAvailability
    freshness: EvidenceFreshness
    provider_snapshot_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN
    trade_recency: USTradeRecency = USTradeRecency.UNKNOWN
    current_session_expected: bool = False
    current_session_satisfied: bool = False
    expectedness: CapabilityExpectation
    display_usable: bool
    research_usable: bool
    limitations: tuple[str, ...] = ()

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("event_at", "fetched_at")
    @classmethod
    def _require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("US observation timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_price_unit(self) -> "USObservation":
        if self.price_unit is PriceUnit.CURRENCY and self.currency is None:
            raise ValueError("currency observation requires currency")
        if self.price_unit is PriceUnit.INDEX_POINT and self.currency is not None:
            raise ValueError("index-point observation cannot claim currency")
        if self.current_session_satisfied and not self.current_session_expected:
            raise ValueError("satisfied current-session observation must be expected")
        if (
            self.freshness in {EvidenceFreshness.STALE, EvidenceFreshness.MISSING}
            and self.research_usable
        ):
            raise ValueError("stale or missing observation cannot be research usable")
        return self


class USCloseRoles(CanonicalModel):
    latest_completed_id: str | None = Field(default=None, max_length=256)
    prior_completed_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _require_distinct_roles(self) -> "USCloseRoles":
        if (
            self.latest_completed_id is not None
            and self.latest_completed_id == self.prior_completed_id
        ):
            raise ValueError("latest and prior completed close must be distinct")
        return self


class USComparisonReference(CanonicalModel):
    contract_version: str = "omi.market.us_comparison_reference.v1"
    reference_id: str = Field(min_length=1, max_length=256)
    evidence_id: str | None = Field(default=None, max_length=256)
    purpose: USComparisonPurpose
    instrument: InstrumentKey
    reference_trade_date: date | None = None
    price: Decimal | None = Field(default=None, gt=0)
    price_unit: PriceUnit | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price_basis: USPriceBasis | None = None
    calculation_eligible: bool
    display_usable: bool
    research_usable: bool
    reason_code: str = Field(min_length=1, max_length=128)
    limitations: tuple[str, ...] = ()

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_reference(self) -> "USComparisonReference":
        materialized = (
            self.evidence_id,
            self.reference_trade_date,
            self.price,
            self.price_unit,
            self.price_basis,
        )
        if self.calculation_eligible and any(value is None for value in materialized):
            raise ValueError("eligible comparison reference must be materialized")
        if self.evidence_id is None and any(
            value is not None for value in (*materialized[1:], self.currency)
        ):
            raise ValueError("unresolved reference cannot expose partial evidence")
        if self.price_unit is PriceUnit.CURRENCY and self.currency is None:
            raise ValueError("currency comparison reference requires currency")
        if self.price_unit is PriceUnit.INDEX_POINT and self.currency is not None:
            raise ValueError("index-point comparison reference cannot claim currency")
        if not self.calculation_eligible and self.research_usable:
            raise ValueError("ineligible reference cannot be research usable")
        return self


class USChangeMetric(CanonicalModel):
    contract_version: str = "omi.market.us_change_metric.v1"
    metric_id: str = Field(min_length=1, max_length=256)
    purpose: USComparisonPurpose
    observation_id: str | None = Field(default=None, max_length=256)
    reference_id: str | None = Field(default=None, max_length=256)
    absolute_change: Decimal | None = None
    percent_change: Decimal | None = None
    calculation_status: USChangeCalculationStatus
    reason_code: str = Field(min_length=1, max_length=128)
    display_usable: bool
    research_usable: bool

    @model_validator(mode="after")
    def _validate_metric(self) -> "USChangeMetric":
        calculated = self.calculation_status in {
            USChangeCalculationStatus.CALCULATED,
            USChangeCalculationStatus.LIMITED,
        }
        identity = (self.observation_id, self.reference_id)
        values = (self.absolute_change, self.percent_change)
        if calculated and (any(value is None for value in identity + values)):
            raise ValueError("calculated change metric requires identities and values")
        if not calculated and any(value is not None for value in values):
            raise ValueError("uncalculated change metric cannot expose numeric values")
        if self.calculation_status is USChangeCalculationStatus.LIMITED:
            if self.research_usable:
                raise ValueError("limited metric cannot be research usable")
        if not calculated and (self.display_usable or self.research_usable):
            raise ValueError("uncalculated metric cannot be usable")
        return self


class USCloseReconciliation(CanonicalModel):
    contract_version: str = "omi.market.us_close_reconciliation.v1"
    trade_date: date
    primary_evidence_id: str | None = Field(default=None, max_length=256)
    secondary_evidence_ids: tuple[str, ...] = ()
    state: USCloseReconciliationState
    comparison_semantics: USCloseComparisonSemantics | None = None
    absolute_difference: Decimal | None = Field(default=None, ge=0)
    relative_difference_bps: Decimal | None = Field(default=None, ge=0)
    tick_difference: Decimal | None = Field(default=None, ge=0)
    tolerance_policy_id: str | None = Field(default=None, max_length=128)
    tolerance_basis: Literal["absolute", "basis_points", "ticks", "combined"] | None = None
    within_tolerance: bool | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_reconciliation(self) -> "USCloseReconciliation":
        compared = self.state in {
            USCloseReconciliationState.MATCHED,
            USCloseReconciliationState.DIVERGED,
            USCloseReconciliationState.MISMATCHED,
        }
        required = (
            self.primary_evidence_id,
            self.comparison_semantics,
            self.tolerance_policy_id,
            self.tolerance_basis,
            self.within_tolerance,
            self.absolute_difference,
            self.relative_difference_bps,
        )
        if compared:
            if not self.secondary_evidence_ids or any(value is None for value in required):
                raise ValueError("compared closes require evidence, difference, and policy")
            if self.state is USCloseReconciliationState.MATCHED and not self.within_tolerance:
                raise ValueError("matched reconciliation must be within tolerance")
            if self.state is USCloseReconciliationState.MISMATCHED and self.within_tolerance:
                raise ValueError("mismatched reconciliation cannot be within tolerance")
            if self.state is USCloseReconciliationState.DIVERGED and self.within_tolerance:
                raise ValueError("diverged reconciliation cannot be within tolerance")
        elif any(
            value is not None
            for value in (
                self.absolute_difference,
                self.relative_difference_bps,
                self.tick_difference,
                self.comparison_semantics,
                self.tolerance_policy_id,
                self.tolerance_basis,
                self.within_tolerance,
            )
        ):
            raise ValueError("pending/not-applicable reconciliation has no comparison")
        return self


class USComponentRevisions(CanonicalModel):
    quote_revision: str | None = None
    intraday_revision: str | None = None
    close_revision: str | None = None
    daily_revision: str | None = None
    calendar_revision: str


class USMarketTruthComponentStatus(CanonicalModel):
    availability: USMarketTruthAvailability
    reason_code: str = Field(min_length=1, max_length=128)
    resolved_health: ResolvedEvidenceHealth
    limitations: tuple[str, ...] = ()


class USMarketTruthHealth(CanonicalModel):
    quote: USMarketTruthComponentStatus
    intraday: USMarketTruthComponentStatus
    daily: USMarketTruthComponentStatus


class USIntradaySeriesPoint(CanonicalModel):
    contract_version: str = "omi.market.us_intraday_series_point.v1"
    observation_id: str = Field(min_length=1, max_length=256)
    start_at: datetime
    end_at: datetime
    open_price: Decimal = Field(gt=0)
    high_price: Decimal = Field(gt=0)
    low_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    volume: Decimal | None = Field(default=None, ge=0)
    volume_status: Literal["observed", "missing", "not_applicable"] | None = None
    price_unit: PriceUnit
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price_basis: USPriceBasis
    session: MarketSession
    finalization: BarFinalization
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("intraday series timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_point(self) -> "USIntradaySeriesPoint":
        if self.start_at >= self.end_at:
            raise ValueError("intraday point start must be before end")
        if self.high_price < max(
            self.open_price, self.low_price, self.close_price
        ):
            raise ValueError("intraday point high is inconsistent")
        if self.low_price > min(
            self.open_price, self.high_price, self.close_price
        ):
            raise ValueError("intraday point low is inconsistent")
        if self.price_unit is PriceUnit.CURRENCY and self.currency is None:
            raise ValueError("currency intraday point requires currency")
        if self.price_unit is PriceUnit.INDEX_POINT and self.currency is not None:
            raise ValueError("index-point intraday point cannot claim currency")
        return self


class USIntradaySeriesProjection(CanonicalModel):
    contract_version: str = "omi.market.us_intraday_series_projection.v1"
    evaluated_at: datetime
    truth_revision: str = Field(min_length=16, max_length=128)
    intraday_revision: str = Field(min_length=16, max_length=128)
    instrument: InstrumentKey
    trade_date: date | None = None
    expected_trade_date: date | None = None
    latest_available_trade_date: date | None = None
    current_session_expected: bool = False
    current_session_satisfied: bool = False
    selection_reason: str = Field(min_length=1, max_length=128)
    interval: str = Field(min_length=1, max_length=16)
    requested_scope: Literal["regular", "extended", "all"]
    regular_points: tuple[USIntradaySeriesPoint, ...] = ()
    pre_market_points: tuple[USIntradaySeriesPoint, ...] = ()
    after_hours_points: tuple[USIntradaySeriesPoint, ...] = ()
    close_boundary_events: tuple[USIntradaySeriesPoint, ...] = ()
    scheduled_interval_count: int = Field(ge=0)
    observed_interval_count: int = Field(ge=0)
    missing_interval_count: int = Field(ge=0)
    explained_gap_count: int = Field(ge=0)
    continuity: Literal["complete", "partial", "missing", "not_applicable"]
    limitations: tuple[str, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def _require_aware_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_series_partition(self) -> "USIntradaySeriesProjection":
        all_points = (
            *self.regular_points,
            *self.pre_market_points,
            *self.after_hours_points,
            *self.close_boundary_events,
        )
        if self.current_session_expected:
            if self.expected_trade_date is None:
                raise ValueError("current-session series requires expected trade date")
            if self.current_session_satisfied:
                if self.trade_date != self.expected_trade_date:
                    raise ValueError("satisfied current-session series must select expected date")
            elif self.trade_date is not None or all_points:
                raise ValueError("missing current-session series cannot expose historical points")
        if self.trade_date is not None and any(
            point.start_at.astimezone(US_MARKET_TIMEZONE).date() != self.trade_date
            for point in all_points
        ):
            raise ValueError("intraday series points must match selected trade date")
        if any(
            point.session is not MarketSession.CONTINUOUS
            for point in self.regular_points
        ):
            raise ValueError("regular series may contain only continuous points")
        if any(
            point.session is not MarketSession.CLOSING_AUCTION
            for point in self.close_boundary_events
        ):
            raise ValueError("close boundary events require closing-auction time bucket")
        if self.observed_interval_count != len(self.regular_points):
            raise ValueError("observed interval count must match regular points")
        if (
            self.observed_interval_count + self.missing_interval_count
            != self.scheduled_interval_count
        ):
            raise ValueError("intraday interval accounting must balance")
        if self.explained_gap_count > self.missing_interval_count:
            raise ValueError("explained gaps cannot exceed missing intervals")
        return self


class USMarketTruthSnapshot(CanonicalModel):
    contract_version: str = "omi.market.us_truth_snapshot.v1"
    evaluated_at: datetime
    evaluation_id: str = Field(min_length=1, max_length=128)
    evidence_revision: str = Field(min_length=16, max_length=128)
    truth_revision: str = Field(min_length=16, max_length=128)
    component_revisions: USComponentRevisions
    instrument: InstrumentKey
    market_phase: USMarketPhase
    expectation: CapabilityExpectation
    latest_observation: USObservation | None = None
    current_observation: USObservation | None = None
    headline_observation: USObservation | None = None
    close_evidence: tuple[USCloseEvidence, ...] = ()
    close_roles: USCloseRoles
    comparison_references: tuple[USComparisonReference, ...] = ()
    change_metrics: tuple[USChangeMetric, ...] = ()
    reconciliation: USCloseReconciliation | None = None
    health: USMarketTruthHealth
    limitations: tuple[str, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def _require_aware_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_snapshot_references(self) -> "USMarketTruthSnapshot":
        evidence_by_id = {item.evidence_id: item for item in self.close_evidence}
        if len(evidence_by_id) != len(self.close_evidence):
            raise ValueError("close evidence ids must be unique")

        role_ids = (
            self.close_roles.latest_completed_id,
            self.close_roles.prior_completed_id,
        )
        if any(item is not None and item not in evidence_by_id for item in role_ids):
            raise ValueError("close role contains dangling evidence id")

        reference_by_id = {
            item.reference_id: item for item in self.comparison_references
        }
        if len(reference_by_id) != len(self.comparison_references):
            raise ValueError("comparison reference ids must be unique")
        for reference in self.comparison_references:
            if reference.evidence_id is None:
                continue
            evidence = evidence_by_id.get(reference.evidence_id)
            if evidence is None:
                raise ValueError("comparison reference contains dangling evidence id")
            if reference.instrument != evidence.instrument:
                raise ValueError("comparison reference instrument mismatch")
            if (
                reference.price_unit != evidence.price_unit
                or reference.currency != evidence.currency
                or reference.price_basis != evidence.price_basis
                or reference.price != evidence.price
            ):
                raise ValueError("comparison reference price semantics mismatch")

        observations = tuple(
            item
            for item in (
                self.latest_observation,
                self.current_observation,
                self.headline_observation,
            )
            if item is not None
        )
        observation_by_id = {item.observation_id: item for item in observations}
        if self.current_observation is not None and (
            self.current_observation.availability
            is not USMarketTruthAvailability.AVAILABLE
            or not self.current_observation.current_session_satisfied
        ):
            raise ValueError("current observation must belong to the current session")

        metric_ids: set[str] = set()
        for metric in self.change_metrics:
            if metric.metric_id in metric_ids:
                raise ValueError("change metric ids must be unique")
            metric_ids.add(metric.metric_id)
            if metric.observation_id is None or metric.reference_id is None:
                continue
            observation = observation_by_id.get(metric.observation_id)
            reference = reference_by_id.get(metric.reference_id)
            if observation is None or reference is None:
                raise ValueError("change metric contains dangling identity")
            if observation.instrument != reference.instrument:
                raise ValueError("change metric instrument mismatch")
            if (
                observation.price_unit != reference.price_unit
                or observation.currency != reference.currency
                or observation.price_basis != reference.price_basis
            ):
                raise ValueError("change metric evidence is not price compatible")

        if self.reconciliation is not None:
            reconciliation_ids = (
                (self.reconciliation.primary_evidence_id,)
                + self.reconciliation.secondary_evidence_ids
            )
            if any(
                item is not None and item not in evidence_by_id
                for item in reconciliation_ids
            ):
                raise ValueError("reconciliation contains dangling evidence id")
        return self


def semantic_fingerprint(value: Any) -> str:
    """Return a deterministic fingerprint for typed semantic content."""

    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def build_evidence_revision(evidence: tuple[USCloseEvidence, ...]) -> str:
    """Hash semantic versions, not only logical evidence keys."""

    ordered = sorted(
        (item.model_dump(mode="json") for item in evidence),
        key=lambda item: (item["evidence_key"], item["evidence_id"]),
    )
    return semantic_fingerprint(ordered)


def build_truth_revision(
    *,
    contract_version: str,
    evidence_revision: str,
    market_phase: USMarketPhase,
    component_revisions: USComponentRevisions,
    selected_observation_ids: tuple[str | None, ...],
    references: tuple[USComparisonReference, ...],
    metrics: tuple[USChangeMetric, ...],
    reconciliation: USCloseReconciliation | None,
) -> str:
    """Hash every truth-affecting classification while excluding request time."""

    return semantic_fingerprint(
        {
            "contract_version": contract_version,
            "evidence_revision": evidence_revision,
            "market_phase": market_phase,
            "component_revisions": component_revisions.model_dump(mode="json"),
            "selected_observation_ids": selected_observation_ids,
            "references": [item.model_dump(mode="json") for item in references],
            "metrics": [item.model_dump(mode="json") for item in metrics],
            "reconciliation": (
                reconciliation.model_dump(mode="json")
                if reconciliation is not None
                else None
            ),
        }
    )


__all__ = [
    "USChangeCalculationStatus",
    "USChangeMetric",
    "USCloseEvidence",
    "USCloseEvidenceKind",
    "USCloseComparisonSemantics",
    "USCloseReconciliation",
    "USCloseReconciliationState",
    "USCloseRoles",
    "USComparisonPurpose",
    "USComparisonReference",
    "USComponentRevisions",
    "USEvidenceRelease",
    "USMarketTruthApplicability",
    "USMarketTruthAvailability",
    "USMarketTruthComponentStatus",
    "USMarketTruthHealth",
    "USMarketTruthSnapshot",
    "USIntradaySeriesPoint",
    "USIntradaySeriesProjection",
    "USObservation",
    "USObservationKind",
    "USOfficialCloseProof",
    "USPriceBasis",
    "build_evidence_revision",
    "build_truth_revision",
    "semantic_fingerprint",
]
