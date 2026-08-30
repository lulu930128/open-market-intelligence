"""Provider-owned rate-limit and failure guard for all TWSE MIS resources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
import time
from typing import Mapping


@dataclass(frozen=True, slots=True)
class TwseMisAttemptToken:
    attempt_id: int
    generation: int
    probe: bool = False


@dataclass(frozen=True, slots=True)
class TwseMisGuardDecision:
    allowed: bool
    status: str
    detail_code: str
    retry_after_seconds: int | None = None
    cooldown_until: datetime | None = None
    probe: bool = False
    generation: int = 0
    attempt: TwseMisAttemptToken | None = None


def parse_retry_after_seconds(
    headers: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> int | None:
    """Parse Retry-After delta-seconds or HTTP-date without raising."""

    if not headers:
        return None
    value: str | None = None
    for key, candidate in headers.items():
        if str(key).casefold() == "retry-after":
            value = str(candidate).strip()
            break
    if not value:
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(int((parsed.astimezone(timezone.utc) - reference).total_seconds()), 0)


class TwseMisProviderGuard:
    """One provider-wide cooldown with exactly one recovery probe at a time."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        failure_cooldown_seconds: int = 90,
        rate_limit_cooldown_seconds: int = 120,
        monotonic=time.monotonic,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        self._failure_threshold = failure_threshold
        self._failure_cooldown_seconds = max(failure_cooldown_seconds, 1)
        self._rate_limit_cooldown_seconds = max(rate_limit_cooldown_seconds, 1)
        self._monotonic = monotonic
        self._clock = clock
        self._lock = Lock()
        self._failures = 0
        self._cooldown_until_monotonic = 0.0
        self._cooldown_until_wall: datetime | None = None
        self._reason = "healthy"
        self._probe_in_flight = False
        self._probe_attempt_id: int | None = None
        self._generation = 0
        self._next_attempt_id = 1
        self._active_attempts: dict[int, TwseMisAttemptToken] = {}

    def _new_attempt_locked(self, *, probe: bool) -> TwseMisAttemptToken:
        attempt = TwseMisAttemptToken(
            attempt_id=self._next_attempt_id,
            generation=self._generation,
            probe=probe,
        )
        self._next_attempt_id += 1
        self._active_attempts[attempt.attempt_id] = attempt
        return attempt

    def _consume_attempt_locked(self, attempt: TwseMisAttemptToken) -> bool:
        active = self._active_attempts.pop(attempt.attempt_id, None)
        return active == attempt

    def before_request(self) -> TwseMisGuardDecision:
        with self._lock:
            remaining = self._cooldown_until_monotonic - self._monotonic()
            if remaining > 0:
                return TwseMisGuardDecision(
                    allowed=False,
                    status=self._reason,
                    detail_code=(
                        "TWSE_MIS_RATE_LIMIT_COOLDOWN"
                        if self._reason == "rate_limited"
                        else "TWSE_MIS_PROVIDER_COOLDOWN"
                    ),
                    retry_after_seconds=max(int(remaining + 0.999), 1),
                    cooldown_until=self._cooldown_until_wall,
                    generation=self._generation,
                )
            if self._cooldown_until_monotonic > 0:
                if self._probe_in_flight:
                    return TwseMisGuardDecision(
                        allowed=False,
                        status="probe_in_flight",
                        detail_code="TWSE_MIS_RECOVERY_PROBE_IN_FLIGHT",
                        retry_after_seconds=1,
                        cooldown_until=self._cooldown_until_wall,
                        generation=self._generation,
                    )
                self._probe_in_flight = True
                attempt = self._new_attempt_locked(probe=True)
                self._probe_attempt_id = attempt.attempt_id
                return TwseMisGuardDecision(
                    allowed=True,
                    status="probing",
                    detail_code="TWSE_MIS_RECOVERY_PROBE",
                    cooldown_until=self._cooldown_until_wall,
                    probe=True,
                    generation=self._generation,
                    attempt=attempt,
                )
            attempt = self._new_attempt_locked(probe=False)
            return TwseMisGuardDecision(
                allowed=True,
                status="healthy",
                detail_code="TWSE_MIS_REQUEST_ALLOWED",
                generation=self._generation,
                attempt=attempt,
            )

    def record_success(
        self,
        attempt: TwseMisAttemptToken,
    ) -> TwseMisGuardDecision:
        with self._lock:
            if not self._consume_attempt_locked(attempt):
                return self._snapshot_locked()
            if attempt.generation != self._generation:
                return self._snapshot_locked()
            if self._cooldown_until_monotonic > 0 and (
                not attempt.probe
                or attempt.attempt_id != self._probe_attempt_id
            ):
                return self._snapshot_locked()
            self._failures = 0
            self._cooldown_until_monotonic = 0.0
            self._cooldown_until_wall = None
            self._reason = "healthy"
            self._probe_in_flight = False
            self._probe_attempt_id = None
            if attempt.probe:
                self._generation += 1
                self._active_attempts.clear()
            return self._snapshot_locked()

    def cancel_attempt(
        self,
        attempt: TwseMisAttemptToken,
    ) -> TwseMisGuardDecision:
        """Release an allowed slot that never reached provider IO."""

        with self._lock:
            if not self._consume_attempt_locked(attempt):
                return self._snapshot_locked()
            if (
                attempt.generation == self._generation
                and attempt.probe
                and attempt.attempt_id == self._probe_attempt_id
            ):
                self._probe_in_flight = False
                self._probe_attempt_id = None
            return self._snapshot_locked()

    def record_http_failure(
        self,
        attempt: TwseMisAttemptToken,
        status_code: int,
        *,
        headers: Mapping[str, object] | None = None,
    ) -> TwseMisGuardDecision:
        if int(status_code) == 429:
            retry_after = parse_retry_after_seconds(headers, now=self._clock())
            return self._open(
                attempt=attempt,
                reason="rate_limited",
                seconds=max(retry_after or 0, self._rate_limit_cooldown_seconds),
                detail_code="TWSE_MIS_HTTP_429",
            )
        return self.record_failure(
            attempt,
            detail_code=f"TWSE_MIS_HTTP_{int(status_code)}",
        )

    def record_failure(
        self,
        attempt: TwseMisAttemptToken,
        *,
        detail_code: str = "TWSE_MIS_REQUEST_FAILED",
    ) -> TwseMisGuardDecision:
        with self._lock:
            if not self._consume_attempt_locked(attempt):
                return self._snapshot_locked()
            if attempt.generation != self._generation:
                return self._snapshot_locked()
            if attempt.probe:
                return self._open_locked(
                    reason="failed",
                    seconds=self._failure_cooldown_seconds,
                    detail_code=detail_code,
                )
            self._failures += 1
            if self._failures < self._failure_threshold:
                return TwseMisGuardDecision(
                    allowed=True,
                    status="degraded",
                    detail_code=detail_code,
                    generation=self._generation,
                )
            return self._open_locked(
                reason="failed",
                seconds=self._failure_cooldown_seconds,
                detail_code=detail_code,
            )

    def _open(
        self,
        *,
        attempt: TwseMisAttemptToken | None,
        reason: str,
        seconds: int,
        detail_code: str,
    ) -> TwseMisGuardDecision:
        duration = max(int(seconds), 1)
        with self._lock:
            if attempt is not None and not self._consume_attempt_locked(attempt):
                return self._snapshot_locked()
            return self._open_locked(
                reason=reason,
                seconds=duration,
                detail_code=detail_code,
            )

    def _open_locked(
        self,
        *,
        reason: str,
        seconds: int,
        detail_code: str,
    ) -> TwseMisGuardDecision:
        duration = max(int(seconds), 1)
        now_monotonic = self._monotonic()
        now_wall = self._clock()
        if now_wall.tzinfo is None or now_wall.utcoffset() is None:
            raise ValueError("TWSE MIS guard clock must be timezone-aware")
        self._cooldown_until_monotonic = max(
            self._cooldown_until_monotonic,
            now_monotonic + duration,
        )
        self._cooldown_until_wall = max(
            self._cooldown_until_wall or now_wall,
            now_wall + timedelta(seconds=duration),
        )
        self._reason = reason
        self._probe_in_flight = False
        self._probe_attempt_id = None
        self._generation += 1
        self._active_attempts.clear()
        return TwseMisGuardDecision(
            allowed=False,
            status=reason,
            detail_code=detail_code,
            retry_after_seconds=duration,
            cooldown_until=self._cooldown_until_wall,
            generation=self._generation,
        )

    def _snapshot_locked(self) -> TwseMisGuardDecision:
        remaining = self._cooldown_until_monotonic - self._monotonic()
        return TwseMisGuardDecision(
            allowed=remaining <= 0 and not self._probe_in_flight,
            status=self._reason,
            detail_code=(
                "TWSE_MIS_RATE_LIMIT_COOLDOWN"
                if self._reason == "rate_limited"
                else "TWSE_MIS_PROVIDER_COOLDOWN"
                if remaining > 0
                else "TWSE_MIS_PROVIDER_AVAILABLE"
            ),
            retry_after_seconds=(
                max(int(remaining + 0.999), 1) if remaining > 0 else None
            ),
            cooldown_until=self._cooldown_until_wall,
            probe=self._probe_in_flight,
            generation=self._generation,
        )

    def snapshot(self) -> TwseMisGuardDecision:
        with self._lock:
            return self._snapshot_locked()

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._cooldown_until_monotonic = 0.0
            self._cooldown_until_wall = None
            self._reason = "healthy"
            self._probe_in_flight = False
            self._probe_attempt_id = None
            self._generation += 1
            self._active_attempts.clear()


TWSE_MIS_PROVIDER_GUARD = TwseMisProviderGuard()


def response_failure_metadata(response: object) -> tuple[int | None, Mapping[str, object]]:
    """Extract HTTP status/headers from requests responses or HTTP exceptions."""

    candidate = getattr(response, "response", None) or response
    status = getattr(candidate, "status_code", None)
    headers = getattr(candidate, "headers", None)
    return (
        int(status) if isinstance(status, int) or str(status or "").isdigit() else None,
        headers if isinstance(headers, Mapping) else {},
    )


__all__ = [
    "TWSE_MIS_PROVIDER_GUARD",
    "TwseMisAttemptToken",
    "TwseMisGuardDecision",
    "TwseMisProviderGuard",
    "parse_retry_after_seconds",
    "response_failure_metadata",
]
