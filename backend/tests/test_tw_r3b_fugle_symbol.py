"""Exercise the real Fugle HTTP reader and canonical ETF demand offline."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from threading import Lock

import pytest

from app.market.providers import fugle_http as http
from app.market_data.contracts import InstrumentKey
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market.tw_intraday_capabilities import FUGLE_HTTP_INTRADAY_DESCRIPTOR
from app.market.public_quote_platform import build_taiwan_public_quote_requirement
from app.market.tw_realtime_capabilities import FUGLE_HTTP_QUOTE_DESCRIPTOR
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.market_data.policies import RealtimePolicy
from app.market.trading_calendar import TAIWAN_TZ

NOW = datetime(2026,10,28,13,25,tzinfo=TAIWAN_TZ)


@pytest.fixture
def transport(monkeypatch):
    from collections import deque
    monkeypatch.setattr(http.settings,'fugle_api_key','offline-fixture')
    monkeypatch.setattr(http,'_calls',deque())
    monkeypatch.setattr(http,'_transport',Lock())
    monkeypatch.setattr(http,'_cooldown_until',0.0)
    class Calls(list):
        bar_count = 265
    calls=Calls()
    def get(url, **kwargs):
        calls.append((url,kwargs))
        symbol=url.rsplit('/',1)[-1]
        body={'symbol':symbol,'type':'ETF' if symbol.startswith('00') else 'EQUITY',
              'exchange':'TWSE','market':'TSE','date':NOW.date().isoformat(),
              'lastTrade':{'price':100,'size':2,'time':int(NOW.timestamp()*1e6)},
              'total':{'tradeVolume':265,'tradeValue':26500000,'time':int(NOW.timestamp()*1e6)},
              'timeframe':'1','data':[{'date':(NOW.replace(hour=9,minute=0)+timedelta(minutes=i)).isoformat(),
                  'open':100,'high':101,'low':99,'close':100,'volume':1} for i in range(calls.bar_count)]}
        return SimpleNamespace(status_code=200,text=json.dumps(body))
    monkeypatch.setattr(http,'get',get)
    return calls


@pytest.mark.parametrize('symbol',['00981A','2330','00679B'])
@pytest.mark.parametrize('kind',['quote','candles'])
def test_default_reader_accepts_canonical_stock_and_etf_routes(transport,symbol,kind):
    instrument=InstrumentKey(market='TW',symbol=symbol,venue='TWSE',instrument_type='etf' if symbol.startswith('00') else 'stock')
    request=(build_taiwan_intraday_requirement(instrument=instrument,interval='1m',range_value='1d',
        policy=RealtimePolicy.PREFER_LIVE,requested_at=NOW,acquiring=True) if kind=='candles' else
        build_taiwan_public_quote_requirement(instrument=instrument,policy=RealtimePolicy.PREFER_LIVE,requested_at=NOW))
    descriptor=FUGLE_HTTP_INTRADAY_DESCRIPTOR if kind=='candles' else FUGLE_HTTP_QUOTE_DESCRIPTOR
    route=plan_data_acquisition_v2(request,(descriptor,)).routes[0]
    assert route.fetch_allowed and not route.subscription_allowed and route.max_external_calls==1
    # Do not replace adapter.reader: this covers the previously bypassed guard.
    result=http.FugleHttpAdapter(clock=lambda:NOW).acquire_route(request,route)
    assert result.summary.status.value=='completed'
    assert result.summary.external_calls==1
    assert len(result.observations)==(265 if kind=='candles' else 1)
    assert len(transport)==1 and transport[0][0].endswith(f'/{kind}/{symbol}')
    assert transport[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('symbol',['','123','12345678','ABCD','00981a','00981AA','00981A/quote','00981A?x=1',
    '../2330','2330#fragment',' 2330','2330 ','2330\n','2330\x00','２３３０','台積電','00981A%2fquote'])
def test_invalid_http_path_segments_never_reach_transport(transport,symbol):
    with pytest.raises(ValueError,match='unsupported Fugle HTTP target'):
        http.read_fugle_http('candles',symbol,1)
    assert transport==[]


# This fixture creates only an in-memory DB and captures dispatch; it does not
# replace acquisition, canonical persistence, resolver, or the final reread.
from test_tw_r3_demand_failure import env


def test_etf_demand_rebuilds_cached_141_bars_to_ready_265(env, transport):
    from app.db.models import StockMaster, JobRun, MarketIntradayBar, MarketIntradayBarLineage
    from app.jobs import taiwan_intraday_demand as demand
    from app.market.intraday_transaction import TaiwanIntradayBarTransaction
    from app.ai.refresh_status import read_refresh_status
    env.clock[0] = NOW
    instrument = InstrumentKey(market='TW', symbol='00981A', venue='TWSE', instrument_type='etf')
    requirement = build_taiwan_intraday_requirement(instrument=instrument, interval='1m', range_value='1d',
        policy=RealtimePolicy.PREFER_LIVE, requested_at=NOW, acquiring=True)
    route = plan_data_acquisition_v2(requirement, (FUGLE_HTTP_INTRADAY_DESCRIPTOR,)).routes[0]
    transport.bar_count = 141
    acquired = http.FugleHttpAdapter(clock=lambda: NOW).acquire_route(requirement, route)
    with env.factory() as db:
        db.add(StockMaster(stock_id='00981A', stock_name='ETF fixture', market='TWSE', instrument_type='etf', is_active=True))
        db.commit()
        persisted = TaiwanIntradayBarTransaction(db).persist_bar_acquisition(requirement, acquired)
        assert persisted.committed and persisted.observations_written == 141
        job, _ = demand.enqueue_consumer_demand(db, stock_id='00981A', requested_at=NOW,
            consumer='ai', max_external_calls=1, timeout_seconds=12)
        job_id = job.id
        before = demand._reread(db, demand.consumer_request(job), NOW)
        assert before['current_session_bar_count'] == 141 and before['reread_ready'] is False
    transport.clear()
    transport.bar_count = 265
    demand.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert len(transport) == 1 and transport[0][0].endswith('/candles/00981A')
        assert result['external_call_count'] == result['external_call_budget_used'] == 1
        assert result['bars_written_count'] == 124
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 265
        assert result['current_session_bar_count'] == 265 and result['reread_ready'] is True
        assert result['snapshot_revision'] != before['snapshot_revision']
        assert result['snapshot_revision'] == demand._reread(db, demand.consumer_request(job), NOW)['snapshot_revision']
        public = read_refresh_status(db=db, job_id=job_id)
        assert public['status'] == 'completed' and public['error'] is None
        assert public['materialization']['reread_ready'] is True
