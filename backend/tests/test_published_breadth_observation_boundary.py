"""Real acquisition/transaction/read path keeps breadth and daily gates separate."""
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from app.db.models import MarketDailyPrice, RawFetchResult, StockMaster, TaiwanPublishedBreadthSnapshot
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.market.official_breadth_platform import read_taiwan_official_breadth
from app.market.providers.tw_official_daily import TWSE_RWD_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID
from test_tw_official_daily_platform import db, FakeResponse  # noqa: F401
from test_tw_published_breadth import DAY, payload
from test_tpex_published_breadth import DAY as TPEX_DAY, RAW as TPEX_RAW


@pytest.mark.parametrize('venue', ['TWSE', 'TPEX'])
@pytest.mark.parametrize('hour,minute,admitted', [(5, 29, False), (5, 30, True), (6, 40, True)])
def test_published_only_uses_close_boundary_with_one_call_and_no_daily_write(db, venue, hour, minute, admitted):
    day = DAY if venue == 'TWSE' else TPEX_DAY
    now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
    symbol = '3711' if venue == 'TWSE' else '6488'
    db.add(StockMaster(stock_id=symbol, stock_name='fixture', market=venue, instrument_type='stock', is_active=True))
    db.commit()
    fetch = Mock(return_value=FakeResponse(text=json.dumps(payload()) if venue == 'TWSE' else TPEX_RAW.decode('utf-8')))
    resource = TWSE_RWD_DAILY_RESOURCE_ID if venue == 'TWSE' else TPEX_HIGHLIGHT_RESOURCE_ID
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={resource: fetch}, clock=lambda: now, monotonic=lambda: 10.0)
    result = refresh_taiwan_official_daily_venue(db, venue=venue, trade_date=day, requested_at=now,
        refresh_daily=False, max_external_calls=1, acquisition=executor)
    assert fetch.call_count == int(admitted)
    assert result['external_call_count'] == int(admitted)
    assert db.query(MarketDailyPrice).count() == 0
    assert db.query(RawFetchResult).count() == int(admitted)
    assert db.query(TaiwanPublishedBreadthSnapshot).count() == int(admitted)
    read = read_taiwan_official_breadth(db, venue=venue, trade_date=day, requested_at=now, allow_universe_fallback=False)
    assert (read.resolved.breadth is not None) == admitted


def test_twse_early_daily_receipt_persists_aggregate_without_promoting_daily(db):
    from test_tw_early_regular_daily import DAY as early_day, payload as early_payload
    now = datetime(early_day.year, early_day.month, early_day.day, 6, 40, tzinfo=timezone.utc)
    body = early_payload()
    body['tables'].append(payload()['tables'][-1])
    db.add(StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock', is_active=True))
    db.commit()
    fetch = Mock(return_value=FakeResponse(text=json.dumps(body)))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={TWSE_RWD_DAILY_RESOURCE_ID: fetch},
        clock=lambda: now, monotonic=lambda: 10.0)
    result = refresh_taiwan_official_daily_venue(db, venue='TWSE', trade_date=early_day, requested_at=now,
        max_external_calls=1, acquisition=executor)
    assert result['external_call_count'] == fetch.call_count == 1
    assert {row.release_status for row in db.query(MarketDailyPrice)} == {'regular_research'}
    stored = db.query(TaiwanPublishedBreadthSnapshot).one()
    assert stored.error_code is None
    read = read_taiwan_official_breadth(db, venue='TWSE', trade_date=early_day, requested_at=now, allow_universe_fallback=False)
    assert read.resolved.breadth is not None
    assert read.resolved.breadth.advance_count == 20
    assert read.resolved.breadth.published_limits.up_count == 3
