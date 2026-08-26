from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path

from app.market_data.contracts import DatasetHealthStatus
from app.market_data.dataset_lifecycle import (
    dataset_lifecycle_contract,
    evaluate_lifecycle,
    require_refresh_contract,
)


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
