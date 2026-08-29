"""US dataset-operation bindings for the provider-neutral Shared dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.market_data.dataset_lifecycle import (
    DatasetOperationRegistry,
    DatasetOperationResult,
    DatasetOperationStatus,
)
from app.market_data.eod_coverage import reconcile_eod_coverage
from app.market_data.integration_contracts import InstrumentTarget, RefreshRequirementV1
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from app.us_market.ohlc_priority import reconcile_us_priority_ohlc


SessionFactory = Callable[[], Session]


def build_us_dataset_operation_registry(
    *,
    session_factory: SessionFactory = SessionLocal,
) -> DatasetOperationRegistry:
    operations = DatasetOperationRegistry()

    def daily(requirement: RefreshRequirementV1) -> DatasetOperationResult:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("US daily OHLCV refresh requires an instrument target")
        db = session_factory()
        try:
            refreshed = USDailyOhlcvPlatform(db).refresh(
                symbol=requirement.target.instrument.symbol,
                bars=min(max(requirement.max_range_days, 1), 5000),
                to_date=requirement.to_date,
                now=requirement.requested_at,
            )
        finally:
            db.close()
        projection = refreshed.projection
        completed = refreshed.postcondition_satisfied
        return DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation="us.refresh_daily_ohlcv",
            status=(
                DatasetOperationStatus.COMPLETED
                if completed
                else DatasetOperationStatus.PARTIAL
            ),
            expected_date=refreshed.expected_state.expected_trade_date,
            latest_date=(
                None
                if projection.get("latest_trade_date") is None
                else date.fromisoformat(projection["latest_trade_date"])
            ),
            target_count=1,
            completed_count=1 if completed else 0,
            next_cursor=None if completed else requirement.target.instrument.symbol,
            postcondition_met=completed,
            limitations=tuple(refreshed.result.limitations),
        )

    def daily_history_coverage(
        requirement: RefreshRequirementV1,
    ) -> DatasetOperationResult:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("US daily history coverage requires an instrument target")
        coverage = requirement.coverage
        if coverage is None or coverage.minimum_observation_count is None:
            raise ValueError(
                "US daily history coverage requires minimum_observation_count"
            )
        symbol = requirement.target.instrument.symbol
        if coverage.target_count not in {None, 1}:
            raise ValueError("US daily history coverage supports one target per call")
        if coverage.requested_symbols and coverage.requested_symbols != (symbol,):
            raise ValueError(
                "US daily history coverage requested_symbols must match target"
            )
        db = session_factory()
        try:
            refreshed = USDailyOhlcvPlatform(db).ensure_history_coverage(
                symbol=symbol,
                bars=coverage.minimum_observation_count,
                to_date=requirement.to_date,
                now=requirement.requested_at,
                max_provider_calls=min(
                    requirement.max_provider_attempts,
                    requirement.max_external_calls,
                    2,
                ),
            )
        finally:
            db.close()
        projection = refreshed.projection
        completed = refreshed.postcondition_satisfied
        return DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation="us.ensure_daily_history_coverage",
            status=(
                DatasetOperationStatus.COMPLETED
                if completed
                else DatasetOperationStatus.PARTIAL
            ),
            expected_date=refreshed.expected_state.expected_trade_date,
            latest_date=(
                None
                if projection.get("latest_trade_date") is None
                else date.fromisoformat(projection["latest_trade_date"])
            ),
            target_count=1,
            completed_count=1 if completed else 0,
            next_cursor=None if completed else symbol,
            postcondition_met=completed,
            limitations=tuple(refreshed.result.limitations),
        )

    def full_market(requirement: RefreshRequirementV1) -> DatasetOperationResult:
        db = session_factory()
        try:
            result = reconcile_eod_coverage(
                db,
                market="US",
                expected_trade_date=requirement.to_date,
                max_symbols=requirement.max_symbols,
                max_runtime_seconds=requirement.timeout_seconds,
                sleep_seconds=0,
                us_port=US_FULL_MARKET_EOD_LIFECYCLE,
            )
        finally:
            db.close()
        completed = result.get("postcondition_met") is True
        checkpoint = result.get("checkpoint") or {}
        return DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation="us.reconcile_full_market_eod",
            status=(
                DatasetOperationStatus.COMPLETED
                if completed
                else DatasetOperationStatus.PARTIAL
            ),
            expected_date=result.get("expected_trade_date"),
            latest_date=result.get("latest_data_date"),
            target_count=result.get("universe_count"),
            completed_count=result.get("current_count", 0),
            next_cursor=None if completed else (checkpoint.get("cursor_symbol") or "START"),
            checkpoint_id=(
                str(checkpoint["id"]) if checkpoint.get("id") is not None else None
            ),
            postcondition_met=completed,
            limitations=(
                ()
                if completed
                else ("FULL_MARKET_RECONCILE_REQUIRES_CONTINUATION",)
            ),
        )

    def priority(requirement: RefreshRequirementV1) -> DatasetOperationResult:
        result = reconcile_us_priority_ohlc(
            max_runtime_seconds=requirement.timeout_seconds,
            cursor_symbol=(
                requirement.continuation.cursor
                if requirement.continuation is not None
                else None
            ),
            session_factory=session_factory,
            repair=True,
        )
        completed = result.get("status") == "completed"
        return DatasetOperationResult(
            dataset_id=requirement.dataset_id,
            operation="us.reconcile_priority_daily_ohlcv",
            status=(
                DatasetOperationStatus.COMPLETED
                if completed
                else DatasetOperationStatus.PARTIAL
            ),
            expected_date=requirement.to_date,
            target_count=result.get("universe_count"),
            completed_count=result.get("satisfied_count", 0),
            next_cursor=None if completed else (result.get("cursor_symbol") or "START"),
            postcondition_met=completed,
            limitations=(
                ()
                if completed
                else ("PRIORITY_RECONCILE_REQUIRES_CONTINUATION",)
            ),
        )

    operations.register(
        dataset_id="us.daily.ohlcv",
        operation="us.refresh_daily_ohlcv",
        handler=daily,
    )
    operations.register(
        dataset_id="us.daily.ohlcv",
        operation="us.ensure_daily_history_coverage",
        handler=daily_history_coverage,
    )
    operations.register(
        dataset_id="us.daily.ohlcv.full_market",
        operation="us.reconcile_full_market_eod",
        handler=full_market,
    )
    operations.register(
        dataset_id="us.daily.ohlcv.priority_research",
        operation="us.reconcile_priority_daily_ohlcv",
        handler=priority,
    )
    return operations


__all__ = ["build_us_dataset_operation_registry"]
