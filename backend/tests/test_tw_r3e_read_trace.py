"""Serving trace is numeric, connection-local, failure-retaining and non-semantic."""
import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import read_execution
from app.ai.capability_resolution_registry import CapabilityReadNode, TW_STOCK_READ_NODES
from app.db import read_diagnostics as trace
from app.market import technical_evidence
from test_tw_capability_read_execution import dependencies, read


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:', poolclass=StaticPool)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_sql_counts_caught_failure_other_connection_exclusion_and_cleanup(db):
    connections = []
    def reader(session):
        connection = session.connection()
        connections.append(connection)
        assert session.execute(text('SELECT :value'), {'value': 'PRIVATE parameter'}).scalar() == 'PRIVATE parameter'
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql('SELECT * FROM PRIVATE_missing_table')
        # This may share a physical SQLite connection but is not the node's
        # SQLAlchemy Connection and must not enter its execute counters.
        with db.get_bind().connect() as other:
            assert other.exec_driver_sql('SELECT 99').scalar() == 99
        return connection.exec_driver_sql('SELECT 42').scalar()
    execution = read_execution.ReadExecution(db, (CapabilityReadNode('read'), CapabilityReadNode('next')))
    assert execution.run('read', reader) == 42
    row = execution.runs[0]
    sql = row['sql_execute']
    assert (sql['count'], sql['completed_count'], sql['error_count']) == (3, 2, 1)
    assert row['sql_execute_scope'] == 'node_read_connection_only'
    assert 'orm_materialization' in row['sql_execute_excludes']
    assert 0 <= sql['last_failed_execute']['wall_ms'] <= sql['wall_ms']
    assert 0 <= sql['last_failed_execute']['thread_cpu_ms'] <= sql['thread_cpu_ms']
    assert 0 < sql['last_failed_execute']['deadline_remaining_ms_at_sql_start'] <= 8000
    assert row['deadline_interrupt_observed'] is False
    assert 'PRIVATE' not in json.dumps(execution.diagnostics())
    for connection in connections:
        assert 'execute' not in vars(connection) and 'exec_driver_sql' not in vars(connection)
        assert not list(connection.dispatch.before_cursor_execute)
        assert not list(connection.dispatch.after_cursor_execute)
    assert not list(db.get_bind().dispatch.before_cursor_execute)
    assert not list(db.get_bind().dialect.dispatch.handle_error)
    assert execution.run('next', lambda session: session.execute(text('SELECT 1')).scalar()) == 1
    assert execution.runs[1]['sql_execute']['count'] == 1
    assert execution.runs[1]['sql_execute']['last_failed_execute'] is None
    assert trace.PHASE_TRACE_KEY not in db.info


def test_execute_clock_excludes_fetch_and_materialization(db, monkeypatch):
    clock = [10.0, 2.0]
    for module in (trace, read_execution):
        monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
        monkeypatch.setattr(module, 'thread_time', lambda: clock[1])
    def delay(value):
        clock[0] += 1
        clock[1] += .1
        return value
    with db.get_bind().connect() as connection:
        connection.connection.driver_connection.create_function('fixture_delay', 1, delay)
    def reader(session):
        result = session.execute(text('SELECT fixture_delay(value) FROM '
            '(SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3)'))
        return result.scalars().all()
    execution = read_execution.ReadExecution(db, (CapabilityReadNode('read'),))
    assert execution.run('read', reader) == [1, 2, 3]
    row = execution.runs[0]
    assert row['sql_execute']['wall_ms'] == row['sql_execute']['max_wall_ms'] == 1000
    assert row['sql_execute']['thread_cpu_ms'] == row['sql_execute']['max_thread_cpu_ms'] == 100
    assert row['reader_ms'] == 3000 and row['thread_cpu_ms'] == 300


@pytest.mark.parametrize('info', [None, {}, {trace.PHASE_TRACE_KEY: {}}, {trace.PHASE_TRACE_KEY: 'PRIVATE'}])
def test_no_valid_trace_is_a_true_noop(info):
    session = object() if info is None else SimpleNamespace(info=info)
    with trace.technical_read_phase(session, 'daily_bars'):
        pass
    with pytest.raises(ValueError, match='original'):
        with trace.technical_read_phase(session, 'daily_bars'):
            raise ValueError('original')


def test_fetch_interrupt_keeps_completed_execute_and_failed_phase(db, monkeypatch):
    clock = [10.0]
    for module in (trace, read_execution):
        monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    execution = read_execution.ReadExecution(db, (TW_STOCK_READ_NODES['technical_evidence'],))
    def reader(session):
        with trace.technical_read_phase(session, 'daily_bars'):
            result = session.execute(text('WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL '
                'SELECT n+1 FROM x WHERE n<100000000) SELECT n FROM x'))
            clock[0] += 16
            result.fetchall()
    assert execution.run('technical_evidence', reader) is None
    row = execution.runs[0]
    assert row['status'] == 'timeout' and row['sqlite_errorcode'] == 9
    assert row['deadline_interrupt_observed'] is True
    assert row['phases'] == [{'phase': 'daily_bars', 'status': 'error', 'wall_ms': 16000,
                             'thread_cpu_ms': row['phases'][0]['thread_cpu_ms']}]
    assert row['sql_execute']['completed_count'] == 1
    assert row['sql_execute']['error_count'] == 0
    assert row['sql_execute']['last_failed_execute'] is None


@pytest.mark.parametrize('kind', ['own_deadline', 'external_interrupt', 'python_overrun'])
def test_interrupt_provenance_and_failed_phase_survive(db, monkeypatch, kind):
    timeout = .015 if kind == 'own_deadline' else 15
    execution = read_execution.ReadExecution(db, (CapabilityReadNode('technical_evidence', timeout_seconds=timeout),))
    def reader(session):
        with trace.technical_read_phase(session, 'daily_bars'):
            if kind == 'python_overrun':
                session.execute(text('SELECT 1'))
                monkeypatch.setattr(read_execution, 'monotonic', lambda: execution.deadline + 1)
                return {'data': 'retained only before deadline gate'}
            if kind == 'external_interrupt':
                session.connection().connection.driver_connection.set_progress_handler(lambda: 1, 1)
            session.execute(text('WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL '
                'SELECT n+1 FROM x WHERE n<100000000) SELECT sum(n) FROM x')).scalar()
    assert execution.run('technical_evidence', reader, {}) == {}
    row = execution.runs[0]
    assert row['deadline_interrupt_observed'] is (kind == 'own_deadline')
    assert row['phases'][0]['phase'] == 'daily_bars'
    assert row['phases'][0]['status'] == ('completed' if kind == 'python_overrun' else 'error')
    assert all(row['phases'][0][key] >= 0 for key in ('wall_ms', 'thread_cpu_ms'))
    if kind != 'python_overrun':
        assert row['sqlite_errorcode'] == 9 and row['sqlite_errorname'] == 'SQLITE_INTERRUPT'
        assert row['sql_execute']['error_count'] == 1
        assert row['sql_execute']['last_failed_execute'] is not None
    else:
        assert row['sql_execute']['error_count'] == 0
        assert row['sql_execute']['last_failed_execute'] is None
    with db.get_bind().connect() as connection:
        assert connection.exec_driver_sql('PRAGMA query_only').scalar() == 0
        assert connection.exec_driver_sql('PRAGMA busy_timeout').scalar() == 5000
        assert connection.exec_driver_sql('SELECT 42').scalar() == 42


def test_public_v4_failure_contains_actual_owner_phase_and_sql_trace(db, dependencies, monkeypatch):
    from app.ai import ask as ask_module
    from app.ai.schemas import AiAskRequest
    from app.db.models import StockMaster
    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id='2328', stock_name='fixture', market='TWSE', instrument_type='stock'))
    db.commit()
    def failing_daily(session, *args, **kwargs):
        session.execute(text('SELECT * FROM PRIVATE_missing_table'))
    monkeypatch.setattr(technical_evidence, '_daily_points', failing_daily)
    dependencies.build_tw_stock_technical_evidence.side_effect = technical_evidence.build_tw_stock_technical_evidence
    caps = ['technical.structure', 'technical.swings']
    request = AiAskRequest(contract_version='omi.decision.v4', question='2328 selected evidence',
        target={'type': 'tw_stock', 'id': '2328'}, mode='data_only', output='evidence_only',
        selection={'include': caps, 'max_response_bytes': 100000}, diagnostics_level='basic',
        realtime_policy='cache_only', allow_llm=False, allow_external_fetch=False, allow_write=False)
    with patch.object(ask_module.tools, 'read_stock_context', side_effect=lambda **_: read(db, dependencies, caps)), \
         patch.object(ask_module.agentic_tools, 'run_tw_stock_tool_session', side_effect=AssertionError('no acquisition')), \
         patch.object(ask_module.portfolio_service, 'get_position_context_for_scope', return_value=None):
        response = ask_module.ask(db, request)
    rows = response['execution']['query_plan']['read_execution']['nodes']
    row = next(row for row in rows if row['node'] == 'technical_evidence')
    assert [(p['phase'], p['status']) for p in row['phases']] == [('parameters', 'completed'), ('daily_bars', 'error')]
    assert row['status'] == 'error' and row['reason_code'] == 'READ_NODE_UNAVAILABLE'
    assert row['sql_execute']['error_count'] == 1
    assert row['sql_execute']['last_failed_execute']['deadline_remaining_ms_at_sql_start'] > 0
    assert row['timeout_seconds'] == TW_STOCK_READ_NODES['technical_evidence'].timeout_seconds == 15
    assert response['evidence']['capability_status']['technical.structure']['decision_usable'] is False
    assert 'PRIVATE' not in json.dumps(response, default=str)
    dependencies.acquire_taiwan_quote_evidence.assert_not_called()


from test_tw_daily_candidate_repository import db as canonical_db
from test_tw_technical_read_reuse import NOW, seed


@pytest.mark.parametrize('historical,relative', [(False, True), (True, False)])
def test_actual_technical_owner_trace_preserves_entire_payload(canonical_db, monkeypatch, tmp_path, historical, relative):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    seed(canonical_db)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(technical_evidence, 'datetime', Clock)
    kwargs = dict(stock_id='2330', requested_capabilities={'technical.structure'} if relative else {'technical.swings'},
                  to_date=date(2026, 8, 21) if historical else None,
                  corporate_event_history={'cache_status': 'degraded', 'events': []})
    expected = technical_evidence.build_tw_stock_technical_evidence(db=canonical_db, **kwargs)
    execution = read_execution.ReadExecution(canonical_db, (TW_STOCK_READ_NODES['technical_evidence'],))
    actual = execution.run('technical_evidence', lambda session:
        technical_evidence.build_tw_stock_technical_evidence(db=session, **kwargs))
    assert actual == expected
    assert actual['indicators']['decision_usable'] is False  # qualification unchanged
    assert actual['indicators']['bar_series_fingerprint'] == expected['indicators']['bar_series_fingerprint']
    assert actual['indicators']['bar_series_revision'] == expected['indicators']['bar_series_revision']
    row = execution.runs[0]
    assert row['status'] == 'completed'
    assert [phase['phase'] for phase in row['phases']] == [
        'parameters', 'daily_bars', 'weekly_bars', 'monthly_bars', 'current_bars',
        'indicators', 'benchmark', 'sector', 'advanced', 'assemble']
    for phase in row['phases']:
        assert phase['status'] == ('skipped' if not relative and phase['phase'] in {'benchmark', 'sector'} else 'completed')
        assert phase['wall_ms'] >= 0 and phase['thread_cpu_ms'] >= 0
    assert row['sql_execute']['count'] > 0 and row['sql_execute']['error_count'] == 0
    assert row['deadline_interrupt_observed'] is False


def test_empty_owner_finishes_daily_phase_without_inventing_later_work(canonical_db, monkeypatch, tmp_path):
    from app.config import settings
    from app.db.models import StockMaster
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    canonical_db.add(StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock'))
    canonical_db.commit()
    execution = read_execution.ReadExecution(canonical_db, (TW_STOCK_READ_NODES['technical_evidence'],))
    result = execution.run('technical_evidence', lambda session:
        technical_evidence.build_tw_stock_technical_evidence(db=session, stock_id='2330'))
    assert result is not None, execution.runs
    assert result['status'] == 'missing'
    assert [(p['phase'], p['status']) for p in execution.runs[0]['phases']] == [
        ('parameters', 'completed'), ('daily_bars', 'completed')]
