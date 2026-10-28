"""Numeric read diagnostics retain deadlines, privacy and connection cleanup."""
import json
import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import read_execution as subject
from app.ai.capability_resolution_registry import CapabilityReadNode


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:', poolclass=StaticPool)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_wall_cpu_connection_and_reader_are_separate_and_request_local(db, monkeypatch):
    clock = [10.0, 1.0]
    monkeypatch.setattr(subject, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(subject, 'thread_time', lambda: clock[1], raising=False)
    class TimedSession(Session):
        def connection(self, *args, **kwargs):
            clock[0] += 3
            clock[1] += .25
            return super().connection(*args, **kwargs)
    monkeypatch.setattr(subject, 'Session', TimedSession)
    def reader(session):
        assert session.execute(text('PRAGMA query_only')).scalar() == 1
        clock[0] += 5
        clock[1] += 2
        return 'available'
    execution = subject.ReadExecution(db, (CapabilityReadNode('technical', timeout_seconds=15),))
    assert execution.run('technical', reader) == 'available'
    row = execution.diagnostics()['nodes'][0]
    assert row['wall_ms'] == row['duration_ms'] == 8000
    assert row['thread_cpu_ms'] == 2250
    assert row['connection_setup_ms'] == 3000
    assert row['reader_ms'] == 5000
    assert row['timeout_seconds'] == 15
    assert execution.run('technical', lambda _: pytest.fail('executed twice')) == 'available'
    assert len(execution.runs) == 1
    assert 'sqlite_errorcode' not in row
    assert subject.ReadExecution(db, ()).diagnostics()['nodes'] == []


@pytest.mark.parametrize('failure', ['interrupted', 'python'])
def test_failure_keeps_safe_code_timings_and_restores_connection(db, failure):
    def reader(session):
        if failure == 'python':
            raise ValueError('PRIVATE exception content')
        raw = session.connection().connection.driver_connection
        raw.set_progress_handler(lambda: 1, 1)
        session.execute(text('SELECT :secret'), {'secret': 'PRIVATE SQL parameter'})
    execution = subject.ReadExecution(db, (CapabilityReadNode('broken'), CapabilityReadNode('next')))
    assert execution.run('broken', reader, 'unavailable') == 'unavailable'
    row = execution.runs[0]
    assert row['status'] == 'error'
    assert row['reason_code'] == 'READ_NODE_UNAVAILABLE'
    assert all(row[key] >= 0 for key in ('wall_ms', 'thread_cpu_ms', 'connection_setup_ms', 'reader_ms'))
    if failure == 'interrupted':
        assert row['sqlite_errorcode'] == sqlite3.SQLITE_INTERRUPT
        assert row['sqlite_errorname'] == 'SQLITE_INTERRUPT'
    else:
        assert 'sqlite_errorcode' not in row and 'sqlite_errorname' not in row
    assert 'PRIVATE' not in json.dumps(execution.diagnostics())
    # The same pooled connection is writable again and its handler was removed.
    with db.get_bind().connect() as connection:
        assert connection.exec_driver_sql('PRAGMA query_only').scalar() == 0
        assert connection.exec_driver_sql('PRAGMA busy_timeout').scalar() == 5000
        connection.exec_driver_sql('CREATE TABLE cleanup_check (value INTEGER)')
    assert execution.run('next', lambda session: session.execute(text('SELECT 42')).scalar()) == 42


def test_expired_budget_does_not_acquire_or_call_reader(db, monkeypatch):
    execution = subject.ReadExecution(db, (CapabilityReadNode('expired'),), total_seconds=0)
    monkeypatch.setattr(subject, 'Session', lambda **_: pytest.fail('acquired after deadline'))
    assert execution.run('expired', lambda _: pytest.fail('read after deadline')) is None
    row = execution.runs[0]
    assert row['status'] == 'timeout'
    assert row['connection_setup_ms'] is None and row['reader_ms'] is None
    assert row['wall_ms'] >= 0 and row['thread_cpu_ms'] >= 0


def test_connection_failure_records_setup_without_reader(db, monkeypatch):
    class FailingSession(Session):
        def connection(self, *args, **kwargs):
            raise RuntimeError('PRIVATE connection detail')
    monkeypatch.setattr(subject, 'Session', FailingSession)
    execution = subject.ReadExecution(db, (CapabilityReadNode('connection'),))
    assert execution.run('connection', lambda _: pytest.fail('reader reached')) is None
    row = execution.runs[0]
    assert row['status'] == 'error' and row['connection_setup_ms'] >= 0
    assert row['reader_ms'] is None
    assert 'PRIVATE' not in json.dumps(execution.diagnostics())


import test_tw_capability_read_execution as existing
from test_tw_capability_read_execution import dependencies


@pytest.mark.parametrize('contract', [
    existing.test_sql_deadline_is_enforced_and_next_node_has_clean_read_session,
    existing.test_read_session_forbids_writes_and_dedupes_success,
])
def test_existing_deadline_and_read_purity_in_memory(db, contract):
    contract(db)


def test_public_v4_basic_diagnostics_keep_numeric_fields_and_quality(db, dependencies):
    from unittest.mock import patch
    from app.ai import ask as ask_module
    from app.ai.schemas import AiAskRequest
    from app.ai.capability_resolution_registry import TW_STOCK_READ_NODES
    from app.db.models import StockMaster
    assert TW_STOCK_READ_NODES['technical_evidence'].timeout_seconds == 15
    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id='2328', stock_name='fixture', market='TWSE', instrument_type='stock'))
    db.commit()
    dependencies.market_service.get_latest_stock_margin_trade.side_effect = TimeoutError('PRIVATE')
    payload = AiAskRequest(contract_version='omi.decision.v4', question='2328 selected evidence',
        target={'type':'tw_stock', 'id':'2328', 'market':'TW'}, mode='data_only', output='evidence_only',
        selection={'include':['chips.institutional','chips.margin'], 'max_response_bytes':100000},
        diagnostics_level='basic', realtime_policy='cache_only', allow_llm=False, allow_external_fetch=False, allow_write=False)
    with patch.object(ask_module.tools, 'read_stock_context', side_effect=lambda **_: existing.read(
            db, dependencies, ['chips.institutional','chips.margin'])), \
         patch.object(ask_module.agentic_tools, 'run_tw_stock_tool_session', side_effect=AssertionError('no acquisition')), \
         patch.object(ask_module.portfolio_service, 'get_position_context_for_scope', return_value=None):
        response = ask_module.ask(db, payload)
    assert response['evidence']['quality']['status'] == 'blocked'
    assert response['evidence']['data']['chips.institutional']['foreign_investor_net'] == 100
    rows = response['execution']['query_plan']['read_execution']['nodes']
    failed = next(row for row in rows if row['node'] == 'margin')
    assert failed['status'] == 'timeout'
    for row in rows:
        assert row['wall_ms'] == row['duration_ms']
        assert all(row[key] >= 0 for key in ('thread_cpu_ms','connection_setup_ms','reader_ms'))
    assert 'PRIVATE' not in json.dumps(response, default=str)
