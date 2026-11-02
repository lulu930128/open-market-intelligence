"""Public v4 must not turn coverage gaps into market observations."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from app.ai import realtime_contract, capability_contract
from test_ai_implemented_feature_contracts import response_for, public

NOW = datetime(2026, 10, 28, 4, 39, 4, tzinfo=timezone.utc)

class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

def bars(*, clock='2026-10-28T12:05:00+08:00', close='2026-10-28T12:06:00+08:00'):
    point = {'price': 100, 'volume': 0}
    if clock:
        point['time'] = clock
    if close:
        point['bar_close_time'] = close
    return {'kind': 'tw_intraday_bars', 'interval': '1m', 'requested_interval': '1m',
        'requested_trade_date': '2026-10-28', 'expected_trade_date': '2026-10-28',
        'session_scope': 'current_session', 'session_phase': 'regular', 'market_status': 'open',
        'provider': 'fugle_marketdata', 'source': 'fugle.intraday.1m', 'volume_unit': 'shares',
        'is_partial': True, 'point_count': 1, 'points': [point], 'latest_point': point,
        'event_time': clock, 'selected_event_at': clock,
        'series_coverage': {'requested_coverage_satisfied': False, 'expected_to': '2026-10-28T12:39:00+08:00',
            'missing_ranges': [{'start_at': close, 'end_at': '2026-10-28T12:39:00+08:00'}]},
        'freshness': {'status': 'partial', 'is_current': False}}

def project(payload, policy='require_live'):
    response = response_for(['intraday.bars'], policy=policy)
    response['policy'] = {'allow_external_fetch': False, 'allow_write': False, 'allow_llm': False,
        'refresh_policy': {'before_answer': False}, 'tool_budget': {'max_external_fetches': 0}}
    response['tool_runs'] = []
    response['result']['data']['compact']['intraday_bars'] = payload
    with patch.object(realtime_contract, 'datetime', Clock), patch.object(capability_contract, 'datetime', Clock):
        return public(response)

@pytest.mark.parametrize('policy', ['cache_only', 'require_live'])
@pytest.mark.parametrize('gap_end', ['2026-10-28T12:39:00+08:00', '2026-10-28T13:30:00+08:00'])
def test_f8_public_old_bars_do_not_borrow_gap_end_and_offer_only_plan(policy, gap_end):
    payload = bars()
    payload['series_coverage']['missing_ranges'][0]['end_at'] = gap_end
    payload.update(served_at=NOW.isoformat(), computed_at=NOW.isoformat(), to_time=gap_end)
    result = project(payload, policy)
    observation = result['evidence']['realtime']['intraday.bars']
    assert observation['event_time'] == '2026-10-28T04:06:00+00:00'
    assert observation['state'] == 'stale'
    assert observation['intraday_research_usable'] is False
    assert observation['price_decision_usable'] is False
    if policy == 'require_live':
        assert observation['policy_satisfied'] is False
    assert observation['refresh_recommended'] is True
    fill = result['continuation']['fill_plan']
    assert any(item['capability'] == 'intraday.bars' for item in fill['actions'])
    assert 'intraday.bars' not in fill['partition']['already_satisfied']
    assert fill.get('jobs', []) == [] and result['execution']['tool_runs'] == []

@pytest.mark.parametrize('clock_key', ['bar_close_time', 'end_at'])
def test_f8_true_fresh_zero_volume_bar_keeps_own_close_clock(clock_key):
    payload = bars(clock='2026-10-28T12:38:00+08:00', close=None)
    payload['points'][0][clock_key] = '2026-10-28T12:39:00+08:00'
    result = project(payload)
    observation = result['evidence']['realtime']['intraday.bars']
    assert observation['event_time'] == '2026-10-28T04:39:00+00:00'
    assert observation['state'] == 'live' and observation['policy_satisfied'] is True
    assert result['evidence']['data']['intraday.bars']['points'][0]['volume'] == 0

def test_f8_unknown_clock_stays_unknown_despite_coverage_and_receipt():
    payload = bars(clock=None, close=None)
    payload.update(fetched_at=NOW.isoformat(), served_at=NOW.isoformat(), as_of=NOW.isoformat())
    result = project(payload)
    observation = result['evidence']['realtime']['intraday.bars']
    assert observation['event_time'] is None
    assert observation['policy_satisfied'] is False and observation['intraday_research_usable'] is False

def test_f8_historical_session_not_promoted_by_new_gap():
    payload = bars(clock='2026-10-27T13:29:00+08:00', close='2026-10-27T13:30:00+08:00')
    payload.update(is_historical=True, requested_trade_date='2026-10-27', expected_trade_date='2026-10-27')
    observation = project(payload)['evidence']['realtime']['intraday.bars']
    assert observation['event_time'] == '2026-10-27T05:30:00+00:00'
    assert observation['state'] == 'historical' and observation['policy_satisfied'] is False

def test_f8_explicit_fresh_no_trade_evidence_is_valid_empty_not_live_price():
    payload = bars(clock=None, close=None)
    payload.update(points=[], latest_point=None, point_count=0, trade_state='awaiting_first_trade',
        provider_snapshot_freshness='fresh', current_session_satisfied=True, event_time=NOW.isoformat())
    payload['source_status'] = {'trade_state': 'awaiting_first_trade',
        'provider_snapshot_freshness': 'fresh', 'current_session_satisfied': True}
    observation = project(payload)['evidence']['realtime']['intraday.bars']
    assert observation['state'] == 'valid_empty'
    assert observation['policy_satisfied'] is False and observation['price_decision_usable'] is False


def test_f8_single_canonical_bar_retains_its_legitimate_end_at():
    result = realtime_contract.classify_observation({
        'interval':'1m', 'start_at':'2026-10-28T12:38:00+08:00',
        'end_at':'2026-10-28T12:39:00+08:00', 'close_price':100,
        'session_phase':'regular', 'market_status':'open', 'is_partial':True,
        'coverage':{'missing_ranges':[{'end_at':'2026-10-28T13:30:00+08:00'}]},
    }, market='TW', capability_id='intraday.bars', realtime_policy='require_live', now=NOW)
    assert result['event_time']=='2026-10-28T04:39:00+00:00'
    assert result['state']=='live' and result['policy_satisfied'] is True


def test_f8_explicit_fresh_no_trade_cache_policy_retains_valid_empty():
    payload=bars(clock=None, close=None)
    payload.update(points=[],latest_point=None,point_count=0,event_time=NOW.isoformat(),
        source_status={'trade_state':'awaiting_first_trade','provider_snapshot_freshness':'fresh','current_session_satisfied':True})
    observation=project(payload, 'cache_only')['evidence']['realtime']['intraday.bars']
    assert observation['state']=='valid_empty' and observation['policy_satisfied'] is True
    assert observation['price_decision_usable'] is False
