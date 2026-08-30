from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.market.providers.kgi_canonical import (
    KGI_PROVIDER,
    KGI_RAW_CONTRACT_VERSION,
    KGI_SOURCE,
)
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter,
    KgiRealtimeProviderSnapshot,
)
from app.market.tw_realtime_capabilities import (
    FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR,
    KGI_AUCTION_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
    TW_AUCTION_CAPABILITY_ID,
    TW_ORDER_BOOK_CAPABILITY_ID,
    TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
    TW_REALTIME_PROVIDER_DESCRIPTORS,
)
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
    ObservationState,
    OperationalStatus,
    ProviderResourceHealth,
    TradeObservationState,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    AcquisitionMode,
    ProviderCapabilityDescriptorV2,
    plan_data_acquisition_v2,
)


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _requirement(
    descriptor: ProviderCapabilityDescriptorV2,
    *,
    session: MarketSession,
) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=SnapshotCapabilityRequest(
            capability_id=descriptor.capability_id,
            depth_levels=(
                5 if descriptor.capability_id == TW_ORDER_BOOK_CAPABILITY_ID else None
            ),
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.REQUIRE_LIVE,
        session=session,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=60),
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=0,
            max_subscriptions=1,
            timeout_seconds=45,
            max_rows=10,
        ),
    )


def _health(capability_id: str) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=KGI_PROVIDER,
        market=Market.TW,
        capability=capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.LIVE,
        checked_at=NOW,
    )


def _plan(
    descriptor: ProviderCapabilityDescriptorV2,
    *,
    session: MarketSession,
):
    requirement = _requirement(descriptor, session=session)
    plan = plan_data_acquisition_v2(
        requirement,
        (descriptor,),
        (_health(descriptor.capability_id),),
    )
    assert len(plan.routes) == 1
    return requirement, plan


def _quote(*, indicative: bool = False) -> dict[str, object]:
    return {
        "symbol": "2330",
        "datetime": "20260826100000",
        "received_at": "2026-08-26T02:00:00+00:00",
        "simtrade": 1 if indicative else 0,
        "close": 1180,
        "volume": 2,
        "total_volume": 100 if not indicative else 0,
        "open": 1170,
        "high": 1185,
        "low": 1165,
        "price_chg": 10,
        "bid_prices": [1175, 1170],
        "bid_volumes": [4, 5],
        "ask_prices": [1180, 1185],
        "ask_volumes": [3, 6],
    }


def _adapter(quote: dict[str, object]) -> KgiRealtimeAcquisitionAdapter:
    return KgiRealtimeAcquisitionAdapter(
        lambda _symbol: KgiRealtimeProviderSnapshot(
            quote=dict(quote),
            status="live",
        ),
        clock=lambda: NOW,
    )


def test_tw_realtime_descriptors_separate_capability_and_resource_contracts() -> None:
    assert len(TW_REALTIME_PROVIDER_DESCRIPTORS) == 7
    keys = {
        (item.provider_key, item.capability_id, item.resource_id)
        for item in TW_REALTIME_PROVIDER_DESCRIPTORS
    }
    assert len(keys) == 7

    assert KGI_QUOTE_SNAPSHOT_DESCRIPTOR.capability_id == TW_QUOTE_SNAPSHOT_CAPABILITY_ID
    assert KGI_ORDER_BOOK_DESCRIPTOR.capability_id == TW_ORDER_BOOK_CAPABILITY_ID
    assert TW_AUCTION_CAPABILITY_ID == "quote.auction"
    assert KGI_AUCTION_DESCRIPTOR.capability_id == TW_AUCTION_CAPABILITY_ID
    assert FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR.capability_id == TW_QUOTE_SNAPSHOT_CAPABILITY_ID
    assert FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR.acquisition_modes == (
        AcquisitionMode.SUBSCRIPTION,
    )
    assert FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR.venue_scope == ("TWSE",)
    assert FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR.priority == 10
    for descriptor in (
        KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
        KGI_ORDER_BOOK_DESCRIPTOR,
        KGI_AUCTION_DESCRIPTOR,
    ):
        assert descriptor.authority is AuthorityClass.BROKER
        assert descriptor.acquisition_modes == (AcquisitionMode.SUBSCRIPTION,)
        assert descriptor.can_produce_live is True
        assert descriptor.max_subscriptions_per_attempt == 1
        assert descriptor.max_symbols_per_call == 1
        assert descriptor.venue_scope == ("TWSE", "TPEX")
        assert descriptor.allow_unknown_health is True
        assert descriptor.allow_disconnected_connect is True
    assert KGI_AUCTION_DESCRIPTOR.supported_sessions == (
        MarketSession.OPENING_AUCTION,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
    )


def test_kgi_quote_acquisition_returns_canonical_observation_and_raw_receipt() -> None:
    requirement, plan = _plan(
        KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
        session=MarketSession.CONTINUOUS,
    )

    result = _adapter(_quote()).acquire_quote_observations(requirement, plan)

    assert result.summary.status.value == "completed"
    assert result.summary.subscriptions_created == 0
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.trade_state is TradeObservationState.TRADE_OBSERVED
    assert observation.last_trade_price is not None
    assert observation.lineage.provider == KGI_PROVIDER
    assert observation.lineage.source == KGI_SOURCE
    assert observation.lineage.raw_contract_version == KGI_RAW_CONTRACT_VERSION
    assert observation.lineage.fetched_at == NOW
    assert observation.lineage.content_hash == result.receipts[0].content_hash
    assert result.receipts[0].method == "STREAM"
    assert result.receipts[0].raw_text is not None


def test_kgi_depth_acquisition_preserves_level_five_semantics_and_lineage() -> None:
    requirement, plan = _plan(
        KGI_ORDER_BOOK_DESCRIPTOR,
        session=MarketSession.CONTINUOUS,
    )

    result = _adapter(_quote()).acquire_depth_observations(requirement, plan)

    assert len(result.observations) == 1
    depth = result.observations[0]
    assert len(depth.bids) == 2
    assert len(depth.asks) == 2
    assert depth.lineage.content_hash == result.receipts[0].content_hash
    assert depth.lineage.fetched_at == NOW


def test_kgi_auction_acquisition_keeps_trial_data_indicative_not_trade() -> None:
    requirement, plan = _plan(
        KGI_AUCTION_DESCRIPTOR,
        session=MarketSession.CLOSING_AUCTION,
    )

    result = _adapter(_quote(indicative=True)).acquire_auction_observations(
        requirement,
        plan,
    )

    assert len(result.observations) == 1
    auction = result.observations[0]
    assert auction.state is ObservationState.INDICATIVE
    assert auction.provisional is True
    assert auction.indicative_price is not None
    assert result.receipts[0].content_hash == auction.lineage.content_hash


def test_kgi_auction_without_trial_evidence_is_partial_but_keeps_receipt() -> None:
    requirement, plan = _plan(
        KGI_AUCTION_DESCRIPTOR,
        session=MarketSession.CLOSING_AUCTION,
    )

    quote = _quote()
    quote.pop("close")
    quote.pop("volume")
    result = _adapter(quote).acquire_auction_observations(requirement, plan)

    assert result.observations == ()
    assert len(result.receipts) == 1
    assert result.summary.status.value == "partial"
    assert result.summary.limitations == ("KGI_AUCTION_OBSERVATION_UNAVAILABLE",)


def test_kgi_adapter_does_not_attempt_a_resource_outside_the_shared_plan() -> None:
    quote_requirement, quote_plan = _plan(
        KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
        session=MarketSession.CONTINUOUS,
    )

    result = _adapter(_quote()).acquire_depth_observations(
        quote_requirement,
        quote_plan,
    )

    assert result.summary.attempted is False
    assert result.observations == ()
    assert result.receipts == ()


def test_shared_core_remains_free_of_taiwan_provider_names() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "market_data"
    for relative in (
        "gateway.py",
        "provider_catalog.py",
        "quality_policy.py",
        "resolution.py",
    ):
        source = (root / relative).read_text(encoding="utf-8").lower()
        assert "kgi_superpy" not in source
        assert "twse_mis" not in source
