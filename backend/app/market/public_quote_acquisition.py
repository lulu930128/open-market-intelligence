"""Bounded TWSE MIS public quote acquisition for shared Gateway plans."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.market.providers import twse_mis
from app.market.providers.twse_mis_guard import (
    TWSE_MIS_PROVIDER_GUARD,
    TwseMisProviderGuard,
    response_failure_metadata,
)
from app.market.providers.tw_public_quote import (
    TWSE_MIS_QUOTE_PARSER_VERSION,
    endpoint_for_instrument,
    exchange_code_for_venue,
    parse_twse_mis_quote_payload,
    quote_observation_from_twse_mis,
)
from app.market.tw_public_quote_contract import (
    TWSE_MIS_QUOTE_RESOURCE_ID,
    TWSE_MIS_QUOTE_SOURCE_NAME,
)
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
    QuoteObservation,
)
from app.market_data.gateway import QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import (
    DataAcquisitionPlanV2,
    ProviderResourceRouteV2,
)


class HttpResponseLike(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]
    url: Any


RouteFetcher = Callable[
    [ProviderResourceRouteV2, InstrumentKey],
    HttpResponseLike,
]


@dataclass(frozen=True, slots=True)
class _QuoteRouteOutcome:
    receipt: RawFetchReceiptV1
    observation: QuoteObservation | None
    health: ProviderResourceHealth
    limitations: tuple[str, ...]
    external_calls: int = 1


def _header(response: HttpResponseLike, name: str) -> str | None:
    for key, value in response.headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _default_fetch(
    route: ProviderResourceRouteV2,
    instrument: InstrumentKey,
) -> HttpResponseLike:
    if route.resource_id != TWSE_MIS_QUOTE_RESOURCE_ID:
        raise ValueError(f"unsupported public quote resource: {route.resource_id}")
    return twse_mis.get_stock_response(
        [instrument.symbol],
        exchange=exchange_code_for_venue(instrument.venue),
        timeout_seconds=route.timeout_seconds,
    )


def _health(
    route: ProviderResourceRouteV2,
    *,
    checked_at: datetime,
    connection: ConnectionStatus,
    entitlement: EntitlementStatus = EntitlementStatus.ENTITLED,
    operational: OperationalStatus,
    freshness: EvidenceFreshness,
    detail_code: str,
    retry_after_seconds: int | None = None,
    cooldown_until: datetime | None = None,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=route.provider_key,
        market=route.market,
        capability=route.capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=connection,
        entitlement=entitlement,
        operational=operational,
        freshness=freshness,
        checked_at=checked_at,
        detail_code=detail_code,
        retry_after_seconds=retry_after_seconds,
        cooldown_until=cooldown_until,
    )


class TaiwanPublicQuoteAcquisitionExecutor:
    """Execute one shared public quote route; never persist or select fallback."""

    def __init__(
        self,
        *,
        fetchers: Mapping[str, RouteFetcher] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        provider_guard: TwseMisProviderGuard | None = None,
    ) -> None:
        self._fetchers = dict(fetchers or {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._provider_guard = provider_guard or (
            TwseMisProviderGuard() if fetchers else TWSE_MIS_PROVIDER_GUARD
        )

    def _fetch(
        self,
        route: ProviderResourceRouteV2,
        instrument: InstrumentKey,
    ) -> HttpResponseLike:
        return self._fetchers.get(route.resource_id, _default_fetch)(
            route,
            instrument,
        )

    def _failure_receipt(
        self,
        route: ProviderResourceRouteV2,
        instrument: InstrumentKey,
        *,
        fetched_at: datetime,
        error: Exception,
    ) -> RawFetchReceiptV1:
        return RawFetchReceiptV1(
            provider=route.provider_key,
            source=TWSE_MIS_QUOTE_SOURCE_NAME,
            resource_id=route.resource_id,
            fetched_at=fetched_at,
            method="GET",
            url=endpoint_for_instrument(instrument),
            status_code=None,
            content_type=None,
            content_hash=hashlib.sha256(b"").hexdigest(),
            raw_text=None,
            parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
            error_message=f"{type(error).__name__}: {error}"[:2048],
        )

    def _run_route(
        self,
        route: ProviderResourceRouteV2,
        *,
        instrument: InstrumentKey,
        session: MarketSession,
    ) -> _QuoteRouteOutcome:
        guard = self._provider_guard.before_request()
        if not guard.allowed:
            sampled_at = self._clock()
            error = RuntimeError(guard.detail_code)
            return _QuoteRouteOutcome(
                receipt=self._failure_receipt(
                    route,
                    instrument,
                    fetched_at=sampled_at,
                    error=error,
                ),
                observation=None,
                health=_health(
                    route,
                    checked_at=sampled_at,
                    connection=ConnectionStatus.DISCONNECTED,
                    operational=(
                        OperationalStatus.RATE_LIMITED
                        if guard.status == "rate_limited"
                        else OperationalStatus.UNAVAILABLE
                    ),
                    freshness=EvidenceFreshness.MISSING,
                    detail_code=guard.detail_code,
                    retry_after_seconds=guard.retry_after_seconds,
                    cooldown_until=guard.cooldown_until,
                ),
                limitations=(guard.detail_code,),
                external_calls=0,
            )
        try:
            response = self._fetch(route, instrument)
        except Exception as exc:
            failed_at = self._clock()
            status_code, headers = response_failure_metadata(exc)
            guard = (
                self._provider_guard.record_http_failure(
                    status_code,
                    headers=headers,
                )
                if status_code is not None
                else self._provider_guard.record_failure(
                    detail_code=f"TWSE_MIS_{type(exc).__name__.upper()}"
                )
            )
            return _QuoteRouteOutcome(
                receipt=self._failure_receipt(
                    route,
                    instrument,
                    fetched_at=failed_at,
                    error=exc,
                ),
                observation=None,
                health=_health(
                    route,
                    checked_at=failed_at,
                    connection=ConnectionStatus.DISCONNECTED,
                    operational=(
                        OperationalStatus.RATE_LIMITED
                        if status_code == 429
                        else OperationalStatus.FAILED
                    ),
                    freshness=EvidenceFreshness.MISSING,
                    detail_code=guard.detail_code,
                    retry_after_seconds=guard.retry_after_seconds,
                    cooldown_until=guard.cooldown_until,
                ),
                limitations=(
                    "PROVIDER_REQUEST_FAILED",
                    f"PROVIDER_ERROR_{type(exc).__name__.upper()}",
                ),
            )

        received_at = self._clock()
        raw_text = str(response.text or "")
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        status_code = int(response.status_code)
        receipt = RawFetchReceiptV1(
            provider=route.provider_key,
            source=TWSE_MIS_QUOTE_SOURCE_NAME,
            resource_id=route.resource_id,
            fetched_at=received_at,
            method="GET",
            url=str(response.url or endpoint_for_instrument(instrument)),
            status_code=status_code,
            content_type=_header(response, "content-type"),
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
            error_message=(
                None if 200 <= status_code < 300 else f"HTTP {status_code}"
            ),
        )
        if not 200 <= status_code < 300:
            guard = self._provider_guard.record_http_failure(
                status_code,
                headers=response.headers,
            )
            entitlement = (
                EntitlementStatus.AUTH_FAILED
                if status_code == 401
                else EntitlementStatus.PLAN_RESTRICTED
                if status_code == 403
                else EntitlementStatus.ENTITLED
            )
            operational = (
                OperationalStatus.RATE_LIMITED
                if status_code == 429
                else OperationalStatus.FAILED
            )
            return _QuoteRouteOutcome(
                receipt=receipt,
                observation=None,
                health=_health(
                    route,
                    checked_at=received_at,
                    connection=ConnectionStatus.CONNECTED,
                    entitlement=entitlement,
                    operational=operational,
                    freshness=EvidenceFreshness.MISSING,
                    detail_code=guard.detail_code,
                    retry_after_seconds=guard.retry_after_seconds,
                    cooldown_until=guard.cooldown_until,
                ),
                limitations=(f"HTTP_{status_code}",),
            )

        try:
            message = parse_twse_mis_quote_payload(
                raw_text,
                target_symbol=instrument.symbol,
            )
            observation = quote_observation_from_twse_mis(
                instrument=instrument,
                message=message,
                session=session,
                received_at=received_at,
                fetched_at=receipt.fetched_at,
                content_hash=receipt.content_hash,
            )
        except Exception as exc:
            self._provider_guard.record_failure(
                detail_code="TWSE_MIS_PAYLOAD_PARSE_FAILED"
            )
            error_receipt = receipt.model_copy(
                update={"error_message": str(exc)[:2048]}
            )
            return _QuoteRouteOutcome(
                receipt=error_receipt,
                observation=None,
                health=_health(
                    route,
                    checked_at=received_at,
                    connection=ConnectionStatus.CONNECTED,
                    operational=OperationalStatus.FAILED,
                    freshness=EvidenceFreshness.MISSING,
                    detail_code="PAYLOAD_PARSE_FAILED",
                ),
                limitations=(
                    "PAYLOAD_PARSE_FAILED",
                    f"PARSER_ERROR_{type(exc).__name__.upper()}",
                ),
            )

        self._provider_guard.record_success()
        has_actual_trade = observation.last_trade_price is not None
        completed_session_observation = session in {
            MarketSession.CLOSE_RESOLUTION,
            MarketSession.POST_CLOSE,
            MarketSession.CLOSED,
        }
        return _QuoteRouteOutcome(
            receipt=receipt,
            observation=observation,
            health=_health(
                route,
                checked_at=received_at,
                connection=ConnectionStatus.CONNECTED,
                operational=(
                    OperationalStatus.HEALTHY
                    if has_actual_trade
                    else OperationalStatus.DEGRADED
                ),
                freshness=(
                    EvidenceFreshness.FRESH
                    if has_actual_trade and completed_session_observation
                    else EvidenceFreshness.LIVE
                    if has_actual_trade
                    else EvidenceFreshness.FRESH
                ),
                detail_code=(
                    "ACTUAL_LAST_TRADE_OBSERVED"
                    if has_actual_trade
                    else "ACTUAL_LAST_TRADE_MISSING"
                ),
            ),
            limitations=(
                () if has_actual_trade else ("ACTUAL_LAST_TRADE_MISSING",)
            ),
        )

    def acquire_quote_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> QuoteAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("shared acquisition plan does not match requirement")
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("public quote acquisition requires instrument target")
        if len(plan.routes) > 1:
            raise ValueError("public quote acquisition is bounded to one route")
        started_at = self._monotonic()
        outcomes = tuple(
            self._run_route(
                route,
                instrument=requirement.target.instrument,
                session=requirement.session,
            )
            for route in plan.routes
        )
        observations = tuple(
            outcome.observation
            for outcome in outcomes
            if outcome.observation is not None
        )
        if observations and all(
            observation.last_trade_price is not None
            for observation in observations
        ):
            status = AcquisitionStatus.COMPLETED
        elif observations:
            status = AcquisitionStatus.PARTIAL
        elif outcomes:
            status = AcquisitionStatus.FAILED
        else:
            status = AcquisitionStatus.NOT_ATTEMPTED
        limitations = _unique(
            tuple(
                limitation
                for route, outcome in zip(plan.routes, outcomes)
                for limitation in (*route.limitations, *outcome.limitations)
            )
        )
        return QuoteAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=bool(outcomes),
                status=status,
                providers_attempted=tuple(
                    route.provider_key for route in plan.routes
                ),
                resource_attempts=tuple(
                    AcquisitionResourceAttempt(
                        provider=route.provider_key,
                        resource_id=route.resource_id,
                    )
                    for route in plan.routes
                ),
                external_calls=sum(outcome.external_calls for outcome in outcomes),
                subscriptions_created=0,
                elapsed_ms=max(
                    int((self._monotonic() - started_at) * 1000),
                    0,
                ),
                limitations=limitations,
            ),
            observations=observations,
            receipts=tuple(outcome.receipt for outcome in outcomes),
            provider_health=tuple(outcome.health for outcome in outcomes),
        )


__all__ = [
    "HttpResponseLike",
    "RouteFetcher",
    "TaiwanPublicQuoteAcquisitionExecutor",
]
