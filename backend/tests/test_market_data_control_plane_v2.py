from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.contracts import (
    AuthorityClass,
    CanonicalMarketSnapshot,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
    QuoteObservation,
    SourceLineage,
)
from app.market_data.control_plane import execute_acquisition
from app.market_data.policies import AcquisitionResult, DataPurpose, DataRequirement, RealtimePolicy
from app.market_data.provider_policy import ProviderDescriptor, plan_acquisition
from app.market_data.research_lease import AcquisitionOutcome, CleanupStatus, ProviderAttemptResult
from market_data_fakes import (
    CancellingWaiter,
    FakeClock,
    FakeLeaseProvider,
    MutableCancellationToken,
    fixed_id_factory,
)


NOW = datetime(2026, 8, 21, 9, 5, tzinfo=timezone(timedelta(hours=8)))


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _requirement(
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    *,
    max_candidates: int = 8,
) -> DataRequirement:
    return DataRequirement(
        instrument=_instrument(),
        capability_id="quote.snapshot",
        realtime_policy=policy,
        purpose=DataPurpose.RESEARCH,
        session=MarketSession.CONTINUOUS,
        instrument_tradability=InstrumentTradability.TRADABLE,
        requested_at=NOW,
        max_age_seconds=15,
        max_candidates=max_candidates,
    )


def _descriptor(key: str, priority: int) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_key=key,
        market=Market.TW,
        capabilities=("quote.snapshot",),
        priority=priority,
        supports_external_fetch=True,
        supports_live_subscription=True,
        can_produce_live=True,
        max_timeout_seconds=0.5,
    )


def _health(key: str) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=key,
        market=Market.TW,
        capability="quote.snapshot",
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.LIVE,
        checked_at=NOW,
    )


def _snapshot(provider: str, price: str) -> CanonicalMarketSnapshot:
    quote = QuoteObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider=provider,
            source=f"{provider}.quote",
            authority=AuthorityClass.BROKER,
            event_at=NOW,
            received_at=NOW,
        ),
        last_trade_price=Decimal(price),
    )
    return CanonicalMarketSnapshot(instrument=_instrument(), quote=quote)


def _attempt_result(
    provider: str,
    *,
    outcome: AcquisitionOutcome = AcquisitionOutcome.ACQUIRED,
    price: str = "100",
    external_calls: int = 1,
    subscriptions: int = 1,
    snapshot_count: int = 1,
) -> ProviderAttemptResult:
    snapshots = (
        tuple(_snapshot(provider, str(Decimal(price) + index)) for index in range(snapshot_count))
        if outcome is AcquisitionOutcome.ACQUIRED
        else ()
    )
    return ProviderAttemptResult(
        outcome=outcome,
        acquisition=AcquisitionResult(
            snapshots=snapshots,
            external_calls=external_calls,
            subscriptions_created=subscriptions,
        ),
        detail_code=(
            "CANDIDATE_PRODUCED"
            if outcome is AcquisitionOutcome.ACQUIRED
            else "PROVIDER_UNAVAILABLE"
        ),
    )


def _plan(
    requirement: DataRequirement,
    keys: tuple[str, ...],
    **kwargs: object,
):
    descriptors = [_descriptor(key, index) for index, key in enumerate(keys)]
    health = {key: _health(key) for key in keys}
    return plan_acquisition(requirement, descriptors, health, **kwargs)


def _ids(count: int = 10):
    return fixed_id_factory([f"id-{index:04d}" for index in range(count)])


def test_collects_bounded_candidates_without_claiming_final_selection() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_primary", "fake_secondary"))
    primary = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_primary", price="100"),
    )
    secondary = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_secondary", price="101"),
    )
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_primary": primary, "fake_secondary": secondary},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.ACQUIRED
    assert [item.quote.lineage.provider for item in result.candidates if item.quote] == [
        "fake_primary",
        "fake_secondary",
    ]
    assert primary.start_count == secondary.start_count == 1
    assert result.active_handles_after == 0
    assert "selected_provider" not in type(result).model_fields
    assert "selection_reason" not in type(result).model_fields


def test_unavailable_and_timeout_fall_back_after_cleanup() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_unavailable", "fake_slow", "fake_success"))
    unavailable = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result(
            "fake_unavailable",
            outcome=AcquisitionOutcome.UNAVAILABLE,
            subscriptions=0,
        ),
    )
    slow = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_slow"),
        ready_after_seconds=10,
    )
    success = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_success", price="102"),
    )
    result = execute_acquisition(
        requirement,
        plan,
        {
            "fake_unavailable": unavailable,
            "fake_slow": slow,
            "fake_success": success,
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert [item.outcome for item in result.attempts] == [
        AcquisitionOutcome.UNAVAILABLE,
        AcquisitionOutcome.TIMED_OUT,
        AcquisitionOutcome.ACQUIRED,
    ]
    assert all(item.cleanup_status is CleanupStatus.RELEASED for item in result.attempts)
    assert unavailable.active_handles == slow.active_handles == success.active_handles == 0


def test_provider_exception_is_classified_then_bounded_fallback_continues() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_broken", "fake_success"))
    broken = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_broken"),
        raise_on_poll=True,
    )
    success = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_success"),
    )
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_broken": broken, "fake_success": success},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.ACQUIRED
    assert result.attempts[0].detail_code == "PROVIDER_POLL_FAILED"
    assert result.attempts[0].cleanup_status is CleanupStatus.RELEASED
    assert success.start_count == 1


def test_cancellation_stops_next_provider_and_cleans_current() -> None:
    clock = FakeClock()
    token = MutableCancellationToken()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_slow", "fake_never"))
    slow = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_slow"),
        ready_after_seconds=10,
    )
    never = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_never"),
    )
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_slow": slow, "fake_never": never},
        cancellation=token,
        clock=clock,
        wait=CancellingWaiter(clock, token, cancel_at=clock() + 0.2),
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.CANCELLED
    assert len(result.attempts) == 1
    assert slow.active_handles == 0
    assert never.start_count == 0


@pytest.mark.parametrize(
    "policy",
    [RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION],
)
def test_zero_io_policy_never_calls_ports(policy: RealtimePolicy) -> None:
    clock = FakeClock()
    requirement = _requirement(policy)
    plan = plan_acquisition(requirement, [], {})
    provider = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_unused"))
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_unused": provider},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.NOT_REQUIRED
    assert result.logical_attempt_count == 0
    assert result.external_calls == result.subscriptions_created == 0
    assert provider.start_count == 0


def test_missing_port_is_truthful_and_fallback_can_continue() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_missing", "fake_success"))
    success = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_success"))
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_success": success},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.attempts[0].detail_code == "PORT_NOT_REGISTERED"
    assert result.attempts[0].port_started is False
    assert result.outcome is AcquisitionOutcome.ACQUIRED
    assert success.start_count == 1


def test_attempt_and_physical_activity_budgets_fail_closed() -> None:
    clock = FakeClock()
    requirement = _requirement()
    bounded_plan = _plan(
        requirement,
        ("fake_0", "fake_1", "fake_2"),
        max_provider_attempts=2,
    )
    ports = {
        key: FakeLeaseProvider(clock=clock, result=_attempt_result(key))
        for key in ("fake_0", "fake_1", "fake_2")
    }
    bounded = execute_acquisition(
        requirement,
        bounded_plan,
        ports,
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert bounded.logical_attempt_count == 2
    assert ports["fake_2"].start_count == 0

    overflow_plan = _plan(
        requirement,
        ("fake_overflow", "fake_never"),
        max_external_calls=1,
    )
    overflow = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_overflow", external_calls=2, subscriptions=0),
    )
    never = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_never"))
    failed = execute_acquisition(
        requirement,
        overflow_plan,
        {"fake_overflow": overflow, "fake_never": never},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert failed.outcome is AcquisitionOutcome.FAILED
    assert "EXTERNAL_CALL_BUDGET_EXCEEDED" in failed.limitations
    assert never.start_count == 0
    assert overflow.active_handles == 0

    subscription_plan = _plan(
        requirement,
        ("fake_subscription_overflow", "fake_subscription_never"),
        max_subscriptions=0,
    )
    subscription_overflow = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result(
            "fake_subscription_overflow",
            external_calls=0,
            subscriptions=1,
        ),
    )
    subscription_never = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_subscription_never"),
    )
    subscription_failed = execute_acquisition(
        requirement,
        subscription_plan,
        {
            "fake_subscription_overflow": subscription_overflow,
            "fake_subscription_never": subscription_never,
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert subscription_failed.outcome is AcquisitionOutcome.FAILED
    assert "SUBSCRIPTION_BUDGET_EXCEEDED" in subscription_failed.limitations
    assert subscription_never.start_count == 0
    assert subscription_overflow.active_handles == 0


def test_route_deadline_is_clamped_to_shorter_overall_remaining_budget() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(
        requirement,
        ("fake_slow", "fake_never"),
        overall_timeout_seconds=0.2,
    )
    slow = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_slow"),
        ready_after_seconds=10,
    )
    never = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_never"))
    started_at = clock()
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_slow": slow, "fake_never": never},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.TIMED_OUT
    assert result.attempts[0].elapsed_seconds == pytest.approx(0.2)
    assert clock() - started_at == pytest.approx(0.2)
    assert never.start_count == 0
    assert slow.active_handles == 0


def test_candidate_bound_violation_does_not_partially_merge_snapshot_batch() -> None:
    clock = FakeClock()
    requirement = _requirement(max_candidates=1)
    plan = _plan(requirement, ("fake_overflow",))
    provider = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_overflow", snapshot_count=2),
    )
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_overflow": provider},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.candidates == ()
    assert "PORT_CANDIDATE_BOUND_EXCEEDED" in result.limitations


def test_cleanup_failure_stops_fallback_instead_of_hiding_leak() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_leak", "fake_never"))
    leak = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_leak"),
        raise_on_release=True,
    )
    never = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_never"))
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_leak": leak, "fake_never": never},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.active_handles_after == 1
    assert "CLEANUP_INVARIANT_FAILED" in result.limitations
    assert never.start_count == 0


def test_all_unavailable_stays_unavailable() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_a", "fake_b"))
    ports = {
        key: FakeLeaseProvider(
            clock=clock,
            result=_attempt_result(
                key,
                outcome=AcquisitionOutcome.UNAVAILABLE,
                subscriptions=0,
            ),
        )
        for key in ("fake_a", "fake_b")
    }
    result = execute_acquisition(
        requirement,
        plan,
        ports,
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.UNAVAILABLE
    assert result.candidates == ()
    assert result.active_handles_after == 0


def test_start_failure_keeps_unknown_activity_counts_truthful() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_broken",))
    provider = FakeLeaseProvider(
        clock=clock,
        result=_attempt_result("fake_broken"),
        raise_on_start=True,
    )
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_broken": provider},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.outcome is AcquisitionOutcome.FAILED
    assert result.external_calls is None
    assert result.subscriptions_created is None
    assert "ACTIVITY_COUNT_UNKNOWN" in result.limitations


def test_plan_requirement_mismatch_is_rejected_before_port_call() -> None:
    clock = FakeClock()
    requirement = _requirement()
    other = requirement.model_copy(update={"max_age_seconds": 30})
    plan = _plan(other, ("fake_primary",))
    provider = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_primary"))
    with pytest.raises(ValueError, match="does not match"):
        execute_acquisition(
            requirement,
            plan,
            {"fake_primary": provider},
            clock=clock,
            wait=clock.wait,
            id_factory=_ids(),
        )
    assert provider.start_count == 0


def test_downstream_resolver_failure_cannot_leak_already_released_handle() -> None:
    clock = FakeClock()
    requirement = _requirement()
    plan = _plan(requirement, ("fake_primary",))
    provider = FakeLeaseProvider(clock=clock, result=_attempt_result("fake_primary"))
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_primary": provider},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    assert result.active_handles_after == 0
    with pytest.raises(RuntimeError, match="downstream"):
        raise RuntimeError("downstream resolver failed")
    assert provider.active_handles == 0
    assert provider.release_count == 1
