"""Offline regressions for the Taiwan full-day outward contract findings."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.data_quality_contract import build_quality_contract
from app.ai.capability_contract import build_refresh_reconciliation
from app.ai.market_context import taiwan_stock, taiwan_market
from app.ai.query_plan import build_query_plan
from app.ai.schemas import AiAskRequest
from app.market import source_health
from app.market import tw_intraday_state
from app.db.models import Base, StockMaster
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_service import taiwan_requested_bar_scope
from app.market.tw_market_breadth_contract import resolve_twse_mis_breadth_price_state
from app.market.twse_mis_observation import resolve_twse_mis_actual_trade


def at(hour, minute=0, day=7):
    return datetime(2026, 9, day, hour, minute, tzinfo=TAIWAN_TZ)


@pytest.mark.parametrize("hour,minute,trial,price,volume", [
    (8, 59, "1", 143, 0), (9, 1, "0", 143, 1),
    (13, 26, "1", 143, 100), (13, 30, "0", 143, 100),
    (10, 0, "0", None, 100), (10, 0, "0", 143, 0),
    (10, 0, "0", float("inf"), 100), (10, 0, "0", float("nan"), 100),
    (10, 0, "0", True, 100),
])
def test_single_and_batch_use_same_actual_trade_predicate(hour, minute, trial, price, volume):
    event = at(hour, minute)
    single = resolve_twse_mis_actual_trade(
        expected_trade_date=event.date(), observation_trade_date=event.date(),
        provider_event_time=event, trial_status=trial, last_trade_price=price,
        last_trade_volume_lots=None, cumulative_volume_lots=volume,
    )
    batch = resolve_twse_mis_breadth_price_state(
        trade_date=event.date(), snapshot_as_of=event, last_trade_price=price,
        cumulative_volume_lots=volume, indicative_price=143,
        indicative_volume_lots=1, indicative_status=trial, cached_state=None,
    )
    assert batch["has_actual_trade"] == single["actual_trade_price_available"]
    assert batch["current_price"] == single["actual_trade_price"]


def test_trial_snapshot_keeps_previous_actual_trade_time_without_relabeling_it():
    result = resolve_twse_mis_breadth_price_state(
        trade_date=date(2026, 9, 7), snapshot_as_of=at(13, 26),
        last_trade_price=144, cumulative_volume_lots=100,
        indicative_price=144, indicative_volume_lots=1, indicative_status="1",
        cached_state={"trade_date": date(2026, 9, 7), "has_actual_trade": True,
                      "price": 143, "price_as_of": at(13, 24)},
    )
    assert result["current_price"] == 143
    assert result["price_as_of"] == at(13, 24)
    assert result["price_source"] == "session_cache"
    assert result["indicative_match_price"] == 144


def test_midpoint_is_not_a_generic_trade_price():
    quote = {"last_trade_available": False, "actual_trade_occurred": False,
             "best_bid_price": 141.5, "best_ask_price": 142.0}
    taiwan_stock._apply_taiwan_current_price_contract(
        quote=quote, intraday_bars={}, latest_daily=None, checked_at=at(8, 59),
        calendar_status={"date": "2026-09-07", "checked_at": at(8, 59),
                         "phase": "preopen", "is_trading_day": True},
    )
    assert quote["mid_price_estimate"] == 141.75
    assert all(quote[key] is None for key in ("price", "latest_price", "last_price"))
    assert quote["last_trade_available"] is False


@pytest.mark.parametrize("question,capability", [
    ("2330 五檔", "quote.order_book"), ("2330 委買委賣", "quote.order_book"),
    ("2330 order book depth", "quote.order_book"),
    ("2330 盤前試撮", "quote.auction"), ("2330 indicative auction", "quote.auction"),
])
def test_planner_selects_requested_quote_component(question, capability):
    plan = build_query_plan(payload=AiAskRequest(question=question, target={"type": "tw_stock", "id": "2330"}),
                            scope_type="stock", target_market="TW", question_intent="quote", effective_mode="brief")
    assert capability in plan.selection["required"]
    assert plan.reader_profile == "quote_only"


def test_quote_negation_preserves_technical_and_explicit_selection():
    for selection, expected_quote in [({}, False), ({"include": ["quote.snapshot"]}, True)]:
        plan = build_query_plan(payload=AiAskRequest(
            question="2330 不要盤中即時 quote，只看技術面", target={"type": "tw_stock", "id": "2330"}, selection=selection),
            scope_type="stock", target_market="TW", question_intent="quote", effective_mode="brief")
        assert ("quote.snapshot" in plan.selection["required"]) is expected_quote
        if not expected_quote:
            assert "technical.structure" in plan.selection["required"]


@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("require_live", [False, True])
def test_session_final_quality_does_not_confuse_reconciliation_with_availability(mismatch, require_live):
    payload = {"status": "session_final", "available": True, "price": 2460,
               "trade_date": "2026-09-07", "event_time": at(13, 30).isoformat(),
               "freshness": {"status": "current", "is_current": True},
               "facts_usable": True, "decision_usable": not mismatch,
               "research_usable": not mismatch,
               "limitations": ["SESSION_CLOSE_OFFICIAL_DAILY_MISMATCH" if mismatch else "OFFICIAL_DAILY_RECONCILIATION_PENDING"]}
    quality = build_quality_contract(
        canonical={"target": {"market": "TW"}, "evidence": {}, "summary": {}},
        selection={"output": "evidence_only"},
        manifest={"capabilities": [{"capability": "quote.session_close", "domain": "quote", "slot": "quote_session_close",
                                    "required": True, "status": "session_final", "returned_count": 1}]},
        projected_data={"quote.session_close": payload},
        realtime_assessments={"quote.session_close": {"policy": "require_live", "policy_satisfied": False}} if require_live else {},
        scope_type="stock",
    )["capabilities"]["quote.session_close"]
    assert quality["facts_usable"] is True
    assert quality["decision_usable"] is (not mismatch and not require_live)
    assert (quality["status_class"] == "blocked") is require_live
    assert payload["limitations"][0] in quality["issues"]


@pytest.mark.parametrize("requested", [None, date(2026, 9, 7)])
def test_explicit_today_matches_implicit_current_session(requested):
    scope, expected, bounds = taiwan_requested_bar_scope(requested, requested_at=at(10))
    assert scope.value == "current_session"
    assert expected == date(2026, 9, 7)
    assert "from_time" not in bounds


def test_exact_history_has_date_bounds_and_never_latest_fallback():
    scope, expected, bounds = taiwan_requested_bar_scope(date(2026, 9, 4), requested_at=at(10))
    assert scope.value == "history"
    assert expected == date(2026, 9, 4)
    assert bounds["from_time"].date() == bounds["to_time"].date() == expected
    reader = Mock(return_value=object())
    with patch.object(taiwan_stock, "project_taiwan_bar_series", return_value={"points": [], "trade_date": "2026-09-04"}):
        result = taiwan_stock._compact_intraday_bars(
            dependencies=SimpleNamespace(read_taiwan_bars=reader), db=object(), stock_id="2330", include_intraday=True,
            market_data_params={"trade_date": "2026-09-04"}, calendar_status={"checked_at": at(10)},
        )
    assert reader.call_args.kwargs["from_time"].date() == expected
    assert reader.call_args.kwargs["to_time"].date() == expected
    assert result["series"]["1m"]["points"] == []


def test_source_health_dataset_filter_skips_other_builders():
    entry = SimpleNamespace(resource="market_breadth", to_dict=lambda: {"resource": "market_breadth"})
    with patch.object(source_health, "build_taiwan_calendar_status", return_value={}), \
         patch.object(source_health, "_market_breadth_entries", return_value=[entry]) as selected, \
         patch.object(source_health, "_dataset_entry", side_effect=AssertionError("unselected dataset")), \
         patch.object(source_health, "_stock_master_entry", side_effect=AssertionError("unselected stock master")), \
         patch.object(source_health, "enrich_source_health_entries", side_effect=lambda db, **kw: kw["entries"]), \
         patch.object(source_health, "_summary", return_value={}), \
         patch.object(source_health, "summarize_status_dimensions", return_value={}):
        result = source_health.build_taiwan_source_health(object(), dataset="market_breadth", now=at(14), limit=10)
    selected.assert_called_once()
    assert result["returned_count"] == 1
    assert result["truncated"] is False


@pytest.mark.parametrize("limit", [0, 501, True, 1.5, "10"])
def test_invalid_health_limit_fails_before_database_access(limit):
    with pytest.raises(ValueError, match="limit"):
        source_health.build_taiwan_source_health(object(), stock_id="2330", limit=limit)


def test_source_health_build_limit_stops_work_and_marks_partial():
    entry = SimpleNamespace(to_dict=lambda: {"resource": "stock_master"})
    with patch.object(source_health, "build_taiwan_calendar_status", return_value={}), \
         patch.object(source_health, "_stock_master_entry", return_value=entry), \
         patch.object(source_health, "_dataset_entry", side_effect=AssertionError("over budget")), \
         patch.object(source_health, "enrich_source_health_entries", side_effect=lambda db, **kw: kw["entries"]), \
         patch.object(source_health, "_summary", return_value={}), \
         patch.object(source_health, "summarize_status_dimensions", return_value={}):
        result = source_health.build_taiwan_source_health(object(), now=at(14), limit=1)
    assert result["returned_count"] == 1
    assert result["truncated"] and result["is_partial"]
    assert result["status"] == "partial"


def test_market_health_only_does_not_build_breadth_or_daily_market_universe():
    health = Mock(return_value={"status": "partial", "entries": [{"resource": "market_breadth"}],
                                "returned_count": 1, "truncated": True, "is_partial": True})
    dependencies = SimpleNamespace(now=lambda: at(14), build_taiwan_source_health=health)
    # No market_service or index reader is provided: using either must fail.
    result = taiwan_market.read_market_overview(
        object(), dependencies=dependencies,
        market_data_params={"requested_domains": ["source_health"],
                            "requested_capabilities": ["diagnostics.source_health", "data.freshness"],
                            "capability_limits": {"diagnostics.source_health": 1}},
    )
    assert health.call_args.kwargs["limit"] == 1
    assert result["data"]["compact"]["source_health"]["entries"] == [{"resource": "market_breadth"}]
    assert result["data"]["compact"]["source_health"]["truncated"] is True


def test_reader_provider_io_is_reported_without_fabricating_a_tool_run():
    result = build_refresh_reconciliation(
        selection={"required": ["quote.snapshot"]},
        manifest={"capabilities": [{"capability": "quote.snapshot", "payload_included": True, "status_class": "ready"}]},
        fill_plan={}, tool_runs=[], scope_type="stock",
        primary_reader_provider_attempts={"quote.snapshot": [{"provider": "twse_mis", "status": "selected"}]},
    )
    assert result["provider_fetch_attempted"] is True
    assert result["primary_reader_attempted"] is True
    assert result["tool_run_attempted"] is False
    assert result["not_attempted_reason"] is None
    assert result["capabilities"]["quote.snapshot"]["not_attempted_reason"] is None


@pytest.mark.parametrize("available,close_price,close_date,expected_final", [
    (True, 143, date(2026, 9, 7), True),
    (False, None, date(2026, 9, 7), False),
    (True, 144, date(2026, 9, 7), False),
    (True, 143, date(2026, 9, 4), False),
])
def test_screening_uses_canonical_session_close_and_preserves_observation_phase(
    available, close_price, close_date, expected_final,
):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(StockMaster(stock_id="2303", stock_name="UMC", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
        event = at(13, 30)
        tw_intraday_state.persist_taiwan_intraday_stock_states(db, rows=[{
            "code": "2303", "market": "TWSE", "trade_date": event.date(), "as_of": event,
            "current_price": 143, "previous_close": 130, "open_price": 130, "high_price": 143, "low_price": 130,
            "cumulative_volume_lots": 100, "estimated_trade_value": 14300000,
            "provider": "twse_mis", "source": "twse_mis_twse_registered_universe",
            "raw_result_id": "raw_fetch_result:2303", "component_raw_result_ids": ["raw_fetch_result:2303"],
            "component_sources": [{"provider": "twse_mis", "source": "twse_mis_twse_registered_universe",
                                   "raw_result_id": "raw_fetch_result:2303", "event_at": event.isoformat()}],
        }], now=event)
        with patch.object(tw_intraday_state, "read_taiwan_session_close", return_value=object()) as reader, \
             patch.object(tw_intraday_state, "project_taiwan_session_close", return_value={
                 "available": available, "status": "session_final" if available else "unavailable",
                 "price": close_price, "trade_date": close_date, "event_time": event,
             }):
            result = tw_intraday_state.build_tw_intraday_screening_snapshot(
                db, parameters={"metric": "change_pct", "limit": 1}, generated_at=at(14),
            )
        row = result["rows"][0]
        reader.assert_called_once()
        assert row["current_price"] == 143
        assert row["session_phase"] == "closing_auction"
        assert row["request_session_phase"] == "post_close"
        assert (row["freshness_status"] == "latest_completed_session") is expected_final
        assert row["decision_usable"] is expected_final
    engine.dispose()
