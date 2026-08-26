"""Descriptor-route executors for Taiwan current-session aggregates."""

from __future__ import annotations

from app.market.providers.tw_current_market import (
    CurrentBreadthAdapter,
    CurrentIndexAdapter,
)
from app.market_data.gateway import (
    MarketBreadthAcquisitionResult,
    MarketIndexAcquisitionResult,
)
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    DataRequirementV2,
)
from app.market_data.provider_catalog import DataAcquisitionPlanV2


def _summary(
    *,
    attempts,
    providers,
    external_calls: int,
    limitations: list[str],
    selected: bool,
) -> AcquisitionSummary:
    attempted = bool(attempts)
    return AcquisitionSummary(
        attempted=attempted,
        status=(
            AcquisitionStatus.COMPLETED
            if selected
            else AcquisitionStatus.FAILED
            if attempted
            else AcquisitionStatus.NOT_ATTEMPTED
        ),
        providers_attempted=tuple(dict.fromkeys(providers)),
        resource_attempts=tuple(attempts),
        external_calls=external_calls,
        limitations=tuple(dict.fromkeys(limitations)),
    )


class TaiwanCurrentIndexAcquisitionExecutor:
    def __init__(self, adapters: tuple[CurrentIndexAdapter, ...]) -> None:
        self._adapters = {
            adapter.binding.descriptor.resource_id: adapter for adapter in adapters
        }

    def acquire_market_index_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> MarketIndexAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("current index plan does not match requirement")
        attempts = []
        providers = []
        receipts = []
        health = []
        limitations: list[str] = []
        observations = ()
        external_calls = 0
        for route in plan.routes:
            adapter = self._adapters.get(route.resource_id)
            if adapter is None:
                limitations.append(f"PROVIDER_ADAPTER_UNAVAILABLE:{route.resource_id}")
                continue
            acquired = adapter.acquire(requirement, route)
            attempts.extend(acquired.summary.resource_attempts)
            providers.extend(acquired.summary.providers_attempted)
            external_calls += acquired.summary.external_calls
            receipts.extend(acquired.receipts)
            health.extend(acquired.provider_health)
            limitations.extend(acquired.summary.limitations)
            if acquired.observations:
                observations = acquired.observations
                break
        if not attempts:
            limitations.append("NO_CURRENT_INDEX_ROUTE_EXECUTED")
        return MarketIndexAcquisitionResult(
            summary=_summary(
                attempts=attempts,
                providers=providers,
                external_calls=external_calls,
                limitations=limitations,
                selected=bool(observations),
            ),
            observations=observations,
            receipts=tuple(receipts),
            provider_health=tuple(health),
        )


class TaiwanCurrentBreadthAcquisitionExecutor:
    def __init__(self, adapters: tuple[CurrentBreadthAdapter, ...]) -> None:
        self._adapters = {
            adapter.binding.descriptor.resource_id: adapter for adapter in adapters
        }

    def acquire_market_breadth_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> MarketBreadthAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("current breadth plan does not match requirement")
        attempts = []
        providers = []
        receipts = []
        health = []
        limitations: list[str] = []
        observations = ()
        external_calls = 0
        for route in plan.routes:
            adapter = self._adapters.get(route.resource_id)
            if adapter is None:
                limitations.append(f"PROVIDER_ADAPTER_UNAVAILABLE:{route.resource_id}")
                continue
            acquired = adapter.acquire(requirement, route)
            attempts.extend(acquired.summary.resource_attempts)
            providers.extend(acquired.summary.providers_attempted)
            external_calls += acquired.summary.external_calls
            receipts.extend(acquired.receipts)
            health.extend(acquired.provider_health)
            limitations.extend(acquired.summary.limitations)
            if acquired.observations:
                observations = acquired.observations
                break
        if not attempts:
            limitations.append("NO_CURRENT_BREADTH_ROUTE_EXECUTED")
        return MarketBreadthAcquisitionResult(
            summary=_summary(
                attempts=attempts,
                providers=providers,
                external_calls=external_calls,
                limitations=limitations,
                selected=bool(observations),
            ),
            observations=observations,
            receipts=tuple(receipts),
            provider_health=tuple(health),
        )


__all__ = [
    "TaiwanCurrentBreadthAcquisitionExecutor",
    "TaiwanCurrentIndexAcquisitionExecutor",
]
