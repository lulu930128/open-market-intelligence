from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market.tw_realtime_lease_platform import (
    acquire_taiwan_realtime_quote_lease,
)
from app.market.tw_realtime_capabilities import KGI_QUOTE_SNAPSHOT_DESCRIPTOR
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
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
    ProviderResourceRouteV2,
)
from app.market_data.research_lease import (
    ViewerLeaseCoordinator,
    ViewerLeaseOwnerKind,
    ViewerLeasePortSummary,
    ViewerLeaseState,
)


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)
CAPABILITY = "quote.snapshot"


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _requirement() -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=SnapshotCapabilityRequest(capability_id=CAPABILITY),
        purpose=DataPurpose.VIEWER,
        realtime_policy=RealtimePolicy.REQUIRE_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=15),
        quality=QualityRequirement(require_canonical_lineage=True),
        bounds=RequestBounds(
            max_provider_attempts=2,
            max_external_calls=0,
            max_subscriptions=1,
            timeout_seconds=30,
            max_candidates=1,
            max_rows=1,
        ),
    )


def _descriptor(provider: str, priority: int) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key=provider,
        market=Market.TW,
        capability_id=CAPABILITY,
        resource_id=f"{provider}.viewer",
        authority=AuthorityClass.BROKER,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,),
        venue_scope=("TWSE", "TPEX"),
        instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
        supported_sessions=(MarketSession.CONTINUOUS,),
        acquisition_modes=(AcquisitionMode.SUBSCRIPTION,),
        priority=priority,
        can_produce_live=True,
        max_external_calls_per_attempt=0,
        max_subscriptions_per_attempt=1,
        allow_unknown_health=False,
        allow_disconnected_connect=True,
    )


class FakeViewerPort:
    def __init__(
        self,
        provider_key: str,
        *,
        enabled: bool = True,
        returned_provider: str | None = None,
    ) -> None:
        self._provider_key = provider_key
        self.enabled = enabled
        self.returned_provider = returned_provider or provider_key
        self.active: dict[str, tuple[str, ViewerLeaseOwnerKind]] = {}
        self.acquired_routes: list[ProviderResourceRouteV2] = []
        self.heartbeat_ids: list[str] = []
        self.release_ids: list[str] = []

    @property
    def provider_key(self) -> str:
        return self._provider_key

    def health(self, requirement: DataRequirementV2) -> ProviderResourceHealth:
        return ProviderResourceHealth(
            provider=self.provider_key,
            market=Market.TW,
            capability=requirement.request.capability_id,
            enablement=(
                EnablementStatus.ENABLED
                if self.enabled
                else EnablementStatus.DISABLED
            ),
            connection=ConnectionStatus.DISCONNECTED,
            entitlement=EntitlementStatus.ENTITLED,
            operational=(
                OperationalStatus.HEALTHY
                if self.enabled
                else OperationalStatus.UNAVAILABLE
            ),
            freshness=EvidenceFreshness.MISSING,
            checked_at=requirement.requested_at,
        )

    def acquire(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
        *,
        owner_kind: ViewerLeaseOwnerKind,
    ) -> ViewerLeaseState:
        self.acquired_routes.append(route)
        inner_id = f"inner-{len(self.active) + 1}"
        symbol = requirement.target.instrument.symbol
        self.active[inner_id] = (symbol, owner_kind)
        return self._state(inner_id, symbol, owner_kind, provider=self.returned_provider)

    def _state(
        self,
        lease_id: str | None,
        symbol: str,
        owner_kind: ViewerLeaseOwnerKind,
        *,
        provider: str | None = None,
        status: str = "live",
    ) -> ViewerLeaseState:
        return ViewerLeaseState(
            lease_id=lease_id,
            stock_id=symbol,
            provider=provider or self.provider_key,
            owner_kind=owner_kind,
            status=status,
            expires_in_seconds=60 if lease_id else None,
            fallback_source="resolved_fallback",
            message="fixture",
        )

    def heartbeat(self, lease_id: str) -> ViewerLeaseState | None:
        self.heartbeat_ids.append(lease_id)
        active = self.active.get(lease_id)
        return self._state(lease_id, *active) if active is not None else None

    def release(self, lease_id: str) -> ViewerLeaseState | None:
        self.release_ids.append(lease_id)
        active = self.active.pop(lease_id, None)
        return (
            self._state(None, *active, status="released")
            if active is not None
            else None
        )

    def summary(self) -> ViewerLeasePortSummary:
        owners: dict[str, int] = {}
        symbols: dict[str, int] = {}
        for symbol, owner in self.active.values():
            owners[owner] = owners.get(owner, 0) + 1
            symbols[symbol] = symbols.get(symbol, 0) + 1
        return ViewerLeasePortSummary(
            provider=self.provider_key,
            total_active_leases=len(self.active),
            active_symbol_count=len(symbols),
            leases_by_owner_kind=owners,
            leases_by_symbol=symbols,
        )


def test_coordinator_selects_by_shared_plan_and_hides_provider_handle() -> None:
    primary = FakeViewerPort("alpha")
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("beta", 20), _descriptor("alpha", 5)),
        ports={"alpha": primary, "beta": secondary},
        id_factory=lambda: "public-owner-token",
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert acquired.detail_code == "VIEWER_LEASE_CREATED"
    assert acquired.selected_provider == "alpha"
    assert acquired.lease is not None
    assert acquired.lease.lease_id == "public-owner-token"
    assert acquired.lease.lease_id not in primary.active
    assert tuple(primary.active) == ("inner-1",)
    assert secondary.acquired_routes == []

    heartbeat = coordinator.heartbeat("public-owner-token")
    assert heartbeat is not None
    assert heartbeat.lease_id == "public-owner-token"
    assert primary.heartbeat_ids == ["inner-1"]

    released = coordinator.release("public-owner-token")
    assert released is not None and released.status == "released"
    assert primary.release_ids == ["inner-1"]
    assert coordinator.summary().total_active_leases == 0
    assert coordinator.summary().tracked_owner_tokens == 0


def test_coordinator_fail_closes_and_cleans_provider_identity_mismatch() -> None:
    port = FakeViewerPort("alpha", returned_provider="forged")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5),),
        ports={"alpha": port},
    )

    with pytest.raises(ValueError, match="different provider"):
        coordinator.acquire(_requirement(), owner_kind="acceptance_probe")

    assert port.active == {}
    assert port.release_ids == ["inner-1"]


def test_invalid_public_owner_token_cleans_provider_handle() -> None:
    port = FakeViewerPort("alpha")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5),),
        ports={"alpha": port},
        id_factory=lambda: "bad token with spaces",
    )

    with pytest.raises(ValueError):
        coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert port.active == {}
    assert port.release_ids == ["inner-1"]


def test_disabled_health_prevents_port_start() -> None:
    port = FakeViewerPort("alpha", enabled=False)
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5),),
        ports={"alpha": port},
    )

    result = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert result.lease is None
    assert result.detail_code == "VIEWER_LEASE_PLAN_UNFILLABLE"
    assert port.acquired_routes == []


def test_taiwan_platform_preserves_public_shape_with_neutral_coordinator() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()
    port = FakeViewerPort("kgi_superpy")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
        ports={"kgi_superpy": port},
        id_factory=lambda: "public-platform-token",
    )
    try:
        state = acquire_taiwan_realtime_quote_lease(
            db,
            stock_id="2330",
            owner_kind="frontend_viewer",
            requested_at=NOW,
            coordinator=coordinator,
        )
    finally:
        db.close()
        engine.dispose()

    assert state.lease_id == "public-platform-token"
    assert state.stock_id == "2330"
    assert state.provider == "kgi_superpy"
    assert state.owner_kind == "frontend_viewer"


def test_router_no_longer_owns_kgi_specific_lease_lifecycle() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "market.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "acquire_kgi_superpy_quote_lease",
        "heartbeat_kgi_superpy_quote_lease",
        "release_kgi_superpy_quote_lease",
        "get_kgi_superpy_quote_lease_summary",
    ):
        assert forbidden not in source
    assert "app.market.tw_realtime_lease_platform" in source
