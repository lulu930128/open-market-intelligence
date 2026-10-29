from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest

NOW=datetime(2026,9,1,9,5,30,tzinfo=ZoneInfo('Asia/Taipei'))


@pytest.mark.parametrize('case',['hole','opening_no_trade','forming'])
def test_derived_point_quality_and_live_fill_use_base_coverage(case):
    from test_tw_bar_service import _db,_seed_session
    from test_tw_opening_coverage_r4 import seed_quote
    from app.db.models import MarketIntradayBar
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER,KGI_INTRADAY_SOURCE,KGI_INTRADAY_PARSER_VERSION
    from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
    from app.ai import capability_contract as contract
    db,engine=_db()
    try:
        count=3 if case=='opening_no_trade' else 2 if case=='forming' else 5
        _seed_session(db,trade_date=NOW.date(),provider=KGI_INTRADAY_PROVIDER,source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,authority='broker',start_minute=2 if case=='opening_no_trade' else 0,minutes=count)
        if case=='hole':
            row=db.query(MarketIntradayBar).filter(MarketIntradayBar.bar_time==NOW.replace(minute=2,second=0).replace(tzinfo=None)).one()
            db.delete(row);db.commit()
        if case=='opening_no_trade':seed_quote(db,'2330')
        now=NOW.replace(minute=2) if case=='forming' else NOW
        for interval in ('1m','5m'):
            series=TaiwanBarService(db).read_current_session_bars(instrument_id='2330',interval=interval,requested_at=now)
            payload=project_taiwan_bar_series(series,session_scope='current_session')
            assert payload['series_coverage']['missing_bucket_count']==(1 if case=='hole' else 0)
            if interval=='5m':
                state=series.bar_states[0];point=payload['points'][0]
                assert point['finalized']==(case!='forming')
                assert point['is_partial']==(case!='opening_no_trade')
                assert point['quality_status']==('ok' if case=='opening_no_trade' else 'partial')
                assert point['indicator_eligible']==state.technical_eligible==(case=='opening_no_trade')
                assert point['source_point_count']==(4 if case=='hole' else count)
                assert point['gap_reason']==('MISSING_BASE_1M_EVIDENCE' if case=='hole' else None)
            canonical={'ok':True,'request_status':'completed','target':{'type':'stock','id':'2330','market':'TW'},
                'evidence':{},'execution':{}}
            selection={'version':'test','required':['intraday.bars'],'optional':[]}
            manifest=contract.build_manifest(canonical=canonical,selection=selection,projected_data={'intraday.bars':payload},
                realtime_assessments={'intraday.bars':{'state':'live','status_class':'ready','facts_usable':True,
                    'decision_usable':False,'refresh_recommended':False,'refresh_possible_now':True}},now=now)
            plan=contract.build_fill_plan(canonical=canonical,selection=selection,manifest=manifest,scope_type='stock')
            assert manifest['capabilities'][0]['fill_state']['satisfied']==(case!='hole')
            assert plan['action_count']==(1 if case=='hole' else 0)
            if case=='hole':
                blocked=contract._historical_intraday_fill_state(scope_type='stock',capability_id='intraday.bars',
                    value=payload,current_state={'status_class':'ready','payload_included':True,'refresh_possible_now':False},now=now)
                assert blocked['satisfied'] is False and blocked['refresh_required'] is True
                assert blocked['refresh_possible_now'] is False
    finally:db.close();engine.dispose()


def test_chart_keeps_completed_technical_prefix_with_forming_tail_and_blocks_hole(monkeypatch):
    from datetime import date, datetime
    from test_tw_bar_service import _db, _seed_session, TAIPEI
    from app.market.tw_chart_service import TaiwanChartService
    from app.market.tw_technical_service import TaiwanTechnicalStatus
    from app.market_data.contracts import BarFinalization
    from app.market.tw_intraday_capabilities import KGI_INTRADAY_PROVIDER, KGI_INTRADAY_SOURCE, KGI_INTRADAY_PARSER_VERSION
    from app.db.models import MarketIntradayBar
    db, engine = _db()
    try:
        monkeypatch.setattr('app.market.tw_bar_service.get_taiwan_disposition_status',
            lambda *a, **k: {'cache_status': 'current', 'is_active': False})
        for day, count in ((date(2026, 8, 31), 265), (date(2026, 9, 1), 137)):
            _seed_session(db, trade_date=day, minutes=count, provider=KGI_INTRADAY_PROVIDER,
                source_name=KGI_INTRADAY_SOURCE, parser_version=KGI_INTRADAY_PARSER_VERSION, authority='broker')
        kwargs = dict(instrument_id='2330', interval='5m',
            from_time=datetime(2026, 8, 31, 9, 0, tzinfo=TAIPEI),
            requested_at=datetime(2026, 9, 1, 11, 17, 30, tzinfo=TAIPEI))
        service = TaiwanChartService(db)
        completed = service.read(**kwargs, include_partial=False)
        forming = service.read(**kwargs, include_partial=True)
        assert len(completed.bars.bars) == len(completed.technical.points) == 80
        assert len(forming.bars.bars) == 81
        assert forming.bars.bar_states[-1].technical_eligible is False
        assert forming.bars.bars[-1].finalization is BarFinalization.PROVISIONAL
        assert all(c.missing_evidence_count == 0 for c in forming.bars.bucket_coverage)
        assert forming.technical.points == completed.technical.points
        assert forming.technical.status is not TaiwanTechnicalStatus.UNAVAILABLE
        assert forming.technical.current_partial is not None
        assert forming.technical.current_partial.point['decision_usable'] is False
        row = db.query(MarketIntradayBar).filter_by(bar_time=datetime(2026, 8, 31, 10, 2)).one()
        db.delete(row); db.commit()
        hole = service.read(**kwargs, include_partial=True)
        assert hole.technical.status is TaiwanTechnicalStatus.UNAVAILABLE
        assert not hole.technical.points
    finally:
        db.close(); engine.dispose()
