from datetime import date, datetime, timedelta

import pytest

from app.db.models import MarketIntradayBar, TaiwanFuturesDailyBar, TaiwanMarketMinuteState
from app.market.tw_futures import taiwan_futures_daily_bar_to_dict
from app.market.tw_bar_service import TaiwanBarService
from app.ai.technical_analysis import (_normalize_technical_points, _chart_from_points,
    _technical_report_from_points, evaluate_technical_evidence_sufficiency)
from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
from app.ai.data_quality_contract import _unit_summary
from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
import test_tw_bar_service as bars
import test_taiwan_market_state as volumes


def test_recent_cache_invalidates_after_materialization_and_correction():
    db, engine = bars._db()
    at = datetime.fromisoformat("2026-09-03T13:34:00+08:00")
    owner = TaiwanBarService(db)
    try:
        empty = owner.read_current_session_bars(instrument_id="2330", requested_at=at)
        assert empty.read_diagnostics.canonical_store_status == "miss"
        bars._seed_session(db, trade_date=at.date(), provider=bars.FUGLE_INTRADAY_PROVIDER, source_name=bars.FUGLE_INTRADAY_SOURCE,
            parser_version=bars.FUGLE_INTRADAY_PARSER_VERSION, authority="vendor", minutes=5)
        materialized = owner.read_current_session_bars(instrument_id="2330", requested_at=at)
        assert len(materialized.bars) == 5
        assert materialized.read_diagnostics.snapshot_cache_status == "miss"
        projected = project_taiwan_bar_series(materialized)
        assert projected["cache_hit"] is True and projected["cache_status"] == "persisted_hit"
        from app.market.tw_bar_contracts import project_taiwan_chart_bar_series
        assert project_taiwan_chart_bar_series(materialized).read_diagnostics == materialized.read_diagnostics
        warm = owner.read_current_session_bars(instrument_id="2330", requested_at=at)
        assert warm.read_diagnostics.snapshot_cache_status == "hit"
        assert warm.identity == materialized.identity
        row = db.query(MarketIntradayBar).order_by(MarketIntradayBar.bar_time.desc()).first()
        row.close_price = 104.75
        db.commit()
        corrected = owner.read_current_session_bars(instrument_id="2330", requested_at=at)
        assert corrected.read_diagnostics.snapshot_cache_status == "miss"
        assert corrected.identity.series_revision != materialized.identity.series_revision
        assert float(corrected.bars[-1].close_price) == 104.75
        assert corrected.read_diagnostics.final_series_revision == corrected.identity.series_revision
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("provider,expected", [("taifex_daily", True), ("legacy_unknown", False)])
def test_futures_owner_metadata_survives_daily_normalization_and_quality(provider, expected):
    rows = [taiwan_futures_daily_bar_to_dict(TaiwanFuturesDailyBar(
        id=index, market="TW", product_code="TX", product_name="TAIEX Futures", contract_symbol="TX202609",
        fetched_at=datetime(2026, 9, 4), created_at=datetime(2026, 9, 4), updated_at=datetime(2026, 9, 4),
        provider=provider, symbol="TXF", contract_month="202609", trade_date=date(2026, 9, 1)+timedelta(days=index),
        close_price=23000+index, total_volume=100+index, source="TAIFEX futures daily market report",
    )) for index in range(3)]
    from app.market.schemas import TaiwanFuturesDailyBarRead
    outward = TaiwanFuturesDailyBarRead.model_validate(rows[-1]).model_dump()
    assert outward["volume_unit"] == ("contracts" if expected else None)
    assert outward["volume_semantics"] == ("trading_day_contracts" if expected else None)
    points = _normalize_technical_points(rows)
    chart = _chart_from_points(timeframe="daily", points=points)
    report = _technical_report_from_points(points=points, timeframe="daily", asset_label="TXF")
    assert points[-1]["volume"] == 102
    assert points[-1]["contract_month"] == "202609"
    assert chart["volume_unit"] == ("contracts" if expected else None)
    assert report["volume_unit"] == chart["volume_unit"]
    assert chart["volume_semantics"] == ("trading_day_contracts" if expected else None)
    sufficiency = evaluate_technical_evidence_sufficiency(chart=chart, technical_reports={}, requested_horizon="short")
    assert sufficiency["volume_lineage_ok"] is expected
    assert bool(_unit_summary(chart)["missing_unit_fields"]) is (not expected)


def test_baseline_diagnostics_explain_zero_and_one_qualified_sample():
    db = volumes.make_session()
    try:
        for day, minute in ((date(2026, 9, 2), 29), (date(2026, 9, 3), 30)):
            persist_taiwan_market_minute_state(db, payload=volumes.market_summary_payload(
                day, hour=10, minute=minute, twse_trade_value=100, tpex_trade_value=20))
        result = read_taiwan_market_volume_state(db)
        assert result["available_sample_days"] == 0
        assert result["baseline_diagnostics"]["reason"] == "NO_COMPARABLE_SAMPLES"
        assert result["baseline_diagnostics"]["missing_comparison_minute"] == 1
        persist_taiwan_market_minute_state(db, payload=volumes.market_summary_payload(
            date(2026, 9, 2), hour=10, minute=30, twse_trade_value=120, tpex_trade_value=25))
        result = read_taiwan_market_volume_state(db)
        assert result["available_sample_days"] == 1
        assert result["baseline_readiness_status"] == "warming_up"
        assert result["baseline_diagnostics"]["reason"] == "WARMING_UP"
        assert result["same_time_baseline_5d"]["decision_usable"] is False
        row = db.query(TaiwanMarketMinuteState).filter_by(trade_date=date(2026, 9, 2), market="TWSE").order_by(TaiwanMarketMinuteState.minute_at.desc()).first()
        row.minute_at = row.minute_at - timedelta(days=1)
        db.commit()
        result = read_taiwan_market_volume_state(db)
        assert result["available_sample_days"] == 0
        assert result["baseline_diagnostics"]["trade_date_mismatch"] == 1
    finally:
        engine = db.get_bind()
        db.close()
        engine.dispose()
