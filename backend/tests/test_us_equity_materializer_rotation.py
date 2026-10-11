"""G1 synthetic clock/store tests: no production database or provider IO."""

from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db.models import PortfolioHolding, USWatchlistItem
from app.jobs import us_intraday_materializer_scheduler as scheduler
from app.us_market import intraday_materializer as materializer


NOW = datetime(2026, 9, 3, 14, tzinfo=timezone.utc)


@pytest.fixture
def rig(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    PortfolioHolding.__table__.create(engine)
    USWatchlistItem.__table__.create(engine)
    clock = [0.0]
    viewers = []
    calls = []
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scheduler, "_EQUITY_ROTATION", scheduler._EquityRotation(not_before=0))
    monkeypatch.setattr(scheduler, "_EQUITY_SELECTION_LOCK", Lock())
    monkeypatch.setattr(scheduler, "_SCHEDULED_US_ACTIVE_LANE_LOCK", Lock())
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(scheduler, "active_us_equity_viewer_symbols", lambda **_: tuple(viewers))
    monkeypatch.setattr(scheduler, "_schedule_intraday_consumer_read_model", lambda _: True)
    monkeypatch.setattr(settings, "enable_us_dynamic_equity_materializer_universe", True)
    for name, value in {
        "scheduler_us_active_equity_materializer_symbols": "",
        "scheduler_us_intraday_materializer_symbols": "",
        "scheduler_us_active_equity_materializer_max_symbols": 2,
        "scheduler_us_intraday_materializer_max_symbols": 2,
        "scheduler_us_active_equity_materializer_max_external_calls": 4,
        "scheduler_us_intraday_materializer_max_external_calls": 4,
    }.items():
        monkeypatch.setattr(settings, name, value)

    class FakeDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakePlatform:
        def read_quote(self, **kwargs):
            raise LookupError("synthetic cache miss")

        read_intraday_bars = read_quote

        def refresh_quote(self, **kwargs):
            return self.refresh("quote.snapshot", kwargs)

        def refresh_intraday_bars(self, **kwargs):
            return self.refresh("intraday.bars", kwargs)

        def refresh(self, capability, kwargs):
            calls.append((clock[0], capability, kwargs["symbol"], kwargs["max_provider_calls"]))
            return SimpleNamespace(
                postcondition_satisfied=True, postcondition_reasons=(),
                result=SimpleNamespace(
                    acquisition=SimpleNamespace(attempted=True, external_calls=1),
                    persistence=SimpleNamespace(committed=True),
                    resolved=SimpleNamespace(health=SimpleNamespace(
                        status=SimpleNamespace(value="selected"), selected_provider="fake",
                        fallback_used=False, facts_usable=True, limitations=(),
                    )),
                ),
            )

    platform = FakePlatform()
    real_materialize = materializer.materialize_us_intraday_capability

    def isolated_materialize(*args, **kwargs):
        return real_materialize(*args, **kwargs, session_factory=FakeDb,
                                platform_factory=lambda _: platform)

    monkeypatch.setattr(scheduler, "materialize_us_intraday_capability", isolated_materialize)

    def holding(symbol, *, market="US", active=True, quantity=1):
        with Session(engine) as db:
            db.add(PortfolioHolding(symbol=symbol, market=market, is_active=active,
                                    quantity=quantity, currency="USD"))
            db.commit()

    def watch(symbol, *, enabled=True, priority=100, group=1):
        with Session(engine) as db:
            db.add(USWatchlistItem(symbol=symbol, enabled=enabled, priority=priority, group_id=group))
            db.commit()

    def cycle(tick):
        clock[0] = tick
        quote = scheduler.collect_us_active_quote_snapshots(now=NOW)
        bars = scheduler.collect_us_active_intraday_bars(now=NOW)
        return quote, bars

    yield SimpleNamespace(clock=clock, viewers=viewers, calls=calls, holding=holding,
                          watch=watch, cycle=cycle, platform=platform)
    engine.dispose()


def test_fixed_window_shares_targets_at_0_35_and_rotates_at_60(rig):
    rig.viewers.extend(["SSO", "AMD", "AAPL"])
    rig.holding("MSFT")
    first = scheduler.collect_us_active_quote_snapshots(now=NOW)
    assert first["selection"]["symbols"] == ["AAPL", "MSFT"]
    rig.clock[0] = 35
    bars = scheduler.collect_us_intraday_bars(now=NOW + timedelta(seconds=35))
    assert bars["selection"]["symbols"] == first["selection"]["symbols"]
    assert scheduler._EQUITY_ROTATION.not_before == 60
    rig.clock[0] = 60
    second = scheduler.collect_us_quote_snapshots(now=NOW + timedelta(seconds=60))
    assert second["selection"]["symbols"] == ["AMD", "MSFT"]
    assert first["selection"]["window_reserved_external_calls"] == 4
    assert second["selection"]["window_reserved_external_calls"] == 4


def test_three_viewers_rotate_with_overlapping_holdings_watchlist_and_canary(rig, monkeypatch):
    rig.viewers.extend(["SSO", "AMD", "AAPL"])
    for symbol in ["AAPL", "AMD", "MSFT"]:
        rig.holding(symbol)
    for symbol in ["AAPL", "SSO", "MSFT", "TSM", "NVDA"]:
        rig.watch(symbol)
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "AAPL,TSM")
    viewers = []
    seen = set()
    for index in range(12):
        # Heartbeat ordering must not cause the first viewer to monopolize slots.
        rig.viewers.reverse()
        quote, bars = rig.cycle(index * 60)
        selection = quote["selection"]
        viewers.append(selection["symbols"][0])
        seen.update(selection["symbols"])
        assert selection["sources"][0] == "active_viewer"
        assert bars["selection"]["symbols"] == selection["symbols"]
        assert len(set(selection["symbols"])) == 2
        assert selection["eligible_counts"] == {
            "active_viewer": 3, "portfolio": 1, "watchlist": 2, "canary": 2,
        }
    assert viewers[:6] == ["AAPL", "AMD", "SSO"] * 2
    assert seen == {"AAPL", "AMD", "SSO", "MSFT", "TSM", "NVDA"}
    assert len(rig.calls) == 12 * 4


def test_canary_probe_keeps_fair_turn_when_also_low_priority_watchlist(rig, monkeypatch):
    rig.viewers.append("SSO")
    rig.holding("MSFT")
    for index in range(376):
        rig.watch(f"W{index:03}")
    rig.watch("TSM", priority=999)
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "TSM")
    results = [rig.cycle(index * 60)[0] for index in range(4)]
    assert [result["selection"]["symbols"][1] for result in results] == [
        "MSFT", "MSFT", "W000", "TSM",
    ]
    assert results[-1]["selection"]["sources"] == ["active_viewer", "watchlist"]
    assert results[-1]["selection"]["canary_probe_symbols"] == ["TSM"]


def test_376_watch_symbols_eventually_selected_with_saturated_viewers(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD", "SSO"])
    rig.holding("MSFT")
    for index in range(376):
        rig.watch(f"W{index:03}")
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "TSM")
    seen = set()
    # Pure batch loop isolates scheduler fairness from IO and market-window time.
    sources = scheduler._equity_source_symbols(now=NOW)
    state = scheduler._EquityRotation(not_before=0)
    for _ in range(4 * 376):
        symbols, owners = scheduler._select_equity_batch(state, sources, 2)
        assert owners[0] == "active_viewer"
        assert len(set(symbols)) == 2
        seen.update(symbols)
    assert set(sources["watchlist"]) <= seen
    assert set(sources["active_viewer"]) <= seen
    assert len(state.cursors) <= 4
    assert len(state.symbols) == 0  # no accumulated work queue


def test_shared_budget_dedupes_all_four_job_triggers_and_runtime_reports_deferrals(rig):
    rig.viewers.extend(["AAPL", "AMD", "SSO"])
    rig.holding("MSFT")
    first = scheduler.collect_us_quote_snapshots(now=NOW)
    assert scheduler.collect_us_active_quote_snapshots(now=NOW)["status"] == "skipped"
    scheduler.collect_us_intraday_bars(now=NOW)
    assert scheduler.collect_us_active_intraday_bars(now=NOW)["status"] == "skipped"
    assert len(rig.calls) == 4
    assert {call[2] for call in rig.calls} == {"AAPL", "MSFT"}
    assert all(call[3] == 1 for call in rig.calls)
    summary = materializer.us_intraday_materializer_runtime_summary()
    selection = summary["runs_by_lane"]["equity_active"]["quote.snapshot"]["selection"]
    assert selection == first["selection"]
    assert selection["capacity"] == 2
    assert selection["deferred_counts"]["active_viewer"] == 2
    assert selection["count_semantics"] == "exclusive_priority_owner_except_overlapping_canary_role"
    assert selection["deferred_reason"] == "bounded_priority_round_robin_capacity"


def test_eligibility_filters_in_memory_rows_and_rejects_malformed_symbols(rig, monkeypatch):
    rig.viewers.extend([" aapl ", "AAPL", "^GSPC", "broken symbol"])
    rig.holding("MSFT")
    rig.holding("ZERO", quantity=0)
    rig.holding("INFINITE", quantity=float("inf"))
    rig.holding("INACTIVE", active=False)
    rig.holding("TWONLY", market="TW")
    rig.holding("SHORT", quantity=-1)
    rig.watch("MSFT")
    rig.watch("DISABLED", enabled=False)
    rig.watch("TSM", group=1)
    rig.watch("TSM", group=2)
    rig.watch("AAPL garbage")
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "AAPL,TSM,?bad,SPX")
    assert scheduler._equity_source_symbols(now=NOW) == {
        "active_viewer": ("AAPL",), "portfolio": ("MSFT", "SHORT"),
        "watchlist": ("TSM",), "canary": ("AAPL", "TSM"),
    }


@pytest.mark.parametrize("closed", [
    datetime(2026, 9, 6, 14, tzinfo=timezone.utc),  # Sunday
    datetime(2026, 9, 4, 1, tzinfo=timezone.utc),   # NY21:00
])
def test_closed_market_does_not_even_open_source_store(rig, monkeypatch, closed):
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: pytest.fail("closed market DB read"))
    assert scheduler.collect_us_quote_snapshots(now=closed)["reason"] == "outside_us_intraday_acquisition_window"
    assert rig.calls == []
    assert scheduler._EQUITY_ROTATION.cursors == {}


@pytest.mark.parametrize("lock_name", ["_EQUITY_SELECTION_LOCK", "_SCHEDULED_US_ACTIVE_LANE_LOCK"])
def test_lock_skip_does_not_advance_or_reserve(rig, lock_name):
    rig.viewers.append("AAPL")
    lock = getattr(scheduler, lock_name)
    with lock:
        assert scheduler.collect_us_quote_snapshots(now=NOW)["reason"] == "materializer_run_in_flight"
    assert scheduler._EQUITY_ROTATION.cursors == {}
    assert scheduler._EQUITY_ROTATION.reservations == 0
    assert rig.calls == []
    assert rig.cycle(0)[0]["status"] == "success"


def test_one_symbol_cap_alternates_viewer_and_background_without_budget_growth(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD", "SSO"])
    rig.holding("MSFT")
    rig.watch("TSM")
    monkeypatch.setattr(settings, "scheduler_us_active_equity_materializer_max_symbols", 1)
    results = [rig.cycle(index * 60)[0] for index in range(8)]
    assert [r["selection"]["symbols"][0] for r in results[:6]] == [
        "AAPL", "MSFT", "AMD", "MSFT", "SSO", "TSM",
    ]
    assert all(r["selection"]["window_reserved_external_calls"] == 2 for r in results)
    assert len(rig.calls) == 16


def test_external_call_config_can_reduce_capacity(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD"])
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_max_external_calls", 1)
    quote, bars = rig.cycle(0)
    assert quote["selection"]["capacity"] == 1
    assert bars["external_call_count"] == 1
    assert len(rig.calls) == 2


def test_unknown_provider_failure_does_not_refund_reservations(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD"])

    def fail(capability, kwargs):
        rig.calls.append((rig.clock[0], capability, kwargs["symbol"], kwargs["max_provider_calls"]))
        raise RuntimeError("synthetic unknown accounting")

    monkeypatch.setattr(rig.platform, "refresh", fail)
    quote, bars = rig.cycle(0)
    assert quote["status"] == bars["status"] == "failed"
    assert scheduler._EQUITY_ROTATION.reservations == 4
    rig.cycle(35)
    assert len(rig.calls) == 4


def test_in_flight_fetch_blocks_other_equity_trigger_without_new_reservation(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD"])
    refresh = rig.platform.refresh
    nested = []

    def during_refresh(capability, kwargs):
        nested.append(scheduler.collect_us_intraday_bars(now=NOW))
        return refresh(capability, kwargs)

    monkeypatch.setattr(rig.platform, "refresh", during_refresh)
    result = scheduler.collect_us_quote_snapshots(now=NOW)
    assert result["status"] == "success"
    assert all(r["reason"] == "materializer_run_in_flight" for r in nested)
    assert len(rig.calls) == 2
    assert scheduler._EQUITY_ROTATION.reservations == 4
    assert scheduler._EQUITY_ROTATION.consumed == {"quote.snapshot"}


def test_overlapping_primary_roles_are_not_reported_as_deferred(rig):
    rig.viewers.append("AAPL")
    rig.holding("AAPL")
    rig.watch("AAPL")
    selection = rig.cycle(0)[0]["selection"]
    assert selection["sources"] == ["active_viewer"]
    assert selection["eligible_counts"]["portfolio"] == 0
    assert selection["eligible_counts"]["watchlist"] == 0
    assert not any(selection["deferred_counts"].values())


def test_missing_capability_does_not_stall_next_window_and_restart_is_tolerated(rig, monkeypatch):
    rig.viewers.extend(["AAPL", "AMD", "SSO"])
    scheduler._EQUITY_ROTATION.cursors["active_viewer"] = 10**9
    first = scheduler.collect_us_quote_snapshots(now=NOW)
    rig.clock[0] = 61
    second = scheduler.collect_us_quote_snapshots(now=NOW)
    assert second["selection"]["symbols"] != first["selection"]["symbols"]
    assert first["selection"]["window_reserved_external_calls"] == 4
    assert second["selection"]["window_reserved_external_calls"] == 4
    bars = scheduler.collect_us_intraday_bars(now=NOW)
    assert bars["selection"]["symbols"] == second["selection"]["symbols"]
    # A process restart drops cursors but waits 60 seconds before new reservations.
    monkeypatch.setattr(scheduler, "_EQUITY_ROTATION", scheduler._EquityRotation())
    assert scheduler.collect_us_quote_snapshots(now=NOW)["status"] == "skipped"
    rig.clock[0] = 121
    assert scheduler.collect_us_quote_snapshots(now=NOW)["selection"]["symbols"][0] == "AAPL"


def test_dynamic_acquisition_default_off_and_legacy_path_does_not_read_holdings(rig, monkeypatch):
    assert Settings(_env_file=None).enable_us_dynamic_equity_materializer_universe is False
    monkeypatch.setattr(settings, "enable_us_dynamic_equity_materializer_universe", False)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: pytest.fail("opt-out source DB read"))
    rig.viewers.append("SSO")
    result = scheduler.collect_us_active_quote_snapshots(now=NOW)
    assert "selection" not in result
    assert result["universe"]["symbols"] == ["SSO"]


@pytest.mark.parametrize("capacity", [1, 2])
@pytest.mark.parametrize("phase", range(5))
def test_explicit_amd_has_bounded_admission_with_large_watchlist(rig, monkeypatch, capacity, phase):
    rig.viewers.append("AAPL")
    rig.holding("MSFT")
    for index in range(374):
        rig.watch(f"W{index:03}")
    monkeypatch.setattr(settings, "scheduler_us_active_equity_materializer_symbols", "AMD")
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "TSM")
    monkeypatch.setattr(settings, "scheduler_us_active_equity_materializer_max_symbols", capacity)
    scheduler._EQUITY_ROTATION.background_turn = phase
    first_admission = None
    for window in range(10):
        quote, bars = rig.cycle(window * 60)
        selected = quote["selection"]["symbols"]
        if "AMD" in selected and first_admission is None:
            first_admission = window + 1
        assert selected == bars["selection"]["symbols"]
        assert len(selected) == len(set(selected)) == capacity
        assert quote["selection"]["window_reserved_external_calls"] == capacity * 2 <= 4
        assert scheduler.collect_us_quote_snapshots(now=NOW)["status"] == "skipped"
        assert scheduler.collect_us_intraday_bars(now=NOW)["status"] == "skipped"
        assert len([call for call in rig.calls if call[0] == window * 60]) == capacity * 2
    # Capacity 1 alternates viewer/background, so an arbitrary phase doubles
    # the five-turn bound. A fresh explicit tier (phase 0) enters window 2.
    assert first_admission <= (5 if capacity == 2 else 10)
    if phase == 0:
        assert first_admission <= 6


@pytest.mark.parametrize("capacity", [1, 2])
def test_multiple_explicit_symbols_and_every_other_tier_remain_bounded(rig, monkeypatch, capacity):
    rig.viewers.extend(["AAPL", "SSO"])
    rig.holding("MSFT")
    rig.holding("AMD")
    rig.watch("AMD")
    for index in range(374):
        rig.watch(f"W{index:03}")
    monkeypatch.setattr(settings, "scheduler_us_active_equity_materializer_symbols", "amd,NVDA,AMD,?bad,SPX,broken token")
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "AMD,TSM")
    sources = scheduler._equity_source_symbols(now=NOW)
    assert sources["explicit"] == ("AMD", "NVDA")
    assert sources["portfolio"] == ("MSFT",)
    assert "AMD" not in sources["watchlist"]
    assert sources["canary"] == ("AMD", "TSM")
    state = scheduler._EquityRotation(not_before=0)
    seen = set()
    factor = 2 if capacity == 1 else 1
    for window in range(5 * 374 * factor):
        selected, owners = scheduler._select_equity_batch(state, sources, capacity)
        assert len(selected) == len(set(selected)) == capacity
        seen.update(selected)
        if window == 5 * 2 * factor - 1:
            assert set(sources["explicit"]) <= seen
            assert set(sources["canary"]) <= seen
            assert set(sources["portfolio"]) <= seen
            assert set(sources["active_viewer"]) <= seen
    assert set(sources["watchlist"]) <= seen
    assert len(state.cursors) <= 5


def test_explicit_canary_overlap_preserves_primary_owner_and_probe(rig, monkeypatch):
    rig.viewers.append("AAPL")
    monkeypatch.setattr(settings, "scheduler_us_active_equity_materializer_symbols", "AMD,AAPL")
    monkeypatch.setattr(settings, "scheduler_us_intraday_materializer_symbols", "AMD")
    result = rig.cycle(0)[0]["selection"]
    assert result["symbols"] == ["AAPL", "AMD"]
    assert result["sources"] == ["active_viewer", "explicit"]
    assert result["canary_probe_symbols"] == ["AMD"]
    assert result["eligible_counts"]["explicit"] == 1
    assert not any(result["deferred_counts"].values())
