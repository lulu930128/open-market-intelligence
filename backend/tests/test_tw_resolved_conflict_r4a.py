"""Resolved candidate differences are diagnostics, not a session-wide denial."""
from datetime import date, datetime, timedelta

import pytest

from test_tw_bar_service import _db, _seed_session, TAIPEI
from app.db.models import MarketIntradayBar, MarketIntradayBarLineage
from app.market.tw_bar_service import TaiwanBarService, _session_requirement
from app.market.tw_intraday_capabilities import (
    KGI_INTRADAY_PROVIDER, KGI_INTRADAY_SOURCE, KGI_INTRADAY_PARSER_VERSION,
    NSTOCK_INTRADAY_PROVIDER, NSTOCK_INTRADAY_SOURCE, NSTOCK_INTRADAY_PARSER_VERSION,
)

DAY = date(2026, 9, 1)
NOW = datetime(2026, 9, 1, 9, 10, tzinfo=TAIPEI)


def seed(db, *, day=DAY, minutes=10, start=0, kgi=False):
    _seed_session(db, trade_date=day, minutes=minutes, start_minute=start,
        provider=KGI_INTRADAY_PROVIDER if kgi else NSTOCK_INTRADAY_PROVIDER,
        source_name=KGI_INTRADAY_SOURCE if kgi else NSTOCK_INTRADAY_SOURCE,
        parser_version=KGI_INTRADAY_PARSER_VERSION if kgi else NSTOCK_INTRADAY_PARSER_VERSION,
        authority='broker' if kgi else 'vendor')


def policy(monkeypatch, *, known=True):
    monkeypatch.setattr('app.market.tw_bar_service.get_taiwan_disposition_status',
        lambda *a, **k: {'cache_status': 'current' if known else 'missing', 'is_active': False})


@pytest.mark.parametrize('interval', ['1m', '5m'])
@pytest.mark.parametrize('case', ['resolved', 'hole', 'unknown_policy', 'no_eligible_winner'])
def test_per_bucket_quality_preserves_resolved_winners(monkeypatch, interval, case):
    from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
    from app.market.intraday_repository import TaiwanIntradayBarRepository
    from app.market_data.gateway import MarketDataGateway
    db, engine = _db()
    try:
        policy(monkeypatch, known=case != 'unknown_policy')
        seed(db)
        seed(db, minutes=2, start=3, kgi=True)
        if case == 'hole':
            db.delete(db.query(MarketIntradayBar).filter_by(bar_time=NOW.replace(hour=9, minute=1, tzinfo=None)).one())
        if case == 'no_eligible_winner':
            db.query(MarketIntradayBarLineage).update({'finalization': 'provisional'})
        db.commit()
        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id='2330', interval=interval, requested_at=NOW, bypass_snapshot_cache=True)
        manifest = result.session_resolution[0]
        if case == 'no_eligible_winner':
            assert not result.bars
            assert result.current_session_coverage.missing_bucket_count == 10
            return
        assert manifest.conflict_bucket_count == 2
        assert 'BAR_SERIES_SAME_TIMESTAMP_CONFLICT_RESOLVED' in result.limitations
        if case == 'unknown_policy':
            assert not manifest.market_semantics_usable
            assert all(not s.technical_eligible for s in result.bar_states)
            return
        if interval == '1m':
            assert [b.lineage.provider for b in result.bars if b.start_at.minute in (3,4)] == [KGI_INTRADAY_PROVIDER]*2
        requirement = _session_requirement(instrument=result.instrument, trade_date=DAY,
            requested_at=NOW, current_session=True)
        resolved = MarketDataGateway().resolve_bars(requirement, reader=TaiwanIntradayBarRepository(db)).resolved
        assert resolved.health.facts_usable and resolved.health.research_usable
        assert resolved.composition.conflict_bucket_count == 2
        points = project_taiwan_bar_series(result, session_scope='current_session')['points']
        if case == 'hole':
            assert result.current_session_coverage.missing_bucket_count == 1
            if interval == '5m':
                assert not result.bar_states[0].technical_eligible
                assert points[0]['quality_status'] == 'partial'
                assert points[0]['gap_reason'] == 'MISSING_BASE_1M_EVIDENCE'
                assert result.bar_states[1].technical_eligible
            else:
                assert all(s.technical_eligible for s in result.bar_states)
        else:
            assert all(s.technical_eligible for s in result.bar_states)
            assert all(p['quality_status']=='ok' and not p['is_partial'] for p in points)
    finally:
        db.close(); engine.dispose()


@pytest.mark.parametrize('case', ['resolved', 'resolved_after_target', 'hole', 'unknown_policy', 'no_eligible_winner'])
def test_fixed_target_demand_keeps_resolved_conflict_diagnostic(monkeypatch, case):
    from app.jobs.taiwan_intraday_demand import _reread
    db, engine = _db()
    try:
        policy(monkeypatch, known=case != 'unknown_policy')
        seed(db, minutes=7 if case == 'resolved_after_target' else 5)
        seed(db, minutes=1 if case == 'resolved_after_target' else 2,
            start=6 if case == 'resolved_after_target' else 3, kgi=True)
        if case == 'hole':
            db.delete(db.query(MarketIntradayBar).filter_by(bar_time=NOW.replace(minute=1, tzinfo=None)).one())
        if case == 'no_eligible_winner':
            db.query(MarketIntradayBarLineage).update({'finalization': 'provisional'})
        db.commit()
        result = _reread(db, {'stock_id':'2330', 'trade_date':DAY.isoformat(),
            'desired_coverage_end_at':NOW.replace(minute=5).isoformat(), 'realtime_policy':'cache_only'},
            NOW.replace(minute=8 if case == 'resolved_after_target' else 6))
        assert result['reread_ready'] is (case in {'resolved', 'resolved_after_target'})
        assert result['latest_tail_missing_bucket_count'] == 1
    finally:
        db.close(); engine.dispose()


def test_chart_forming_tail_preserves_resolved_completed_prefix(monkeypatch):
    from app.market.tw_chart_service import TaiwanChartService
    from app.market.tw_technical_service import TaiwanTechnicalStatus
    db, engine = _db()
    try:
        policy(monkeypatch)
        seed(db, day=date(2026,8,31), minutes=265, kgi=True)
        seed(db, minutes=137, kgi=True)
        seed(db, minutes=137)
        db.query(MarketIntradayBar).filter_by(provider=NSTOCK_INTRADAY_PROVIDER,
            bar_time=datetime(2026,9,1,9,0)).one().trade_value = None
        db.commit()
        kwargs = dict(instrument_id='2330', interval='5m',
            from_time=datetime(2026,8,31,9,0,tzinfo=TAIPEI),
            requested_at=datetime(2026,9,1,11,17,30,tzinfo=TAIPEI))
        chart = TaiwanChartService(db)
        completed = chart.read(**kwargs, include_partial=False)
        forming = chart.read(**kwargs, include_partial=True)
        assert forming.bars.session_resolution[-1].conflict_bucket_count == 1
        assert len(completed.technical.points) == 80
        assert forming.technical.points == completed.technical.points
        assert not forming.bars.bar_states[-1].technical_eligible
        assert forming.technical.current_partial.point['decision_usable'] is False
        db.delete(db.query(MarketIntradayBar).filter_by(bar_time=datetime(2026,8,31,10,2)).one()); db.commit()
        hole = chart.read(**kwargs, include_partial=True)
        assert hole.technical.status is TaiwanTechnicalStatus.UNAVAILABLE
        assert not hole.technical.points
    finally:
        db.close(); engine.dispose()
