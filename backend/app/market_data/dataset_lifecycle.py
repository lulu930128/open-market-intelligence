"""Shared runtime contract for registry-owned market dataset lifecycle."""

from __future__ import annotations

from datetime import date, datetime

from app.market_data.contracts import CanonicalModel, DatasetHealth, Market
from app.market_data.registry import (
    DATASET_REGISTRY,
    DatasetRegistry,
    EligibilityPolicy,
    ExpectedStatePolicy,
    RefreshBounds,
    evaluate_dataset_health,
)


class DatasetLifecycleContract(CanonicalModel):
    contract_version: str = "omi.market.dataset_lifecycle.v1"
    dataset_id: str
    schema_version: str
    market: Market
    scope_kind: str
    owner: str
    read_operation: str
    projection_id: str
    capability_ids: tuple[str, ...]
    expected_state_policy: ExpectedStatePolicy
    eligibility_policy: EligibilityPolicy
    storage_reference: str | None = None
    refreshable: bool
    refresh_operation: str | None = None
    refresh_bounds: RefreshBounds | None = None
    postcondition: str
    repairable: bool


class DatasetLifecycleEvaluation(CanonicalModel):
    contract_version: str = "omi.market.dataset_lifecycle_evaluation.v1"
    lifecycle: DatasetLifecycleContract
    health: DatasetHealth


def dataset_lifecycle_contract(
    dataset_id: str,
    *,
    registry: DatasetRegistry = DATASET_REGISTRY,
) -> DatasetLifecycleContract:
    spec = registry.get(dataset_id)
    return DatasetLifecycleContract(
        dataset_id=spec.dataset_id,
        schema_version=spec.schema_version,
        market=spec.market,
        scope_kind=spec.scope_kind,
        owner=spec.owner,
        read_operation=spec.read_operation,
        projection_id=spec.projection_id,
        capability_ids=spec.capability_ids,
        expected_state_policy=spec.expected_state_policy,
        eligibility_policy=spec.eligibility_policy,
        storage_reference=spec.storage_reference,
        refreshable=spec.refreshable,
        refresh_operation=spec.refresh_operation,
        refresh_bounds=spec.refresh_bounds,
        postcondition=spec.postcondition,
        repairable=spec.repairable,
    )


def require_refresh_contract(
    lifecycle: DatasetLifecycleContract,
    *,
    operation: str,
) -> RefreshBounds:
    if not lifecycle.refreshable or not lifecycle.repairable:
        raise ValueError(f"dataset '{lifecycle.dataset_id}' is not repairable")
    if lifecycle.refresh_operation != operation:
        raise ValueError(
            f"dataset '{lifecycle.dataset_id}' does not own refresh operation "
            f"'{operation}'"
        )
    if lifecycle.refresh_bounds is None:
        raise ValueError(
            f"dataset '{lifecycle.dataset_id}' has no executable refresh bounds"
        )
    return lifecycle.refresh_bounds


def evaluate_lifecycle(
    lifecycle: DatasetLifecycleContract,
    *,
    expected_date: date | None,
    latest_date: date | None,
    checked_at: datetime,
    eligible: bool | None,
    partial: bool = False,
    provider_available: bool = True,
    registry: DatasetRegistry = DATASET_REGISTRY,
) -> DatasetLifecycleEvaluation:
    spec = registry.get(lifecycle.dataset_id)
    if spec.market is not lifecycle.market:
        raise ValueError("lifecycle market no longer matches the registry")
    return DatasetLifecycleEvaluation(
        lifecycle=lifecycle,
        health=evaluate_dataset_health(
            spec,
            expected_date=expected_date,
            latest_date=latest_date,
            checked_at=checked_at,
            eligible=eligible,
            partial=partial,
            provider_available=provider_available,
        ),
    )


__all__ = [
    "DatasetLifecycleContract",
    "DatasetLifecycleEvaluation",
    "dataset_lifecycle_contract",
    "evaluate_lifecycle",
    "require_refresh_contract",
]
