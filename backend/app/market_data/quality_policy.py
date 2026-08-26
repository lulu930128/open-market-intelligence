"""Pure candidate-quality policy for provider-neutral market observations.

The evaluator owns eligibility and usability reasons only. It performs no
provider selection, market-specific session interpretation, I/O, persistence,
or transaction work. Gateway/Resolver integration is deliberately separate so
the policy can be validated before it changes a production selection path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    CanonicalModel,
    EvidenceFreshness,
    ObservationState,
    SourceLineage,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import RealtimePolicy


FUTURE_TIMESTAMP_TOLERANCE = timedelta(minutes=5)

_AUTHORITY_RANK: dict[AuthorityClass, int] = {
    AuthorityClass.CACHE: 0,
    AuthorityClass.DERIVED: 1,
    AuthorityClass.VENDOR: 2,
    AuthorityClass.BROKER: 3,
    AuthorityClass.EXCHANGE: 4,
}

_CANONICAL_LINEAGE_FIELDS = (
    "raw_contract_version",
    "event_at",
    "received_at",
    "fetched_at",
    "observation_id",
    "raw_receipt_id",
    "content_hash",
)


class QualityReasonCode(str, Enum):
    ELIGIBLE = "QUALITY_ELIGIBLE"
    OBSERVATION_MISSING = "QUALITY_OBSERVATION_MISSING"
    REQUIRED_FIELDS_MISSING = "QUALITY_REQUIRED_FIELDS_MISSING"
    AUTHORITY_BELOW_MINIMUM = "QUALITY_AUTHORITY_BELOW_MINIMUM"
    PARTIAL_NOT_ALLOWED = "QUALITY_PARTIAL_NOT_ALLOWED"
    PARTIAL_ALLOWED = "QUALITY_PARTIAL_ALLOWED"
    CANONICAL_LINEAGE_INCOMPLETE = "QUALITY_CANONICAL_LINEAGE_INCOMPLETE"
    FUTURE_TIMESTAMP = "QUALITY_FUTURE_TIMESTAMP"
    FRESHNESS_UNUSABLE = "QUALITY_FRESHNESS_UNUSABLE"
    LIVE_REQUIRED = "QUALITY_LIVE_REQUIRED"
    STALE_EVIDENCE = "QUALITY_STALE_EVIDENCE"
    INDICATIVE_EVIDENCE = "QUALITY_INDICATIVE_EVIDENCE"


class QualityEvaluation(CanonicalModel):
    contract_version: str = "omi.market.quality_evaluation.v1"
    eligible: bool
    reason_code: QualityReasonCode
    reason_codes: tuple[QualityReasonCode, ...] = Field(min_length=1, max_length=16)
    missing_fields: tuple[str, ...] = Field(default=(), max_length=32)
    missing_lineage_fields: tuple[str, ...] = Field(default=(), max_length=16)
    facts_usable: bool = False
    research_usable: bool = False
    limitations: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _validate_evaluation(self) -> QualityEvaluation:
        if self.reason_code is not self.reason_codes[0]:
            raise ValueError("reason_code must equal the first reason_codes entry")
        if not self.eligible and self.research_usable:
            raise ValueError("ineligible quality evidence cannot be research usable")
        if self.research_usable and not self.facts_usable:
            raise ValueError("research-usable evidence must also be facts usable")
        return self


def authority_satisfies(
    actual: AuthorityClass,
    minimum: AuthorityClass | None,
) -> bool:
    """Return whether ``actual`` satisfies the explicit shared authority floor."""

    if minimum is None:
        return True
    return _AUTHORITY_RANK[actual] >= _AUTHORITY_RANK[minimum]


def required_fields_for(requirement: DataRequirementV2) -> tuple[str, ...]:
    """Return the ordered union of capability and quality field requirements."""

    requested: tuple[str, ...] = ()
    if isinstance(requirement.request, SnapshotCapabilityRequest):
        requested = requirement.request.required_fields
    return tuple(dict.fromkeys((*requested, *requirement.quality.required_fields)))


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (tuple, list, dict, set, frozenset)):
        return not value
    return False


def _field_value(observation: CanonicalModel, field_path: str) -> tuple[bool, Any]:
    current: Any = observation
    for segment in field_path.split("."):
        if isinstance(current, CanonicalModel):
            if segment not in type(current).model_fields:
                return False, None
            current = getattr(current, segment)
        elif isinstance(current, dict):
            if segment not in current:
                return False, None
            current = current[segment]
        else:
            return False, None
    return True, current


def _missing_required_fields(
    observation: CanonicalModel,
    requirement: DataRequirementV2,
) -> tuple[str, ...]:
    missing: list[str] = []
    for field_path in required_fields_for(requirement):
        exists, value = _field_value(observation, field_path)
        if not exists or _is_missing_value(value):
            missing.append(field_path)
    return tuple(missing)


def _missing_lineage_fields(lineage: SourceLineage) -> tuple[str, ...]:
    missing: list[str] = []
    for field_name in _CANONICAL_LINEAGE_FIELDS:
        value = getattr(lineage, field_name)
        if _is_missing_value(value):
            missing.append(field_name)
    return tuple(missing)


def _lineage_has_future_timestamp(lineage: SourceLineage, *, now: datetime) -> bool:
    threshold = now + FUTURE_TIMESTAMP_TOLERANCE
    return any(
        timestamp is not None and timestamp > threshold
        for timestamp in (lineage.event_at, lineage.received_at, lineage.fetched_at)
    )


def _observed_at(lineage: SourceLineage) -> datetime | None:
    return lineage.event_at or lineage.received_at or lineage.fetched_at


def evaluate_candidate_quality(
    observation: CanonicalModel,
    *,
    requirement: DataRequirementV2,
    freshness: EvidenceFreshness | None = None,
    now: datetime | None = None,
) -> QualityEvaluation:
    """Evaluate shared eligibility without choosing or ranking a provider."""

    evaluation_time = now or requirement.requested_at
    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise ValueError("quality evaluation time must be timezone-aware")

    reasons: list[QualityReasonCode] = []
    limitations: list[str] = []
    hard_rejection = False
    facts_usable = True
    research_usable = True

    state = getattr(observation, "state", ObservationState.AVAILABLE)
    if state is ObservationState.MISSING:
        reasons.append(QualityReasonCode.OBSERVATION_MISSING)
        limitations.append("The candidate observation is missing.")
        hard_rejection = True

    missing_fields = _missing_required_fields(observation, requirement)
    if missing_fields:
        reasons.append(QualityReasonCode.REQUIRED_FIELDS_MISSING)
        limitations.append("The candidate is missing fields required by the request.")
        hard_rejection = True

    lineage = getattr(observation, "lineage", None)
    missing_lineage_fields: tuple[str, ...] = ()
    if not isinstance(lineage, SourceLineage):
        missing_lineage_fields = _CANONICAL_LINEAGE_FIELDS
        reasons.append(QualityReasonCode.CANONICAL_LINEAGE_INCOMPLETE)
        limitations.append("The candidate has no canonical source lineage.")
        hard_rejection = True
    else:
        if not authority_satisfies(
            lineage.authority,
            requirement.quality.minimum_authority,
        ):
            reasons.append(QualityReasonCode.AUTHORITY_BELOW_MINIMUM)
            limitations.append("The candidate authority is below the required minimum.")
            hard_rejection = True

        if requirement.quality.require_canonical_lineage:
            missing_lineage_fields = _missing_lineage_fields(lineage)
            if missing_lineage_fields:
                reasons.append(QualityReasonCode.CANONICAL_LINEAGE_INCOMPLETE)
                limitations.append(
                    "The candidate does not contain complete canonical raw lineage."
                )
                hard_rejection = True

        if _lineage_has_future_timestamp(lineage, now=evaluation_time):
            reasons.append(QualityReasonCode.FUTURE_TIMESTAMP)
            limitations.append("The candidate lineage contains a future timestamp.")
            hard_rejection = True

    if state is ObservationState.PARTIAL:
        if requirement.quality.allow_partial:
            reasons.append(QualityReasonCode.PARTIAL_ALLOWED)
            limitations.append("Partial evidence is allowed for factual fallback only.")
            research_usable = False
        else:
            reasons.append(QualityReasonCode.PARTIAL_NOT_ALLOWED)
            limitations.append("Partial evidence is not allowed by the requirement.")
            hard_rejection = True
    elif state is ObservationState.STALE:
        reasons.append(QualityReasonCode.STALE_EVIDENCE)
        limitations.append("The candidate observation is stale.")
        research_usable = False
    elif state is ObservationState.INDICATIVE:
        reasons.append(QualityReasonCode.INDICATIVE_EVIDENCE)
        limitations.append("The candidate is indicative, not an actual trade.")
        research_usable = False

    if freshness in {
        EvidenceFreshness.MISSING,
        EvidenceFreshness.NOT_APPLICABLE,
        EvidenceFreshness.UNKNOWN,
    }:
        reasons.append(QualityReasonCode.FRESHNESS_UNUSABLE)
        limitations.append("The candidate freshness state is not usable.")
        hard_rejection = True
    elif freshness is EvidenceFreshness.STALE:
        if QualityReasonCode.STALE_EVIDENCE not in reasons:
            reasons.append(QualityReasonCode.STALE_EVIDENCE)
            limitations.append("The candidate freshness is stale.")
        research_usable = False

    if freshness is not None and isinstance(lineage, SourceLineage):
        observed_at = _observed_at(lineage)
        if (
            observed_at is not None
            and requirement.realtime_policy is not RealtimePolicy.COMPLETED_SESSION
            and evaluation_time - observed_at
            > timedelta(seconds=requirement.freshness.max_age_seconds)
        ):
            if QualityReasonCode.STALE_EVIDENCE not in reasons:
                reasons.append(QualityReasonCode.STALE_EVIDENCE)
                limitations.append("The candidate exceeds the requested freshness age.")
            research_usable = False
            if requirement.realtime_policy is RealtimePolicy.REQUIRE_LIVE:
                reasons.append(QualityReasonCode.LIVE_REQUIRED)
                limitations.append("The requirement needs live evidence.")
                hard_rejection = True

    if hard_rejection:
        facts_usable = False
        research_usable = False
    if not reasons:
        reasons.append(QualityReasonCode.ELIGIBLE)

    return QualityEvaluation(
        eligible=not hard_rejection,
        reason_code=reasons[0],
        reason_codes=tuple(dict.fromkeys(reasons)),
        missing_fields=missing_fields,
        missing_lineage_fields=missing_lineage_fields,
        facts_usable=facts_usable,
        research_usable=research_usable,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def combine_quality_evaluations(
    evaluations: tuple[QualityEvaluation, ...],
) -> QualityEvaluation:
    """Combine per-observation evaluations without weakening any rejection."""

    if not evaluations:
        raise ValueError("quality evaluation combination requires at least one item")
    reason_codes = tuple(
        dict.fromkeys(
            reason
            for evaluation in evaluations
            for reason in evaluation.reason_codes
            if reason is not QualityReasonCode.ELIGIBLE
        )
    )
    if not reason_codes:
        reason_codes = (QualityReasonCode.ELIGIBLE,)
    return QualityEvaluation(
        eligible=all(evaluation.eligible for evaluation in evaluations),
        reason_code=reason_codes[0],
        reason_codes=reason_codes,
        missing_fields=tuple(
            dict.fromkeys(
                field
                for evaluation in evaluations
                for field in evaluation.missing_fields
            )
        ),
        missing_lineage_fields=tuple(
            dict.fromkeys(
                field
                for evaluation in evaluations
                for field in evaluation.missing_lineage_fields
            )
        ),
        facts_usable=all(evaluation.facts_usable for evaluation in evaluations),
        research_usable=all(
            evaluation.research_usable for evaluation in evaluations
        ),
        limitations=tuple(
            dict.fromkeys(
                limitation
                for evaluation in evaluations
                for limitation in evaluation.limitations
            )
        ),
    )


__all__ = [
    "FUTURE_TIMESTAMP_TOLERANCE",
    "QualityEvaluation",
    "QualityReasonCode",
    "authority_satisfies",
    "combine_quality_evaluations",
    "evaluate_candidate_quality",
    "required_fields_for",
]
