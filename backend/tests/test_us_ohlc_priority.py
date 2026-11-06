from __future__ import annotations

from unittest.mock import Mock, patch
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.jobs import backfill_tasks, scheduler
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.utils.owner_checkpoint import OwnerOutcomeUnknown
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
)
from app.db.models import (
    Base,
    JobRun,
    PortfolioHolding,
    USWatchlistGroup,
    USWatchlistItem,
)
from app.us_market.ohlc_priority import (
    PRIORITY_DAILY_RESEARCH_CONTRACT,
    PRIORITY_US_INDEX_SYMBOLS,
    list_us_priority_ohlc_critical_symbols,
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
            acquisition=AcquisitionSummary(
                attempted=attempts > 0,
                status=(
                    AcquisitionStatus.COMPLETED
                    if attempts > 0
                    else AcquisitionStatus.NOT_ATTEMPTED
                ),
                external_calls=attempts,
            )
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
        assert list_us_priority_ohlc_critical_symbols(db) == (
            *PRIORITY_US_INDEX_SYMBOLS,
            "UMC",
        )
    finally:
        db.close()


def test_priority_research_contract_is_daily_with_technical_history_depth() -> None:
    assert PRIORITY_US_INDEX_SYMBOLS == (
        "^GSPC",
        "^DJI",
        "^IXIC",
        "^SOX",
        "^NDX",
        "^VIX",
    )
    assert PRIORITY_DAILY_RESEARCH_CONTRACT.dataset_id == (
        "us.daily.ohlcv.priority_research"
    )
    assert PRIORITY_DAILY_RESEARCH_CONTRACT.timeframe == "daily"
    assert PRIORITY_DAILY_RESEARCH_CONTRACT.minimum_bar_count == 260


def test_lowercase_holdings_share_critical_prefix_with_legacy_market_case():
    db = _session()
    try:
        active = USWatchlistGroup(group_name="active", is_active=True)
        inactive = USWatchlistGroup(group_name="inactive", is_active=False)
        db.add_all([active, inactive])
        db.flush()
        db.add_all([PortfolioHolding(market=market, symbol=symbol, quantity=1,
            currency="USD", is_active=enabled) for market, symbol, enabled in (
                ("us", "AAPL", True), ("us", "MSFT", True), ("US", "MSFT", True),
                (" Us ", "TSM", True), ("us", "INACTIVE", False), ("tw", "2330", True))])
        db.add_all([USWatchlistItem(group_id=group, symbol=symbol, enabled=enabled, priority=priority)
            for group, symbol, enabled, priority in (
                (active.id, "WATCH", True, 1), (active.id, "MSFT", True, 2),
                (active.id, "DISABLED", False, 3), (inactive.id, "INACTIVE_GROUP", True, 1))])
        db.commit()
        critical = (*PRIORITY_US_INDEX_SYMBOLS, "AAPL", "MSFT", "TSM")
        assert list_us_priority_ohlc_critical_symbols(db) == critical
        assert list_us_priority_ohlc_symbols(db) == (*critical, "WATCH")
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=True)
        result = reconcile_us_priority_ohlc(max_symbols=10, cursor_symbol="WATCH", repair=False,
            session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
        assert [call.kwargs["symbol"] for call in platform.read.call_args_list] == [*critical, "WATCH"]
        assert result["critical_symbol_count"] == len(critical)
        platform.ensure_history_coverage.assert_not_called()
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
        assert result["contract"] == {
            "timeframe": "daily",
            "bars": 260,
            "minimum_observation_count": 260,
            "continuity": "all completed US sessions from first available row",
            "history": (
                "provider-coherent completed-session Daily bars; requests below the "
                "minimum remain partial with explicit coverage limitations"
            ),
        }
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
        assert checked_symbols == ["^GSPC", "AAPL", "UMC"]
        assert result["status"] == "completed"
        assert result["cursor_symbol"] == "UMC"
    finally:
        db.close()


def test_priority_reconcile_never_rotates_critical_targets_behind_watchlist() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=True)
        with (
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                return_value=("^GSPC", "TSM", "AAPL", "MSFT"),
            ),
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols",
                return_value=("^GSPC", "TSM"),
            ),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                max_symbols=3,
                cursor_symbol="AAPL",
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
            )

        checked_symbols = [
            call.kwargs["symbol"] for call in platform.read.call_args_list
        ]
        assert checked_symbols == ["^GSPC", "TSM", "MSFT"]
        assert result["critical_symbol_count"] == 2
        assert result["rotatable_symbol_count"] == 2
        assert result["cursor_symbol"] == "MSFT"
    finally:
        db.close()


def test_successful_shards_continue_one_finite_pass_without_false_full_coverage():
    db = _session()
    platform = Mock()
    platform.read.return_value = _platform_result(satisfied=True)
    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                  return_value=("^GSPC", "AAPL", "MSFT", "TSM")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols",
                  return_value=("^GSPC",)),
        ):
            cursor, remaining, checked = None, None, []
            for _ in range(3):
                platform.reset_mock()
                result = reconcile_us_priority_ohlc(max_symbols=2, cursor_symbol=cursor,
                    continuation_remaining_count=remaining, to_date=date(2026, 9, 28),
                    session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
                checked.extend(c.kwargs["symbol"] for c in platform.read.call_args_list
                               if c.kwargs["symbol"] != "^GSPC")
                assert result["status"] == "partial" and result["universe_count"] == 4
                assert result["expected_trade_date"] == "2026-09-28"
                cursor, remaining = result["cursor_symbol"], result["continuation_remaining_count"]
            assert checked == ["AAPL", "MSFT", "TSM"]
            assert remaining == 0 and not result["continuation_required"]
            platform.ensure_history_coverage.assert_not_called()
    finally:
        db.close()


def test_critical_overflow_rotates_instead_of_starving_later_targets():
    db = _session()
    platform = Mock()
    platform.read.return_value = _platform_result(satisfied=True)
    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                  return_value=("^GSPC", "TSM", "AAPL", "MSFT")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols",
                  return_value=("^GSPC", "TSM", "AAPL")),
        ):
            first = reconcile_us_priority_ohlc(max_symbols=2,
                session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
            assert first["continuation_required"]
            second = reconcile_us_priority_ohlc(max_symbols=2, cursor_symbol=first["cursor_symbol"],
                continuation_remaining_count=first["continuation_remaining_count"],
                session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
            assert [c.kwargs["symbol"] for c in platform.read.call_args_list] == ["^GSPC", "TSM", "AAPL", "MSFT"]
            assert not second["continuation_required"]
    finally:
        db.close()


def test_priority_reconcile_promotes_required_consumer_symbols() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=True)
        with (
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                return_value=("^GSPC", "AAPL"),
            ),
            patch(
                "app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols",
                return_value=("^GSPC",),
            ),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                max_symbols=2,
                required_symbols=("SMH", "TSM", "SMH"),
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
            )

        checked_symbols = [
            call.kwargs["symbol"] for call in platform.read.call_args_list
        ]
        assert checked_symbols == ["^GSPC", "SMH"]
        assert result["required_consumer_symbols"] == ["SMH", "TSM"]
        assert result["critical_symbol_count"] == 3
        assert result["stopped_reason"] == "symbol_budget_exhausted"
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
            bars=260,
            to_date=None,
            now=None,
            max_provider_calls=2,
        )
        platform.read.assert_called_once_with(
            symbol="^GSPC",
            bars=260,
            to_date=None,
            now=None,
        )
    finally:
        db.close()


def test_priority_reconcile_enforces_symbol_and_external_call_budgets() -> None:
    db = _session()
    try:
        platform = Mock()
        platform.read.return_value = _platform_result(satisfied=False)
        platform.ensure_history_coverage.return_value = _platform_result(
            satisfied=False,
            attempts=1,
        )
        with patch(
            "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
            return_value=("^GSPC", "^DJI", "AAPL"),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                max_symbols=2,
                max_external_calls=1,
                max_provider_attempts=2,
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: platform,
            )

        assert result["status"] == "partial"
        assert result["universe_count"] == 3
        assert result["run_target_count"] == 2
        assert result["checked_count"] == 2
        assert result["external_call_count"] == 1
        assert result["unscanned_count"] == 1
        assert result["continuation_required"]
        assert result["continuation_remaining_count"] == 1
        platform.ensure_history_coverage.assert_called_once_with(
            symbol="^GSPC",
            bars=260,
            to_date=None,
            now=None,
            max_provider_calls=1,
        )
    finally:
        db.close()


def test_priority_reconcile_isolates_one_symbol_failure() -> None:
    db = _session()
    try:
        failed = Mock()
        failed.read.side_effect = RuntimeError("provider contract failed")
        healthy = Mock()
        healthy.read.return_value = _platform_result(satisfied=True)
        platforms = iter((failed, healthy))
        with patch(
            "app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
            return_value=("^GSPC", "AAPL"),
        ):
            result = reconcile_us_priority_ohlc(
                max_runtime_seconds=30,
                session_factory=lambda: Session(db.get_bind()),
                platform_factory=lambda _db: next(platforms),
            )

        assert result["status"] == "partial"
        assert result["checked_count"] == 2
        assert result["satisfied_count"] == 1
        assert result["error_count"] == 1
        assert not result["continuation_required"]
        assert result["errors"][0]["symbol"] == "^GSPC"
        assert result["errors"][0]["error_type"] == "RuntimeError"
        healthy.read.assert_called_once()
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


@pytest.mark.parametrize("failure", ["identity", "known_read_error", "incomplete"])
def test_partial_priority_continues_finite_unscanned_pass_through_scheduler(failure):
    db = _session()
    factory = sessionmaker(db.get_bind())
    reads, acquisitions = [], []
    now = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)

    class Platform:
        def __init__(self, chart_db):
            self.db = chart_db

        def read(self, **kwargs):
            symbol = kwargs["symbol"]
            reads.append(symbol)
            if symbol == "BK":
                if failure == "identity":
                    # Exercise the real canonical master lookup; no provider IO.
                    return USDailyOhlcvPlatform(self.db).read(**kwargs)
                if failure == "known_read_error":
                    raise ValueError("fixture known per-symbol read failure")
                return _platform_result(satisfied=False)
            return _platform_result(satisfied=True)

        def ensure_history_coverage(self, symbol, max_provider_calls, **kwargs):
            acquisitions.append((symbol, max_provider_calls))
            return _platform_result(satisfied=False, attempts=1)

    def run(request):
        return reconcile_us_priority_ohlc(
            **{key: value for key, value in request.items() if key != "expected_trade_date"},
            to_date=date(2026, 9, 28), requested_at=now,
            session_factory=factory, platform_factory=Platform)

    request = dict(max_runtime_seconds=30, max_symbols=3, max_external_calls=1,
        max_provider_attempts=2, required_symbols=["SMH"], cursor_symbol=None,
        continuation_remaining_count=None)
    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols",
                return_value=("^GSPC", "BK", "AAPL", "MSFT")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols",
                return_value=("^GSPC",)),
            patch.object(scheduler, "SessionLocal", factory),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_interval_minutes", 30),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_continuation_interval_seconds", 60),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_max_symbols", 3),
            patch.object(scheduler.settings, "scheduler_us_priority_ohlc_max_external_calls", 1),
            patch.object(scheduler, "list_active_cross_market_us_requirement_symbols", return_value=("SMH",)),
            patch.object(scheduler.job_service, "enqueue_job", return_value=(Mock(id=99), True)) as enqueue,
        ):
            for index, symbol in enumerate(("BK", "AAPL", "MSFT")):
                result = run(request)
                assert result["status"] == "partial" and result["checked_count"] == 3
                assert result["cursor_symbol"] == symbol
                assert result["continuation_remaining_count"] == 2 - index
                assert result["continuation_required"] is (index < 2)
                if index == 0:
                    assert result["satisfied_count"] == 2 and result["unscanned_count"] == 2
                    assert result["unresolved_count"] == 3
                    if failure == "incomplete":
                        assert result["unresolved_sample"][0]["symbol"] == "BK"
                        assert result["unresolved_sample"][0]["reason"] == "shared_core_postcondition_unsatisfied"
                        assert result["external_call_count"] == result["external_call_budget_used"] == 1
                    else:
                        assert result["errors"][0]["symbol"] == "BK" and result["error_count"] == 1
                        assert result["external_call_count"] == 0
                        if failure == "identity":
                            assert result["errors"][0]["error_type"] == "USInstrumentIdentityUnavailableError"
                with factory() as receipt_db:
                    receipt_db.add(JobRun(job_type=scheduler.US_PRIORITY_OHLC_RECONCILE_JOB_TYPE,
                        status="success", target="priority-research", ended_at=now,
                        result_json=json.dumps(result, default=str)))
                    receipt_db.commit()
                enqueue.reset_mock()
                scheduler.enqueue_us_priority_ohlc_reconcile(now=now + timedelta(seconds=59))
                enqueue.assert_not_called()
                scheduler.enqueue_us_priority_ohlc_reconcile(now=now + timedelta(seconds=60))
                assert enqueue.call_count == int(index < 2)
                if index < 2:
                    request = enqueue.call_args.kwargs["request"]
                    assert request["cursor_symbol"] == symbol
                    assert request["continuation_remaining_count"] == 2 - index
                    assert request["required_symbols"] == ["SMH"]
                now += timedelta(seconds=60)
            assert reads == ["^GSPC", "SMH", "BK", "^GSPC", "SMH", "AAPL", "^GSPC", "SMH", "MSFT"]
            assert acquisitions == ([("BK", 1)] if failure == "incomplete" else [])
            # The ordinary round revisits unresolved symbols after the pass ends.
            scheduler.enqueue_us_priority_ohlc_reconcile(now=now + timedelta(minutes=30))
            request = enqueue.call_args.kwargs["request"]
            assert request["continuation_remaining_count"] is None
            assert run(request)["cursor_symbol"] == "BK"
            assert reads.count("BK") == 2
    finally:
        db.close()
        db.get_bind().dispose()


@pytest.mark.parametrize("usage", [None, True, -1, 3, "exception"])
def test_priority_unknown_usage_stops_continuation_and_keeps_reservation(usage):
    db = _session()
    platform = Mock()
    platform.read.return_value = _platform_result(satisfied=False)
    result = _platform_result(satisfied=False)
    result.result.acquisition = SimpleNamespace(external_calls=usage)
    if usage == "exception":
        platform.ensure_history_coverage.side_effect = RuntimeError("provider outcome unknown")
    else:
        platform.ensure_history_coverage.return_value = result
    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols", return_value=("BK", "AAPL", "MSFT")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols", return_value=()),
        ):
            result = reconcile_us_priority_ohlc(max_symbols=2, max_external_calls=2,
                session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
        assert result["checked_count"] == 1 and result["continuation_remaining_count"] == 2
        assert result["external_call_count"] is None and result["provider_call_count"] is None
        assert result["external_call_budget_used"] == 2
        assert result["stopped_reason"] == "provider_usage_unknown"
        assert not result["continuation_required"]
        assert platform.read.call_count == platform.ensure_history_coverage.call_count == 1
    finally:
        db.close()


@pytest.mark.parametrize("fault", ["persistence", "rollback"])
def test_priority_unknown_persistence_or_rollback_retains_inflight(fault):
    db = _session()
    ledger = []
    platform = Mock()
    platform.read.side_effect = (OperationalError("fixture query", None, RuntimeError("unknown"))
        if fault == "persistence" else ValueError("fixture read error"))

    class ChartSession(Session):
        def rollback(self):
            if fault == "rollback":
                raise RuntimeError("rollback unknown")
            super().rollback()

    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols", return_value=("BK", "AAPL")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols", return_value=()),
            pytest.raises(OwnerOutcomeUnknown, match=f"US_PRIORITY_{fault.upper()}_UNKNOWN"),
        ):
            reconcile_us_priority_ohlc(max_symbols=1, session_factory=lambda: ChartSession(db.get_bind()),
                platform_factory=lambda _: platform, continuation=lambda phase, state: ledger.append((phase, state)))
        state = ledger[-1][1]
        assert state["inflight"] == {"item": "BK", "calls": 2}
        assert state["totals"]["calls"] == 2 and not state["results"]
        platform.ensure_history_coverage.assert_not_called()
    finally:
        db.close()


@pytest.mark.parametrize("repair,critical,advance", [(False, (), True), (True, ("^GSPC",), False), (True, (), True)])
def test_priority_runtime_boundary_requires_repair_and_cursor_progress(repair, critical, advance):
    db = _session()
    clock = [0.0]
    platform = Mock()

    def read(**kwargs):
        clock[0] += 1
        return _platform_result(satisfied=True)

    platform.read.side_effect = read
    try:
        with (
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_symbols", return_value=("^GSPC", "AAPL", "MSFT")),
            patch("app.us_market.ohlc_priority.list_us_priority_ohlc_critical_symbols", return_value=critical),
            patch("app.us_market.ohlc_priority.monotonic", side_effect=lambda: clock[0]),
        ):
            result = reconcile_us_priority_ohlc(max_runtime_seconds=1, max_symbols=2, repair=repair,
                session_factory=lambda: Session(db.get_bind()), platform_factory=lambda _: platform)
        assert result["checked_count"] == 1 and result["stopped_reason"] == "runtime_budget_exhausted"
        assert result["continuation_required"] is (repair and advance)
        assert result["cursor_symbol"] == ("^GSPC" if advance else None)
        platform.ensure_history_coverage.assert_not_called()
    finally:
        db.close()
