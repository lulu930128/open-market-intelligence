"""Synthetic incident shapes, never live quotes: raw -> canonical -> Gateway.

No provider, subscription or database IO. Synthetic symbol/price combinations
prove contracts only; they are not Oct 19 raw receipts or coverage evidence.
"""
from datetime import datetime, timedelta
import hashlib
import json
import socket
from pathlib import Path

import pytest

from app.market.providers.tw_public_quote import parse_twse_mis_quote_payload, quote_observation_from_twse_mis
from app.market.providers.twse_mis_current_breadth import _classify_message
from app.market.public_quote_platform import (
    TaiwanPublicQuoteCandidateReader, build_taiwan_public_quote_requirement,
    project_taiwan_public_last_trade_quote,
)
from app.market.public_quote_repository import PersistedPublicQuoteRead
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import InstrumentKey, InstrumentType, Market, MarketSession
from app.market_data.gateway import MarketDataGateway
from app.market_data.policies import RealtimePolicy

NOW = datetime(2026, 10, 19, 9, 23, tzinfo=TAIWAN_TZ)
SYMBOLS = [('2308', 'TWSE'), ('2221', 'TWSE'), ('2330', 'TWSE'),
           ('3324', 'TPEX'), ('2883', 'TWSE'), ('6173', 'TPEX')]


def test_representative_venues_are_backed_by_existing_receipts():
    fixtures = Path(__file__).parent / 'fixtures/tw_market_data'
    daily = json.loads((fixtures / 'g6_daily_received_excerpt.json').read_text(encoding='utf-8'))
    assert any(row['SecuritiesCompanyCode'] == '3324' for row in daily['tpex'])
    quotes = json.loads((fixtures / 'twse_mis_public_quote_actual_20260825.json').read_text(encoding='utf-8'))
    assert any(row['stock_id'] == '6173' and row['venue'] == 'TPEX' for row in quotes['records'])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('offline source evidence cannot connect')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def message(symbol, **updates):
    return dict(c=symbol, d='20261019', t='09:23:00', z='110', y='100', v='5',
                tv='1', ts='0', pz='999', ps='9', b='109_', a='111_', **updates)


@pytest.mark.parametrize('symbol,venue', SYMBOLS)
@pytest.mark.parametrize('case', ['valid', 'missing', 'trial', 'stale', 'noncurrent'])
def test_raw_canonical_candidate_gateway_keeps_price_authority(symbol, venue, case):
    updates = {'missing': {'z': '-'}, 'trial': {'ts': '1'},
               'stale': {'t': '09:00:01'}, 'noncurrent': {'d': '20261016'}}.get(case, {})
    raw = json.dumps({'rtcode': '0000', 'msgArray': [{**message(symbol), **updates}]})
    parsed = parse_twse_mis_quote_payload(raw, target_symbol=symbol)
    instrument = InstrumentKey(market=Market.TW, symbol=symbol, venue=venue, instrument_type=InstrumentType.STOCK)
    observation = quote_observation_from_twse_mis(instrument=instrument, message=parsed,
        session=MarketSession.CONTINUOUS, received_at=NOW, fetched_at=NOW,
        content_hash=hashlib.sha256(raw.encode()).hexdigest())
    if case in {'missing', 'trial'}:
        assert observation.last_trade_price is None
    else:
        assert observation.last_trade_price == 110
    # The storage seam supplies the same cache/receipt lineage as the real
    # repository; the raw converter itself must not pretend it read a cache.
    observation = observation.model_copy(update={'lineage': observation.lineage.model_copy(update={
        'cache_hit': True, 'observation_id': 'taiwan_stock_quote_snapshot:1',
        'raw_receipt_id': 'raw_fetch_result:1',
    })})
    stored = PersistedPublicQuoteRead(observation=observation, storage_row_id=1, raw_result_id=1,
                                     market_session=MarketSession.CONTINUOUS)
    class Repository:
        def load_quote_candidates(self, *args, **kwargs):
            return (stored,)
    requirement = build_taiwan_public_quote_requirement(instrument=instrument,
        policy=RealtimePolicy.CACHE_ONLY, requested_at=NOW)
    assert requirement.freshness.max_age_seconds == 15
    result = MarketDataGateway().resolve_quote(requirement, reader=TaiwanPublicQuoteCandidateReader(Repository()))
    assert not result.acquisition.attempted and not result.persistence.committed
    projection = project_taiwan_public_last_trade_quote(result)
    assert projection['freshness']['is_live'] is (case == 'valid')
    if case == 'valid':
        assert result.resolved.quote.last_trade_price == 110
    elif case in {'missing', 'trial', 'noncurrent'}:
        assert result.resolved.quote is None
        assert result.candidate_rejections
    else:
        assert projection['freshness']['status'] == 'stale'


@pytest.mark.parametrize('symbol,venue', SYMBOLS)
@pytest.mark.parametrize('increased', [False, True])
def test_missing_z_cache_never_refreshes_event_clock(symbol, venue, increased):
    prior_at = NOW - timedelta(minutes=22, seconds=59)
    prior = dict(trade_date=NOW.date(), price=110, price_as_of=prior_at,
                 has_actual_trade=True, cumulative_volume_lots=5)
    row = _classify_message({**message(symbol), 'z': '-', 'v': '6' if increased else '5'},
                            venue, cached_state=prior)
    assert row['actual_trade_reason_code'] == 'ACTUAL_TRADE_PRICE_MISSING'
    if increased:
        assert row['current_price'] is None
        assert row['cache_rejection_reason'] == 'SESSION_CACHE_VOLUME_INCREASED'
    else:
        assert row['current_price'] == 110
        assert row['price_as_of'] == prior_at
        assert row['price_source'] == 'session_cache'


@pytest.mark.parametrize('entitled', [False, True])
def test_tier_a_entitlement_is_required_by_existing_plan(entitled):
    from test_tw_realtime_capabilities import _requirement, _health, KGI_QUOTE_SNAPSHOT_DESCRIPTOR
    from app.market_data.contracts import EntitlementStatus
    from app.market_data.provider_catalog import plan_data_acquisition_v2
    descriptor = KGI_QUOTE_SNAPSHOT_DESCRIPTOR
    requirement = _requirement(descriptor, session=MarketSession.CONTINUOUS)
    health = _health(descriptor.capability_id).model_copy(update={
        'entitlement': EntitlementStatus.ENTITLED if entitled else EntitlementStatus.PLAN_RESTRICTED,
    })
    plan = plan_data_acquisition_v2(requirement, (descriptor,), (health,))
    assert bool(plan.routes) is entitled
