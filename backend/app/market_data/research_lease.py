"""Request-scoped, cooperative Research Lease lifecycle primitives.

This dark module owns no provider implementation. A market-specific port must
return an owned, non-blocking handle before a potentially long acquisition so
the runner can cooperatively cancel and release it on every exit path.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from enum import Enum
from typing import Protocol

from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel
from app.market_data.policies import AcquisitionResult, DataRequirement
from app.market_data.provider_policy import ProviderRoute, ReasonCode


class AcquisitionOutcome(str, Enum):
    NOT_REQUIRED = "not_required"
    ACQUIRED = "acquired"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    POLICY_UNFILLABLE = "policy_unfillable"


class CleanupStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RELEASED = "released"
    CLEANUP_FAILED = "cleanup_failed"


class AcquisitionActivity(CanonicalModel):
    contract_version: str = "omi.market.acquisition_activity.v1"
    external_calls: int | None = Field(default=None, ge=0, le=20)
    subscriptions_created: int | None = Field(default=None, ge=0, le=8)


class CancelResult(CanonicalModel):
    contract_version: str = "omi.market.research_lease_cancel.v1"
    accepted: bool
    detail_code: ReasonCode


class CleanupResult(CanonicalModel):
    contract_version: str = "omi.market.research_lease_cleanup.v1"
    status: CleanupStatus
    detail_code: ReasonCode

    @model_validator(mode="after")
    def _require_terminal_cleanup_status(self) -> CleanupResult:
        if self.status not in {
            CleanupStatus.RELEASED,
            CleanupStatus.CLEANUP_FAILED,
        }:
            raise ValueError("handle cleanup result must be terminal")
        return self


class ProviderAttemptResult(CanonicalModel):
    contract_version: str = "omi.market.provider_attempt_result.v1"
    outcome: AcquisitionOutcome
    acquisition: AcquisitionResult
    detail_code: ReasonCode

    @model_validator(mode="after")
    def _validate_provider_outcome(self) -> ProviderAttemptResult:
        allowed = {
            AcquisitionOutcome.ACQUIRED,
            AcquisitionOutcome.UNAVAILABLE,
            AcquisitionOutcome.FAILED,
        }
        if self.outcome not in allowed:
            raise ValueError("provider attempt returned a runner-owned outcome")
        if self.outcome is AcquisitionOutcome.ACQUIRED and not self.acquisition.snapshots:
            raise ValueError("acquired provider result requires canonical snapshots")
        if self.outcome is not AcquisitionOutcome.ACQUIRED and self.acquisition.snapshots:
            raise ValueError("non-acquired provider result cannot contain snapshots")
        return self


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class AcquisitionAttemptContext(CanonicalModel):
    contract_version: str = "omi.market.acquisition_attempt_context.v1"
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    owner_token: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    requirement: DataRequirement
    route: ProviderRoute
    started_at_monotonic: float = Field(ge=0)
    absolute_deadline_monotonic: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate_attempt_scope(self) -> AcquisitionAttemptContext:
        if self.absolute_deadline_monotonic <= self.started_at_monotonic:
            raise ValueError("attempt deadline must be after start")
        if self.route.market is not self.requirement.instrument.market:
            raise ValueError("route market must match requirement instrument")
        if self.route.capability_id != self.requirement.capability_id:
            raise ValueError("route capability must match requirement")
        return self


class ResearchAcquisitionHandle(Protocol):
    @property
    def owner_token(self) -> str: ...

    @property
    def active(self) -> bool: ...

    @property
    def terminal(self) -> bool: ...

    @property
    def activity(self) -> AcquisitionActivity: ...

    def poll(self) -> ProviderAttemptResult | None: ...

    def cancel(self, reason_code: str) -> CancelResult: ...

    def release(self) -> CleanupResult: ...


class ResearchAcquisitionPort(Protocol):
    def start(self, context: AcquisitionAttemptContext) -> ResearchAcquisitionHandle: ...


class ResearchLeaseResult(CanonicalModel):
    contract_version: str = "omi.market.research_lease_result.v1"
    request_id: str = Field(min_length=1, max_length=64)
    owner_token: str = Field(min_length=8, max_length=128)
    provider_key: str = Field(min_length=1, max_length=64)
    outcome: AcquisitionOutcome
    cleanup_status: CleanupStatus
    acquisition_result: AcquisitionResult | None = None
    detail_code: ReasonCode
    port_started: bool
    external_calls: int | None = Field(default=None, ge=0, le=20)
    subscriptions_created: int | None = Field(default=None, ge=0, le=8)
    elapsed_seconds: float = Field(ge=0, le=120)
    active_after_cleanup: bool | None = None
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _validate_result(self) -> ResearchLeaseResult:
        if self.outcome is AcquisitionOutcome.ACQUIRED:
            if self.acquisition_result is None or not self.acquisition_result.snapshots:
                raise ValueError("acquired lease result requires canonical snapshots")
        if self.cleanup_status is CleanupStatus.RELEASED and self.active_after_cleanup:
            raise ValueError("released lease cannot remain active")
        if not self.port_started and self.cleanup_status is not CleanupStatus.NOT_REQUIRED:
            raise ValueError("unstarted port cannot require handle cleanup")
        return self


Clock = Callable[[], float]
Wait = Callable[[float], None]


def _dedupe_codes(codes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


class ResearchLeaseRunner:
    """Execute one provider route with cooperative deadline and owned cleanup."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 0.01,
        max_poll_iterations: int = 20_000,
    ) -> None:
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be finite and positive")
        if max_poll_iterations < 1 or max_poll_iterations > 100_000:
            raise ValueError("max_poll_iterations must be between 1 and 100000")
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_iterations = max_poll_iterations

    def run(
        self,
        port: ResearchAcquisitionPort,
        context: AcquisitionAttemptContext,
        *,
        cancellation: CancellationToken | None = None,
        clock: Clock = time.monotonic,
        wait: Wait = time.sleep,
    ) -> ResearchLeaseResult:
        token = cancellation or NeverCancelled()
        now = clock()
        if token.is_cancelled():
            return self._without_handle(
                context,
                outcome=AcquisitionOutcome.CANCELLED,
                detail_code="REQUEST_CANCELLED_BEFORE_START",
                elapsed_seconds=max(0.0, now - context.started_at_monotonic),
            )
        if now >= context.absolute_deadline_monotonic:
            return self._without_handle(
                context,
                outcome=AcquisitionOutcome.TIMED_OUT,
                detail_code="DEADLINE_EXPIRED_BEFORE_START",
                elapsed_seconds=max(0.0, now - context.started_at_monotonic),
            )

        try:
            handle = port.start(context)
        except Exception:
            return ResearchLeaseResult(
                request_id=context.request_id,
                owner_token=context.owner_token,
                provider_key=context.route.provider_key,
                outcome=AcquisitionOutcome.FAILED,
                cleanup_status=CleanupStatus.NOT_REQUIRED,
                detail_code="PORT_START_FAILED",
                port_started=True,
                external_calls=None,
                subscriptions_created=None,
                elapsed_seconds=min(
                    120.0,
                    max(0.0, clock() - context.started_at_monotonic),
                ),
                active_after_cleanup=None,
                limitations=("ACTIVITY_COUNT_UNKNOWN",),
            )

        if handle.owner_token != context.owner_token:
            return ResearchLeaseResult(
                request_id=context.request_id,
                owner_token=context.owner_token,
                provider_key=context.route.provider_key,
                outcome=AcquisitionOutcome.FAILED,
                cleanup_status=CleanupStatus.CLEANUP_FAILED,
                detail_code="OWNER_TOKEN_MISMATCH",
                port_started=True,
                external_calls=handle.activity.external_calls,
                subscriptions_created=handle.activity.subscriptions_created,
                elapsed_seconds=min(
                    120.0,
                    max(0.0, clock() - context.started_at_monotonic),
                ),
                active_after_cleanup=handle.active,
                limitations=("UNKNOWN_HANDLE_NOT_RELEASED",),
            )

        outcome = AcquisitionOutcome.FAILED
        detail_code = "UNCLASSIFIED_PROVIDER_ERROR"
        acquisition_result: AcquisitionResult | None = None
        limitations: list[str] = []
        iterations = 0

        while True:
            iterations += 1
            now = clock()
            if token.is_cancelled():
                outcome = AcquisitionOutcome.CANCELLED
                detail_code = "REQUEST_CANCELLED"
                self._cancel_owned(handle, "REQUEST_CANCELLED", limitations)
                break
            if now >= context.absolute_deadline_monotonic:
                outcome = AcquisitionOutcome.TIMED_OUT
                detail_code = "ACQUISITION_TIMED_OUT"
                self._cancel_owned(handle, "ACQUISITION_TIMED_OUT", limitations)
                break
            if iterations > self._max_poll_iterations:
                outcome = AcquisitionOutcome.FAILED
                detail_code = "POLL_ITERATION_BOUND_EXCEEDED"
                self._cancel_owned(handle, detail_code, limitations)
                break

            try:
                attempt_result = handle.poll()
            except Exception:
                outcome = AcquisitionOutcome.FAILED
                detail_code = "PROVIDER_POLL_FAILED"
                self._cancel_owned(handle, detail_code, limitations)
                break

            if attempt_result is not None:
                outcome = attempt_result.outcome
                detail_code = attempt_result.detail_code
                acquisition_result = attempt_result.acquisition
                activity = handle.activity
                if (
                    activity.external_calls is not None
                    and activity.external_calls != acquisition_result.external_calls
                ) or (
                    activity.subscriptions_created is not None
                    and activity.subscriptions_created
                    != acquisition_result.subscriptions_created
                ):
                    outcome = AcquisitionOutcome.FAILED
                    detail_code = "ACTIVITY_COUNT_MISMATCH"
                    acquisition_result = None
                    limitations.append("PORT_ACTIVITY_CONTRACT_VIOLATION")
                elif attempt_result.acquisition.limitations:
                    limitations.append("PROVIDER_LIMITATION_REPORTED")
                    acquisition_result = attempt_result.acquisition.model_copy(
                        update={"limitations": ()}
                    )
                break

            if handle.terminal:
                outcome = AcquisitionOutcome.FAILED
                detail_code = "TERMINAL_WITHOUT_RESULT"
                self._cancel_owned(handle, detail_code, limitations)
                break

            remaining = context.absolute_deadline_monotonic - clock()
            wait(max(0.0, min(self._poll_interval_seconds, remaining)))

        cleanup_status, cleanup_code, active_after = self._release_owned(
            handle,
            context.owner_token,
            limitations,
        )
        if cleanup_status is CleanupStatus.CLEANUP_FAILED:
            limitations.append(cleanup_code)

        activity = handle.activity
        elapsed = min(
            120.0,
            max(0.0, clock() - context.started_at_monotonic),
        )
        return ResearchLeaseResult(
            request_id=context.request_id,
            owner_token=context.owner_token,
            provider_key=context.route.provider_key,
            outcome=outcome,
            cleanup_status=cleanup_status,
            acquisition_result=acquisition_result,
            detail_code=detail_code,
            port_started=True,
            external_calls=activity.external_calls,
            subscriptions_created=activity.subscriptions_created,
            elapsed_seconds=elapsed,
            active_after_cleanup=active_after,
            limitations=_dedupe_codes(limitations),
        )

    @staticmethod
    def _without_handle(
        context: AcquisitionAttemptContext,
        *,
        outcome: AcquisitionOutcome,
        detail_code: str,
        elapsed_seconds: float,
    ) -> ResearchLeaseResult:
        return ResearchLeaseResult(
            request_id=context.request_id,
            owner_token=context.owner_token,
            provider_key=context.route.provider_key,
            outcome=outcome,
            cleanup_status=CleanupStatus.NOT_REQUIRED,
            detail_code=detail_code,
            port_started=False,
            external_calls=0,
            subscriptions_created=0,
            elapsed_seconds=min(120.0, elapsed_seconds),
            active_after_cleanup=False,
        )

    @staticmethod
    def _cancel_owned(
        handle: ResearchAcquisitionHandle,
        reason_code: str,
        limitations: list[str],
    ) -> None:
        try:
            cancel_result = handle.cancel(reason_code)
            if not cancel_result.accepted:
                limitations.append("CANCEL_NOT_ACCEPTED")
        except Exception:
            limitations.append("CANCEL_FAILED")

    @staticmethod
    def _release_owned(
        handle: ResearchAcquisitionHandle,
        owner_token: str,
        limitations: list[str],
    ) -> tuple[CleanupStatus, str, bool | None]:
        if handle.owner_token != owner_token:
            return CleanupStatus.CLEANUP_FAILED, "OWNER_CHANGED_BEFORE_RELEASE", handle.active
        try:
            cleanup = handle.release()
        except Exception:
            return CleanupStatus.CLEANUP_FAILED, "RELEASE_FAILED", handle.active
        active_after = handle.active
        if cleanup.status is CleanupStatus.CLEANUP_FAILED:
            return cleanup.status, cleanup.detail_code, active_after
        if active_after:
            return CleanupStatus.CLEANUP_FAILED, "HANDLE_STILL_ACTIVE", True
        if not handle.terminal:
            limitations.append("HANDLE_NOT_TERMINAL_AFTER_RELEASE")
            return CleanupStatus.CLEANUP_FAILED, "HANDLE_NOT_TERMINAL_AFTER_RELEASE", False
        return CleanupStatus.RELEASED, cleanup.detail_code, False


__all__ = [
    "AcquisitionActivity",
    "AcquisitionAttemptContext",
    "AcquisitionOutcome",
    "CancelResult",
    "CancellationToken",
    "CleanupResult",
    "CleanupStatus",
    "NeverCancelled",
    "ProviderAttemptResult",
    "ResearchAcquisitionHandle",
    "ResearchAcquisitionPort",
    "ResearchLeaseResult",
    "ResearchLeaseRunner",
]
