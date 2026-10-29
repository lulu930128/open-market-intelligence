from datetime import date,datetime,timedelta,timezone
from dataclasses import replace
from types import SimpleNamespace
import inspect
import pytest

from test_us_sector_distribution import db,stock,bar
from app.us_market import service,watchlist_workflows


@pytest.mark.parametrize('same_day_daily,missing_prior',[(False,False),(True,False),(False,True)])
def test_quote_change_uses_exact_prior_session_and_keeps_daily_volume_clock(db,monkeypatch,same_day_daily,missing_prior):
    from app.db.models import USWatchlistGroup,USWatchlistItem
    stock(db,'AAPL')
    bar(db,'AAPL',day=date(2026,10,26),close=100)
    if not missing_prior:bar(db,'AAPL',day=date(2026,10,27),close=110)
    now=datetime(2026,10,29,6,tzinfo=timezone.utc) if same_day_daily else datetime(2026,10,28,15,tzinfo=timezone.utc)
    if same_day_daily:bar(db,'AAPL',day=date(2026,10,28),close=114,received=datetime(2026,10,29,4,5,tzinfo=timezone.utc))
    group=USWatchlistGroup(group_name='R4');db.add(group);db.flush()
    db.add(USWatchlistItem(group_id=group.id,symbol='AAPL',enabled=True,priority=1));db.commit()
    quote_time=datetime(2026,10,28,15,tzinfo=timezone.utc)
    projection={'facts_usable':True,'quote':{'last_trade_price':115,'event_at':quote_time.isoformat()},
        'selected_session':'continuous','selected_provider':'twelve_data','selected_source':'twelve.quote'}
    monkeypatch.setattr(service,'USIntradayMarketPlatform',lambda db:SimpleNamespace(read_quote=lambda **kw:None))
    monkeypatch.setattr(service,'_project_us_quote_temporal_contract',lambda *a,**k:(projection,{'is_live_window':True,'decision_usable':True}))
    overlay=service._get_us_current_quote_overlay('AAPL',db=db,now=now)
    expected=None if missing_prior else 110
    assert overlay['previous_close']==expected
    deps=service._us_watchlist_workflow_dependencies()
    deps=replace(deps,current_quote_overlay_loader=lambda **kw:overlay,
        resolved_daily_batch_loader=lambda **kw:{'AAPL':{'bars':[
            {'start_at':'2026-10-26T09:30:00-04:00','close_price':100,'volume':100},
            {'start_at':'2026-10-27T09:30:00-04:00','close_price':110,'volume':200}],
            'selected_session':'regular','selected_provider':'yahoo_chart','selected_source':'yahoo.daily'}})
    result=watchlist_workflows.get_us_watchlist_ranking(db,dependencies=deps,use_current_quote=True)
    row=result['results'][0]
    assert row['previous_close']==expected
    assert row['change_pct']==(None if missing_prior else pytest.approx(100*5/110))
    assert str(row['price_trade_date'])=='2026-10-28'
    assert str(row['volume_trade_date'])=='2026-10-27'
    assert row['volume']==200 and row['volume_semantics']=='completed_daily'
    from app.us_market.schemas import USWatchlistRankingRead
    serialized=USWatchlistRankingRead.model_validate(result).model_dump(mode='json')['results'][0]
    for field in ('price_trade_date','daily_trade_date','volume_trade_date','volume_semantics','volume_unit',
                  'previous_close_trade_date','previous_close_status'):
        assert field in serialized
    assert serialized['volume_trade_date']=='2026-10-27'


def test_cross_market_compaction_and_selected_capability_preserve_assets():
    from app.ai.market_context.taiwan_market import _build_tw_market_compact
    from app.ai.market_context.tw_cross_market import _market_pack
    from app.ai import capability_contract
    asset={'id':'^GSPC','price':102,'as_of':'2026-10-28','available_at':'2026-10-29T00:01:00Z','status':'current'}
    pack,_=_market_pack(market='us',requested=(('^GSPC','S&P 500'),),assets=[asset])
    cross={'status':'ready','as_of':'2026-10-29T02:00:00Z','markets':{'us':pack},'missing':[],'warnings':[]}
    kwargs={name:{} for name in inspect.signature(_build_tw_market_compact).parameters}
    kwargs.update(as_of=cross['as_of'],latest_trade_date='2026-10-28',payload_level='full',cross_market=cross)
    compact=_build_tw_market_compact(**kwargs)
    selection=capability_contract.normalize_selection(selection={'required':['market.cross_market']},output='evidence_only',
        realtime_policy='cache_only',payload_level='full',scope_type='market',question_intent='general')
    projected,unavailable=capability_contract.project_selected_data(response={'result':{'data':{'compact':compact,'cross_market':cross}}},selection=selection)
    assert 'market.cross_market' not in unavailable
    assert projected['market.cross_market']['markets']['us']['assets']==[asset]


def test_generic_breadth_never_calls_partial_coverage_bullish():
    from app.dispatch.templates import _market_stance
    assert _market_stance(dict(advance_count=500,decline_count=10,total_count=1080,decision_usable=False,coverage_ratio=.47))=='資料不足'


def test_report_labels_formal_current_quote_contract():
    from app.dispatch.templates import _us_source_label
    row=dict(status='current_quote',current_quote_overlay_applied=True,quote_is_live=True,
        selected_session='continuous',selected_provider='twelve_data',selected_source='twelve.quote',trade_date='2026-10-28')
    assert _us_source_label(row)=='盤中 / twelve.quote'
    row['quote_is_live']=False
    assert '非即時' in _us_source_label(row)


def test_explicit_missing_daily_never_borrows_quote_date():
    deps=replace(service._us_watchlist_workflow_dependencies(),expected_daily_price_date=lambda:date(2026,10,28))
    result=watchlist_workflows._us_ranking_freshness([dict(daily_trade_date=None,trade_date=date(2026,10,28),
        time='2026-10-28T20:00:00Z')],1,dependencies=deps)
    assert result['is_current'] is False and result['current_symbol_count']==0


@pytest.mark.parametrize('session,label',[('pre_open','盤前'),('continuous','盤中'),
    ('closing_auction','收盤競價'),('post_close','盤後'),('closed','休市')])
def test_source_label_uses_canonical_session(session,label):
    from app.dispatch.templates import _us_source_label
    result=_us_source_label(dict(current_quote_overlay_applied=True,quote_is_live=True,
        selected_session=session,selected_source='fixture'))
    assert label in result
