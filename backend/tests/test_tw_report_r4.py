"""R4 report temporal regressions through persisted canonical daily evidence."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.ai.market_context.tw_cross_market import _us_daily_asset
from app.dispatch.market_report_phase import select_phase_preview
from app.us_market.trading_calendar import previous_us_trading_day, us_session_close_time
from test_us_sector_distribution import bar as storage_bar

ET = ZoneInfo('America/New_York')
TW = ZoneInfo('Asia/Taipei')


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def bar(db, symbol, **kwargs):
    if kwargs.get('received') is not None:
        kwargs['received'] = kwargs['received'].astimezone(timezone.utc)
    return storage_bar(db, symbol, volume=None, volume_unit=None, volume_status='not_applicable', **kwargs)


def selected(asset, now):
    preview = {'metadata': {'cross_market': {'markets': {'us': {
        'status': 'ready', 'available_count': 1, 'assets': [asset]}}}}}
    return select_phase_preview(preview, phase='intraday', now=now,
        daily_cap=now.date()-timedelta(days=1))['metadata']['cross_market']['markets']['us']


@pytest.mark.parametrize('day,report_day,close_hour', [
    (date(2026,10,28),date(2026,10,29),16),
    (date(2026,10,23),date(2026,10,26),16),
    (date(2026,7,2),date(2026,7,6),16),  # July 3 observed holiday
    (date(2026,3,6),date(2026,3,9),16),  # DST weekend
    (date(2026,10,30),date(2026,11,2),16),
    (date(2026,11,27),date(2026,11,30),13),
])
def test_us_completed_session_survives_tw_report(db, day, report_day, close_hour):
    # Yahoo historical receipt must actually exist by the report cutoff. A
    # 10:40 TW report cannot use a receipt from the next NY calendar day yet.
    now = datetime.combine(report_day,time(13,40),TW)
    received = datetime.combine(day+timedelta(days=1),time(0,5),ET)
    prior = previous_us_trading_day(day, include_value=False)
    bar(db,'^GSPC',day=prior,close=100)
    bar(db,'^GSPC',day=day,close=102,received=received)
    db.commit()
    asset = _us_daily_asset(db,symbol='^GSPC',label='S&P 500',now=now)
    assert asset is not None
    assert asset['as_of'] == asset['trade_date'] == day.isoformat()
    assert asset['status'] == 'current'
    assert asset['change_pct'] == pytest.approx(2)
    assert datetime.fromisoformat(asset['available_at']) == received
    assert datetime.fromisoformat(asset['session_end_at']).astimezone(ET).hour == close_hour
    assert selected(asset,now)['assets'] == [asset]


@pytest.mark.parametrize('kind', ['future_receipt','same_day_vendor','provisional'])
def test_unavailable_us_daily_cannot_enter_report(db,kind):
    day=date(2026,10,28);now=datetime(2026,10,29,10,40,tzinfo=TW)
    if kind in {'future_receipt','provisional'}:now=now.replace(hour=13)
    received = now+timedelta(minutes=1) if kind=='future_receipt' else (
        datetime(2026,10,28,16,10,tzinfo=ET) if kind=='same_day_vendor' else
        datetime(2026,10,29,0,5,tzinfo=ET))
    bar(db,'^GSPC',day=day,received=received,
        finalization='provisional' if kind=='provisional' else 'final')
    db.commit()
    assert _us_daily_asset(db,symbol='^GSPC',label='S&P 500',now=now) is None


def test_old_daily_keeps_stale_and_missing_comparison(db):
    now=datetime(2026,10,29,10,40,tzinfo=TW)
    bar(db,'^GSPC',day=date(2026,10,23))
    db.commit()
    asset=_us_daily_asset(db,symbol='^GSPC',label='S&P 500',now=now)
    assert asset['status']=='stale' and asset['change_pct'] is None
    assert asset['expected_trade_date']=='2026-10-28'
    assert selected(asset,now)['assets'][0]['status']=='stale'


def test_date_without_availability_and_future_availability_stay_excluded():
    now=datetime(2026,10,29,10,40,tzinfo=TW)
    asset={'id':'^GSPC','as_of':'2026-10-28','trade_date':'2026-10-28','price':100}
    assert selected(asset,now)['assets']==[]
    assert selected(asset,now)['available_count']==0
    assert selected(asset,now)['status']=='missing'
    asset['available_at']=(now+timedelta(seconds=1)).isoformat()
    assert selected(asset,now)['assets']==[]


def test_overnight_change_requires_exact_previous_session(db):
    now=datetime(2026,10,29,13,40,tzinfo=TW)
    bar(db,'^GSPC',day=date(2026,10,23),close=90)
    bar(db,'^GSPC',day=date(2026,10,28),close=102,received=datetime(2026,10,29,0,5,tzinfo=ET))
    db.commit()
    asset=_us_daily_asset(db,symbol='^GSPC',label='S&P 500',now=now)
    assert asset['price']==102 and asset['change_pct'] is None
    assert asset['change_reason']=='EXACT_PREVIOUS_COMPLETED_SESSION_MISSING'


@pytest.mark.parametrize('day,report_day,hour,case',[
    (date(2026,10,28),date(2026,10,29),8,'complete'),
    (date(2026,10,28),date(2026,10,29),10,'complete'),
    (date(2026,11,27),date(2026,11,30),8,'complete'),
    (date(2026,3,6),date(2026,3,9),8,'complete'),
    (date(2026,10,28),date(2026,10,29),8,'future_interior'),
    (date(2026,10,28),date(2026,10,29),8,'provisional_interior'),
    (date(2026,10,28),date(2026,10,29),8,'missing_prior'),
])
def test_early_tw_report_uses_complete_regular_interval_owner(db,day,report_day,hour,case):
    from test_us_intraday_shared_core import _yahoo_bars_payload
    from test_us_sector_distribution import stock
    from app.us_market.intraday_platform import USIntradayMarketPlatform
    from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
    from app.us_market.market_data.descriptors import YAHOO_INTRADAY_RESOURCE_ID
    from app.db.models import MarketIntradayBar,MarketIntradayBarLineage,RawFetchResult
    stock(db,'AAPL')
    close=datetime.combine(day,us_session_close_time(day),ET)
    opening=datetime.combine(day,time(9,30),ET)
    count=int((close-opening).total_seconds()/60)
    receipt=close+timedelta(seconds=30)
    now=datetime.combine(report_day,time(hour,55 if hour==8 else 0),TW)
    payload=_yahoo_bars_payload(close,count=count)
    platform=USIntradayMarketPlatform(db,acquisition=USIntradayAcquisitionExecutor(
        fetchers={YAHOO_INTRADAY_RESOURCE_ID:lambda *a:(payload,'https://example.invalid/replay')},clock=lambda:receipt))
    acquired=platform.refresh_intraday_bars(symbol='AAPL',bars=1000,now=receipt,max_provider_calls=1)
    assert acquired.result.persistence.committed
    assert db.query(MarketIntradayBar).count()==count
    if case=='future_interior':
        interior=db.query(MarketIntradayBar).order_by(MarketIntradayBar.bar_time).offset(5).first()
        lineage=db.query(MarketIntradayBarLineage).filter_by(bar_id=interior.id).one()
        # Only the interior support has a later correction receipt; the last
        # bar remains early. Checking the last receipt alone would leak it.
        lineage.received_at=(now+timedelta(seconds=1)).astimezone(timezone.utc)
    if case=='provisional_interior':
        interior=db.query(MarketIntradayBar).order_by(MarketIntradayBar.bar_time).offset(5).first()
        db.query(MarketIntradayBarLineage).filter_by(bar_id=interior.id).one().finalization='provisional'
    if case!='missing_prior':
        storage_bar(db,'AAPL',day=previous_us_trading_day(day,include_value=False),close=198)
    db.commit()
    asset=_us_daily_asset(db,symbol='AAPL',label='Apple',now=now)
    if case in {'future_interior','provisional_interior'}:
        assert asset is None or asset['trade_date']!=day.isoformat()
    else:
        assert asset['trade_date']==day.isoformat()
        assert asset['status']=='provisional'
        assert asset['evidence_kind']=='finalized_regular_interval_close'
        assert asset['display_usable'] and not asset['research_usable']
        assert asset['official_close_proof']=='none'
        assert asset['price']==pytest.approx(200+(count-1)/100+.5)
        assert (asset['change_pct'] is None)==(case=='missing_prior')
        assert selected(asset,now)['assets']==[asset]
        if hour==8:
            from app.dispatch.market_report_presentation import build_presentation,phase_report_lines
            from app.dispatch.market_report_chart import render_market_dashboard_chart
            preview={'metadata':{'cross_market':{'markets':{'us':{'status':'partial','assets':[asset]}}}}}
            model=build_presentation(preview,phase='preopen',report_date=report_day)
            assert model.cross_market_strip['promoted'][0]['status']=='provisional'
            text='\n'.join(phase_report_lines(model))
            assert '隔夜美股基準 unavailable' not in text
            assert '非官方' in text and '日線修訂待確認' in text
            assert render_market_dashboard_chart(model).startswith(b'\x89PNG')


@pytest.mark.parametrize('historical',[False,True])
def test_us_refresh_receipt_after_start_survives_command_but_not_asof(db,historical):
    from test_us_intraday_shared_core import _yahoo_bars_payload
    from test_us_sector_distribution import stock
    from app.us_market.intraday_platform import USIntradayMarketPlatform
    from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
    from app.us_market.market_data.descriptors import YAHOO_INTRADAY_RESOURCE_ID
    stock(db,'AAPL')
    close=datetime(2026,10,28,16,tzinfo=ET)
    start=close+timedelta(minutes=1) if historical else close-timedelta(minutes=1)
    payload=_yahoo_bars_payload(close if historical else start,count=390 if historical else 20)
    platform=USIntradayMarketPlatform(db,acquisition=USIntradayAcquisitionExecutor(
        fetchers={YAHOO_INTRADAY_RESOURCE_ID:lambda *a:(payload,'https://example.invalid/receipt')},
        clock=lambda:start+timedelta(seconds=1)))
    result=platform.refresh_intraday_bars(symbol='AAPL',bars=1000,now=start,max_provider_calls=1,
        **({'trade_date':close.date()} if historical else {}))
    assert result.result.persistence.committed
    assert result.projection['bars']
    if historical:assert result.postcondition_satisfied
    old=platform.read_intraday_bars_for_trade_date(symbol='AAPL',trade_date=close.date(),now=start,bars=1000)
    assert not old.result.resolved.bars
