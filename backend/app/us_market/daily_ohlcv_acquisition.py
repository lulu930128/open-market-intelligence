"""US-owned execution of Shared Core plans for daily OHLCV.

The executor performs provider I/O and pure canonical conversion only. It does
not select final evidence, persist rows, or own a transaction.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings
from app.market_data.contracts import (
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentType,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.observability.provider_http import provider_http_failure
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import DataAcquisitionPlanV2, ProviderResourceRouteV2
from app.us_market.market_data.descriptors import (
    ALPACA_SIP_DAILY_RESOURCE_ID,
    ALPHAVANTAGE_DAILY_RESOURCE_ID,
    YAHOO_DAILY_RESOURCE_ID,
)
from app.us_market.providers.alpaca import fetch_alpaca_stock_bars_payload
from app.us_market.providers.alphavantage import fetch_alphavantage_daily_payload
from app.us_market.providers.canonical import (
    canonical_alpaca_stock_bars_payload,
    canonical_alphavantage_daily_payload,
    canonical_yahoo_chart_payload,
)
from app.us_market.providers.errors import USProviderDataError
from app.us_market.providers.yahoo import fetch_yahoo_chart_payload


@dataclass(frozen=True, slots=True)
class USProviderPayload:
    payload: Mapping[str, Any]
    url: str


PayloadFetcher = Callable[
    [ProviderResourceRouteV2, DataRequirementV2], USProviderPayload
]


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _health(
    route: ProviderResourceRouteV2,
    *,
    checked_at: datetime,
    connection: ConnectionStatus,
    operational: OperationalStatus,
    freshness: EvidenceFreshness,
    detail_code: str,
    enablement: EnablementStatus = EnablementStatus.ENABLED,
    entitlement: EntitlementStatus = EntitlementStatus.ENTITLED,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=route.provider_key,
        market=route.market,
        capability=route.capability_id,
        resource_id=route.resource_id,
        enablement=enablement,
        connection=connection,
        entitlement=entitlement,
        operational=operational,
        freshness=freshness,
        checked_at=checked_at,
        detail_code=detail_code,
    )


def _failure_health(
    route: ProviderResourceRouteV2,
    *,
    checked_at: datetime,
    error: Exception,
) -> tuple[ProviderResourceHealth, str]:
    if isinstance(error, USProviderDataError):
        code = error.code
        if error.category == "configuration":
            return (
                _health(
                    route,
                    checked_at=checked_at,
                    connection=ConnectionStatus.NOT_APPLICABLE,
                    operational=OperationalStatus.UNAVAILABLE,
                    freshness=EvidenceFreshness.MISSING,
                    detail_code=code,
                    enablement=EnablementStatus.DISABLED,
                    entitlement=EntitlementStatus.UNKNOWN,
                ),
                code,
            )
        if error.category == "auth":
            entitlement = EntitlementStatus.AUTH_FAILED
        elif error.category in {"entitlement", "eligibility"}:
            entitlement = EntitlementStatus.PLAN_RESTRICTED
        else:
            entitlement = EntitlementStatus.UNKNOWN
        operational = (
            OperationalStatus.RATE_LIMITED
            if error.category == "rate_limit"
            else OperationalStatus.FAILED
        )
        return (
            _health(
                route,
                checked_at=checked_at,
                connection=ConnectionStatus.CONNECTED,
                operational=operational,
                freshness=EvidenceFreshness.MISSING,
                detail_code=code,
                entitlement=entitlement,
            ),
            code,
        )

    http_failure = provider_http_failure(error)
    if http_failure is not None:
        status_code = http_failure.http_status_code
        code = (
            f"{route.provider_key.upper()}_RATE_LIMITED"
            if http_failure.rate_limited
            else f"{route.provider_key.upper()}_AUTH_FAILED"
            if status_code == 401
            else f"{route.provider_key.upper()}_PLAN_RESTRICTED"
            if status_code == 403
            else f"{route.provider_key.upper()}_REQUEST_FAILED"
        )
        return (
            _health(
                route,
                checked_at=checked_at,
                connection=(
                    ConnectionStatus.DISCONNECTED
                    if http_failure.status in {"timeout", "error"}
                    else ConnectionStatus.CONNECTED
                ),
                operational=(
                    OperationalStatus.RATE_LIMITED
                    if http_failure.rate_limited
                    else OperationalStatus.FAILED
                ),
                freshness=EvidenceFreshness.MISSING,
                detail_code=code,
                entitlement=(
                    EntitlementStatus.AUTH_FAILED
                    if status_code == 401
                    else EntitlementStatus.PLAN_RESTRICTED
                    if status_code == 403
                    else EntitlementStatus.UNKNOWN
                ),
            ),
            code,
        )

    return (
        _health(
            route,
            checked_at=checked_at,
            connection=ConnectionStatus.DISCONNECTED,
            operational=OperationalStatus.FAILED,
            freshness=EvidenceFreshness.MISSING,
            detail_code="PROVIDER_REQUEST_FAILED",
            entitlement=EntitlementStatus.UNKNOWN,
        ),
        "PROVIDER_REQUEST_FAILED",
    )


def _completed_daily_temporal_requirement_satisfied(
    request: BarCapabilityRequest,
    bars: tuple[BarObservation, ...],
) -> bool:
    expected_date = request.end_at.date()
    return any(
        bar.end_at.date() == expected_date
        and bar.finalization in {BarFinalization.FINAL, BarFinalization.CORRECTED}
        and (
            bar.volume_status == "not_applicable"
            if bar.instrument.instrument_type is InstrumentType.INDEX
            else bar.volume_status == "observed"
        )
        for bar in bars
    )


def _completed_daily_requirement_satisfied(
    request: BarCapabilityRequest,
    bars: tuple[BarObservation, ...],
    *,
    limitations: tuple[str, ...] = (),
) -> bool:
    if not _completed_daily_temporal_requirement_satisfied(request, bars):
        return False
    if request.coverage is None:
        return True
    return (
        len(bars) >= request.coverage.minimum_bar_count
        and "ALPACA_PAGINATION_TRUNCATED" not in limitations
    )


class USDailyOhlcvAcquisitionExecutor:
    def __init__(
        self,
        *,
        fetchers: Mapping[str, PayloadFetcher] | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetchers = dict(fetchers or {})
        self._settings = settings or Settings()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic

    def _fetch(
        self,
        route: ProviderResourceRouteV2,
        requirement: DataRequirementV2,
    ) -> USProviderPayload:
        injected = self._fetchers.get(route.resource_id)
        if injected is not None:
            return injected(route, requirement)
        assert isinstance(requirement.target, InstrumentTarget)
        assert isinstance(requirement.request, BarCapabilityRequest)
        symbol = requirement.target.instrument.symbol
        if route.resource_id == YAHOO_DAILY_RESOURCE_ID:
            payload, url = fetch_yahoo_chart_payload(
                symbol=symbol,
                range_value="10y",
                interval="1d",
                timeout_seconds=route.timeout_seconds,
                resource="daily_price_shared_core",
            )
            return USProviderPayload(payload=payload, url=url)
        if route.resource_id == ALPACA_SIP_DAILY_RESOURCE_ID:
            api_key_id = str(self._settings.alpaca_api_key_id or "").strip()
            api_secret_key = str(self._settings.alpaca_api_secret_key or "").strip()
            if not api_key_id or not api_secret_key:
                raise USProviderDataError(
                    provider="alpaca",
                    code="ALPACA_CREDENTIALS_NOT_CONFIGURED",
                    category="configuration",
                    message="Alpaca credentials are not configured.",
                )
            eligible_before = self._clock() - timedelta(minutes=15)
            if requirement.request.end_at > eligible_before:
                raise USProviderDataError(
                    provider="alpaca",
                    code="ALPACA_SIP_DELAY_WINDOW_NOT_ELIGIBLE",
                    category="eligibility",
                    message="Requested SIP evidence is inside the free-plan delay window.",
                )
            payload, url = fetch_alpaca_stock_bars_payload(
                symbol=symbol,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                timeframe="1Day",
                start=requirement.request.start_at,
                end=requirement.request.end_at,
                limit=min(10_000, max(requirement.request.max_bars * 6, 30)),
                feed="sip",
                adjustment="raw",
                sort="asc",
                timeout_seconds=route.timeout_seconds,
            )
            return USProviderPayload(payload=payload, url=url)
        if route.resource_id == ALPHAVANTAGE_DAILY_RESOURCE_ID:
            api_key = self._settings.alphavantage_api_key
            if not api_key:
                raise RuntimeError("Alpha Vantage API key is not configured")
            range_days = (
                requirement.request.end_at.date()
                - requirement.request.start_at.date()
            ).days + 1
            payload, url = fetch_alphavantage_daily_payload(
                symbol=symbol,
                api_key=api_key,
                outputsize="full" if range_days > 100 else "compact",
                adjusted=False,
                timeout_seconds=route.timeout_seconds,
            )
            return USProviderPayload(payload=payload, url=url)
        raise ValueError(f"unsupported US daily resource: {route.resource_id}")

    def acquire_bar_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> BarAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("shared acquisition plan does not match requirement")
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("US daily acquisition requires an instrument target")
        if not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("US daily acquisition requires a bar request")
        request = requirement.request
        if request.capability_id != "daily.ohlcv" or request.interval != "1d":
            raise ValueError("US daily acquisition supports daily.ohlcv interval=1d")

        started_at = self._monotonic()
        attempts: list[AcquisitionResourceAttempt] = []
        receipts: list[RawFetchReceiptV1] = []
        observations: list[BarObservation] = []
        health: list[ProviderResourceHealth] = []
        limitations: list[str] = []
        failures = 0

        for route in plan.routes:
            attempts.append(
                AcquisitionResourceAttempt(
                    provider=route.provider_key,
                    resource_id=route.resource_id,
                )
            )
            checked_at = self._clock()
            try:
                fetched = self._fetch(route, requirement)
                raw_text = json.dumps(
                    fetched.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
                fetched_at = self._clock()
                if route.resource_id == YAHOO_DAILY_RESOURCE_ID:
                    batch = canonical_yahoo_chart_payload(
                        instrument=requirement.target.instrument,
                        payload=fetched.payload,
                        fetched_at=fetched_at,
                        interval="1d",
                    )
                elif route.resource_id == ALPACA_SIP_DAILY_RESOURCE_ID:
                    batch = canonical_alpaca_stock_bars_payload(
                        instrument=requirement.target.instrument,
                        payload=fetched.payload,
                        fetched_at=fetched_at,
                    )
                elif route.resource_id == ALPHAVANTAGE_DAILY_RESOURCE_ID:
                    batch = canonical_alphavantage_daily_payload(
                        instrument=requirement.target.instrument,
                        payload=fetched.payload,
                        fetched_at=fetched_at,
                    )
                else:
                    raise ValueError(f"unsupported US daily resource: {route.resource_id}")
                bars = tuple(
                    bar.model_copy(
                        update={
                            "lineage": bar.lineage.model_copy(
                                update={"content_hash": content_hash}
                            )
                        }
                    )
                    for bar in batch.bars
                    if request.start_at.date()
                    <= bar.start_at.date()
                    <= request.end_at.date()
                )
                source = (
                    bars[0].lineage.source
                    if bars
                    else (
                        "yahoo.chart.1d"
                        if route.resource_id == YAHOO_DAILY_RESOURCE_ID
                        else "alpaca.sip.stock_bars.1d"
                        if route.resource_id == ALPACA_SIP_DAILY_RESOURCE_ID
                        else "alphavantage.time_series_daily"
                    )
                )
                parser_version = (
                    bars[0].lineage.raw_contract_version
                    if bars
                    else (
                        "yahoo.chart.v8"
                        if route.resource_id == YAHOO_DAILY_RESOURCE_ID
                        else "alpaca.stock_bars.v2"
                        if route.resource_id == ALPACA_SIP_DAILY_RESOURCE_ID
                        else "alphavantage.daily.v1"
                    )
                )
                receipts.append(
                    RawFetchReceiptV1(
                        provider=route.provider_key,
                        source=source,
                        resource_id=route.resource_id,
                        fetched_at=fetched_at,
                        method="GET",
                        url=fetched.url,
                        status_code=200,
                        content_type="application/json",
                        content_hash=content_hash,
                        raw_text=raw_text,
                        parser_version=parser_version,
                    )
                )
                observations.extend(bars)
                limitations.extend(route.limitations)
                limitations.extend(batch.limitations)
                requirement_satisfied = _completed_daily_requirement_satisfied(
                    request,
                    bars,
                    limitations=batch.limitations,
                )
                if not bars:
                    failures += 1
                    limitations.append("REQUESTED_RANGE_NOT_OBSERVED")
                elif not requirement_satisfied:
                    failures += 1
                    if not _completed_daily_temporal_requirement_satisfied(request, bars):
                        limitations.append("EXPECTED_SESSION_NOT_OBSERVED")
                    elif (
                        request.coverage is not None
                        and len(bars) < request.coverage.minimum_bar_count
                    ):
                        limitations.append("REQUESTED_HISTORY_COVERAGE_NOT_OBSERVED")
                    elif "ALPACA_PAGINATION_TRUNCATED" not in limitations:
                        limitations.append("HISTORY_COVERAGE_NOT_PROVEN_COMPLETE")
                health.append(
                    _health(
                        route,
                        checked_at=fetched_at,
                        connection=ConnectionStatus.CONNECTED,
                        operational=(
                            OperationalStatus.HEALTHY
                            if requirement_satisfied
                            else OperationalStatus.DEGRADED
                        ),
                        freshness=(
                            EvidenceFreshness.FRESH
                            if requirement_satisfied
                            else (
                                EvidenceFreshness.STALE
                                if bars
                                else EvidenceFreshness.MISSING
                            )
                        ),
                        detail_code=(
                            "US_DAILY_OBSERVED"
                            if requirement_satisfied
                            else (
                                "REQUESTED_RANGE_NOT_OBSERVED"
                                if not bars
                                else "EXPECTED_SESSION_NOT_OBSERVED"
                                if not _completed_daily_temporal_requirement_satisfied(
                                    request, bars
                                )
                                else "REQUESTED_HISTORY_COVERAGE_NOT_OBSERVED"
                            )
                        ),
                    )
                )
                if requirement_satisfied:
                    break
            except Exception as exc:
                failures += 1
                failure_health, failure_code = _failure_health(
                    route,
                    checked_at=checked_at,
                    error=exc,
                )
                limitations.append(failure_code)
                health.append(failure_health)

        if observations:
            status = AcquisitionStatus.PARTIAL if failures else AcquisitionStatus.COMPLETED
        elif attempts:
            status = AcquisitionStatus.FAILED
        else:
            status = AcquisitionStatus.NOT_ATTEMPTED
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=bool(attempts),
                status=status,
                providers_attempted=tuple(
                    dict.fromkeys(item.provider for item in attempts)
                ),
                resource_attempts=tuple(attempts),
                external_calls=len(attempts),
                subscriptions_created=0,
                elapsed_ms=max(0, int((self._monotonic() - started_at) * 1000)),
                limitations=_unique(limitations),
            ),
            observations=tuple(observations),
            receipts=tuple(receipts),
            provider_health=tuple(health),
        )


__all__ = [
    "PayloadFetcher",
    "USDailyOhlcvAcquisitionExecutor",
    "USProviderPayload",
]
