from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketIndexDailyStat, RawFetchResult, SourceRegistry
from app.market import indices
from app.market.index_resolution import resolve_taiwan_index_quote_state
from app.market.official_index_contract import (
    TWSE_INDEX_SOURCE_NAME, expected_taiwan_index_close_date,
)
from app.market.official_index_platform import read_taiwan_official_index
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import TAIWAN_TZ


def _now(hour, minute):
    return datetime(2026, 8, 25, hour, minute, tzinfo=TAIWAN_TZ)


@pytest.mark.parametrize("hour,minute,index_day,daily_day", [
    (13, 34, 24, 24), (13, 35, 25, 24), (13, 40, 25, 24), (15, 15, 25, 25),
])
def test_index_expectedness_is_independent_of_stock_daily(hour, minute, index_day, daily_day):
    assert expected_taiwan_index_close_date(now=_now(hour, minute)) == date(2026, 8, index_day)
    assert expected_daily_price_date(now=_now(hour, minute)) == date(2026, 8, daily_day)


def _summary(*, final):
    values = []
    for config in indices.INDEX_CONFIGS:
        item = {"index_id": config["index_id"], "time": "2026-08-25",
                "trade_date": "2026-08-25", "as_of": _now(13, 30).isoformat(),
                "close": 100, "source": "fugle_indices_stream", "provider": "fugle",
                "breadth": {"trade_date": "2026-08-25", "scope": "full_market"}}
        if final:
            item.update(completed_daily_close=101, completed_daily_trade_date="2026-08-25",
                completed_daily_event_time=_now(13, 30).isoformat(),
                completed_daily_source="twse_mi_5mins_hist", completed_daily_provider="twse",
                completed_daily_authority="exchange", completed_daily_finalization="final",
                completed_daily_official=True, completed_daily_release_status="released",
                completed_daily_reconciliation_status="not_applicable", completed_daily_qualified=True)
        item["resolution"] = resolve_taiwan_index_quote_state(
            intraday=None, index_snapshot=item, index_id=config["index_id"],
            acquisition_policy="cache_only", calendar_status={
                "phase": "post_close", "timezone": "Asia/Taipei", "date": "2026-08-25",
                "checked_at": _now(13, 41).isoformat(), "previous_trading_day": "2026-08-24",
                "is_trading_day": True, "presentation_session": {"trade_date": "2026-08-25"},
            })
        values.append(item)
    return {"indices": values}


@pytest.mark.parametrize("minute", [35, 36, 41, 50])
def test_reconciliation_does_not_stop_for_provisional_with_ready_breadth(minute):
    assert indices.market_index_summary_needs_reconciliation(_summary(final=False), now=_now(13, minute))
    assert indices.market_index_summary_needs_reconciliation(None, now=_now(13, minute))
    assert not indices.market_index_summary_needs_reconciliation(_summary(final=True), now=_now(13, minute))


def test_reconciliation_is_bounded_and_axes_remain_independent():
    assert not indices.market_index_summary_needs_reconciliation(None, now=_now(13, 34))
    assert not indices.market_index_summary_needs_reconciliation(None, now=_now(16, 1))
    assert indices.market_index_summary_needs_reconciliation(None, now=_now(16, 1), allow_late=True)
    final = _summary(final=True)
    final["indices"][0]["breadth"] = None
    assert indices.market_index_summary_needs_reconciliation(final, now=_now(13, 41))


@pytest.mark.parametrize("receipt_minute,accepted", [(34, False), (35, True), (36, True)])
def test_production_official_reader_qualifies_index_receipt_before_daily_release(receipt_minute, accepted):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = SourceRegistry(source_name=TWSE_INDEX_SOURCE_NAME, source_type="official", category="market_index")
        db.add(source)
        db.flush()
        raw = RawFetchResult(source_id=source.id, fetched_at=_now(13, receipt_minute).astimezone(timezone.utc),
                             content_hash="official-close", parser_version="test")
        db.add(raw)
        db.flush()
        db.add(MarketIndexDailyStat(source_id=source.id, raw_result_id=raw.id, index_id="TAIEX", market="TWSE",
                                   trade_date=date(2026, 8, 25), close_value=100, price_change=1,
                                   trade_volume=100, trade_value=1000, transaction_count=5, source="fixture"))
        db.commit()
        result = read_taiwan_official_index(db, index_id="TAIEX", trade_date=date(2026, 8, 25), requested_at=_now(13, 41))
        assert (result.resolved.market_index is not None) is accepted
        assert result.acquisition.external_calls == 0
    engine.dispose()
