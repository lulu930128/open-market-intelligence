"""Real stock event mapper -> selected projection -> capability manifest."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from app.ai import capability_contract as contract
from app.ai.market_context.taiwan_events import build_tw_stock_event_context


@pytest.mark.parametrize('capability,sort_order', [('events.history','desc'),('events.upcoming','asc')])
@pytest.mark.parametrize('count,limit,total', [(20,5,103),(20,1,103),(3,5,103),(5,5,5),(0,5,0)])
def test_event_page_order_counts_and_manifest(capability,sort_order,count,limit,total):
    now=datetime(2026,11,4,tzinfo=timezone.utc)
    rows=[{'event_id':str(i),'start_date':(now+timedelta(days=i+1) if sort_order=='asc'
        else now-timedelta(days=i+1)).date().isoformat(),'event_type':'ex_dividend'} for i in range(count)]
    offset=7 if total==103 else 0
    source={'results':rows,'cache_status':'current','returned_count':count,'total_count':total,
            'offset':offset,'sort_order':sort_order,'stock_id':'1102'}
    original=deepcopy(source)
    context=build_tw_stock_event_context(stock_id='1102',market='TWSE',now=now,
        market_data_params={'requested_capabilities':[capability]},
        get_event_history=lambda *a,**k:source, get_event_summary=lambda *a,**k:source,
        get_disposition_status=lambda *a,**k:{})
    # Match the actual legacy outward envelope; projection owns the requested limit.
    raw=context['data'][capability]
    response={'result':{'data':{'events':{capability.split('.')[1]:raw}}}}
    selection=contract.normalize_selection(selection={'required':[capability],'limits':{capability:limit}},
        output='evidence_only',realtime_policy='cache_only',payload_level='full',scope_type='stock',question_intent='general')
    projected,missing=contract.project_selected_data(response=response,selection=selection)
    assert capability not in missing
    item=projected[capability]
    assert item['events']==rows[:limit]
    assert item['returned_count']==item['result_count']==min(count,limit)
    assert item['total_count']==total and item['offset']==offset and item['sort_order']==sort_order
    assert item['truncated']==(total>min(count,limit))
    manifest=contract.build_manifest(canonical={'target':{'type':'tw_stock'},'evidence':{'data':projected}},
        selection=selection,projected_data=projected)
    entry=next(x for x in manifest['capabilities'] if x['capability']==capability)
    assert entry['returned_count']==min(count,limit) and entry['canonical_available_count']==total
    assert entry['truncated']==item['truncated']
    assert source==original and raw['events']==rows


def test_chronological_series_still_projects_latest_tail():
    assert contract._bounded_value(list(range(20)),limit=5)==[15,16,17,18,19]
