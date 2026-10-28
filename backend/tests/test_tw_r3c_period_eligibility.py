"""Frozen pre-R3C all(...) is the independent equivalence/cost oracle."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.market import tw_bar_service as owner
from app.db.models import StockMaster
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row

NOW = datetime(2026,8,26,4,tzinfo=timezone.utc)


def legacy_predicate(paired):
    # Exact original inclusive filter and empty-all semantics; no new index.
    def eligible(start_at, end_at):
        return all(state.technical_eligible for base, state in paired
                   if start_at <= base.start_at <= end_at)
    return eligible


@pytest.mark.parametrize('offsets,flags', [
    ([], []), ([0,1,2,3],[True]*4), ([0,1,2,3],[False,True,True,False]),
    ([0,1,1,2],[True,True,False,True]), ([3,1,0,1,2],[False,True,True,False,True]),
])
def test_inclusive_duplicate_empty_and_unordered_pairing(offsets, flags):
    pairs = [(SimpleNamespace(start_at=NOW+timedelta(days=offset)),
              SimpleNamespace(technical_eligible=flag)) for offset,flag in zip(offsets,flags)]
    reference = legacy_predicate(pairs)
    # The service already sorts pairs together; never sort flags independently.
    actual = owner._period_technical_eligibility(sorted(pairs,key=lambda pair:pair[0].start_at))
    for first in range(-1,5):
        for last in range(-1,5):
            assert actual(NOW+timedelta(days=first), NOW+timedelta(days=last)) == reference(
                NOW+timedelta(days=first), NOW+timedelta(days=last))


def test_index_removes_full_history_scan_per_period():
    class CountedTime(datetime):
        comparisons = 0
        def __lt__(self, other):
            type(self).comparisons += 1
            return super().__lt__(other)
        def __le__(self, other):
            type(self).comparisons += 1
            return super().__le__(other)
        def __gt__(self, other):
            type(self).comparisons += 1
            return super().__gt__(other)
        def __ge__(self, other):
            type(self).comparisons += 1
            return super().__ge__(other)
    starts = [CountedTime(2020,1,1,tzinfo=timezone.utc)+timedelta(days=i) for i in range(1000)]
    paired = [(SimpleNamespace(start_at=at), SimpleNamespace(technical_eligible=True)) for at in starts]
    CountedTime.comparisons = 0
    old = legacy_predicate(paired)
    expected = [old(starts[i], starts[i+1]) for i in range(0,998,2)]
    old_comparisons = CountedTime.comparisons
    CountedTime.comparisons = 0
    new = owner._period_technical_eligibility(paired)
    assert [new(starts[i], starts[i+1]) for i in range(0,998,2)] == expected
    assert CountedTime.comparisons < 12000 < old_comparisons


@pytest.mark.parametrize('interval',['1w','1mo'])
@pytest.mark.parametrize('partial',[False,True])
def test_real_service_full_json_and_four_identities_match_legacy(db, monkeypatch, tmp_path, interval, partial):
    from app.config import settings
    monkeypatch.setattr(settings,'tw_corporate_event_cache_path',tmp_path/'absent.json')
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    db.add(StockMaster(stock_id='2330',stock_name='fixture',market='TWSE',instrument_type='stock'))
    first = date(2026,3,1)
    db.add_all([_daily_row(source=source,raw=raw,trade_date=first+timedelta(days=i)) for i in range(177)])
    db.commit()
    import test_tw_bar_service as intraday
    intraday._seed_session(db, trade_date=NOW.astimezone(owner.TAIWAN_TZ).date(),
        provider=intraday.FUGLE_INTRADAY_PROVIDER, source_name=intraday.FUGLE_INTRADAY_SOURCE,
        parser_version=intraday.FUGLE_INTRADAY_PARSER_VERSION, authority='vendor', minutes=5)
    service = owner.TaiwanBarService(db)
    original = service._completed_daily_inputs
    def unordered_inputs(repository, requirement):
        result,bars,states,metadata = original(repository,requirement)
        assert len(bars) > 50
        # Legal canonical bars with a duplicate timestamp, distinct lineage and
        # a conflicting outward qualification flag. Preserve pairing in sort.
        duplicate = bars[10].model_copy(update={'lineage':bars[10].lineage.model_copy(
            update={'observation_id':'fixture:duplicate'})})
        metadata = {**metadata, 'fixture:duplicate':{'reconciliation_status':'mismatched'}}
        return result,tuple(reversed((*bars,duplicate))),states,metadata
    monkeypatch.setattr(service,'_completed_daily_inputs',unordered_inputs)
    request = dict(instrument_id='2330',interval=interval,limit=1800,
        from_time=datetime(2026,3,1,tzinfo=timezone.utc),to_time=NOW,
        requested_at=NOW,include_partial=partial)
    with patch.object(owner,'_period_technical_eligibility',legacy_predicate):
        expected = service.read_bars(**request).model_dump(mode='json')
    actual = service.read_bars(**request).model_dump(mode='json')
    assert actual == expected
    assert actual['bars'] and any(not row['technical_eligible'] for row in actual['bar_states'])
    if partial:
        assert actual['bars'][-1]['finalization'] == 'provisional'
        assert actual['bar_states'][-1]['technical_eligible'] is False
    else:
        assert all(bar['finalization'] != 'provisional' for bar in actual['bars'])
    for key in ('series_fingerprint','lineage_digest','state_digest','series_revision'):
        assert actual['identity'][key] == expected['identity'][key]


@pytest.mark.parametrize('interval',['1w','1mo'])
def test_actual_empty_service_keeps_missing_series(db, monkeypatch, tmp_path, interval):
    from app.config import settings
    monkeypatch.setattr(settings,'tw_corporate_event_cache_path',tmp_path/'absent.json')
    db.add(StockMaster(stock_id='2330',stock_name='fixture',market='TWSE',instrument_type='stock'))
    db.commit()
    request = dict(instrument_id='2330',interval=interval,requested_at=NOW,include_partial=False,limit=1800)
    service = owner.TaiwanBarService(db)
    with patch.object(owner,'_period_technical_eligibility',legacy_predicate):
        expected = service.read_bars(**request).model_dump(mode='json')
    actual = service.read_bars(**request).model_dump(mode='json')
    assert actual == expected and actual['bars'] == [] and actual['bar_states'] == []
    assert actual['history']['history_status'] == 'missing'
