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
    add_taiwan_intraday_bar_jobs,
    collect_taiwan_intraday_bars,
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
    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["id"] == "taiwan_intraday_bar_materialization"
    assert job["max_instances"] == 1
    assert job["coalesce"] is True


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
