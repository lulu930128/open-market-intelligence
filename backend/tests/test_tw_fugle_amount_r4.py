import pytest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

RECEIPTS=json.loads((Path(__file__).parent/'fixtures/tw_fugle_index_r4.json').read_text(encoding='utf-8'))


def replay(db, monkeypatch, receipt, *, requested_at=None, completion_clock=None):
    from app.market.providers import fugle_http
    from app.market.providers.tw_current_market import CurrentIndexAdapter
    from app.market.tw_current_market_capabilities import current_source_binding,FUGLE_HTTP_CURRENT_INDEX_DESCRIPTOR
    from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor
    from app.market.tw_current_market_platform import refresh_taiwan_current_index
    fetched=datetime.fromisoformat(receipt['received_at'])
    scope='TAIEX' if receipt['symbol']=='IX0001' else 'TPEX'
    assert sha256(receipt['raw_text'].encode()).hexdigest()==receipt['content_hash']
    calls=[]
    def reader(kind,symbol,timeout):
        calls.append((kind,symbol))
        return fugle_http.FugleHttpPayload(raw_text=receipt['raw_text'],status_code=200,external_calls=1)
    monkeypatch.setattr(fugle_http,'read_fugle_http',reader)
    binding=current_source_binding(provider='fugle_marketdata',source='fugle_http_index_quote',capability_id='market.index.snapshot')
    adapter=CurrentIndexAdapter(binding,fugle_http.read_fugle_current_index,clock=lambda:fetched)
    observed=[]
    acquire=adapter.acquire
    def recording(*args):
        acquired=acquire(*args);observed.extend(acquired.observations);return acquired
    monkeypatch.setattr(adapter,'acquire',recording)
    result=refresh_taiwan_current_index(db,index_id=scope,requested_at=requested_at or fetched+timedelta(seconds=1),
        completion_clock=completion_clock,
        require_trade_value=True,descriptors=(FUGLE_HTTP_CURRENT_INDEX_DESCRIPTOR,),
        acquisition=TaiwanCurrentIndexAcquisitionExecutor((adapter,)))
    assert result.acquisition.external_calls==1 and len(calls)==1
    assert observed[0].cumulative_trade_value is not None
    return result


def test_real_http_amounts_survive_canonical_persistence_and_report(monkeypatch):
    from test_tw_current_market_platform import _db
    from app.market.tw_current_market_platform import project_taiwan_current_trade_value
    from app.market.taiwan_market_state import read_taiwan_market_volume_state,_volume_comparison_identity
    db,engine=_db()
    try:
        amounts=[]
        for receipt in RECEIPTS:
            result=replay(db,monkeypatch,receipt)
            amount=project_taiwan_current_trade_value(result)
            assert amount['trade_value']==json.loads(receipt['raw_text'])['total']['tradeValue']
            assert amount['official_flag'] is False and amount['trade_value_is_estimate'] is False
            assert amount['lineage']['content_hash']==receipt['content_hash']
            amounts.append(amount)
        state=read_taiwan_market_volume_state(db,requested_at=datetime.fromisoformat(RECEIPTS[-1]['received_at'])+timedelta(seconds=1))
        assert state['current_cumulative_trade_value']==645978481260
        assert state['official_cumulative_trade_value'] is None
        assert state['estimated_cumulative_trade_value'] is None
        assert state['trade_value_authority_status']=='vendor_reported'
        assert state['same_time_baseline_5d']['pace_ratio'] is None
        assert state['same_time_baseline_20d']['pace_ratio'] is None
        assert _volume_comparison_identity(amounts[0])['authority_class']=='vendor_reported'
    finally:db.close();engine.dispose()


def test_newer_stream_does_not_hide_amount_or_satisfy_amount_requirement(monkeypatch):
    from test_tw_current_market_platform import _db
    from app.db.models import TaiwanCurrentIndexSnapshot,RawFetchResult,SourceRegistry
    from app.market.tw_current_market_platform import read_taiwan_current_index,project_taiwan_current_trade_value
    db,engine=_db()
    try:
        replay(db,monkeypatch,RECEIPTS[0])
        http=db.query(TaiwanCurrentIndexSnapshot).one()
        source=SourceRegistry(source_name='fugle_indices_stream',source_type='stream',category='market_data')
        db.add(source);db.flush()
        event=http.event_at+timedelta(seconds=2)
        raw=RawFetchResult(source_id=source.id,fetched_at=http.fetched_at,content_hash='stream-fixture',
            parser_version='fugle.websocket.indices.v1',raw_text=json.dumps({'data':{'symbol':'IX0001'}}))
        db.add(raw);db.flush()
        values={col.name:getattr(http,col.name) for col in TaiwanCurrentIndexSnapshot.__table__.columns
                if col.name not in {'id','created_at','updated_at'}}
        values.update(source_id=source.id,raw_result_id=raw.id,source=source.source_name,
            raw_contract_version=raw.parser_version,event_at=event,trade_value=None,currency=None,transaction_count=None)
        db.add(TaiwanCurrentIndexSnapshot(**values));db.commit()
        now=datetime.fromisoformat(RECEIPTS[0]['received_at'])+timedelta(seconds=3)
        price=read_taiwan_current_index(db,index_id='TAIEX',requested_at=now)
        amount=read_taiwan_current_index(db,index_id='TAIEX',requested_at=now,require_trade_value=True)
        assert price.resolved.market_index.lineage.source=='fugle_indices_stream'
        projected=project_taiwan_current_trade_value(amount)
        assert projected['source']=='fugle_http_index_quote'
        assert datetime.fromisoformat(projected['as_of'])!=price.resolved.market_index.lineage.event_at
        # Remove the amount row in the isolated DB; the fresh price is not a
        # satisfied turnover requirement and the registered FETCH runs once.
        db.delete(http);db.commit()
        assert read_taiwan_current_index(db,index_id='TAIEX',requested_at=now,require_trade_value=True).resolved.market_index is None
        replay(db,monkeypatch,RECEIPTS[0])
    finally:db.close();engine.dispose()

@pytest.mark.parametrize('symbol',['IX0001','IX0043'])
def test_existing_http_owner_accepts_only_supported_index_quotes(monkeypatch,symbol):
    from app.market.providers import fugle_http
    monkeypatch.setattr(fugle_http.settings,'fugle_api_key',None)
    assert fugle_http.read_fugle_http('quote',symbol,5).error=='FUGLE_CREDENTIAL_MISSING'
    with pytest.raises(ValueError):fugle_http.read_fugle_http('candles',symbol,5)
    with pytest.raises(ValueError):fugle_http.read_fugle_http('quote','IX9999',5)


def test_current_refresh_accepts_its_receipt_but_historical_read_cannot(monkeypatch):
    from test_tw_current_market_platform import _db
    from app.market.tw_current_market_platform import read_taiwan_current_index
    db,engine=_db()
    receipt=datetime.fromisoformat(RECEIPTS[0]['received_at']);started=receipt-timedelta(seconds=1)
    try:
        result=replay(db,monkeypatch,RECEIPTS[0],requested_at=started,completion_clock=lambda:receipt+timedelta(seconds=1))
        assert result.resolved.market_index.cumulative_trade_value is not None
        historical=read_taiwan_current_index(db,index_id='TAIEX',requested_at=started,require_trade_value=True)
        assert historical.resolved.market_index is None
    finally:db.close();engine.dispose()


@pytest.mark.parametrize('case',['one_venue','different_minute','identity','wrong_unit'])
def test_amount_selection_rebuilds_old_official_state_and_deltas(monkeypatch,case):
    from test_tw_current_market_platform import _db
    from test_tw_volume_composition import evidence
    from app.market.tw_current_market_platform import project_taiwan_current_trade_value
    from app.market.taiwan_market_state import compose_taiwan_market_volume_state
    db,engine=_db()
    try:
        components={}
        for receipt in RECEIPTS:
            amount=project_taiwan_current_trade_value(replay(db,monkeypatch,receipt));components[amount['market']]=amount
        old,official=evidence()
        old.update(current_cumulative_trade_value=999,official_cumulative_trade_value=999,
            markets=list(official['markets'].values()),as_of=components['TPEX']['as_of'],
            previous_minute_cumulative_trade_value=900,one_minute_trade_value_change=99)
        old['same_time_baseline_20d']={**old['same_time_baseline_5d'],'sample_days':20,'qualified_sample_days':20}
        if case=='one_venue':components.pop('TPEX')
        if case=='different_minute':components['TPEX']['as_of']='2026-10-29T11:09:45+08:00'
        if case=='wrong_unit':components['TPEX']['trade_value_unit']='USD'
        state=compose_taiwan_market_volume_state(old,breadth=None,current_components=components)
        assert state['official_cumulative_trade_value'] is None
        assert state['estimated_cumulative_trade_value'] is None
        assert state['previous_minute_cumulative_trade_value'] is None
        assert state['one_minute_trade_value_change'] is None
        assert state['field_status']['current_cumulative_trade_value']['source']=='canonical_market_trade_value'
        assert all(row['trade_date']=='2026-10-29' for row in state['markets'])
        assert (state['current_cumulative_trade_value'] is not None)==(case=='identity')
        for days in (5,20):assert state[f'same_time_baseline_{days}d']['pace_ratio'] is None
    finally:db.close();engine.dispose()


def test_persisted_minute_fallback_respects_historical_cutoff():
    from test_taiwan_market_state import make_session,market_summary_payload
    from app.market.taiwan_market_state import persist_taiwan_market_minute_state,read_taiwan_market_volume_state
    from datetime import date
    db=make_session()
    try:
        persist_taiwan_market_minute_state(db,payload=market_summary_payload(date(2026,10,29),hour=9,minute=45,
            twse_trade_value=1000,tpex_trade_value=2000));db.commit()
        result=read_taiwan_market_volume_state(db,requested_at=datetime.fromisoformat('2026-10-29T09:30:00+08:00'))
        assert result['current_cumulative_trade_value'] is None and result['as_of'] is None
    finally:db.close();db.get_bind().dispose()


def test_scheduler_summary_entry_acquires_amounts(monkeypatch):
    from test_tw_current_market_platform import _db
    from app.market import indices,tw_current_market_operations,tw_current_market_platform as platform
    from app.market.providers import fugle_http
    from app.market.providers.tw_current_market import CurrentIndexAdapter
    from app.market.tw_current_market_capabilities import current_source_binding
    from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor
    db,engine=_db();calls=[]
    completed=datetime.fromisoformat(RECEIPTS[-1]['received_at'])+timedelta(seconds=1)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return completed.astimezone(tz) if tz else completed.replace(tzinfo=None)
    def reader(kind,symbol,timeout):
        calls.append(symbol);r=next(row for row in RECEIPTS if row['symbol']==symbol)
        return fugle_http.FugleHttpPayload(raw_text=r['raw_text'],status_code=200,external_calls=1)
    monkeypatch.setattr(fugle_http,'read_fugle_http',reader)
    binding=current_source_binding(provider='fugle_marketdata',source='fugle_http_index_quote',capability_id='market.index.snapshot')
    adapter=CurrentIndexAdapter(binding,fugle_http.read_fugle_current_index,clock=lambda:completed)
    executor=TaiwanCurrentIndexAcquisitionExecutor((adapter,))
    monkeypatch.setattr(tw_current_market_operations,'build_current_market_executors',lambda *a,**k:(executor,None))
    monkeypatch.setattr(indices,'datetime',Clock)
    monkeypatch.setattr(indices,'_shared_current_market_summary',lambda db,**kw:{'indices':[
        platform.project_taiwan_current_trade_value(platform.read_taiwan_current_index(db,index_id=s,
            requested_at=completed,require_trade_value=True)) for s in ('TAIEX','TPEX')]})
    try:
        result=indices.refresh_current_market_index_snapshots(db)
        assert sorted(calls)==['IX0001','IX0043']
        assert all(row['trade_value']>0 for row in result['indices'])
    finally:db.close();engine.dispose()


def test_completion_cutoff_never_mutates_second_route_acquisition_plan():
    from test_tw_current_market_platform import _db
    from app.market.providers.tw_current_market import CurrentIndexAdapter,CurrentMarketProviderPayload
    from app.market.tw_current_market_capabilities import current_source_binding,FUGLE_HTTP_CURRENT_INDEX_DESCRIPTOR,TWSE_MIS_CURRENT_INDEX_DESCRIPTOR
    from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor
    from app.market.tw_current_market_platform import refresh_taiwan_current_index
    now=datetime.fromisoformat(RECEIPTS[0]['received_at']);calls=[]
    def failed(*a):
        calls.append('http');return CurrentMarketProviderPayload(payload=None,status='failed',error='fixture denied')
    def price_only(*a):
        calls.append('mis');return CurrentMarketProviderPayload(payload=dict(as_of=now.isoformat(),close=20000,
            change=100,trade_date=now.date().isoformat()),status='available')
    adapters=tuple(CurrentIndexAdapter(current_source_binding(provider=p,source=s,capability_id='market.index.snapshot'),r,
        clock=lambda:now+timedelta(seconds=1)) for p,s,r in (
            ('fugle_marketdata','fugle_http_index_quote',failed),('twse_mis','twse_mis_index_snapshot',price_only)))
    db,engine=_db()
    try:
        result=refresh_taiwan_current_index(db,index_id='TAIEX',requested_at=now,require_trade_value=True,
            completion_clock=lambda:now+timedelta(seconds=2),
            descriptors=(FUGLE_HTTP_CURRENT_INDEX_DESCRIPTOR,TWSE_MIS_CURRENT_INDEX_DESCRIPTOR),
            acquisition=TaiwanCurrentIndexAcquisitionExecutor(adapters))
        assert calls==['http','mis']
        assert result.acquisition.external_calls==2
        assert result.resolved.market_index is None
        assert result.requirement.requested_at==now
    finally:db.close();engine.dispose()
