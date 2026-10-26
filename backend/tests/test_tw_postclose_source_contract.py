"""2026-10-20 incident regression: disposable SQLite, no provider/runtime IO."""
from datetime import date, datetime, timedelta
import json

import pytest

from app.db.models import (
    JobRun, MarketDailyPrice, MarketIndexDailyStat, RawFetchResult,
    SourceRegistry, StockMaster, TaiwanMarketMinuteState,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_contracts import TAIEX_OFFICIAL_DAILY_SOURCE
from app.market.tw_market_dashboard import _latest_index_baseline
from app.market.taiwan_market_state import (
    _has_usable_trade_value, compose_taiwan_market_volume_state,
    persist_taiwan_market_minute_state, read_taiwan_market_volume_state,
)
from test_taiwan_market_state import make_session, market_summary_payload


@pytest.fixture
def db():
    session = make_session()
    yield session
    session.close()
    session.bind.dispose()


def _seed_index(db):
    from app.market.indices import _persist_market_index_daily_stats
    _persist_market_index_daily_stats(
        db, index_id="TAIEX", market="TWSE",
        rows=[dict(trade_date=date(2026, 10, 19), close_value=123.5, price_change=1)],
        source="twse_rwd_fmtqik", source_url=None,
    )
    legacy = db.query(MarketIndexDailyStat).one()
    assert legacy.source_id is None and legacy.raw_result_id is None
    source = SourceRegistry(source_name=TAIEX_OFFICIAL_DAILY_SOURCE,
                            source_type="official", category="market_index",
                            reliability_level="official")
    db.add(source)
    db.flush()
    raw = RawFetchResult(source_id=source.id,
        fetched_at=datetime(2026, 10, 19, 12, 40), method="GET",
        content_hash="a" * 64, parser_version="fixture")
    db.add(raw)
    db.flush()
    row = MarketDailyPrice(source_id=source.id, raw_result_id=raw.id,
        stock_id="TAIEX", trade_date=date(2026, 10, 19), canonical_market="TW",
        venue="TWSE", instrument_type="index", authority="exchange",
        finalization="final", official=True, release_status="released",
        reconciliation_status="not_applicable",
        open_price=120, low_price=119, high_price=125, close_price=123.5)
    db.add(row)
    db.commit()
    return row, raw, source


def _baseline(db, **kwargs):
    return _latest_index_baseline(db, index_id="TAIEX",
        trade_date=date(2026, 10, 20),
        requested_at=kwargs.get("requested_at", datetime(2026, 10, 20, 8, tzinfo=TAIWAN_TZ)))


def test_legacy_writer_null_fks_use_existing_canonical_gateway_without_repair(db):
    row, raw, _ = _seed_index(db)
    before = (db.query(MarketIndexDailyStat).one().raw_result_id, db.query(RawFetchResult).count())
    baseline = _baseline(db)
    assert float(baseline.close_value) == 123.5  # fixture, never the incident's real price
    assert baseline.trade_date == date(2026, 10, 19)
    assert baseline.lineage.raw_receipt_id == f"raw_fetch_result:{raw.id}"
    assert baseline.lineage.observation_id == f"market_daily_price:{row.id}"
    assert (db.query(MarketIndexDailyStat).one().raw_result_id,
            db.query(RawFetchResult).count()) == before
    assert not db.dirty and not db.new


@pytest.mark.parametrize("case", [
    "missing_raw", "wrong_raw_source", "wrong_source", "wrong_date",
    "pre_release_receipt", "future_receipt", "derived", "unreleased",
    "provisional", "reconciliation_mismatch", "missing_hash",
])
def test_index_baseline_never_relaxes_official_date_release_or_lineage(db, case):
    row, raw, source = _seed_index(db)
    if case == "missing_raw":
        row.raw_result_id = None
    elif case == "wrong_raw_source":
        other = SourceRegistry(source_name="other", source_type="official", category="market_index")
        db.add(other)
        db.flush()
        raw.source_id = other.id
    elif case == "wrong_source":
        source.source_name = "untrusted_daily"
    elif case == "wrong_date":
        row.trade_date = date(2026, 10, 16)
    elif case == "pre_release_receipt":
        raw.fetched_at = datetime(2026, 10, 19, 5, 34, 59)
    elif case == "future_receipt":
        raw.fetched_at = datetime(2026, 10, 20, 1)
    elif case == "derived":
        row.authority = "derived"
    elif case == "unreleased":
        row.release_status = "pending_release"
    elif case == "provisional":
        row.finalization = "provisional"
    elif case == "reconciliation_mismatch":
        row.reconciliation_status = "mismatched"
    elif case == "missing_hash":
        raw.content_hash = ""
    db.commit()
    assert _baseline(db) is None


def test_index_baseline_before_release_is_unavailable(db):
    _seed_index(db)
    assert _baseline(db, requested_at=datetime(2026, 10, 19, 13, 34, tzinfo=TAIWAN_TZ)) is None


def _final_payload(day, minute=32):
    payload = market_summary_payload(day, hour=13, minute=minute,
                                    twse_trade_value=1000, tpex_trade_value=200)
    for item in payload["indices"]:
        item["breadth"].update(
            trade_value_is_estimate=True, official_flag=False,
            trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots",
            acquisition_diagnostics=dict(acquisition_complete=True, failed_batch_count=0,
                skipped_batch_count=0, fallback_used=False, received_count=item["breadth"]["total_count"]),
            coverage_reason_counts=dict(advance=item["breadth"]["advance_count"],
                decline=item["breadth"]["decline_count"], unchanged=item["breadth"]["unchanged_count"],
                valid_no_trade=0),
        )
        # Receipt/summary clock and index close are not the turnover owner clock.
        item["current_data_core"]["index"]["as_of"] = f"{day}T13:30:00+08:00"
    payload["as_of"] = f"{day}T14:15:00+08:00"
    return payload


def test_finalized_1332_event_stays_1332_and_compares_only_exact_history(db):
    days = [date(2026, 10, d) for d in (13, 14, 15, 16, 19, 20)]
    for day in days:
        persist_taiwan_market_minute_state(db, payload=_final_payload(day), finalized=True)
    rows = db.query(TaiwanMarketMinuteState).all()
    assert {row.minute_at.strftime("%H:%M") for row in rows} == {"13:32"}
    assert all(_has_usable_trade_value(row) for row in rows)
    assert all("13:32:45" in row.component_sources_json for row in rows)
    result = read_taiwan_market_volume_state(db)
    assert result["comparison_minute"] == "13:32"
    assert result["current_cumulative_trade_value"] == 1200
    assert result["same_time_baseline_5d"]["sample_days"] == 5
    assert result["same_time_baseline_5d"]["comparison_minute"] == "13:32"
    assert result["same_time_baseline_5d"]["pace_ratio"] == 1
    assert result["same_time_baseline_20d"]["pace_ratio"] is None
    assert result["official_cumulative_trade_value"] is None
    assert compose_taiwan_market_volume_state(result, breadth=None)["same_time_baseline_5d"]["pace_ratio"] == 1


def test_existing_1330_baseline_is_not_relabelled_when_current_resolves_1332():
    from test_tw_volume_composition import evidence
    volume, breadth = evidence()
    volume["same_time_baseline_5d"]["comparison_minute"] = "13:30"
    for item in breadth["markets"].values():
        item["as_of"] = "2026-09-14T13:32:45+08:00"
        item["lineage"]["event_at"] = item["as_of"]
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["comparison_minute"] == "13:32"
    baseline = result["same_time_baseline_5d"]
    assert baseline["comparison_minute"] == "13:32"
    assert baseline["sample_days"] == 0
    assert baseline["samples"] == []
    assert baseline["pace_ratio"] is None
    rejected = result["baseline_diagnostics"]["rejected_comparison_context"]["same_time_baseline_5d"]
    assert rejected["comparison_minute"] == "13:30" and rejected["sample_days"] == 5
    assert volume["same_time_baseline_5d"]["sample_days"] == 5


@pytest.mark.parametrize("case", [
    "legacy_1330_bucket", "wrong_date", "missing_receipt", "missing_provider",
    "mixed_authority", "mixed_semantics", "mixed_scope", "different_event_minute",
    "missing_value",
])
def test_finalized_volume_negative_contracts(db, case):
    persist_taiwan_market_minute_state(db, payload=_final_payload(date(2026, 10, 20)), finalized=True)
    row = db.query(TaiwanMarketMinuteState).filter_by(market="TPEX").one()
    if case == "legacy_1330_bucket":
        # Incident-shaped historical rows stay untrusted. No rewrite/backfill.
        for existing in db.query(TaiwanMarketMinuteState):
            existing.minute_at = datetime(2026, 10, 20, 13, 30)
            existing.calculation_version = "tw.market.minute_state.derived.v3"
    elif case == "wrong_date":
        row.trade_date = date(2026, 10, 19)
    elif case in {"missing_receipt", "missing_provider"}:
        components = json.loads(row.component_sources_json)
        owner = next(item for item in components if item["owns_trade_value"])
        owner["raw_result_id" if case == "missing_receipt" else "provider"] = None
        row.component_sources_json = json.dumps(components)
    elif case == "mixed_authority":
        row.trade_value_is_estimate = False
    elif case == "mixed_semantics":
        row.trade_value_semantics = "official_cumulative_trade_value"
    elif case == "mixed_scope":
        row.breadth_scope = "registered_universe"
    elif case == "different_event_minute":
        row.minute_at = datetime(2026, 10, 20, 13, 31)
    else:
        row.cumulative_trade_value = None
    db.commit()
    result = read_taiwan_market_volume_state(db)
    assert result["current_cumulative_trade_value"] is None
    assert result["same_time_baseline_5d"]["pace_ratio"] is None


def test_proxy_is_research_only_in_resolver_headline_and_v4():
    from app.market.index_resolution import (
        ResolvedTaiwanIndexTruth, resolve_taiwan_index_truth, project_taiwan_index_headline,
    )
    from app.ai.market_context.taiwan_projection import _compact_index_quote
    from app.ai.decision_envelope_v4 import _brief_capability_summary
    from test_tw_index_truth_convergence import _snapshot, _calendar
    snapshot = _snapshot()
    snapshot.update(index_id="TPEX", completed_daily_source="tpex_index_5s_components",
                    completed_daily_provider="tpex_index_5s", completed_daily_authority="derived",
                    completed_daily_official=False)
    truth = resolve_taiwan_index_truth(intraday=None, index_snapshot=snapshot,
        calendar_status=_calendar(), index_id="TPEX", acquisition_policy="cache_only")
    assert truth.selected_authority == "derived_proxy"
    assert truth.research_usable is True
    assert truth.decision_usable is False
    assert truth.official_close_confirmed is False
    assert truth.provisional_estimate is True
    snapshot["resolution"] = truth.model_dump(mode="json")
    with pytest.raises(ValueError, match="decision usability"):
        ResolvedTaiwanIndexTruth.model_validate({**snapshot["resolution"], "decision_usable": True})
    assert project_taiwan_index_headline(snapshot)["decision_usable"] is False
    quote = _compact_index_quote(index_id="TPEX", index_snapshot=snapshot,
                                 intraday=None, calendar_status=_calendar())
    for output in (quote, _brief_capability_summary("quote.snapshot", quote)):
        assert output["decision_usable"] is False
        assert output["price_decision_usable"] is False
        assert output["research_usable"] is True
        assert output["selected_authority"] == "derived_proxy"
        assert output["official_close_confirmed"] is False
        assert output["source"] == truth.selected_source
        assert output["latest_price"] == truth.selected_value


def test_selector_ranks_and_cadence_receipt_preserve_cap_and_due_times(db, monkeypatch):
    from app.market import tw_intraday_universe as universe
    from app.jobs import taiwan_intraday_bar_scheduler as scheduler
    symbols = [str(1000 + i) for i in range(40)]
    db.add_all([StockMaster(stock_id=code, market="TWSE", instrument_type="stock",
                           is_active=True) for code in symbols])
    db.commit()
    monkeypatch.setattr(universe, "_holding_symbols", lambda db: [])
    monkeypatch.setattr(universe, "_watchlist_symbols", lambda db: symbols)
    plan = universe.resolve_taiwan_tier_a_target_plan(
        db, configured_symbols=[], lease_symbols=[], max_symbols=32)
    excluded = plan["selection_diagnostics"][35]
    assert excluded == dict(stock_id=symbols[35], selected=False, candidate_rank=36,
                            eligible_rank=36, reason="scheduler_hard_cap")
    before = db.query(JobRun).count()
    now = datetime(2026, 10, 20, 10, tzinfo=TAIWAN_TZ)
    row, state = scheduler._checkpoint(db, f"tw-cadence:scheduler:{now.date()}")
    state["next_due_at"] = {code: (now + timedelta(minutes=5)).isoformat() for code in plan["symbols"]}
    state["existing_owner_marker"] = "retained"
    scheduler.save_checkpoint(db, row, state, now)
    def forbidden(*args, **kwargs):
        raise AssertionError("no due work: enqueue forbidden")
    results = scheduler._submit_batch(db, plan["symbols"], now=now, origin="scheduler",
                                      enqueuer=forbidden, target_plan=plan)
    _, after = scheduler._checkpoint(db, row.key)
    assert results == [] and db.query(JobRun).count() == before
    assert after["next_due_at"] == state["next_due_at"]
    assert after["existing_owner_marker"] == "retained"
    assert after["target_selection"]["diagnostics"][35] == excluded
    assert after["target_selection"]["selected_count"] == 32


@pytest.mark.parametrize("symbol,day,missing_count", [
    ("2330", date(2026, 10, 20), 1),
    ("3406", date(2026, 10, 19), 28),
])
def test_source_absent_minutes_are_not_synthesized(db, symbol, day, missing_count):
    """Synthetic coverage shapes, not a replay of the production Raw receipts."""
    from app.market.providers.tw_intraday_bars import (
        IntradayProviderPayload, NStockIntradayAdapter, YahooIntradayAdapter,
    )
    from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
    from app.market.tw_intraday_capabilities import NSTOCK_INTRADAY_DESCRIPTOR
    from app.market.tw_intraday_platform import refresh_taiwan_intraday_bars
    from app.market.tw_bar_service import TaiwanBarService
    db.add(StockMaster(stock_id=symbol, market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    start = datetime.combine(day, datetime.min.time(), tzinfo=TAIWAN_TZ).replace(hour=9)
    now = start.replace(hour=14)
    omitted = {start + timedelta(minutes=128 + n) for n in range(missing_count)}
    times = [start + timedelta(minutes=n) for n in range(265)]
    rows = [
        {"交易日": day.strftime("%Y%m%d"), "交易時間": at.strftime("%H%M%S"),
         "開盤價": "100", "最高價": "101", "最低價": "99", "收盤價": "100", "成交量": "1"}
        for at in times if at not in omitted
    ]
    raw_text = json.dumps({"data": [{"分K": rows, "總成交量": str(len(rows))}]})
    calls = []
    def fixture_reader(stock_id, timeout):
        calls.append(stock_id)
        return IntradayProviderPayload(raw_text=raw_text, status="available",
            url="https://example.test/nstock", status_code=200, content_type="application/json")
    def forbidden(*args):
        raise AssertionError("alternate provider forbidden")
    acquisition = TaiwanIntradayAcquisitionExecutor(
        nstock=NStockIntradayAdapter(fixture_reader, clock=lambda: now),
        yahoo=YahooIntradayAdapter(forbidden, clock=lambda: now), clock=lambda: now)
    refresh_taiwan_intraday_bars(db, stock_id=symbol, interval="1m", range_value="1d",
        requested_at=now, descriptors=(NSTOCK_INTRADAY_DESCRIPTOR,), acquisition=acquisition)
    series = TaiwanBarService(db).read_bars(instrument_id=symbol, interval="1m",
        from_time=start, to_time=now, requested_at=now, include_partial=True)
    observed = {bar.start_at.astimezone(TAIWAN_TZ) for bar in series.bars}
    assert calls == [symbol]
    assert len(observed) == 265 - missing_count
    assert observed == set(times) - omitted
    assert all(bar.volume.value > 0 for bar in series.bars)
    assert any(item.status.value == "missing_evidence" for item in series.bucket_coverage)
