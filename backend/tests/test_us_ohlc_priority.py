from __future__ import annotations

from unittest.mock import Mock, patch
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs import backfill_tasks
from app.db.models import (
    Base,
    PortfolioHolding,
    USWatchlistGroup,
    USWatchlistItem,
)
from app.us_market.ohlc_priority import (
    PRIORITY_US_INDEX_SYMBOLS,
    list_us_priority_ohlc_symbols,
    reconcile_us_priority_ohlc,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def _platform_result(*, satisfied: bool, attempts: int = 0):
    return SimpleNamespace(
        postcondition_satisfied=satisfied,
        temporal_postcondition_satisfied=satisfied,
        coverage_postcondition_satisfied=satisfied,
        projection={
            "coverage_status": "complete" if satisfied else "partial",
            "latest_trade_date": "2026-08-28" if satisfied else None,
            "expected_trade_date": "2026-08-28",
        },
        result=SimpleNamespace(
            acquisition=SimpleNamespace(attempts=tuple(range(attempts)))
        ),
    )


def test_priority_universe_orders_indices_holdings_then_enabled_watchlist() -> None:
    db = _session()
    try:
        group = USWatchlistGroup(group_name="US", is_active=True)
        db.add(group)
        db.flush()
        db.add_all(
            [
                PortfolioHolding(
                    market="US",
                    symbol="UMC",
                    quantity=100,
                    currency="USD",
                    is_active=True,
                ),
                USWatchlistItem(
                    group_id=group.id,
                    symbol="AAPL",
                    priority=10,
                    enabled=True,
                ),
                USWatchlistItem(
                    group_id=group.id,
                    symbol="UMC",
                    priority=100,
                    enabled=True,
                ),
                USWatchlistItem(
                    group_id=group.id,
                    symbol="DISABLED",
                    priority=1,
                    enabled=False,
                ),
            ]
        )
        db.commit()

        symbols = list_us_priority_ohlc_symbols(db)

        assert symbols[: len(PRIORITY_US_INDEX_SYMBOLS)] == PRIORITY_US_INDEX_SYMBOLS
        assert symbols.count("UMC") == 1
        assert symbols.index("UMC") < symbols.index("AAPL")
        assert "DISABLED" not in symbols
    finally:
        db.close()


def test_priority_reconcile_can_audit_without_provider_io_or_false_completion() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=False)
        with (
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                return_value=("^GSPC", "UMC"),
            ),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
                repair=False,
            )

        assert result["status"] == "partial"
        assert result["repair_available"] is True
        assert result["repair_requested"] is False
        assert result["external_call_count"] == 0
        assert result["provider_call_count"] == 0
        assert result["satisfied_count"] == 0
        assert result["unresolved_count"] == 2
        assert result["stopped_reason"] == "shared_core_postcondition_unsatisfied"
        assert {
            item["reason"] for item in result["unresolved_sample"]
        } == {"repair_not_requested"}
        platform.ensure_history_coverage.assert_not_called()
    finally:
        db.close()


def test_priority_reconcile_rotates_after_durable_cursor() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=True)
        with (
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                return_value=("^GSPC", "UMC", "AAPL"),
            ),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                cursor_symbol="UMC",
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
            )

        checked_symbols = [
            call.kwargs["symbol"] for call in platform.read.call_args_list
        ]
        assert checked_symbols == ["AAPL", "^GSPC", "UMC"]
        assert result["status"] == "completed"
        assert result["cursor_symbol"] == "UMC"
    finally:
        db.close()


def test_priority_reconcile_repairs_through_same_platform_with_bounded_calls() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=False)
        platform.ensure_history_coverage.return_value = _platform_result(
            satisfied=True,
            attempts=2,
        )
        with patch(
            "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
            return_value=("^GSPC",),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
            )

        assert result["status"] == "completed"
        assert result["repaired_count"] == 1
        assert result["provider_call_count"] == 2
        platform.ensure_history_coverage.assert_called_once_with(
            symbol="^GSPC",
            bars=72,
        )
    finally:
        db.close()


def test_priority_tracked_job_does_not_reuse_job_status_session_for_market_io() -> None:
    job_db = Mock()
    progress = Mock()

    def run_inline(job_id, worker) -> None:
        assert job_id == 99
        worker(job_db, progress)

    with (
        patch.object(backfill_tasks, "run_tracked_job", side_effect=run_inline),
        patch.object(
            backfill_tasks,
            "reconcile_us_priority_ohlc",
            return_value={"status": "completed"},
        ) as reconcile,
    ):
        backfill_tasks.run_us_priority_ohlc_reconcile_job(
            99,
            30,
            None,
        )

    assert "db" not in reconcile.call_args.kwargs
    assert reconcile.call_args.kwargs["progress_callback"] is progress
