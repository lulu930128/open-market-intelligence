"""R3 public quality must preserve interval clocks and market-owned coverage."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.ai import capability_contract
from app.db.models import ResourceOhlcvBar
from app.market import taiwan_market_state as volume
from app.resource_market import service
from app.resource_market.contract import list_resource_instruments
from test_resource_ask_refresh import db, isolated_clock_and_network, NOW, ask  # noqa: F401
from test_ai_implemented_feature_contracts import response_for, public


@pytest.mark.parametrize('limit', [3, 90])
@pytest.mark.parametrize('reverse', [False, True])
def test_resource_latest_clock_and_daily_quality_do_not_depend_on_intraday(db, limit, reverse):
    instrument = list_resource_instruments(symbol='GC')[0]
    values = {name: getattr(instrument, name) for name in (
        'provider', 'exchange', 'symbol', 'provider_symbol', 'name', 'root_folder',
        'group', 'asset_class', 'base_asset', 'quote_asset', 'instrument_type')}
    latest = NOW - timedelta(hours=10)
    for interval in ('1d', '1m'):
        for i in range(95 if interval == '1d' else 3):
            at = latest - timedelta(days=i) if interval == '1d' else NOW - timedelta(days=20, seconds=(48, 60, 76)[i])
            db.add(ResourceOhlcvBar(**values, contract_key=instrument.contract_type,
                interval=interval, bar_time=at, open_price=100, high_price=102,
                low_price=99, close_price=101, volume=0 if i == 0 else None,
                fetched_at=NOW + timedelta(hours=2), source_url='https://example.invalid/fixture'))
    db.commit()
    original = service.list_resource_ohlcv_bars
    def read(*args, **kwargs):
        rows = original(*args, **kwargs)
        return list(reversed(rows)) if reverse else rows
    results = []
    with patch.object(service, 'list_resource_ohlcv_bars', side_effect=read):
        for caps in (['daily.ohlcv'], ['daily.ohlcv', 'intraday.bars']):
            results.append(ask(db, allow_external_fetch=False, realtime_policy='cache_only',
                refresh_policy={'mode': 'off', 'before_answer': False}, payload_level='full',
                market_data_params={'interval':'1m', 'intraday_interval':'1m', 'include_intraday':True},
                selection={'include':caps, 'limits':{'daily.ohlcv':limit, 'intraday.bars':3},
                           'max_response_bytes':450000}))
    for result in results:
        evidence = result['evidence']
        rows = evidence['data']['daily.ohlcv']['bars']
        assert len(rows) == limit
        assert [row['bar_time'] for row in rows] == sorted(row['bar_time'] for row in rows)
        assert rows[-1]['volume'] == 0
        quality = evidence['quality']['capabilities']['daily.ohlcv']
        assert quality['event_time'] == latest.isoformat()
        assert quality['decision_usable'] is False
        assert 'volume_unit_missing' in quality['issues']
        assert quality['freshness'] == 'partial'
        assert result['execution']['tool_runs'] == []
    assert results[0]['evidence']['capability_status']['daily.ohlcv'] == results[1]['evidence']['capability_status']['daily.ohlcv']
    intra = results[1]['evidence']['quality']['capabilities']['intraday.bars']
    assert intra['freshness'] == 'stale'
    assert 'interval_mismatch' in intra['issues'] and 'volume_unit_missing' in intra['issues']


@pytest.mark.parametrize('coverage,current,available', [('partial',None,364948096473), ('missing',None,None), ('complete',0,0)])
def test_volume_public_coverage_is_owner_truth(coverage, current, available):
    response = response_for(['market.volume_state'])
    response['scope'] = {'type':'market', 'market':'TW'}
    response['query_plan']['selection'] = capability_contract.normalize_selection(
        selection={'include':['market.volume_state'], 'max_response_bytes':350000},
        output='evidence_only', realtime_policy='cache_only', payload_level='full',
        scope_type='market', target_market='TW', question_intent='analysis')
    payload = {'kind':'taiwan_market_volume_state', 'status':'partial', 'trade_date':'2026-10-28',
        'as_of':'2026-10-28T13:48:00+08:00', 'comparison_minute':'13:48',
        'trade_value_coverage_status':coverage, 'trade_value_complete':coverage=='complete',
        'current_cumulative_trade_value':current, 'available_cumulative_trade_value':available,
        'currency':'TWD', 'missing_markets':['TPEX'] if coverage=='partial' else [],
        'trade_value_qualification':{'decision_usable':False, 'reason_codes':['OFFICIAL_AUTHORITY_UNVERIFIED']}}
    response['result']['data']['compact']['volume_state'] = deepcopy(payload)
    result = public(response)
    evidence = result['evidence']
    assert evidence['capability_status']['market.volume_state']['coverage_status'] == coverage
    assert evidence['freshness_by_capability']['market.volume_state']['coverage_status'] == coverage
    actual = evidence['data']['market.volume_state']
    for key in ('trade_date','as_of','comparison_minute','trade_value_coverage_status','trade_value_complete','current_cumulative_trade_value','available_cumulative_trade_value','currency','missing_markets','trade_value_qualification'):
        assert actual[key] == payload[key]


@pytest.mark.parametrize('current,official', [(None,True),(120,False),(120,True)])
def test_baseline_wait_is_only_predicted_for_qualified_current(current, official):
    components = [{'market':m, 'scope':'full_market', 'trade_value_semantics':'official_cumulative_trade_value',
        'trade_value_is_estimate':False, 'official_flag':official} for m in ('TWSE','TPEX')]
    state = {'current_cumulative_trade_value':current, 'available_cumulative_trade_value':120,
             'markets':components, 'comparison_minute':'13:48', 'trade_date':'2026-10-28',
             'baseline_readiness_status':'warming_up', 'expected_5d_ready_after_sessions':5,
             'expected_20d_ready_after_sessions':20, 'next_fill':'scheduler_accumulation'}
    for days in (5,20):
        state[f'same_time_baseline_{days}d'] = volume._baseline_payload(current, [], days,
            comparison_minute='13:48', comparison_trade_date='2026-10-28')
    result = volume._qualify_volume_comparisons(state)
    eligible = current is not None and official
    for days in (5,20):
        baseline = result[f'same_time_baseline_{days}d']
        assert baseline['remaining_sample_days'] == days
        assert baseline['expected_ready_after_sessions'] == (days if eligible else None)
        assert baseline['readiness_status'] == ('warming_up' if eligible else 'current_unqualified')
        assert baseline['next_fill'] == ('scheduler_accumulation' if eligible else None)
        assert baseline['pace_ratio'] is None
        assert result[f'expected_{days}d_ready_after_sessions'] == (days if eligible else None)
    assert result['baseline_readiness_status'] == ('warming_up' if eligible else 'current_unqualified')
    assert result['comparison_minute'] == '13:48'
    assert result['current_cumulative_trade_value'] == current


def test_volume_composition_requalifies_same_minute_in_both_directions(db):
    from test_tw_volume_composition import evidence
    original, breadth = evidence()
    original.update(trade_date='2026-09-14', comparison_minute='09:06', markets=[])
    before = volume._qualify_volume_comparisons(original)
    assert before['baseline_readiness_status'] == 'current_unqualified'
    after = volume.compose_taiwan_market_volume_state(before, breadth=breadth)
    assert after['same_time_baseline_5d']['decision_usable'] is True
    assert after['same_time_baseline_5d']['readiness_status'] == 'ready'
    assert after['expected_5d_ready_after_sessions'] == 0
    assert after['same_time_baseline_20d']['readiness_status'] == 'warming_up'
    assert after['expected_20d_ready_after_sessions'] == 20
    assert after['baseline_readiness_status'] == 'warming_up'
    after['markets'][0]['official_flag'] = False
    again = volume.compose_taiwan_market_volume_state(after, breadth=breadth)
    assert again['baseline_readiness_status'] == 'current_unqualified'
    assert again['expected_5d_ready_after_sessions'] is None
    assert again['same_time_baseline_5d']['pace_ratio'] is None
    empty = volume.read_taiwan_market_volume_state(db)
    assert empty['status'] == 'empty'
    assert empty['baseline_readiness_status'] == 'current_unqualified'
    assert empty['expected_5d_ready_after_sessions'] is None
    assert empty['same_time_baseline_5d']['remaining_sample_days'] == 5


def test_actual_minute_reader_requalifies_after_same_minute_breadth_composition(db):
    from datetime import date
    from app.db.models import TaiwanMarketMinuteState
    from test_taiwan_market_state import market_summary_payload
    for day in (7, 8, 9, 10, 11, 14):
        payload = market_summary_payload(date(2026, 9, day), hour=9, minute=6,
                                        twse_trade_value=1000, tpex_trade_value=200)
        volume.persist_taiwan_market_minute_state(db, payload=payload)
    qualified = volume.read_taiwan_market_volume_state(db)
    assert qualified['same_time_baseline_5d']['decision_usable'] is True
    breadth = {'markets': {item['market']: {**item, 'trade_value':item['cumulative_trade_value'],
                           'lineage': {'provider':'twse_mis', 'source':'fixture', 'content_hash':'a'*64,
                                       'raw_receipt_id':f"fixture:{item['market']}", 'event_at':item['as_of']}}
                          for item in qualified['markets']}}
    row = db.query(TaiwanMarketMinuteState).filter_by(trade_date=date(2026,9,14), market='TPEX').one()
    row.cumulative_trade_value = None
    db.commit()
    before = volume.read_taiwan_market_volume_state(db)
    assert before['current_cumulative_trade_value'] is None
    assert before['baseline_readiness_status'] == 'current_unqualified'
    after = volume.compose_taiwan_market_volume_state(before, breadth=breadth)
    assert after['comparison_minute'] == before['comparison_minute'] == '09:06'
    assert after['same_time_baseline_5d']['sample_days'] == 5
    assert after['same_time_baseline_5d']['decision_usable'] is True
    assert after['same_time_baseline_5d']['readiness_status'] == 'ready'
    assert after['expected_5d_ready_after_sessions'] == 0
    assert after['baseline_readiness_status'] == 'warming_up'
    assert after['expected_20d_ready_after_sessions'] == 15
    from app.market.schemas import TaiwanMarketVolumeStateRead
    typed = TaiwanMarketVolumeStateRead.model_validate(after).model_dump(mode='json')
    assert typed['same_time_baseline_5d']['expected_ready_after_sessions'] == 0
    assert typed['same_time_baseline_20d']['remaining_sample_days'] == 15
    assert typed['expected_20d_ready_after_sessions'] == 15
    after['markets'][0]['official_flag'] = False
    reverse = volume.compose_taiwan_market_volume_state(after, breadth=breadth)
    assert reverse['baseline_readiness_status'] == 'current_unqualified'
    assert reverse['expected_5d_ready_after_sessions'] is None


def test_empty_reader_becomes_partial_when_qualified_breadth_arrives(db):
    from test_tw_volume_composition import evidence
    _, breadth = evidence()
    empty = volume.read_taiwan_market_volume_state(db)
    assert empty['status'] == 'empty'
    assert empty['expected_5d_ready_after_sessions'] is None
    assert volume.compose_taiwan_market_volume_state(empty, breadth=None)['status'] == 'empty'
    composed = volume.compose_taiwan_market_volume_state(empty, breadth=breadth)
    assert composed['current_cumulative_trade_value'] == 41_097_867_618
    assert composed['trade_value_complete'] is True
    assert composed['trade_value_qualification']['decision_usable'] is True
    assert composed['status'] == 'partial'  # current exists; comparable history does not
    assert composed['baseline_readiness_status'] == 'warming_up'
    assert composed['expected_5d_ready_after_sessions'] == 5
    assert composed['expected_20d_ready_after_sessions'] == 20
    assert composed['comparison_minute'] == '09:06'
    assert composed['as_of'] == '2026-09-14T09:06:00+08:00'
    assert empty['status'] == 'empty' and empty['current_cumulative_trade_value'] is None


@pytest.mark.parametrize('interval', ['1w', '1M'])
@pytest.mark.parametrize('state', ['stale', 'missing', 'blocked'])
def test_legacy_resource_period_health_is_preserved(interval, state):
    from types import SimpleNamespace
    from app.ai.market_context.resource_context import read_resource_asset_context, ResourceContextDependencies
    deps = ResourceContextDependencies(resource_service=SimpleNamespace(
        list_supported_resource_instruments=lambda **kw: [{'root_folder':'commodity', 'provider':'yahoo_chart'}],
        list_latest_resource_quotes=lambda *a,**kw: [],
        list_resource_ohlcv_bars=lambda *a,**kw: ([SimpleNamespace(bar_time=NOW)] if state != 'missing' else []),
        resource_ohlcv_bar_to_public_dict=lambda row: {'bar_time':row.bar_time.isoformat()}),
        build_resource_source_health=lambda *a,**kw: {'entries':[
            {'resource':'ohlcv', 'target':f'GC:{interval}', 'status':state, 'ok':False}]}, now=lambda:NOW)
    result = read_resource_asset_context(None, symbol='GC', market_data_params={'interval':interval}, dependencies=deps)
    assert result['data']['compact']['freshness_by_domain']['chart'] == state
