"""G-C SYNTHETIC fixtures exercising existing canonical owners, never live IO."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.db.models import MarketIntradayBar, MarketIntradayBarLineage, USStockMaster
from app.market_data.contracts import BarFinalization, EvidenceFreshness, ResolvedEvidenceStatus
from app.us_market.historical_intraday import completed_intraday_window, regular_intraday_coverage
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import (
    TWELVE_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_DESCRIPTOR,
)
from app.us_market.market_truth import read_us_historical_intraday_trend, read_us_market_truth_bundle
from app.us_market.market_truth_contracts import USRegularSessionCoverage
from test_us_intraday_shared_core import _db, _twelve_bars_payload, _yahoo_bars_payload
from test_us_market_truth_snapshot import (
    _bar, _fake_components, _install_fake_components,
)

UTC = timezone.utc
DAY = date(2026, 10, 9)
START = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 10, 1, tzinfo=UTC)


@pytest.fixture
def db():
    session = _db()  # Existing complete helper: sqlite :memory: only.
    for symbol in ("AMD", "SSO"):
        session.add(USStockMaster(symbol=symbol, exchange="NASDAQ", is_etf=symbol == "SSO"))
    session.commit()
    try:
        yield session
    finally:
        engine = session.get_bind()
        session.close()
        engine.dispose()


def seed(db, symbol, count, *, twelve=False, start=START, now=NOW, missing_volume=False):
    descriptor = TWELVE_INTRADAY_DESCRIPTOR if twelve else YAHOO_INTRADAY_DESCRIPTOR
    end = start + timedelta(minutes=count)
    payload = _twelve_bars_payload(end, count=count) if twelve else _yahoo_bars_payload(end, count=count)
    result = payload if twelve else payload["chart"]["result"][0]
    result["meta"]["symbol"] = symbol
    if missing_volume and count:
        result["indicators"]["quote"][0]["volume"][0] = None
    calls = []

    def fetch(route, requirement):
        calls.append(route.resource_id)
        assert requirement.target.instrument.symbol == symbol
        return payload, "https://fixture.invalid/gc"

    platform = USIntradayMarketPlatform(
        db, bar_descriptors=(descriptor,), acquisition=USIntradayAcquisitionExecutor(
            fetchers={descriptor.resource_id: fetch}, clock=lambda: now,
        ),
    )
    platform.refresh_intraday_bars(symbol=symbol, trade_date=start.date(), now=now, max_provider_calls=1)
    assert calls == [descriptor.resource_id]


def historical(db, symbol, day=DAY, now=NOW):
    with patch.object(USIntradayAcquisitionExecutor, "acquire_bar_observations",
                      side_effect=AssertionError("read attempted acquisition")):
        return read_us_historical_intraday_trend(db, symbol=symbol, trade_date=day, evaluated_at=now)


@pytest.mark.parametrize("symbol,count,status", [("AMD", 390, "complete"), ("SSO", 378, "partial"), ("AMD", 0, "missing")])
def test_regular_matrix_public_canonical_coverage(db, symbol, count, status):
    if count:
        seed(db, symbol, count)
    result = historical(db, symbol)
    coverage = USRegularSessionCoverage.model_validate({
        key: value for key, value in result["session_coverage"].items()
        if key in USRegularSessionCoverage.model_fields
    })
    assert coverage.coverage_status == status
    assert coverage.expected_point_count == 390
    assert coverage.point_count == result["point_count"] == len(result["points"]) == count
    assert coverage.missing_slot_count == 390 - count
    assert coverage.gap_count == (0 if count == 390 else 1)
    assert result["is_partial"] is (count != 390)
    assert result["decision_usable"] is False
    assert result["is_live"] is False
    assert db.query(MarketIntradayBar).count() == count  # Missing slots are not zero bars.
    if count:
        source = result["source_status"]
        assert source["provider"] == "yahoo_chart"
        assert source["source"] == result["source"] == "yahoo.chart.1m"
        assert source["facts_usable"] is True
        assert source["event_trade_date"] == DAY.isoformat()
        read = USIntradayMarketPlatform(db).read_intraday_bars_for_trade_date(
            symbol=symbol, trade_date=DAY, now=NOW, completed_regular=True,
        )
        assert read.result.acquisition.external_calls == 0
        assert read.result.persistence.attempted is False
        for bar in read.result.resolved.bars:
            assert bar.instrument.symbol == symbol
            assert bar.lineage.provider == source["provider"]
            assert bar.lineage.source == source["source"]
            assert bar.lineage.fetched_at == NOW
            assert bar.lineage.event_at is not None
            assert bar.lineage.observation_id
            assert bar.finalization is BarFinalization.FINAL
        assert datetime.fromisoformat(source["selected_event_at"]) == read.result.resolved.health.selected_event_at


def test_full_but_provisional_is_not_complete(db):
    seed(db, "AMD", 390)
    for row in db.query(MarketIntradayBarLineage):
        row.finalization = "provisional"
    db.commit()
    result = historical(db, "AMD")
    assert result["point_count"] == 390
    assert result["session_coverage"]["missing_slot_count"] == 0
    assert result["is_partial"] is True
    assert result["source_status"]["status"] == "partial"
    assert result["research_usable"] is False
    assert not any(point["finalized"] for point in result["points"])


@pytest.mark.parametrize("defect,field", [("duplicate", "duplicate_count"), ("out_of_order", "non_monotonic_count"), ("off_grid", "off_grid_count")])
def test_public_coverage_rejects_bad_minute_identity(defect, field):
    # Exercise the production public coverage contract; no fixture-side calculation.
    times = [START + timedelta(minutes=i) for i in range(390)]
    if defect == "duplicate":
        times[120] = times[119]
    elif defect == "out_of_order":
        times[120], times[121] = times[121], times[120]
    else:
        times[120] += timedelta(seconds=30)
    coverage = USRegularSessionCoverage.model_validate(regular_intraday_coverage(times, trade_date=DAY))
    assert coverage.coverage_status == "partial"
    assert getattr(coverage, field) == 1


@pytest.mark.parametrize("yahoo,twelve,selected,count", [(378, 390, "twelve_data", 390), (195, 195, "yahoo_chart", 195)])
def test_single_provider_selection_never_stitches_or_promotes_sip_volume(db, yahoo, twelve, selected, count):
    seed(db, "SSO", yahoo)
    # Complementary halves would be 390 only if a consumer illegally stitched them.
    start = START if twelve == 390 else START + timedelta(minutes=195)
    seed(db, "SSO", twelve, twelve=True, start=start)
    result = historical(db, "SSO")
    assert result["source_status"]["provider"] == selected
    assert result["point_count"] == count
    assert result["is_partial"] is (count != 390)
    assert result["decision_usable"] is False
    assert all(point["volume_based_decision_usable"] is False for point in result["points"])
    if selected == "twelve_data":
        assert {"PARTIAL_US_MARKET_VOLUME", "PERSONAL_INTERNAL_USE_ONLY"} <= set(result["warnings"])
        assert result["research_usable"] is False
        assert result["session_coverage"]["coverage_status"] == "complete"


def test_missing_volume_preserves_null(db):
    seed(db, "AMD", 390, missing_volume=True)
    result = historical(db, "AMD")
    assert result["point_count"] == 390
    assert result["points"][0]["volume"] is None
    assert all(point["volume"] != 0 for point in result["points"])


def test_market_truth_stale_quote_and_complete_bars_are_independent(monkeypatch):
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 8, 31, 13, 30, tzinfo=UTC)
    bars = tuple(_bar(observation_id=f"gc-{i}", start_at=start + timedelta(minutes=i),
                      end_at=start + timedelta(minutes=i + 1), close="200") for i in range(390))
    quote = quote.model_copy(update={
        "health": quote.health.model_copy(update={"status": ResolvedEvidenceStatus.STALE, "research_usable": False}),
        "candidates": tuple(c.model_copy(update={"freshness": EvidenceFreshness.STALE}) for c in quote.candidates),
    })
    intraday = intraday.model_copy(update={"bars": bars})
    _install_fake_components(monkeypatch, (quote, intraday, daily))
    bundle = read_us_market_truth_bundle(object(), symbol="AAPL",
        evaluated_at=datetime(2026, 9, 1, 1, tzinfo=UTC), requested_scope="regular")
    assert bundle.snapshot.quote_observation.freshness is EvidenceFreshness.STALE
    assert bundle.snapshot.quote_observation.selected_source == "yahoo.chart.quote"
    assert bundle.series.continuity == "complete"
    assert bundle.series.regular_session_coverage.point_count == 390
    assert bundle.series.regular_session_coverage.unfinalized_count == 0


@pytest.mark.parametrize("day,utc_hour,count", [(date(2026, 3, 6), 14, 390), (date(2026, 3, 9), 13, 390), (date(2026, 11, 2), 14, 390), (date(2026, 11, 27), 14, 210)])
def test_existing_calendar_dst_early_close_and_platform(db, day, utc_hour, count):
    now = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=1)
    start, end = completed_intraday_window(day, now=now)
    assert (start.hour, start.minute) == (9, 30)
    assert start.astimezone(UTC).hour == utc_hour
    assert int((end - start).total_seconds() / 60) == count
    seed(db, "AMD", count, start=start.astimezone(UTC), now=now)
    result = historical(db, "AMD", day, now)
    assert result["session_coverage"]["expected_point_count"] == count
    assert result["point_count"] == count
    assert result["is_partial"] is False


@pytest.mark.parametrize("day", [date(2026, 7, 3), date(2026, 10, 10), date(2026, 12, 25)])
def test_existing_calendar_holiday_or_weekend_has_no_completed_session(day):
    with pytest.raises(ValueError, match="NO_TRADING_SESSION"):
        completed_intraday_window(day, now=datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC))
