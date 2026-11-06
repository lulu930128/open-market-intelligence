"""Required event evidence, provider checked windows and semantic dependencies."""
from datetime import date, datetime, timedelta, timezone
import json
from copy import deepcopy

import pytest
from app.config import settings
from app.market import tw_corporate_events as owner
from app.market.providers.tw_corporate_events import MopsConferenceBatch
from app.market.technical_evidence import build_corporate_action_contract

NOW = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
DAY = NOW.date()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path/'events.json'
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', path)
    monkeypatch.setattr('socket.socket.connect', lambda *a, **k: pytest.fail('external I/O'))
    owner.invalidate_taiwan_corporate_event_cache()
    yield path
    owner.invalidate_taiwan_corporate_event_cache()


def provider(end=DAY, **extra):
    return {'fetched_at': NOW.isoformat(), 'coverage_start':'2017-01-01',
            'coverage_end':str(end), 'entries':[], **extra}


def write(path, providers):
    path.write_text(json.dumps({'schema_version':1, 'providers':providers}),encoding='utf-8')
    owner.invalidate_taiwan_corporate_event_cache()


def action_history(path):
    return owner.get_taiwan_stock_event_history('1102',market='TWSE',years=10,max_results=200,
        event_types={'ex_dividend'}, now=NOW,cache_path=path)


@pytest.mark.parametrize('degraded', [True, False])
def test_required_exdiv_scope_is_not_blocked_or_extended_by_mops(cache, degraded):
    write(cache, {'twse_ex_dividend_history':provider(end=DAY if degraded else DAY-timedelta(days=1)),
        'mops_conference_history':provider(last_error='fixture failed' if degraded else None)})
    history=action_history(cache)
    contract=build_corporate_action_contract(history,analysis_start=date(2026,1,1),analysis_end=DAY)
    assert contract['coverage_status']==('complete' if degraded else 'partial')
    assert set(history['sources'])=={'twse_ex_dividend_history'}
    generic=owner.get_taiwan_stock_event_history('1102',market='TWSE',now=NOW,cache_path=cache)
    assert generic['cache_status']==('degraded' if degraded else 'current')
    assert generic['coverage_end']==(DAY if degraded else DAY-timedelta(days=1))


def test_filter_precedes_limit_and_truncated_absence_is_not_complete(cache):
    events=[{'event_id':str(i),'stock_id':'1102','market':'TWSE','event_type':'investor_conference',
             'start_date':'2026-10-01','end_date':'2026-10-01','title':str(i)} for i in range(250)]
    exdiv={'event_id':'exdiv','stock_id':'1102','market':'TWSE','event_type':'ex_dividend',
           'start_date':'2026-09-16','end_date':'2026-09-16','title':'exdiv'}
    write(cache,{'twse_ex_dividend_history':provider(entries=[exdiv]),
                'mops_conference_history':provider(entries=events)})
    history=action_history(cache)
    assert history['results']==[owner._public_event(exdiv,as_of=DAY)]
    contract=build_corporate_action_contract(history,analysis_start=date(2026,8,1),analysis_end=DAY)
    assert contract['affected_dates']==['2026-09-16'] and not contract['adjustment_applied']
    truncated={**history,'total_count':201,'returned_count':200,'results':[]}
    assert build_corporate_action_contract(truncated,analysis_start=date(2026,1,1),analysis_end=DAY)['coverage_status']=='partial'


def test_price_map_revision_ignores_mops_but_keeps_required_evidence(cache):
    from app.market.price_map_snapshot_repository import read_price_map_external_revision
    providers={'twse_ex_dividend_history':provider(),'mops_conference_history':provider()}
    write(cache,providers);before=read_price_map_external_revision()
    providers['mops_conference_history']=provider(entries=[{'event_id':'mops','start_date':'2026-10-01'}])
    write(cache,providers);assert read_price_map_external_revision()==before
    providers['twse_ex_dividend_history']['coverage_end']='2026-11-03'
    write(cache,providers);assert read_price_map_external_revision()!=before


@pytest.mark.parametrize('types',[{'unrecognized'},{'ex_dividend','unrecognized'}])
def test_unknown_type_and_exdiv_do_not_prove_price_basis_or_unknown_absence(cache,types):
    from app.market_data.contracts import InstrumentKey
    write(cache,{'twse_ex_dividend_history':provider()})
    history=owner.get_taiwan_stock_event_history('1102',market='TWSE',now=NOW,cache_path=cache,event_types=types)
    assert history['cache_status']=='missing' and history['uncovered_event_types']==['unrecognized']
    assert build_corporate_action_contract(history,analysis_start=date(2026,1,1),analysis_end=DAY)['coverage_status']=='missing'
    evidence=owner.read_taiwan_instrument_event_evidence(instrument=InstrumentKey(
        market='TW',venue='TWSE',symbol='1102',instrument_type='stock'),available_at=NOW,path=cache)
    basis=owner.resolve_taiwan_price_basis(evidence,prior_date=DAY-timedelta(days=1),trade_date=DAY)
    assert basis.status=='unknown'  # Ex-div history does not qualify lifecycle/price-basis windows.


def test_writer_respects_declared_range_and_revalidates_legacy_overclaim(cache):
    # Old version declared every provider checked through today. No version tag.
    write(cache,{key:provider() for key in owner.HISTORY_PROVIDER_KEYS})
    calls=[]
    def fetch(key, **kwargs):
        calls.append((key,kwargs['year']))
        if key=='mops_conference_history':
            return MopsConferenceBatch(entries=[],request_count=2,errors=[],
                coverage_start=date(kwargs['year'],1,1),coverage_end=DAY-timedelta(days=1))
        return []
    owner.backfill_taiwan_corporate_event_history(years=1,force=False,now=NOW,cache_path=cache,fetch_provider=fetch)
    assert ('mops_conference_history',2026) in calls
    stored=owner.read_taiwan_corporate_event_cache(path=cache)['providers']
    assert stored['mops_conference_history']['coverage_end']=='2026-11-03'
    assert not stored['mops_conference_history']['entries']
    assert stored['twse_ex_dividend_history']['coverage_end']=='2026-11-04'
    before=len(calls)
    owner.backfill_taiwan_corporate_event_history(years=1,force=False,now=NOW,cache_path=cache,fetch_provider=fetch)
    assert len(calls)==before  # Per-provider checked targets, not today's fabricated MOPS range.


def test_same_history_scheduler_owns_early_final_and_configured_opportunities(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs import scheduler
    from app.market.trading_calendar import TAIWAN_TZ
    monkeypatch.setattr(settings,'enable_tw_corporate_event_scheduler',True)
    jobs=BackgroundScheduler(timezone=TAIWAN_TZ)
    assert scheduler._add_taiwan_corporate_event_history_refresh_job(jobs)
    job=jobs.get_job('taiwan_corporate_event_history_refresh')
    assert len(jobs.get_jobs())==1 and job.func is scheduler.refresh_taiwan_corporate_event_history
    assert job.max_instances==1 and job.coalesce
    tick=datetime(2026,11,4,14,31,tzinfo=TAIWAN_TZ)
    first=job.trigger.get_next_fire_time(None,tick)
    second=job.trigger.get_next_fire_time(first,first+timedelta(seconds=1))
    third=job.trigger.get_next_fire_time(second,second+timedelta(seconds=1))
    assert [x.strftime('%H:%M') for x in (first,second,third)]==['14:35','15:20',settings.scheduler_tw_corporate_event_history_refresh_time]


def test_cold_new_year_writer_checks_only_completed_year(cache):
    calls=[]
    def fetch(key,**kwargs):
        calls.append((key,kwargs['year'],kwargs['date_from'],kwargs['date_to']))
        return []  # Qualified empty is a successful checked historical window.
    result=owner.backfill_taiwan_corporate_event_history(years=1,force=True,
        now=datetime(2027,1,1,tzinfo=timezone.utc),cache_path=cache,fetch_provider=fetch)
    assert result['error_count']==0 and len(calls)==len(owner.HISTORY_PROVIDER_KEYS)
    assert all(year==2026 and start==date(2026,1,1) and end==date(2026,12,31) for _,year,start,end in calls)
    stored=owner.read_taiwan_corporate_event_cache(path=cache)['providers']
    assert all(entry['coverage_years']==[2026] and entry['coverage_end']=='2026-12-31' for entry in stored.values())


def test_writer_failure_year_only_blocks_the_requested_scope(cache):
    def fetch(key,**kwargs):
        if key=='twse_ex_dividend_history' and kwargs['year']==2023:
            raise TimeoutError('2023 fixture timeout')
        return []
    owner.backfill_taiwan_corporate_event_history(years=5,force=True,now=NOW,cache_path=cache,fetch_provider=fetch)
    current=owner.get_taiwan_stock_event_history('1102',market='TWSE',event_types={'ex_dividend'},
        date_from=date(2026,1,1),date_to=DAY,now=NOW,cache_path=cache)
    assert current['cache_status']=='current'
    assert build_corporate_action_contract(current,analysis_start=date(2026,1,1),analysis_end=DAY)['coverage_status']=='complete'
    broad=owner.get_taiwan_stock_event_history('1102',market='TWSE',event_types={'ex_dividend'},
        date_from=date(2023,1,1),date_to=DAY,now=NOW,cache_path=cache)
    assert broad['cache_status']=='degraded'
    providers=owner.read_taiwan_corporate_event_cache(path=cache)['providers']
    entry=providers['twse_ex_dividend_history']
    assert entry['failed_years']==[2023] and 'TWSE:2026' in entry['successful_windows']
    # An old/unknown failure scope must remain conservative.
    entry['last_failure_details'][0]['window']='all'
    write(cache,providers)
    assert action_history(cache)['cache_status']=='degraded'
