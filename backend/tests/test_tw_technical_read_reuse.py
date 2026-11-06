"""Reuse only identical completed-day inputs within a bounded read scope."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.market.tw_bar_service import TaiwanBarService, taiwan_bar_read_scope
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market import technical_evidence
from app.db.models import StockMaster
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row  # noqa: F401

NOW = datetime(2026, 8, 26, 0, tzinfo=timezone.utc)

def seed(db):
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type='twse_daily', priority=10)
    raw.status_code = 200
    db.add(StockMaster(stock_id='2330', market='TWSE', stock_name='fixture', instrument_type='stock'))
    db.add_all([_daily_row(source=source, raw=raw, trade_date=date(2026, 8, day)) for day in (20, 21)])
    db.commit()
    db.expunge_all()

def test_completed_inputs_reuse_keeps_full_interval_outputs_and_request_bounds(db, monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    seed(db)
    service = TaiwanBarService(db)
    requests = [dict(instrument_id='2330', interval=interval, limit=1800, include_partial=partial, requested_at=NOW)
                for interval, partial in [('1d', False), ('1w', False), ('1mo', False), ('1d', True)]]
    expected = [service.read_bars(**request).model_dump(mode='json') for request in requests]
    original = TaiwanOfficialDailyBarRepository.resolve_daily_days
    calls = []
    def observe(self, **kwargs):
        calls.append((kwargs['instrument'], kwargs['start_date'], kwargs['end_date']))
        return original(self, **kwargs)
    monkeypatch.setattr(TaiwanOfficialDailyBarRepository, 'resolve_daily_days', observe)
    with taiwan_bar_read_scope():
        actual = [service.read_bars(**request).model_dump(mode='json') for request in requests]
        assert actual == expected
        # Completed daily, completed weekly/monthly and research-purpose
        # forming inputs have distinct eligibility requirements.
        assert len(calls) == 3
        # Distinct receipt visibility and bounds must resolve separately.
        service.read_bars(**{**requests[0], 'requested_at': NOW + timedelta(seconds=1)})
        service.read_bars(**{**requests[0], 'limit': 1})
        assert len(calls) == 5
    with taiwan_bar_read_scope():
        assert service.read_bars(**requests[0]).model_dump(mode='json') == expected[0]
    assert len(calls) == 6

def test_technical_evidence_opens_read_scope_with_one_receipt_cutoff(db, monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    seed(db)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(technical_evidence, 'datetime', Clock)
    original = TaiwanOfficialDailyBarRepository.resolve_daily_days
    calls = []
    def observe(self, **kwargs):
        calls.append(self._available_at)
        return original(self, **kwargs)
    monkeypatch.setattr(TaiwanOfficialDailyBarRepository, 'resolve_daily_days', observe)
    result = technical_evidence.build_tw_stock_technical_evidence(db=db, stock_id='2330',
        requested_capabilities={'technical.swings'})
    assert result['swings']
    # Before the opening, the owner cannot produce a forming regular bar.
    assert len(calls) == 2 and len(set(calls)) == 1


import pytest


def test_read_scope_never_reuses_another_session_on_the_same_engine(db, monkeypatch):
    from sqlalchemy.orm import Session
    seed(db)
    original = TaiwanBarService._read_daily_bars
    sessions = []
    def read(self, **kwargs):
        sessions.append(self._db)
        return original(self, **kwargs)
    monkeypatch.setattr(TaiwanBarService, "_read_daily_bars", read)
    request = dict(instrument_id="2330", interval="1d", limit=1, include_partial=False, requested_at=NOW)
    with Session(db.get_bind()) as second, taiwan_bar_read_scope():
        TaiwanBarService(db).read_bars(**request)
        TaiwanBarService(second).read_bars(**request)
    assert sessions == [db, second]


def test_formal_close_reader_is_not_called_before_its_event_boundary(db, monkeypatch):
    from app.market import tw_bar_service
    from app.market_data.contracts import InstrumentKey
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise ValueError("not captured")
    monkeypatch.setattr(tw_bar_service, "read_taiwan_session_close", unavailable)
    instrument = InstrumentKey(market="TW", symbol="2330", venue="TWSE", instrument_type="stock")
    close = datetime(2026, 11, 6, 5, 30, tzinfo=timezone.utc)
    for cutoff in (close-timedelta(microseconds=1), close):
        assert tw_bar_service._qualified_formal_close_component(db, instrument=instrument,
            trade_date=close.date(), requested_at=cutoff) is None
    assert len(calls) == 1 and calls[0]["requested_at"] == close

@pytest.mark.parametrize("initial,mutation", [({}, "add"), ({"source": ("reason",)}, "clear"), ({"source": ("reason",)}, "overwrite")])
def test_request_memo_isolates_nested_resolution_reasons_on_first_return_and_hits(db, monkeypatch, tmp_path, initial, mutation):
    from app.config import settings
    from app.market.tw_bar_contracts import TaiwanSessionResolutionManifest
    from app.market_data.integration_contracts import BarSeriesResolutionMode
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    seed(db)
    service = TaiwanBarService(db)
    request = dict(instrument_id='2330', interval='1d', limit=1800, include_partial=False, requested_at=NOW)
    original = service.read_bars(**request)
    manifest = TaiwanSessionResolutionManifest(trade_date=date(2026, 8, 21),
        resolution_mode=BarSeriesResolutionMode.SINGLE_CANDIDATE, current_session=False,
        coverage_status='ready', rejected_candidate_reasons=initial)
    original = original.model_copy(update={'session_resolution': (manifest,)})
    expected = original.model_dump(mode='json')
    with patch.object(service, '_read_daily_bars', return_value=original), taiwan_bar_read_scope():
        for _ in range(2):  # first return and later memo hit must both be independent
            returned = service.read_bars(**request)
            reasons = returned.session_resolution[0].rejected_candidate_reasons
            if mutation == 'clear':
                reasons.clear()
            elif mutation == 'overwrite':
                reasons['source'] = ('injected',)
            else:
                reasons['x'] = ('injected',)
            clean = service.read_bars(**request)
            assert clean.model_dump(mode='json') == expected
            assert original.model_dump(mode='json') == expected
            assert clean.identity == original.identity
            assert clean.bars is original.bars  # immutable bulk graph is shared


@pytest.mark.parametrize('capability', ['technical.relative_strength', 'technical.structure'])
def test_benchmark_and_stock_share_exact_receipt_cutoff(db, monkeypatch, tmp_path, capability):
    from app.config import settings
    monkeypatch.setattr(settings, 'tw_corporate_event_cache_path', tmp_path / 'missing-events.json')
    seed(db)
    class MovingClock(datetime):
        ticks=0
        @classmethod
        def now(cls,tz=None):
            value=NOW+timedelta(seconds=cls.ticks)
            cls.ticks+=1
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(technical_evidence,'datetime',MovingClock)
    monkeypatch.setattr(technical_evidence,'build_tw_sector_benchmark',lambda *a,**kw:None)
    original=TaiwanBarService.read_bars
    calls=[]
    def read(self,**kwargs):
        calls.append((kwargs['instrument_id'],kwargs.get('requested_at')))
        return original(self,**kwargs)
    monkeypatch.setattr(TaiwanBarService,'read_bars',read)
    technical_evidence.build_tw_stock_technical_evidence(db=db,stock_id='2330',requested_capabilities={capability})
    assert {symbol for symbol,_ in calls} >= {'2330','TAIEX'}
    assert all(cutoff==NOW for _,cutoff in calls)
