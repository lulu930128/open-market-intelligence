"""Resource public bars keep each selected interval in its own capability."""
from datetime import timedelta
from unittest.mock import patch
import pytest
from app.ai import agentic_tools
from app.db.models import ResourceOhlcvBar
from app.resource_market import service
from app.resource_market.contract import list_resource_instruments
from test_resource_ask_refresh import db, isolated_clock_and_network, NOW, ask  # noqa: F401


def seed_bars(db, intervals):
    instrument = list_resource_instruments(symbol='GC')[0]
    values = {name: getattr(instrument, name) for name in (
        'provider', 'exchange', 'symbol', 'provider_symbol', 'name', 'root_folder',
        'group', 'asset_class', 'base_asset', 'quote_asset', 'instrument_type')}
    for interval in intervals:
        for i in range(5):
            db.add(ResourceOhlcvBar(**values, contract_key=instrument.contract_type,
                interval=interval, bar_time=NOW - timedelta(days=20, minutes=i) if interval == '1m' else NOW - timedelta(days=20+i),
                open_price=100, high_price=102, low_price=99, close_price=101,
                volume=0 if i==0 else None, fetched_at=NOW,
                source_url='https://example.invalid/fixture'))
    db.commit()

@pytest.mark.parametrize('available', [('1m', '1d'), ('1m',), ('1d',)])
def test_public_resource_daily_and_intraday_are_separate_bounded_cache_reads(db, available):
    seed_bars(db, available)
    with patch.object(service, 'list_resource_ohlcv_bars', wraps=service.list_resource_ohlcv_bars) as read, \
         patch.object(service, 'fetch_yahoo_chart_payload_for_interval', side_effect=AssertionError('network forbidden')) as fetch:
        result = ask(db, allow_external_fetch=False, realtime_policy='cache_only',
            refresh_policy={'mode':'off','before_answer':False}, payload_level='full',
            market_data_params={'interval':'1m', 'intraday_interval':'1m', 'include_intraday':True},
            tool_budget={'max_calls':2,'max_external_fetches':0,'max_total_seconds':20},
            selection={'include':['resource.metadata','daily.ohlcv','intraday.bars'],
                       'limits':{'daily.ohlcv':3,'intraday.bars':3},'max_response_bytes':200000})
    assert result['request_valid'] is True
    data = result['evidence']['data']
    for capability, interval in [('daily.ohlcv','1d'), ('intraday.bars','1m')]:
        series = data.get(capability, {})
        rows = series.get('bars', []) if isinstance(series, dict) else series
        if interval in available:
            assert len(rows) == 3 and {row['interval'] for row in rows} == {interval}
            assert [row['bar_time'] for row in rows] == sorted(row['bar_time'] for row in rows)
            assert rows[-1]['volume'] == 0 and rows[0]['volume'] is None
            assert all(row['provider']=='yahoo_chart' for row in rows)
        else:
            assert not rows
        quality = result['evidence']['quality']['capabilities'][capability]
        assert quality['decision_usable'] is False
    assert [(call.kwargs['interval'], call.kwargs['limit']) for call in read.call_args_list] == [('1d',3),('1m',3)]
    fetch.assert_not_called()
    assert result['execution']['tool_runs'] == []


def test_legacy_resource_chart_default_retains_daily_shape(db):
    seed_bars(db, ('1d','1m'))
    result = agentic_tools.read_resource_asset_context(db, symbol='GC', market_data_params={'limit':3})
    assert result['data']['interval'] == '1d'
    assert len(result['data']['chart']) == 3
    assert {row['interval'] for row in result['data']['chart']} == {'1d'}
