from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.tw_bar_aggregation import observed_trade_coverage
from app.market.tw_bar_contracts import (
    TaiwanBarOutwardState, TaiwanBarSeriesRead, TaiwanHistoryCoverage,
    TaiwanHistoryStatus, TaiwanReconciliationStatus, TaiwanReleaseStatus,
)
from app.market.tw_bar_identity import build_taiwan_bar_series_identity
from app.market.tw_swing_screening import (
    SwingInstitutionalEvidence, SwingPriceMapEvidence, SwingReason,
    SwingScreenRequest, SwingStockEvidence, _read_institutional,
    build_tw_swing_screening_snapshot, screen_tw_swing_candidates,
)
from app.market.tw_technical_service import TaiwanTechnicalService
from app.market_data.contracts import (
    AuthorityClass, BarFinalization, BarObservation, InstrumentKey,
    InstrumentType, Market, Quantity, QuantityUnit, SourceLineage,
)


CUTOFF = date(2026, 10, 27)
REQUESTED_AT = datetime(2026, 10, 27, 18, tzinfo=TAIWAN_TZ)


def _request(ids=("2330", "6147"), **overrides):
    return SwingScreenRequest(stock_ids=ids, as_of_trade_date=CUTOFF,
        requested_at=REQUESTED_AT, **overrides)


def _evidence(stock_id, *, falling=False, last_close=None):
    instrument = InstrumentKey(market=Market.TW, symbol=stock_id,
        instrument_type=InstrumentType.STOCK, venue="TWSE")
    sessions = []
    cursor = CUTOFF
    while len(sessions) < 80:
        if is_taiwan_trading_day(cursor):
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    sessions.reverse()
    step = Decimal("-0.1") if falling else Decimal("0.1")
    final = Decimal(str(last_close)) if last_close is not None else Decimal("100")
    bars, states = [], []
    for index, day in enumerate(sessions):
        close = final + step * (index - 79)
        start = datetime.combine(day, time(9), TAIWAN_TZ)
        end = datetime.combine(day, time(13, 30), TAIWAN_TZ)
        bar = BarObservation(instrument=instrument, lineage=SourceLineage(
            provider="twse_openapi", source="twse_daily_ohlcv", authority=AuthorityClass.EXCHANGE,
            event_at=end, received_at=end + timedelta(hours=1), content_hash=f"{stock_id}-{index}"),
            interval="1d", start_at=start, end_at=end,
            open_price=close - step, close_price=close,
            high_price=close + Decimal("1"), low_price=close - Decimal("1"),
            volume=Quantity(value=Decimal(1_000_000), unit=QuantityUnit.SHARE), volume_status="observed",
            turnover_value=close * 1_000_000, turnover_currency="TWD", trade_count=1000,
            price_basis="raw", finalization=BarFinalization.FINAL)
        bars.append(bar)
        states.append(TaiwanBarOutwardState(start_at=start, finalization=BarFinalization.FINAL,
            authority=AuthorityClass.EXCHANGE, official=True, release_status=TaiwanReleaseStatus.RELEASED,
            reconciliation_status=TaiwanReconciliationStatus.MATCHED, persisted=True,
            source_interval="1d", technical_eligible=True))
    coverage = observed_trade_coverage(tuple(bars), trading_policy_version="tw.trading_policy.daily.v1")
    identity = build_taiwan_bar_series_identity(instrument=instrument, requested_interval="1d", base_interval="1d",
        bars=tuple(bars), coverage=coverage, aggregation_version=None, state={"fixture": stock_id})
    series = TaiwanBarSeriesRead(instrument=instrument, requested_interval="1d", base_interval="1d", derived=False,
        bars=tuple(bars), bar_states=tuple(states), bucket_coverage=coverage, expected_sessions=tuple(sessions),
        identity=identity, history=TaiwanHistoryCoverage(requested_from=bars[0].start_at, requested_to=bars[-1].end_at,
            available_from=bars[0].start_at, available_to=bars[-1].end_at,
            requested_session_count=80, covered_session_count=80, history_status=TaiwanHistoryStatus.READY,
            requested_coverage_satisfied=True))
    parameters = get_technical_analysis_parameters(persisted_settings={
        "ma_windows": "5,20,60", "volume_ma_windows": "5,20", "atr_period": 14})
    technical = TaiwanTechnicalService().calculate(series, parameters=parameters)
    price = float(final)
    payload = {"version": "tw.stock.price_map.v4", "stock_id": stock_id, "structure_timeframe": "daily",
        "structure_input_usable": True, "basis_revision": f"basis-{stock_id}",
        "reference": {"trade_date": CUTOFF.isoformat(), "price": price},
        "parameter_contract": technical.parameter_contract,
        "corporate_action": {"coverage_status": "complete", "affected_dates": []},
        "zones": [
            {"zone_id": "support", "side": "downside", "lower_bound": price - 1, "upper_bound": price - 0.5,
             "scanner_eligible": True, "geometry_status": "ready"},
            {"zone_id": "resistance", "side": "upside", "lower_bound": price + 0.5, "upper_bound": price + 1,
             "scanner_eligible": True, "geometry_status": "ready"},
        ]}
    sign = -1 if falling else 1
    return SwingStockEvidence(stock_id=stock_id, market="TWSE", stock_name=stock_id,
        active_ordinary_stock=True, bars=series, technical=technical,
        price_map=SwingPriceMapEvidence(status="ready", published_at=REQUESTED_AT - timedelta(hours=1), payload=payload),
        institutional=SwingInstitutionalEvidence(status="qualified", trade_dates=tuple(sessions[-5:]),
            available_at=REQUESTED_AT - timedelta(hours=1), foreign_net_shares=sign * 50_000,
            trust_net_shares=sign * 10_000, source_refs=("raw_fetch_result:1",)))


@pytest.fixture(scope="module")
def evidence():
    return (_evidence("2330"), _evidence("6147", falling=True))


@pytest.mark.parametrize("horizon", [10, 15])
def test_completed_daily_long_short_stable_ranking_without_current_quote(evidence, horizon):
    request = _request(horizon_sessions=horizon, mode="confirmed")
    result = screen_tw_swing_candidates(request, evidence)
    replay = screen_tw_swing_candidates(request, tuple(reversed(evidence)))
    assert result == replay
    assert result.status == "ready" and result.coverage.qualified == 2
    assert {(x.stock_id, x.direction, x.mode) for x in result.candidates} == {
        ("2330", "long", "confirmed"), ("6147", "short", "confirmed")}
    assert all(x.horizon_sessions == horizon and x.stage == "research_qualified" for x in result.candidates)
    short = next(x for x in result.candidates if x.direction == "short")
    assert short.current_short_price_cap == "unknown"
    assert not short.execution_ready and not short.trigger_ready
    assert short.basis.source_received_at < REQUESTED_AT
    assert short.basis.price_map_basis_revision == "basis-6147"


def test_aggressive_is_a_completed_daily_hypothesis_not_trigger(evidence):
    item = evidence[0]
    last = item.bars.bars[-1]
    # Daily close holds the MA but the candle does not confirm reversal.
    last = last.model_copy(update={"open_price": last.close_price + Decimal("0.1")})
    bars = item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)})
    changed = item.model_copy(update={"bars": bars})
    result = screen_tw_swing_candidates(_request(("2330",), mode="aggressive"), (changed,))
    assert len(result.candidates) == 1 and result.candidates[0].mode == "aggressive"
    assert not result.candidates[0].trigger_ready


@pytest.mark.parametrize("price,eligible", [(199.9, True), (200, False), (200.1, False)])
def test_short_cap_is_strictly_below_200(price, eligible):
    item = _evidence("6147", falling=True, last_close=price)
    result = screen_tw_swing_candidates(_request(("6147",), direction="short"), (item,))
    assert bool(result.candidates) is eligible
    if not eligible:
        assert result.assessments[0].excluded_directions == {"short": (SwingReason.SHORT_PRICE_CAP,)}
        assert result.empty_result_is_valid


@pytest.mark.parametrize("partial,affected", [(True, False), (False, True)])
def test_partial_or_corporate_action_only_allows_limited_discovery(evidence, partial, affected):
    item = evidence[0]
    payload = {**item.price_map.payload, "corporate_action": {
        "coverage_status": "partial" if partial else "complete",
        "affected_dates": ["2026-10-20"] if affected else [], "adjustment_applied": False}}
    item = item.model_copy(update={"price_map": item.price_map.model_copy(update={"status": "partial", "payload": payload})})
    result = screen_tw_swing_candidates(_request(("2330",)), (item,))
    assert result.status == "limited" and result.coverage.incomplete == 1
    assert result.candidates[0].stage == "discovered" and result.candidates[0].zone is None
    assert result.candidates[0].opportunity_score is None
    assert not result.empty_result_is_valid
    reason = SwingReason.CORPORATE_ACTION_AFFECTED if affected else SwingReason.CORPORATE_ACTION_UNKNOWN
    assert reason in result.assessments[0].reason_codes


@pytest.mark.parametrize("fault,reason", [
    ("gap", SwingReason.DAILY_HISTORY_GAP),
    ("partial", SwingReason.DAILY_NOT_COMPLETED),
    ("late_receipt", SwingReason.SOURCE_AFTER_CUTOFF),
    ("future_bar", SwingReason.SOURCE_AFTER_CUTOFF),
])
def test_ineligible_history_never_enters_ranking(evidence, fault, reason):
    item = evidence[0]
    bars = list(item.bars.bars)
    states = list(item.bars.bar_states)
    if fault == "gap":
        del bars[-3]
        del states[-3]
    elif fault == "partial":
        bars[-1] = bars[-1].model_copy(update={"finalization": BarFinalization.PROVISIONAL})
        states[-1] = states[-1].model_copy(update={"technical_eligible": False})
    elif fault == "future_bar":
        bars[-1] = bars[-1].model_copy(update={"start_at": bars[-1].start_at + timedelta(days=2)})
    else:
        lineage = bars[-1].lineage.model_copy(update={"received_at": REQUESTED_AT + timedelta(days=2)})
        bars[-1] = bars[-1].model_copy(update={"lineage": lineage})
    item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": tuple(bars), "bar_states": tuple(states)})})
    result = screen_tw_swing_candidates(_request(("2330",)), (item,))
    assert result.status == "limited" and not result.candidates and not result.empty_result_is_valid
    assert reason in result.assessments[0].reason_codes


@pytest.mark.parametrize("late", [False, True])
def test_daily_raw_receipt_fetched_at_is_used_without_fabricating_received_at(evidence, late):
    item = evidence[0]
    bars = []
    for index, bar in enumerate(item.bars.bars):
        fetched_at = bar.lineage.received_at
        if late and index == len(item.bars.bars) - 1:
            fetched_at = REQUESTED_AT + timedelta(days=2)
        lineage = bar.lineage.model_copy(update={"received_at": None, "fetched_at": fetched_at,
            "raw_receipt_id": f"raw_fetch_result:{index + 1}"})
        bars.append(bar.model_copy(update={"lineage": lineage}))
    item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": tuple(bars)})})
    result = screen_tw_swing_candidates(_request(("2330",), mode="confirmed"), (item,))
    assessment = result.assessments[0]
    assert assessment.basis.daily_receipt_basis == "raw_receipt_fetched_at"
    assert assessment.basis.source_received_at is None
    assert assessment.basis.source_fetched_at == bars[-1].lineage.fetched_at
    assert "raw_fetch_result:80" in assessment.basis.source_refs
    assert SwingReason.SOURCE_TIME_UNKNOWN not in assessment.reason_codes
    if late:
        assert result.status == "limited" and not result.candidates
        assert SwingReason.SOURCE_AFTER_CUTOFF in assessment.reason_codes
        assert not assessment.basis.daily_cutoff_verified
    else:
        assert result.status == "ready" and result.candidates[0].stage == "research_qualified"
        assert assessment.basis.daily_cutoff_verified


@pytest.mark.parametrize("missing", ["event", "traceable_receipt"])
def test_truly_unknown_time_only_allows_historical_limited_discovery(evidence, missing):
    item = evidence[0]
    last = item.bars.bars[-1]
    patch = {"event_at": None} if missing == "event" else {
        # A local updated_at/fetched_at without a receipt reference is not
        # proof of when the underlying evidence became available.
        "received_at": None, "fetched_at": REQUESTED_AT - timedelta(hours=1), "raw_receipt_id": None}
    last = last.model_copy(update={"lineage": last.lineage.model_copy(update=patch)})
    item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)})})
    result = screen_tw_swing_candidates(_request(("2330",)), (item,))
    candidate = result.candidates[0]
    assert result.status == "limited" and result.coverage.qualified == 0 and result.coverage.incomplete == 1
    assert not result.empty_result_is_valid and not result.coverage.complete
    assert SwingReason.SOURCE_TIME_UNKNOWN in candidate.reason_codes
    assert candidate.stage == "discovered" and candidate.evidence_quality == "limited"
    assert candidate.zone is None and candidate.opportunity_score is None
    assert not candidate.trigger_ready and not candidate.execution_ready
    assert not candidate.basis.daily_cutoff_verified
    assert any("point-in-time replay are unverified" in note for note in candidate.basis.evidence_cutoff_limitations)
    assert not screen_tw_swing_candidates(_request(("2330",), mode="confirmed"), (item,)).candidates


def test_unknown_time_discovery_keeps_short_cap_and_empty_quality_gate(evidence):
    item = _evidence("6147", falling=True, last_close=200)
    last = item.bars.bars[-1]
    last = last.model_copy(update={"lineage": last.lineage.model_copy(update={"received_at": None})})
    item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)})})
    result = screen_tw_swing_candidates(_request(("6147",), direction="short"), (item,))
    assert result.status == "limited" and not result.candidates
    assert result.assessments[0].excluded_directions == {"short": (SwingReason.SHORT_PRICE_CAP,)}
    assert not result.empty_result_is_valid and not result.coverage.complete


def test_snapshot_after_historical_request_does_not_backfill_ranking(evidence):
    item = evidence[0]
    pm = item.price_map.model_copy(update={"published_at": REQUESTED_AT + timedelta(days=2)})
    result = screen_tw_swing_candidates(_request(("2330",)), (item.model_copy(update={"price_map": pm}),))
    assert result.status == "limited"
    assert result.candidates[0].stage == "discovered" and result.candidates[0].zone is None
    assert SwingReason.SOURCE_AFTER_CUTOFF in result.assessments[0].reason_codes


@pytest.mark.parametrize("patch", [{"version": "tw.stock.price_map.v3"}, {"reference": []}])
def test_incompatible_or_malformed_snapshot_is_limited(evidence, patch):
    item = evidence[0]
    pm = item.price_map.model_copy(update={"payload": {**item.price_map.payload, **patch}})
    result = screen_tw_swing_candidates(_request(("2330",)), (item.model_copy(update={"price_map": pm}),))
    assert result.status == "limited"
    assert all(x.stage == "discovered" and x.zone is None for x in result.candidates)


def test_valid_empty_is_distinct_from_not_computed_and_partial(evidence):
    request = _request(("2330",), direction="short")
    empty = screen_tw_swing_candidates(request, (evidence[0],))
    missing = screen_tw_swing_candidates(request, (evidence[0].model_copy(update={"bars": None, "technical": None}),))
    partial = screen_tw_swing_candidates(request, (evidence[0].model_copy(update={"price_map": None}),))
    assert empty.status == "ready" and empty.empty_result_is_valid
    assert missing.status == "not_computed" and missing.coverage.not_computed == 1
    assert not missing.empty_result_is_valid
    assert partial.status == "limited" and not partial.empty_result_is_valid


def test_coverage_precedes_ranking_pagination_and_unavailable_members(evidence):
    request = _request(("2330", "6147", "6770"), top_n=1, limit=1, mode="confirmed")
    result = screen_tw_swing_candidates(request, evidence)
    assert result.coverage.universe_count == 3 and result.coverage.observed == 2
    assert result.coverage.qualified == 2 and result.coverage.excluded == 1
    assert result.coverage.candidate_count == 2 and result.coverage.returned_count == 1
    assert result.coverage.research_qualified_candidate_count == 2
    assert result.coverage.limited_candidate_count == 0
    assert result.coverage.sample_only and not result.coverage.complete
    assert result.response_truncated and result.status == "limited"
    page = screen_tw_swing_candidates(request.model_copy(update={"offset": 1}), evidence)
    assert page.snapshot_id == result.snapshot_id and not page.candidates
    assert page.coverage.research_qualified_candidate_count == result.coverage.research_qualified_candidate_count
    assert not page.empty_result_is_valid


def test_unknown_institutional_and_liquidity_are_not_zero(evidence):
    item = evidence[0]
    last = item.bars.bars[-1].model_copy(update={"turnover_value": None})
    item = item.model_copy(update={"institutional": SwingInstitutionalEvidence(),
        "bars": item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)})})
    result = screen_tw_swing_candidates(_request(("2330",)), (item,))
    candidate = result.candidates[0]
    assert candidate.evidence_quality == "limited" and candidate.liquidity_turnover_twd is None
    assert result.coverage.limited_candidate_count == 1
    assert candidate.institutional.foreign_net_shares is None
    assert SwingReason.LIQUIDITY_UNKNOWN in candidate.reason_codes


def test_internal_db_entry_delegates_cutoff_and_keeps_missing_snapshot_limited(monkeypatch, evidence):
    import app.market.price_map_snapshot_repository as snapshots
    import app.market.tw_bar_service as canonical
    import app.market.tw_universe as universe
    import app.market.tw_swing_screening as screening
    import app.market.technical_parameters as parameters

    monkeypatch.setattr(parameters, "get_technical_analysis_setting_payload", lambda: {})

    calls = []
    monkeypatch.setattr(universe, "list_taiwan_stock_universe", lambda db, **kw: [
        SimpleNamespace(stock_id=x.stock_id, stock_name=x.stock_name, market=x.market) for x in evidence])
    monkeypatch.setattr(snapshots, "snapshot_storage_available", lambda db: False)
    monkeypatch.setattr(canonical.TaiwanBarService, "read_bars", lambda self, **kw:
        calls.append(kw) or next(x.bars for x in evidence if x.stock_id == kw["instrument_id"]))
    monkeypatch.setattr(canonical.TaiwanBarService, "read_current_session_bars", lambda *a, **kw:
        pytest.fail("Completed-daily swing research must not require an intraday baseline"))
    monkeypatch.setattr(screening, "_read_institutional", lambda db, request, stock_id, sessions:
        next(x.institutional for x in evidence if x.stock_id == stock_id))
    # Data may have been filled through 10/29 now; the market cutoff remains
    # 10/27 independently of the visibility/receipt cutoff.
    visible_at = REQUESTED_AT + timedelta(days=3)
    result = build_tw_swing_screening_snapshot(object(), request=_request().model_copy(update={"requested_at": visible_at}))
    assert result.status == "limited" and len(result.candidates) == 2
    assert all(x.stage == "discovered" and x.zone is None for x in result.candidates)
    assert all(x["to_time"].date() == CUTOFF and x["requested_at"] == visible_at
        and x["include_partial"] is False and x["interval"] == "1d" for x in calls)


def test_institutional_reader_bounds_dates_and_rejects_late_corrections(monkeypatch, evidence):
    import app.market.service as service

    dates = evidence[0].bars.expected_sessions[-5:]
    calls = []
    rows = [SimpleNamespace(id=i, trade_date=day, created_at=REQUESTED_AT - timedelta(hours=1),
        updated_at=REQUESTED_AT - timedelta(hours=1), raw_result_id=i,
        foreign_investor_net=100, investment_trust_net=-50) for i, day in enumerate(dates, 1)]
    monkeypatch.setattr(service, "list_stock_institutional_trade_history", lambda db, **kw: calls.append(kw) or rows)
    result = _read_institutional(object(), _request(), "2330", dates)
    assert result.status == "qualified" and result.foreign_net_shares == 500 and result.trust_net_shares == -250
    assert calls[0]["to_date"] == CUTOFF
    rows[-1].updated_at = REQUESTED_AT + timedelta(days=2)
    partial = _read_institutional(object(), _request(), "2330", dates)
    assert partial.status == "partial" and partial.foreign_net_shares is None


@pytest.mark.parametrize("overrides", [{"horizon_sessions": 5}, {"short_price_cap": 201}, {"limit": True}, {"requested_at": datetime(2026, 10, 27, 18)}])
def test_invalid_requests_are_rejected(overrides):
    with pytest.raises(ValueError):
        SwingScreenRequest.model_validate({**_request().model_dump(), **overrides})


def _retest_evidence(*, short=False):
    item = _evidence("6147" if short else "2330", falling=short)
    bars = list(item.bars.bars)
    sign = Decimal(-1 if short else 1)
    for index, price, low, high in ((-2, Decimal("100") + sign * 2, Decimal("97"), Decimal("103")),
                                   (-1, Decimal("100") + sign * Decimal("1.5"), Decimal("97") if short else Decimal("100.5"), Decimal("99.5") if short else Decimal("103"))):
        bars[index] = bars[index].model_copy(update={"close_price": price, "open_price": price - sign * Decimal("0.1"),
            "low_price": low, "high_price": high,
            "volume": Quantity(value=Decimal(3_000_000 if index == -2 else 1_000_000), unit=QuantityUnit.SHARE)})
    coverage = observed_trade_coverage(tuple(bars), trading_policy_version="tw.trading_policy.daily.v1")
    identity = build_taiwan_bar_series_identity(instrument=item.bars.instrument, requested_interval="1d", base_interval="1d",
        bars=tuple(bars), coverage=coverage, aggregation_version=None, state={"retest_fixture": short})
    series = item.bars.model_copy(update={"bars": tuple(bars), "identity": identity, "bucket_coverage": coverage})
    params = get_technical_analysis_parameters(persisted_settings={"ma_windows": "5,20,60", "volume_ma_windows": "5,20", "atr_period": 14})
    technical = TaiwanTechnicalService().calculate(series, parameters=params)
    payload = {**item.price_map.payload, "reference": {"trade_date": CUTOFF.isoformat(), "price": float(bars[-1].close_price)}}
    return item.model_copy(update={"bars": series, "technical": technical,
        "price_map": item.price_map.model_copy(update={"payload": payload})})


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("horizon", [10, 15])
def test_completed_daily_retests_use_prior_owner_levels(short, horizon):
    item = _retest_evidence(short=short)
    result = screen_tw_swing_candidates(_request((item.stock_id,), direction="short" if short else "long", horizon_sessions=horizon), (item,))
    candidate = result.candidates[0]
    assert candidate.setup_type == ("breakdown_retest" if short else "breakout_retest")
    assert candidate.stage == "research_qualified" and candidate.mode == "confirmed"
    assert candidate.retest.level_basis_trade_date < candidate.retest.break_trade_date < candidate.retest.retest_trade_date == CUTOFF
    assert candidate.retest.break_volume_ratio > 1 and candidate.retest.break_pvo > 0
    assert not candidate.trigger_ready and not candidate.execution_ready


@pytest.mark.parametrize("fault", ["unconfirmed_volume", "future_only_level", "reclaimed_level", "corporate_partial"])
def test_retest_needs_qualified_prior_evidence_and_no_close_invalidation(fault):
    item = _retest_evidence(short=True)
    points = [dict(point) for point in item.technical.points]
    if fault == "unconfirmed_volume":
        points[-2] = {**points[-2], "pvo": {"pvo": None}}
    elif fault == "future_only_level":
        points[-3] = {**points[-3], "support_resistance": {}}
    elif fault == "reclaimed_level":
        last = item.bars.bars[-1].model_copy(update={"close_price": Decimal("100")})
        item = item.model_copy(update={"bars": item.bars.model_copy(update={"bars": (*item.bars.bars[:-1], last)}),
            "price_map": item.price_map.model_copy(update={"payload": {**item.price_map.payload,
                "reference": {"trade_date": CUTOFF.isoformat(), "price": 100}}})})
    else:
        item = item.model_copy(update={"price_map": item.price_map.model_copy(update={"status": "partial",
            "payload": {**item.price_map.payload, "corporate_action": {"coverage_status": "partial"}}})})
    item = item.model_copy(update={"technical": item.technical.model_copy(update={"points": tuple(points)})})
    result = screen_tw_swing_candidates(_request((item.stock_id,), direction="short"), (item,))
    assert all(candidate.setup_type != "breakdown_retest" and candidate.retest is None for candidate in result.candidates)
