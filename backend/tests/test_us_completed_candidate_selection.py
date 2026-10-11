"""Offline regressions from the 2026-10-08/09 candidate evidence shape."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.db.models import MarketIntradayBarLineage
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import (
    YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID,
    TWELVE_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_RESOURCE_ID,
)
from app.us_market.market_truth import read_us_historical_intraday_trend
from test_us_intraday_shared_core import _db, _yahoo_bars_payload, _twelve_bars_payload

DAY = date(2026, 10, 8)
START = datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)
END = START + timedelta(minutes=390)
NOW = datetime(2026, 10, 9, 17, 33, tzinfo=timezone.utc)


def seeded_candidates(yahoo_count, twelve_count, provisional=0):
    db = _db()
    for descriptor, resource, payload in (
        (YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID,
         _yahoo_bars_payload(START + timedelta(minutes=yahoo_count), count=yahoo_count)),
        (TWELVE_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_RESOURCE_ID,
         _twelve_bars_payload(END, count=twelve_count)),
    ):
        platform = USIntradayMarketPlatform(db, bar_descriptors=(descriptor,),
            acquisition=USIntradayAcquisitionExecutor(
                fetchers={resource: lambda *_args, value=payload: (value, 'https://fixture.invalid/bars')},
                clock=lambda: NOW,
            ))
        platform.refresh_intraday_bars(symbol='AAPL', trade_date=DAY, now=NOW, max_provider_calls=1)
    for lineage in db.query(MarketIntradayBarLineage).filter_by(provider='yahoo_chart').limit(provisional):
        lineage.finalization = 'provisional'
    db.commit()
    return db


@pytest.mark.parametrize('yahoo_count,twelve_count,provisional,expected,count,partial', [
    (390, 390, 2, 'twelve_data', 390, False),
    (236, 390, 1, 'twelve_data', 390, False),
    (236, 387, 1, 'twelve_data', 387, True),
    (236, 387, 0, 'twelve_data', 387, True),
    (387, 236, 0, 'yahoo_chart', 387, True),
    (390, 390, 0, 'yahoo_chart', 390, False),
])
def test_completed_regular_requires_whole_final_candidate_before_priority(
    yahoo_count, twelve_count, provisional, expected, count, partial,
):
    db = seeded_candidates(yahoo_count, twelve_count, provisional)
    with patch.object(USIntradayAcquisitionExecutor, 'acquire_bar_observations', side_effect=AssertionError('GET acquired')):
        result = read_us_historical_intraday_trend(db, symbol='AAPL', trade_date=DAY, evaluated_at=NOW)
    assert result['source_status']['provider'] == expected
    assert result['point_count'] == count
    assert result['is_partial'] is partial
    assert result['decision_usable'] is False
    assert result['is_live'] is False
    assert result['session_coverage']['missing_slot_count'] == 390 - count
    assert result['source_status']['facts_usable'] is True
    if expected == 'twelve_data':
        assert 'PARTIAL_US_MARKET_VOLUME' in result['warnings']
        assert 'PERSONAL_INTERNAL_USE_ONLY' in result['warnings']
        assert all(point['volume_based_decision_usable'] is False for point in result['points'])
        assert result['research_usable'] is False
    else:
        assert 'PARTIAL_US_MARKET_VOLUME' not in result['warnings']
    db.close()


def test_current_read_keeps_existing_priority_and_provisional_visibility():
    db = seeded_candidates(390, 390, 2)
    result = USIntradayMarketPlatform(db).read_intraday_bars_for_trade_date(
        symbol='AAPL', trade_date=DAY, now=NOW,
    )
    assert result.result.resolved.health.selected_provider == 'yahoo_chart'
    assert result.result.acquisition.external_calls == 0
    assert not result.result.persistence.attempted
    assert sum(b.finalization.value == 'provisional' for b in result.result.resolved.bars) == 2
    db.close()


def test_deeper_ineligible_lineage_cannot_win_partial_coverage_fallback():
    db = seeded_candidates(236, 387)
    for lineage in db.query(MarketIntradayBarLineage).filter_by(provider='twelve_data'):
        lineage.raw_contract_version = 'invalid.fixture.contract'
    db.commit()
    result = read_us_historical_intraday_trend(db, symbol='AAPL', trade_date=DAY, evaluated_at=NOW)
    assert result['source_status']['provider'] == 'yahoo_chart'
    assert result['point_count'] == 236
    assert result['is_partial'] is True
    db.close()


def test_complete_candidate_can_include_corrected_bars_and_excludes_close_boundary():
    db = seeded_candidates(390, 390, 2)
    lineage = db.query(MarketIntradayBarLineage).filter_by(provider='twelve_data').first()
    lineage.finalization = 'corrected'
    db.commit()
    result = USIntradayMarketPlatform(db).read_intraday_bars_for_trade_date(
        symbol='AAPL', trade_date=DAY, now=NOW, completed_regular=True,
    )
    assert result.result.resolved.health.selected_provider == 'twelve_data'
    assert len(result.result.resolved.bars) == 390
    assert all(START <= bar.start_at < END for bar in result.result.resolved.bars)
    assert result.result.acquisition.external_calls == 0
    assert not result.result.persistence.attempted
    from app.market_data.integration_contracts import DataRequirementV2
    for field, value in [('completed_only', False), ('series_resolution', 'compose_by_timestamp')]:
        invalid = result.result.requirement.model_dump()
        invalid['request'][field] = value
        with pytest.raises(ValueError, match='partial coverage fallback requires'):
            DataRequirementV2.model_validate(invalid)
    invalid = result.result.requirement.model_dump()
    invalid['realtime_policy'] = 'prefer_live'
    with pytest.raises(ValueError, match='partial coverage fallback requires'):
        DataRequirementV2.model_validate(invalid)
    db.close()


def test_unchanged_ohlcv_finalization_transition_is_persisted_and_invalidates_cache():
    db = _db()
    clock = [START + timedelta(seconds=30)]
    payload = _yahoo_bars_payload(START + timedelta(minutes=1), count=1)
    calls = []
    def fetch(*_args):
        calls.append(clock[0])
        return payload, 'https://fixture.invalid/bars'
    platform = USIntradayMarketPlatform(db, bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: clock[0],
        ))
    acquired = []
    acquire = platform._acquisition.acquire_bar_observations
    def capture(*args):
        result = acquire(*args)
        acquired.append(result)
        return result
    with patch.object(platform._acquisition, 'acquire_bar_observations', side_effect=capture):
        first = platform.refresh_intraday_bars(symbol='AAPL', now=clock[0], max_provider_calls=1)
    assert db.query(MarketIntradayBarLineage).one().finalization == 'provisional'
    clock[0] = START + timedelta(minutes=2)
    with patch('app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache') as invalidate:
        final = platform.refresh_intraday_bars(symbol='AAPL', now=clock[0], max_provider_calls=1)
    assert final.result.persistence.observations_written == 1
    assert final.result.persistence.observations_unchanged == 0
    assert db.query(MarketIntradayBarLineage).one().finalization == 'final'
    invalidate.assert_called_once_with('AAPL')
    with patch('app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache') as invalidate:
        late = platform._bar_transaction.persist_bar_acquisition(first.result.requirement, acquired[0])
    assert late.observations_written == 0
    assert db.query(MarketIntradayBarLineage).one().finalization == 'final'
    invalidate.assert_not_called()
    clock[0] += timedelta(minutes=2)
    with patch('app.us_market.intraday_read_model_cache.invalidate_us_intraday_read_cache') as invalidate:
        repeated = platform.refresh_intraday_bars(symbol='AAPL', now=clock[0], max_provider_calls=1)
    assert repeated.result.persistence.observations_written == 0
    assert repeated.result.persistence.observations_unchanged == 1
    invalidate.assert_not_called()
    assert len(calls) == 3
    assert first.result.acquisition.external_calls == final.result.acquisition.external_calls == 1
    db.close()
