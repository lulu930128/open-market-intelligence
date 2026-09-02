"""Descriptor-route executor for bounded Taiwan intraday acquisition."""

from __future__ import annotations

from app.market.providers.tw_intraday_bars import (
    NStockIntradayAdapter,
    YahooIntradayAdapter,
)
from app.market.tw_intraday_capabilities import (
    NSTOCK_INTRADAY_PROVIDER,
    YAHOO_INTRADAY_PROVIDER,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
)
from app.market_data.provider_catalog import DataAcquisitionPlanV2


class TaiwanIntradayAcquisitionExecutor:
    """Execute only shared-planned routes, in shared priority order."""

    def __init__(
        self,
        *,
        nstock: NStockIntradayAdapter | None = None,
        yahoo: YahooIntradayAdapter | None = None,
        clock,
    ) -> None:
        self._adapters = {
            NSTOCK_INTRADAY_PROVIDER: nstock or NStockIntradayAdapter(clock=clock),
            YAHOO_INTRADAY_PROVIDER: yahoo or YahooIntradayAdapter(clock=clock),
        }

    @staticmethod
    def _range_days(requirement: DataRequirementV2) -> int:
        if not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("intraday acquisition requires bar capability request")
        return max(
            1,
            (
                requirement.request.end_at.date()
                - requirement.request.start_at.date()
            ).days
            + 1,
        )

    def acquire_bar_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> BarAcquisitionResult:
        if plan.requirement != requirement:
            raise ValueError("intraday acquisition plan does not match requirement")
        if len(plan.routes) > 1:
            raise ValueError(
                "intraday acquisition executor accepts one Gateway-controlled route"
            )
        receipts = []
        health = []
        attempts = []
        providers = []
        limitations: list[str] = []
        observations = ()
        external_calls = 0
        attempted_statuses: list[AcquisitionStatus] = []
        requested_range_days = self._range_days(requirement)

        route = plan.routes[0] if plan.routes else None
        if route is not None and requested_range_days > route.max_range_days:
            limitations.append(f"ROUTE_RANGE_EXCEEDED:{route.provider_key}")
        elif route is not None:
            adapter = self._adapters.get(route.provider_key)
            if adapter is None:
                limitations.append(
                    f"PROVIDER_ADAPTER_UNAVAILABLE:{route.provider_key}"
                )
            else:
                acquired = adapter.acquire_route(requirement, route)
                attempted_statuses.append(acquired.summary.status)
                external_calls += acquired.summary.external_calls
                providers.extend(acquired.summary.providers_attempted)
                attempts.extend(acquired.summary.resource_attempts)
                receipts.extend(acquired.receipts)
                health.extend(acquired.provider_health)
                limitations.extend(acquired.summary.limitations)
                observations = acquired.observations

        attempted = bool(attempts)
        if observations:
            status = AcquisitionStatus.COMPLETED
        elif attempted and any(
            item is AcquisitionStatus.PARTIAL for item in attempted_statuses
        ):
            status = AcquisitionStatus.PARTIAL
        elif attempted:
            status = AcquisitionStatus.FAILED
        else:
            status = AcquisitionStatus.NOT_ATTEMPTED
            limitations.append("NO_ROUTE_WITHIN_INTRADAY_RANGE_BOUND")
        return BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=attempted,
                status=status,
                providers_attempted=tuple(dict.fromkeys(providers)),
                resource_attempts=tuple(attempts),
                external_calls=external_calls,
                limitations=tuple(dict.fromkeys(limitations)),
            ),
            observations=observations,
            receipts=tuple(receipts),
            provider_health=tuple(health),
        )


__all__ = ["TaiwanIntradayAcquisitionExecutor"]
