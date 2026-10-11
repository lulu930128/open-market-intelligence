"""Real cache-only ask orchestration against disposable, read-only SQLite."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai import agentic_tools, scope_resolution
from app.ai.schemas import AiAskV4Request
from app.db.models import Base, USStockMaster
from app.db.session import get_db
from app.errors import unhandled_exception_handler
from app.market_data.errors import MarketDataContractError
from app.routers import ai as ai_router
from app.us_market.daily_market_state import (
    USInstrumentIdentityUnavailableError,
    resolve_us_instrument_identity,
)
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from test_us_intraday_shared_core import _yahoo_bars_payload


NOW = datetime(2026, 10, 11, 8, tzinfo=timezone.utc)
INCLUDE = ['target.identity', 'intraday.bars', 'quote.snapshot', 'data.freshness']


def request_payload(question, target=None):
    return AiAskV4Request(
        question=question,
        target=target or {'type': 'auto'},
        output='evidence_only',
        realtime_policy='cache_only',
        selection={
            'include': INCLUDE,
            'limits': {'intraday.points': 3},
            'max_response_bytes': 23000,
        },
        refresh_policy={'mode': 'off', 'before_answer': False},
        tool_budget={'max_calls': 0, 'max_external_fetches': 0},
        market_data_params={
            'market': 'us', 'trade_date': '2026-10-09',
            'session_scope': 'regular', 'intraday_interval': '1m',
        },
    )


@pytest.fixture(scope='module')
def engine():
    value = create_engine(
        'sqlite:///:memory:', poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(value)
    with Session(value) as db:
        for symbol in ('AMD', 'SSO', 'BRK-B', 'BF-B', 'AI', 'NODATA', 'NOVENUE'):
            db.add(USStockMaster(
                symbol=symbol, security_name=symbol,
                exchange=None if symbol == 'NOVENUE' else 'NYSE',
                asset_type='stock', listing_source='fixture',
                is_etf=symbol == 'SSO', is_active=True, is_test_issue=False,
            ))
        db.commit()
        # Seed canonical partial history through the existing fixture adapter.
        # No real provider is constructed or contacted; ask itself remains pure.
        for symbol in ('AMD', 'SSO'):
            fixture = _yahoo_bars_payload(
                datetime(2026, 10, 9, 20, tzinfo=timezone.utc), count=6,
            )
            fixture['chart']['result'][0]['meta']['symbol'] = symbol
            platform = USIntradayMarketPlatform(
                db,
                acquisition=USIntradayAcquisitionExecutor(
                    fetchers={YAHOO_INTRADAY_RESOURCE_ID: lambda _route, _requirement: (
                        fixture, 'https://fixture.invalid/intraday',
                    )},
                    clock=lambda: NOW,
                ),
                bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
            )
            seeded = platform.refresh_intraday_bars(
                symbol=symbol, now=NOW, trade_date='2026-10-09', max_provider_calls=1,
            )
            assert seeded.result.persistence.committed is True
        db.execute(text('PRAGMA query_only=ON'))
    yield value
    value.dispose()


@pytest.fixture
def event_loop():
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and not loop.is_closed():
        yield loop
    else:
        loop = asyncio.new_event_loop()
        try:
            yield loop
        finally:
            loop.close()


@pytest.fixture
def db(engine, monkeypatch):
    writes = []
    external_calls = []

    def check_read_only(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() not in {'SELECT', 'PRAGMA', 'WITH'}:
            writes.append(statement)
            raise AssertionError('ask attempted a database mutation')

    def denied(*args, **kwargs):
        external_calls.append(args)
        raise AssertionError('cache-only ask attempted external IO')

    monkeypatch.setattr(agentic_tools, '_now', lambda: NOW)
    monkeypatch.setattr('socket.socket.connect', denied)
    monkeypatch.setattr('socket.getaddrinfo', denied)
    event.listen(engine, 'before_cursor_execute', check_read_only)
    with Session(engine) as session:
        assert session.scalar(text('PRAGMA query_only')) == 1
        yield session
    event.remove(engine, 'before_cursor_execute', check_read_only)
    assert writes == []
    assert external_calls == []


def ask(db, payload):
    # Production router and orchestration: no mocked resolver, reader or response.
    return ai_router.ask_omi(
        request=SimpleNamespace(headers={}, client=None), payload=payload, db=db,
    )


QUESTIONS = [
    '請以 cache-only 讀取美股 {symbol}',
    '請以 CACHE-ONLY 讀取美股 {symbol}',
    '請以 alpha-beta 讀取美股 {symbol}',
    '請以 ALPHA-BETA 讀取美股 {symbol}',
    '{symbol} 請以 cache-only 讀取美股',
    '{symbol} 請以 alpha-beta 讀取美股',
    '請讀取美股 {symbol}，使用 cache-only',
    '請讀取美股 {symbol}，使用 alpha-beta',
    '請以快取讀取美股 {symbol}',
    '請讀取美股 {symbol}',
    'Please read US stock {symbol} with alpha-beta',
]


@pytest.mark.parametrize('symbol', ['AMD', 'amd', 'SSO', 'sso', 'BRK-B', 'brk-b', 'BF-B', 'bf-b'])
@pytest.mark.parametrize('question', QUESTIONS)
def test_auto_symbol_uses_real_ask(db, symbol, question):
    payload = request_payload(question.format(symbol=symbol))
    result = ask(db, payload)
    assert result['contract_version'] == 'omi.decision.v4'
    assert result['target']['type'] == 'us_stock'
    assert result['target']['id'] == symbol.upper()
    assert not result['execution'].get('tool_runs')
    assert set(result['evidence']['data']) <= set(INCLUDE)
    assert result['limitations']['missing']
    assert result['status']['readiness']['decision_ready'] is False


@pytest.mark.parametrize('symbol', ['AMD', 'SSO', 'BRK-B', 'BF-B', 'ZZZZZZ', 'NODATA', 'NOVENUE'])
def test_explicit_target_wins_and_missing_data_is_truthful(db, symbol):
    result = ask(db, request_payload(
        '請以 alpha-beta 讀取美股 AMD 與 SSO', {'type': 'us_stock', 'id': symbol},
    ))
    assert result['target']['id'] == symbol
    assert result['limitations']['missing']
    assert result['status']['readiness']['decision_ready'] is False
    assert not result['execution'].get('tool_runs')
    if symbol in {'ZZZZZZ', 'NOVENUE'}:
        assert result['evidence']['quality']['capabilities']['intraday.bars']['status'] == 'unavailable'
        assert result['evidence']['data']['quote.snapshot']['price'] is None
        gaps = agentic_tools.scan_us_stock_gaps(db, symbol, question='美股日線')
        assert 'us_daily_price' in gaps['missing']
        assert gaps['is_current'] is False
        assert any('identity is unavailable' in item for item in gaps['warnings'])


@pytest.mark.parametrize('symbol', ['ZZZZZZ', 'zzzzzz', 'NEW-B', 'new-b'])
@pytest.mark.parametrize('question', QUESTIONS)
def test_contextual_unknown_remains_resolvable_without_becoming_control_word(db, symbol, question):
    result = ask(db, request_payload(question.format(symbol=symbol)))
    assert result['target']['id'] == symbol.upper()
    assert result['limitations']['missing']
    assert result['status']['readiness']['decision_ready'] is False


@pytest.mark.parametrize('question,expected', [
    ('請以 arbitrary-command 讀取美股 AMD', 'AMD'),
    ('請以 mystery 讀取美股 SSO', 'SSO'),
    ('美股 AMD SSO', 'AMD'),
    ('美股 SSO AMD', 'SSO'),
    ('美股 AMD $ZZZZZZ', 'ZZZZZZ'),
    ('美股 $ZZZZZZ $AMD', 'ZZZZZZ'),
    ('美股 AMD NYSE:NEW-B', 'NEW-B'),
    ('美股 $UNKNOWN-WT', 'UNKNOWN-WT'),
    ('美股 AI', 'AI'),
    ('SOX 半導體指數最新行情', '^SOX'),
])
def test_resolver_evidence_priority_and_explicit_markers(db, question, expected):
    result = scope_resolution._resolve_scope(db=db, payload=request_payload(question))
    assert result.selected_scope_id == expected


def test_missing_identity_error_is_narrow_and_lookup_compatible(db):
    with pytest.raises(USInstrumentIdentityUnavailableError) as error:
        resolve_us_instrument_identity(db, 'ZZZZZZ')
    assert isinstance(error.value, LookupError)


@pytest.mark.parametrize('symbol', ['AMD', 'SSO'])
def test_auto_and_explicit_preserve_selected_cached_partial_bars(db, symbol):
    question = f'請以 cache-only 讀取美股 {symbol}'
    auto = ask(db, request_payload(question))
    explicit = ask(db, request_payload(question, {'type': 'us_stock', 'id': symbol}))
    auto_bars = auto['evidence']['data']['intraday.bars']
    assert auto_bars == explicit['evidence']['data']['intraday.bars']
    assert auto_bars['requested_trade_date'] == '2026-10-09'
    assert auto_bars['session_coverage']['requested_scope'] == 'regular'
    assert auto_bars['session_coverage']['point_count'] == 6
    assert auto_bars['session_coverage']['expected_point_count'] == 390
    assert auto_bars['session_coverage']['missing_slot_count'] == 384
    assert auto_bars['session_coverage']['coverage_status'] == 'partial'
    assert auto_bars['is_partial'] is True
    assert auto['evidence']['quality']['capabilities']['intraday.bars']['decision_usable'] is False
    assert auto_bars['returned_point_count'] == 3
    # Default evidence-only summary omits point rows; the selected reader limit
    # and canonical coverage must survive that existing projection.
    assert len(auto_bars.get('points', [])) <= 3


@pytest.mark.parametrize('failure', [
    KeyError('broken projection'),
    LookupError('unrelated lookup failure'),
    MarketDataContractError('invalid canonical evidence'),
    OperationalError('fixture SQL', {}, Exception('database failure')),
])
def test_freshness_does_not_swallow_unrelated_failures(db, failure):
    with patch.object(USDailyOhlcvPlatform, 'read', side_effect=failure):
        with pytest.raises(type(failure)) as caught:
            agentic_tools.scan_us_stock_gaps(db, 'AMD', question='美股日線')
    assert caught.value is failure


@pytest.mark.parametrize('question,target,expected', [
    ('請以 cache-only 讀取美股 AMD', None, 'AMD'),
    ('請以 alpha-beta 讀取美股 SSO', None, 'SSO'),
    ('請以 cache-only 讀取美股 AMD', {'type': 'us_stock', 'id': 'AMD'}, 'AMD'),
    ('請以快取讀取美股 ZZZZZZ', {'type': 'us_stock', 'id': 'ZZZZZZ'}, 'ZZZZZZ'),
])
def test_http_router_serializes_complete_v4_request(event_loop, db, question, target, expected):
    app = FastAPI()
    app.include_router(ai_router.router, prefix='/api/ai')
    app.dependency_overrides[get_db] = lambda: db
    app.add_exception_handler(Exception, unhandled_exception_handler)
    messages = []
    payload = request_payload(question, target).model_dump(mode='json')

    async def receive():
        return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}

    async def send(message):
        messages.append(message)

    # The offline test runner creates the loop before denying network access;
    # Windows uses a loopback socketpair to initialize an asyncio event loop.
    event_loop.run_until_complete(app({
        'type': 'http', 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
        'path': '/api/ai/ask', 'query_string': b'',
        'headers': [(b'content-type', b'application/json')],
        'client': ('offline', 1), 'server': ('fixture', 80),
    }, receive, send))
    assert messages[0]['status'] == 200
    body = b''.join(message.get('body', b'') for message in messages)
    assert len(body) <= 23000
    result = json.loads(body)
    assert result['contract_version'] == 'omi.decision.v4'
    assert result['target']['id'] == expected
    assert not result['execution'].get('tool_runs')
    assert result['limitations']['missing']
