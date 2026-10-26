"""G4 isolated regressions: no live provider or production persistence."""
from datetime import date, datetime

import pytest

from app.market.providers import twse_mis_current_breadth as provider
from app.market.providers.tw_current_market import _health
from app.market.tw_current_market_platform import build_taiwan_current_requirement
from app.market.tw_current_market_capabilities import TW_CURRENT_BREADTH_CAPABILITY_ID, TW_CURRENT_BREADTH_DATASET_ID
from app.market_data.contracts import OperationalStatus
from app.market_data.policies import RealtimePolicy
from test_tw_breadth_acquisition_evidence import clock, offline, CODES, NOW, fake_fetch


@pytest.mark.parametrize("cache_path", ["immediate", "after_lock"])
def test_rescue_failure_health_survives_cache_hit_without_new_provider_io(clock, monkeypatch, cache_path):
    calls = []
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages",
                        fake_fetch(clock, calls, scan_duration=0.1, rescue_duration=5))
    first = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    if cache_path == "after_lock":
        # Another caller finishes acquisition while this caller waits for the lock.
        provider._CACHE["TWSE"]["expires_at"] = 0
        class FilledWhileWaiting:
            def __enter__(self):
                provider._CACHE["TWSE"]["expires_at"] = clock.seconds + 30
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(provider, "_REFRESH_LOCK", FilledWhileWaiting())
    cached = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: pytest.fail("cache called universe"))
    assert first.operational_status is OperationalStatus.DEGRADED
    assert cached.status == "cached" and cached.external_calls == 0 and len(calls) == 12
    assert cached.payload is first.payload
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_BREADTH_DATASET_ID, capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
        scope_key="TWSE", requested_at=NOW, policy=RealtimePolicy.CACHE_ONLY, acquiring=False)
    health = _health(requirement, provider="twse_mis", checked_at=NOW, payload=cached, healthy=True)
    assert health.operational is OperationalStatus.DEGRADED
    assert cached.detail_code == first.detail_code == "TWSE_MIS_BREADTH_RESCUE_FAILED"
    assert cached.payload["missing_z_rescue"]["backoff_seconds"] == 300


def test_new_successful_acquisition_replaces_cached_failure_health(clock, monkeypatch):
    calls = []
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages",
                        fake_fetch(clock, calls, scan_duration=0.1, rescue_duration=5))
    failed = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    assert failed.operational_status is OperationalStatus.DEGRADED
    clock.seconds += 301
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages",
                        fake_fetch(clock, calls, scan_duration=0.1, rescue_duration=0.5))
    recovered = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    cached = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    assert recovered.operational_status is cached.operational_status is OperationalStatus.HEALTHY
    assert cached.payload is recovered.payload and cached.payload is not failed.payload
    assert cached.detail_code == "TWSE_MIS_BREADTH_AVAILABLE"


def test_history_partial_does_not_reclassify_complete_selected_session(monkeypatch):
    from test_tw_bar_service import _db, _seed_session, TAIPEI
    from app.market.tw_intraday_capabilities import NSTOCK_INTRADAY_PROVIDER, NSTOCK_INTRADAY_SOURCE, NSTOCK_INTRADAY_PARSER_VERSION
    from app.market.tw_bar_service import TaiwanBarService
    from app.market.tw_intraday_platform import project_taiwan_intraday_bars
    monkeypatch.setattr("app.market.tw_bar_service.get_taiwan_disposition_status",
                        lambda *args, **kwargs: {"cache_status": "current", "is_active": False})
    db, engine = _db()
    try:
        for day, count in [(date(2026, 10, 7), 2), (date(2026, 10, 8), 265)]:
            _seed_session(db, trade_date=day, provider=NSTOCK_INTRADAY_PROVIDER,
                          source_name=NSTOCK_INTRADAY_SOURCE, parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
                          authority="vendor", minutes=count)
        service = TaiwanBarService(db)
        now = datetime(2026, 10, 10, 12, tzinfo=TAIPEI)
        history = service.read_bars(instrument_id="2330", interval="1m",
            from_time=datetime(2026, 10, 7, tzinfo=TAIPEI), to_time=datetime(2026, 10, 9, tzinfo=TAIPEI), requested_at=now)
        current = service.read_current_session_bars(instrument_id="2330", requested_at=now, bypass_snapshot_cache=True)
        assert history.history.history_status.value == "partial"
        assert history.session_resolution[-1].coverage_status.value == "ready"
        assert history.current_session_coverage is None
        assert current.current_session_coverage.missing_bucket_count == 0
        assert current.current_session_coverage.expected_bucket_count == 265
        _, history_projection = project_taiwan_intraday_bars(db, history)
        _, session_projection = project_taiwan_intraday_bars(db, current)
        assert history_projection["series_coverage"]["contract_version"] == "tw.bar.history_coverage.v1"
        assert history_projection["series_coverage"]["history_status"] == "partial"
        assert session_projection["series_coverage"]["status"] == "complete_session"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("authority,official,release,confirmed", [
    ("derived", False, "pending_release", False),
    ("exchange", True, "released", True),
])
def test_completed_tpex_reference_usability_does_not_imply_official(authority, official, release, confirmed):
    from app.market.index_resolution import resolve_taiwan_index_truth, project_taiwan_index_headline
    from test_tw_index_truth_convergence import _snapshot, _calendar
    snapshot = {**_snapshot(), "index_id": "TPEX", "completed_daily_authority": authority,
        "completed_daily_official": official, "completed_daily_release_status": release,
        "completed_daily_source": "tpex_index_5s_components" if not official else "tpex_official_index_close",
        "completed_daily_provider": "tpex_derived" if not official else "tpex"}
    truth = resolve_taiwan_index_truth(intraday=None, index_snapshot=snapshot,
        calendar_status=_calendar(), index_id="TPEX", acquisition_policy="cache_only")
    assert truth.research_usable is True
    assert truth.decision_usable is official
    assert truth.selected_finalization == "final"
    assert truth.official_close_confirmed is confirmed
    assert truth.provisional_estimate is (not official)
    assert truth.selected_authority == ("official_exchange" if official else "derived_proxy")
    headline = project_taiwan_index_headline({"resolution": truth.model_dump(mode="json")})
    assert headline["official"] is confirmed
    assert headline["provisional"] is (not official)
