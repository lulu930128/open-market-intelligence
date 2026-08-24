"""Allowlisted diagnostics for dark market-data acquisition attempts."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel, Market
from app.market_data.control_plane import ControlPlaneAcquisitionResult
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_policy import (
    AcquisitionPlan,
    ProviderKey,
    ReasonCode,
)
from app.market_data.research_lease import AcquisitionOutcome, CleanupStatus


class ProviderSkipDiagnostic(CanonicalModel):
    contract_version: str = "omi.market.provider_skip_diagnostic.v1"
    provider_key: ProviderKey
    reason_code: ReasonCode


class ProviderAttemptDiagnostic(CanonicalModel):
    contract_version: str = "omi.market.provider_attempt_diagnostic.v1"
    provider_key: ProviderKey
    outcome: AcquisitionOutcome
    cleanup_status: CleanupStatus
    detail_code: ReasonCode
    port_started: bool
    candidate_count: int = Field(ge=0, le=8)
    external_calls: int | None = Field(default=None, ge=0, le=20)
    subscriptions_created: int | None = Field(default=None, ge=0, le=8)
    elapsed_seconds: float = Field(ge=0, le=120)
    active_after_cleanup: bool | None = None
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=8)


class AcquisitionDiagnostic(CanonicalModel):
    contract_version: str = "omi.market.acquisition_diagnostic.v1"
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    purpose: DataPurpose
    market: Market
    target: str = Field(min_length=3, max_length=72, pattern=r"^[A-Z]+:[A-Z0-9_.-]+$")
    capability_id: str = Field(min_length=1, max_length=128)
    realtime_policy: RealtimePolicy
    attempts: tuple[ProviderAttemptDiagnostic, ...] = Field(default=(), max_length=8)
    skipped_providers: tuple[ProviderSkipDiagnostic, ...] = Field(
        default=(),
        max_length=16,
    )
    logical_attempt_count: int = Field(ge=0, le=8)
    port_start_count: int = Field(ge=0, le=8)
    candidate_count: int = Field(ge=0, le=8)
    external_calls: int | None = Field(default=None, ge=0, le=20)
    subscriptions_created: int | None = Field(default=None, ge=0, le=8)
    released_attempt_count: int = Field(ge=0, le=8)
    cleanup_failed_attempt_count: int = Field(ge=0, le=8)
    active_handles_after: int | None = Field(default=None, ge=0, le=8)
    additional_route_attempted: bool
    final_acquisition_outcome: AcquisitionOutcome
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def _validate_summary(self) -> AcquisitionDiagnostic:
        if self.logical_attempt_count != len(self.attempts):
            raise ValueError("diagnostic attempt count mismatch")
        if self.released_attempt_count + self.cleanup_failed_attempt_count > len(
            self.attempts
        ):
            raise ValueError("cleanup summary exceeds attempts")
        return self


def build_acquisition_diagnostic(
    plan: AcquisitionPlan,
    result: ControlPlaneAcquisitionResult,
) -> AcquisitionDiagnostic:
    """Project only safe acquisition metadata; never observations or exceptions."""

    if plan.requirement != result.requirement:
        raise ValueError("diagnostic plan and result requirements do not match")

    attempts = tuple(
        ProviderAttemptDiagnostic(
            provider_key=attempt.provider_key,
            outcome=attempt.outcome,
            cleanup_status=attempt.cleanup_status,
            detail_code=attempt.detail_code,
            port_started=attempt.port_started,
            candidate_count=(
                len(attempt.acquisition_result.snapshots)
                if attempt.acquisition_result is not None
                else 0
            ),
            external_calls=attempt.external_calls,
            subscriptions_created=attempt.subscriptions_created,
            elapsed_seconds=attempt.elapsed_seconds,
            active_after_cleanup=attempt.active_after_cleanup,
            limitations=attempt.limitations,
        )
        for attempt in result.attempts
    )
    skipped = tuple(
        ProviderSkipDiagnostic(
            provider_key=item.provider_key,
            reason_code=item.reason_code,
        )
        for item in plan.skipped_providers
    )
    return AcquisitionDiagnostic(
        request_id=result.request_id,
        purpose=result.requirement.purpose,
        market=result.requirement.instrument.market,
        target=(
            f"{result.requirement.instrument.market.value}:"
            f"{result.requirement.instrument.symbol}"
        ),
        capability_id=result.requirement.capability_id,
        realtime_policy=result.requirement.realtime_policy,
        attempts=attempts,
        skipped_providers=skipped,
        logical_attempt_count=result.logical_attempt_count,
        port_start_count=result.port_start_count,
        candidate_count=len(result.candidates),
        external_calls=result.external_calls,
        subscriptions_created=result.subscriptions_created,
        released_attempt_count=sum(
            attempt.cleanup_status is CleanupStatus.RELEASED for attempt in attempts
        ),
        cleanup_failed_attempt_count=sum(
            attempt.cleanup_status is CleanupStatus.CLEANUP_FAILED
            for attempt in attempts
        ),
        active_handles_after=result.active_handles_after,
        additional_route_attempted=len(attempts) > 1,
        final_acquisition_outcome=result.outcome,
        limitations=result.limitations,
    )


__all__ = [
    "AcquisitionDiagnostic",
    "ProviderAttemptDiagnostic",
    "ProviderSkipDiagnostic",
    "build_acquisition_diagnostic",
]
