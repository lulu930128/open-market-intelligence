from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    AuthorityClass,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    DatasetTarget,
    FreshnessRequirement,
    InstrumentTarget,
    RefreshRequirementV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
    plan_data_acquisition_v2,
    plan_refresh_acquisition_v1,
)


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 21, 14, 0, tzinfo=TAIPEI)


def _requirement(
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    *,
    venue: str = "TWSE",
    interval: str = "1d",
    max_attempts: int = 2,
    max_calls: int = 2,
    max_subscriptions: int = 0,
) -> DataRequirementV2:
    zero_io = policy in {RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION}
    return DataRequirementV2(
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="2330",
                instrument_type=InstrumentType.STOCK,
                venue=venue,
            )
        ),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval=interval,
            start_at=datetime(2026, 8, 1, 9, tzinfo=TAIPEI),
            end_at=datetime(2026, 8, 21, 13, 30, tzinfo=TAIPEI),
            max_bars=21,
            completed_only=policy is RealtimePolicy.COMPLETED_SESSION,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=policy,
        session=MarketSession.CLOSED,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=86_400),
        bounds=RequestBounds(
            max_provider_attempts=0 if zero_io else max_attempts,
            max_external_calls=0 if zero_io else max_calls,
            max_subscriptions=0 if zero_io else max_subscriptions,
            timeout_seconds=30,
            max_rows=100,
        ),
    )


def _descriptor(
    provider: str,
    resource: str,
    *,
    priority: int = 100,
    venue_scope: tuple[str, ...] = ("TWSE",),
    modes: tuple[AcquisitionMode, ...] = (AcquisitionMode.FETCH,),
    live: bool = False,
    allow_unknown_health: bool = False,
) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key=provider,
        market=Market.TW,
        capability_id="daily.ohlcv",
        resource_id=resource,
        authority=AuthorityClass.EXCHANGE,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,),
        venue_scope=venue_scope,
        instrument_types=(InstrumentType.STOCK,),
        intervals=("1d",),
        supported_sessions=(MarketSession.CLOSED,),
        acquisition_modes=modes,
        priority=priority,
        can_produce_live=live,
        can_produce_final=True,
        max_external_calls_per_attempt=1 if AcquisitionMode.FETCH in modes else 0,
        max_subscriptions_per_attempt=1 if AcquisitionMode.SUBSCRIPTION in modes else 0,
        max_range_days=366,
        allow_unknown_health=allow_unknown_health,
    )


def _health(
    provider: str,
    *,
    operational: OperationalStatus = OperationalStatus.HEALTHY,
    connection: ConnectionStatus = ConnectionStatus.CONNECTED,
    checked_at: datetime = NOW,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=provider,
        market=Market.TW,
        capability="daily.ohlcv",
        enablement=EnablementStatus.ENABLED,
        connection=connection,
        entitlement=EntitlementStatus.ENTITLED,
        operational=operational,
        freshness=EvidenceFreshness.FRESH,
        checked_at=checked_at,
    )


def _refresh() -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv.official",
        target=DatasetTarget(
            market=Market.TW,
            dataset_id="tw.daily.ohlcv.official",
            scope_key="TWSE",
        ),
        from_date=date(2026, 8, 21),
        to_date=date(2026, 8, 21),
        requested_at=NOW,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=2,
        max_external_calls=2,
        timeout_seconds=60,
        max_symbols=500,
        max_range_days=1,
        postcondition="Persisted official daily rows are reread and resolved.",
    )


def test_descriptor_is_one_capability_resource_with_explicit_bounds() -> None:
    descriptor = _descriptor("fake_exchange", "daily_bulk")

    assert descriptor.contract_version == "omi.market.provider_capability_descriptor.v2"
    assert descriptor.capability_id == "daily.ohlcv"
    assert descriptor.resource_id == "daily_bulk"
    assert descriptor.authority is AuthorityClass.EXCHANGE
    assert descriptor.venue_scope == ("TWSE",)
    assert descriptor.max_external_calls_per_attempt == 1


def test_descriptor_rejects_ambiguous_acquisition_and_dataset_shapes() -> None:
    with pytest.raises(ValidationError, match="subscription resources must produce live"):
        _descriptor(
            "fake_stream",
            "daily_stream",
            modes=(AcquisitionMode.SUBSCRIPTION,),
            live=False,
        )
    with pytest.raises(ValidationError, match="dataset resources require dataset_ids"):
        ProviderCapabilityDescriptorV2(
            provider_key="fake_dataset",
            market=Market.TW,
            capability_id="daily.ohlcv",
            resource_id="bulk",
            authority=AuthorityClass.EXCHANGE,
            target_kinds=(DescriptorTargetKind.DATASET,),
            acquisition_modes=(AcquisitionMode.FETCH,),
        )


@pytest.mark.parametrize(
    "policy",
    [RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION],
)
def test_read_only_policies_return_zero_io_plan(policy: RealtimePolicy) -> None:
    plan = plan_data_acquisition_v2(
        _requirement(policy),
        [_descriptor("fake_exchange", "daily_bulk")],
        [_health("fake_exchange")],
    )

    assert plan.acquisition_required is False
    assert plan.unfillable is False
    assert plan.routes == ()
    assert plan.limitations == ("POLICY_NO_EXTERNAL_ACQUISITION",)


def test_injected_resources_are_filtered_and_ordered_without_provider_catalog() -> None:
    descriptors = (
        _descriptor("fake_second", "twse_daily", priority=20),
        _descriptor("fake_wrong_venue", "tpex_daily", priority=0, venue_scope=("TPEX",)),
        _descriptor("fake_first", "twse_daily", priority=10),
    )
    plan = plan_data_acquisition_v2(
        _requirement(),
        descriptors,
        [_health(item.provider_key) for item in descriptors],
    )

    assert [(route.provider_key, route.resource_id) for route in plan.routes] == [
        ("fake_first", "twse_daily"),
        ("fake_second", "twse_daily"),
    ]
    assert plan.skipped_resources[0].reason_code == "VENUE_NOT_SUPPORTED_BY_RESOURCE"
    assert sum(route.max_external_calls for route in plan.routes) == 2


def test_require_live_fails_closed_when_resource_cannot_produce_live() -> None:
    plan = plan_data_acquisition_v2(
        _requirement(RealtimePolicy.REQUIRE_LIVE, max_subscriptions=1),
        [_descriptor("fake_delayed", "daily")],
        [_health("fake_delayed")],
    )

    assert plan.routes == ()
    assert plan.unfillable is True
    assert plan.skipped_resources[0].reason_code == "LIVE_NOT_SUPPORTED_BY_RESOURCE"


def test_health_is_strict_but_unknown_can_be_explicitly_bounded() -> None:
    strict = plan_data_acquisition_v2(
        _requirement(),
        [_descriptor("fake_strict", "daily")],
    )
    assert strict.skipped_resources[0].reason_code == "HEALTH_UNKNOWN"

    bounded = plan_data_acquisition_v2(
        _requirement(max_attempts=1, max_calls=1),
        [_descriptor("fake_probe", "daily", allow_unknown_health=True)],
    )
    assert bounded.routes[0].limitations == ("HEALTH_UNKNOWN",)

    stale = plan_data_acquisition_v2(
        _requirement(),
        [_descriptor("fake_stale", "daily")],
        [_health("fake_stale", checked_at=NOW - timedelta(minutes=10))],
    )
    assert stale.skipped_resources[0].reason_code == "HEALTH_STALE"


def test_attempt_and_call_budgets_truncate_routes_truthfully() -> None:
    descriptors = tuple(
        _descriptor(f"fake_{index}", f"daily_{index}", priority=index)
        for index in range(3)
    )
    plan = plan_data_acquisition_v2(
        _requirement(max_attempts=2, max_calls=1),
        descriptors,
        [_health(item.provider_key) for item in descriptors],
    )

    assert len(plan.routes) == 1
    assert plan.routes[0].max_external_calls == 1
    assert [item.reason_code for item in plan.skipped_resources] == [
        "EXTERNAL_CALL_BOUND_EXCEEDED",
        "EXTERNAL_CALL_BOUND_EXCEEDED",
    ]


def test_refresh_planning_uses_dataset_resource_and_never_subscribes() -> None:
    matching = ProviderCapabilityDescriptorV2(
        provider_key="fake_official",
        market=Market.TW,
        capability_id="daily.ohlcv",
        resource_id="official_bulk",
        authority=AuthorityClass.EXCHANGE,
        target_kinds=(DescriptorTargetKind.DATASET,),
        dataset_ids=("tw.daily.ohlcv.official",),
        venue_scope=("TWSE", "TPEX"),
        acquisition_modes=(AcquisitionMode.FETCH,),
        can_produce_final=True,
        max_external_calls_per_attempt=2,
        max_symbols_per_call=500,
        max_range_days=1,
    )
    wrong_dataset = matching.model_copy(
        update={"provider_key": "fake_other", "dataset_ids": ("tw.indices.official",)}
    )
    plan = plan_refresh_acquisition_v1(
        _refresh(),
        [wrong_dataset, matching],
        [_health("fake_other"), _health("fake_official")],
    )

    assert len(plan.routes) == 1
    assert plan.routes[0].provider_key == "fake_official"
    assert plan.routes[0].fetch_allowed is True
    assert plan.routes[0].subscription_allowed is False
    assert plan.routes[0].max_range_days == 1
    assert plan.skipped_resources[0].reason_code == "DATASET_NOT_SUPPORTED_BY_RESOURCE"


def test_duplicate_provider_resource_descriptor_is_rejected() -> None:
    descriptor = _descriptor("fake_exchange", "daily")
    with pytest.raises(ValueError, match="unique by provider/resource"):
        plan_data_acquisition_v2(
            _requirement(),
            [descriptor, descriptor],
            [_health("fake_exchange")],
        )


def test_shared_catalog_source_contains_no_production_provider_names() -> None:
    path = Path(__file__).parents[1] / "app" / "market_data" / "provider_catalog.py"
    source = path.read_text(encoding="utf-8").lower()
    for provider_name in ("kgi", "twse", "tpex", "yahoo", "nstock", "alpha"):
        assert provider_name not in source
