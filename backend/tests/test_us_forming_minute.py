"""Completed-minute production path; isolated SQLite and fixture-only IO."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.db.models import Base, MarketIntradayBar, RawFetchResult, USStockMaster
from app.db.session import SessionLocal
from app.us_market import intraday_materializer as owner
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import TWELVE_INTRADAY_DESCRIPTOR, TWELVE_INTRADAY_RESOURCE_ID
from test_us_intraday_shared_core import _twelve_bars_payload

NY = ZoneInfo("America/New_York")
BOUNDARY = datetime(2026, 11, 3, 10, 0, tzinfo=NY)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'intraday.db'}", poolclass=NullPool, connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    with SessionLocal(bind=engine) as db:
        db.add(USStockMaster(symbol="AAPL", security_name="Apple", exchange="NASDAQ", asset_type="stock", is_etf=False))
        db.commit()
    yield lambda: SessionLocal(bind=engine)
    engine.dispose()


def platform(db, payload, fetched, calls):
    def fetch(route, requirement):
        calls.append((route.provider_key, requirement))
        return payload, "https://fixture.invalid/minutes"
    return USIntradayMarketPlatform(db, acquisition=USIntradayAcquisitionExecutor(
        fetchers={TWELVE_INTRADAY_RESOURCE_ID: fetch}, clock=lambda: fetched),
        bar_descriptors=(TWELVE_INTRADAY_DESCRIPTOR,))


@pytest.mark.parametrize("second", [30, 45, 45.001, 59.999])
def test_real_materializer_completed_and_forming(sessions, second):
    now = BOUNDARY + timedelta(seconds=second)
    payload = _twelve_bars_payload(BOUNDARY + timedelta(minutes=1), count=2)
    calls = []
    result = owner.materialize_us_intraday_capability("intraday.bars", configured_symbols="AAPL",
        now=now, max_provider_calls=1, session_factory=sessions,
        platform_factory=lambda db: platform(db, payload, now, calls))
    assert result["status"] == "success", result
    assert result["external_call_count"] == 1 and len(calls) == 1
    with sessions() as db:
        assert db.query(MarketIntradayBar).count() == 1
        raw = db.query(RawFetchResult).one()
        assert '10:00:00' in raw.raw_text  # Forming row remains in original receipt.


def test_all_forming_receipt_then_same_payload_at_end(sessions):
    payload = _twelve_bars_payload(BOUNDARY + timedelta(minutes=1), count=1)
    calls = []
    with sessions() as db:
        first = platform(db, payload, BOUNDARY + timedelta(seconds=30), calls).refresh_intraday_bars(
            symbol="AAPL", now=BOUNDARY + timedelta(seconds=30), bars=1, max_provider_calls=1)
        assert first.result.persistence.committed and not first.postcondition_satisfied
        assert db.query(MarketIntradayBar).count() == 0 and db.query(RawFetchResult).count() == 1
        assert "INCOMPLETE_INTRADAY_BAR_DEFERRED" in first.result.acquisition.limitations
        assert first.result.acquisition.status.value == "partial"
    with sessions() as db:
        later = platform(db, payload, BOUNDARY + timedelta(minutes=1), calls).refresh_intraday_bars(
            symbol="AAPL", now=BOUNDARY + timedelta(minutes=1), bars=1, max_provider_calls=1)
        assert later.postcondition_satisfied and later.result.persistence.committed
        assert db.query(MarketIntradayBar).count() == 1 and db.query(RawFetchResult).count() == 1
        assert len(calls) == 2
        lineage = later.result.resolved.bars[0].lineage
        assert lineage.fetched_at == BOUNDARY + timedelta(minutes=1)
        assert db.query(RawFetchResult).one().fetched_at.replace(tzinfo=timezone.utc) < lineage.fetched_at


@pytest.mark.parametrize("requested,fetched,end,current", [
    ("2026-11-03T10:01:00", "2026-11-03T10:01:00", "2026-11-03T10:00:00", False),
    ("2026-11-03T10:02:20", "2026-11-03T10:02:20", "2026-11-03T10:00:00", False),
    ("2026-11-03T10:00:59", "2026-11-03T10:01:01", "2026-11-03T10:01:00", True),
    ("2026-11-03T10:00:59", "2026-11-03T10:01:01", "2026-11-03T10:00:00", False),
    ("2026-11-03T09:30:20", "2026-11-03T09:30:20", "2026-11-03T09:30:00", False),
    ("2026-11-03T09:31:00", "2026-11-03T09:31:00", "2026-11-03T09:31:00", True),
    ("2026-11-03T08:00:59", "2026-11-03T08:00:59", "2026-11-03T08:00:00", True),
    ("2026-11-03T16:00:00", "2026-11-03T16:00:00", "2026-11-03T16:00:00", False),
    ("2026-11-27T13:00:00", "2026-11-27T13:00:00", "2026-11-27T13:00:00", False),
    ("2026-11-03T19:00:59", "2026-11-03T19:00:59", "2026-11-03T19:00:00", True),
    ("2026-11-04T04:00:20", "2026-11-04T04:00:20", "2026-11-03T19:59:00", False),
])
def test_actual_cutoff_and_market_session_slots(sessions, requested, fetched, end, current):
    requested, fetched, end = (datetime.fromisoformat(s).replace(tzinfo=NY) for s in (requested, fetched, end))
    calls = []
    with sessions() as db:
        result = platform(db, _twelve_bars_payload(end, count=1), fetched, calls).refresh_intraday_bars(
            symbol="AAPL", now=requested, bars=1, max_provider_calls=1)
        assert result.postcondition_satisfied is current, result.result.resolved.health
        assert result.result.dataset_health.status.value == ("healthy" if current else "stale")
        assert result.result.resolution_at == fetched
        assert result.result.requirement.request.end_at == requested + timedelta(minutes=1)
        assert result.result.persistence.committed and len(calls) == 1
        assert result.result.resolved.bars[-1].end_at == end
        assert result.result.acquisition.status.value != "failed"  # Sparse/stale is not transport failure.


def test_only_latest_of_600_completed_bars_has_slot_freshness(sessions):
    now = BOUNDARY + timedelta(seconds=59.999)
    with sessions() as db:
        result = platform(db, _twelve_bars_payload(BOUNDARY + timedelta(minutes=1), count=601), now, []).refresh_intraday_bars(
            symbol="AAPL", now=now, bars=600, max_provider_calls=1)
        assert result.postcondition_satisfied and len(result.result.resolved.bars) == 600
        assert result.result.resolved.bars[-1].end_at == BOUNDARY
        assert "INCOMPLETE_INTRADAY_BAR_DEFERRED" in result.result.acquisition.limitations
        assert "PROVIDER_RESPONSE_TRUNCATED_TO_REQUEST_BOUND" not in result.result.acquisition.limitations
        assert result.result.dataset_health.status.value == "healthy"


def test_completed_slot_is_explicit_bar_only_policy_not_a_magic_age(sessions):
    from dataclasses import replace
    from app.market_data.integration_contracts import DataRequirementV2, SnapshotCapabilityRequest
    from app.us_market.intraday_profiles import US_RECURRING_INTRADAY_PROFILE, US_BOOTSTRAP_INTRADAY_PROFILE
    with sessions() as db:
        application = platform(db, {}, BOUNDARY, [])
        identity = application.read_quote(symbol="AAPL", now=BOUNDARY).identity
        args = dict(now=BOUNDARY, allow_acquisition=True, require_live=False, max_provider_calls=1)
        def requirement(profile):
            return application._bar_requirement(identity, bars=10, history_days=1, profile=profile, **args)
        ordinary = requirement(replace(US_RECURRING_INTRADAY_PROFILE, completed_minute_freshness=False))
        explicit = requirement(replace(US_RECURRING_INTRADAY_PROFILE, producer_refresh_due_seconds=21))
        assert ordinary.freshness.max_age_seconds == 45 and ordinary.freshness.completed_bar is None
        assert explicit.freshness.max_age_seconds == 21 and explicit.freshness.completed_bar is not None
        assert requirement(US_BOOTSTRAP_INTRADAY_PROFILE).freshness.completed_bar is None
        assert application._quote_requirement(identity, profile=US_RECURRING_INTRADAY_PROFILE, **args).freshness.completed_bar is None
        invalid = explicit.model_dump()
        invalid["request"] = SnapshotCapabilityRequest(capability_id="quote.snapshot")
        with pytest.raises(ValueError, match="completed-bar freshness"):
            DataRequirementV2.model_validate(invalid)


@pytest.mark.parametrize("fault", ["future_start", "off_grid", "duplicate", "identity", "duration"])
def test_forming_filter_does_not_accept_malformed(sessions, fault):
    from app.market_data.gateway import PostAcquisitionError
    payload = _twelve_bars_payload(BOUNDARY + timedelta(minutes=1), count=1)
    if fault == "future_start":
        payload["values"][0]["datetime"] = "2026-11-03 10:01:00"
    elif fault == "off_grid":
        payload["values"][0]["datetime"] = "2026-11-03 10:00:01"
    elif fault == "duplicate":
        payload["values"] *= 2
    elif fault == "identity":
        payload["meta"]["symbol"] = "AMD"
    with sessions() as db:
        application = platform(db, payload, BOUNDARY + timedelta(seconds=30), [])
        if fault == "duration":
            # Contract-fault injection after the real adapter, before acquisition filtering.
            canonical = application._acquisition._canonical
            def invalid_duration(*args):
                batch = canonical(*args)
                from dataclasses import replace
                return replace(batch, bars=(batch.bars[0].model_copy(update={"end_at": BOUNDARY + timedelta(minutes=2)}),))
            application._acquisition._canonical = invalid_duration
        try:
            result = application.refresh_intraday_bars(symbol="AAPL", now=BOUNDARY + timedelta(seconds=30), bars=1, max_provider_calls=1)
        except PostAcquisitionError as exc:
            assert fault in {"future_start", "off_grid", "duration"} and exc.stage == "persistence"
        else:
            assert fault in {"duplicate", "identity"} and not result.postcondition_satisfied
            assert result.result.acquisition.status.value == "failed"
        assert db.query(MarketIntradayBar).count() == 0
        assert db.query(RawFetchResult).count() == 0
