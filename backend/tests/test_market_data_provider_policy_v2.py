from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
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
)
from app.market_data.policies import DataPurpose, DataRequirement, RealtimePolicy
from app.market_data.provider_policy import (
    ProviderDescriptor,
    plan_acquisition,
)


NOW = datetime(2026, 8, 21, 9, 5, tzinfo=timezone(timedelta(hours=8)))


def _requirement(
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    *,
    capability: str = "quote.snapshot",
    market: Market = Market.TW,
    purpose: DataPurpose = DataPurpose.RESEARCH,
) -> DataRequirement:
    return DataRequirement(
        instrument=InstrumentKey(
            market=market,
            symbol="2330" if market is Market.TW else "AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="TWSE" if market is Market.TW else "NASDAQ",
        ),
        capability_id=capability,
        realtime_policy=policy,
        purpose=purpose,
        session=MarketSession.CONTINUOUS,
        instrument_tradability=InstrumentTradability.TRADABLE,
        requested_at=NOW,
        max_age_seconds=15,
    )


def _descriptor(
    key: str,
    *,
    priority: int = 100,
    market: Market = Market.TW,
    capabilities: tuple[str, ...] = ("quote.snapshot",),
    live: bool = True,
    allow_unknown: bool = False,
    allow_disconnected: bool = False,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_key=key,
        market=market,
        capabilities=capabilities,
        priority=priority,
        supports_external_fetch=True,
        supports_live_subscription=live,
        can_produce_live=live,
        max_timeout_seconds=4,
        allow_unknown_health=allow_unknown,
        allow_disconnected_connect=allow_disconnected,
    )


def _health(
    key: str,
    *,
    capability: str = "quote.snapshot",
    market: Market = Market.TW,
    enablement: EnablementStatus = EnablementStatus.ENABLED,
    connection: ConnectionStatus = ConnectionStatus.CONNECTED,
    entitlement: EntitlementStatus = EntitlementStatus.ENTITLED,
    operational: OperationalStatus = OperationalStatus.HEALTHY,
    freshness: EvidenceFreshness = EvidenceFreshness.LIVE,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=key,
        market=market,
        capability=capability,
        enablement=enablement,
        connection=connection,
        entitlement=entitlement,
        operational=operational,
        freshness=freshness,
        checked_at=NOW,
    )


@pytest.mark.parametrize(
    "policy",
    [RealtimePolicy.CACHE_ONLY, RealtimePolicy.COMPLETED_SESSION],
)
def test_zero_io_policies_never_create_routes(policy: RealtimePolicy) -> None:
    plan = plan_acquisition(
        _requirement(policy),
        [_descriptor("fake_primary")],
        {"fake_primary": _health("fake_primary")},
    )
    assert plan.routes == ()
    assert plan.acquisition_required is False
    assert plan.unfillable is False
    assert plan.allow_external_acquisition is False
    assert plan.allow_live_subscription is False
    assert plan.limitations == ("POLICY_NO_EXTERNAL_ACQUISITION",)


def test_routes_are_injected_deterministic_and_stably_tied() -> None:
    descriptors = [
        _descriptor("fake_z", priority=10),
        _descriptor("fake_a", priority=10),
        _descriptor("fake_first", priority=0),
    ]
    health = {item.provider_key: _health(item.provider_key) for item in descriptors}
    plan = plan_acquisition(_requirement(), reversed(descriptors), health)
    assert [route.provider_key for route in plan.routes] == [
        "fake_first",
        "fake_a",
        "fake_z",
    ]
    assert all(route.external_fetch_allowed for route in plan.routes)
    assert all(route.subscription_allowed for route in plan.routes)


def test_require_live_skips_provider_that_cannot_produce_live() -> None:
    descriptor = ProviderDescriptor(
        provider_key="fake_delayed",
        market=Market.TW,
        capabilities=("quote.snapshot",),
        supports_external_fetch=True,
        can_produce_live=False,
    )
    plan = plan_acquisition(
        _requirement(RealtimePolicy.REQUIRE_LIVE),
        [descriptor],
        {"fake_delayed": _health("fake_delayed", freshness=EvidenceFreshness.FRESH)},
    )
    assert plan.unfillable is True
    assert plan.routes == ()
    assert plan.skipped_providers[0].reason_code == "LIVE_NOT_SUPPORTED_BY_PROVIDER"


@pytest.mark.parametrize(
    ("health_kwargs", "reason"),
    [
        ({"enablement": EnablementStatus.DISABLED}, "PROVIDER_DISABLED"),
        ({"entitlement": EntitlementStatus.AUTH_FAILED}, "AUTH_FAILED"),
        ({"entitlement": EntitlementStatus.PLAN_RESTRICTED}, "PLAN_RESTRICTED"),
        ({"operational": OperationalStatus.FAILED}, "OPERATIONAL_FAILED"),
        ({"operational": OperationalStatus.RATE_LIMITED}, "RATE_LIMITED"),
        ({"operational": OperationalStatus.UNAVAILABLE}, "UNAVAILABLE"),
        ({"connection": ConnectionStatus.DISCONNECTED}, "NOT_CONNECTED"),
    ],
)
def test_terminal_health_dimensions_are_truthful_skips(
    health_kwargs: dict[str, object],
    reason: str,
) -> None:
    plan = plan_acquisition(
        _requirement(),
        [_descriptor("fake_primary")],
        {"fake_primary": _health("fake_primary", **health_kwargs)},
    )
    assert plan.routes == ()
    assert plan.unfillable is True
    assert plan.skipped_providers[0].reason_code == reason


def test_unknown_health_requires_explicit_descriptor_policy() -> None:
    strict_plan = plan_acquisition(
        _requirement(),
        [_descriptor("fake_strict")],
        {},
    )
    assert strict_plan.routes == ()
    assert strict_plan.skipped_providers[0].reason_code == "HEALTH_UNKNOWN"

    allowed_plan = plan_acquisition(
        _requirement(),
        [_descriptor("fake_probe", allow_unknown=True)],
        {},
    )
    assert len(allowed_plan.routes) == 1
    assert allowed_plan.routes[0].limitations == ("HEALTH_UNKNOWN",)


def test_degraded_and_bounded_connect_routes_preserve_limitations() -> None:
    descriptors = [
        _descriptor("fake_degraded", priority=0),
        _descriptor("fake_connect", priority=1, allow_disconnected=True),
    ]
    plan = plan_acquisition(
        _requirement(),
        descriptors,
        {
            "fake_degraded": _health(
                "fake_degraded",
                connection=ConnectionStatus.DEGRADED,
                operational=OperationalStatus.DEGRADED,
                freshness=EvidenceFreshness.STALE,
            ),
            "fake_connect": _health(
                "fake_connect",
                connection=ConnectionStatus.DISCONNECTED,
            ),
        },
    )
    assert plan.routes[0].limitations == (
        "CONNECTION_DEGRADED",
        "OPERATIONAL_DEGRADED",
        "PROVIDER_FRESHNESS_STALE",
    )
    assert plan.routes[1].limitations == ("BOUNDED_CONNECT_REQUIRED",)


def test_attempt_bound_and_fallback_disable_are_explicit() -> None:
    descriptors = [_descriptor(f"fake_{index}", priority=index) for index in range(4)]
    health = {item.provider_key: _health(item.provider_key) for item in descriptors}
    bounded = plan_acquisition(
        _requirement(),
        descriptors,
        health,
        max_provider_attempts=2,
    )
    assert len(bounded.routes) == 2
    assert bounded.limitations == ("PROVIDER_ROUTES_TRUNCATED",)
    assert [item.reason_code for item in bounded.skipped_providers] == [
        "ATTEMPT_BOUND_EXCEEDED",
        "ATTEMPT_BOUND_EXCEEDED",
    ]

    no_fallback = plan_acquisition(
        _requirement(),
        descriptors,
        health,
        fallback_allowed=False,
    )
    assert len(no_fallback.routes) == 1
    assert no_fallback.limitations == ("FALLBACK_DISABLED",)


@pytest.mark.parametrize(
    "requirement",
    [
        _requirement(capability="bar.1m"),
        _requirement(market=Market.JP),
        _requirement(purpose=DataPurpose.VIEWER),
    ],
)
def test_unsupported_02a_scope_fails_closed(requirement: DataRequirement) -> None:
    plan = plan_acquisition(requirement, [], {})
    assert plan.routes == ()
    assert plan.unfillable is True
    assert len(plan.limitations) == 1


def test_us_scope_is_supported_when_market_owner_injects_matching_provider() -> None:
    requirement = _requirement(market=Market.US)
    descriptor = _descriptor(
        "fake_us",
        market=Market.US,
        capabilities=("quote.snapshot",),
        live=False,
    )
    plan = plan_acquisition(
        requirement,
        [descriptor],
        {"fake_us": _health("fake_us", market=Market.US)},
    )
    assert [route.provider_key for route in plan.routes] == ["fake_us"]
    assert plan.routes[0].subscription_allowed is False


def test_duplicate_descriptors_and_invalid_bounds_are_rejected() -> None:
    descriptor = _descriptor("fake_primary")
    with pytest.raises(ValueError, match="unique provider keys"):
        plan_acquisition(_requirement(), [descriptor, descriptor], {})
    with pytest.raises(ValidationError):
        plan_acquisition(_requirement(), [], {}, max_provider_attempts=9)
    with pytest.raises(ValidationError):
        plan_acquisition(_requirement(), [], {}, overall_timeout_seconds=0)


def test_descriptor_contract_rejects_ambiguous_or_unbounded_shape() -> None:
    with pytest.raises(ValidationError, match="fetch or subscription"):
        ProviderDescriptor(
            provider_key="fake_none",
            market=Market.TW,
            capabilities=("quote.snapshot",),
        )
    with pytest.raises(ValidationError, match="must be unique"):
        _descriptor(
            "fake_duplicate",
            capabilities=("quote.snapshot", "quote.snapshot"),
        )
    with pytest.raises(ValidationError):
        _descriptor("UPPERCASE_NOT_ALLOWED")


def test_policy_source_contains_no_production_provider_catalog() -> None:
    module_path = Path(__file__).parents[1] / "app" / "market_data" / "provider_policy.py"
    source = module_path.read_text(encoding="utf-8").lower()
    assert "kgi" not in source
    assert "twse_mis" not in source
    assert "yahoo" not in source
    assert "alpha" not in source
