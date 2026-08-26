"""Market-owned execution of official Taiwan market-index refresh routes."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.market.providers import tpex, twse
from app.market.providers.tw_official_index import (
    TPEX_INDEX_RESOURCE_ID,
    TWSE_INDEX_RESOURCE_ID,
    endpoint_for_index_resource,
    official_index_record_to_observation,
    parse_tpex_official_index_payload,
    parse_twse_official_index_payload,
    parser_version_for_index_resource,
    source_name_for_index_resource,
)
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    MarketIndexObservation,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.gateway import MarketIndexAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import ProviderResourceRouteV2


class HttpResponseLike(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]
    url: Any


RouteFetcher = Callable[[ProviderResourceRouteV2], HttpResponseLike]


@dataclass(frozen=True, slots=True)
class _RouteOutcome:
    receipt: RawFetchReceiptV1 | None
    observations: tuple[MarketIndexObservation, ...]
    health: ProviderResourceHealth
    limitations: tuple[str, ...]
    success: bool


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _default_fetch(route: ProviderResourceRouteV2) -> HttpResponseLike:
    if route.resource_id == TWSE_INDEX_RESOURCE_ID:
        return twse.get_response(
            twse.MARKET_DAILY_URL,
            timeout_seconds=route.timeout_seconds,
        )
    if route.resource_id == TPEX_INDEX_RESOURCE_ID:
        return tpex.get_response(
            tpex.DAILY_INDEX_URL,
            timeout_seconds=route.timeout_seconds,
        )
    raise ValueError(f"unsupported Taiwan official index resource: {route.resource_id}")


def _header(response: HttpResponseLike, name: str) -> str | None:
    for key, value in response.headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def _health(
    route: ProviderResourceRouteV2,
    *,
    checked_at: datetime,
    connection: ConnectionStatus,
    operational: OperationalStatus,
    freshness: EvidenceFreshness,
    detail_code: str,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=route.provider_key,
        market=route.market,
        capability=route.capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=connection,
        entitlement=EntitlementStatus.ENTITLED,
        operational=operational,
        freshness=freshness,
        checked_at=checked_at,
        detail_code=detail_code,
    )


class TaiwanOfficialIndexAcquisitionExecutor:
    """Execute shared planner routes; never persist, select, or fallback."""

    def __init__(
        self,
        *,
        fetchers: Mapping[str, RouteFetcher] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetchers = dict(fetchers or {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic

    def _fetch(self, route: ProviderResourceRouteV2) -> HttpResponseLike:
        return self._fetchers.get(route.resource_id, _default_fetch)(route)

    def _run_route(
        self,
        route: ProviderResourceRouteV2,
        *,
        index_id: str,
        trade_date: date,
    ) -> _RouteOutcome:
        checked_at = self._clock()
        try:
            response = self._fetch(route)
        except Exception as exc:
            return _RouteOutcome(
                receipt=None,
                observations=(),
                health=_health(
                    route,
                    checked_at=checked_at,
                    connection=ConnectionStatus.DISCONNECTED,
                    operational=OperationalStatus.FAILED,
                    freshness=EvidenceFreshness.MISSING,
                    detail_code="PROVIDER_REQUEST_FAILED",
                ),
                limitations=(
                    "PROVIDER_REQUEST_FAILED",
                    f"PROVIDER_ERROR_{type(exc).__name__.upper()}",
                ),
                success=False,
            )
        raw_text = str(response.text or "")
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        fetched_at = self._clock()
        status_code = int(response.status_code)
        receipt = RawFetchReceiptV1(
            provider=route.provider_key,
            source=source_name_for_index_resource(route.resource_id),
            resource_id=route.resource_id,
            fetched_at=fetched_at,
            method="GET",
            url=str(response.url or endpoint_for_index_resource(route.resource_id)),
            status_code=status_code,
            content_type=_header(response, "content-type"),
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=parser_version_for_index_resource(route.resource_id),
            error_message=(
                None if 200 <= status_code < 300 else f"HTTP {status_code}"
            ),
        )
        if not 200 <= status_code < 300:
            return _RouteOutcome(
                receipt=receipt,
                observations=(),
                health=_health(
                    route,
                    checked_at=fetched_at,
                    connection=ConnectionStatus.CONNECTED,
                    operational=(
                        OperationalStatus.RATE_LIMITED
                        if status_code == 429
                        else OperationalStatus.FAILED
                    ),
                    freshness=EvidenceFreshness.MISSING,
                    detail_code=f"HTTP_{status_code}",
                ),
                limitations=(f"HTTP_{status_code}",),
                success=False,
            )
        try:
            if route.resource_id == TWSE_INDEX_RESOURCE_ID:
                parsed = parse_twse_official_index_payload(raw_text)
            elif route.resource_id == TPEX_INDEX_RESOURCE_ID:
                parsed = parse_tpex_official_index_payload(raw_text)
            else:
                raise ValueError(
                    f"unsupported Taiwan official index resource: {route.resource_id}"
                )
            matching = tuple(
                record
                for record in parsed.records
                if record.index_id == index_id and record.trade_date == trade_date
            )
            observations = tuple(
                official_index_record_to_observation(
                    record,
                    provider=route.provider_key,
                    source=receipt.source,
                    parser_version=receipt.parser_version,
                    fetched_at=receipt.fetched_at,
                    content_hash=receipt.content_hash,
                )
                for record in matching
            )
            issue_codes = tuple(issue.reason_code for issue in parsed.issues)
            if not matching:
                issue_codes = (*issue_codes, "TARGET_TRADE_DATE_NOT_FOUND")
            limitations = _unique(issue_codes)
        except Exception as exc:
            return _RouteOutcome(
                receipt=receipt.model_copy(update={"error_message": str(exc)[:2048]}),
                observations=(),
                health=_health(
                    route,
                    checked_at=fetched_at,
                    connection=ConnectionStatus.CONNECTED,
                    operational=OperationalStatus.FAILED,
                    freshness=EvidenceFreshness.MISSING,
                    detail_code="PAYLOAD_PARSE_FAILED",
                ),
                limitations=(
                    "PAYLOAD_PARSE_FAILED",
                    f"PARSER_ERROR_{type(exc).__name__.upper()}",
                ),
                success=False,
            )
        success = bool(observations)
        return _RouteOutcome(
            receipt=receipt,
            observations=observations,
            health=_health(
                route,
                checked_at=fetched_at,
                connection=ConnectionStatus.CONNECTED,
                operational=(
                    OperationalStatus.HEALTHY
                    if success
                    else OperationalStatus.DEGRADED
                ),
                freshness=(
                    EvidenceFreshness.FRESH
                    if success
                    else EvidenceFreshness.MISSING
                ),
                detail_code=(
                    "OFFICIAL_INDEX_ACQUIRED"
                    if success
                    else "OFFICIAL_INDEX_TARGET_MISSING"
                ),
            ),
            limitations=limitations,
            success=success,
        )

    def acquire_routes(
        self,
        *,
        index_id: str,
        trade_date: date,
        routes: Sequence[ProviderResourceRouteV2],
    ) -> MarketIndexAcquisitionResult:
        started_at = self._monotonic()
        outcomes = tuple(
            self._run_route(route, index_id=index_id, trade_date=trade_date)
            for route in routes
        )
        successful = sum(1 for outcome in outcomes if outcome.success)
        if successful == len(outcomes) and outcomes:
            status = AcquisitionStatus.COMPLETED
        elif successful:
            status = AcquisitionStatus.PARTIAL
        else:
            status = AcquisitionStatus.FAILED
        return MarketIndexAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=bool(outcomes),
                status=(status if outcomes else AcquisitionStatus.NOT_ATTEMPTED),
                providers_attempted=tuple(
                    dict.fromkeys(route.provider_key for route in routes)
                ),
                resource_attempts=tuple(
                    AcquisitionResourceAttempt(
                        provider=route.provider_key,
                        resource_id=route.resource_id,
                    )
                    for route in routes
                ),
                external_calls=len(outcomes),
                elapsed_ms=max(int((self._monotonic() - started_at) * 1000), 0),
                limitations=_unique(
                    tuple(
                        limitation
                        for outcome in outcomes
                        for limitation in outcome.limitations
                    )
                ),
            ),
            observations=tuple(
                observation
                for outcome in outcomes
                for observation in outcome.observations
            ),
            receipts=tuple(
                outcome.receipt
                for outcome in outcomes
                if outcome.receipt is not None
            ),
            provider_health=tuple(outcome.health for outcome in outcomes),
        )


__all__ = ["TaiwanOfficialIndexAcquisitionExecutor"]
