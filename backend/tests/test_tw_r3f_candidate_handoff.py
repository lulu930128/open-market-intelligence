"""Full candidate evidence is handed off only for one exact repository read."""
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.db.models import RawFetchResult, StockMaster
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository as Repository
from app.market.tw_bar_service import TaiwanBarService, taiwan_bar_read_scope
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import InstrumentKey
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME, TWSE_RWD_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row  # noqa: F401

CUTOFF = datetime(2026, 8, 26, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey(market='TW', venue='TWSE', symbol='2330', instrument_type='stock')


def seed_complex(db):
    primary, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    preferred, preferred_raw = _source_and_raw(db, source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME, parser_type='twse_rwd_daily', priority=1)
    raw.status_code = preferred_raw.status_code = 200
    late = RawFetchResult(source_id=preferred.id, fetched_at=CUTOFF+timedelta(seconds=1),
        status_code=200, content_hash='late-receipt', parser_version='fixture.v1', raw_text='[]')
    early = RawFetchResult(source_id=primary.id, fetched_at=datetime(2026,8,24,1,tzinfo=timezone.utc),
        status_code=200, content_hash='before-release', parser_version='fixture.v1', raw_text='[]')
    db.add_all([late, early, StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock')])
    db.flush()
    rows = [
        _daily_row(source=primary, raw=raw, trade_date=date(2026,8,17)),
        _daily_row(source=preferred, raw=preferred_raw, trade_date=date(2026,8,17), close_price=109),
        _daily_row(source=primary, raw=raw, trade_date=date(2026,8,18), open_price=None, high_price=None,
                   low_price=None, close_price=None, trade_volume=10),
        _daily_row(source=primary, raw=raw, trade_date=date(2026,8,19), close_price=1000),  # invalid OHLC
        _daily_row(source=primary, raw=raw, trade_date=date(2026,8,20), open_price=None, high_price=None,
                   low_price=None, close_price=None, trade_volume=0),
        _daily_row(source=primary, raw=raw, trade_date=date(2026,8,21)),
        _daily_row(source=preferred, raw=late, trade_date=date(2026,8,21), high_price=1100, close_price=1000),
        _daily_row(source=primary, raw=early, trade_date=date(2026,8,24)),
    ]
    rows[2].trade_value, rows[2].transaction_count = 1000, 1
    rows[4].trade_value, rows[4].transaction_count = 0, 0
    db.add_all(rows)
    db.commit()
    return {name: row.id for name,row in zip(('loser','winner','activity','invalid','zero','price','late','unreleased'), rows)}


def request(interval='1w', *, partial=False):
    return dict(instrument_id='2330', interval=interval, limit=1800, requested_at=CUTOFF,
        from_time=datetime(2026,8,17,tzinfo=timezone.utc), to_time=datetime(2026,8,25,tzinfo=timezone.utc),
        include_partial=partial)


def observe(monkeypatch):
    calls = []
    original = Repository.load_daily_bars
    def counted(self, query):
        result = original(self, query)
        calls.append((self, self._db, self._available_at, query, result))
        return result
    monkeypatch.setattr(Repository, 'load_daily_bars', counted)
    return calls


@pytest.mark.parametrize('interval,expected', [('1d',2), ('1w',1), ('1mo',1)])
def test_exact_candidate_read_count_and_full_query_evidence(db, monkeypatch, tmp_path, interval, expected):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path/'absent.json')
    ids = seed_complex(db)
    calls = observe(monkeypatch)
    output = TaiwanBarService(db).read_bars(**request(interval))
    assert calls and all(c[0] is calls[0][0] and c[1] is db and c[2] == calls[0][2] for c in calls)
    assert all(c[3].model_copy(update={'max_rows':5000}) == calls[0][3].model_copy(update={'max_rows':5000}) for c in calls)
    if interval != '1d':
        assert all(c[3] == calls[0][3] and c[4] == calls[0][4] for c in calls)
    stored = calls[0][4]
    assert {r.reason_code for r in stored.rejections} == {
        'MISSING_REQUIRED_OHLC', 'INVALID_CANONICAL_BAR', 'DAILY_RECEIPT_PREDATES_RELEASE'}
    assert {r.storage_row_id for r in stored.rejections} == {ids[n] for n in ('activity','invalid','zero','unreleased')}
    assert {n for series in stored.series for n in series.storage_row_ids} == {ids[n] for n in ('loser','winner','price')}
    print(json.dumps(dict(interval=interval, load_count=len(calls), same_repository_session_cutoff=True,
        queries=[c[3].model_dump(mode='json') for c in calls],
        candidate_sha256=[sha256(c[4].model_dump_json().encode()).hexdigest() for c in calls],
        rows_examined=stored.rows_examined, rows_accepted=stored.rows_accepted,
        rejections=len(stored.rejections), output_sha256=sha256(output.model_dump_json().encode()).hexdigest(),
        identity=output.identity.model_dump(mode='json'))))
    assert [c[3].max_rows for c in calls] == ([1800,5000] if interval == '1d' else [5000])
    assert len(calls) == expected


def legacy_completed_inputs(self, repository, requirement):
    """Frozen R3E no-memo-hit path, before the candidate handoff existed."""
    from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
    from app.market.trading_calendar import TAIWAN_TZ
    from app.market_data.gateway import MarketDataGateway
    result = MarketDataGateway().resolve_bars(requirement, reader=TaiwanCompletedDailyCandidateReader(repository))
    bars = result.resolved.bars
    states = repository.resolve_daily_days(instrument=requirement.target.instrument,
        start_date=requirement.request.start_at.astimezone(TAIWAN_TZ).date(),
        end_date=requirement.request.end_at.astimezone(TAIWAN_TZ).date(), resolved_bars=bars)
    bars, states = repository.complete_no_trade_bars(resolved_bars=bars, day_states=states)
    metadata = repository.outward_state_metadata(tuple(b.lineage.observation_id for b in bars if b.lineage.observation_id))
    return result, tuple(bars), tuple(states), metadata


def compare_legacy(service, kwargs):
    from app.market import tw_bar_identity
    normalized = tw_bar_identity._normalized_digest
    payloads = []
    def digest(payload):
        payloads.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        return normalized(payload)
    with patch.object(tw_bar_identity, '_normalized_digest', digest):
        with patch.object(TaiwanBarService, '_completed_daily_inputs', legacy_completed_inputs):
            expected = service.read_bars(**kwargs)
        old_bytes, payloads[:] = list(payloads), []
        actual = service.read_bars(**kwargs)
    assert actual.model_dump(mode='json') == expected.model_dump(mode='json')
    assert actual.model_dump_json().encode() == expected.model_dump_json().encode()
    assert len(old_bytes) == len(payloads) == 4 and payloads == old_bytes
    for field in ('series_fingerprint','lineage_digest','state_digest','series_revision'):
        assert getattr(actual.identity, field) == getattr(expected.identity, field)
    return actual


@pytest.mark.parametrize('interval', ['1d','1w','1mo'])
@pytest.mark.parametrize('partial', [False, True])
def test_complete_payload_qualification_and_four_identity_bytes_match_frozen_owner(db, monkeypatch, tmp_path, interval, partial):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path/'absent.json')
    ids = seed_complex(db)
    actual = compare_legacy(TaiwanBarService(db), request(interval, partial=partial))
    by_day = {s.trade_date:s for s in actual.day_states}
    assert by_day[date(2026,8,18)].state == 'TRADE_ACTIVITY_WITHOUT_PRICE'
    assert by_day[date(2026,8,20)].state == 'VERIFIED_NO_TRADE'
    assert by_day[date(2026,8,20)].blockers  # unknown corporate basis is not relaxed
    observed = {lineage.observation_id for s in actual.day_states for lineage in s.lineage}
    assert {f'market_daily_price:{ids[n]}' for n in ('loser','winner','activity','zero')} <= observed
    assert f'market_daily_price:{ids["late"]}' not in observed
    assert f'market_daily_price:{ids["unreleased"]}' not in observed


@pytest.mark.parametrize('interval,size', [('1d',1800),('1w',5000)])
def test_full_history_retains_all_candidates_and_exact_output(db, monkeypatch, tmp_path, interval, size):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path/'absent.json')
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    raw.status_code = 200
    db.add(StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock'))
    dates, day = [], date(2026,8,21)
    while len(dates) < size:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    db.add_all([_daily_row(source=source, raw=raw, trade_date=day) for day in dates])
    db.commit()
    calls = observe(monkeypatch)
    kwargs = request(interval)
    kwargs.pop('from_time')  # real latest-N discovery, not a reduced test window
    actual = compare_legacy(TaiwanBarService(db), kwargs)
    assert [c[4].rows_accepted for c in calls] == ([size]*4 if interval == '1d' else [size]*3)
    assert [c[3].max_rows for c in calls] == ([1800,5000,1800,5000] if interval == '1d' else [5000]*3)
    assert actual.bars
    print(json.dumps(dict(history_size=size, interval=interval, candidate_counts=[c[4].rows_accepted for c in calls],
        old_loads=2, new_loads=2 if interval=='1d' else 1, four_identity_payload_bytes_equal=True,
        identity=actual.identity.model_dump(mode='json'))))


@pytest.mark.parametrize('change', ['max_rows','start_date','end_date','instrument','query_available_at','cutoff','session','no_cutoff'])
def test_handoff_requires_exact_query_session_and_fixed_cutoff(db, monkeypatch, tmp_path, change):
    from app.config import settings
    from sqlalchemy.orm import Session
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path/'absent.json')
    seed_complex(db)
    repository = Repository(db, available_at=None if change == 'no_cutoff' else CUTOFF)
    query = DailyBarCandidateQuery(instrument=INSTRUMENT, start_date=date(2026,8,17), end_date=date(2026,8,25), max_rows=5000)
    if change == 'max_rows': query = query.model_copy(update={'max_rows':1800})
    if change == 'query_available_at': query = query.model_copy(update={'available_at':CUTOFF})
    args = dict(instrument=INSTRUMENT, start_date=query.start_date, end_date=query.end_date, resolved_bars=())
    calls = observe(monkeypatch)
    other = Session(db.get_bind())
    try:
        with repository.completed_daily_candidate_read_scope():
            repository.load_daily_bars(query)
            if change == 'start_date': args['start_date'] += timedelta(days=1)
            if change == 'end_date': args['end_date'] -= timedelta(days=1)
            if change == 'instrument': args['instrument'] = INSTRUMENT.model_copy(update={'symbol':'2317'})
            if change == 'cutoff': repository._available_at += timedelta(seconds=2)
            if change == 'session': repository._db = other
            repository.resolve_daily_days(**args)
        assert len(calls) == 2
        assert repository._daily_candidate_handoff is None
        assert repository._capture_daily_candidate_read is False
    finally:
        other.close()


def test_frozen_handoff_consumed_once_and_cannot_leak_to_next_scope(db, monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path/'absent.json')
    seed_complex(db)
    repository = Repository(db, available_at=CUTOFF)
    query = DailyBarCandidateQuery(instrument=INSTRUMENT, start_date=date(2026,8,17), end_date=date(2026,8,25), max_rows=5000)
    args = dict(instrument=INSTRUMENT, start_date=query.start_date, end_date=query.end_date, resolved_bars=())
    calls = observe(monkeypatch)
    with repository.completed_daily_candidate_read_scope():
        stored = repository.load_daily_bars(query)
        before = stored.model_dump_json()
        with pytest.raises(ValidationError): stored.series[0].bars[0].close_price = 999
        with pytest.raises(ValidationError): stored.series[0].bars[0].lineage.content_hash = 'changed'
        with pytest.raises(ValidationError): stored.series[0].storage_row_ids += (999,)
        with pytest.raises(ValidationError): stored.query.max_rows = 1
        consumer_copy = stored.model_dump(mode='json')
        consumer_copy['series'][0]['bars'][0]['lineage']['content_hash'] = 'changed'
        consumer_copy['rejections'].clear()
        assert stored.model_dump_json() == before
        repository.resolve_daily_days(**args)
        assert len(calls) == 1 and repository._daily_candidate_handoff is None
        repository.resolve_daily_days(**args)
        assert len(calls) == 2  # consumed once; no general result cache
    with repository.completed_daily_candidate_read_scope():
        repository.resolve_daily_days(**args)
        assert len(calls) == 3
    with pytest.raises(RuntimeError, match='fixture'):
        with repository.completed_daily_candidate_read_scope():
            repository.load_daily_bars(query)
            raise RuntimeError('fixture')
    assert repository._daily_candidate_handoff is None and repository._capture_daily_candidate_read is False
    repository.resolve_daily_days(**args)
    assert len(calls) == 5
