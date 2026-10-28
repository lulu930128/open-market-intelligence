"""Selected price provenance must not borrow a stale sibling's provider."""
from copy import deepcopy
from datetime import date, datetime

import pytest

from app.ai.taiwan_intraday_contract import resolve_taiwan_current_price
from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
from app.ai.capability_contract import CAPABILITIES, _project_fields
from app.market.quote_depth import get_taiwan_stock_quote_depth
import test_tw_quote_depth_shared_projection as shared
from test_tw_g5_price_safety import quote, NOW


def assert_providers(raw, now, provider):
    before = deepcopy(raw)
    resolved = resolve_taiwan_current_price(quote=raw, intraday_bars={},
        current_session_date=now.date(), checked_at=now)
    for price in (resolved, resolved['decision_price'], resolved['research_price']):
        assert price['provider'] == provider
        assert price['source'] == raw.get('headline_source', raw.get('source'))
        assert price['event_time'] == str(raw['headline_event_time']).replace(' ', 'T')
    assert raw == before
    return resolved


def test_actual_canonical_close_provider_survives_compact_and_public_projection():
    db, engine = shared._db()
    try:
        shared._persist_quote_and_depth(db)
        shared._persist_official_daily_close(db, trade_date=date(2026,8,26), close_price=1182)
        now = datetime(2026,8,26,16,tzinfo=shared.TAIPEI)
        raw = get_taiwan_stock_quote_depth(db=db, stock_id='2330', now=now)
        official = raw['data_core_components']['quote.official_close']
        assert official['provider'] == 'twse_openapi' != raw['provider']
        assert raw['freshness']['is_stale'] is True
        resolved = assert_providers(raw, now, official['provider'])
        assert resolved['value'] == 1182 and resolved['decision_usable'] is True
        compact = _compact_quote_snapshot(latest_daily=None, quote_depth=raw, quote_error=None,
            session_phase='post_close', current_session_date='2026-08-26', is_trading_day=True)
        resolved = assert_providers(compact, now, official['provider'])
        compact.update(current_price=resolved, decision_price=resolved['decision_price'])
        projected = _project_fields(compact, fields=CAPABILITIES['quote.snapshot'].fields, limit=100)
        assert projected['current_price']['provider'] == official['provider']
        assert projected['current_price']['research_price']['provider'] == official['provider']
        assert compact['provider'] == raw['provider']
        assert compact['freshness']['is_stale'] is True
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize('basis', ['session_close','official_close'])
@pytest.mark.parametrize('provider_location', ['provider','lineage'])
def test_selected_close_keeps_snapshot_amount_volume_and_stale_quality(basis, provider_location):
    component = {'available':True, 'decision_usable':True,
        'freshness':{'status':'fresh','is_stale':False},
        **({'provider':'canonical_close'} if provider_location == 'provider' else {'lineage':{'provider':'canonical_close'}})}
    raw = quote(provider='older_snapshot', headline_source='canonical source', headline_basis=basis,
        headline_event_time='2026-10-12T13:30:00+08:00',
        cumulative_volume=123, cumulative_turnover=456,
        cumulative_turnover_time='2026-10-12T12:39:14+08:00', fresh_amount_usable=False,
        freshness={'status':'stale','is_stale':True},
        data_core_components={f'quote.{basis}':component})
    resolved = assert_providers(raw, NOW.replace(hour=14), 'canonical_close')
    assert resolved['decision_usable'] is True and resolved['execution_usable'] is False
    assert raw['provider'] == 'older_snapshot' and raw['freshness']['is_stale'] is True
    assert raw['cumulative_volume'] == 123 and raw['cumulative_turnover'] == 456
    assert raw['cumulative_turnover_time'].endswith('12:39:14+08:00') and raw['fresh_amount_usable'] is False


@pytest.mark.parametrize('basis', ['actual_trade','session_close','official_close'])
def test_snapshot_owned_price_keeps_snapshot_provider_when_close_component_unavailable(basis):
    raw = quote(headline_basis=basis, data_core_components={f'quote.{basis}':{'available':False,'provider':'unselected'}})
    checked = NOW
    if basis != 'actual_trade':
        raw.update(headline_event_time='2026-10-12T13:30:00+08:00')
        checked = NOW.replace(hour=14)
    assert_providers(raw, checked, raw['provider'])


def test_selected_close_without_provider_does_not_guess_from_source_or_reference():
    raw = quote(headline_basis='official_close', headline_source='TWSE RWD Daily Trading',
        headline_event_time='2026-10-12T13:30:00+08:00', change_reference_provider='unrelated_reference',
        data_core_components={'quote.official_close':{'available':True,'decision_usable':True}})
    assert_providers(raw, NOW.replace(hour=14), None)
