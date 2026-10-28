"""Demand failures remain visible beside cached evidence, without private text."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.refresh_status import read_refresh_status
from app.ai.schemas import AiRefreshStatusRead
from app.db.models import Base, JobRun, StockMaster
from app.jobs import taiwan_intraday_demand as demand
from app.market_data.gateway import PostAcquisitionError
from app.market_data.integration_contracts import AcquisitionSummary, AcquisitionStatus
import test_tw_intraday_consumer_demand as contracts


@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite:///:memory:', poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    result = SimpleNamespace(engine=engine, factory=factory, dispatches=[], clock=[contracts.NOW])
    monkeypatch.setattr(demand.jobs, 'SessionLocal', factory)
    monkeypatch.setattr(demand.jobs, 'submit_job_task', lambda task, job_id, **kw: result.dispatches.append(job_id))
    monkeypatch.setattr(demand, '_now', lambda: result.clock[0])
    with factory() as db:
        db.add(StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock', is_active=True))
        db.commit()
    yield result
    engine.dispose()


@pytest.mark.parametrize('failure,stage,error_type,actual_calls', [
    ('provider', 'acquisition', 'ConnectionError', None),
    ('parse', 'acquisition', 'JSONDecodeError', None),
    ('persistence', 'persistence', 'ValueError', 1),
    ('reject', 'persistence', None, 1),
    ('summary', 'acquisition', None, 1),
    ('timeout', 'acquisition', 'TimeoutError', None),
])
@pytest.mark.parametrize('cached_count', [0, 141])
def test_failure_retains_safe_stage_and_unknown_counts(env, monkeypatch, caplog, failure, stage, error_type, actual_calls, cached_count):
    reads = contracts.reread_stub(monkeypatch, count=cached_count)
    summary = AcquisitionSummary(attempted=True, status=AcquisitionStatus.FAILED if failure == 'summary' else AcquisitionStatus.COMPLETED,
        external_calls=1, limitations=('PROVIDER_REQUEST_OR_PARSE_FAILED',) if failure == 'summary' else ())
    def refresh(*args, **kwargs):
        if failure == 'provider': raise ConnectionError('SECRET https://private.invalid/token')
        if failure == 'parse': raise json.JSONDecodeError('SECRET', 'PRIVATE', 0)
        if failure == 'timeout': raise TimeoutError('SECRET')
        if failure == 'persistence':
            try: raise ValueError('PRIVATE')
            except ValueError as cause:
                raise PostAcquisitionError('SECRET', acquisition=summary, stage='persistence') from cause
        return SimpleNamespace(acquisition=summary, persistence=SimpleNamespace(
            attempted=failure != 'summary', committed=False, observations_written=0))
    monkeypatch.setattr(demand, 'refresh_taiwan_intraday_bars', refresh)
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id='2330', requested_at=contracts.NOW, consumer='ai', max_external_calls=1)
        job_id = job.id
    demand.run_consumer_demand(job_id)
    with env.factory() as db:
        job = db.get(JobRun, job_id)
        result = json.loads(job.result_json)
        assert result['external_call_budget_used'] == 1
        assert result['external_call_count'] == actual_calls
        assert result['bars_written_count'] == (0 if failure in {'reject', 'summary'} else None)
        assert result['reread_ready'] is False
        diagnostic = result['last_failure']
        assert diagnostic['stage'] == stage
        assert diagnostic['error_type'] == error_type
        assert diagnostic['attempt_count'] == 1
        public = AiRefreshStatusRead.model_validate(read_refresh_status(db=db, job_id=job_id)).model_dump(mode='json')
        assert public['status'] == ('partial' if cached_count else 'failed')
        assert public['materialization']['last_failure'] == diagnostic
        assert public['error']['code'] == result['reason_code']
        assert public['error']['diagnostic'] == diagnostic
        assert public['evidence_rebuild_required'] is bool(cached_count)
        if cached_count:
            assert public['resume']['arguments']['allow_external_fetch'] is False
        assert public['materialization']['external_call_count'] == actual_calls
        assert not any(secret in json.dumps(public) + job.result_json + caplog.text for secret in ('SECRET', 'PRIVATE', 'private.invalid'))
    assert len(reads) == 3


@pytest.mark.parametrize('contract', [
    contracts.test_final_reread_is_mandatory_after_provider_and_persistence,
    contracts.test_status_redacts_and_pins_cache_only_resume,
    contracts.test_same_job_three_heartbeat_attempts_and_cooldown,
    contracts.test_real_canonical_persistence_and_reread_keep_partial_truth,
])
def test_existing_readiness_and_budgets_in_memory(env, monkeypatch, contract):
    contract(env, monkeypatch)


@pytest.mark.parametrize('field', ['reason_code', 'stage', 'subphase', 'error_type'])
@pytest.mark.parametrize('malicious', ['SECRET', {'private':'SECRET'}, ['SECRET']])
def test_old_partial_job_and_malicious_diagnostics_are_safely_projected(env, monkeypatch, field, malicious):
    contracts.reread_stub(monkeypatch, count=141)
    with env.factory() as db:
        job, _ = demand.enqueue_consumer_demand(db, stock_id='2330', requested_at=contracts.NOW, consumer='ai')
        result = json.loads(job.result_json)
        diagnostic = {'reason_code':'TW_INTRADAY_DEMAND_ACQUISITION_FAILED', 'stage':'acquisition',
                      'subphase':'parse', 'error_type':'JSONDecodeError', 'attempt_count':1}
        diagnostic[field] = malicious
        result.update(status='partial', reason_code='TW_INTRADAY_DEMAND_ACQUISITION_FAILED',
            external_call_count=None, bars_written_count=None,
            last_failure={**diagnostic, 'message':'PRIVATE'})
        job.status = 'error'
        job.result_json = json.dumps(result)
        db.commit()
        public = read_refresh_status(db=db, job_id=job.id)
        assert public['error']['code'] == 'TW_INTRADAY_DEMAND_ACQUISITION_FAILED'
        assert 'PRIVATE' not in json.dumps(public, default=str) and 'SECRET' not in json.dumps(public, default=str)
        assert public['materialization']['external_call_count'] is None
        projected = public['materialization']['last_failure']
        if field == 'reason_code':
            assert projected is None
        else:
            assert projected[field] is None
            assert projected['reason_code'] == 'TW_INTRADAY_DEMAND_ACQUISITION_FAILED'
            assert projected['attempt_count'] == 1
        # Legacy partial rows have no structured diagnostic at all.
        result.pop('last_failure')
        job.result_json = json.dumps(result); db.commit()
        legacy = read_refresh_status(db=db, job_id=job.id)
        assert legacy['error']['code'] == public['error']['code']
        assert legacy['materialization']['last_failure'] is None
