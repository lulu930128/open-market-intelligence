"""Crypto selection reaches only bounded cached owners through public ask."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text
from app.ai import ask, agentic_tools, read_execution
from app.ai.market_context import crypto_context
from app.ai.schemas import AiAskRequest
from app.crypto_market.assets import get_crypto_asset
from test_tw_daily_candidate_repository import db  # noqa: F401

NOW = datetime(2026, 10, 28, 4, 39, tzinfo=timezone.utc)
READERS = (
    'list_latest_crypto_tickers', 'list_latest_crypto_order_books', 'list_latest_crypto_ohlcv_bars',
    'list_crypto_ohlcv_coverage', 'list_latest_crypto_derivatives', 'list_latest_crypto_market_caps',
    'list_latest_crypto_spreads', 'list_crypto_ticker_history', 'list_crypto_liquidity_history',
    'list_crypto_derivatives_history', 'list_crypto_long_short_ratio_history', 'list_crypto_liquidation_heatmap_cells',
)

@pytest.fixture
def owners(monkeypatch):
    service = SimpleNamespace(**{name: Mock(return_value=[]) for name in READERS})
    service.get_crypto_provider_contract = Mock(return_value={})
    ticker = SimpleNamespace(provider='binance', exchange='Binance', symbol='BTC-USDT',
        instrument_type='spot', last_price=100, bid_price=99, ask_price=101, price_change_pct_24h=0,
        event_time=NOW, fetched_at=NOW, base_asset='BTC', quote_asset='USDT', base_volume_24h=0)
    service.list_latest_crypto_tickers.return_value = [ticker]
    def bars(reader, **kwargs):
        return [SimpleNamespace(provider='binance', exchange='Binance', symbol='BTC-USDT',
            instrument_type='spot', interval=kwargs['interval'], bar_time=datetime(2026, 10, 27, tzinfo=timezone.utc) - timedelta(days=27-day),
            fetched_at=NOW, open_price=100, high_price=101, low_price=99, close_price=100,
            base_volume=0 if day == 27 else None, quote_volume=None, base_asset='BTC', quote_asset='USDT')
            for day in range(27, 27 - kwargs['limit'], -1)]
    service.list_latest_crypto_ohlcv_bars.side_effect = bars
    health = Mock(return_value={'entries': [], 'summary': {}})
    monkeypatch.setattr(agentic_tools, 'crypto_market_service', service)
    monkeypatch.setattr(agentic_tools, 'build_crypto_source_health', health)
    monkeypatch.setattr(ask.portfolio_service, 'get_position_context_for_scope', Mock(return_value=None))
    return service, health

def payload():
    return AiAskRequest(contract_version='omi.decision.v4', question='BTC cached quote and daily bars',
        target={'type': 'crypto_asset', 'id': 'BTC', 'market': 'crypto'}, mode='data_only', output='evidence_only',
        analysis_horizon='short', payload_level='compact', realtime_policy='cache_only',
        refresh_policy={'mode': 'off', 'before_answer': False},
        allow_external_fetch=False, allow_llm=False, allow_write=False,
        selection={'include': ['quote.snapshot', 'daily.ohlcv'], 'limits': {'daily.ohlcv': 3}, 'max_response_bytes': 65536},
        tool_budget={'max_calls': 2, 'max_external_fetches': 0, 'max_total_seconds': 20})

def test_public_selected_crypto_skips_heavy_readers_and_passes_remaining_budget(db, owners):
    service, health = owners
    for name in READERS:
        if name not in {'list_latest_crypto_tickers', 'list_latest_crypto_ohlcv_bars'}:
            getattr(service, name).side_effect = AssertionError('unselected cached reader')
    health.side_effect = AssertionError('unselected source health')
    with patch.object(crypto_context, 'read_crypto_context', wraps=crypto_context.read_crypto_context) as reader:
        result = ask.ask(db, payload())
    params = reader.call_args.kwargs['market_data_params']
    assert set(params['requested_capabilities']) >= {'quote.snapshot', 'daily.ohlcv'}
    assert params['capability_limits']['daily.ohlcv'] == 3
    assert 0 < params['read_budget_seconds'] <= 20
    assert params['external_fetch_allowed'] is False
    assert result['contract_version'] == 'omi.decision.v4' and result['request_valid'] is True
    data = result['evidence']['data']
    assert data['quote.snapshot']['price'] == 100
    bars = data['daily.ohlcv']['bars']
    assert len(bars) == 3 and [row['bar_time'] for row in bars] == sorted(row['bar_time'] for row in bars)
    assert bars[-1]['base_volume'] == 0 and bars[0]['base_volume'] is None
    assert bars[-1]['volume_unit'] == 'BTC'
    service.list_latest_crypto_ohlcv_bars.assert_called_once()
    assert service.list_latest_crypto_ohlcv_bars.call_args.kwargs['interval'] == '1d'
    assert service.list_latest_crypto_ohlcv_bars.call_args.kwargs['limit'] == 3
    assert result['execution']['tool_runs'] == []
    for name in READERS:
        if name not in {'list_latest_crypto_tickers', 'list_latest_crypto_ohlcv_bars'}:
            getattr(service, name).assert_not_called()
    health.assert_not_called()

@pytest.mark.parametrize('empty', [True, False])
def test_public_crypto_missing_and_sql_timeout_keep_partial_evidence(db, owners, empty):
    service, health = owners
    if empty:
        service.list_latest_crypto_ohlcv_bars.side_effect = None
        service.list_latest_crypto_ohlcv_bars.return_value = []
    else:
        def expensive(reader, **kwargs):
            assert reader.connection().exec_driver_sql('PRAGMA query_only').scalar() == 1
            return reader.execute(text('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n')).all()
        service.list_latest_crypto_ohlcv_bars.side_effect = expensive
        original = read_execution.ReadExecution.__init__
        def short_budget(self, db, nodes, **kwargs):
            original(self, db, nodes, total_seconds=.02)
        with patch.object(read_execution.ReadExecution, '__init__', short_budget):
            result = ask.ask(db, payload())
    if empty:
        result = ask.ask(db, payload())
    assert result['request_valid'] is True
    assert result['evidence']['data']['quote.snapshot']['price'] == 100
    assert not result['evidence']['data'].get('daily.ohlcv', {}).get('bars')
    assert result['execution']['tool_runs'] == []
    if not empty:
        runs = result['execution']['query_plan']['read_execution']['nodes']
        assert any(row['node'] == 'daily.ohlcv' and row['status'] == 'timeout' for row in runs)


def test_legacy_crypto_context_still_reads_original_resources(db, owners):
    service, health = owners
    result = agentic_tools.read_crypto_context(db, asset='BTC', market_data_params={'limit': 3})
    for name in READERS:
        getattr(service, name).assert_called_once()
    health.assert_called_once()
    assert result['data']['compact']['quote']['price'] == 100
    assert len(result['data']['ohlcv']) == 3


def test_exhausted_crypto_budget_dispatches_no_cached_reader(db, owners):
    service, health = owners
    result = agentic_tools.read_crypto_context(db, asset='BTC', market_data_params={
        'requested_capabilities': ['quote.snapshot', 'daily.ohlcv'], 'read_budget_seconds': 0})
    for name in READERS:
        getattr(service, name).assert_not_called()
    health.assert_not_called()
    assert result['data']['compact']['quote']['price'] is None
    assert all(row['status'] == 'timeout' for row in result['read_execution']['nodes'])


def test_legacy_ask_params_without_explicit_selection_keep_original_resources(db, owners):
    service, health=owners
    result=agentic_tools.read_crypto_context(db,asset='BTC',market_data_params={
        'explicit_domain_selection':False, 'requested_capabilities':['quote.snapshot'], 'limit':3})
    for name in READERS:
        getattr(service,name).assert_called_once()
    health.assert_called_once()
    assert len(result['data']['ohlcv'])==3
