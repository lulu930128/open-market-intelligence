"""KR AI completed evidence shares the market calendar cutoff before SQL limits."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch
import pytest
from sqlalchemy import event
from app.ai import ask, agentic_tools
from app.ai.schemas import AiAskRequest
from app.ai.market_context import kr_context
from app.config import settings
from app.db.models import KRDailyPrice, KRStockMaster
from app.kr_market import service
from app.kr_market.trading_calendar import expected_kr_daily_price_date, previous_kr_trading_day
from test_resource_ask_refresh import db  # noqa: F401

@pytest.mark.parametrize('now,historical,only_partial', [
    (datetime(2026,10,28,4,tzinfo=timezone.utc),None,False),
    (datetime(2026,10,25,4,tzinfo=timezone.utc),None,False),
    (datetime(2026,10,9,4,tzinfo=timezone.utc),None,False),
    (datetime(2026,10,28,4,tzinfo=timezone.utc),'2026-10-23',False),
    (datetime(2026,10,28,4,tzinfo=timezone.utc),None,True),
])
def test_public_kr_completed_rows_chart_and_quote_share_cutoff(db, monkeypatch, now, historical, only_partial):
    monkeypatch.setattr(settings,'kr_canonical_daily_enabled',False)
    monkeypatch.setattr(agentic_tools,'_now',lambda:now)
    monkeypatch.setattr(ask.portfolio_service,'get_position_context_for_scope',Mock(return_value=None))
    expected = previous_kr_trading_day(date.fromisoformat(historical),include_value=True) if historical else expected_kr_daily_price_date(now=now)
    completed = [expected]
    for _ in range(2): completed.append(previous_kr_trading_day(completed[-1]))
    db.add(KRStockMaster(symbol='005930.KS',local_code='005930',security_name='fixture',market_segment='KOSPI',asset_type='stock'))
    days = [now.date()] if only_partial else [now.date(), *completed]
    for day in days:
        db.add(KRDailyPrice(provider='yahoo_chart',symbol='005930.KS',trade_date=day,currency='KRW',
            open_price=100, high_price=102, low_price=99, close_price=101, trade_volume=1000,
            fetched_at=now, source_url='https://example.invalid/fixture'))
    db.commit()
    writes=[]
    def observe(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')): writes.append(statement)
    event.listen(db.get_bind(),'before_cursor_execute',observe)
    captured=[]
    original=kr_context.read_kr_stock_context
    def capture(*args,**kwargs):
        result=original(*args,**kwargs); captured.append(result);return result
    with patch.object(kr_context,'read_kr_stock_context',side_effect=capture), \
         patch.object(service,'fetch_yahoo_chart_payload',side_effect=AssertionError('network forbidden')), \
         patch.object(service,'fetch_krx_daily_price_payload',side_effect=AssertionError('network forbidden')):
        result=ask.ask(db,AiAskRequest(contract_version='omi.decision.v4',question='005930.KS completed daily evidence',
            target={'type':'kr_stock','id':'005930.KS'},mode='data_only',output='evidence_only',
            realtime_policy='cache_only',allow_external_fetch=False,allow_write=False,allow_llm=False,
            refresh_policy={'mode':'off','before_answer':False}, market_data_params={'trade_date':historical} if historical else {},
            selection={'include':['daily.ohlcv'],'limits':{'daily.ohlcv':3},'max_response_bytes':200000},
            tool_budget={'max_calls':2,'max_external_fetches':0,'max_total_seconds':20}))
    data=captured[0]['data']; chart=data['chart']
    assert all(row['trade_date'] <= expected.isoformat() for row in data['daily_prices'])
    assert chart['expected_data_date']==expected.isoformat()
    assert chart['latest_data_date']==(None if only_partial else expected.isoformat())
    assert captured[0]['summary']['latest_trade_date']==(None if only_partial else expected.isoformat())
    points=result['evidence']['data'].get('daily.ohlcv',{}).get('points',[])
    if only_partial:
        assert not points and not chart['points'] and not data['daily_prices']
    else:
        assert [point['time'] for point in points]==[day.isoformat() for day in reversed(completed)]
        assert chart['freshness_status']=='current'
        assert result['evidence']['quality']['capabilities']['daily.ohlcv']['facts_usable'] is True
        assert all(row['provider']=='yahoo_chart' for row in data['daily_prices'])
    assert writes==[] and result['execution']['tool_runs']==[]
