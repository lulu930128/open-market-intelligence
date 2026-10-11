"""G-B/G-C offline fixtures: real owner, planner, parser, SQLite and Resolver."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, JobRun, MarketIntradayBar, MarketIntradayBarLineage, USStockMaster
from app.market_data.contracts import ProviderResourceHealth
from app.us_market import intraday_materializer as owner
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_truth import read_us_historical_intraday_trend
from app.us_market.market_data.descriptors import (
    YAHOO_INTRADAY_DESCRIPTOR as YAHOO, TWELVE_INTRADAY_DESCRIPTOR as TWELVE,
)
from test_us_intraday_convergence import DAY, START, AFTER_HOURS
from test_us_intraday_shared_core import _yahoo_bars_payload, _twelve_bars_payload
from test_us_eod_durable import fixture_route, MISSING


@pytest.fixture
def rig(tmp_path):
    engine = create_engine('sqlite:///' + (tmp_path / 'gb.sqlite').as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(USStockMaster(symbol='SSO', exchange='NYSE', is_etf=True))
        db.commit()
    calls = []
    clock = [AFTER_HOURS]
    behavior = {YAHOO.resource_id: 378, TWELVE.resource_id: 390}
    descriptors = [YAHOO, TWELVE]
    health = []

    def platform(db):
        def fetch(route, requirement):
            # This is the external-call seam. Its reservation is visible to a
            # different connection, and no writer/read transaction crosses IO.
            assert not db.in_transaction()
            assert requirement.bounds.max_external_calls == 1
            assert requirement.bounds.max_provider_attempts == 1
            assert requirement.request.acquisition_window == 'dated'
            with Session(engine) as observer:
                row = observer.query(JobRun).filter_by(target=owner._eod_target('SSO', DAY)).one()
                attempts = json.loads(row.request_json)['attempts']
                assert row.status == 'running'
                assert attempts[-1]['outcome'] == 'unknown'
                assert attempts[-1]['planned_resource']['resource_id'] == route.resource_id
                assert attempts[-1]['external_call_reservation'] == 1
            calls.append((row.id, route.provider_key, route.resource_id))
            value = behavior[route.resource_id]
            if isinstance(value, BaseException):
                raise value
            if value == 'malformed':
                return {'unexpected': 'fixture'}, 'https://fixture.invalid'
            end = START + timedelta(minutes=value)
            if route.provider_key == YAHOO.provider_key:
                payload = _yahoo_bars_payload(end, count=value)
                payload['chart']['result'][0]['meta']['symbol'] = 'SSO'
            else:
                payload = _twelve_bars_payload(end, count=value)
                payload['meta']['symbol'] = 'SSO'
            return payload, 'https://fixture.invalid'

        p = USIntradayMarketPlatform(db, bar_descriptors=tuple(descriptors),
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={d.resource_id: fetch for d in descriptors}, clock=lambda: clock[0]))
        read = p._bar_reader.read_bar_candidates
        p._bar_reader.read_bar_candidates = lambda req: replace(read(req), provider_health=tuple(health))
        return p

    def run(minutes=0, **kwargs):
        clock[0] = AFTER_HOURS + timedelta(minutes=minutes)
        return owner.reconcile_us_intraday_session(
            configured_symbols='SSO', trade_date=DAY, now=clock[0],
            session_factory=lambda: Session(engine), platform_factory=platform, **kwargs)

    yield engine, calls, behavior, descriptors, health, run
    engine.dispose()


def attempts(engine):
    with Session(engine) as db:
        return json.loads(db.query(JobRun).one().request_json)['attempts']


@pytest.mark.parametrize('yahoo_count,twelve_count,expected,count', [
    (378, 390, 'twelve_data', 390), (378, 387, 'twelve_data', 387),
    (387, 378, 'yahoo_chart', 387), (378, 378, 'yahoo_chart', 378),
])
def test_distinct_durable_routes_single_source_quality(rig, yahoo_count, twelve_count, expected, count):
    engine, calls, behavior, _, _, run = rig
    behavior.update({YAHOO.resource_id: yahoo_count, TWELVE.resource_id: twelve_count})
    first = run()
    assert first['reserved_external_call_count'] == first['external_call_count'] == 1
    assert first['results'][0]['coverage']['point_count'] == yahoo_count
    assert run(1)['results'][0]['reason'] == 'cooldown'
    second = run(15)  # fresh Session/platform, same durable obligation
    assert second['reserved_external_call_count'] == second['external_call_count'] == 1
    assert [x[1] for x in calls] == ['yahoo_chart', 'twelve_data']
    assert calls[0][0] == calls[1][0]
    ledger = attempts(engine)
    assert len(ledger) == 2
    assert [a['planned_resource']['provider_key'] for a in ledger] == ['yahoo_chart', 'twelve_data']
    assert all(a['external_call_reservation'] == 1 for a in ledger)
    assert all(a['selected_resources'][0]['resource_id'] == a['planned_resource']['resource_id'] for a in ledger)
    with Session(engine) as db:
        result = read_us_historical_intraday_trend(db, symbol='SSO', trade_date=DAY, evaluated_at=AFTER_HOURS + timedelta(minutes=15))
        assert db.query(MarketIntradayBar).count() == yahoo_count + twelve_count
    assert result['source_status']['provider'] == expected
    assert result['point_count'] == count
    assert result['is_partial'] is (count < 390)
    assert result['decision_usable'] is False
    if expected == 'twelve_data':
        assert {'PARTIAL_US_MARKET_VOLUME', 'PERSONAL_INTERNAL_USE_ONLY'} <= set(result['warnings'])
        assert result['research_usable'] is False
        assert all(p['volume_based_decision_usable'] is False for p in result['points'])
    third = run(30)
    assert third['reserved_external_call_count'] == 0
    assert third['results'][0]['reason'] == ('canonical_cache_already_satisfied' if count == 390 else 'acquisition_plan_unfillable')
    assert len(calls) == len(attempts(engine)) == 2


@pytest.mark.parametrize('failure', [TimeoutError('fixture'), ValueError('fixture'), 'malformed', 0])
def test_failed_first_route_can_advance_without_refund(rig, failure):
    engine, calls, behavior, _, _, run = rig
    behavior[YAHOO.resource_id] = failure
    first = run()['results'][0]
    assert not first['postcondition_satisfied']
    assert first['acquisition_limitations']
    if isinstance(failure, TimeoutError):
        assert 'INTRADAY_PROVIDER_TIMEOUT' in first['acquisition_limitations']
    assert run(15)['results'][0]['postcondition_satisfied']
    assert len(attempts(engine)) == len(calls) == 2


@pytest.mark.parametrize('field,value,reason', [
    ('supports_dated_queries', False, 'DATED_ACQUISITION_NOT_SUPPORTED'),
    ('max_lookback_days', 0, 'OUT_OF_REPAIR_HORIZON'),
    ('intervals', ('5m',), 'INTERVAL_NOT_SUPPORTED_BY_RESOURCE'),
])
def test_ineligible_second_route_never_reserves(rig, field, value, reason):
    engine, calls, _, descriptors, _, run = rig
    run()
    descriptors[1] = TWELVE.model_copy(update={field: value})
    item = run(15)['results'][0]
    assert item['reason'] == 'acquisition_plan_unfillable'
    assert reason in item['acquisition_limitations']
    assert len(calls) == len(attempts(engine)) == 1


@pytest.mark.parametrize('axis,value,reason', [
    ('entitlement', 'plan_restricted', 'PLAN_RESTRICTED'),
    ('entitlement', 'auth_failed', 'AUTH_FAILED'),
    ('operational', 'rate_limited', 'RATE_LIMITED'),
    ('enablement', 'disabled', 'PROVIDER_DISABLED'),
])
def test_shared_health_blocks_next_route(rig, axis, value, reason):
    engine, calls, _, _, health, run = rig
    run()
    state = dict(provider='twelve_data', market='US', capability='intraday.bars', resource_id=TWELVE.resource_id,
        enablement='enabled', connection='connected', entitlement='entitled', operational='healthy',
        freshness='fresh', checked_at=AFTER_HOURS + timedelta(minutes=15))
    state[axis] = value
    health.append(ProviderResourceHealth(**state))
    item = run(15)['results'][0]
    assert item['reason'] == 'acquisition_plan_unfillable'
    assert reason in item['acquisition_limitations']
    assert len(calls) == len(attempts(engine)) == 1


@pytest.mark.parametrize('count', [1, 3])
def test_old_ledger_missing_route_never_backfilled_or_retried(rig, count):
    engine, calls, _, _, _, run = rig
    run()
    with Session(engine) as db:
        job = db.query(JobRun).one()
        request = json.loads(job.request_json)
        old = request['attempts'][0]
        old.pop('planned_resource')
        request['attempts'] = [{**old, 'reservation_id': str(i)} for i in range(count)]
        job.request_json = json.dumps(request)
        db.commit()
        before = job.request_json
    item = run(15)['results'][0]
    assert item['reason'] == ('retry_budget_exhausted' if count == 3 else 'legacy_route_history_unknown')
    with Session(engine) as db:
        assert db.query(JobRun).one().request_json == before
    assert len(calls) == 1


def test_unknown_orphan_keeps_consumed_route(rig):
    engine, calls, _, _, _, run = rig
    run()
    with Session(engine) as db:
        job = db.query(JobRun).one()
        request = json.loads(job.request_json)
        request['attempts'][0]['outcome'] = 'unknown'
        job.request_json = json.dumps(request)
        job.status = 'running'
        db.commit()
    assert run(1)['results'][0]['reason'] == 'cooldown'
    assert run(15)['results'][0]['postcondition_satisfied']
    assert attempts(engine)[0]['outcome'] == 'unknown'
    assert [x[1] for x in calls] == ['yahoo_chart', 'twelve_data']


def test_zero_run_budget_never_calls_provider(rig):
    engine, calls, _, _, _, run = rig
    assert run(max_external_calls=0)['results'][0]['reason'] == 'external_call_budget_exhausted'
    assert calls == attempts(engine) == []


def test_no_eligible_first_route_does_not_consume_attempt(rig):
    engine, calls, _, descriptors, _, run = rig
    descriptors[:] = [d.model_copy(update={'supports_dated_queries': False}) for d in descriptors]
    item = run()['results'][0]
    assert item['reason'] == 'acquisition_plan_unfillable'
    assert 'DATED_ACQUISITION_NOT_SUPPORTED' in item['acquisition_limitations']
    assert calls == attempts(engine) == []


def test_route_order_is_descriptor_owned_not_scheduler_override(rig):
    engine, calls, _, descriptors, _, run = rig
    descriptors[1] = TWELVE.model_copy(update={'priority': YAHOO.priority - 1})
    assert run()['results'][0]['postcondition_satisfied']
    assert [c[1] for c in calls] == ['twelve_data']
    assert len(attempts(engine)) == 1


def test_gc_provisional_full_series_not_complete(rig):
    engine, calls, _, _, _, run = rig
    run()
    run(15)
    with Session(engine) as db:
        for line in db.query(MarketIntradayBarLineage).filter_by(provider='twelve_data'):
            line.finalization = 'provisional'
        db.commit()
    item = run(30)['results'][0]
    assert not item['postcondition_satisfied']
    assert item['status'] == 'partial'
    assert len(calls) == 2


def test_current_historical_and_quote_read_contract_regression():
    from test_us_intraday_shared_core import _db
    from test_us_intraday_materializer import _yahoo_quote_payload
    from app.us_market.market_data.descriptors import YAHOO_QUOTE_RESOURCE_ID, YAHOO_QUOTE_DESCRIPTOR
    db = _db()
    now = START + timedelta(minutes=30)
    seen = []
    def fetch(route, requirement):
        seen.append(requirement)
        payload = (_yahoo_quote_payload(now) if route.resource_id == YAHOO_QUOTE_RESOURCE_ID
                   else _yahoo_bars_payload(now, count=30))
        return payload, 'https://fixture.invalid'
    platform = USIntradayMarketPlatform(db, bar_descriptors=(YAHOO,), quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
        acquisition=USIntradayAcquisitionExecutor(clock=lambda: now,
            fetchers={YAHOO.resource_id: fetch, YAHOO_QUOTE_RESOURCE_ID: fetch}))
    assert platform.read_intraday_bars(symbol='AAPL', now=now).result.requirement.request.acquisition_window == 'relative'
    current = platform.refresh_intraday_bars(symbol='AAPL', now=now, max_provider_calls=1)
    assert current.result.acquisition.external_calls == 1
    assert current.result.requirement.request.acquisition_window == 'relative'
    historical = platform.read_intraday_bars_for_trade_date(symbol='AAPL', trade_date=DAY,
        now=AFTER_HOURS, completed_regular=True)
    assert historical.result.requirement.request.acquisition_window == 'dated'
    quote = platform.refresh_quote(symbol='AAPL', now=now, max_provider_calls=1)
    assert quote.result.acquisition.external_calls == 1
    cached = platform.read_quote(symbol='AAPL', now=now)
    assert cached.result.acquisition.external_calls == 0
    assert cached.result.resolved.health.facts_usable
    assert len(seen) == 2
    db.close()


@pytest.mark.parametrize('state', ['complete', 'legacy', 'exhausted', 'same_provider'])
def test_second_admission_rechecks_ledger_without_extra_reservation(rig, state):
    engine, calls, _, _, _, _ = rig
    with Session(engine) as db:
        pending = owner._eod_admit(db, symbol='SSO', trade_date=DAY, now=AFTER_HOURS,
            evidence=MISSING, allow_call=True)
        assert pending['reason'] == 'route_pending'
        assert attempts(engine) == []
        evidence = {**MISSING, 'postcondition_satisfied': state == 'complete'}
        if state != 'complete':
            job = db.query(JobRun).one()
            request = json.loads(job.request_json)
            old = dict(reservation_id='old', outcome='unknown', external_call_reservation=1)
            if state != 'legacy':
                old['planned_resource'] = fixture_route().model_dump(mode='json')
            request['attempts'] = [old] * (3 if state == 'exhausted' else 1)
            job.request_json = json.dumps(request, separators=(',', ':'))
            db.commit()
        before = attempts(engine)
        before_bytes = db.query(JobRun).one().request_json
        item = owner._eod_admit(db, symbol='SSO', trade_date=DAY, now=AFTER_HOURS,
            evidence=evidence, allow_call=True, planned_resource=fixture_route())
    assert item['reason'] == dict(complete='canonical_cache_already_satisfied',
        legacy='legacy_route_history_unknown', exhausted='retry_budget_exhausted',
        same_provider='provider_already_reserved')[state]
    assert not item['acquisition_attempted']
    assert before == attempts(engine)
    with Session(engine) as db:
        assert db.query(JobRun).one().request_json == before_bytes
    assert calls == []
