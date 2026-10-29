"""Positive opening evidence never manufactures OHLC or exempts an ETF clock."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from app.market.tw_bar_aggregation import continuous_session_coverage
from app.market_data.contracts import QuoteObservation, Quantity, QuantityUnit, TradeObservationState
from test_tw_bar_aggregation import _bar, INSTRUMENT, TAIPEI

DAY=date(2026,9,1)
NOW=datetime(2026,9,1,9,5,tzinfo=TAIPEI)


def quote(symbol='00981A', minute=2, *, volume=0, state=TradeObservationState.INDICATIVE_OBSERVED):
    instrument=INSTRUMENT.model_copy(update={'symbol':symbol})
    event=NOW.replace(minute=minute)
    lineage=_bar(0).lineage.model_copy(update={'provider':'twse_mis','source':'twse_mis_quote_depth',
        'event_at':event,'received_at':event+timedelta(seconds=1),'fetched_at':event+timedelta(seconds=1),
        'raw_receipt_id':'raw_fetch_result:42','observation_id':'taiwan_stock_quote_snapshot:42'})
    return QuoteObservation(instrument=instrument,lineage=lineage,trade_date=DAY,trade_state=state,
        cumulative_quantity=Quantity(value=Decimal(volume),unit=QuantityUnit.SHARE))


def coverage(evidence, *, symbol='00981A', minutes=(2,4)):
    instrument=INSTRUMENT.model_copy(update={'symbol':symbol})
    bars=tuple(_bar(m).model_copy(update={'instrument':instrument}) for m in minutes)
    return continuous_session_coverage(bars,trade_date=DAY,trading_policy_version='fixture',as_of=NOW,
        instrument=instrument,opening_quote_evidence=tuple(evidence)),bars


@pytest.mark.parametrize('symbol',['00981A','00631L','2330'])
def test_proven_zero_cumulative_prefix_and_actual_interior_hole(symbol):
    rows,bars=coverage([quote(symbol)],symbol=symbol)
    assert [r.status.value for r in rows]==['verified_no_trade','verified_no_trade','observed_trade','missing_evidence','observed_trade']
    assert len(bars)==2 and bars[0].close_price==Decimal('102.5')
    assert rows[0].evidence_refs and rows[0].verified_by


@pytest.mark.parametrize('case',['no_evidence','wrong_symbol','wrong_date','positive_volume_enum',
    'unknown_volume','future_receipt','missing_lineage','earlier_actual','partial_minute'])
def test_unknown_and_contradictory_prefix_remains_missing(case):
    q=quote();minutes=(2,4)
    if case=='wrong_symbol':q=quote('00631L')
    if case=='wrong_date':q=q.model_copy(update={'trade_date':date(2026,8,31)})
    if case=='positive_volume_enum':q=quote(volume=1000,state=TradeObservationState.AWAITING_FIRST_TRADE)
    if case=='unknown_volume':q=q.model_copy(update={'cumulative_quantity':None})
    if case=='future_receipt':q=q.model_copy(update={'lineage':q.lineage.model_copy(update={'fetched_at':NOW+timedelta(seconds=1)})})
    if case=='missing_lineage':q=q.model_copy(update={'lineage':q.lineage.model_copy(update={'raw_receipt_id':None})})
    if case=='earlier_actual':minutes=(0,2,4)
    if case=='partial_minute':q=q.model_copy(update={'lineage':q.lineage.model_copy(update={'event_at':NOW.replace(minute=1,second=56)})})
    rows,_=coverage([] if case=='no_evidence' else [q],minutes=minutes)
    assert rows[1].status.value=='missing_evidence'
    if case not in {'earlier_actual','partial_minute'}:
        assert rows[0].status.value=='missing_evidence'


def test_first_actual_quote_with_matching_cumulative_quantity_proves_prefix():
    q=quote(volume=1000,state=TradeObservationState.TRADE_OBSERVED)
    q=q.model_copy(update={'last_trade_price':Decimal(100),
        'last_trade_quantity':Quantity(value=Decimal(1000),unit=QuantityUnit.SHARE)})
    rows,_=coverage([q])
    assert [r.status.value for r in rows[:2]]==['verified_no_trade']*2
    q=q.model_copy(update={'cumulative_quantity':Quantity(value=Decimal(2000),unit=QuantityUnit.SHARE)})
    rows,_=coverage([q])
    assert rows[0].status.value=='missing_evidence'


def seed_quote(db, symbol, *, minute=2, volume=0, receipt_offset=1, raw_hash='fixture', provider='twse_mis'):
    from app.db.models import SourceRegistry, RawFetchResult, TaiwanStockQuoteSnapshot
    event=NOW.replace(minute=minute)
    received=(event+timedelta(seconds=receipt_offset)).astimezone(timezone.utc)
    source=db.query(SourceRegistry).filter_by(source_name='twse_mis_quote_depth').first()
    if source is None:
        source=SourceRegistry(source_name='twse_mis_quote_depth',source_type='api',category='market_data')
        db.add(source);db.flush()
    raw=RawFetchResult(source_id=source.id,fetched_at=received,content_hash=raw_hash,
        parser_version='twse.mis.getStockInfo.v1',raw_text='{"msgArray":[]}')
    db.add(raw);db.flush()
    row=TaiwanStockQuoteSnapshot(source_id=source.id,raw_result_id=raw.id,provider=provider,
        market='TWSE',stock_id=symbol,source=source.source_name,trade_date=DAY,
        quote_time=event,received_at=received,session_phase='opening_auction_delayed',
        market_session='continuous',observation_state='indicative',trade_state='indicative_observed',
        raw_contract_version=raw.parser_version,total_volume_lots=volume)
    db.add(row);db.commit()
    return row


@pytest.mark.parametrize('symbol',['00981A','00631L','2330'])
def test_canonical_repository_service_and_bootstrap_share_opening_proof(monkeypatch,symbol):
    from app.db.models import MarketIntradayBar,StockMaster
    from app.market.tw_bar_service import TaiwanBarService
    from app.market import tw_intraday_platform as platform
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER,KGI_INTRADAY_SOURCE,KGI_INTRADAY_PARSER_VERSION
    from test_tw_bar_service import _db,_seed_session
    db,engine=_db()
    try:
        _seed_session(db,trade_date=DAY,provider=KGI_INTRADAY_PROVIDER,source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,authority='broker',start_minute=2,minutes=3)
        kind='stock' if symbol=='2330' else 'etf'
        for row in db.query(MarketIntradayBar):
            row.stock_id=row.symbol=symbol;row.instrument_type=kind
        master=db.query(StockMaster).filter_by(stock_id='2330').one();master.stock_id=symbol;master.instrument_type=kind
        db.commit()
        seed_quote(db,symbol)
        now=NOW+timedelta(seconds=30)
        result=TaiwanBarService(db).read_current_session_bars(instrument_id=symbol,interval='1m',requested_at=now,
            bypass_snapshot_cache=True)
        assert len(result.bars)==3
        assert result.current_session_coverage.missing_bucket_count==0
        assert result.current_session_coverage.observed_bucket_count==5
        assert result.bucket_coverage[0].status.value=='verified_no_trade'
        captured=[]
        monkeypatch.setattr(platform.MarketDataGateway,'resolve_bars',lambda self,requirement,**kwargs:captured.append(requirement))
        platform.refresh_taiwan_intraday_bars(db,stock_id=symbol,requested_at=now,target_trade_date=DAY)
        assert captured[0].request.coverage.minimum_bar_count==3
    finally:
        db.close();engine.dispose()


@pytest.mark.parametrize('case',['future_receipt','missing_lineage','positive_volume_enum','earlier_positive'])
def test_persisted_opening_evidence_cannot_excuse_unknown(case):
    from app.market.public_quote_repository import TaiwanPublicQuoteRepository
    from test_tw_bar_service import _db
    db,engine=_db()
    try:
        seed_quote(db,'2330',receipt_offset=300 if case=='future_receipt' else 1,
            raw_hash=None if case=='missing_lineage' else 'fixture',volume=1 if case=='positive_volume_enum' else 0)
        if case=='earlier_positive':seed_quote(db,'2330',minute=0,volume=1)
        proof=TaiwanPublicQuoteRepository(db).load_opening_quote_evidence(INSTRUMENT,trade_date=DAY,requested_at=NOW)
        rows,_=coverage(proof,symbol='2330')
        assert rows[0].status.value=='missing_evidence'
    finally:
        db.close();engine.dispose()


def test_invalid_first_positive_cannot_hide_later_valid_positive():
    from app.market.public_quote_repository import TaiwanPublicQuoteRepository
    from test_tw_bar_service import _db
    db,engine=_db()
    try:
        seed_quote(db,'2330',minute=0,volume=1,raw_hash=None)
        seed_quote(db,'2330',minute=1,volume=2)
        seed_quote(db,'2330',minute=2,volume=0)
        proof=TaiwanPublicQuoteRepository(db).load_opening_quote_evidence(INSTRUMENT,trade_date=DAY,requested_at=NOW)
        rows,_=coverage(proof,symbol='2330')
        assert all(row.status.value=='missing_evidence' for row in rows[:2])
    finally:
        db.close();engine.dispose()


def test_opening_receipt_invalidates_same_minute_snapshot():
    from app.market.tw_bar_service import TaiwanBarService
    from test_tw_bar_service import _db,_seed_session
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER,KGI_INTRADAY_SOURCE,KGI_INTRADAY_PARSER_VERSION
    db,engine=_db()
    try:
        _seed_session(db,trade_date=DAY,provider=KGI_INTRADAY_PROVIDER,source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,authority='broker',start_minute=2,minutes=3)
        service=TaiwanBarService(db)
        before=service.read_current_session_bars(instrument_id='2330',requested_at=NOW+timedelta(seconds=10))
        assert before.current_session_coverage.missing_bucket_count==2
        seed_quote(db,'2330')
        after=service.read_current_session_bars(instrument_id='2330',requested_at=NOW+timedelta(seconds=11))
        assert after.current_session_coverage.missing_bucket_count==0
        assert after.current_session_coverage.snapshot_revision!=before.current_session_coverage.snapshot_revision
        assert after.current_session_coverage.snapshot_bar_count==len(after.bars)==3
    finally:
        db.close();engine.dispose()


def test_demand_finishes_original_target_while_new_tail_stays_missing():
    from app.jobs.taiwan_intraday_demand import _reread
    from test_tw_bar_service import _db,_seed_session
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER,KGI_INTRADAY_SOURCE,KGI_INTRADAY_PARSER_VERSION
    db,engine=_db()
    try:
        _seed_session(db,trade_date=DAY,provider=KGI_INTRADAY_PROVIDER,source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,authority='broker',start_minute=0,minutes=5)
        request={'stock_id':'2330','trade_date':DAY.isoformat(),'desired_coverage_end_at':NOW.isoformat()}
        result=_reread(db,request,NOW+timedelta(minutes=1,seconds=10))
        assert result['reread_ready'] is True
        assert result['snapshot_phase']!='ready'
        assert result['current_session_bar_count']==5
        assert result['target_covered_bucket_count']==5
        assert result['latest_tail_missing_bucket_count']==1
    finally:
        db.close();engine.dispose()


def test_demand_full_target_requires_known_market_semantics(monkeypatch):
    from app.jobs.taiwan_intraday_demand import _reread
    from test_tw_bar_service import _db,_seed_session
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER,KGI_INTRADAY_SOURCE,KGI_INTRADAY_PARSER_VERSION
    db,engine=_db()
    try:
        _seed_session(db,trade_date=DAY,provider=KGI_INTRADAY_PROVIDER,source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,authority='broker',start_minute=0,minutes=5)
        monkeypatch.setattr('app.market.tw_bar_service.get_taiwan_disposition_status',
            lambda *a,**k:dict(cache_status='missing',is_active=False))
        request={'stock_id':'2330','trade_date':DAY.isoformat(),'desired_coverage_end_at':NOW.isoformat()}
        result=_reread(db,request,NOW+timedelta(seconds=10))
        assert result['target_covered_bucket_count']==5
        assert result['reread_ready'] is False
    finally:db.close();engine.dispose()


def seed_fugle_quote(db, payload, received):
    from app.db.models import SourceRegistry,RawFetchResult,TaiwanStockQuoteSnapshot
    import json
    from hashlib import sha256
    source=db.query(SourceRegistry).filter_by(source_name='fugle_intraday_quote').first()
    if source is None:
        source=SourceRegistry(source_name='fugle_intraday_quote',source_type='api',category='market_data')
        db.add(source);db.flush()
    raw_text=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    raw=RawFetchResult(source_id=source.id,raw_text=raw_text,content_hash=sha256(raw_text.encode()).hexdigest(),
        parser_version='fugle.http.quote.v1',fetched_at=received)
    db.add(raw);db.flush()
    event=datetime.fromtimestamp(payload['lastTrade']['time']/1000000,timezone.utc).astimezone(NOW.tzinfo)
    row=TaiwanStockQuoteSnapshot(source_id=source.id,raw_result_id=raw.id,provider='fugle_marketdata',
        market='TWSE',stock_id=payload['symbol'],source=source.source_name,trade_date=event.date(),quote_time=event,
        received_at=received.astimezone(timezone.utc),session_phase='intraday',market_session='continuous',observation_state='available',trade_state='trade_observed',
        raw_contract_version=raw.parser_version,last_price=payload['lastTrade']['price'],
        open_price=payload.get('openPrice'),
        last_trade_volume_lots=payload['lastTrade']['size'],total_volume_lots=payload['total']['tradeVolume'])
    db.add(row);db.commit()
    return row


def test_decoded_price_only_does_not_hide_positive_or_opening_role():
    from app.market.public_quote_repository import TaiwanPublicQuoteRepository
    from test_tw_bar_service import _db
    db,engine=_db()
    try:
        at=NOW.replace(minute=0)
        payload=dict(symbol='2330',date=DAY.isoformat(),type='EQUITY',exchange='TWSE',market='TSE',
            lastTrade=dict(time=int(at.timestamp()*1000000),price=100,size=1),
            total=dict(time=0,tradeVolume=1,tradeValue=100000))
        row=seed_fugle_quote(db,payload,at+timedelta(seconds=1))
        repo=TaiwanPublicQuoteRepository(db)
        assert repo._decode_row(INSTRUMENT,row).observation.cumulative_quantity is None
        seed_quote(db,'2330',minute=1,volume=2)
        seed_quote(db,'2330',minute=2,volume=0)
        proof=repo.load_opening_quote_evidence(INSTRUMENT,trade_date=DAY,requested_at=NOW)
        rows,_=coverage(proof,symbol='2330')
        assert all(row.status.value=='missing_evidence' for row in rows[:2])
    finally:db.close();engine.dispose()


@pytest.mark.parametrize('case',['actual','historical_cutoff','wrong_scope','future_open','earlier_positive'])
@pytest.mark.parametrize('symbol,filename,opened,volume',[
    ('00981A','tw_fugle_opening_r4.json','2026-10-29T09:02:00.861081+08:00',32739000),
    ('00631L','tw_fugle_opening_00631l_r4.json','2026-10-29T09:02:00.331186+08:00',None)])
def test_real_persisted_fugle_open_time_proves_only_qualified_prefix(case,symbol,filename,opened,volume):
    from pathlib import Path
    import json
    from app.market.public_quote_repository import TaiwanPublicQuoteRepository
    from test_tw_bar_service import _db
    receipt=json.loads((Path(__file__).parent/'fixtures'/filename).read_text(encoding='utf-8'))
    payload=json.loads(receipt['raw_text'])
    received=datetime.fromisoformat(receipt['fetched_at']).replace(tzinfo=timezone.utc)
    if case=='wrong_scope':payload['market']='ODDLOT'
    if case=='future_open':payload['openTime']=int((received+timedelta(seconds=1)).timestamp()*1000000)
    db,engine=_db()
    try:
        seed_fugle_quote(db,payload,received)
        instrument=INSTRUMENT.model_copy(update={'symbol':symbol})
        at=received-timedelta(seconds=1) if case=='historical_cutoff' else received+timedelta(seconds=1)
        proof=TaiwanPublicQuoteRepository(db).load_opening_quote_evidence(instrument,trade_date=date(2026,10,29),requested_at=at)
        bars=tuple(_bar(m).model_copy(update={'instrument':instrument,
            'start_at':_bar(m).start_at.replace(month=10,day=29),'end_at':_bar(m).end_at.replace(month=10,day=29)})
            for m in ((0,2,4) if case=='earlier_positive' else (2,4)))
        rows=continuous_session_coverage(bars,trade_date=date(2026,10,29),trading_policy_version='fixture',
            as_of=at,instrument=instrument,opening_quote_evidence=proof)
        assert rows[1].status.value==('verified_no_trade' if case=='actual' else 'missing_evidence')
        if case=='actual':
            assert proof[0].first_trade_at.isoformat()==opened
            assert proof[0].cumulative_quantity.value==(volume or payload['total']['tradeVolume']*1000)
    finally:db.close();engine.dispose()
