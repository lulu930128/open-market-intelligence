"""Shared runtime contract for registry-owned market dataset lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from enum import Enum

from app.market_data.contracts import CanonicalModel, DatasetHealth, Market
from app.market_data.integration_contracts import RefreshRequirementV1
from app.market_data.registry import (
    AdditionalRefreshOperation,
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
    additional_refresh_operations: tuple[AdditionalRefreshOperation, ...] = ()
    postcondition: str
    repairable: bool


class DatasetLifecycleEvaluation(CanonicalModel):
    contract_version: str = "omi.market.dataset_lifecycle_evaluation.v1"
    lifecycle: DatasetLifecycleContract
    health: DatasetHealth


class DatasetOperationStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DatasetOperationResult(CanonicalModel):
    """Typed, bounded result returned by an injected market-owned operation."""

    contract_version: str = "omi.market.dataset_operation_result.v1"
    dataset_id: str
    operation: str
    status: DatasetOperationStatus
    expected_date: date | None = None
    latest_date: date | None = None
    target_count: int | None = None
    completed_count: int = 0
    next_cursor: str | None = None
    checkpoint_id: str | None = None
    postcondition_met: bool = False
    limitations: tuple[str, ...] = ()

    def model_post_init(self, __context: object) -> None:
        if self.target_count is not None and self.completed_count > self.target_count:
            raise ValueError("completed_count cannot exceed target_count")
        if self.status is DatasetOperationStatus.COMPLETED and not self.postcondition_met:
            raise ValueError("completed operation requires a satisfied postcondition")
        if self.status is DatasetOperationStatus.PARTIAL and self.next_cursor is None:
            raise ValueError("partial operation requires next_cursor")


DatasetOperation = Callable[[RefreshRequirementV1], DatasetOperationResult]


class DatasetOperationRegistry:
    """Dependency-injected executable bindings; Shared Core owns no market imports."""

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], DatasetOperation] = {}

    def register(
        self,
        *,
        dataset_id: str,
        operation: str,
        handler: DatasetOperation,
        registry: DatasetRegistry = DATASET_REGISTRY,
    ) -> None:
        lifecycle = dataset_lifecycle_contract(dataset_id, registry=registry)
        require_refresh_contract(lifecycle, operation=operation)
        key = (dataset_id, operation)
        if key in self._bindings:
            raise ValueError(f"dataset operation already registered: {dataset_id}/{operation}")
        self._bindings[key] = handler

    def execute(
        self,
        requirement: RefreshRequirementV1,
        *,
        operation: str | None = None,
        registry: DatasetRegistry = DATASET_REGISTRY,
    ) -> DatasetOperationResult:
        lifecycle = dataset_lifecycle_contract(requirement.dataset_id, registry=registry)
        selected_operation = operation or lifecycle.refresh_operation or ""
        bounds = require_refresh_contract(lifecycle, operation=selected_operation)
        if requirement.max_external_calls > bounds.max_calls:
            raise ValueError("refresh requirement exceeds registry max_calls")
        if requirement.timeout_seconds > bounds.timeout_seconds:
            raise ValueError("refresh requirement exceeds registry timeout_seconds")
        if requirement.max_symbols > bounds.max_symbols:
            raise ValueError("refresh requirement exceeds registry max_symbols")
        if requirement.max_range_days > bounds.max_range_days:
            raise ValueError("refresh requirement exceeds registry max_range_days")
        try:
            handler = self._bindings[(requirement.dataset_id, selected_operation)]
        except KeyError as exc:
            raise LookupError(
                f"no executable binding for dataset operation: "
                f"{requirement.dataset_id}/{selected_operation}"
            ) from exc
        result = handler(requirement)
        if (
            result.dataset_id != requirement.dataset_id
            or result.operation != selected_operation
        ):
            raise ValueError("dataset operation result identity does not match binding")
        return result

    def missing_repairable_bindings(
        self,
        *,
        registry: DatasetRegistry = DATASET_REGISTRY,
    ) -> tuple[str, ...]:
        missing = []
        for spec in registry.all():
            if not spec.repairable or not spec.refresh_operation:
                continue
            required_operations = (spec.refresh_operation,) + tuple(
                operation.operation for operation in spec.additional_refresh_operations
            )
            if any(
                (spec.dataset_id, operation) not in self._bindings
                for operation in required_operations
            ):
                missing.append(spec.dataset_id)
        return tuple(sorted(missing))


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
        additional_refresh_operations=spec.additional_refresh_operations,
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
    if lifecycle.refresh_operation == operation:
        bounds = lifecycle.refresh_bounds
    else:
        additional = next(
            (
                candidate
                for candidate in lifecycle.additional_refresh_operations
                if candidate.operation == operation
            ),
            None,
        )
        bounds = additional.bounds if additional is not None else None
    if bounds is None:
        raise ValueError(
            f"dataset '{lifecycle.dataset_id}' does not own bounded refresh operation "
            f"'{operation}'"
        )
    return bounds


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
    "DatasetOperationRegistry",
    "DatasetOperationResult",
    "DatasetOperationStatus",
    "dataset_lifecycle_contract",
    "evaluate_lifecycle",
    "require_refresh_contract",
]
