from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    PortfolioHolding,
    StockMaster,
    WatchlistGroup,
    WatchlistItem,
)
from app.jobs.taiwan_intraday_bar_scheduler import (
    TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES,
    TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND,
    add_taiwan_intraday_bar_jobs,
    collect_taiwan_intraday_bars,
    reconcile_taiwan_intraday_close_tails,
)
from app.market.quote_contract_health import resolve_taiwan_quote_contract_universe
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_universe import (
    resolve_taiwan_intraday_target_universe,
    resolve_taiwan_tier_a_target_plan,
)


class _FakeDb:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.closed = False

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, function, **kwargs) -> None:
        self.jobs.append({"function": function, **kwargs})


def test_intraday_bar_scheduler_skips_outside_market_window() -> None:
    session_opened = False

    def session_factory():
        nonlocal session_opened
        session_opened = True
        return _FakeDb()

    result = collect_taiwan_intraday_bars(
        now=datetime(2026, 8, 28, 15, 0, tzinfo=TAIWAN_TZ),
        session_factory=session_factory,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "outside_taiwan_intraday_acquisition_window"
    assert session_opened is False


def _scheduler_db():
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine)


def test_scheduler_submits_canonical_jobs_without_claiming_completed_evidence(monkeypatch):
    from app.jobs import taiwan_intraday_bar_scheduler as subject
    monkeypatch.setattr(subject.settings, "job_worker_max_concurrency", 3)
    engine, factory = _scheduler_db()
    seen = []
    def enqueuer(db, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(id=len(seen), status="running"), True
    try:
        result = subject.collect_taiwan_intraday_bars(
            now=datetime(2026, 9, 21, 10, 0, tzinfo=TAIWAN_TZ),
            session_factory=factory,
            universe_resolver=lambda db: {"symbols": ["2330", "0050", "2317"]},
            enqueuer=enqueuer)
        assert [item["stock_id"] for item in seen] == ["2330", "0050"]
        assert all(item["consumer"] == "scheduler" and item["max_external_calls"] == 2 for item in seen)
        assert result["status"] == "pending" and result["refreshed_count"] == 0
        seen.clear()
        subject.collect_taiwan_intraday_bars(
            now=datetime(2026, 9, 21, 10, 5, tzinfo=TAIWAN_TZ),
            session_factory=factory,
            universe_resolver=lambda db: {"symbols": ["2330", "0050", "2317"]},
            enqueuer=enqueuer)
        assert seen[0]["stock_id"] == "2317"
    finally:
        engine.dispose()


def test_intraday_bar_scheduler_registers_coalesced_command_owners():
    scheduler = _FakeScheduler()
    assert add_taiwan_intraday_bar_jobs(scheduler)
    by_id = {item["id"]: item for item in scheduler.jobs}
    assert {"taiwan_intraday_bar_materialization", "taiwan_intraday_completed_coverage",
            "taiwan_intraday_materialization_retry"} <= by_id.keys()
    from app.config import settings
    assert by_id["taiwan_intraday_bar_materialization"]["seconds"] == settings.scheduler_taiwan_intraday_bar_interval_seconds
    assert by_id["taiwan_intraday_completed_coverage"]["seconds"] == settings.scheduler_taiwan_completed_materialization_interval_seconds
    tails = [item for item in scheduler.jobs if item["id"].startswith("taiwan_intraday_close_tail_")]
    assert [item["minute"] for item in tails] == list(TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES)
    assert {item["second"] for item in tails} == {TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND}
    assert all(item["coalesce"] and item["max_instances"] == 1 for item in scheduler.jobs)


def test_close_tail_commands_cover_post_1330_resolution_window():
    engine, factory = _scheduler_db()
    seen = []
    try:
        for minute in (25, 30, 33):
            result = reconcile_taiwan_intraday_close_tails(
                now=datetime(2026, 9, 21, 13, minute, 5, tzinfo=TAIWAN_TZ),
                session_factory=factory, universe_resolver=lambda db, **kw: {"symbols": ["2330"]},
                enqueuer=lambda db, **kw: (seen.append(kw) or SimpleNamespace(id=1, status="running"), False))
            assert result["status"] == "pending"
        assert len(seen) == 3
        assert all(item["consumer"] == "close_tail" for item in seen)
        assert all(item["trade_date"] == "2026-09-21" for item in seen)
    finally:
        engine.dispose()


def test_completed_audit_uses_normal_lane_without_repair_budget(monkeypatch):
    from app.jobs import taiwan_intraday_bar_scheduler as subject
    from app.jobs import taiwan_intraday_demand as demand
    engine, factory = _scheduler_db()
    seen = []
    with factory() as db:
        db.add_all([StockMaster(stock_id=str(2000+i), stock_name="fixture", market="TWSE",
                   instrument_type="stock", is_active=True) for i in range(70)])
        db.commit()
    reread = lambda db, request, now: {"reread_ready": False,
        "reread_trade_date": request["trade_date"], "current_session_bar_count": 0}
    monkeypatch.setattr(subject, "_reread", reread)
    monkeypatch.setattr(demand, "_reread", reread)
    monkeypatch.setattr(demand.jobs, "submit_job_task", lambda task, job_id, **kw: seen.append(kw))
    monkeypatch.setattr(subject.settings, "scheduler_taiwan_intraday_repair_max_symbols_per_window", 0)
    try:
        for _ in range(5):
            result = subject.audit_completed_taiwan_intraday_coverage(
                now=datetime(2026, 9, 21, 15, 0, tzinfo=TAIWAN_TZ), session_factory=factory)
        assert result["coverage_scan_complete"] and result["audited_count"] == 70
        assert result["pending_count"] == 67 and result["active_count"] == 3
        assert result["pending_repair_count"] == result["active_repair_count"] == 0
        assert result["admissions_reserved"] == 0
        assert not result["lifecycle_complete"]
        assert len(seen) == 3 and all(c["execution_lane"] == "market_completed" for c in seen)
    finally:
        engine.dispose()


def test_close_tail_reconciliation_skips_outside_window_without_opening_db():
    def forbidden():
        raise AssertionError("out-of-window command cannot open a DB")
    result = reconcile_taiwan_intraday_close_tails(
        now=datetime(2026, 8, 28, 13, 24, 59, tzinfo=TAIWAN_TZ),
        session_factory=forbidden)
    assert result["status"] == "skipped"


def test_intraday_target_universe_merges_tier_a_sources_and_keeps_etf() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="3711",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="0050",
                    market="TWSE",
                    instrument_type="ETF",
                ),
                StockMaster(
                    stock_id="6488",
                    market="TPEX",
                    instrument_type="stock",
                ),
                PortfolioHolding(
                    market="tw",
                    symbol="3711",
                    quantity=1000,
                    currency="TWD",
                    is_active=True,
                ),
            ]
        )
        group = WatchlistGroup(group_name="active", is_active=True)
        db.add(group)
        db.flush()
        db.add_all(
            [
                WatchlistItem(
                    group_id=group.id,
                    stock_id="0050",
                    priority=10,
                    enabled=True,
                ),
                WatchlistItem(
                    group_id=group.id,
                    stock_id="6488",
                    priority=20,
                    enabled=True,
                ),
            ]
        )
        db.commit()

        universe = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=3,
            configured_symbols=["2330"],
            lease_symbols=["0050"],
        )

        assert universe["symbols"] == ["2330", "3711", "0050"]
        assert universe["eligible_count"] == 4
        assert universe["selected_count"] == 3
        assert universe["skipped_count"] == 1
        assert universe["targets"][2]["instrument_type"] == "ETF"
        assert universe["targets"][2]["origins"] == [
            "active_lease",
            "watchlist",
        ]
        assert universe["skipped_targets"] == [
            {
                "stock_id": "6488",
                "reason": "scheduler_hard_cap",
                "origins": ["watchlist"],
            }
        ]
    finally:
        db.close()
        engine.dispose()


def test_intraday_target_universe_prioritizes_active_watchlist_etfs_within_bound() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="0050",
                    market="TWSE",
                    instrument_type="ETF",
                ),
                StockMaster(
                    stock_id="0056",
                    market="TWSE",
                    instrument_type="etf",
                ),
            ]
        )
        group = WatchlistGroup(group_name="active", is_active=True)
        db.add(group)
        db.flush()
        db.add_all(
            [
                WatchlistItem(
                    group_id=group.id,
                    stock_id="2330",
                    priority=1,
                    enabled=True,
                ),
                WatchlistItem(
                    group_id=group.id,
                    stock_id="0056",
                    priority=30,
                    enabled=True,
                ),
                WatchlistItem(
                    group_id=group.id,
                    stock_id="0050",
                    priority=20,
                    enabled=True,
                ),
            ]
        )
        db.commit()

        plan = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=2,
            configured_symbols=[],
            lease_symbols=[],
        )

        assert plan["symbols"] == ["0050", "0056"]
        assert [target["instrument_type"].lower() for target in plan["targets"]] == [
            "etf",
            "etf",
        ]
        assert plan["skipped_targets"] == [
            {
                "stock_id": "2330",
                "reason": "scheduler_hard_cap",
                "origins": ["watchlist"],
            }
        ]
    finally:
        db.close()
        engine.dispose()


def test_intraday_target_universe_reports_unknown_and_inactive_targets() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add(
            StockMaster(
                stock_id="2330",
                market="TWSE",
                instrument_type="stock",
                is_active=False,
            )
        )
        db.commit()

        universe = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=3,
            configured_symbols=["2330", "999999"],
            lease_symbols=[],
        )

        assert universe["symbols"] == []
        assert universe["candidate_count"] == 2
        assert universe["eligible_count"] == 0
        assert [item["reason"] for item in universe["skipped_targets"]] == [
            "inactive_instrument",
            "target_not_found",
        ]
    finally:
        db.close()
        engine.dispose()


def test_viewer_selected_symbol_enters_and_leaves_plan_only_via_active_lease() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add(
            StockMaster(
                stock_id="3711",
                market="TWSE",
                instrument_type="stock",
            )
        )
        db.commit()

        before = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=3,
            configured_symbols=[],
            lease_symbols=[],
        )
        active = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=3,
            configured_symbols=[],
            lease_symbols=["3711"],
        )
        expired = resolve_taiwan_intraday_target_universe(
            db,
            max_symbols=3,
            configured_symbols=[],
            lease_symbols=[],
        )

        assert before["symbols"] == []
        assert active["symbols"] == ["3711"]
        assert active["targets"][0]["origins"] == ["active_lease"]
        assert expired["symbols"] == []
    finally:
        db.close()
        engine.dispose()


def test_acceptance_canary_is_an_explicit_subset_of_the_shared_plan() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="3711",
                    market="TWSE",
                    instrument_type="stock",
                ),
                PortfolioHolding(
                    market="tw",
                    symbol="3711",
                    quantity=1000,
                    currency="TWD",
                    is_active=True,
                ),
            ]
        )
        db.commit()

        plan = resolve_taiwan_tier_a_target_plan(
            db,
            operation_profile="acceptance_canary",
            max_symbols=5,
            configured_symbols=["2330"],
            lease_symbols=[],
        )

        assert plan["symbols"] == ["2330"]
        assert plan["operation_profile"] == "acceptance_canary"
        assert plan["profile_semantics"] == (
            "configured_canary_subset_of_canonical_plan"
        )
        assert plan["candidate_count"] == 2
        assert plan["eligible_count"] == 2
        assert plan["skipped_targets"] == [
            {
                "stock_id": "3711",
                "reason": "acceptance_canary_profile_excluded",
                "origins": ["holding"],
            }
        ]
    finally:
        db.close()
        engine.dispose()


def test_quote_contract_universe_projects_the_shared_acceptance_profile(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="3711",
                    market="TWSE",
                    instrument_type="stock",
                ),
                PortfolioHolding(
                    market="tw",
                    symbol="3711",
                    quantity=1000,
                    currency="TWD",
                    is_active=True,
                ),
            ]
        )
        db.commit()
        monkeypatch.setattr(
            "app.market.tw_intraday_universe.settings."
            "scheduler_taiwan_quote_contract_symbols",
            "2330",
        )
        monkeypatch.setattr(
            "app.market.quote_contract_health.settings."
            "scheduler_taiwan_quote_contract_max_symbols",
            3,
        )

        universe = resolve_taiwan_quote_contract_universe(db)

        assert universe["symbols"] == ["2330"]
        assert universe["source"] == (
            "shared_tier_a_target_plan:acceptance_canary"
        )
        assert universe["target_plan"]["operation_profile"] == (
            "acceptance_canary"
        )
        assert universe["target_plan"]["candidate_count"] == 2
    finally:
        db.close()
        engine.dispose()
