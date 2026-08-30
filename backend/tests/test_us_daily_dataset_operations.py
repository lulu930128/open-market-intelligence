from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.market_data.dataset_lifecycle import DatasetOperationStatus
from app.market_data.integration_contracts import (
    InstrumentTarget,
    RefreshCoverageScopeV1,
    RefreshRequirementV1,
)
from app.market_data.policies import DataPurpose
from app.us_market.dataset_operations import build_us_dataset_operation_registry


def _history_requirement(
    *,
    symbol: str = "AAPL",
    instrument_type: InstrumentType = InstrumentType.STOCK,
    max_calls: int = 2,
) -> RefreshRequirementV1:
    return RefreshRequirementV1(
        dataset_id="us.daily.ohlcv",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.US,
                symbol=symbol,
                instrument_type=instrument_type,
                venue=(
                    "NASDAQ_INDEX"
                    if instrument_type is InstrumentType.INDEX
                    else "NASDAQ"
                ),
            )
        ),
        to_date=date(2026, 8, 28),
        requested_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        reason_code="INSUFFICIENT_HISTORY",
        coverage=RefreshCoverageScopeV1(
            scope_key=f"instrument:{symbol}",
            target_count=1,
            requested_symbols=(symbol,),
            minimum_observation_count=260,
        ),
        max_provider_attempts=max_calls,
        max_external_calls=max_calls,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=780,
        postcondition="Current provider-coherent history has at least 260 bars.",
    )


def test_history_coverage_operation_uses_explicit_platform_method() -> None:
    db = Mock()
    platform = Mock()
    platform.ensure_history_coverage.return_value = SimpleNamespace(
        expected_state=SimpleNamespace(expected_trade_date=date(2026, 8, 28)),
        projection={"latest_trade_date": "2026-08-28"},
        result=SimpleNamespace(limitations=()),
        postcondition_satisfied=True,
    )

    with patch(
        "app.us_market.dataset_operations.USDailyOhlcvPlatform",
        return_value=platform,
    ):
        operations = build_us_dataset_operation_registry(session_factory=lambda: db)
        result = operations.execute(
            _history_requirement(),
            operation="us.ensure_daily_history_coverage",
        )

    assert result.status is DatasetOperationStatus.COMPLETED
    assert result.postcondition_met is True
    assert result.completed_count == 1
    platform.ensure_history_coverage.assert_called_once_with(
        symbol="AAPL",
        bars=260,
        to_date=date(2026, 8, 28),
        now=datetime(2026, 8, 29, tzinfo=timezone.utc),
        max_provider_calls=2,
    )
    db.close.assert_called_once_with()


def test_us_dataset_operation_registry_has_all_repair_bindings() -> None:
    operations = build_us_dataset_operation_registry(session_factory=Mock())

    assert "us.daily.ohlcv" not in operations.missing_repairable_bindings()


def test_index_history_coverage_operation_is_single_target_and_one_call() -> None:
    db = Mock()
    platform = Mock()
    platform.ensure_history_coverage.return_value = SimpleNamespace(
        expected_state=SimpleNamespace(expected_trade_date=date(2026, 8, 28)),
        projection={"latest_trade_date": "2026-08-28"},
        result=SimpleNamespace(limitations=()),
        postcondition_satisfied=True,
    )

    with patch(
        "app.us_market.dataset_operations.USDailyOhlcvPlatform",
        return_value=platform,
    ):
        operations = build_us_dataset_operation_registry(session_factory=lambda: db)
        result = operations.execute(
            _history_requirement(
                symbol="^GSPC",
                instrument_type=InstrumentType.INDEX,
                max_calls=1,
            ),
            operation="us.ensure_daily_history_coverage",
        )

    assert result.status is DatasetOperationStatus.COMPLETED
    platform.ensure_history_coverage.assert_called_once_with(
        symbol="^GSPC",
        bars=260,
        to_date=date(2026, 8, 28),
        now=datetime(2026, 8, 29, tzinfo=timezone.utc),
        max_provider_calls=1,
    )
    db.close.assert_called_once_with()


def test_priority_operation_forwards_all_requirement_bounds() -> None:
    requirement = RefreshRequirementV1(
        dataset_id="us.daily.ohlcv.priority_research",
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.US,
                symbol="^GSPC",
                instrument_type=InstrumentType.INDEX,
                venue="NASDAQ_INDEX",
            )
        ),
        to_date=date(2026, 8, 28),
        requested_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        purpose=DataPurpose.REPAIR,
        reason_code="PRIORITY_RESEARCH_COVERAGE",
        max_provider_attempts=1,
        max_external_calls=7,
        timeout_seconds=45,
        max_symbols=5,
        max_range_days=780,
        postcondition="Priority research universe has canonical Daily coverage.",
    )
    with patch(
        "app.us_market.dataset_operations.reconcile_us_priority_ohlc",
        return_value={
            "status": "partial",
            "universe_count": 8,
            "satisfied_count": 4,
            "cursor_symbol": "^SOX",
        },
    ) as reconcile:
        operations = build_us_dataset_operation_registry(session_factory=Mock())
        result = operations.execute(
            requirement,
            operation="us.reconcile_priority_daily_ohlcv",
        )

    assert result.status is DatasetOperationStatus.PARTIAL
    reconcile.assert_called_once_with(
        max_runtime_seconds=45,
        max_symbols=5,
        max_external_calls=7,
        max_provider_attempts=1,
        cursor_symbol=None,
        to_date=date(2026, 8, 28),
        requested_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        session_factory=ANY,
        repair=True,
    )
