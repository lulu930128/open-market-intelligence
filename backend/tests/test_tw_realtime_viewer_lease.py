from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market.tw_realtime_lease_platform import (
    _sync_canonical_snapshot,
    acquire_taiwan_realtime_quote_lease,
    release_taiwan_realtime_quote_lease,
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
        acquire_status: str = "live",
        create_lease: bool = True,
        acquire_error: Exception | None = None,
        heartbeat_statuses: list[str | None] | None = None,
    ) -> None:
        self._provider_key = provider_key
        self.enabled = enabled
        self.returned_provider = returned_provider or provider_key
        self.acquire_status = acquire_status
        self.create_lease = create_lease
        self.acquire_error = acquire_error
        self.heartbeat_statuses = list(heartbeat_statuses or [])
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
        if self.acquire_error is not None:
            raise self.acquire_error
        inner_id = f"inner-{len(self.active) + 1}" if self.create_lease else None
        symbol = requirement.target.instrument.symbol
        if inner_id is not None:
            self.active[inner_id] = (symbol, owner_kind)
        return self._state(
            inner_id,
            symbol,
            owner_kind,
            provider=self.returned_provider,
            status=self.acquire_status,
        )

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
        if active is None:
            return None
        status = (
            self.heartbeat_statuses.pop(0)
            if self.heartbeat_statuses
            else "live"
        )
        return (
            self._state(lease_id, *active, status=status)
            if status is not None
            else None
        )

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
    assert acquired.providers_attempted == ("alpha",)
    assert acquired.plan.subscription_execution == "sequential_fallback"
    assert tuple(route.provider_key for route in acquired.plan.routes) == (
        "alpha",
        "beta",
    )
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


def test_viewer_lease_falls_back_when_primary_acquire_is_unavailable() -> None:
    primary = FakeViewerPort("alpha", acquire_status="unavailable")
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
        id_factory=lambda: "public-fallback-token",
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert acquired.detail_code == "VIEWER_LEASE_CREATED"
    assert acquired.selected_provider == "beta"
    assert acquired.providers_attempted == ("alpha", "beta")
    assert acquired.lease is not None
    assert acquired.lease.provider == "beta"
    assert primary.active == {}
    assert primary.release_ids == ["inner-1"]
    assert len(secondary.active) == 1
    assert coordinator.summary().total_active_leases == 1


def test_viewer_lease_does_not_start_secondary_when_primary_succeeds() -> None:
    primary = FakeViewerPort("alpha")
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert acquired.selected_provider == "alpha"
    assert acquired.providers_attempted == ("alpha",)
    assert secondary.acquired_routes == []


def test_viewer_lease_falls_back_after_primary_timeout() -> None:
    primary = FakeViewerPort("alpha", acquire_error=TimeoutError("timed out"))
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    assert acquired.selected_provider == "beta"
    assert acquired.providers_attempted == ("alpha", "beta")
    assert any("TimeoutError" in item for item in acquired.limitations)


class MutableMonotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_viewer_lease_heartbeat_falls_back_after_starting_unavailable() -> None:
    current = MutableMonotonic()
    primary = FakeViewerPort(
        "alpha",
        acquire_status="starting",
        heartbeat_statuses=["unavailable"],
    )
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
        id_factory=lambda: "public-heartbeat-fallback",
        monotonic=current,
        transitional_grace_seconds=9,
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")
    heartbeat = coordinator.heartbeat("public-heartbeat-fallback")
    repeated = coordinator.heartbeat("public-heartbeat-fallback")

    assert acquired.lease is not None and acquired.lease.status == "starting"
    assert acquired.lease.expires_in_seconds == 9
    assert heartbeat is not None
    assert heartbeat.lease_id == "public-heartbeat-fallback"
    assert heartbeat.provider == "beta"
    assert primary.release_ids == ["inner-1"]
    assert len(secondary.active) == 1
    assert repeated is not None and repeated.provider == "beta"
    assert len(secondary.acquired_routes) == 1


def test_concurrent_heartbeats_share_one_atomic_failover() -> None:
    primary = FakeViewerPort(
        "alpha",
        acquire_status="starting",
        heartbeat_statuses=["unavailable"],
    )
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
        id_factory=lambda: "public-concurrent-fallback",
    )
    coordinator.acquire(_requirement(), owner_kind="frontend_viewer")

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = tuple(
            pool.map(
                coordinator.heartbeat,
                ("public-concurrent-fallback", "public-concurrent-fallback"),
            )
        )

    assert all(state is not None and state.provider == "beta" for state in states)
    assert primary.release_ids == ["inner-1"]
    assert len(secondary.acquired_routes) == 1
    assert len(secondary.active) == 1


def test_viewer_lease_starting_can_become_live_without_secondary() -> None:
    current = MutableMonotonic()
    primary = FakeViewerPort(
        "alpha",
        acquire_status="starting",
        heartbeat_statuses=["live"],
    )
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
        monotonic=current,
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")
    heartbeat = coordinator.heartbeat(acquired.lease.lease_id)  # type: ignore[union-attr]

    assert heartbeat is not None and heartbeat.status == "live"
    assert heartbeat.provider == "alpha"
    assert secondary.acquired_routes == []


def test_viewer_lease_transitional_state_has_bounded_timeout() -> None:
    current = MutableMonotonic()
    primary = FakeViewerPort(
        "alpha",
        acquire_status="starting",
        heartbeat_statuses=["starting", "starting"],
    )
    secondary = FakeViewerPort("beta")
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5), _descriptor("beta", 20)),
        ports={"alpha": primary, "beta": secondary},
        id_factory=lambda: "public-grace-fallback",
        monotonic=current,
        transitional_grace_seconds=5,
    )

    acquired = coordinator.acquire(_requirement(), owner_kind="frontend_viewer")
    within_grace = coordinator.heartbeat("public-grace-fallback")
    current.advance(6)
    after_grace = coordinator.heartbeat("public-grace-fallback")

    assert acquired.lease is not None
    assert acquired.lease.expires_in_seconds == 5
    assert within_grace is not None and within_grace.provider == "alpha"
    assert after_grace is not None and after_grace.provider == "beta"
    assert primary.release_ids == ["inner-1"]
    assert len(secondary.active) == 1


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
    warmup_calls: list[tuple[Session, str, datetime]] = []

    def enqueue_baseline_warmup(
        warmup_db: Session,
        stock_id: str,
        requested_at: datetime,
    ) -> None:
        warmup_calls.append((warmup_db, stock_id, requested_at))

    try:
        state = acquire_taiwan_realtime_quote_lease(
            db,
            stock_id="2330",
            owner_kind="frontend_viewer",
            requested_at=NOW,
            coordinator=coordinator,
            baseline_warmup_enqueuer=enqueue_baseline_warmup,
        )

        assert warmup_calls == [(db, "2330", NOW)]
    finally:
        db.close()
        engine.dispose()

    assert state.lease_id == "public-platform-token"
    assert state.stock_id == "2330"
    assert state.provider == "kgi_superpy"
    assert state.owner_kind == "frontend_viewer"


def test_non_frontend_lease_does_not_signal_viewer_baseline_warmup() -> None:
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
        id_factory=lambda: "non-frontend-token",
    )
    warmup_calls: list[str] = []
    try:
        state = acquire_taiwan_realtime_quote_lease(
            db,
            stock_id="2330",
            owner_kind="acceptance_probe",
            requested_at=NOW,
            coordinator=coordinator,
            baseline_warmup_enqueuer=(
                lambda _db, stock_id, _requested_at: warmup_calls.append(stock_id)
            ),
        )
    finally:
        db.close()
        engine.dispose()

    assert state.lease_id == "non-frontend-token"
    assert warmup_calls == []


def test_kgi_release_flushes_closed_bar_buffer_before_provider_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        id_factory=lambda: "public-release-flush-token",
    )
    acquired = acquire_taiwan_realtime_quote_lease(
        db,
        stock_id="2330",
        owner_kind="frontend_viewer",
        requested_at=NOW,
        coordinator=coordinator,
    )
    assert acquired.lease_id is not None
    calls: list[tuple[str, datetime]] = []

    def sync_bars(_db, *, stock_id: str, requested_at: datetime) -> None:
        calls.append((stock_id, requested_at))
        assert port.release_ids == []

    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform._sync_kgi_minute_bars",
        sync_bars,
    )

    try:
        released = release_taiwan_realtime_quote_lease(
            db,
            acquired.lease_id,
            requested_at=NOW,
            coordinator=coordinator,
        )
    finally:
        db.close()
        engine.dispose()

    assert calls == [("2330", NOW)]
    assert released is not None and released.status == "released"
    assert port.release_ids == ["inner-1"]


def test_close_resolution_sync_persists_quote_without_depth_or_auction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def sync_quote(*_args, **_kwargs):
        calls.append("quote")
        return SimpleNamespace(
            requirement=SimpleNamespace(session=MarketSession.CLOSE_RESOLUTION)
        )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("close resolution must not reacquire depth or auction")

    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_public_last_trade_quote",
        sync_quote,
    )
    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_depth",
        forbidden,
    )
    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_auction",
        forbidden,
    )

    _sync_canonical_snapshot(
        SimpleNamespace(),
        stock_id="2330",
        requested_at=datetime(2026, 8, 26, 13, 31, tzinfo=TAIPEI),
    )

    assert calls == ["quote"]


def test_kgi_depth_failure_uses_one_market_owned_mis_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def sync_quote(*_args, **_kwargs):
        calls.append("quote")
        return SimpleNamespace(
            requirement=SimpleNamespace(session=MarketSession.CONTINUOUS)
        )

    def sync_depth(*_args, **_kwargs):
        calls.append("kgi_depth")
        raise TimeoutError("broker depth timed out")

    def sync_mis(*_args, **_kwargs):
        calls.append("mis_depth")

    def sync_auction(*_args, **_kwargs):
        calls.append("auction")

    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_public_last_trade_quote",
        sync_quote,
    )
    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_depth",
        sync_depth,
    )
    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform._sync_mis_depth_snapshot",
        sync_mis,
    )
    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform.acquire_taiwan_auction",
        sync_auction,
    )

    _sync_canonical_snapshot(
        SimpleNamespace(),
        stock_id="2330",
        requested_at=NOW,
    )

    assert calls == ["quote", "kgi_depth", "mis_depth", "auction"]


def test_unavailable_broker_lease_refreshes_bounded_mis_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    port = FakeViewerPort("alpha", enabled=False)
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5),),
        ports={"alpha": port},
    )
    fallback_calls: list[tuple[str, datetime]] = []

    def sync_mis(_db, *, stock_id: str, requested_at: datetime) -> None:
        fallback_calls.append((stock_id, requested_at))

    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform._sync_mis_depth_snapshot",
        sync_mis,
    )
    try:
        state = acquire_taiwan_realtime_quote_lease(
            db,
            stock_id="2330",
            requested_at=NOW,
            coordinator=coordinator,
        )
    finally:
        db.close()
        engine.dispose()

    assert fallback_calls == [("2330", NOW)]
    assert state.lease_id is None
    assert state.status == "degraded"
    assert state.fallback_source == "twse_mis_quote_depth"


def test_post_close_unavailable_lease_does_not_fetch_mis_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    port = FakeViewerPort("alpha", enabled=False)
    coordinator = ViewerLeaseCoordinator(
        descriptors=(_descriptor("alpha", 5),),
        ports={"alpha": port},
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("post-close must not refresh order-book depth")

    monkeypatch.setattr(
        "app.market.tw_realtime_lease_platform._sync_mis_depth_snapshot",
        forbidden,
    )
    try:
        state = acquire_taiwan_realtime_quote_lease(
            db,
            stock_id="2330",
            requested_at=datetime(2026, 8, 26, 14, 0, tzinfo=TAIPEI),
            coordinator=coordinator,
        )
    finally:
        db.close()
        engine.dispose()

    assert state.lease_id is None
    assert state.status == "unavailable"


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
