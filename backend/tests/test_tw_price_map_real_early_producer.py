"""True producer, canonical receipt reads, checked history, publish and scanner."""
from datetime import date, datetime, timedelta, timezone
import json
import math
import pytest

from sqlalchemy import event, text
from app.db.models import MarketDailyPrice, RawFetchResult, SourceRegistry, StockMaster, TaiwanPriceMapSnapshot
from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
from app.market.price_map_snapshot_repository import read_price_map_external_revision
from app.market.stock_price_map import build_tw_stock_price_map
from app.market.trading_calendar import previous_taiwan_trading_day, TAIWAN_TZ
from app.market.tw_price_map_screening import build_tw_price_map_screening_snapshot
from app.market import tw_corporate_events as events
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME
from test_tw_early_regular_daily import payload, FakeResponse
from test_tw_corporate_required_scope import cache, write, provider
from test_tw_price_map_screening import sessions

DAY=date(2026,11,3)
EARLY=datetime(2026,11,3,14,35,tzinfo=TAIWAN_TZ)
FINAL=datetime(2026,11,3,15,20,tzinfo=TAIWAN_TZ)


def seed_history(db):
    db.add(StockMaster(stock_id='1102',market='TWSE',instrument_type='stock',is_active=True))
    source=SourceRegistry(source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,source_type='api',category='market_data',reliability_level='official')
    db.add(source);db.flush()
    raw=RawFetchResult(source_id=source.id,fetched_at=datetime(2026,11,2,8,tzinfo=timezone.utc),
        status_code=200,content_hash='fixture-history',parser_version='twse_mi_index_allbut0999.v2',raw_text='{}')
    db.add(raw);db.flush()
    dates=[date(2026,11,2)]
    while len(dates)<140:dates.append(previous_taiwan_trading_day(dates[-1],include_value=False))
    for i,day in enumerate(reversed(dates)):
        close=2200+math.sin(i/5)*25+i/2
        db.add(MarketDailyPrice(source_id=source.id,raw_result_id=raw.id,stock_id='1102',trade_date=day,
            open_price=close-2,high_price=close+5,low_price=close-5,close_price=close,trade_volume=1000000+i))
    db.commit()


def acquire(db, now, *, price_delta=0):
    body=payload()
    table=next(t for t in body['tables'] if '證券代號' in t.get('fields',[]))
    table['data']=[next(r for r in table['data'] if r[0]=='2330')]
    table['data'][0][0]='1102'  # Synthetic no-action control, not a claim about 1102 prices.
    for field in ('開盤價','最高價','最低價','收盤價'):
        index=table['fields'].index(field)
        table['data'][0][index]=str(float(str(table['data'][0][index]).replace(',',''))+price_delta)
    return refresh_taiwan_official_daily_venue(db,venue='TWSE',trade_date=DAY,requested_at=now,
        refresh_published=False,max_external_calls=1,acquisition=TaiwanOfficialDailyAcquisitionExecutor(
            fetchers={'MI_INDEX_ALLBUT0999':lambda _:FakeResponse(text=json.dumps(body,ensure_ascii=False))},clock=lambda:now))


def test_real_early_producer_requires_history_refresh_then_final_revision_and_cold_cutoff(sessions,cache,monkeypatch):
    from app.market import tw_price_map_screening as scanner
    yesterday={key:provider(end=DAY-timedelta(days=1)) for key in events.HISTORY_PROVIDER_KEYS}
    for value in yesterday.values():value['fetched_at']=(EARLY-timedelta(days=1)).isoformat()
    # Current forecast is not historical checked evidence.
    write(cache,{**yesterday,'twse_ex_dividend':provider(end=DAY)})
    with sessions() as db:
        seed_history(db);acquire(db,EARLY)
    def produce(now):
        return produce_taiwan_price_map_snapshots(session_factory=sessions,clock=lambda:now,
            stock_ids=('1102',),batch_size=1,time_budget_seconds=45)
    first=produce(EARLY)
    with sessions() as db:
        row=db.get(TaiwanPriceMapSnapshot,('1102','daily'));initial=json.loads(row.payload_json)
        assert row.status=='partial' and not initial['structure_input_usable']
        assert str(initial['reference']['trade_date'])==str(DAY)
        assert initial['corporate_action']['coverage_status']=='partial'
    calls=[]
    def fetch(key,**kwargs):calls.append(key);return []  # Qualified empty official response port.
    events.backfill_taiwan_corporate_event_history(years=1,force=False,now=EARLY,cache_path=cache,fetch_provider=fetch)
    assert 'twse_ex_dividend_history' in calls
    # Coverage advancement alone must invalidate the partial snapshot before retry_after.
    assert produce(EARLY+timedelta(seconds=1))['published']==1
    with sessions() as db:
        row=db.get(TaiwanPriceMapSnapshot,('1102','daily'));early=json.loads(row.payload_json)
        assert row.status in {'ready','empty'} and early['structure_input_usable']
        assert early['reference']['release_status']=='regular_research'
        assert not early['reference']['official_final'] and not early['decision_usable']
        assert early['corporate_action']['coverage_status']=='complete'
        scan=build_tw_price_map_screening_snapshot(db,parameters={'lane':'completed_daily'},generated_at=EARLY+timedelta(seconds=1))
        assert scan['coverage']['current_structure_symbols']==1
        assert scan['coverage']['eligible_symbols']==1
        early_basis=early['basis_revision'];early_input=row.input_revision
        # Identical OHLC, but newly qualified final receipt must change revision.
        acquire(db,FINAL)
    assert produce(FINAL)['published']==1
    with sessions() as db:
        row=db.get(TaiwanPriceMapSnapshot,('1102','daily'));final=json.loads(row.payload_json)
        assert final['reference']['price']==early['reference']['price']
        assert row.input_revision>early_input and final['basis_revision']!=early_basis
        assert final['reference']['official_final'] and final['decision_usable']
        # Late replay of early evidence cannot downgrade the accepted final version.
        acquire(db,EARLY)
        assert build_tw_stock_price_map(db=db,stock_id='1102',now=FINAL)['reference']['official_final']
    assert produce(FINAL+timedelta(seconds=1))['attempted']==0
    # A cold read at early cutoff must not peek at the already-stored final receipt.
    with sessions() as db:
        statements=[]
        event.listen(db.bind,'before_cursor_execute',lambda c,cur,sql,p,ctx,m:statements.append(sql))
        db.execute(text('PRAGMA query_only=ON'))
        cold=build_tw_stock_price_map(db=db,stock_id='1102',now=EARLY)
        assert cold['reference']['release_status']=='regular_research' and not cold['reference']['official_final']
        assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements)


def test_research_mode_keeps_a_real_required_history_gap_partial(sessions,cache):
    with sessions() as db:
        seed_history(db)
        # Fixture starts with a missing required session; no publication exists yet.
        victim=db.query(MarketDailyPrice).filter_by(stock_id='1102').order_by(MarketDailyPrice.trade_date.desc()).offset(5).first()
        assert victim is not None
        db.delete(victim)
        db.commit()
        acquire(db,EARLY)
    events.backfill_taiwan_corporate_event_history(years=1,force=True,now=EARLY,cache_path=cache,
        fetch_provider=lambda *a,**k:[])
    result=produce_taiwan_price_map_snapshots(session_factory=sessions,clock=lambda:EARLY,
        stock_ids=('1102',),batch_size=1,time_budget_seconds=45)
    assert result['published']==1
    with sessions() as db:
        assert db.get(TaiwanPriceMapSnapshot,('1102','daily')).status=='partial'
        rejected=build_tw_price_map_screening_snapshot(db,parameters={'lane':'completed_daily'},generated_at=EARLY)
        assert rejected['coverage']['eligible_symbols']==0


def test_cold_early_cutoff_cannot_relabel_a_different_future_final_price(sessions,cache):
    with sessions() as db:
        seed_history(db)
        acquire(db,EARLY)
        acquire(db,FINAL,price_delta=100)
        final=build_tw_stock_price_map(db=db,stock_id='1102',now=FINAL)
        assert final['reference']['price']==2395 and final['reference']['official_final']
    with sessions() as db:
        db.execute(text('PRAGMA query_only=ON'))
        cold=build_tw_stock_price_map(db=db,stock_id='1102',now=EARLY)
        assert cold['reference']['price']==2295
        assert cold['reference']['price']!=final['reference']['price']
        assert cold['reference']['release_status']=='regular_research' and not cold['reference']['official_final']
        summaries=json.dumps(cold['technical']['evidence_summary'],ensure_ascii=False)
        assert '2,295' in summaries and '2,395' not in summaries


@pytest.mark.parametrize('defect',['missing_ohlc','raw_error'])
def test_legacy_invalid_final_does_not_block_valid_early_repair(sessions,cache,defect):
    with sessions() as db:
        seed_history(db)
        source=db.query(SourceRegistry).filter_by(source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME).one()
        bad_raw=RawFetchResult(source_id=source.id,fetched_at=FINAL.astimezone(timezone.utc),status_code=200,
            parser_version='twse_mi_index_allbut0999.v2',content_hash='invalid-final',raw_text='{}',
            error_message='legacy parse error' if defect=='raw_error' else None)
        db.add(bad_raw);db.flush()
        row=MarketDailyPrice(source_id=source.id,raw_result_id=bad_raw.id,stock_id='1102',trade_date=DAY,
            canonical_market='TW',venue='TWSE',instrument_type='stock',authority='exchange',official=True,
            finalization='final',release_status='released',open_price=None if defect=='missing_ohlc' else 2390,
            high_price=2400,low_price=2380,close_price=None if defect=='missing_ohlc' else 2395,
            trade_volume=1000,trade_value=2395000,transaction_count=10)
        db.add(row);db.commit()
        result=acquire(db,EARLY)
        db.refresh(row)
        assert row.close_price==2295 and row.open_price is not None
        assert row.release_status=='regular_research' and row.raw_result_id!=bad_raw.id
        assert result['inserted_count']==1 and db.get(RawFetchResult,bad_raw.id) is not None


def test_qualified_final_v1_is_not_downgraded_by_late_early_v2(sessions,cache):
    from app.db.models import TaiwanTechnicalInputRevision
    from app.market.daily_ohlcv_platform import read_taiwan_official_daily
    with sessions() as db:
        seed_history(db)
        source=db.query(SourceRegistry).filter_by(source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME).one()
        final_raw=RawFetchResult(source_id=source.id,fetched_at=FINAL.astimezone(timezone.utc),status_code=200,
            parser_version='twse_mi_index_allbut0999.v1',content_hash='qualified-final-v1',raw_text='{}')
        db.add(final_raw);db.flush()
        row=MarketDailyPrice(source_id=source.id,raw_result_id=final_raw.id,stock_id='1102',trade_date=DAY,
            canonical_market='TW',venue='TWSE',instrument_type='stock',authority='exchange',official=True,
            finalization='final',release_status='released',open_price=2390,high_price=2400,low_price=2380,
            close_price=2395,trade_volume=1000,trade_value=2395000,transaction_count=10)
        db.add(row);db.commit()
        # Establish qualification through the normal owner, not a fabricated boolean.
        final=read_taiwan_official_daily(db,stock_id='1102',from_date=DAY,to_date=DAY,requested_at=FINAL)
        assert final.resolved.bars[0].close_price==2395
        generation=db.get(TaiwanTechnicalInputRevision,'1102').generation
        result=acquire(db,EARLY)
        db.refresh(row)
        assert row.raw_result_id==final_raw.id and row.release_status=='released'
        assert (row.open_price,row.high_price,row.low_price,row.close_price)==(2390,2400,2380,2395)
        assert db.get(TaiwanTechnicalInputRevision,'1102',populate_existing=True).generation==generation
        assert result['inserted_count']==0 and result['unchanged_observation_count']==1
