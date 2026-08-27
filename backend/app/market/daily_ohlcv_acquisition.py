"""Market-owned execution of shared plans for official Taiwan daily bars."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.market.providers import tpex, twse
from app.market.providers.tw_official_daily import (
    TPEX_DAILY_RESOURCE_ID,
    TWSE_DAILY_RESOURCE_ID,
    TWSE_RWD_DAILY_RESOURCE_ID,
    endpoint_for_resource,
    official_daily_record_to_bar,
    parse_tpex_official_daily_payload,
    parse_twse_rwd_official_daily_payload,
    parse_twse_official_daily_payload,
    parser_version_for_resource,
    source_name_for_resource,
)
from app.market_data.contracts import (
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.gateway import BarAcquisitionResult
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


RouteFetcher = Callable[[ProviderResourceRouteV2], HttpResponseLike]


@dataclass(frozen=True, slots=True)
class _RouteOutcome:
    receipt: RawFetchReceiptV1 | None
    bars: tuple[BarObservation, ...]
    health: ProviderResourceHealth
    limitations: tuple[str, ...]
    success: bool


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _default_fetch(
    route: ProviderResourceRouteV2,
    *,
    trade_date: date | None,
) -> HttpResponseLike:
    if route.resource_id == TWSE_DAILY_RESOURCE_ID:
        return twse.get_response(
            twse.DAILY_QUOTES_URL,
            timeout_seconds=route.timeout_seconds,
        )
    if route.resource_id == TWSE_RWD_DAILY_RESOURCE_ID:
        if trade_date is None:
            raise ValueError("TWSE RWD official daily acquisition requires trade_date")
        return twse.get_response(
            twse.RWD_MI_INDEX_URL,
            timeout_seconds=route.timeout_seconds,
            params={
                "date": trade_date.strftime("%Y%m%d"),
                "type": "ALLBUT0999",
                "response": "json",
            },
        )
    if route.resource_id == TPEX_DAILY_RESOURCE_ID:
        return tpex.get_response(
            tpex.DAILY_QUOTES_URL,
            timeout_seconds=route.timeout_seconds,
        )
    raise ValueError(f"unsupported Taiwan official daily resource: {route.resource_id}")


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


class TaiwanOfficialDailyAcquisitionExecutor:
    """Execute only routes selected by the shared planner; never persist or resolve."""

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

    def _fetch(
        self,
        route: ProviderResourceRouteV2,
        *,
        trade_date: date | None,
    ) -> HttpResponseLike:
        fetcher = self._fetchers.get(route.resource_id)
        if fetcher is not None:
            return fetcher(route)
        return _default_fetch(route, trade_date=trade_date)

    def _run_route(
        self,
        route: ProviderResourceRouteV2,
        *,
        instruments: Mapping[str, InstrumentKey],
        trade_date: date | None,
    ) -> _RouteOutcome:
        checked_at = self._clock()
        try:
            response = self._fetch(route, trade_date=trade_date)
        except Exception as exc:
            return _RouteOutcome(
                receipt=None,
                bars=(),
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
            source=source_name_for_resource(route.resource_id),
            resource_id=route.resource_id,
            fetched_at=fetched_at,
            method="GET",
            url=str(response.url or endpoint_for_resource(route.resource_id)),
            status_code=status_code,
            content_type=_header(response, "content-type"),
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=parser_version_for_resource(route.resource_id),
            error_message=(
                None if 200 <= status_code < 300 else f"HTTP {status_code}"
            ),
        )
        if not 200 <= status_code < 300:
            return _RouteOutcome(
                receipt=receipt,
                bars=(),
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
            target_symbols = frozenset(instruments)
            if route.resource_id == TWSE_DAILY_RESOURCE_ID:
                parsed = parse_twse_official_daily_payload(
                    raw_text,
                    target_symbols=target_symbols,
                )
            elif route.resource_id == TWSE_RWD_DAILY_RESOURCE_ID:
                parsed = parse_twse_rwd_official_daily_payload(
                    raw_text,
                    target_symbols=target_symbols,
                )
            elif route.resource_id == TPEX_DAILY_RESOURCE_ID:
                parsed = parse_tpex_official_daily_payload(
                    raw_text,
                    target_symbols=target_symbols,
                )
            else:
                raise ValueError(
                    f"unsupported Taiwan official daily resource: {route.resource_id}"
                )
            date_records = tuple(
                record
                for record in parsed.records
                if trade_date is None or record.trade_date == trade_date
            )
            bars = tuple(
                official_daily_record_to_bar(
                    record,
                    instrument=instruments[record.symbol],
                    provider=route.provider_key,
                    source=receipt.source,
                    parser_version=receipt.parser_version,
                    fetched_at=receipt.fetched_at,
                    content_hash=receipt.content_hash,
                )
                for record in date_records
            )
            limitations = _unique(
                (
                    *tuple(issue.reason_code for issue in parsed.issues),
                    *(
                        ("EXPECTED_TRADE_DATE_NOT_OBSERVED",)
                        if trade_date is not None and not date_records
                        else ()
                    ),
                )
            )
        except Exception as exc:
            return _RouteOutcome(
                receipt=receipt.model_copy(update={"error_message": str(exc)[:2048]}),
                bars=(),
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

        success = bool(bars)
        return _RouteOutcome(
            receipt=receipt,
            bars=bars,
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
                    EvidenceFreshness.FRESH if success else EvidenceFreshness.MISSING
                ),
                detail_code=(
                    "OFFICIAL_DAILY_OBSERVED"
                    if success
                    else "TARGET_SYMBOL_NOT_OBSERVED"
                ),
            ),
            limitations=limitations,
            success=success,
        )

    def acquire_routes(
        self,
        instrument: InstrumentKey,
        routes: Sequence[ProviderResourceRouteV2],
        *,
        trade_date: date | None = None,
    ) -> BarAcquisitionResult:
        return self.acquire_dataset_routes(
            {instrument.symbol: instrument},
            routes,
            trade_date=trade_date,
        )

    def acquire_dataset_routes(
        self,
        instruments: Mapping[str, InstrumentKey],
        routes: Sequence[ProviderResourceRouteV2],
        *,
        trade_date: date | None,
    ) -> BarAcquisitionResult:
        if not instruments:
            raise ValueError("official daily dataset acquisition requires instruments")
        started_at = self._monotonic()
        attempts: list[AcquisitionResourceAttempt] = []
        receipts: list[RawFetchReceiptV1] = []
        bars: list[BarObservation] = []
        health: list[ProviderResourceHealth] = []
        limitations: list[str] = []
        had_failure = False

        for route in routes:
            attempts.append(
                AcquisitionResourceAttempt(
                    provider=route.provider_key,
                    resource_id=route.resource_id,
                )
            )
            outcome = self._run_route(
                route,
                instruments=instruments,
                trade_date=trade_date,
            )
            if outcome.receipt is not None:
                receipts.append(outcome.receipt)
            bars.extend(outcome.bars)
            health.append(outcome.health)
            limitations.extend(route.limitations)
            limitations.extend(outcome.limitations)
            if outcome.limitations:
                had_failure = True
            if outcome.success:
                break
            had_failure = True

        if bars:
            status = AcquisitionStatus.PARTIAL if had_failure else AcquisitionStatus.COMPLETED
        elif attempts:
            status = AcquisitionStatus.FAILED if had_failure else AcquisitionStatus.UNAVAILABLE
        else:
            status = AcquisitionStatus.UNAVAILABLE
        providers = tuple(dict.fromkeys(item.provider for item in attempts))
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=bool(attempts),
                status=(status if attempts else AcquisitionStatus.NOT_ATTEMPTED),
                providers_attempted=providers,
                resource_attempts=tuple(attempts),
                external_calls=len(attempts),
                subscriptions_created=0,
                elapsed_ms=max(
                    0,
                    int((self._monotonic() - started_at) * 1000),
                ),
                limitations=_unique(limitations),
            ),
            observations=tuple(bars),
            receipts=tuple(receipts),
            provider_health=tuple(health),
        )

    def acquire_bar_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> BarAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("shared acquisition plan does not match requirement")
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("official daily acquisition requires an instrument target")
        return self.acquire_routes(
            requirement.target.instrument,
            plan.routes,
            trade_date=requirement.request.end_at.date(),
        )


__all__ = [
    "HttpResponseLike",
    "RouteFetcher",
    "TaiwanOfficialDailyAcquisitionExecutor",
]
