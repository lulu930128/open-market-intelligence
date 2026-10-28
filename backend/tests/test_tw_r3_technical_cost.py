"""Representative history and sector work use canonical owners and one cutoff."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from collections.abc import Mapping
from unittest.mock import patch
from enum import Enum, IntEnum
from hashlib import sha256
import json

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Query

from app.db.models import StockMaster
from app.market import taiwan_industries, tw_bar_identity, technical_evidence
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository as Repository
from app.market_data.candidate_repository import CandidateReadLimitExceeded
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME, TWSE_RWD_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row  # noqa: F401

CUTOFF = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)


def sector_rows(db):
    early, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    late, late_raw = _source_and_raw(db, source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME, parser_type='twse_rwd_daily', priority=1)
    late_raw.fetched_at = CUTOFF + timedelta(seconds=1)
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(61)]
    for code in ('2330','2317'):
        db.add(StockMaster(stock_id=code, stock_name='fixture', market='TWSE', instrument_type='stock', industry='半導體業', is_active=True))
        for i, day in enumerate(dates):
            db.add(_daily_row(source=early, raw=raw, stock_id=code, trade_date=day,
                close_price=100 + i / 10))
            db.add(_daily_row(source=late, raw=late_raw, stock_id=code, trade_date=day,
                close_price=100 if i == 0 else 1000, high_price=2000))
    db.commit(); db.expunge_all()
    return dates


def test_sector_same_receipt_cutoff_rejects_late_higher_priority_candidate(db):
    dates = sector_rows(db)
    result = taiwan_industries.build_tw_sector_benchmark(db, stock_id='2330', trade_dates=dates, requested_at=CUTOFF)
    assert result['points'][-1]['close'] == pytest.approx(106)
    assert len(result['points']) == 61
    later = taiwan_industries.build_tw_sector_benchmark(db, stock_id='2330', trade_dates=dates, requested_at=CUTOFF+timedelta(seconds=2))
    assert later['points'][-1]['close'] == 1000


def test_sector_61_dates_use_bounded_batch_without_changing_canonical_results(db, monkeypatch):
    dates = sector_rows(db)
    expected = {day: Repository(db, available_at=CUTOFF).load_market_universe(
        trade_date=day, symbols=('2317','2330')) for day in dates}
    sql = []
    original_all = Query.all
    def bounded_all(query):
        assert not any(item['name'] == 'MarketDailyPrice' for item in query.column_descriptions), 'joined history must stream'
        return original_all(query)
    monkeypatch.setattr(Query, 'all', bounded_all)
    def observe(conn,cursor,statement,params,ctx,many): sql.append(statement)
    event.listen(db.get_bind(),'before_cursor_execute',observe)
    try:
        actual = Repository(db, available_at=CUTOFF).load_market_universe_history(
            trade_dates=tuple(reversed(dates)), symbols=('2317','2330'))
    finally:
        event.remove(db.get_bind(),'before_cursor_execute',observe)
    assert actual == expected
    assert len(sql) == 2
    assert all('raw_fetch_result.raw_text' not in query for query in sql)
    assert actual[dates[-1]].bars[0].close_price == 106
    with pytest.raises(CandidateReadLimitExceeded):
        Repository(db).load_market_universe_history(trade_dates=tuple(dates), symbols=('2330',), max_rows=1)


def reference_canonical(value):
    # Frozen pre-optimization algorithm: an independent byte/hash oracle.
    if isinstance(value, Decimal): return tw_bar_identity._decimal(value)
    if isinstance(value, datetime): return tw_bar_identity._timestamp(value)
    if isinstance(value, Enum): return value.value
    if isinstance(value, Mapping): return {str(k):reference_canonical(v) for k,v in sorted(value.items())}
    if isinstance(value, (tuple,list)): return [reference_canonical(v) for v in value]
    return value


@pytest.mark.parametrize('size',[1800,5000])
def test_identity_canonicalization_retains_exact_bytes_without_scalar_mapping_checks(size):
    # The nested lineage/day-state workload matches the history scale, including
    # values whose serialization distinguishes receipt/event/zero/null/Decimal.
    payload = [{'event':CUTOFF-timedelta(days=i), 'received':CUTOFF,
                'basis':{'value':Decimal('100.00'),'zero':Decimal('-0'),'missing':None},
                'day_state':{'reasons':['unknown','not_received'], 'count':i, 'ready':False}}
               for i in range(size)]
    class Text(str, Enum): READY = 'ready'
    class Count(IntEnum): ZERO = 0
    class CustomText(str): pass
    class CustomInt(int): pass
    class CustomFloat(float): pass
    payload[0]['scalars'] = [Text.READY, Count.ZERO, CustomText('文字'), CustomInt(3), CustomFloat(-0.0), 1.5]
    expected = reference_canonical(payload)
    scalar_checks=[]
    class MappingProbe(type):
        def __instancecheck__(cls,value):
            if type(value) in (str,int,float,bool,type(None)): scalar_checks.append(type(value))
            return isinstance(value,Mapping)
    class Probe(metaclass=MappingProbe): pass
    with patch.object(tw_bar_identity,'Mapping',Probe):
        actual=tw_bar_identity._canonical(payload)
    assert actual==expected
    assert not scalar_checks
    encode = lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert encode(actual) == encode(expected)
    assert tw_bar_identity._digest(payload) == sha256(encode(expected)).hexdigest()
    actual[0]['day_state']['reasons'].append('mutation')
    assert payload[0]['day_state']['reasons']==['unknown','not_received']


def test_batch_independent_qualification_and_late_membership_fixture(db):
    primary, receipt = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    preferred, preferred_receipt = _source_and_raw(db, source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME, parser_type='twse_rwd_daily', priority=1)
    unqualified, bad_receipt = _source_and_raw(db, source_name='unqualified_fixture', parser_type='fixture', priority=0)
    first, second, empty = date(2026,8,20), date(2026,8,21), date(2026,8,22)
    for code, active in [('2330',True), ('2317',True), ('9999',False)]:
        db.add(StockMaster(stock_id=code, stock_name='fixture', market='TWSE', instrument_type='stock', industry='半導體業', is_active=active))
    winner = _daily_row(source=preferred, raw=preferred_receipt, trade_date=first, close_price=108)
    rows = [winner,
        _daily_row(source=primary, raw=receipt, trade_date=first, close_price=100),
        _daily_row(source=preferred, raw=preferred_receipt, trade_date=first, stock_id='2317', close_price=1000),  # invalid OHLC
        _daily_row(source=unqualified, raw=bad_receipt, trade_date=first, close_price=109),
        _daily_row(source=primary, raw=receipt, trade_date=second, close_price=105),
        _daily_row(source=primary, raw=receipt, trade_date=second, stock_id='2317', close_price=100),
        _daily_row(source=primary, raw=receipt, trade_date=first, stock_id='9999')]
    db.add_all(rows); db.commit()
    winner_id, receipt_id = winner.id, preferred_receipt.id
    result = Repository(db, available_at=CUTOFF).load_market_universe_history(trade_dates=(empty,second,first))
    assert [(bar.instrument.symbol,bar.close_price) for bar in result[first].bars] == [('2330',Decimal(108))]
    assert result[first].bars[0].lineage.observation_id == f'market_daily_price:{winner_id}'
    assert result[first].bars[0].lineage.raw_receipt_id == f'raw_fetch_result:{receipt_id}'
    assert result[first].duplicate_candidate_count == 1
    assert result[first].rows_rejected == 2
    assert set(result[first].rejection_reasons) == {('2330','DAILY_SOURCE_NOT_QUALIFIED'),('2317','DAILY_CANONICAL_VALUE_INVALID')}
    assert result[first].universe_count == result[second].universe_count == 2
    assert [bar.instrument.symbol for bar in result[second].bars] == ['2317','2330']
    assert result[empty].bars == () and result[empty].rows_examined == 0
    benchmark = taiwan_industries.build_tw_sector_benchmark(db, stock_id='2330', trade_dates=[first,second], requested_at=CUTOFF)
    assert benchmark['points'][0]['close'] == 100
    assert benchmark['points'][1]['close'] == pytest.approx((105/108*100+100)/2)
    assert benchmark['observed_member_count'] == 2


@pytest.mark.parametrize('capability',['technical.relative_strength','technical.structure'])
def test_real_sector_receives_technical_cutoff_and_historical_bound(db, monkeypatch, tmp_path, capability):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'absent.json')
    dates = sector_rows(db)
    class MovingClock(datetime):
        ticks = 0
        @classmethod
        def now(cls, tz=None):
            value = CUTOFF + timedelta(seconds=cls.ticks)
            cls.ticks += 2
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(technical_evidence, 'datetime', MovingClock)
    original = taiwan_industries.build_tw_sector_benchmark
    observed = []
    def sector(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append((kwargs, result))
        return result
    monkeypatch.setattr(technical_evidence, 'build_tw_sector_benchmark', sector)
    technical_evidence.build_tw_stock_technical_evidence(db=db, stock_id='2330',
        to_date=dates[-2], requested_capabilities={capability})
    assert len(observed) == 1
    kwargs, result = observed[0]
    assert kwargs['requested_at'] == CUTOFF
    assert max(kwargs['trade_dates']) <= dates[-2]
    # Canonical session filtering can drop weekends, but the selected close
    # must remain the pre-cutoff candidate rather than the valid 1000 receipt.
    assert 100 <= result['points'][-1]['close'] < 110


@pytest.mark.parametrize('size',[1800,5000])
def test_actual_history_identity_matches_frozen_algorithm(db, monkeypatch, tmp_path, size):
    from app.config import settings
    from app.market.tw_bar_service import TaiwanBarService, taiwan_bar_read_scope
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'absent.json')
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    db.add(StockMaster(stock_id='2330', stock_name='fixture', market='TWSE', instrument_type='stock', is_active=True))
    end = date(2026,8,21)
    db.add_all([_daily_row(source=source, raw=raw, trade_date=end-timedelta(days=i), close_price=100+i%10) for i in range(size)])
    db.commit(); db.expunge_all()
    request = dict(instrument_id='2330', interval='1d', limit=size, requested_at=CUTOFF, include_partial=False)
    service = TaiwanBarService(db)
    with patch.object(tw_bar_identity, '_canonical', reference_canonical):
        expected = service.read_bars(**request).model_dump(mode='json')
    with taiwan_bar_read_scope():
        actual = service.read_bars(**request)
        assert actual.model_dump(mode='json') == expected
        assert len(actual.bars) > size // 2
        assert actual.identity.series_revision == expected['identity']['series_revision']
        # First return and memo hit retain nested mutable isolation at scale.
        if actual.session_resolution:
            actual.session_resolution[0].rejected_candidate_reasons['injected'] = ('mutable',)
        assert service.read_bars(**request).model_dump(mode='json') == expected
