from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

import app.market.tw_swing_prefilter as prefilter
import app.market.tw_swing_screening as detailed
from app.market.daily_price_repository import TaiwanOfficialDailyUniverseRead
from app.market.tw_swing_prefilter import (
    SwingDiscoveryCheckpoint, SwingDiscoveryRequest, build_tw_swing_discovery_snapshot,
)
from app.market.tw_swing_screening import SwingReason, screen_tw_swing_candidates
from app.market_data.contracts import BarFinalization
from app.market.tw_technical_service import TaiwanTechnicalService
from test_tw_swing_screening import CUTOFF, REQUESTED_AT, _evidence


def _request(**changes):
    return SwingDiscoveryRequest(as_of_trade_date=CUTOFF, requested_at=REQUESTED_AT,
        batch_size=2, top_n=2, detail_batch_size=1, **changes)


@pytest.fixture
def inputs():
    return {symbol: _evidence(symbol, falling=symbol in {"6147", "6770"}, last_close=200 if symbol == "2331" else None)
            for symbol in ("2330", "2331", "2332", "6147", "6770", "9999")}


def _install(monkeypatch, inputs):
    calls = {"canonical": [], "detail": [], "external": "fixed-corporate-calendar"}
    stocks = [SimpleNamespace(stock_id=key, market=value.market) for key, value in inputs.items()]
    monkeypatch.setattr(prefilter, "list_taiwan_stock_universe", lambda db, **kw: stocks)
    monkeypatch.setattr(prefilter, "snapshot_storage_available", lambda db: False)
    monkeypatch.setattr(prefilter, "read_price_map_external_revision", lambda: calls["external"])
    monkeypatch.setattr(prefilter, "get_technical_analysis_parameters", lambda: SimpleNamespace(revision="fixed-params"))

    class Repository:
        def __init__(self, db, *, available_at):
            assert available_at == REQUESTED_AT

        def load_market_universe_history(self, **kwargs):
            calls["canonical"].append(kwargs)
            assert kwargs["include_etf"] is False and len(kwargs["symbols"]) <= 100
            return {day: TaiwanOfficialDailyUniverseRead(trade_date=day, bars=tuple(
                bar for symbol in kwargs["symbols"] for bar in inputs[symbol].bars.bars
                if bar.start_at.date() == day)) for day in kwargs["trade_dates"]}

    def detail(db, *, request):
        calls["detail"].append(request)
        return screen_tw_swing_candidates(request, tuple(inputs[symbol] for symbol in request.stock_ids))

    monkeypatch.setattr(prefilter, "TaiwanOfficialDailyBarRepository", Repository)
    monkeypatch.setattr(prefilter, "build_tw_swing_screening_snapshot", detail)
    # A cheap-stage institutional or technical calculation is a regression.
    monkeypatch.setattr(detailed, "_read_institutional", lambda *a, **kw: pytest.fail("N+1 institutional query in prefilter"))
    monkeypatch.setattr(TaiwanTechnicalService, "calculate", lambda *a, **kw: pytest.fail("technical calculation in prefilter"))
    return calls, stocks


@pytest.mark.parametrize("horizon", [10, 15])
def test_resumable_full_universe_then_batched_top_n_detail(monkeypatch, inputs, horizon):
    calls, _ = _install(monkeypatch, inputs)
    request = _request(horizon_sessions=horizon)
    first = build_tw_swing_discovery_snapshot(object(), request=request)
    assert first.status == "in_progress" and first.coverage.considered == 2 and first.coverage.pending == 4
    assert first.coverage.sample_only and first.coverage.full_market_scope and not first.coverage.is_full_market
    assert not calls["detail"]
    checkpoint = SwingDiscoveryCheckpoint.model_validate_json(first.checkpoint.model_dump_json())
    second = build_tw_swing_discovery_snapshot(object(), request=request, checkpoint=checkpoint)
    third = build_tw_swing_discovery_snapshot(object(), request=request, checkpoint=second.checkpoint)
    assert third.coverage.all_considered and third.coverage.is_full_market and not third.coverage.sample_only
    assert third.coverage.considered == 6 and third.coverage.pending == 0
    assert not third.coverage.quality_complete and third.coverage.quality_status == "partial"
    assert third.coverage.detail_considered == 1 and third.coverage.detail_pending == 1
    assert third.status == "in_progress"
    canonical_calls = len(calls["canonical"])
    final = build_tw_swing_discovery_snapshot(object(), request=request, checkpoint=third.checkpoint)
    assert len(calls["canonical"]) == canonical_calls == 3
    assert final.status == "limited" and final.coverage.detail_considered == 2 and final.coverage.detail_pending == 0
    assert tuple(symbol for call in calls["detail"] for symbol in call.stock_ids) == final.top_stock_ids
    assert all(len(call.stock_ids) == 1 and call.horizon_sessions == horizon for call in calls["detail"])
    assert all(len(call["trade_dates"]) == horizon and max(call["trade_dates"]) == CUTOFF for call in calls["canonical"])
    assert all(row.institutional_policy == "deferred_to_top_n_detail" and row.institutional.foreign_net_shares is None for row in final.checkpoint.rows)
    assert all(SwingReason.INSTITUTIONAL_UNKNOWN in row.reason_codes for row in final.checkpoint.rows)
    assert final.coverage.institutional_unknown == 6 and not final.empty_result_is_valid
    assert SwingReason.INSTITUTIONAL_UNKNOWN.value not in final.coverage.excluded_reason_counts
    assert final.coverage.deferred_reason_counts == {"INSTITUTIONAL_UNKNOWN": 6}
    assert final.coverage.prefilter_selected == 2 and final.coverage.detail_sample_only
    assert final.coverage.detail_qualified == sum(batch.coverage.qualified for batch in final.detail_batches)
    assert final.coverage.detail_research_qualified_candidates == sum(
        candidate.stage == "research_qualified" for batch in final.detail_batches for candidate in batch.candidates)
    # A single-shot batch and a resumed scan produce the same pinned evidence
    # and Top-N, independently of the cheap/detail work budget.
    one_shot = build_tw_swing_discovery_snapshot(object(), request=request.model_copy(update={"batch_size": 6, "max_detail_batches": 2}))
    assert one_shot.top_stock_ids == final.top_stock_ids
    assert one_shot.snapshot_id == final.snapshot_id


def test_unknown_missing_history_provisional_and_cap_reconcile(monkeypatch, inputs):
    missing = inputs["9999"]
    inputs["9999"] = missing.model_copy(update={"bars": missing.bars.model_copy(update={"bars": ()})})
    partial = inputs["2332"]
    inputs["2332"] = partial.model_copy(update={"bars": partial.bars.model_copy(update={"bars": (*partial.bars.bars[:-4], *partial.bars.bars[-3:])})})
    provisional = inputs["2330"]
    last = provisional.bars.bars[-1].model_copy(update={"close_price": Decimal(999), "finalization": BarFinalization.PROVISIONAL})
    inputs["2330"] = provisional.model_copy(update={"bars": provisional.bars.model_copy(update={"bars": (*provisional.bars.bars[:-1], last)})})
    _install(monkeypatch, inputs)
    result = build_tw_swing_discovery_snapshot(object(), request=_request(direction="short").model_copy(update={"batch_size": 6}), with_detail=False)
    rows = {row.stock_id: row for row in result.checkpoint.rows}
    assert rows["9999"].status == "unknown" and rows["9999"].window_return_pct is None
    assert rows["2332"].status == "limited" and not rows["2332"].daily_usable
    assert rows["2330"].window_return_pct is None and SwingReason.DAILY_NOT_COMPLETED in rows["2330"].reason_codes
    assert rows["2331"].reference_close == 200 and not rows["2331"].allowed_directions
    assert rows["2331"].excluded_directions == {"short": (SwingReason.SHORT_PRICE_CAP,)}
    coverage = result.coverage
    assert coverage.considered == coverage.eligible + coverage.incomplete + coverage.unknown + coverage.excluded == 6
    assert coverage.is_full_market and not coverage.sample_only and not coverage.quality_complete
    assert not coverage.daily_coverage_complete and coverage.unknown == 1
    assert all(row.stock_id not in {"2330", "2331", "9999"} for row in result.ranked_prefilter)


def test_future_receipt_never_ranks_and_cutoff_stays_fixed(monkeypatch, inputs):
    item = inputs["2330"]
    last = item.bars.bars[-1]
    last = last.model_copy(update={"lineage": last.lineage.model_copy(update={"received_at": REQUESTED_AT + timedelta(days=2)})})
    inputs["2330"] = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)})})
    calls, _ = _install(monkeypatch, inputs)
    result = build_tw_swing_discovery_snapshot(object(), request=_request().model_copy(update={"batch_size": 6}), with_detail=False)
    row = next(row for row in result.checkpoint.rows if row.stock_id == "2330")
    assert row.window_return_pct is None and not row.receipt_cutoff_verified
    assert SwingReason.SOURCE_AFTER_CUTOFF in row.reason_codes
    assert "2330" not in result.top_stock_ids
    assert all(max(call["trade_dates"]) == CUTOFF for call in calls["canonical"])


def test_resume_rejects_changed_source_and_request_but_allows_budget_change(monkeypatch, inputs):
    calls, _ = _install(monkeypatch, inputs)
    request = _request()
    first = build_tw_swing_discovery_snapshot(object(), request=request, with_detail=False)
    resumed = build_tw_swing_discovery_snapshot(object(), request=request.model_copy(update={"batch_size": 1}), checkpoint=first.checkpoint, with_detail=False)
    assert resumed.coverage.considered == 3
    with pytest.raises(ValueError, match="CHECKPOINT_BASIS_CHANGED"):
        build_tw_swing_discovery_snapshot(object(), request=request.model_copy(update={"horizon_sessions": 15}), checkpoint=first.checkpoint)
    calls["external"] = "changed-corporate"
    with pytest.raises(ValueError, match="CHECKPOINT_BASIS_CHANGED"):
        build_tw_swing_discovery_snapshot(object(), request=request, checkpoint=first.checkpoint)
    with pytest.raises(ValueError, match="exact processed universe prefix"):
        SwingDiscoveryCheckpoint.model_validate({**first.checkpoint.model_dump(), "rows": tuple(reversed(first.checkpoint.rows))})


def test_calendar_unknown_is_a_typed_quality_limit_not_a_scope_change(monkeypatch, inputs):
    _install(monkeypatch, inputs)
    monkeypatch.setattr(prefilter, "has_taiwan_calendar_year", lambda year: False)
    result = build_tw_swing_discovery_snapshot(object(), request=_request().model_copy(update={"batch_size": 6}), with_detail=False)
    assert result.coverage.is_full_market and not result.coverage.sample_only
    assert not result.calendar_coverage_known and not result.coverage.quality_complete
    assert all(SwingReason.CALENDAR_COVERAGE_UNKNOWN in row.reason_codes for row in result.checkpoint.rows)
    assert result.model_dump(mode="json")["checkpoint"]["rows"][0]["reason_codes"]


def test_empty_universe_and_budget_validation(monkeypatch):
    _install(monkeypatch, {})
    result = build_tw_swing_discovery_snapshot(object(), request=_request())
    assert result.status == "empty" and result.coverage.universe_count == 0
    assert not result.prefilter_empty_result_is_valid and not result.empty_result_is_valid
    for change in ({"batch_size": 101}, {"top_n": 101}, {"max_batches": True}, {"markets": ()}):
        with pytest.raises(ValueError):
            SwingDiscoveryRequest.model_validate({**_request().model_dump(), **change})


@pytest.mark.parametrize("case", ["visible", "future", "affected"])
def test_snapshot_receipt_quality_does_not_change_full_scan_scope(monkeypatch, inputs, case):
    future = case == "future"
    item = inputs["2330"]
    _install(monkeypatch, {"2330": item})
    monkeypatch.setattr(prefilter, "snapshot_storage_available", lambda db: True)
    monkeypatch.setattr(prefilter, "read_input_revisions", lambda db, ids: {})
    monkeypatch.setattr(prefilter, "snapshot_matches", lambda *a, **kw: True)
    monkeypatch.setattr(prefilter, "get_technical_analysis_parameters", lambda: SimpleNamespace(
        revision=item.technical.parameter_contract["parameter_revision"]))
    payload = dict(item.price_map.payload)
    if case == "affected":
        payload["corporate_action"] = {"coverage_status": "complete", "affected_dates": [CUTOFF.isoformat()], "adjustment_applied": False}
    row = SimpleNamespace(status="ready", payload_json=json.dumps(payload),
        published_at=REQUESTED_AT + timedelta(days=1) if future else REQUESTED_AT - timedelta(hours=1))
    monkeypatch.setattr(prefilter, "read_price_map_snapshots", lambda *a: {"2330": row})
    result = build_tw_swing_discovery_snapshot(object(), request=_request(), with_detail=False)
    cheap = result.checkpoint.rows[0]
    assert result.coverage.is_full_market and not result.coverage.sample_only
    assert not result.coverage.quality_complete  # flow remains explicitly deferred
    assert cheap.corporate_quality == ("unknown" if future else "affected" if case == "affected" else "complete")
    if case == "affected":
        assert cheap.window_return_pct is None and not result.top_stock_ids
    assert (SwingReason.SOURCE_AFTER_CUTOFF in cheap.reason_codes) is future
    assert cheap.institutional_policy == "deferred_to_top_n_detail"
    if case == "visible":
        assert cheap.status == "eligible"
        assert result.coverage.eligible == 1 and result.coverage.incomplete == 0
        assert result.coverage.prefilter_quality_complete
        assert result.coverage.prefilter_selected == 1
        assert result.coverage.detail_sample_only and result.coverage.detail_considered == 0
        assert cheap.institutional.status == "unknown" and cheap.institutional.foreign_net_shares is None


def test_price_map_and_swing_share_the_same_ordinary_stock_owner():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models import Base, StockMaster
    from app.market.price_map_snapshot_repository import read_price_map_universe
    from app.market.tw_universe import list_taiwan_stock_universe
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            for symbol, market, kind, active in [("2330", "TWSE", "stock", True),
                    ("6147", "TPEx", "stock", True), ("12345", "TWSE", "stock", True),
                    ("ABCD", "TPEX", "stock", True), ("0050", "TWSE", "ETF", True),
                    ("9999", "TWSE", "stock", False)]:
                db.add(StockMaster(stock_id=symbol, market=market, instrument_type=kind, is_active=active))
            db.commit()
            expected = [s.stock_id for s in list_taiwan_stock_universe(db)]
            assert expected == ["2330", "6147"]
            assert [s.stock_id for s in read_price_map_universe(db)] == expected
    finally:
        engine.dispose()
