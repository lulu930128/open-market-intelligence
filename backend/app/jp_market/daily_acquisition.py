"""Bounded JP acquisition port. Provider choice belongs to the shared plan."""

from datetime import datetime, timezone
import time

from app.config import settings
from app.jp_market.market_data.adapters import adapt_jquants_daily, adapt_yahoo_daily
from app.jp_market.providers.jquants import fetch_jquants_daily_payload
from app.jp_market.providers.yahoo import fetch_yahoo_chart_payload
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE
from app.market_data.contracts import (
    ConnectionStatus, EnablementStatus, EntitlementStatus, EvidenceFreshness,
    Market, OperationalStatus, ProviderResourceHealth,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt, AcquisitionStatus, AcquisitionSummary,
    BarCapabilityRequest, DataRequirementV2, InstrumentTarget,
)
from app.market_data.provider_catalog import DataAcquisitionPlanV2
from app.market_data.policies import allows_external_acquisition


def _http_status(exc: Exception) -> int | None:
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "http_status_code", None)
        if status is not None:
            return status
        response = getattr(current, "response", None)
        if response is not None:
            return response.status_code
        current = current.__cause__
    return None


class JPDailyAcquisition:
    def __init__(self, *, fetchers=None, clock=None, monotonic=None) -> None:
        self.fetchers = fetchers or {}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic

    def _fetch(self, route, requirement):
        if route.provider_key in self.fetchers:
            return self.fetchers[route.provider_key](route, requirement)
        instrument = requirement.target.instrument
        request = requirement.request
        if route.provider_key == "yahoo_chart":
            days = (request.end_at - request.start_at).days
            return fetch_yahoo_chart_payload(
                symbol=instrument.symbol, interval="1d",
                range_value=("1y" if days <= 365 else "2y" if days <= 730
                             else "5y" if days <= 1826 else "10y"),
                timeout_seconds=route.timeout_seconds,
            )
        if route.provider_key == "jquants":
            return fetch_jquants_daily_payload(
                base_url=settings.jquants_api_base_url, api_key=settings.jquants_api_key or "",
                local_code=instrument.symbol.removesuffix(".T"),
                from_date=request.start_at.astimezone(JP_MARKET_TIMEZONE).date(),
                to_date=request.end_at.astimezone(JP_MARKET_TIMEZONE).date(),
                timeout_seconds=route.timeout_seconds,
            )
        raise ValueError("Unregistered JP acquisition route")

    def acquire_bar_observations(self, requirement: DataRequirementV2,
                                 plan: DataAcquisitionPlanV2) -> BarAcquisitionResult:
        if (not isinstance(requirement.target, InstrumentTarget)
                or requirement.target.instrument.market is not Market.JP
                or not isinstance(requirement.request, BarCapabilityRequest)
                or requirement.request.capability_id != "daily.ohlcv"
                or requirement.request.price_basis != "raw"
                or not allows_external_acquisition(requirement.realtime_policy)
                or requirement.bounds.max_external_calls == 0):
            raise ValueError("JP acquisition requires an authorized bounded daily requirement")
        started = self.monotonic()
        attempts, receipts, observations, health, limitations = [], [], [], [], []
        for route in plan.routes:
            if len(attempts) >= min(requirement.bounds.max_external_calls, requirement.bounds.max_provider_attempts):
                limitations.append("ACQUISITION_BOUND_REACHED")
                break
            remaining = requirement.bounds.timeout_seconds - (self.monotonic() - started)
            if remaining < 1:
                limitations.append("ACQUISITION_DEADLINE_REACHED")
                break
            route = route.model_copy(update={"timeout_seconds": min(route.timeout_seconds, int(remaining))})
            if not route.fetch_allowed or route.max_external_calls < 1:
                raise ValueError("JP acquisition received a non-fetch route")
            attempts.append(AcquisitionResourceAttempt(provider=route.provider_key, resource_id=route.resource_id))
            status_code = None
            try:
                payload, url = self._fetch(route, requirement)
                fetched_at = self.clock()
                if route.provider_key == "jquants":
                    result = adapt_jquants_daily(
                        payload, instrument=requirement.target.instrument, fetched_at=fetched_at, url=url,
                        start_date=requirement.request.start_at.astimezone(JP_MARKET_TIMEZONE).date(),
                        end_date=requirement.request.end_at.astimezone(JP_MARKET_TIMEZONE).date(),
                    )
                else:
                    result = adapt_yahoo_daily(payload, instrument=requirement.target.instrument, fetched_at=fetched_at, url=url)
                receipts.append(result.receipt)
                bars = tuple(bar for bar in result.bars if requirement.request.start_at <= bar.start_at and bar.end_at <= requirement.request.end_at)
                observations.extend(bars)
                reasons = tuple(reason for _, reason in result.rejections)
                limitations.extend(reasons)
                if not bars:
                    limitations.append("EMPTY_CANONICAL_CANDIDATES")
                detail = reasons[0] if reasons else "DAILY_CANDIDATES_ACQUIRED" if bars else "EMPTY_CANONICAL_CANDIDATES"
                operational = OperationalStatus.HEALTHY if bars and not reasons else OperationalStatus.DEGRADED
                connection, entitlement = ConnectionStatus.CONNECTED, EntitlementStatus.ENTITLED
                freshness = EvidenceFreshness.FRESH if bars and bars[-1].end_at == requirement.request.end_at else EvidenceFreshness.STALE if bars else EvidenceFreshness.MISSING
            except Exception as exc:
                # Never expose exception text: provider failures may contain credentials.
                status_code = _http_status(exc)
                detail = {401: "AUTH_FAILED", 403: "PLAN_RESTRICTED", 429: "RATE_LIMITED"}.get(status_code, "PROVIDER_REQUEST_FAILED")
                limitations.append(detail)
                operational = OperationalStatus.RATE_LIMITED if status_code == 429 else OperationalStatus.FAILED
                connection = ConnectionStatus.CONNECTED if status_code is not None else ConnectionStatus.UNKNOWN
                entitlement = EntitlementStatus.AUTH_FAILED if status_code == 401 else EntitlementStatus.PLAN_RESTRICTED if status_code == 403 else EntitlementStatus.UNKNOWN
                freshness = EvidenceFreshness.UNKNOWN
            health.append(ProviderResourceHealth(
                provider=route.provider_key, market=Market.JP, capability="daily.ohlcv", resource_id=route.resource_id,
                enablement=EnablementStatus.ENABLED, connection=connection, entitlement=entitlement,
                operational=operational, freshness=freshness, checked_at=self.clock(), detail_code=detail,
            ))
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=bool(attempts),
                status=(AcquisitionStatus.PARTIAL if limitations else AcquisitionStatus.COMPLETED)
                if observations else AcquisitionStatus.FAILED if attempts else AcquisitionStatus.NOT_ATTEMPTED,
                providers_attempted=tuple(dict.fromkeys(a.provider for a in attempts)),
                resource_attempts=tuple(attempts), external_calls=len(attempts),
                elapsed_ms=max(0, int((self.monotonic() - started) * 1000)),
                limitations=tuple(dict.fromkeys(limitations)),
            ),
            observations=tuple(observations), receipts=tuple(receipts), provider_health=tuple(health),
        )
