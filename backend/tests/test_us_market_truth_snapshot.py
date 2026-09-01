from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    CandidateSummary,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    QuoteObservation,
    ResolvedBarSeries,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
    ResolvedQuote,
    SourceLineage,
    TradeObservationState,
)
from app.us_market.daily_market_state import USInstrumentIdentity
from app.us_market.market_truth import (
    _comparison_evidence,
    _intraday_close_evidence,
    read_us_market_truth_bundle,
    read_us_market_truth_snapshot,
)
from app.us_market.market_truth_contracts import (
    USChangeCalculationStatus,
    USCloseEvidenceKind,
    USComparisonPurpose,
    USMarketTruthAvailability,
    USObservation,
    USObservationKind,
)
from app.us_market.market_truth_shadow import compare_legacy_to_us_market_truth


UTC = timezone.utc
EVALUATED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
AAPL = InstrumentKey(
    market=Market.US,
    symbol="AAPL",
    instrument_type=InstrumentType.STOCK,
    venue="NASDAQ",
)
IDENTITY = USInstrumentIdentity(
    instrument=AAPL,
    identity_source="us_stock_master",
    volume_applicability="required",
)


def _lineage(
    observation_id: str,
    *,
    event_at: datetime,
    source: str,
) -> SourceLineage:
    return SourceLineage(
        provider="yahoo_chart",
        source=source,
        authority=AuthorityClass.VENDOR,
        raw_contract_version="yahoo.chart.v8",
        event_at=event_at,
        fetched_at=event_at + timedelta(seconds=2),
        observation_id=observation_id,
        content_hash=(observation_id.replace(":", "") + "0" * 64)[:64],
    )


def _health(
    *,
    source: str,
    session: MarketSession,
    event_at: datetime,
    status: ResolvedEvidenceStatus = ResolvedEvidenceStatus.SELECTED,
    facts_usable: bool = True,
    research_usable: bool = True,
    limitations: tuple[str, ...] = (),
) -> ResolvedEvidenceHealth:
    return ResolvedEvidenceHealth(
        status=status,
        selected_provider=("yahoo_chart" if status is not ResolvedEvidenceStatus.MISSING else None),
        selected_source=(source if status is not ResolvedEvidenceStatus.MISSING else None),
        selected_session=(session if status is not ResolvedEvidenceStatus.MISSING else None),
        selected_event_at=(event_at if status is not ResolvedEvidenceStatus.MISSING else None),
        selection_reason="FIXTURE_SELECTED",
        facts_usable=facts_usable,
        research_usable=research_usable,
        limitations=limitations,
    )


def _candidate(
    *,
    source: str,
    session: MarketSession,
    event_at: datetime,
) -> CandidateSummary:
    return CandidateSummary(
        provider="yahoo_chart",
        source=source,
        freshness=EvidenceFreshness.FRESH,
        authority=AuthorityClass.VENDOR,
        session=session,
        event_at=event_at,
        eligible=True,
        reason_code="ELIGIBLE",
    )


def _bar(
    *,
    observation_id: str,
    start_at: datetime,
    end_at: datetime,
    close: str,
    interval: str = "1m",
) -> BarObservation:
    value = Decimal(close)
    return BarObservation(
        instrument=AAPL,
        lineage=_lineage(
            observation_id,
            event_at=start_at,
            source=f"yahoo.chart.{interval}",
        ),
        interval=interval,
        start_at=start_at,
        end_at=end_at,
        open_price=value,
        high_price=value,
        low_price=value,
        close_price=value,
        price_basis="raw",
        volume_status="missing",
        finalization=BarFinalization.FINAL,
    )


def _fake_components(
    *,
    include_regular_close: bool = True,
    quote_available: bool = True,
    intraday_available: bool = True,
    daily_available: bool = True,
    intraday_limitations: tuple[str, ...] = (),
):
    quote_event = datetime(2026, 9, 1, 11, 59, tzinfo=UTC)
    quote = QuoteObservation(
        instrument=AAPL,
        lineage=_lineage(
            "quote-aapl-v1",
            event_at=quote_event,
            source="yahoo.chart.quote",
        ),
        trade_date=date(2026, 9, 1),
        currency="USD",
        state=ObservationState.AVAILABLE,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        last_trade_price=Decimal("201"),
        previous_close=Decimal("200"),
    )
    resolved_quote = ResolvedQuote(
        quote=(quote if quote_available else None),
        health=_health(
            source="yahoo.chart.quote",
            session=MarketSession.PRE_OPEN,
            event_at=quote_event,
            status=(
                ResolvedEvidenceStatus.SELECTED
                if quote_available
                else ResolvedEvidenceStatus.MISSING
            ),
            facts_usable=quote_available,
            research_usable=quote_available,
        ),
        candidates=((
            _candidate(
                source="yahoo.chart.quote",
                session=MarketSession.PRE_OPEN,
                event_at=quote_event,
            ),
        ) if quote_available else ()),
    )

    regular_start = datetime(2026, 8, 31, 19, 59, tzinfo=UTC)
    close_boundary_start = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    intraday = (
        *(
            (
                _bar(
                    observation_id="bar-aapl-1559-v1",
                    start_at=regular_start,
                    end_at=regular_start + timedelta(minutes=1),
                    close="199.80",
                ),
            )
            if include_regular_close
            else ()
        ),
        _bar(
            observation_id="bar-aapl-1600-v1",
            start_at=close_boundary_start,
            end_at=close_boundary_start + timedelta(minutes=1),
            close="200",
        ),
    )
    resolved_intraday = ResolvedBarSeries(
        bars=(intraday if intraday_available else ()),
        health=_health(
            source="yahoo.chart.1m",
            session=MarketSession.CLOSING_AUCTION,
            event_at=close_boundary_start,
            status=(
                ResolvedEvidenceStatus.SELECTED
                if intraday_available
                else ResolvedEvidenceStatus.MISSING
            ),
            facts_usable=intraday_available,
            research_usable=intraday_available,
            limitations=intraday_limitations,
        ),
        candidates=((
            _candidate(
                source="yahoo.chart.1m",
                session=MarketSession.CLOSING_AUCTION,
                event_at=close_boundary_start,
            ),
        ) if intraday_available else ()),
    )

    daily_end = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
    daily = _bar(
        observation_id="daily-aapl-20260828-v1",
        start_at=datetime(2026, 8, 28, 13, 30, tzinfo=UTC),
        end_at=daily_end,
        close="198",
        interval="1d",
    )
    resolved_daily = ResolvedBarSeries(
        bars=((daily,) if daily_available else ()),
        health=_health(
            source="yahoo.chart.1d",
            session=MarketSession.CLOSED,
            event_at=daily_end,
            status=(
                ResolvedEvidenceStatus.SELECTED
                if daily_available
                else ResolvedEvidenceStatus.MISSING
            ),
            facts_usable=daily_available,
            research_usable=daily_available,
        ),
        candidates=((
            _candidate(
                source="yahoo.chart.1d",
                session=MarketSession.CLOSED,
                event_at=daily_end,
            ),
        ) if daily_available else ()),
    )
    return resolved_quote, resolved_intraday, resolved_daily


def _install_fake_components(monkeypatch, components) -> None:
    quote, intraday, daily = components

    class FakeIntradayPlatform:
        def __init__(self, db):
            pass

        def read_quote(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=quote, limitations=()),
            )

        def read_intraday_bars(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=intraday, limitations=()),
            )

    class FakeDailyPlatform:
        def __init__(self, db):
            pass

        def read(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=daily, limitations=()),
            )

    monkeypatch.setattr(
        "app.us_market.market_truth.USIntradayMarketPlatform",
        FakeIntradayPlatform,
    )
    monkeypatch.setattr(
        "app.us_market.market_truth.USDailyOhlcvPlatform",
        FakeDailyPlatform,
    )


def test_snapshot_is_deterministic_and_uses_limited_hint(monkeypatch) -> None:
    quote, intraday, daily = _fake_components(include_regular_close=False)
    sessions: list[object] = []
    read_times: list[datetime] = []

    class FakeIntradayPlatform:
        def __init__(self, db):
            sessions.append(db)

        def read_quote(self, *, symbol: str, now: datetime):
            assert symbol == "AAPL"
            read_times.append(now)
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=quote, limitations=()),
            )

        def read_intraday_bars(self, *, symbol: str, bars: int, now: datetime):
            assert symbol == "AAPL"
            assert bars == 5000
            read_times.append(now)
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=intraday, limitations=()),
            )

    class FakeDailyPlatform:
        def __init__(self, db):
            sessions.append(db)

        def read(self, *, symbol: str, bars: int, now: datetime):
            assert symbol == "AAPL"
            assert bars == 30
            read_times.append(now)
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=daily, limitations=()),
            )

    monkeypatch.setattr(
        "app.us_market.market_truth.USIntradayMarketPlatform",
        FakeIntradayPlatform,
    )
    monkeypatch.setattr(
        "app.us_market.market_truth.USDailyOhlcvPlatform",
        FakeDailyPlatform,
    )
    caller_session = object()

    first = read_us_market_truth_snapshot(
        caller_session,
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )
    second = read_us_market_truth_snapshot(
        caller_session,
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )

    assert sessions == [caller_session, caller_session] * 2
    assert read_times == [EVALUATED_AT] * 6
    assert first.evaluation_id != second.evaluation_id
    assert first.evidence_revision == second.evidence_revision
    assert first.truth_revision == second.truth_revision
    assert first.current_observation is not None
    assert first.current_observation.kind.value == "quote"
    assert first.close_roles.latest_completed_id is None
    headline_reference = next(
        item
        for item in first.comparison_references
        if item.purpose is USComparisonPurpose.HEADLINE_CHANGE
    )
    headline_metric = next(
        item
        for item in first.change_metrics
        if item.purpose is USComparisonPurpose.HEADLINE_CHANGE
    )
    assert headline_reference.reason_code == (
        "PROVIDER_PREVIOUS_CLOSE_LIMITED"
    )
    assert headline_metric.calculation_status is (
        USChangeCalculationStatus.LIMITED
    )
    assert headline_metric.absolute_change == Decimal("1")
    assert {item.purpose for item in first.change_metrics} == set(
        USComparisonPurpose
    )


def test_close_boundary_is_preserved_but_not_promoted_to_official(monkeypatch) -> None:
    quote, intraday, daily = _fake_components()

    class FakeIntradayPlatform:
        def __init__(self, db):
            pass

        def read_quote(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=quote, limitations=()),
            )

        def read_intraday_bars(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=intraday, limitations=()),
            )

    class FakeDailyPlatform:
        def __init__(self, db):
            pass

        def read(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=daily, limitations=()),
            )

    monkeypatch.setattr(
        "app.us_market.market_truth.USIntradayMarketPlatform",
        FakeIntradayPlatform,
    )
    monkeypatch.setattr(
        "app.us_market.market_truth.USDailyOhlcvPlatform",
        FakeDailyPlatform,
    )

    snapshot = read_us_market_truth_snapshot(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )

    close_boundary = next(
        item
        for item in snapshot.close_evidence
        if item.evidence_kind
        is USCloseEvidenceKind.UNVERIFIED_CLOSE_BOUNDARY_BAR
    )
    assert close_boundary.official_close_proof.value == "none"
    assert close_boundary.research_usable is False
    assert "CLOSE_BOUNDARY_NOT_OFFICIAL" in close_boundary.limitations


def test_series_keeps_close_boundary_out_of_regular_points(monkeypatch) -> None:
    quote, intraday, daily = _fake_components()

    class FakeIntradayPlatform:
        def __init__(self, db):
            pass

        def read_quote(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=quote, limitations=()),
            )

        def read_intraday_bars(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=intraday, limitations=()),
            )

    class FakeDailyPlatform:
        def __init__(self, db):
            pass

        def read(self, **kwargs):
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=daily, limitations=()),
            )

    monkeypatch.setattr(
        "app.us_market.market_truth.USIntradayMarketPlatform",
        FakeIntradayPlatform,
    )
    monkeypatch.setattr(
        "app.us_market.market_truth.USDailyOhlcvPlatform",
        FakeDailyPlatform,
    )

    bundle = read_us_market_truth_bundle(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
        requested_scope="all",
    )

    assert bundle.series.truth_revision == bundle.snapshot.truth_revision
    assert bundle.series.scheduled_interval_count == 390
    assert bundle.series.observed_interval_count == 1
    assert bundle.series.missing_interval_count == 389
    assert len(bundle.series.regular_points) == 1
    assert len(bundle.series.close_boundary_events) == 1
    assert bundle.series.close_boundary_events[0].start_at == datetime(
        2026, 8, 31, 20, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("missing_component", "expected_availability"),
    (
        ("quote", USMarketTruthAvailability.MISSING),
        ("intraday", USMarketTruthAvailability.MISSING),
        ("daily", USMarketTruthAvailability.MISSING),
    ),
)
def test_snapshot_preserves_typed_partial_component_health(
    monkeypatch,
    missing_component: str,
    expected_availability: USMarketTruthAvailability,
) -> None:
    components = _fake_components(
        quote_available=missing_component != "quote",
        intraday_available=missing_component != "intraday",
        daily_available=missing_component != "daily",
    )
    _install_fake_components(monkeypatch, components)

    snapshot = read_us_market_truth_snapshot(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )

    component = getattr(snapshot.health, missing_component)
    assert component.availability is expected_availability
    assert component.reason_code == "COMPONENT_EVIDENCE_MISSING"
    remaining = {"quote", "intraday", "daily"} - {missing_component}
    assert all(
        getattr(snapshot.health, name).availability
        is USMarketTruthAvailability.AVAILABLE
        for name in remaining
    )


def test_snapshot_all_missing_is_truthful_and_referentially_complete(monkeypatch) -> None:
    _install_fake_components(
        monkeypatch,
        _fake_components(
            quote_available=False,
            intraday_available=False,
            daily_available=False,
        ),
    )

    snapshot = read_us_market_truth_snapshot(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )

    assert snapshot.latest_observation is None
    assert snapshot.current_observation is None
    assert snapshot.headline_observation is None
    assert snapshot.close_evidence == ()
    assert all(
        item.availability is USMarketTruthAvailability.MISSING
        for item in (
            snapshot.health.quote,
            snapshot.health.intraday,
            snapshot.health.daily,
        )
    )
    assert len(snapshot.comparison_references) == 4
    assert all(not item.calculation_eligible for item in snapshot.comparison_references)
    assert all(
        item.calculation_status is USChangeCalculationStatus.MISSING
        for item in snapshot.change_metrics
    )


def _complete_regular_bars(
    *,
    start_at: datetime,
    count: int,
) -> tuple[BarObservation, ...]:
    return tuple(
        _bar(
            observation_id=f"complete-{start_at.date()}-{index}",
            start_at=start_at + timedelta(minutes=index),
            end_at=start_at + timedelta(minutes=index + 1),
            close="200",
        )
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("trade_date", "start_at", "scheduled_count"),
    (
        (date(2026, 8, 31), datetime(2026, 8, 31, 13, 30, tzinfo=UTC), 390),
        (date(2026, 11, 27), datetime(2026, 11, 27, 14, 30, tzinfo=UTC), 210),
    ),
)
def test_final_regular_interval_requires_complete_dynamic_session(
    trade_date: date,
    start_at: datetime,
    scheduled_count: int,
) -> None:
    bars = _complete_regular_bars(start_at=start_at, count=scheduled_count)
    resolved = ResolvedBarSeries(
        bars=bars,
        health=_health(
            source="yahoo.chart.1m",
            session=MarketSession.CONTINUOUS,
            event_at=bars[-1].end_at,
        ),
        candidates=(
            _candidate(
                source="yahoo.chart.1m",
                session=MarketSession.CONTINUOUS,
                event_at=bars[-1].end_at,
            ),
        ),
    )

    evidence = _intraday_close_evidence(
        resolved,
        target_dates={trade_date},
        evaluated_at=bars[-1].end_at + timedelta(minutes=1),
    )

    assert len(evidence) == 1
    assert evidence[0].display_usable is True
    assert "REGULAR_SESSION_CONTINUITY_INCOMPLETE" not in evidence[0].limitations


def test_interval_close_fails_visible_on_integrity_or_continuity_defect() -> None:
    _, intraday, _ = _fake_components(
        intraday_limitations=(
            "NON_CANONICAL_MINUTE_IDENTITY",
            "DUPLICATE_MINUTE_BUCKET",
        )
    )

    evidence = _intraday_close_evidence(
        intraday,
        target_dates={date(2026, 8, 31)},
        evaluated_at=EVALUATED_AT,
    )
    interval = next(
        item
        for item in evidence
        if item.evidence_kind
        is USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE
    )

    assert interval.display_usable is False
    assert "INTRADAY_INTEGRITY_GATE_FAILED" in interval.limitations
    assert "REGULAR_SESSION_CONTINUITY_INCOMPLETE" in interval.limitations


def test_interval_close_requires_exact_scheduled_bucket_identity() -> None:
    bars = list(
        _complete_regular_bars(
            start_at=datetime(2026, 8, 31, 13, 30, tzinfo=UTC),
            count=390,
        )
    )
    bars[0] = bars[0].model_copy(
        update={
            "start_at": bars[0].start_at + timedelta(seconds=30),
            "end_at": bars[0].end_at + timedelta(seconds=30),
        }
    )
    resolved = ResolvedBarSeries(
        bars=tuple(bars),
        health=_health(
            source="yahoo.chart.1m",
            session=MarketSession.CONTINUOUS,
            event_at=bars[-1].end_at,
        ),
        candidates=(
            _candidate(
                source="yahoo.chart.1m",
                session=MarketSession.CONTINUOUS,
                event_at=bars[-1].end_at,
            ),
        ),
    )

    evidence = _intraday_close_evidence(
        resolved,
        target_dates={date(2026, 8, 31)},
        evaluated_at=EVALUATED_AT,
    )

    assert evidence[0].display_usable is False
    assert "REGULAR_SESSION_CONTINUITY_INCOMPLETE" in evidence[0].limitations


def test_after_hours_comparison_never_falls_back_to_prior_day_or_hint(
    monkeypatch,
) -> None:
    _install_fake_components(monkeypatch, _fake_components())
    snapshot = read_us_market_truth_snapshot(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )
    prior = next(
        item
        for item in snapshot.close_evidence
        if item.evidence_kind is USCloseEvidenceKind.COMPLETED_DAILY
    )
    hint = next(
        item
        for item in snapshot.close_evidence
        if item.evidence_kind
        is USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT
    )
    after_hours = snapshot.current_observation.model_copy(
        update={
            "session": MarketSession.POST_CLOSE,
            "trade_date": date(2026, 9, 1),
        }
    )

    assert (
        _comparison_evidence(
            purpose=USComparisonPurpose.HEADLINE_CHANGE,
            headline=after_hours,
            market_phase="after_hours",
            latest_close=prior,
            prior_close=prior,
            hint=hint,
        )
        is None
    )


def test_sqlite_bundle_reads_one_wal_generation_under_concurrent_writer(
    monkeypatch,
) -> None:
    database_path = Path(__file__).parent / f".us_truth_snapshot_{uuid4().hex}.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.execute(text("CREATE TABLE generation (value INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO generation(value) VALUES (1)"))
    quote, intraday, daily = _fake_components()
    seen: list[int] = []

    class FakeIntradayPlatform:
        def __init__(self, db):
            self.db = db

        def read_quote(self, **kwargs):
            seen.append(self.db.execute(text("SELECT value FROM generation")).scalar_one())
            with Session(engine) as writer:
                writer.execute(text("UPDATE generation SET value = 2"))
                writer.commit()
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=quote, limitations=()),
            )

        def read_intraday_bars(self, **kwargs):
            seen.append(self.db.execute(text("SELECT value FROM generation")).scalar_one())
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=intraday, limitations=()),
            )

    class FakeDailyPlatform:
        def __init__(self, db):
            self.db = db

        def read(self, **kwargs):
            seen.append(self.db.execute(text("SELECT value FROM generation")).scalar_one())
            return SimpleNamespace(
                identity=IDENTITY,
                result=SimpleNamespace(resolved=daily, limitations=()),
            )

    monkeypatch.setattr(
        "app.us_market.market_truth.USIntradayMarketPlatform",
        FakeIntradayPlatform,
    )
    monkeypatch.setattr(
        "app.us_market.market_truth.USDailyOhlcvPlatform",
        FakeDailyPlatform,
    )
    try:
        with Session(engine) as db:
            bundle = read_us_market_truth_bundle(
                db,
                symbol="AAPL",
                evaluated_at=EVALUATED_AT,
                requested_scope="all",
            )
        assert seen == [1, 1, 1]
        assert bundle.series.truth_revision == bundle.snapshot.truth_revision
    finally:
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)


def test_truth_shadow_diff_is_diagnostic_and_bounded(monkeypatch) -> None:
    _install_fake_components(
        monkeypatch,
        _fake_components(include_regular_close=False),
    )
    snapshot = read_us_market_truth_snapshot(
        object(),
        symbol="AAPL",
        evaluated_at=EVALUATED_AT,
    )

    matched = compare_legacy_to_us_market_truth(
        legacy={
            "symbol": "AAPL",
            "market_phase": "pre_market",
            "price": "201",
            "previous_close": None,
            "change": "1",
            "change_percent": "0.5",
        },
        truth=snapshot,
    )
    different = compare_legacy_to_us_market_truth(legacy={}, truth=snapshot)

    assert matched.status == "matched"
    assert different.status == "different"
    assert different.compared_fields == 6
    assert "DIAGNOSTIC_ONLY_NO_CONSUMER_CUTOVER" in different.limitations
