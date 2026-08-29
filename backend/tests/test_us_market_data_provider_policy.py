from __future__ import annotations

from datetime import datetime, timezone

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
from app.us_market.market_data_policy import (
    US_PROVIDER_DESCRIPTORS,
    build_us_acquisition_plan,
    us_provider_order,
)


NOW = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)


def _requirement(
    capability: str,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    session: MarketSession = MarketSession.CONTINUOUS,
) -> DataRequirement:
    return DataRequirement(
        instrument=InstrumentKey(
            market=Market.US,
            symbol="AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        capability_id=capability,
        realtime_policy=policy,
        purpose=DataPurpose.RESEARCH,
        session=session,
        instrument_tradability=InstrumentTradability.TRADABLE,
        requested_at=NOW,
        max_age_seconds=300,
    )


def _health(provider: str, capability: str) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=provider,
        market=Market.US,
        capability=capability,
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.FRESH,
        checked_at=NOW,
    )


def test_us_descriptors_are_market_owned_and_capability_specific() -> None:
    assert [item.provider_key for item in US_PROVIDER_DESCRIPTORS] == [
        "yahoo_chart",
    ]
    assert "intraday.bars" in US_PROVIDER_DESCRIPTORS[0].capabilities
    assert "daily.ohlcv" not in US_PROVIDER_DESCRIPTORS[0].capabilities
    assert us_provider_order("daily.ohlcv") == (
        "yahoo_chart",
        "alpaca",
    )
    assert not any(item.can_produce_live for item in US_PROVIDER_DESCRIPTORS)


def test_prefer_live_quote_has_bounded_delayed_vendor_route() -> None:
    plan = build_us_acquisition_plan(
        _requirement("quote.snapshot"),
        {"yahoo_chart": _health("yahoo_chart", "quote.snapshot")},
    )
    assert [route.provider_key for route in plan.routes] == ["yahoo_chart"]
    assert plan.bounds.max_provider_attempts == 2
    assert plan.bounds.max_external_calls == 2
    assert plan.bounds.max_subscriptions == 0
    assert plan.routes[0].external_fetch_allowed is True
    assert plan.routes[0].subscription_allowed is False


def test_require_live_is_truthfully_unfillable_without_live_provider() -> None:
    plan = build_us_acquisition_plan(
        _requirement("quote.snapshot", RealtimePolicy.REQUIRE_LIVE),
        {"yahoo_chart": _health("yahoo_chart", "quote.snapshot")},
    )
    assert plan.routes == ()
    assert plan.unfillable is True
    assert {
        item.reason_code for item in plan.skipped_providers
    } == {
        "LIVE_NOT_SUPPORTED_BY_PROVIDER",
    }


def test_daily_routes_are_deterministic_and_fallback_bounded() -> None:
    plan = build_us_acquisition_plan(
        _requirement("daily.ohlcv", session=MarketSession.CLOSED),
        {
            "yahoo_chart": _health("yahoo_chart", "daily.ohlcv"),
            "alpaca": _health("alpaca", "daily.ohlcv"),
        },
    )
    assert [route.provider_key for route in plan.routes] == [
        "yahoo_chart",
        "alpaca",
    ]
    assert all(route.route_timeout_seconds <= 30 for route in plan.routes)


def test_daily_provider_session_eligibility_fails_closed_during_continuous_session() -> None:
    plan = build_us_acquisition_plan(
        _requirement("daily.ohlcv", session=MarketSession.CONTINUOUS),
        {
            "yahoo_chart": _health("yahoo_chart", "daily.ohlcv"),
            "alpaca": _health("alpaca", "daily.ohlcv"),
        },
    )

    assert plan.routes == ()
    assert {
        (item.provider_key, item.reason_code)
        for item in plan.skipped_providers
    } == {
        ("yahoo_chart", "SESSION_NOT_SUPPORTED_BY_PROVIDER"),
        ("alpaca", "SESSION_NOT_SUPPORTED_BY_PROVIDER"),
    }


def test_cache_only_never_builds_us_provider_routes() -> None:
    plan = build_us_acquisition_plan(
        _requirement("intraday.bars", RealtimePolicy.CACHE_ONLY),
        {},
    )
    assert plan.routes == ()
    assert plan.acquisition_required is False
    assert plan.unfillable is False
    assert plan.limitations == ("POLICY_NO_EXTERNAL_ACQUISITION",)
