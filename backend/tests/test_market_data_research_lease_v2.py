from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    AuthorityClass,
    CanonicalMarketSnapshot,
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    QuoteObservation,
    SourceLineage,
)
from app.market_data.policies import AcquisitionResult, DataPurpose, DataRequirement, RealtimePolicy
from app.market_data.provider_policy import ProviderRoute
from app.market_data.research_lease import (
    AcquisitionAttemptContext,
    AcquisitionOutcome,
    CleanupStatus,
    ProviderAttemptResult,
    ResearchLeaseRunner,
)
from market_data_fakes import (
    CancellingWaiter,
    FakeClock,
    FakeLeaseProvider,
    MutableCancellationToken,
)


NOW = datetime(2026, 8, 21, 9, 5, tzinfo=timezone(timedelta(hours=8)))


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _requirement() -> DataRequirement:
    return DataRequirement(
        instrument=_instrument(),
        capability_id="quote.snapshot",
        realtime_policy=RealtimePolicy.REQUIRE_LIVE,
        purpose=DataPurpose.RESEARCH,
        session=MarketSession.CONTINUOUS,
        instrument_tradability=InstrumentTradability.TRADABLE,
        requested_at=NOW,
        max_age_seconds=15,
    )


def _route(key: str = "fake_primary", timeout: float = 2.0) -> ProviderRoute:
    return ProviderRoute(
        provider_key=key,
        market=Market.TW,
        capability_id="quote.snapshot",
        priority=0,
        external_fetch_allowed=True,
        subscription_allowed=True,
        route_timeout_seconds=timeout,
    )


def _context(
    clock: FakeClock,
    *,
    owner: str = "owner-token-0001",
    deadline_after: float = 2.0,
    key: str = "fake_primary",
) -> AcquisitionAttemptContext:
    return AcquisitionAttemptContext(
        request_id="request-1",
        owner_token=owner,
        requirement=_requirement(),
        route=_route(key),
        started_at_monotonic=clock(),
        absolute_deadline_monotonic=clock() + deadline_after,
    )


def _acquired_result(
    *,
    external_calls: int = 1,
    subscriptions_created: int = 1,
    limitations: tuple[str, ...] = (),
) -> ProviderAttemptResult:
    quote = QuoteObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider="fake_primary",
            source="fake.quote",
            authority=AuthorityClass.BROKER,
            event_at=NOW,
            received_at=NOW,
        ),
        last_trade_price=Decimal("100"),
    )
    return ProviderAttemptResult(
        outcome=AcquisitionOutcome.ACQUIRED,
        acquisition=AcquisitionResult(
            snapshots=(CanonicalMarketSnapshot(instrument=_instrument(), quote=quote),),
            external_calls=external_calls,
            subscriptions_created=subscriptions_created,
            limitations=limitations,
        ),
        detail_code="CANDIDATE_PRODUCED",
    )


def _empty_result(outcome: AcquisitionOutcome) -> ProviderAttemptResult:
    return ProviderAttemptResult(
        outcome=outcome,
        acquisition=AcquisitionResult(external_calls=1),
        detail_code=(
            "PROVIDER_UNAVAILABLE"
            if outcome is AcquisitionOutcome.UNAVAILABLE
            else "PROVIDER_FAILED"
        ),
    )


def test_success_preserves_outcome_and_releases_owned_handle() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(clock=clock, result=_acquired_result())
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.ACQUIRED
    assert result.cleanup_status is CleanupStatus.RELEASED
    assert result.acquisition_result is not None
    assert result.external_calls == 1
    assert result.subscriptions_created == 1
    assert result.active_after_cleanup is False
    assert provider.active_handles == 0
    assert provider.release_count == 1


def test_unavailable_is_not_coerced_to_success_and_still_cleans_up() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_empty_result(AcquisitionOutcome.UNAVAILABLE),
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.UNAVAILABLE
    assert result.cleanup_status is CleanupStatus.RELEASED
    assert result.acquisition_result is not None
    assert result.acquisition_result.snapshots == ()
    assert provider.active_handles == 0


def test_timeout_cooperatively_cancels_releases_and_blocks_late_callback() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(),
        ready_after_seconds=10,
    )
    result = ResearchLeaseRunner(poll_interval_seconds=0.1).run(
        provider,
        _context(clock, deadline_after=0.3),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.TIMED_OUT
    assert result.cleanup_status is CleanupStatus.RELEASED
    assert provider.cancel_count == 1
    assert provider.release_count == 1
    assert provider.active_handles == 0
    assert provider.handles[0].terminal is True
    clock.advance(20)
    assert provider.handles[0].late_callback() is False


def test_caller_cancellation_is_cooperative_and_terminal() -> None:
    clock = FakeClock()
    token = MutableCancellationToken()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(),
        ready_after_seconds=10,
    )
    waiter = CancellingWaiter(clock, token, cancel_at=clock() + 0.2)
    result = ResearchLeaseRunner(poll_interval_seconds=0.1).run(
        provider,
        _context(clock, deadline_after=1),
        cancellation=token,
        clock=clock,
        wait=waiter,
    )
    assert result.outcome is AcquisitionOutcome.CANCELLED
    assert result.cleanup_status is CleanupStatus.RELEASED
    assert provider.cancel_count == 1
    assert provider.active_handles == 0


@pytest.mark.parametrize(
    ("provider_kwargs", "detail_code"),
    [
        ({"raise_on_start": True}, "PORT_START_FAILED"),
        ({"raise_on_poll": True}, "PROVIDER_POLL_FAILED"),
        ({"terminal_without_result": True}, "TERMINAL_WITHOUT_RESULT"),
    ],
)
def test_provider_failures_are_classified_without_exception_text(
    provider_kwargs: dict[str, bool],
    detail_code: str,
) -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(),
        **provider_kwargs,
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.detail_code == detail_code
    assert "secret" not in result.model_dump_json().lower()
    if provider_kwargs.get("raise_on_start"):
        assert result.cleanup_status is CleanupStatus.NOT_REQUIRED
        assert result.external_calls is None
        assert result.port_started is True
    else:
        assert result.cleanup_status is CleanupStatus.RELEASED
        assert provider.active_handles == 0


def test_cleanup_failure_remains_visible_and_does_not_overwrite_outcome() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(),
        raise_on_release=True,
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.ACQUIRED
    assert result.cleanup_status is CleanupStatus.CLEANUP_FAILED
    assert result.active_after_cleanup is True
    assert "RELEASE_FAILED" in result.limitations


def test_release_is_idempotent_without_double_decrement() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(clock=clock, result=_acquired_result())
    handle = provider.start(_context(clock))
    first = handle.release()
    second = handle.release()
    assert first.status is CleanupStatus.RELEASED
    assert second.detail_code == "ALREADY_RELEASED"
    assert provider.release_count == 1
    assert provider.active_handles == 0


def test_one_hundred_sequential_runs_restore_baseline() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(clock=clock, result=_acquired_result())
    runner = ResearchLeaseRunner()
    for index in range(100):
        result = runner.run(
            provider,
            _context(clock, owner=f"owner-token-{index:04d}"),
            clock=clock,
            wait=clock.wait,
        )
        assert result.cleanup_status is CleanupStatus.RELEASED
    assert provider.start_count == 100
    assert provider.release_count == 100
    assert provider.active_handles == 0


def test_parallel_handles_are_owner_isolated() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(clock=clock, result=_acquired_result())
    handle_a = provider.start(_context(clock, owner="owner-token-a001"))
    handle_b = provider.start(_context(clock, owner="owner-token-b001"))
    assert provider.active_handles == 2
    handle_a.release()
    assert provider.active_handles == 1
    assert handle_b.active is True
    handle_b.release()
    assert provider.active_handles == 0


def test_owner_mismatch_fails_closed_without_releasing_unknown_handle() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(),
        override_owner_token="different-owner-token",
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.cleanup_status is CleanupStatus.CLEANUP_FAILED
    assert result.detail_code == "OWNER_TOKEN_MISMATCH"
    assert provider.release_count == 0
    assert provider.active_handles == 1


def test_activity_count_mismatch_fails_closed() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(external_calls=1),
        external_calls=2,
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.detail_code == "ACTIVITY_COUNT_MISMATCH"
    assert result.acquisition_result is None
    assert result.cleanup_status is CleanupStatus.RELEASED


def test_provider_limitations_are_not_copied_as_untrusted_diagnostics() -> None:
    clock = FakeClock()
    provider = FakeLeaseProvider(
        clock=clock,
        result=_acquired_result(limitations=("PASSWORD=do-not-serialize",)),
    )
    result = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        clock=clock,
        wait=clock.wait,
    )
    assert result.limitations == ("PROVIDER_LIMITATION_REPORTED",)
    assert "password" not in str(result.limitations).lower()


def test_pre_start_cancellation_and_timeout_do_not_call_port() -> None:
    clock = FakeClock()
    token = MutableCancellationToken()
    token.cancel()
    provider = FakeLeaseProvider(clock=clock, result=_acquired_result())
    cancelled = ResearchLeaseRunner().run(
        provider,
        _context(clock),
        cancellation=token,
        clock=clock,
        wait=clock.wait,
    )
    assert cancelled.outcome is AcquisitionOutcome.CANCELLED
    assert cancelled.external_calls == 0
    assert provider.start_count == 0

    expired_context = AcquisitionAttemptContext(
        **_context(clock).model_dump(exclude={"absolute_deadline_monotonic"}),
        absolute_deadline_monotonic=clock() + 0.1,
    )
    clock.advance(0.1)
    timed_out = ResearchLeaseRunner().run(
        provider,
        expired_context,
        clock=clock,
        wait=clock.wait,
    )
    assert timed_out.outcome is AcquisitionOutcome.TIMED_OUT
    assert provider.start_count == 0


def test_provider_result_contract_rejects_empty_success_and_runner_outcome() -> None:
    with pytest.raises(ValidationError, match="requires canonical snapshots"):
        ProviderAttemptResult(
            outcome=AcquisitionOutcome.ACQUIRED,
            acquisition=AcquisitionResult(),
            detail_code="EMPTY_SUCCESS",
        )
    with pytest.raises(ValidationError, match="runner-owned outcome"):
        ProviderAttemptResult(
            outcome=AcquisitionOutcome.TIMED_OUT,
            acquisition=AcquisitionResult(),
            detail_code="INVALID_OWNER",
        )
