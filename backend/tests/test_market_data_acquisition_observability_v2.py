from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.market_data.acquisition_observability import (
    AcquisitionDiagnostic,
    ProviderAttemptDiagnostic,
    build_acquisition_diagnostic,
)
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
from market_data_fakes import FakeClock, FakeLeaseProvider, fixed_id_factory


NOW = datetime(2026, 8, 21, 9, 5, tzinfo=timezone(timedelta(hours=8)))


def _requirement() -> DataRequirement:
    return DataRequirement(
        instrument=InstrumentKey(
            market=Market.TW,
            symbol="2330",
            instrument_type=InstrumentType.STOCK,
            venue="TWSE",
        ),
        capability_id="quote.snapshot",
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        purpose=DataPurpose.RESEARCH,
        session=MarketSession.CONTINUOUS,
        instrument_tradability=InstrumentTradability.TRADABLE,
        requested_at=NOW,
        max_age_seconds=15,
    )


def _descriptor(key: str, priority: int = 0) -> ProviderDescriptor:
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


def _health(
    key: str,
    *,
    operational: OperationalStatus = OperationalStatus.HEALTHY,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=key,
        market=Market.TW,
        capability="quote.snapshot",
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=operational,
        freshness=EvidenceFreshness.LIVE,
        checked_at=NOW,
    )


def _attempt(provider: str, *, limitation: str | None = None) -> ProviderAttemptResult:
    instrument = _requirement().instrument
    quote = QuoteObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=provider,
            source=f"{provider}.quote",
            authority=AuthorityClass.BROKER,
            event_at=NOW,
            received_at=NOW,
        ),
        last_trade_price=Decimal("100"),
    )
    return ProviderAttemptResult(
        outcome=AcquisitionOutcome.ACQUIRED,
        acquisition=AcquisitionResult(
            snapshots=(CanonicalMarketSnapshot(instrument=instrument, quote=quote),),
            external_calls=1,
            subscriptions_created=1,
            limitations=((limitation,) if limitation else ()),
        ),
        detail_code="CANDIDATE_PRODUCED",
    )


def _ids():
    return fixed_id_factory([f"id-{index:04d}" for index in range(10)])


def test_diagnostic_exposes_attempt_cleanup_counts_without_observations() -> None:
    clock = FakeClock()
    requirement = _requirement()
    descriptors = [_descriptor("fake_a", 0), _descriptor("fake_b", 1)]
    plan = plan_acquisition(
        requirement,
        descriptors,
        {item.provider_key: _health(item.provider_key) for item in descriptors},
    )
    result = execute_acquisition(
        requirement,
        plan,
        {
            "fake_a": FakeLeaseProvider(clock=clock, result=_attempt("fake_a")),
            "fake_b": FakeLeaseProvider(clock=clock, result=_attempt("fake_b")),
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    diagnostic = build_acquisition_diagnostic(plan, result)
    payload = diagnostic.model_dump(mode="json")
    assert diagnostic.target == "TW:2330"
    assert diagnostic.logical_attempt_count == 2
    assert diagnostic.candidate_count == 2
    assert diagnostic.released_attempt_count == 2
    assert diagnostic.cleanup_failed_attempt_count == 0
    assert diagnostic.additional_route_attempted is True
    assert "candidates" not in payload
    assert "acquisition_result" not in payload["attempts"][0]
    assert "provider_health" not in payload
    assert "selected_provider" not in payload
    assert "selection_reason" not in payload


def test_skipped_provider_reason_is_visible_without_attempting_it() -> None:
    requirement = _requirement()
    descriptors = [_descriptor("fake_disabled"), _descriptor("fake_ready", 1)]
    plan = plan_acquisition(
        requirement,
        descriptors,
        {
            "fake_disabled": ProviderResourceHealth(
                **_health("fake_disabled").model_dump(exclude={"enablement"}),
                enablement=EnablementStatus.DISABLED,
            ),
            "fake_ready": _health("fake_ready"),
        },
    )
    clock = FakeClock()
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_ready": FakeLeaseProvider(clock=clock, result=_attempt("fake_ready"))},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    diagnostic = build_acquisition_diagnostic(plan, result)
    assert diagnostic.skipped_providers[0].provider_key == "fake_disabled"
    assert diagnostic.skipped_providers[0].reason_code == "PROVIDER_DISABLED"


def test_exception_and_secret_like_port_limitation_are_not_serialized() -> None:
    clock = FakeClock()
    requirement = _requirement()
    descriptors = [_descriptor("fake_broken", 0), _descriptor("fake_secret", 1)]
    plan = plan_acquisition(
        requirement,
        descriptors,
        {item.provider_key: _health(item.provider_key) for item in descriptors},
    )
    result = execute_acquisition(
        requirement,
        plan,
        {
            "fake_broken": FakeLeaseProvider(
                clock=clock,
                result=_attempt("fake_broken"),
                raise_on_poll=True,
            ),
            "fake_secret": FakeLeaseProvider(
                clock=clock,
                result=_attempt(
                    "fake_secret",
                    limitation="PASSWORD=never-serialize-this",
                ),
            ),
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    payload = build_acquisition_diagnostic(plan, result).model_dump_json().lower()
    assert "password" not in payload
    assert "never-serialize" not in payload
    assert "provider secret" not in payload
    assert "provider_poll_failed" in payload
    assert "provider_limitation_reported" in payload


def test_unknown_activity_counts_remain_null() -> None:
    clock = FakeClock()
    requirement = _requirement()
    descriptor = _descriptor("fake_start_failure")
    plan = plan_acquisition(
        requirement,
        [descriptor],
        {descriptor.provider_key: _health(descriptor.provider_key)},
    )
    result = execute_acquisition(
        requirement,
        plan,
        {
            descriptor.provider_key: FakeLeaseProvider(
                clock=clock,
                result=_attempt(descriptor.provider_key),
                raise_on_start=True,
            )
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    diagnostic = build_acquisition_diagnostic(plan, result)
    assert diagnostic.external_calls is None
    assert diagnostic.subscriptions_created is None
    assert diagnostic.attempts[0].external_calls is None
    assert diagnostic.port_start_count == 1


def test_cleanup_failure_is_visible_and_never_reported_as_released() -> None:
    clock = FakeClock()
    requirement = _requirement()
    descriptor = _descriptor("fake_cleanup_failure")
    plan = plan_acquisition(
        requirement,
        [descriptor],
        {descriptor.provider_key: _health(descriptor.provider_key)},
    )
    result = execute_acquisition(
        requirement,
        plan,
        {
            descriptor.provider_key: FakeLeaseProvider(
                clock=clock,
                result=_attempt(descriptor.provider_key),
                raise_on_release=True,
            )
        },
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    diagnostic = build_acquisition_diagnostic(plan, result)
    assert diagnostic.released_attempt_count == 0
    assert diagnostic.cleanup_failed_attempt_count == 1
    assert diagnostic.active_handles_after == 1


def test_allowlist_models_reject_raw_payload_and_oversized_detail() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProviderAttemptDiagnostic(
            provider_key="fake_a",
            outcome=AcquisitionOutcome.FAILED,
            cleanup_status=CleanupStatus.NOT_REQUIRED,
            detail_code="PROVIDER_FAILED",
            port_started=False,
            candidate_count=0,
            elapsed_seconds=0,
            raw_payload={"token": "secret"},
        )
    with pytest.raises(ValidationError):
        ProviderAttemptDiagnostic(
            provider_key="fake_a",
            outcome=AcquisitionOutcome.FAILED,
            cleanup_status=CleanupStatus.NOT_REQUIRED,
            detail_code="X" * 65,
            port_started=False,
            candidate_count=0,
            elapsed_seconds=0,
        )
    assert "raw_payload" not in AcquisitionDiagnostic.model_fields


def test_diagnostic_projection_failure_happens_after_owned_cleanup() -> None:
    clock = FakeClock()
    requirement = _requirement()
    descriptor = _descriptor("fake_ready")
    plan = plan_acquisition(
        requirement,
        [descriptor],
        {descriptor.provider_key: _health(descriptor.provider_key)},
    )
    provider = FakeLeaseProvider(clock=clock, result=_attempt("fake_ready"))
    result = execute_acquisition(
        requirement,
        plan,
        {"fake_ready": provider},
        clock=clock,
        wait=clock.wait,
        id_factory=_ids(),
    )
    mismatched_requirement = requirement.model_copy(update={"max_age_seconds": 30})
    mismatched_plan = plan.model_copy(update={"requirement": mismatched_requirement})
    with pytest.raises(ValueError, match="do not match"):
        build_acquisition_diagnostic(mismatched_plan, result)
    assert provider.active_handles == 0
    assert provider.release_count == 1
