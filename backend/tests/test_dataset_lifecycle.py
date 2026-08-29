from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.market_data.contracts import (
    DatasetHealthStatus,
    InstrumentKey,
    InstrumentType,
    Market,
)
from app.market_data.dataset_lifecycle import (
    DatasetOperationRegistry,
    DatasetOperationResult,
    DatasetOperationStatus,
    dataset_lifecycle_contract,
    evaluate_lifecycle,
    require_refresh_contract,
)
from app.market_data.integration_contracts import (
    InstrumentTarget,
    RefreshCoverageScopeV1,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose


def test_full_market_tw_lifecycle_is_derived_from_registry() -> None:
    lifecycle = dataset_lifecycle_contract("tw.daily.ohlcv.full_market")
    bounds = require_refresh_contract(
        lifecycle,
        operation="tw.reconcile_full_market_eod",
    )

    assert lifecycle.owner == "app.market_data.eod_coverage"
    assert lifecycle.read_operation == "cached_eod_coverage_projection"
    assert lifecycle.refresh_operation == "tw.reconcile_full_market_eod"
    assert lifecycle.postcondition
    assert bounds.max_calls == 2
    assert bounds.max_symbols == 2
    assert bounds.max_range_days == 1


def test_lifecycle_evaluation_keeps_missing_partial_and_stale_distinct() -> None:
    lifecycle = dataset_lifecycle_contract("tw.daily.ohlcv.full_market")
    checked_at = datetime(2026, 8, 25, tzinfo=timezone.utc)

    missing = evaluate_lifecycle(
        lifecycle,
        expected_date=date(2026, 8, 25),
        latest_date=None,
        checked_at=checked_at,
        eligible=True,
    )
    partial = evaluate_lifecycle(
        lifecycle,
        expected_date=date(2026, 8, 25),
        latest_date=date(2026, 8, 25),
        checked_at=checked_at,
        eligible=True,
        partial=True,
    )
    stale = evaluate_lifecycle(
        lifecycle,
        expected_date=date(2026, 8, 25),
        latest_date=date(2026, 8, 24),
        checked_at=checked_at,
        eligible=True,
    )

    assert missing.health.status is DatasetHealthStatus.MISSING
    assert partial.health.status is DatasetHealthStatus.PARTIAL
    assert stale.health.status is DatasetHealthStatus.STALE


def test_priority_dataset_owns_its_bounded_repair_operation() -> None:
    lifecycle = dataset_lifecycle_contract("us.daily.ohlcv.priority_research")

    bounds = require_refresh_contract(
        lifecycle,
        operation="us.reconcile_priority_daily_ohlcv",
    )

    assert lifecycle.repairable is True
    assert bounds.max_symbols == 20


def test_us_daily_dataset_owns_bounded_history_coverage_operation() -> None:
    lifecycle = dataset_lifecycle_contract("us.daily.ohlcv")

    bounds = require_refresh_contract(
        lifecycle,
        operation="us.ensure_daily_history_coverage",
    )

    assert lifecycle.refresh_operation == "us.refresh_daily_ohlcv"
    assert bounds.max_calls == 2
    assert bounds.max_symbols == 1


def test_shared_lifecycle_contract_has_no_db_job_scheduler_or_provider_imports() -> None:
    path = Path(__file__).parents[1] / "app" / "market_data" / "dataset_lifecycle.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )

    assert not any(
        name.startswith(
            (
                "app.db",
                "app.jobs",
                "app.market.providers",
                "app.pipelines",
                "app.us_market",
            )
        )
        for name in imports
    )


def _refresh_requirement(*, max_calls: int = 1) -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv.full_market",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="2330",
                instrument_type=InstrumentType.STOCK,
                venue="TWSE",
            )
        ),
        from_date=date(2026, 8, 25),
        to_date=date(2026, 8, 25),
        requested_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        reason_code="EXPECTED_SESSION_MISSING",
        max_provider_attempts=max_calls,
        max_external_calls=max_calls,
        timeout_seconds=120,
        max_symbols=1,
        max_range_days=1,
        postcondition="Expected session is classified after mandatory reread.",
    )


def test_dataset_operation_dispatch_is_typed_bounded_and_identity_checked() -> None:
    operations = DatasetOperationRegistry()
    operations.register(
        dataset_id="tw.daily.ohlcv.full_market",
        operation="tw.reconcile_full_market_eod",
        handler=lambda requirement: DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation="tw.reconcile_full_market_eod",
            status=DatasetOperationStatus.COMPLETED,
            expected_date=date(2026, 8, 25),
            latest_date=date(2026, 8, 25),
            target_count=1,
            completed_count=1,
            checkpoint_id="tw-eod-20260825",
            postcondition_met=True,
        ),
    )

    result = operations.execute(_refresh_requirement())

    assert result.status is DatasetOperationStatus.COMPLETED
    assert result.postcondition_met is True
    assert result.latest_date == date(2026, 8, 25)

    with pytest.raises(ValueError, match="max_calls"):
        operations.execute(_refresh_requirement(max_calls=3))


def test_dataset_operation_missing_binding_and_false_success_fail_closed() -> None:
    with pytest.raises(LookupError, match="no executable binding"):
        DatasetOperationRegistry().execute(_refresh_requirement())

    with pytest.raises(ValueError, match="satisfied postcondition"):
        DatasetOperationResult(
            dataset_id="tw.daily.ohlcv.full_market",
            operation="tw.reconcile_full_market_eod",
            status=DatasetOperationStatus.COMPLETED,
            postcondition_met=False,
        )


def test_dataset_operation_dispatches_explicit_additional_operation() -> None:
    operations = DatasetOperationRegistry()
    operation = "us.ensure_daily_history_coverage"
    operations.register(
        dataset_id="us.daily.ohlcv",
        operation=operation,
        handler=lambda requirement: DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation=operation,
            status=DatasetOperationStatus.COMPLETED,
            expected_date=date(2026, 8, 28),
            latest_date=date(2026, 8, 28),
            target_count=1,
            completed_count=1,
            postcondition_met=True,
        ),
    )
    requirement = RefreshRequirementV1(
        dataset_id="us.daily.ohlcv",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.US,
                symbol="AAPL",
                instrument_type=InstrumentType.STOCK,
                venue="NASDAQ",
            )
        ),
        to_date=date(2026, 8, 28),
        requested_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        reason_code="INSUFFICIENT_HISTORY",
        coverage=RefreshCoverageScopeV1(
            scope_key="instrument:AAPL",
            target_count=1,
            requested_symbols=("AAPL",),
            minimum_observation_count=260,
        ),
        max_provider_attempts=2,
        max_external_calls=2,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=780,
        postcondition="Current provider-coherent history has at least 260 bars.",
    )

    result = operations.execute(requirement, operation=operation)

    assert result.status is DatasetOperationStatus.COMPLETED
    assert result.operation == operation
