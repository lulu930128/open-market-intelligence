"""A failed planned node cannot qualify fallback facts as ready research."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.market_context import taiwan_stock
from test_tw_capability_read_execution import dependencies, read
from test_ai_implemented_feature_contracts import response_for, public


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def ready_legacy(monkeypatch, dependencies):
    monkeypatch.setattr(taiwan_stock, '_evaluate_technical_evidence_sufficiency', lambda **kw: {
        'status': 'ready', 'decision_usable': True, 'reason_codes': []})
    monkeypatch.setattr(taiwan_stock, '_technical_analysis_summary', lambda **kw: {
        'status': 'ready', 'decision_usable': True, 'selected_score': 3,
        'scores': {'daily': 3}, 'selected_timeframe': 'daily'})
    monkeypatch.setattr(taiwan_stock, '_technical_price_levels', lambda **kw: {
        'latest_price': 12, 'entry': {'observed': 12}, 'risk': {'observed': 10}})
    dependencies.build_stock_technical_report.return_value = {
        'latest_close': 12, 'latest_finalized_close': 12, 'score': 3,
        'indicators': {'close': 12}, 'warnings': []}
    price_map = {'version': 'tw.stock.price_map.v4', 'status': 'ready', 'decision_usable': True,
        'corporate_action': {'coverage_status': 'complete', 'cache_status': 'current'},
        'reference': {'as_of': '2026-09-28', 'price': 12}, 'warnings': []}
    return replace(dependencies, build_tw_stock_price_map=Mock(return_value=price_map)), deepcopy(price_map)


def projected(result, caps):
    response = response_for(caps)
    response['result'] = result
    return public(response)['evidence']


@pytest.mark.parametrize('failure', [TimeoutError('bounded'), ValueError('bad input')])
def test_failed_planned_evidence_retains_facts_without_promoting_fallback(db, ready_legacy, failure):
    deps, independent_price_map = ready_legacy
    deps.build_tw_stock_technical_evidence.side_effect = failure
    caps = ['technical.structure', 'technical.price_map']
    result = read(db, deps, caps)
    compact = result['data']['compact']['technical']
    assert compact['status'] == 'partial'
    assert compact['decision_usable'] is False
    assert compact['levels']['latest_price'] == 12
    assert compact['levels']['entry'] == {} and compact['levels']['risk'] == {}
    assert 'READ_NODE_UNAVAILABLE' in compact['analysis']['sufficiency']['reason_codes']
    assert result['data']['technical_reports']['daily']['latest_close'] == 12
    evidence = projected(result, caps)
    structure = evidence['data']['technical.structure']
    assert structure['status'] == 'partial' and structure['decision_usable'] is False
    assert 'READ_NODE_UNAVAILABLE' in structure['quality']['reason_codes']
    assert 'READ_NODE_UNAVAILABLE' in evidence['quality']['capabilities']['technical.structure']['reason_codes']
    canonical = evidence['capability_status']['technical.structure']
    assert 'READ_NODE_UNAVAILABLE' in canonical['reason_codes']
    assert canonical['coverage_status'] == 'partial'
    assert canonical['decision_usable'] is False
    assert result['data']['price_map'] == independent_price_map
    assert evidence['data']['technical.price_map']['decision_usable'] is True
    assert evidence['capability_status']['technical.price_map']['coverage_status'] == 'complete'
    deps.acquire_taiwan_quote_evidence.assert_not_called()


@pytest.mark.parametrize('technical', [{}, {'indicators': {'decision_usable': True}}])
def test_successful_technical_reader_does_not_masquerade_as_failed_node(db, ready_legacy, technical):
    deps, _ = ready_legacy
    deps.build_tw_stock_technical_evidence.return_value = technical
    result = read(db, deps, ['technical.structure'])
    compact = result['data']['compact']['technical']
    assert compact['status'] == 'ready' and compact['decision_usable'] is True
    assert 'READ_NODE_UNAVAILABLE' not in compact['analysis']['sufficiency']['reason_codes']


def test_unselected_evidence_node_does_not_block_independent_price_map(db, ready_legacy):
    deps, independent_price_map = ready_legacy
    deps.build_tw_stock_technical_evidence.side_effect = AssertionError('unselected reader')
    result = read(db, deps, ['technical.price_map'])
    deps.build_tw_stock_technical_evidence.assert_not_called()
    assert result['data']['price_map'] == independent_price_map
    assert 'technical_evidence' not in result['read_execution']['planned_nodes']
    evidence = projected(result, ['technical.price_map'])
    assert evidence['data']['technical.price_map']['decision_usable'] is True
    assert not any(node['status'] != 'completed' for node in result['read_execution']['nodes'])
