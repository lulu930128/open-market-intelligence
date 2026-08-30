from __future__ import annotations

from datetime import datetime, timezone

from app.market.providers.twse_mis_guard import (
    TwseMisProviderGuard,
    parse_retry_after_seconds,
)


class MutableTime:
    def __init__(self) -> None:
        self.seconds = 100.0
        self.wall = datetime(2026, 8, 30, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.seconds

    def clock(self) -> datetime:
        return self.wall

    def advance(self, seconds: int) -> None:
        self.seconds += seconds
        self.wall = datetime.fromtimestamp(
            self.wall.timestamp() + seconds,
            tz=timezone.utc,
        )


def test_rate_limit_opens_provider_wide_cooldown_and_allows_one_probe() -> None:
    current = MutableTime()
    guard = TwseMisProviderGuard(
        rate_limit_cooldown_seconds=10,
        monotonic=current.monotonic,
        clock=current.clock,
    )

    request = guard.before_request()
    assert request.attempt is not None
    opened = guard.record_http_failure(
        request.attempt,
        429,
        headers={"Retry-After": "30"},
    )
    assert opened.status == "rate_limited"
    assert opened.retry_after_seconds == 30
    assert not guard.before_request().allowed

    current.advance(30)
    probe = guard.before_request()
    assert probe.allowed
    assert probe.probe
    assert not guard.before_request().allowed
    assert guard.before_request().detail_code == "TWSE_MIS_RECOVERY_PROBE_IN_FLIGHT"

    assert probe.attempt is not None
    guard.record_success(probe.attempt)
    assert guard.before_request().allowed
    assert guard.snapshot().status == "healthy"


def test_transport_failures_open_only_after_threshold() -> None:
    current = MutableTime()
    guard = TwseMisProviderGuard(
        failure_threshold=2,
        failure_cooldown_seconds=9,
        monotonic=current.monotonic,
        clock=current.clock,
    )

    first_request = guard.before_request()
    assert first_request.attempt is not None
    first = guard.record_failure(
        first_request.attempt,
        detail_code="NETWORK_TIMEOUT",
    )
    assert first.allowed
    second_request = guard.before_request()
    assert second_request.allowed
    assert second_request.attempt is not None

    second = guard.record_failure(
        second_request.attempt,
        detail_code="NETWORK_TIMEOUT",
    )
    assert not second.allowed
    assert second.retry_after_seconds == 9
    assert not guard.before_request().allowed


def test_older_success_cannot_clear_newer_rate_limit_cooldown() -> None:
    current = MutableTime()
    guard = TwseMisProviderGuard(
        rate_limit_cooldown_seconds=20,
        monotonic=current.monotonic,
        clock=current.clock,
    )

    older = guard.before_request()
    newer = guard.before_request()
    assert older.attempt is not None
    assert newer.attempt is not None

    opened = guard.record_http_failure(newer.attempt, 429)
    stale_success = guard.record_success(older.attempt)

    assert opened.status == "rate_limited"
    assert stale_success.status == "rate_limited"
    assert not stale_success.allowed
    assert not guard.before_request().allowed


def test_only_current_recovery_probe_can_clear_cooldown() -> None:
    current = MutableTime()
    guard = TwseMisProviderGuard(
        rate_limit_cooldown_seconds=5,
        monotonic=current.monotonic,
        clock=current.clock,
    )

    stale = guard.before_request()
    limiter = guard.before_request()
    assert stale.attempt is not None
    assert limiter.attempt is not None
    guard.record_http_failure(limiter.attempt, 429)

    current.advance(5)
    probe = guard.before_request()
    assert probe.probe
    assert probe.attempt is not None
    assert not guard.record_success(stale.attempt).allowed
    assert guard.record_success(probe.attempt).allowed
    assert guard.snapshot().status == "healthy"


def test_cancelled_probe_releases_probe_slot_without_clearing_cooldown() -> None:
    current = MutableTime()
    guard = TwseMisProviderGuard(
        rate_limit_cooldown_seconds=5,
        monotonic=current.monotonic,
        clock=current.clock,
    )

    limiter = guard.before_request()
    assert limiter.attempt is not None
    guard.record_http_failure(limiter.attempt, 429)
    current.advance(5)

    probe = guard.before_request()
    assert probe.attempt is not None
    cancelled = guard.cancel_attempt(probe.attempt)
    next_probe = guard.before_request()

    assert cancelled.status == "rate_limited"
    assert next_probe.allowed
    assert next_probe.probe


def test_retry_after_parser_accepts_delta_and_rejects_malformed() -> None:
    assert parse_retry_after_seconds({"retry-after": "12"}) == 12
    assert parse_retry_after_seconds({"Retry-After": "invalid"}) is None
    assert parse_retry_after_seconds({}) is None
