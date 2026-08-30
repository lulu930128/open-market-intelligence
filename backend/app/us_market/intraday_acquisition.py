"""US-owned provider acquisition for quote snapshots and intraday bars.

This module performs bounded provider I/O plus pure canonical conversion. It
never selects final evidence and never writes the database.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from app.config import Settings
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.gateway import BarAcquisitionResult, QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
    SnapshotCapabilityRequest,
)
from app.market_data.provider_catalog import DataAcquisitionPlanV2, ProviderResourceRouteV2
from app.us_market.daily_ohlcv_acquisition import _failure_health, _health, _unique
from app.us_market.market_data.descriptors import (
    TWELVE_INTRADAY_RESOURCE_ID,
    TWELVE_QUOTE_RESOURCE_ID,
    YAHOO_INTRADAY_RESOURCE_ID,
    YAHOO_QUOTE_RESOURCE_ID,
)
from app.us_market.providers.canonical import (
    canonical_twelve_data_intraday_payload,
    canonical_twelve_data_quote_payload,
    canonical_yahoo_chart_payload,
)
from app.us_market.providers.errors import USProviderDataError
from app.us_market.providers.twelve_data import (
    fetch_twelve_data_quote_payload,
    fetch_twelve_data_time_series_payload,
)


_TWELVE_PROVIDER_INTERVALS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1h": "1h",
}
from app.us_market.providers.yahoo import fetch_yahoo_chart_payload


class USIntradayAcquisitionExecutor:
    def __init__(
        self,
        *,
        fetchers: Mapping[str, Callable[[ProviderResourceRouteV2, DataRequirementV2], tuple[Mapping, str]]] | None = None,
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
    ) -> tuple[Mapping, str]:
        injected = self._fetchers.get(route.resource_id)
        if injected is not None:
            return injected(route, requirement)
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("US intraday acquisition requires instrument target")
        symbol = requirement.target.instrument.symbol
        if route.resource_id in {YAHOO_QUOTE_RESOURCE_ID, YAHOO_INTRADAY_RESOURCE_ID}:
            return fetch_yahoo_chart_payload(
                symbol=symbol,
                range_value="5d",
                interval="1m",
                timeout_seconds=route.timeout_seconds,
                include_prepost=True,
                resource="us_intraday_shared_core",
            )
        api_key = str(self._settings.twelve_data_api_key or "").strip()
        if not api_key:
            raise USProviderDataError(
                provider="twelve_data",
                code="TWELVE_DATA_API_KEY_NOT_CONFIGURED",
                category="configuration",
                message="Twelve Data API key is not configured.",
            )
        if route.resource_id == TWELVE_QUOTE_RESOURCE_ID:
            return fetch_twelve_data_quote_payload(
                symbol=symbol,
                api_key=api_key,
                timeout_seconds=route.timeout_seconds,
            )
        if route.resource_id == TWELVE_INTRADAY_RESOURCE_ID:
            assert isinstance(requirement.request, BarCapabilityRequest)
            provider_interval = _TWELVE_PROVIDER_INTERVALS.get(
                requirement.request.interval
            )
            if provider_interval is None:
                raise ValueError("unsupported Twelve Data canonical interval")
            return fetch_twelve_data_time_series_payload(
                symbol=symbol,
                api_key=api_key,
                interval=provider_interval,
                outputsize=requirement.request.max_bars,
                timezone_name="America/New_York",
                timeout_seconds=route.timeout_seconds,
            )
        raise ValueError(f"unsupported US intraday resource: {route.resource_id}")

    def _canonical(
        self,
        route: ProviderResourceRouteV2,
        requirement: DataRequirementV2,
        payload: Mapping,
        fetched_at: datetime,
    ):
        assert isinstance(requirement.target, InstrumentTarget)
        if route.resource_id in {YAHOO_QUOTE_RESOURCE_ID, YAHOO_INTRADAY_RESOURCE_ID}:
            return canonical_yahoo_chart_payload(
                instrument=requirement.target.instrument,
                payload=payload,
                fetched_at=fetched_at,
                interval="1m",
                session_scope="all",
            )
        if route.resource_id == TWELVE_QUOTE_RESOURCE_ID:
            return canonical_twelve_data_quote_payload(
                instrument=requirement.target.instrument,
                payload=payload,
                fetched_at=fetched_at,
            )
        assert isinstance(requirement.request, BarCapabilityRequest)
        provider_interval = _TWELVE_PROVIDER_INTERVALS.get(
            requirement.request.interval
        )
        if provider_interval is None:
            raise ValueError("unsupported Twelve Data canonical interval")
        return canonical_twelve_data_intraday_payload(
            instrument=requirement.target.instrument,
            payload=payload,
            fetched_at=fetched_at,
            interval=provider_interval,
        )

    @staticmethod
    def _receipt(
        route: ProviderResourceRouteV2,
        *,
        batch,
        raw_text: str,
        content_hash: str,
        fetched_at: datetime,
        url: str,
        source: str,
        parser_version: str,
    ) -> RawFetchReceiptV1:
        return RawFetchReceiptV1(
            provider=route.provider_key,
            source=source,
            resource_id=route.resource_id,
            fetched_at=fetched_at,
            method="GET",
            url=url,
            status_code=200,
            content_type="application/json",
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=parser_version,
        )

    def _execute(self, requirement: DataRequirementV2, plan: DataAcquisitionPlanV2, *, quote: bool):
        if plan.requirement != requirement:
            raise ValueError("shared acquisition plan does not match requirement")
        started_at = self._monotonic()
        attempts: list[AcquisitionResourceAttempt] = []
        receipts: list[RawFetchReceiptV1] = []
        observations: list = []
        health: list[ProviderResourceHealth] = []
        limitations: list[str] = []
        failures = 0
        for route in plan.routes:
            attempts.append(AcquisitionResourceAttempt(provider=route.provider_key, resource_id=route.resource_id))
            checked_at = self._clock()
            try:
                payload, url = self._fetch(route, requirement)
                raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
                fetched_at = self._clock()
                batch = self._canonical(route, requirement, payload, fetched_at)
                if quote:
                    canonical = batch.snapshot.quote if batch.snapshot is not None else None
                    current = (canonical,) if canonical is not None else ()
                else:
                    assert isinstance(requirement.request, BarCapabilityRequest)
                    current = tuple(
                        bar for bar in batch.bars
                        if requirement.request.start_at <= bar.start_at <= requirement.request.end_at
                    )
                source = (
                    current[0].lineage.source if current else
                    "yahoo.chart.1m" if route.provider_key == "yahoo_chart" else
                    "twelve_data.quote" if quote else
                    f"twelve_data.time_series.{requirement.request.interval}"
                )
                parser = (
                    current[0].lineage.raw_contract_version if current else
                    "yahoo.chart.v8" if route.provider_key == "yahoo_chart" else
                    "twelve_data.quote.v1" if quote else
                    "twelve_data.time_series.v1"
                )
                current = tuple(
                    item.model_copy(update={"lineage": item.lineage.model_copy(update={"content_hash": content_hash})})
                    for item in current
                )
                receipts.append(self._receipt(route, batch=batch, raw_text=raw_text, content_hash=content_hash, fetched_at=fetched_at, url=url, source=source, parser_version=parser))
                observations.extend(current)
                limitations.extend(route.limitations)
                limitations.extend(batch.limitations)
                latest_event = (
                    current[-1].lineage.event_at
                    if current
                    else None
                )
                age_seconds = (
                    (requirement.requested_at - latest_event).total_seconds()
                    if latest_event is not None
                    else float("inf")
                )
                satisfied = bool(current) and -300 <= age_seconds <= requirement.freshness.max_age_seconds
                if not satisfied:
                    failures += 1
                    limitations.append(
                        "REQUESTED_EVIDENCE_STALE"
                        if current
                        else "REQUESTED_EVIDENCE_NOT_OBSERVED"
                    )
                health.append(_health(
                    route,
                    checked_at=fetched_at,
                    connection=ConnectionStatus.CONNECTED,
                    operational=OperationalStatus.HEALTHY if satisfied else OperationalStatus.DEGRADED,
                    freshness=EvidenceFreshness.FRESH if satisfied else EvidenceFreshness.STALE if current else EvidenceFreshness.MISSING,
                    detail_code="US_QUOTE_OBSERVED" if quote and satisfied else "US_INTRADAY_OBSERVED" if satisfied else "REQUESTED_EVIDENCE_STALE" if current else "REQUESTED_EVIDENCE_NOT_OBSERVED",
                ))
                if satisfied:
                    break
            except Exception as exc:
                failures += 1
                failure_health, code = _failure_health(route, checked_at=checked_at, error=exc)
                health.append(failure_health)
                limitations.append(code)
        status = AcquisitionStatus.PARTIAL if observations and failures else AcquisitionStatus.COMPLETED if observations else AcquisitionStatus.FAILED if attempts else AcquisitionStatus.NOT_ATTEMPTED
        summary = AcquisitionSummary(
            attempted=bool(attempts),
            status=status,
            providers_attempted=tuple(dict.fromkeys(item.provider for item in attempts)),
            resource_attempts=tuple(attempts),
            external_calls=len(attempts),
            subscriptions_created=0,
            elapsed_ms=max(0, int((self._monotonic() - started_at) * 1000)),
            limitations=_unique(limitations),
        )
        result_type = QuoteAcquisitionResult if quote else BarAcquisitionResult
        return result_type(summary=summary, observations=tuple(observations), receipts=tuple(receipts), provider_health=tuple(health))

    def acquire_quote_observations(self, requirement: DataRequirementV2, plan: DataAcquisitionPlanV2) -> QuoteAcquisitionResult:
        if not isinstance(requirement.request, SnapshotCapabilityRequest) or requirement.request.capability_id != "quote.snapshot":
            raise ValueError("US quote acquisition capability mismatch")
        return self._execute(requirement, plan, quote=True)

    def acquire_bar_observations(self, requirement: DataRequirementV2, plan: DataAcquisitionPlanV2) -> BarAcquisitionResult:
        if not isinstance(requirement.request, BarCapabilityRequest) or requirement.request.capability_id != "intraday.bars":
            raise ValueError("US intraday acquisition capability mismatch")
        return self._execute(requirement, plan, quote=False)


__all__ = ["USIntradayAcquisitionExecutor"]
