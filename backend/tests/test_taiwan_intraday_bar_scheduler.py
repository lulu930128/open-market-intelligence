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


def test_intraday_bar_scheduler_materializes_bounded_tier_a_universe() -> None:
    db = _FakeDb()
    refreshed: list[str] = []

    def refresher(_db, *, stock_id: str, **_kwargs):
        refreshed.append(stock_id)
        if stock_id == "3711":
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(
            resolved=SimpleNamespace(
                health=SimpleNamespace(status=SimpleNamespace(value="selected")),
                bars=(object(), object()),
            )
        )

    result = collect_taiwan_intraday_bars(
        now=datetime(2026, 8, 28, 10, 0, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=lambda _db: {
            "symbols": ["2330", "3711"],
            "target": "configured_and_watchlist",
        },
        refresher=refresher,
    )

    assert refreshed == ["2330", "3711"]
    assert result["status"] == "partial"
    assert result["requested_count"] == 2
    assert result["refreshed_count"] == 1
    assert result["failed_count"] == 1
    assert db.rollback_count == 1
    assert db.closed is True


def test_intraday_bar_scheduler_registers_one_coalesced_owner_job() -> None:
    scheduler = _FakeScheduler()

    assert add_taiwan_intraday_bar_jobs(scheduler) is True
    assert len(scheduler.jobs) == 1 + len(TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES)
    job = next(
        item
        for item in scheduler.jobs
        if item["id"] == "taiwan_intraday_bar_materialization"
    )
    assert job["id"] == "taiwan_intraday_bar_materialization"
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    close_tail_jobs = [
        item
        for item in scheduler.jobs
        if item["id"].startswith("taiwan_intraday_close_tail_")
    ]
    assert [item["minute"] for item in close_tail_jobs] == list(
        TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES
    )
    assert {item["second"] for item in close_tail_jobs} == {
        TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND
    }
    assert all(item["coalesce"] is True for item in close_tail_jobs)
    assert all(item["max_instances"] == 1 for item in close_tail_jobs)


def _tail_projection(_db, result):
    coverage = result["coverage"]
    return [object()] * int(coverage.get("observed_bar_count") or 0), {
        "series_coverage": coverage,
        "provider": result.get("provider"),
        "source": result.get("source"),
        "limitations": result.get("limitations", []),
    }


def test_close_tail_reconciliation_is_bounded_fetch_only_and_truthful() -> None:
    db = _FakeDb()
    refreshed: list[str] = []
    seen_max_symbols: list[int] = []

    def universe_resolver(_db, *, max_symbols: int):
        seen_max_symbols.append(max_symbols)
        return {"symbols": ["2330", "2330", "3711"]}

    def reader(_db, *, stock_id: str, **_kwargs):
        return {
            "coverage": {
                "status": "partial_prefix",
                "gap_count": 12,
                "observed_bar_count": 252,
                "continuous_session_covered": False,
            }
        }

    def refresher(_db, *, stock_id: str, descriptors, **_kwargs):
        refreshed.append(stock_id)
        assert [item.provider_key for item in descriptors] == ["nstock", "yahoo_finance_chart"]
        complete = stock_id == "2330"
        return {
            "provider": "nstock",
            "source": "nstock_minute_stock_data",
            "coverage": {
                "status": "complete_session" if complete else "sparse",
                "gap_count": 0 if complete else 2,
                "observed_bar_count": 265 if complete else 263,
                "continuous_session_covered": complete,
                "last_bar_at": "2026-08-28T13:24:00+08:00",
            },
        }

    result = reconcile_taiwan_intraday_close_tails(
        now=datetime(2026, 8, 28, 13, 25, 5, tzinfo=TAIWAN_TZ),
        session_factory=lambda: db,
        universe_resolver=universe_resolver,
        reader=reader,
        refresher=refresher,
        projector=_tail_projection,
        attempt_registry={},
    )

    assert seen_max_symbols == [3]
    assert refreshed == ["2330", "3711"]
    assert result["status"] == "partial"
    assert result["requested_count"] == 2
    assert result["complete_count"] == 1
    assert result["partial_count"] == 1
    assert result["refresh_attempt_count"] == 2
    assert result["results"][1]["after"]["gap_count"] == 2
    assert db.closed is True


def test_close_tail_reconciliation_short_circuits_complete_and_cools_down() -> None:
    registry: dict[tuple[str, str], datetime] = {}
    refreshed: list[str] = []

    def reader(_db, *, stock_id: str, **_kwargs):
        complete = stock_id == "2330"
        return {
            "coverage": {
                "status": "complete_session" if complete else "partial_prefix",
                "gap_count": 0 if complete else 3,
                "observed_bar_count": 265 if complete else 262,
                "continuous_session_covered": complete,
            }
        }

    def refresher(_db, *, stock_id: str, **_kwargs):
        refreshed.append(stock_id)
        return reader(_db, stock_id=stock_id)

    common = {
        "session_factory": _FakeDb,
        "universe_resolver": lambda _db, **_kwargs: {
            "symbols": ["2330", "3711"]
        },
        "reader": reader,
        "refresher": refresher,
        "projector": _tail_projection,
        "attempt_registry": registry,
    }
    first = reconcile_taiwan_intraday_close_tails(
        now=datetime(2026, 8, 28, 13, 30, 5, tzinfo=TAIWAN_TZ),
        **common,
    )
    repeated = reconcile_taiwan_intraday_close_tails(
        now=datetime(2026, 8, 28, 13, 31, 0, tzinfo=TAIWAN_TZ),
        **common,
    )

    assert refreshed == ["3711"]
    assert [item["status"] for item in first["results"]] == [
        "already_complete",
        "partial",
    ]
    assert [item["status"] for item in repeated["results"]] == [
        "already_complete",
        "cooldown",
    ]
    assert repeated["cooldown_count"] == 1
    assert repeated["refresh_attempt_count"] == 0


def test_close_tail_reconciliation_skips_outside_window_without_opening_db() -> None:
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return _FakeDb()

    result = reconcile_taiwan_intraday_close_tails(
        now=datetime(2026, 8, 28, 13, 24, 59, tzinfo=TAIWAN_TZ),
        session_factory=session_factory,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "outside_taiwan_intraday_close_tail_window"
    assert opened is False


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
