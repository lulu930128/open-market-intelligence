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

    opened = guard.record_http_failure(429, headers={"Retry-After": "30"})
    assert opened.status == "rate_limited"
    assert opened.retry_after_seconds == 30
    assert not guard.before_request().allowed

    current.advance(30)
    probe = guard.before_request()
    assert probe.allowed
    assert probe.probe
    assert not guard.before_request().allowed
    assert guard.before_request().detail_code == "TWSE_MIS_RECOVERY_PROBE_IN_FLIGHT"

    guard.record_success()
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

    first = guard.record_failure(detail_code="NETWORK_TIMEOUT")
    assert first.allowed
    assert guard.before_request().allowed

    second = guard.record_failure(detail_code="NETWORK_TIMEOUT")
    assert not second.allowed
    assert second.retry_after_seconds == 9
    assert not guard.before_request().allowed


def test_retry_after_parser_accepts_delta_and_rejects_malformed() -> None:
    assert parse_retry_after_seconds({"retry-after": "12"}) == 12
    assert parse_retry_after_seconds({"Retry-After": "invalid"}) is None
    assert parse_retry_after_seconds({}) is None
