from datetime import datetime, date
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
from app.market import tw_bar_service as owner
from app.market.intraday import _append_completed_session_close_marker
from test_tw_bar_service import _db


def test_empty_bars_keep_close_event_separate_and_revision_unchanged():
    db, engine = _db()
    at = datetime.fromisoformat("2026-09-03T13:34:00+08:00")
    close = {
        "available": True, "price": 2390, "trade_date": at.date(),
        "event_time": at.replace(minute=30), "provider": "twse_mis",
        "source": "twse_mis_quote_depth", "closing_match_volume_shares": 1000,
    }
    try:
        series = owner.TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330", interval="1m", requested_at=at,
        )
        identity = series.identity
        with (
            patch.object(owner, "read_taiwan_latest_daily_evidence", return_value=SimpleNamespace(daily=None)),
            patch.object(owner, "read_taiwan_session_close", return_value=object()),
            patch.object(owner, "project_taiwan_session_close", return_value=close),
        ):
            events = owner.TaiwanBarService(db).read_current_session_presentation_events(series=series, requested_at=at)
            projected = project_taiwan_bar_series(series, session_scope="current_session", presentation_events=events)
            legacy = _append_completed_session_close_marker(db, stock_id="2330", points=[], requested_at=at)
            assert len(legacy) == 1 and legacy[0]["indicator_eligible"] is False
            assert owner.TaiwanBarService(db).read_current_session_presentation_events(
                series=series, requested_at=at.replace(day=4, hour=10),
            ) == ()
            changed = {**close, "price": 2391}
            with patch.object(owner, "project_taiwan_session_close", return_value=changed):
                corrected = owner.TaiwanBarService(db).read_current_session_presentation_events(series=series, requested_at=at)
                assert corrected[0].evidence_id != events[0].evidence_id
        assert projected["point_count"] == 0
        assert projected["display_event_count"] == 1
        assert projected["materialization_state"] == "not_materialized"
        assert projected["freshness_status"] == "missing"
        assert series.identity == identity
        assert events[0].event_at.hour == 13 and events[0].event_at.minute == 30
    finally:
        db.close()
        engine.dispose()


def test_brief_budget_keeps_display_event_without_claiming_bars():
    from app.ai.decision_envelope_v4 import _brief_capability_summary
    value = {"point_count": 0, "points": [], "display_event_count": 1,
        "presentation_events": [{"evidence_id": "close-1", "event_type": "session_close_marker", "technical_eligible": False}],
        "cache_status": "persisted_miss"}
    summary = _brief_capability_summary("intraday.bars", value)
    assert summary["point_count"] == 0
    assert summary["display_event_count"] == 1
    assert summary["presentation_events"] == value["presentation_events"]
