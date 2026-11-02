"""Source acceptance: real v4 orchestration, isolated stores, no external IO."""
from datetime import timedelta

import pytest

from app.ai.schemas import AiAskV4Request
from app.us_market import service
from app.us_market.market_truth import read_us_market_truth_bundle
from app.market_data.contracts import EvidenceFreshness
from test_ai_us_symbol_resolution import ask, db, engine  # noqa: F401
from test_us_market_truth_snapshot import (
    EVALUATED_AT, _fake_components, _install_fake_components,
)


def request(question, *, params=None, include=None):
    return AiAskV4Request(
        question=question, target={'type': 'auto'}, output='evidence_only',
        realtime_policy='cache_only',
        selection={'include': include or ['target.identity', 'quote.snapshot', 'data.freshness'],
                   'max_response_bytes': 30000},
        refresh_policy={'mode': 'off', 'before_answer': False},
        tool_budget={'max_calls': 0, 'max_external_fetches': 0},
        market_data_params=params or {},
    )


@pytest.mark.parametrize('question,params,kind,symbol', [
    ('請問美股 S&P 500、Nasdaq 與 Dow Jones 目前表現如何？', {}, 'market', 'US'),
    ('美股盤中廣度有資料嗎？若沒有請標 missing/stale。', {}, 'market', 'US'),
    ('請告訴我美股大盤目前主要指數的漲跌情況。', {}, 'market', 'US'),
    ('S&P500 目前表現如何？', {}, 'market', 'US'),
    ('Nasdaq 目前表現如何？', {}, 'market', 'US'),
    ('Dow Jones 目前表現如何？', {}, 'market', 'US'),
    ('美股大盤 MISSING/STALE', {}, 'market', 'US'),
    ('美股 missing/stale', {}, 'market', 'US'),
    ('大盤目前表現', {'market': 'us'}, 'market', 'US'),
    ('S', {}, 'us_stock', 'S'),
    ('美股 S 報價', {}, 'us_stock', 'S'),
    ('$S 報價', {}, 'us_stock', 'S'),
    ('NYSE:S 報價', {}, 'us_stock', 'S'),
    ('美股 S&P 500 與 $S 報價', {}, 'us_stock', 'S'),
    ('美股 TSM 報價 missing/stale', {}, 'us_stock', 'TSM'),
    ('美股 NVDA 報價', {}, 'us_stock', 'NVDA'),
    ('台積電報價', {}, 'tw_stock', '2330'),
    ('台股大盤目前表現', {}, 'market', 'TW'),
    ('日股大盤目前表現', {}, 'market', 'JP'),
    ('韓股大盤目前表現', {}, 'market', 'KR'),
    ('日股 7203.T 報價', {'market': 'jp'}, 'jp_stock', '7203.T'),
    ('韓股 005930 報價', {'market': 'kr'}, 'kr_stock', '005930.KS'),
])
def test_market_and_stock_target_selection_end_to_end(db, question, params, kind, symbol):
    payload = request(question, params=params, include=(
        ['target.identity', 'market.indices', 'market.breadth', 'data.freshness']
        if kind == 'market' else None
    ))
    result = ask(db, payload)
    assert result['contract_version'] == 'omi.decision.v4'
    assert (result['target']['type'], result['target']['id']) == (kind, symbol)
    assert not result['execution'].get('tool_runs')
    assert set(result['evidence']['data']) <= set(payload.selection['include'])


@pytest.mark.parametrize('question,params', [
    ('2330 台積電與 $S 報價', {}),
    ('美股 NVDA 報價', {'market': 'tw', 'symbol': '2330'}),
])
def test_cross_market_target_conflict_end_to_end(db, question, params):
    result = ask(db, request(question, params=params))
    assert result['target'].get('id') is None
    assert not result['execution'].get('tool_runs')
    assert result['status']['readiness']['decision_ready'] is False


@pytest.mark.parametrize('quote_freshness,bar_freshness', [
    ('stale', 'fresh'), ('fresh', 'stale'), ('delayed', 'fresh'), ('provider_delayed', 'fresh'),
])
def test_quote_facade_and_ask_keep_independent_evidence(db, monkeypatch, quote_freshness, bar_freshness):
    quote, bars, daily = _fake_components()
    event_at = EVALUATED_AT - timedelta(seconds=30)
    if quote_freshness in {'delayed', 'provider_delayed'}:
        quote_event = EVALUATED_AT - timedelta(seconds=150 if quote_freshness == 'delayed' else 901)
        quote = quote.model_copy(update={
            'quote': quote.quote.model_copy(update={
                'lineage': quote.quote.lineage.model_copy(update={
                    'event_at': quote_event, 'fetched_at': EVALUATED_AT,
                }),
            }),
            'health': quote.health.model_copy(update={'selected_event_at': quote_event}),
        })
    quote = quote.model_copy(update={
        'candidates': (quote.candidates[0].model_copy(update={
            'freshness': EvidenceFreshness.STALE if quote_freshness == 'stale' else EvidenceFreshness.FRESH,
        }),),
    })
    bar = bars.bars[-1].model_copy(update={
        'start_at': event_at - timedelta(minutes=1), 'end_at': event_at,
        'lineage': bars.bars[-1].lineage.model_copy(update={'event_at': event_at, 'fetched_at': event_at}),
    })
    bars = bars.model_copy(update={
        'bars': (bar,),
        'health': bars.health.model_copy(update={'selected_event_at': event_at}),
        'candidates': (bars.candidates[0].model_copy(update={
            'event_at': event_at, 'freshness': EvidenceFreshness(bar_freshness),
        }),),
    })
    _install_fake_components(monkeypatch, (quote, bars, daily))
    bundle = read_us_market_truth_bundle(db, symbol='AAPL', evaluated_at=EVALUATED_AT, requested_scope='all')
    monkeypatch.setattr(service, 'read_us_market_truth_bundle', lambda *args, **kwargs: bundle)
    projection = service._market_truth_compat_intraday_payload(bundle=bundle, session_scope='all', interval='1m')
    snapshot = service.get_us_quote_snapshot(db, symbol='AAPL', now=EVALUATED_AT)
    expected = {'fresh': 'current', 'provider_delayed': 'stale'}.get(quote_freshness, quote_freshness)
    assert snapshot['status'] == snapshot['source_status']['status'] == expected
    assert snapshot['research_usable'] == snapshot['source_status']['decision_usable'] == (expected == 'current')
    assert snapshot['source_status']['as_of'] == snapshot['selected_event_at']
    assert projection['bar_source_status']['status'] == ('current' if bar_freshness == 'fresh' else bar_freshness)
    assert projection['current_source_status']['as_of'] == projection['current_observation']['observed_at']
    assert snapshot['quote']['previous_close'] != snapshot['quote']['provider_previous_close_hint']
    result = ask(db, request('美股 AAPL 報價', include=['target.identity', 'quote.snapshot']))
    outward = result['evidence']['data']['quote.snapshot']
    assert outward['source_status']['status'] == expected
    assert outward['status'] == expected
    assert outward['research_usable'] == (expected == 'current')
    assert outward['source_status']['decision_usable'] == (expected == 'current')
    if expected != 'current':
        assert result['evidence']['quality']['capabilities']['quote.snapshot']['decision_usable'] is False
