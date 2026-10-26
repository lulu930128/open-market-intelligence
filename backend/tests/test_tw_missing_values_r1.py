"""Deterministic regressions for TW-MISSING-VALUES-20261020-R1; no provider IO."""

from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, JobRun, TaiwanIntradayStockState
from app.jobs import taiwan_intraday_demand as demand
from app.market import tw_screening as screening
from app.market.providers.twse_mis_current_breadth import _build_payload
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states, _ranking_eligibility
from app.market.tw_market_breadth_contract import breadth_classification_reason
from test_tw_breadth_convergence import NOW, message
from test_tw_intraday_consumer_demand import env, reread_stub  # noqa: F401
import test_tw_screening as screening_fixture


@pytest.mark.parametrize("ts,volume,expected", [
    ("1", "0", "actual_trade_unavailable"),
    ("1", "5", "actual_trade_unavailable"),
    ("0", "0", "valid_no_trade"),
    ("0", "-", "unknown"),
    ("0", "5", "actual_trade_unavailable"),
])
def test_no_trade_requires_canonical_proof_through_persistence(ts, volume, expected):
    payload = _build_payload("TWSE", ["2330", "2454"], [
        message(z="-", tv="0", ts=ts, v=volume),
    ], 0)
    assert payload["coverage_reason_counts"][expected] == 1
    assert payload["classified_count"] == 0
    assert payload["unknown_count"] == 2
    assert sum(payload["coverage_reason_counts"].values()) == 2
    raw = dict(payload["component_stock_rows"][0])
    raw.update(raw_result_id="fixture", component_sources=[{
        "provider": "twse_mis", "source": "fixture", "raw_result_id": "fixture",
        "event_at": NOW.isoformat(), "received_at": NOW.isoformat(),
    }])
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TaiwanIntradayStockState.__table__])
    try:
        with Session(engine) as db:
            persist_taiwan_intraday_stock_states(db, rows=[raw], now=NOW)
            state = db.query(TaiwanIntradayStockState).one()
            result = _ranking_eligibility(db, state, generated=NOW)
            assert result["coverage_reason"] == expected
            assert result["breadth_usable"] is (expected == "valid_no_trade")
            assert result["decision_usable"] is False
            assert state.current_price is None
            if expected == "valid_no_trade":
                state.calculation_version = "tw.stock.intraday.state.derived.v3"
                assert _ranking_eligibility(db, state, generated=NOW)["coverage_reason"] == "unknown"
            if ts == "1" and volume == "0":
                # The same event clock can carry corrected trade-state proof.
                raw["actual_trade_reason_code"] = "ACTUAL_TRADE_EVIDENCE_MISSING"
                persisted = persist_taiwan_intraday_stock_states(db, rows=[raw], now=NOW)
                assert persisted["updated_count"] == 1
                assert _ranking_eligibility(db, state, generated=NOW)["coverage_reason"] == "valid_no_trade"
    finally:
        engine.dispose()


@pytest.mark.parametrize("reason", [
    None, "AUCTION_INDICATIVE_ONLY", "OBSERVATION_TRADE_DATE_MISMATCH",
    "PROVIDER_EVENT_TIME_MISSING", "OUTSIDE_ACTUAL_TRADE_WINDOW",
])
def test_zero_volume_without_no_trade_proof_never_becomes_verified(reason):
    classification, _ = breadth_classification_reason(dict(
        market_session="regular", has_actual_trade=False, previous_close=100,
        cumulative_volume_lots=0, actual_trade_reason_code=reason,
    ))
    assert classification != "valid_no_trade"


@pytest.mark.parametrize("window", [5, 20])
@pytest.mark.parametrize("values,expected_count,expected_sum", [
    ([10, None, 20, None, 30], 3, 60),
    ([0, 0, 0, 0, 0], 5, 0),
    ([None] * 5, 0, None),
])
def test_metric_valid_periods_not_row_count(monkeypatch, window, values, expected_count, expected_sum):
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(window)]
    expanded = values * (window // 5)
    rows = [SimpleNamespace(trade_date=day, id=i, foreign_investor_net=value)
            for i, (day, value) in enumerate(zip(days, expanded))]
    stock = SimpleNamespace(stock_id="2330", stock_name="fixture", market="TWSE", industry="", category="")
    monkeypatch.setattr(screening, "list_taiwan_stock_universe", lambda *a, **kw: [stock])
    monkeypatch.setattr(screening, "_latest_rows_by_stock_and_date", lambda *a, **kw: (days, {"2330": rows}))
    params = {"metric": "foreign_investor_net_shares", "window": window}
    result = screening.build_tw_screening_snapshot(None, parameters=params)
    complete = expected_count == 5
    assert result["coverage"]["complete_window_count"] == int(complete)
    assert result["ranking"]["pagination"]["total_ranked_count"] == int(complete)
    assert result["coverage"]["reconciliation"]["status"] == "balanced"
    partial = screening.build_tw_screening_snapshot(None, parameters={
        **params, "require_complete_window": False, "min_observed_periods": 1,
    })
    ranked = partial["ranking"]["rows"]
    if expected_sum is None:
        assert ranked == []
        assert result["coverage"]["reconciliation"]["observed_but_unusable"]["count"] == 1
    else:
        assert ranked[0]["value"] == expected_sum * (window // 5)
        assert ranked[0]["observed_periods"] == expected_count * (window // 5)
        assert ranked[0]["missing_value_days"] == [
            day.isoformat() for day, value in zip(days, expanded) if value is None
        ]


def test_latest_row_null_does_not_resurrect_old_value_and_margin_stays_endpoint_based():
    fixture = screening_fixture.TaiwanScreeningTests()
    fixture.setUp()
    try:
        latest = fixture.db.query(screening.InstitutionalTradeDaily).filter_by(
            stock_id="2330", trade_date=fixture.day_two,
            source_id=fixture.source_b.id,
        ).one()
        latest.foreign_investor_net = None
        fixture.db.commit()
        result = screening.build_tw_screening_snapshot(fixture.db, parameters={
            "metric": "foreign_investor_net_shares", "window": 5,
            "require_complete_window": False,
        })
        row = next(row for row in result["ranking"]["rows"] if row["stock_id"] == "2330")
        assert row["observed_periods"] == 4
        assert row["value"] == 100
        assert row["missing_value_days"] == [fixture.day_two.isoformat()]
        metric = next(metric for metric in screening.METRICS.values()
                      if metric.model is screening.MarginTradingDaily)
        margin = screening.build_tw_screening_snapshot(fixture.db, parameters={
            "metric": metric.metric_id, "window": 5,
        })
        assert len(margin["ranking"]["rows"]) == 2
        assert all(row["value"] == 21 and row["observed_periods"] == 5
                   for row in margin["ranking"]["rows"])
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("offset", [0, 8])
def test_dispatch_and_finish_persist_utc_without_resetting_handoff(env, monkeypatch, offset):
    utc = datetime(2026, 9, 16, 2, tzinfo=timezone.utc)
    requested = utc.astimezone(timezone(timedelta(hours=offset)))
    env.clock[0] = utc
    reread_stub(monkeypatch)
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id="2330",
                                               requested_at=requested, consumer="viewer")
        request_before = job.request_json
        assert job.started_at == utc.replace(tzinfo=None)
        assert job.updated_at == utc.replace(tzinfo=None)
        progress = json.loads(job.result_json)
        progress.update(attempt_count=1, external_call_budget_used=2,
                        external_call_count=1, next_retry_at=(utc + timedelta(seconds=15)).isoformat())
        job.result_json = json.dumps(progress)
        db.commit()
        demand._requeue_unstarted(db, job)
        assert demand.is_restart_handoff(job)
        assert not demand._dispatch(db, job, requested + timedelta(seconds=14))
        assert demand._dispatch(db, job, requested + timedelta(seconds=15))
        assert job.started_at == utc.replace(tzinfo=None)
        assert job.updated_at == (utc + timedelta(seconds=15)).replace(tzinfo=None)
        assert job.request_json == request_before
        after = json.loads(job.result_json)
        assert (after["attempt_count"], after["external_call_budget_used"]) == (1, 2)
        env.clock[0] = utc + timedelta(seconds=16)
        demand._finish(db, job, after, "FIXTURE_END")
        assert job.ended_at - job.started_at == timedelta(seconds=16)
        assert job.updated_at == job.ended_at


def test_dispatch_rejects_naive_clock_before_mutation(env):
    with env.factory() as db, pytest.raises(ValueError, match="timezone-aware"):
        demand._dispatch(db, JobRun(), datetime(2026, 9, 16, 10))
