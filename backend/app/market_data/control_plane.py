"""Dark provider-neutral orchestration for bounded market-data acquisition."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping

from pydantic import Field, model_validator

from app.market_data.contracts import (
    CanonicalMarketSnapshot,
    CanonicalModel,
    ProviderResourceHealth,
)
from app.market_data.policies import DataRequirement
from app.market_data.provider_policy import AcquisitionPlan, ReasonCode
from app.market_data.research_lease import (
    AcquisitionAttemptContext,
    AcquisitionOutcome,
    CancellationToken,
    CleanupStatus,
    NeverCancelled,
    ResearchAcquisitionPort,
    ResearchLeaseResult,
    ResearchLeaseRunner,
)


MAX_PROVIDER_HEALTH_RECORDS = 16


class ControlPlaneAcquisitionResult(CanonicalModel):
    contract_version: str = "omi.market.control_plane_acquisition_result.v1"
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    requirement: DataRequirement
    candidates: tuple[CanonicalMarketSnapshot, ...] = Field(default=(), max_length=8)
    provider_health: tuple[ProviderResourceHealth, ...] = Field(
        default=(),
        max_length=MAX_PROVIDER_HEALTH_RECORDS,
    )
    attempts: tuple[ResearchLeaseResult, ...] = Field(default=(), max_length=8)
    logical_attempt_count: int = Field(ge=0, le=8)
    port_start_count: int = Field(ge=0, le=8)
    external_calls: int | None = Field(default=None, ge=0, le=20)
    subscriptions_created: int | None = Field(default=None, ge=0, le=8)
    active_handles_after: int | None = Field(default=None, ge=0, le=8)
    outcome: AcquisitionOutcome
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def _validate_result(self) -> ControlPlaneAcquisitionResult:
        if len(self.candidates) > self.requirement.max_candidates:
            raise ValueError("candidate count exceeds requirement.max_candidates")
        if self.logical_attempt_count != len(self.attempts):
            raise ValueError("logical attempt count must match attempt records")
        if self.port_start_count != sum(item.port_started for item in self.attempts):
            raise ValueError("port start count must match attempt records")
        if self.outcome is AcquisitionOutcome.ACQUIRED and not self.candidates:
            raise ValueError("acquired control-plane result requires candidates")
        if self.active_handles_after == 0 and any(
            item.active_after_cleanup is True for item in self.attempts
        ):
            raise ValueError("active handle summary conflicts with attempt records")
        return self


IdFactory = Callable[[], str]
Clock = Callable[[], float]
Wait = Callable[[float], None]


def _default_id() -> str:
    return uuid.uuid4().hex


def _dedupe_codes(codes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def _no_handle_attempt(
    *,
    request_id: str,
    owner_token: str,
    provider_key: str,
    outcome: AcquisitionOutcome,
    detail_code: str,
) -> ResearchLeaseResult:
    return ResearchLeaseResult(
        request_id=request_id,
        owner_token=owner_token,
        provider_key=provider_key,
        outcome=outcome,
        cleanup_status=CleanupStatus.NOT_REQUIRED,
        detail_code=detail_code,
        port_started=False,
        external_calls=0,
        subscriptions_created=0,
        elapsed_seconds=0,
        active_after_cleanup=False,
    )


def execute_acquisition(
    requirement: DataRequirement,
    plan: AcquisitionPlan,
    ports: Mapping[str, ResearchAcquisitionPort],
    *,
    cancellation: CancellationToken | None = None,
    runner: ResearchLeaseRunner | None = None,
    clock: Clock = time.monotonic,
    wait: Wait = time.sleep,
    id_factory: IdFactory = _default_id,
) -> ControlPlaneAcquisitionResult:
    """Execute a bounded plan and return candidates, never final selection."""

    if plan.requirement != requirement:
        raise ValueError("acquisition plan requirement does not match execution request")

    request_id = id_factory()
    token = cancellation or NeverCancelled()
    lease_runner = runner or ResearchLeaseRunner()
    limitations: list[str] = list(plan.limitations)

    if not plan.acquisition_required:
        return ControlPlaneAcquisitionResult(
            request_id=request_id,
            requirement=requirement,
            logical_attempt_count=0,
            port_start_count=0,
            external_calls=0,
            subscriptions_created=0,
            active_handles_after=0,
            outcome=AcquisitionOutcome.NOT_REQUIRED,
            limitations=_dedupe_codes(limitations),
        )
    if plan.unfillable:
        return ControlPlaneAcquisitionResult(
            request_id=request_id,
            requirement=requirement,
            logical_attempt_count=0,
            port_start_count=0,
            external_calls=0,
            subscriptions_created=0,
            active_handles_after=0,
            outcome=AcquisitionOutcome.POLICY_UNFILLABLE,
            limitations=_dedupe_codes(limitations),
        )

    started_at = clock()
    overall_deadline = started_at + plan.bounds.overall_timeout_seconds
    candidates: list[CanonicalMarketSnapshot] = []
    health_records: list[ProviderResourceHealth] = []
    attempts: list[ResearchLeaseResult] = []
    external_total = 0
    subscription_total = 0
    counts_known = True
    final_override: AcquisitionOutcome | None = None

    for route in plan.routes:
        if token.is_cancelled():
            final_override = AcquisitionOutcome.CANCELLED
            limitations.append("REQUEST_CANCELLED_BEFORE_ROUTE")
            break
        now = clock()
        if now >= overall_deadline:
            final_override = AcquisitionOutcome.TIMED_OUT
            limitations.append("OVERALL_DEADLINE_EXPIRED")
            break

        owner_token = f"owner-{id_factory()}"
        port = ports.get(route.provider_key)
        if port is None:
            attempts.append(
                _no_handle_attempt(
                    request_id=request_id,
                    owner_token=owner_token,
                    provider_key=route.provider_key,
                    outcome=AcquisitionOutcome.UNAVAILABLE,
                    detail_code="PORT_NOT_REGISTERED",
                )
            )
            limitations.append("PORT_NOT_REGISTERED")
            if not plan.fallback_allowed:
                break
            continue

        route_deadline = min(
            overall_deadline,
            now + route.route_timeout_seconds,
        )
        context = AcquisitionAttemptContext(
            request_id=request_id,
            owner_token=owner_token,
            requirement=requirement,
            route=route,
            started_at_monotonic=now,
            absolute_deadline_monotonic=route_deadline,
        )
        attempt = lease_runner.run(
            port,
            context,
            cancellation=token,
            clock=clock,
            wait=wait,
        )
        attempts.append(attempt)
        limitations.extend(route.limitations)
        limitations.extend(attempt.limitations)

        if attempt.cleanup_status is CleanupStatus.CLEANUP_FAILED:
            final_override = AcquisitionOutcome.FAILED
            limitations.append("CLEANUP_INVARIANT_FAILED")
            break
        if attempt.external_calls is None or attempt.subscriptions_created is None:
            counts_known = False
            limitations.append("ACTIVITY_COUNT_UNKNOWN")
        else:
            external_total += attempt.external_calls
            subscription_total += attempt.subscriptions_created
            if external_total > plan.bounds.max_external_calls:
                final_override = AcquisitionOutcome.FAILED
                limitations.append("EXTERNAL_CALL_BUDGET_EXCEEDED")
                break
            if subscription_total > plan.bounds.max_subscriptions:
                final_override = AcquisitionOutcome.FAILED
                limitations.append("SUBSCRIPTION_BUDGET_EXCEEDED")
                break

        acquisition = attempt.acquisition_result
        if acquisition is not None:
            if len(health_records) + len(acquisition.provider_health) > MAX_PROVIDER_HEALTH_RECORDS:
                final_override = AcquisitionOutcome.FAILED
                limitations.append("PROVIDER_HEALTH_BOUND_EXCEEDED")
                break
            health_records.extend(acquisition.provider_health)

        if attempt.outcome is AcquisitionOutcome.ACQUIRED:
            assert acquisition is not None
            if len(candidates) + len(acquisition.snapshots) > requirement.max_candidates:
                final_override = AcquisitionOutcome.FAILED
                limitations.append("PORT_CANDIDATE_BOUND_EXCEEDED")
                break
            candidates.extend(acquisition.snapshots)
            limitations.append("CANDIDATES_COLLECTED_RESOLUTION_PENDING")
        elif attempt.outcome is AcquisitionOutcome.CANCELLED:
            final_override = AcquisitionOutcome.CANCELLED
            break
        elif not plan.fallback_allowed:
            final_override = attempt.outcome
            break

    if final_override is not None:
        final_outcome = final_override
    elif candidates:
        final_outcome = AcquisitionOutcome.ACQUIRED
    elif any(item.outcome is AcquisitionOutcome.FAILED for item in attempts):
        final_outcome = AcquisitionOutcome.FAILED
    elif any(item.outcome is AcquisitionOutcome.TIMED_OUT for item in attempts):
        final_outcome = AcquisitionOutcome.TIMED_OUT
    else:
        final_outcome = AcquisitionOutcome.UNAVAILABLE

    if counts_known:
        final_external_calls: int | None = external_total
        final_subscriptions: int | None = subscription_total
    else:
        final_external_calls = None
        final_subscriptions = None

    active_known = all(
        item.active_after_cleanup is not None or not item.port_started for item in attempts
    )
    active_after = (
        sum(item.active_after_cleanup is True for item in attempts)
        if active_known
        else None
    )
    return ControlPlaneAcquisitionResult(
        request_id=request_id,
        requirement=requirement,
        candidates=tuple(candidates),
        provider_health=tuple(health_records),
        attempts=tuple(attempts),
        logical_attempt_count=len(attempts),
        port_start_count=sum(item.port_started for item in attempts),
        external_calls=final_external_calls,
        subscriptions_created=final_subscriptions,
        active_handles_after=active_after,
        outcome=final_outcome,
        limitations=_dedupe_codes(limitations),
    )


__all__ = [
    "ControlPlaneAcquisitionResult",
    "MAX_PROVIDER_HEALTH_RECORDS",
    "execute_acquisition",
]
