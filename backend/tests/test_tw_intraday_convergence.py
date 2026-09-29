"""Factual day ranking and same-minute comparison boundaries, through persistence."""
from datetime import date, datetime, timedelta
import json

import pytest
from sqlalchemy import text

from app.ai import query_plan
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster, TaiwanIntradayStockState, TaiwanMarketMinuteState
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_state import (
    persist_taiwan_intraday_stock_states, build_tw_intraday_screening_snapshot,
    build_tw_intraday_group_snapshots,
)
from app.market.taiwan_market_state import (
    persist_taiwan_market_minute_state, read_taiwan_market_volume_state,
    compose_taiwan_market_volume_state,
)
from app.market.tw_market_dashboard import _project_hot_groups_for_dashboard
from app.market.tw_market_dashboard_schemas import TaiwanDashboardGroupRead
from test_taiwan_market_state import make_session, market_summary_payload
import test_tw_intraday_market_capabilities as fixtures

NOW = datetime(2026, 9, 22, 10, 21, 45, tzinfo=TAIWAN_TZ)


@pytest.fixture
def db():
    session = make_session()
    yield session
    session.close()
    session.bind.dispose()


def persist_stock(db, symbol, age):
    db.add(StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE", instrument_type="stock",
                       industry="半導體業", is_active=True))
    db.commit()
    event_at = NOW - timedelta(seconds=age)
    row = fixtures.TaiwanIntradayMarketCapabilityTests._stock_state_row(symbol, "TWSE", 110, 100, NOW)
    row.update(price_as_of=event_at, has_actual_trade=True, price_semantics="actual_trade")
    persist_taiwan_intraday_stock_states(db, rows=[row], now=NOW)
    return db.query(TaiwanIntradayStockState).filter_by(stock_id=symbol).one()


@pytest.mark.parametrize("age,freshness", [(30, "current"), (120, "delayed"), (601, "stale"), (3600, "stale")])
def test_production_actual_trade_is_factual_regardless_of_execution_age(db, age, freshness):
    state = persist_stock(db, "2330", age)
    assert state.price_semantics == "actual_trade" and state.lineage_complete
    assert state.decision_usable is (age <= 90)
    # Persisted rolling values and valid references cannot override latest-event freshness.
    state.samples_json = json.dumps([
        {"time": (NOW - timedelta(seconds=age, minutes=minutes)).isoformat(), "price": 100}
        for minutes in (5, 15)
    ])
    state.five_minute_return = state.fifteen_minute_return = 10
    db.commit()
    db.execute(text("PRAGMA query_only=ON"))
    ranking = build_tw_intraday_screening_snapshot(db, generated_at=NOW)
    row = ranking["rows"][0]
    assert row["facts_usable_for_ranking"] and row["value"] == pytest.approx(10)
    assert row["freshness_status"] == freshness
    assert row["last_trade_recency"] == freshness
    assert row["observation_received_freshness"] == "current"
    assert row["observation_age_seconds"] == age
    assert row["intraday_research_usable"] is (age <= 90)
    assert row["decision_usable"] is (age <= 90)
    assert row["execution_grade_usable"] is False
    if age > 90:
        assert row["five_minute_return"] is row["fifteen_minute_return"] is None
        assert row["five_minute_return_status"] == "stale"
    for metric in ("five_minute_return", "fifteen_minute_return", "estimated_trade_value", "distance_from_high_pct"):
        result = build_tw_intraday_screening_snapshot(db, generated_at=NOW, parameters={"metric": metric})
        assert bool(result["rows"]) is (age <= 90)
    for metric in ("vwap_deviation_pct", "order_book_imbalance"):
        assert not build_tw_intraday_screening_snapshot(db, generated_at=NOW, parameters={"metric": metric})["rows"]
    assert not db.dirty


def test_volume_identity_and_diagnostics_survive_v4_evidence_projection(db):
    from app.ai import decision_envelope_v4, capability_contract
    from test_tw_session_answers import market_response
    persist_volume(db, date(2026, 9, 21), "registered_universe", "tw.market.breadth.v2")
    persist_volume(db, NOW.date())
    state = read_taiwan_market_volume_state(db)
    response = decision_envelope_v4.build(market_response(["market.volume_state"], {"volume_state": state}))
    evidence = response["evidence"]["data"]["market.volume_state"]
    assert evidence["comparison_identity"] == state["comparison_identity"]
    assert evidence["baseline_diagnostics"] == state["baseline_diagnostics"]
    spec = next(spec for spec in capability_contract.CAPABILITY_SPECS if spec.capability_id == "market.volume_state")
    assert set(spec.default_fields) <= set(spec.fields)
    from app.market.schemas import TaiwanMarketVolumeStateRead
    http = TaiwanMarketVolumeStateRead.model_validate(state).model_dump(mode="json")
    assert http["comparison_identity"] == evidence["comparison_identity"]
    assert http["baseline_diagnostics"] == evidence["baseline_diagnostics"]
    assert http["same_time_baseline_5d"]["samples"] == evidence["same_time_baseline_5d"]["samples"]


@pytest.mark.parametrize("invalid", ["previous_session", "previous_price_date", "no_actual_trade", "indicative",
                                     "lineage", "reference", "inconsistent_change", "future"])
def test_factual_relaxation_does_not_relax_identity_or_value_guards(db, invalid):
    state = persist_stock(db, "2330", 30)
    if invalid == "previous_session":
        state.trade_date = NOW.date() - timedelta(days=1)
    elif invalid == "previous_price_date":
        state.price_as_of = NOW - timedelta(days=1)
    elif invalid == "no_actual_trade":
        state.has_actual_trade = False
    elif invalid == "indicative":
        state.price_semantics = "indicative_match"
    elif invalid == "lineage":
        state.lineage_complete = False
    elif invalid == "reference":
        state.previous_close = None
    elif invalid == "inconsistent_change":
        state.change_pct = 999
    else:
        state.price_as_of = NOW + timedelta(seconds=1)
    db.commit()
    assert not build_tw_intraday_screening_snapshot(db, generated_at=NOW)["rows"]
    assert not build_tw_intraday_group_snapshots(db, generated_at=NOW)["hot_groups"]["facts_usable_for_ranking"]


def test_group_factual_coverage_and_dashboard_quality_share_owner(db):
    for symbol, age in (("2330", 30), ("2454", 120), ("3711", 900)):
        persist_stock(db, symbol, age)
    db.execute(text("PRAGMA query_only=ON"))
    groups = build_tw_intraday_group_snapshots(db, generated_at=NOW)["hot_groups"]
    group = groups["groups"][0]
    assert group["facts_usable_for_ranking"] and group["observed_count"] == 3
    assert group["coverage_ratio"] == 1
    assert group["freshness_member_counts"] == {"current": 1, "delayed": 1, "stale": 1, "latest_completed_session": 0}
    assert group["lineage"]["oldest_event_time"] == NOW - timedelta(seconds=900)
    assert not group["intraday_research_usable"] and not group["decision_usable"]
    projected = TaiwanDashboardGroupRead.model_validate(_project_hot_groups_for_dashboard(groups, session_phase="regular")[0])
    assert projected.facts_usable_for_ranking
    assert projected.freshness_member_counts == group["freshness_member_counts"]
    assert not projected.decision_usable and not projected.execution_grade_usable


@pytest.mark.parametrize("symbol", ["2330", "2344"])
@pytest.mark.parametrize("alias", ["試搓", "試撮", "indicative auction"])
def test_automatic_optional_supplements_do_not_widen_pure_auction(symbol, alias):
    payload = AiAskRequest(question=f"{symbol} {alias} 多少？相對昨收漲跌多少？",
                           selection={"auto_planning": True, "optional": ["news.events"]})
    plan = query_plan.build_query_plan(payload=payload, scope_type="stock", target_market="TW",
                                       question_intent="quote", effective_mode="data_only")
    assert plan.reader_profile == "quote_only"
    assert "quote.auction" in plan.selected_capabilities
    assert "news.events" not in plan.optional_selected_capabilities
    assert payload.selection["optional"] == ["news.events"]


def test_explicit_optional_quote_supplement_remains_authoritative():
    payload = AiAskRequest(question="2330 試搓多少？",
                           selection={"required": ["quote.auction"], "optional": ["news.events"]})
    plan = query_plan.build_query_plan(payload=payload, scope_type="stock", target_market="TW",
                                       question_intent="quote", effective_mode="data_only")
    assert plan.reader_profile == "standard"
    assert "quote.auction" in plan.selected_capabilities
    assert "news.events" in plan.optional_selected_capabilities


def persist_volume(db, day, scope="full_market_registered_stock_universe", version="omi.market.breadth.v1"):
    payload = market_summary_payload(day, hour=10, minute=21, twse_trade_value=1000, tpex_trade_value=200)
    for item in payload["indices"]:
        item["breadth"].update(scope=scope, version=version, official_flag=False, source="twse_mis_live_breadth",
            trade_value_is_estimate=True, trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots")
    persist_taiwan_market_minute_state(db, payload=payload)
    return db.query(TaiwanMarketMinuteState).filter_by(trade_date=day).all()


def test_legacy_universe_equivalence_is_proved_by_producer_contract():
    from app.market.indices import _market_breadth_universe_definition
    from app.market.providers.twse_mis_current_breadth import _universe_definition
    for venue in ("TWSE", "TPEX"):
        assert _market_breadth_universe_definition("registered_universe", venue) == _universe_definition(venue)
        assert _market_breadth_universe_definition("full_market", venue) != _universe_definition(venue)


@pytest.mark.parametrize("history_days", [4, 5, 20])
def test_only_proven_legacy_scopes_join_5d_20d_baselines_without_writes(db, history_days):
    history = [date(2026, 8, 3) + timedelta(days=i) for i in range(45)]
    history = [day for day in history if day.weekday() < 5][:history_days]
    for day in history:
        persist_volume(db, day, "registered_universe", "tw.market.breadth.v2")
    persist_volume(db, NOW.date())
    db.commit()
    raw_before = [(row.id, row.breadth_scope, row.component_sources_json) for row in db.query(TaiwanMarketMinuteState)]
    db.execute(text("PRAGMA query_only=ON"))
    result = read_taiwan_market_volume_state(db)
    diagnostic = result["baseline_diagnostics"]
    assert diagnostic["usable_sample_count"] == history_days, diagnostic
    assert diagnostic["raw_scope_mismatch"] == history_days
    assert diagnostic["canonical_scope_mismatch"] == diagnostic["scope_mismatch"] == 0
    assert diagnostic["equivalent_scope_sample_count"] == history_days
    composed = compose_taiwan_market_volume_state(result, breadth=None)
    for days in (5, 20):
        baseline = composed[f"same_time_baseline_{days}d"]
        assert baseline["sample_days"] == min(days, history_days)
        assert [s["trade_date"] for s in baseline["samples"]] == [day.isoformat() for day in history[-days:]]
        assert baseline["decision_usable"] is (history_days >= days)
        assert baseline["pace_ratio"] == (1 if history_days >= days else None)
        assert baseline["comparison_identity"] == composed["comparison_identity"]
    assert raw_before == [(row.id, row.breadth_scope, row.component_sources_json) for row in db.query(TaiwanMarketMinuteState)]
    assert not db.dirty


@pytest.mark.parametrize("invalid,reason", [
    ("full_market", "canonical_scope_mismatch"), ("active_ordinary_stock_universe", "canonical_scope_mismatch"),
    ("semantics", "trade_value_semantic_mismatch"), ("authority", "authority_mismatch"),
    ("lineage", "unusable_value_or_lineage"), ("unverified_version", "canonical_scope_mismatch"),
    ("wrong_source", "canonical_scope_mismatch"),
])
def test_volume_comparison_rejects_non_equivalent_history_with_specific_diagnostics(db, invalid, reason):
    rows = persist_volume(db, date(2026, 9, 21))
    for row in rows:
        if invalid in {"full_market", "active_ordinary_stock_universe"}:
            row.breadth_scope = invalid
        elif invalid == "semantics":
            row.trade_value_semantics = "official_cumulative_trade_value"
        elif invalid == "authority":
            row.trade_value_is_estimate = False
        elif invalid == "lineage":
            row.lineage_complete = False
        elif invalid == "unverified_version":
            row.breadth_scope = "registered_universe"
            row.breadth_contract_version = "legacy_unverified"
        else:
            row.breadth_scope = "registered_universe"
            row.source = "unverified_source"
    db.commit()
    persist_volume(db, NOW.date())
    result = read_taiwan_market_volume_state(db)
    diagnostic = result["baseline_diagnostics"]
    assert diagnostic["usable_sample_count"] == 0
    assert diagnostic[reason] == 1
    assert reason in diagnostic["sessions"][0]["exclusion_reasons"]
    assert result["same_time_baseline_5d"]["pace_ratio"] is None
    assert not result["same_time_baseline_20d"]["decision_usable"]
