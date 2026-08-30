"""Viewer-lease port for the single Fugle active-stock subscription budget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
import time
import uuid

from app.config import settings
from app.market.providers.fugle_realtime_runtime import get_fugle_realtime_runtime
from app.market.tw_realtime_capabilities import FUGLE_PROVIDER
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.integration_contracts import DataRequirementV2, InstrumentTarget
from app.market_data.provider_catalog import ProviderResourceRouteV2
from app.market_data.research_lease import (
    ViewerLeaseOwnerKind,
    ViewerLeasePortSummary,
    ViewerLeaseState,
)


@dataclass(frozen=True, slots=True)
class _Lease:
    symbol: str
    owner_kind: ViewerLeaseOwnerKind
    expires_at: float


class FugleRealtimeQuoteLeasePort:
    def __init__(
        self,
        *,
        ttl_seconds: int = 60,
        monotonic=time.monotonic,
    ) -> None:
        self._ttl_seconds = max(int(ttl_seconds), 10)
        self._monotonic = monotonic
        self._lock = RLock()
        self._leases: dict[str, _Lease] = {}

    @property
    def provider_key(self) -> str:
        return FUGLE_PROVIDER

    def _expire(self) -> None:
        now = self._monotonic()
        with self._lock:
            self._leases = {
                lease_id: lease
                for lease_id, lease in self._leases.items()
                if lease.expires_at > now
            }
            symbols = {lease.symbol for lease in self._leases.values()}
        runtime = get_fugle_realtime_runtime()
        if runtime is not None and not symbols:
            runtime.set_active_stock(None)

    def health(self, requirement: DataRequirementV2) -> ProviderResourceHealth:
        runtime = get_fugle_realtime_runtime()
        enabled = bool(settings.enable_fugle_realtime)
        configured = bool(str(settings.fugle_api_key or "").strip())
        connected = runtime is not None and runtime.connection_status == "connected"
        entitlement = runtime.entitlement_status if runtime is not None else "unknown"
        return ProviderResourceHealth(
            provider=self.provider_key,
            market=requirement.target.instrument.market,
            capability=requirement.request.capability_id,
            enablement=EnablementStatus.ENABLED if enabled else EnablementStatus.DISABLED,
            connection=(
                ConnectionStatus.CONNECTED
                if connected
                else ConnectionStatus.DISCONNECTED
                if enabled
                else ConnectionStatus.NOT_APPLICABLE
            ),
            entitlement=(
                EntitlementStatus.ENTITLED
                if entitlement == "entitled"
                else EntitlementStatus.AUTH_FAILED
                if entitlement == "auth_failed"
                else EntitlementStatus.PLAN_RESTRICTED
                if entitlement == "plan_restricted"
                else EntitlementStatus.UNKNOWN
            ),
            operational=(
                OperationalStatus.HEALTHY
                if connected
                else OperationalStatus.DEGRADED
                if runtime is not None and configured
                else OperationalStatus.UNAVAILABLE
            ),
            freshness=(
                EvidenceFreshness.LIVE if connected else EvidenceFreshness.MISSING
            ),
            checked_at=requirement.requested_at,
            detail_code=(
                "FUGLE_RUNTIME_CONNECTED"
                if connected
                else "FUGLE_API_KEY_MISSING"
                if enabled and not configured
                else "FUGLE_RUNTIME_CONNECTING"
                if runtime is not None and configured
                else "FUGLE_RUNTIME_UNAVAILABLE"
            ),
        )

    def acquire(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
        *,
        owner_kind: ViewerLeaseOwnerKind,
    ) -> ViewerLeaseState:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("Fugle viewer lease requires instrument target")
        if route.provider_key != self.provider_key or not route.subscription_allowed:
            raise ValueError("Fugle viewer lease received an invalid shared route")
        runtime = get_fugle_realtime_runtime()
        symbol = requirement.target.instrument.symbol
        if runtime is None:
            return ViewerLeaseState(
                stock_id=symbol,
                provider=self.provider_key,
                owner_kind=owner_kind,
                status="unavailable",
                fallback_source="resolved_fallback",
                message="Fugle runtime尚未啟動；行情維持既有resolved fallback。",
                error="FUGLE_RUNTIME_UNAVAILABLE",
            )
        self._expire()
        with self._lock:
            active_symbols = {lease.symbol for lease in self._leases.values()}
            if active_symbols and active_symbols != {symbol}:
                return ViewerLeaseState(
                    stock_id=symbol,
                    provider=self.provider_key,
                    owner_kind=owner_kind,
                    status="unavailable",
                    fallback_source="resolved_fallback",
                    message="Fugle Basic active-stock槽位正由另一檔個股使用。",
                    error="FUGLE_ACTIVE_STOCK_SLOT_OCCUPIED",
                )
            lease_id = uuid.uuid4().hex
            self._leases[lease_id] = _Lease(
                symbol=symbol,
                owner_kind=owner_kind,
                expires_at=self._monotonic() + self._ttl_seconds,
            )
        runtime.set_active_stock(symbol)
        live = runtime.connection_status == "connected"
        return ViewerLeaseState(
            lease_id=lease_id,
            stock_id=symbol,
            provider=self.provider_key,
            owner_kind=owner_kind,
            status="live" if live else "connecting",
            expires_in_seconds=self._ttl_seconds,
            fallback_source="resolved_fallback",
            message=(
                "Fugle active-stock即時槽位已建立。"
                if live
                else "Fugle active-stock槽位已保留，等待連線／訂閱確認。"
            ),
        )

    def heartbeat(self, lease_id: str) -> ViewerLeaseState | None:
        self._expire()
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return None
            renewed = _Lease(
                symbol=lease.symbol,
                owner_kind=lease.owner_kind,
                expires_at=self._monotonic() + self._ttl_seconds,
            )
            self._leases[lease_id] = renewed
        runtime = get_fugle_realtime_runtime()
        live = runtime is not None and runtime.connection_status == "connected"
        return ViewerLeaseState(
            lease_id=lease_id,
            stock_id=lease.symbol,
            provider=self.provider_key,
            owner_kind=lease.owner_kind,
            status="live" if live else "degraded",
            expires_in_seconds=self._ttl_seconds,
            fallback_source="resolved_fallback",
            message=(
                "Fugle active-stock租約已續期。"
                if live
                else "Fugle租約仍有效，但stream目前未連線。"
            ),
        )

    def release(self, lease_id: str) -> ViewerLeaseState | None:
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            has_remaining = bool(self._leases)
        if lease is None:
            return None
        runtime = get_fugle_realtime_runtime()
        if runtime is not None and not has_remaining:
            runtime.set_active_stock(None)
        return ViewerLeaseState(
            stock_id=lease.symbol,
            provider=self.provider_key,
            owner_kind=lease.owner_kind,
            status="released",
            fallback_source="resolved_fallback",
            message="Fugle active-stock租約已釋放。",
        )

    def summary(self) -> ViewerLeasePortSummary:
        self._expire()
        with self._lock:
            owners: dict[str, int] = {}
            symbols: dict[str, int] = {}
            for lease in self._leases.values():
                owners[lease.owner_kind] = owners.get(lease.owner_kind, 0) + 1
                symbols[lease.symbol] = symbols.get(lease.symbol, 0) + 1
        runtime = get_fugle_realtime_runtime()
        connected = runtime is not None and runtime.connection_status == "connected"
        return ViewerLeasePortSummary(
            provider=self.provider_key,
            total_active_leases=sum(symbols.values()),
            active_symbol_count=len(symbols),
            leases_by_owner_kind=owners,
            leases_by_symbol=symbols,
            bridge_process_running=connected,
            idle_shutdown_pending=False,
            subscription_worker_count=(
                int(runtime.allocator.snapshot()["bound_count"])
                if runtime is not None
                else 0
            ),
        )


__all__ = ["FugleRealtimeQuoteLeasePort"]
