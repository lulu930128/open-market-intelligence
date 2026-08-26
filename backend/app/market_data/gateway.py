"""Cache-first application gateway for canonical market-data evidence.

The gateway coordinates reads, pure resolution, bounded acquisition, and the
mandatory post-acquisition reread. It owns no provider catalog, SQL, market
semantics, or outward presentation formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from collections.abc import Iterable
from typing import Protocol

from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    BarObservation,
    DatasetHealth,
    MarketBreadthObservation,
    MarketIndexObservation,
    ProviderResourceHealth,
    QuoteObservation,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    InstrumentTarget,
    MarketDataResultV1,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import allows_external_acquisition
from app.market_data.provider_catalog import (
    DataAcquisitionPlanV2,
    ProviderCapabilityDescriptorV2,
    plan_data_acquisition_v2,
)
from app.market_data.resolution import (
    BarSeriesCandidate,
    ResolutionCandidate,
    resolve_bar_series,
    resolve_market_breadth,
    resolve_market_index,
    resolve_quote,
)


@dataclass(frozen=True, slots=True)
class BarCandidateBatch:
    candidates: tuple[BarSeriesCandidate, ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    dataset_health: DatasetHealth | None = None
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


class BarCandidateReader(Protocol):
    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch: ...


@dataclass(frozen=True, slots=True)
class QuoteCandidateBatch:
    candidates: tuple[ResolutionCandidate[QuoteObservation], ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    dataset_health: DatasetHealth | None = None
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


class QuoteCandidateReader(Protocol):
    def read_quote_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> QuoteCandidateBatch: ...


@dataclass(frozen=True, slots=True)
class MarketBreadthCandidateBatch:
    candidates: tuple[ResolutionCandidate[MarketBreadthObservation], ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    dataset_health: DatasetHealth | None = None
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


class MarketBreadthCandidateReader(Protocol):
    def read_market_breadth_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketBreadthCandidateBatch: ...


@dataclass(frozen=True, slots=True)
class MarketIndexCandidateBatch:
    candidates: tuple[ResolutionCandidate[MarketIndexObservation], ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    dataset_health: DatasetHealth | None = None
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


class MarketIndexCandidateReader(Protocol):
    def read_market_index_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketIndexCandidateBatch: ...


@dataclass(frozen=True, slots=True)
class BarAcquisitionResult:
    summary: AcquisitionSummary
    observations: tuple[BarObservation, ...] = ()
    receipts: tuple[RawFetchReceiptV1, ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()


@dataclass(frozen=True, slots=True)
class QuoteAcquisitionResult:
    summary: AcquisitionSummary
    observations: tuple[QuoteObservation, ...] = ()
    receipts: tuple[RawFetchReceiptV1, ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketIndexAcquisitionResult:
    summary: AcquisitionSummary
    observations: tuple[MarketIndexObservation, ...] = ()
    receipts: tuple[RawFetchReceiptV1, ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()


class BarAcquisitionPort(Protocol):
    def acquire_bar_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> BarAcquisitionResult: ...


class QuoteAcquisitionPort(Protocol):
    def acquire_quote_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> QuoteAcquisitionResult: ...


class BarTransactionPort(Protocol):
    def persist_bar_acquisition(
        self,
        requirement: DataRequirementV2 | RefreshRequirementV1,
        acquisition: BarAcquisitionResult,
    ) -> PersistenceSummary: ...


class QuoteTransactionPort(Protocol):
    def persist_quote_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: QuoteAcquisitionResult,
    ) -> PersistenceSummary: ...


class AcquisitionBudgetExceeded(RuntimeError):
    """Raised when a provider port reports work beyond the request budget."""


def _not_attempted(reason: str) -> AcquisitionSummary:
    return AcquisitionSummary(
        attempted=False,
        status=AcquisitionStatus.NOT_ATTEMPTED,
        limitations=(reason,),
    )


def _plan_unavailable(plan: DataAcquisitionPlanV2) -> AcquisitionSummary:
    skip_reasons = tuple(item.reason_code for item in plan.skipped_resources)
    return AcquisitionSummary(
        attempted=False,
        status=AcquisitionStatus.NOT_ATTEMPTED,
        limitations=_unique((*plan.limitations, *skip_reasons)),
    )


def _not_persisted(reason: str) -> PersistenceSummary:
    return PersistenceSummary(attempted=False, limitations=(reason,))


def _is_satisfied(status: ResolvedEvidenceStatus) -> bool:
    return status in {
        ResolvedEvidenceStatus.SELECTED,
        ResolvedEvidenceStatus.FALLBACK,
    }


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in values if item))


def _merge_provider_health(
    *groups: tuple[ProviderResourceHealth, ...],
) -> tuple[ProviderResourceHealth, ...]:
    merged: dict[tuple[str, str, str], ProviderResourceHealth] = {}
    for group in groups:
        for item in group:
            merged[(item.provider, item.market.value, item.capability)] = item
    return tuple(merged.values())


class MarketDataGateway:
    def _read(
        self,
        requirement: DataRequirementV2,
        reader: BarCandidateReader,
    ) -> BarCandidateBatch:
        batch = reader.read_bar_candidates(requirement)
        if len(batch.candidates) > requirement.bounds.max_candidates:
            raise ValueError("candidate reader exceeded bounds.max_candidates")
        return batch

    def _resolve(
        self,
        requirement: DataRequirementV2,
        batch: BarCandidateBatch,
    ):
        return resolve_bar_series(
            batch.candidates,
            policy=requirement.realtime_policy,
            now=requirement.requested_at,
            max_age=timedelta(seconds=requirement.freshness.max_age_seconds),
        )

    @staticmethod
    def _validate_acquisition_budget(
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
        result: BarAcquisitionResult | QuoteAcquisitionResult,
    ) -> None:
        summary = result.summary
        if summary.external_calls > requirement.bounds.max_external_calls:
            raise AcquisitionBudgetExceeded("acquisition exceeded max_external_calls")
        if summary.subscriptions_created > requirement.bounds.max_subscriptions:
            raise AcquisitionBudgetExceeded("acquisition exceeded max_subscriptions")
        if len(summary.providers_attempted) > requirement.bounds.max_provider_attempts:
            raise AcquisitionBudgetExceeded("acquisition exceeded max_provider_attempts")
        if (
            summary.elapsed_ms is not None
            and summary.elapsed_ms > requirement.bounds.timeout_seconds * 1000
        ):
            raise AcquisitionBudgetExceeded("acquisition exceeded timeout_seconds")
        if len(result.observations) > requirement.bounds.max_rows:
            raise AcquisitionBudgetExceeded("acquisition exceeded bounds.max_rows")
        if len(result.receipts) > requirement.bounds.max_external_calls:
            raise AcquisitionBudgetExceeded("receipt count exceeded max_external_calls")
        planned_resources = {
            (route.provider_key, route.resource_id) for route in plan.routes
        }
        attempted_resources = {
            (attempt.provider, attempt.resource_id)
            for attempt in summary.resource_attempts
        }
        if not attempted_resources <= planned_resources:
            raise AcquisitionBudgetExceeded(
                "acquisition attempted a provider resource outside the shared plan"
            )
        if (summary.external_calls or summary.subscriptions_created) and not attempted_resources:
            raise AcquisitionBudgetExceeded(
                "acquisition reported external work without resource attempts"
            )

    @staticmethod
    def _validate_persistence_result(
        acquisition: BarAcquisitionResult | QuoteAcquisitionResult,
        persistence: PersistenceSummary,
    ) -> None:
        if not persistence.attempted:
            raise ValueError("transaction port must report an attempted persistence")
        if not persistence.committed:
            raise ValueError("transaction port returned without an atomic commit")
        if persistence.receipts_written > len(acquisition.receipts):
            raise ValueError("transaction port wrote more receipts than acquired")
        persisted_observations = (
            persistence.observations_written + persistence.observations_unchanged
        )
        if persisted_observations > len(acquisition.observations):
            raise ValueError("transaction port accounted for more observations than acquired")

    def resolve_bars(
        self,
        requirement: DataRequirementV2,
        *,
        reader: BarCandidateReader,
        descriptors: Iterable[ProviderCapabilityDescriptorV2] = (),
        acquisition_port: BarAcquisitionPort | None = None,
        transaction_port: BarTransactionPort | None = None,
    ) -> MarketDataResultV1:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("bar resolution requires an instrument target")
        if not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("bar resolution requires a bars capability request")

        initial_batch = self._read(requirement, reader)
        resolved = self._resolve(requirement, initial_batch)
        final_batch = initial_batch
        acquisition_health: tuple[ProviderResourceHealth, ...] = ()
        persistence = _not_persisted("PERSISTENCE_NOT_REQUIRED")

        if _is_satisfied(resolved.health.status):
            acquisition = _not_attempted("PRE_RESOLUTION_SATISFIED")
        elif not allows_external_acquisition(requirement.realtime_policy):
            acquisition = _not_attempted("READ_POLICY_FORBIDS_ACQUISITION")
        elif (
            requirement.bounds.max_provider_attempts == 0
            or requirement.bounds.max_external_calls == 0
        ):
            acquisition = _not_attempted("ACQUISITION_BUDGET_ZERO")
        else:
            plan = plan_data_acquisition_v2(
                requirement,
                descriptors,
                initial_batch.provider_health,
            )
            if plan.unfillable:
                acquisition = _plan_unavailable(plan)
            elif acquisition_port is None:
                acquisition = _not_attempted("ACQUISITION_PORT_UNAVAILABLE")
            elif transaction_port is None:
                acquisition = _not_attempted("TRANSACTION_PORT_UNAVAILABLE")
                persistence = _not_persisted("TRANSACTION_PORT_UNAVAILABLE")
            else:
                acquired = acquisition_port.acquire_bar_observations(requirement, plan)
                self._validate_acquisition_budget(requirement, plan, acquired)
                acquisition = acquired.summary
                acquisition_health = acquired.provider_health
                if acquisition.attempted and (acquired.receipts or acquired.observations):
                    persistence = transaction_port.persist_bar_acquisition(
                        requirement,
                        acquired,
                    )
                    self._validate_persistence_result(acquired, persistence)
                    final_batch = self._read(requirement, reader)
                    resolved = self._resolve(requirement, final_batch)
                elif acquisition.attempted:
                    persistence = _not_persisted("NO_PERSISTABLE_ACQUISITION_EVIDENCE")
                else:
                    persistence = _not_persisted("ACQUISITION_NOT_ATTEMPTED")

        return MarketDataResultV1(
            requirement=requirement,
            result_kind="bar_series",
            resolved=resolved,
            provider_health=_merge_provider_health(
                final_batch.provider_health,
                acquisition_health,
            ),
            dataset_health=final_batch.dataset_health,
            acquisition=acquisition,
            persistence=persistence,
            candidate_rejections=final_batch.rejections,
            limitations=_unique(
                (
                    *final_batch.limitations,
                    *acquisition.limitations,
                )
            ),
        )

    def resolve_quote(
        self,
        requirement: DataRequirementV2,
        *,
        reader: QuoteCandidateReader,
        descriptors: Iterable[ProviderCapabilityDescriptorV2] = (),
        acquisition_port: QuoteAcquisitionPort | None = None,
        transaction_port: QuoteTransactionPort | None = None,
    ) -> MarketDataResultV1:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("quote resolution requires an instrument target")
        if not isinstance(requirement.request, SnapshotCapabilityRequest):
            raise ValueError("quote resolution requires a snapshot capability request")

        initial_batch = reader.read_quote_candidates(requirement)
        if len(initial_batch.candidates) > requirement.bounds.max_candidates:
            raise ValueError("candidate reader exceeded bounds.max_candidates")
        resolved = resolve_quote(
            initial_batch.candidates,
            policy=requirement.realtime_policy,
            now=requirement.requested_at,
            max_age=timedelta(seconds=requirement.freshness.max_age_seconds),
        )
        final_batch = initial_batch
        acquisition_health: tuple[ProviderResourceHealth, ...] = ()
        persistence = _not_persisted("PERSISTENCE_NOT_REQUIRED")

        if _is_satisfied(resolved.health.status):
            acquisition = _not_attempted("PRE_RESOLUTION_SATISFIED")
        elif not allows_external_acquisition(requirement.realtime_policy):
            acquisition = _not_attempted("READ_POLICY_FORBIDS_ACQUISITION")
        elif (
            requirement.bounds.max_provider_attempts == 0
            or requirement.bounds.max_external_calls == 0
        ):
            acquisition = _not_attempted("ACQUISITION_BUDGET_ZERO")
        else:
            plan = plan_data_acquisition_v2(
                requirement,
                descriptors,
                initial_batch.provider_health,
            )
            if plan.unfillable:
                acquisition = _plan_unavailable(plan)
            elif acquisition_port is None:
                acquisition = _not_attempted("ACQUISITION_PORT_UNAVAILABLE")
            elif transaction_port is None:
                acquisition = _not_attempted("TRANSACTION_PORT_UNAVAILABLE")
                persistence = _not_persisted("TRANSACTION_PORT_UNAVAILABLE")
            else:
                acquired = acquisition_port.acquire_quote_observations(
                    requirement,
                    plan,
                )
                self._validate_acquisition_budget(requirement, plan, acquired)
                acquisition = acquired.summary
                acquisition_health = acquired.provider_health
                if acquisition.attempted and (
                    acquired.receipts or acquired.observations
                ):
                    persistence = transaction_port.persist_quote_acquisition(
                        requirement,
                        acquired,
                    )
                    self._validate_persistence_result(acquired, persistence)
                    final_batch = reader.read_quote_candidates(requirement)
                    if len(final_batch.candidates) > requirement.bounds.max_candidates:
                        raise ValueError(
                            "candidate reader exceeded bounds.max_candidates"
                        )
                    resolved = resolve_quote(
                        final_batch.candidates,
                        policy=requirement.realtime_policy,
                        now=requirement.requested_at,
                        max_age=timedelta(
                            seconds=requirement.freshness.max_age_seconds
                        ),
                    )
                elif acquisition.attempted:
                    persistence = _not_persisted(
                        "NO_PERSISTABLE_ACQUISITION_EVIDENCE"
                    )
                else:
                    persistence = _not_persisted("ACQUISITION_NOT_ATTEMPTED")

        return MarketDataResultV1(
            requirement=requirement,
            result_kind="quote",
            resolved=resolved,
            provider_health=_merge_provider_health(
                final_batch.provider_health,
                acquisition_health,
            ),
            dataset_health=final_batch.dataset_health,
            acquisition=acquisition,
            persistence=persistence,
            candidate_rejections=final_batch.rejections,
            limitations=_unique(
                (
                    *final_batch.limitations,
                    *acquisition.limitations,
                )
            ),
        )

    def resolve_market_breadth(
        self,
        requirement: DataRequirementV2,
        *,
        reader: MarketBreadthCandidateReader,
    ) -> MarketDataResultV1:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("market breadth resolution requires a dataset target")
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("market breadth resolution requires a dataset capability")
        if requirement.request.capability_id != "market.breadth":
            raise ValueError("market breadth resolver requires capability=market.breadth")
        batch = reader.read_market_breadth_candidates(requirement)
        if len(batch.candidates) > requirement.bounds.max_candidates:
            raise ValueError("candidate reader exceeded bounds.max_candidates")
        resolved = resolve_market_breadth(
            batch.candidates,
            policy=requirement.realtime_policy,
            now=requirement.requested_at,
            max_age=timedelta(seconds=requirement.freshness.max_age_seconds),
        )
        return MarketDataResultV1(
            requirement=requirement,
            result_kind="market_breadth",
            resolved=resolved,
            provider_health=batch.provider_health,
            dataset_health=batch.dataset_health,
            acquisition=_not_attempted("READ_POLICY_FORBIDS_ACQUISITION"),
            persistence=_not_persisted("PERSISTENCE_NOT_REQUIRED"),
            candidate_rejections=batch.rejections,
            limitations=batch.limitations,
        )

    def resolve_market_index(
        self,
        requirement: DataRequirementV2,
        *,
        reader: MarketIndexCandidateReader,
    ) -> MarketDataResultV1:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("market index resolution requires a dataset target")
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("market index resolution requires a dataset capability")
        if requirement.request.capability_id != "market.index.daily":
            raise ValueError(
                "market index resolver requires capability=market.index.daily"
            )
        batch = reader.read_market_index_candidates(requirement)
        if len(batch.candidates) > requirement.bounds.max_candidates:
            raise ValueError("candidate reader exceeded bounds.max_candidates")
        resolved = resolve_market_index(
            batch.candidates,
            policy=requirement.realtime_policy,
            now=requirement.requested_at,
            max_age=timedelta(seconds=requirement.freshness.max_age_seconds),
        )
        return MarketDataResultV1(
            requirement=requirement,
            result_kind="market_index",
            resolved=resolved,
            provider_health=batch.provider_health,
            dataset_health=batch.dataset_health,
            acquisition=_not_attempted("READ_POLICY_FORBIDS_ACQUISITION"),
            persistence=_not_persisted("PERSISTENCE_NOT_REQUIRED"),
            candidate_rejections=batch.rejections,
            limitations=batch.limitations,
        )


__all__ = [
    "AcquisitionBudgetExceeded",
    "BarAcquisitionPort",
    "BarAcquisitionResult",
    "BarCandidateBatch",
    "BarCandidateReader",
    "BarTransactionPort",
    "MarketDataGateway",
    "MarketBreadthCandidateBatch",
    "MarketBreadthCandidateReader",
    "MarketIndexAcquisitionResult",
    "MarketIndexCandidateBatch",
    "MarketIndexCandidateReader",
    "QuoteAcquisitionPort",
    "QuoteAcquisitionResult",
    "QuoteCandidateBatch",
    "QuoteCandidateReader",
    "QuoteTransactionPort",
]
