from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, RawFetchResult, SourceRegistry
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.contracts import (
    AuctionObservation,
    AuctionType,
    AuthorityClass,
    BarFinalization,
    BarObservation,
    DatasetHealth,
    DatasetHealthStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    ResolvedEvidenceStatus,
    SourceLineage,
)
from app.market_data.gateway import (
    AcquisitionBudgetExceeded,
    BarAcquisitionResult,
    BarCandidateBatch,
    MarketDataGateway,
)
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DataAcquisitionPlanV2,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)
from app.market_data.resolution import BarSeriesCandidate, ResolutionCandidate, resolve_auction
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 21, 14, 0, tzinfo=TAIPEI)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _bar(
    *,
    trade_date: date = date(2026, 8, 21),
    provider: str = "twse_openapi",
    cache_hit: bool = True,
) -> BarObservation:
    start_at = datetime.combine(trade_date, time(9), tzinfo=TAIPEI)
    end_at = datetime.combine(trade_date, time(13, 30), tzinfo=TAIPEI)
    return BarObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider=provider,
            source=f"{provider}.daily",
            authority=AuthorityClass.EXCHANGE,
            event_at=end_at,
            fetched_at=end_at + timedelta(minutes=5),
            cache_hit=cache_hit,
        ),
        interval="1d",
        start_at=start_at,
        end_at=end_at,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("95"),
        close_price=Decimal("105"),
        volume=Quantity(value=Decimal("1000"), unit=QuantityUnit.SHARE),
        finalization=BarFinalization.FINAL,
    )


def _health(status: DatasetHealthStatus = DatasetHealthStatus.HEALTHY) -> DatasetHealth:
    return DatasetHealth(
        dataset_id="tw.daily.ohlcv",
        market=Market.TW,
        status=status,
        expected_date=date(2026, 8, 21),
        latest_date=date(2026, 8, 21) if status is not DatasetHealthStatus.MISSING else None,
        checked_at=NOW,
        refreshable=True,
        refresh_operation="tw.refresh_daily_price",
    )


def _requirement(policy: RealtimePolicy, *, max_calls: int = 0) -> DataRequirementV2:
    return DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=datetime(2026, 8, 20, 9, 0, tzinfo=TAIPEI),
            end_at=datetime(2026, 8, 21, 13, 30, tzinfo=TAIPEI),
            max_bars=2,
            completed_only=policy is RealtimePolicy.COMPLETED_SESSION,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=policy,
        session=MarketSession.CLOSED,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=86400),
        bounds=RequestBounds(
            max_provider_attempts=1 if max_calls else 0,
            max_external_calls=max_calls,
            max_rows=10,
        ),
    )


class FakeReader:
    def __init__(
        self,
        batches: list[BarCandidateBatch],
        events: list[str] | None = None,
    ) -> None:
        self._batches = batches
        self._events = events
        self.calls = 0

    def read_bar_candidates(self, _requirement: DataRequirementV2) -> BarCandidateBatch:
        if self._events is not None:
            self._events.append("read")
        index = min(self.calls, len(self._batches) - 1)
        self.calls += 1
        return self._batches[index]


class FakeAcquisition:
    def __init__(
        self,
        summary: AcquisitionSummary,
        *,
        observations: tuple[BarObservation, ...] = (),
        receipts: tuple[RawFetchReceiptV1, ...] = (),
        events: list[str] | None = None,
    ) -> None:
        self.summary = summary
        self.observations = observations
        self.receipts = receipts
        self._events = events
        self.calls = 0

    def acquire_bar_observations(
        self,
        _requirement: DataRequirementV2,
        _plan: DataAcquisitionPlanV2,
    ) -> BarAcquisitionResult:
        if self._events is not None:
            self._events.append("acquire")
        self.calls += 1
        return BarAcquisitionResult(
            summary=self.summary,
            observations=self.observations,
            receipts=self.receipts,
        )


class FakeTransaction:
    def __init__(
        self,
        *,
        events: list[str] | None = None,
        unchanged: bool = False,
        fail: bool = False,
    ) -> None:
        self._events = events
        self._unchanged = unchanged
        self._fail = fail
        self.calls = 0
        self.rolled_back = False

    def persist_bar_acquisition(
        self,
        _requirement: DataRequirementV2,
        acquisition: BarAcquisitionResult,
    ) -> PersistenceSummary:
        if self._events is not None:
            self._events.append("persist")
        self.calls += 1
        if self._fail:
            self.rolled_back = True
            raise RuntimeError("transaction rolled back")
        return PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=len(acquisition.receipts),
            observations_written=0 if self._unchanged else len(acquisition.observations),
            observations_unchanged=len(acquisition.observations) if self._unchanged else 0,
            raw_result_ids=(1,) if acquisition.receipts else (),
        )


def _receipt() -> RawFetchReceiptV1:
    return RawFetchReceiptV1(
        provider="twse_openapi",
        source="twse_openapi.daily",
        resource_id="STOCK_DAY_ALL",
        fetched_at=NOW,
        method="GET",
        status_code=200,
        content_type="application/json",
        content_hash="a" * 64,
        raw_text="[]",
        parser_version="twse_stock_day_all_v1",
    )


def _descriptor(*, live: bool = False) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key="twse_openapi",
        market=Market.TW,
        capability_id="daily.ohlcv",
        resource_id="STOCK_DAY_ALL",
        authority=AuthorityClass.EXCHANGE,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,),
        venue_scope=("TWSE",),
        instrument_types=(InstrumentType.STOCK,),
        intervals=("1d",),
        supported_sessions=(MarketSession.CLOSED,),
        acquisition_modes=(AcquisitionMode.FETCH,),
        can_produce_live=live,
        can_produce_final=True,
        max_external_calls_per_attempt=1,
        allow_unknown_health=True,
    )


def _attempt() -> AcquisitionResourceAttempt:
    return AcquisitionResourceAttempt(
        provider="twse_openapi",
        resource_id="STOCK_DAY_ALL",
    )


def _batch(
    *,
    freshness: EvidenceFreshness,
    cache_hit: bool = True,
    health: DatasetHealth | None = None,
) -> BarCandidateBatch:
    return BarCandidateBatch(
        candidates=(
            BarSeriesCandidate(
                bars=(_bar(cache_hit=cache_hit),),
                freshness=freshness,
                provider_priority=10,
                session=MarketSession.CLOSED,
            ),
        ),
        dataset_health=health or _health(),
    )


def test_cache_only_resolves_persisted_candidate_with_zero_acquisition() -> None:
    reader = FakeReader([_batch(freshness=EvidenceFreshness.FRESH)])
    acquisition = FakeAcquisition(
        AcquisitionSummary(attempted=True, status=AcquisitionStatus.COMPLETED, external_calls=1)
    )

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.CACHE_ONLY),
        reader=reader,
        acquisition_port=acquisition,
    )

    assert reader.calls == 1
    assert acquisition.calls == 0
    assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert result.acquisition.attempted is False
    assert result.acquisition.limitations == ("PRE_RESOLUTION_SATISFIED",)


def test_prefer_live_stale_cache_acquires_then_must_reread() -> None:
    events: list[str] = []
    reader = FakeReader(
        [
            _batch(freshness=EvidenceFreshness.STALE, health=_health(DatasetHealthStatus.STALE)),
            _batch(freshness=EvidenceFreshness.FRESH),
        ],
        events,
    )
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=("twse_openapi",),
            resource_attempts=(_attempt(),),
            external_calls=1,
            elapsed_ms=50,
        ),
        observations=(_bar(cache_hit=False),),
        receipts=(_receipt(),),
        events=events,
    )
    transaction = FakeTransaction(events=events)

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
        reader=reader,
        descriptors=(_descriptor(),),
        acquisition_port=acquisition,
        transaction_port=transaction,
    )

    assert events == ["read", "acquire", "persist", "read"]
    assert acquisition.calls == 1
    assert transaction.calls == 1
    assert reader.calls == 2
    assert result.acquisition.attempted is True
    assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
    assert result.persistence.committed is True
    assert result.persistence.observations_written == 1
    assert result.persistence.raw_result_ids == (1,)


def test_require_live_without_port_is_truthful_policy_unsatisfied() -> None:
    reader = FakeReader([_batch(freshness=EvidenceFreshness.FRESH)])

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.REQUIRE_LIVE, max_calls=1),
        reader=reader,
        descriptors=(_descriptor(live=True),),
    )

    assert reader.calls == 1
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.acquisition.limitations == ("ACQUISITION_PORT_UNAVAILABLE",)


def test_gateway_fails_closed_when_port_exceeds_call_budget() -> None:
    reader = FakeReader([_batch(freshness=EvidenceFreshness.STALE)])
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.PARTIAL,
            providers_attempted=("twse_openapi",),
            resource_attempts=(_attempt(),),
            external_calls=2,
        )
    )

    with pytest.raises(AcquisitionBudgetExceeded, match="max_external_calls"):
        MarketDataGateway().resolve_bars(
            _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
            reader=reader,
            descriptors=(_descriptor(),),
            acquisition_port=acquisition,
            transaction_port=FakeTransaction(),
        )
    assert reader.calls == 1


def test_gateway_rejects_resource_attempt_outside_shared_plan() -> None:
    reader = FakeReader([_batch(freshness=EvidenceFreshness.STALE)])
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.FAILED,
            providers_attempted=("unplanned_provider",),
            resource_attempts=(
                AcquisitionResourceAttempt(
                    provider="unplanned_provider",
                    resource_id="unplanned_resource",
                ),
            ),
            external_calls=1,
        )
    )

    with pytest.raises(AcquisitionBudgetExceeded, match="outside the shared plan"):
        MarketDataGateway().resolve_bars(
            _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
            reader=reader,
            descriptors=(_descriptor(),),
            acquisition_port=acquisition,
            transaction_port=FakeTransaction(),
        )

    assert reader.calls == 1


def test_missing_descriptor_catalog_is_truthful_and_performs_no_io() -> None:
    reader = FakeReader([_batch(freshness=EvidenceFreshness.STALE)])
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=("twse_openapi",),
            resource_attempts=(_attempt(),),
            external_calls=1,
        )
    )

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
        reader=reader,
        acquisition_port=acquisition,
        transaction_port=FakeTransaction(),
    )

    assert acquisition.calls == 0
    assert result.acquisition.attempted is False
    assert result.acquisition.limitations == ("ACQUISITION_PLAN_UNFILLABLE",)
    assert result.resolved.health.status is ResolvedEvidenceStatus.STALE


def test_transaction_failure_propagates_after_rollback_without_reread() -> None:
    events: list[str] = []
    reader = FakeReader([_batch(freshness=EvidenceFreshness.STALE)], events)
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=("twse_openapi",),
            resource_attempts=(_attempt(),),
            external_calls=1,
        ),
        observations=(_bar(cache_hit=False),),
        receipts=(_receipt(),),
        events=events,
    )
    transaction = FakeTransaction(events=events, fail=True)

    with pytest.raises(RuntimeError, match="transaction rolled back"):
        MarketDataGateway().resolve_bars(
            _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
            reader=reader,
            descriptors=(_descriptor(),),
            acquisition_port=acquisition,
            transaction_port=transaction,
        )

    assert events == ["read", "acquire", "persist"]
    assert reader.calls == 1
    assert transaction.rolled_back is True


def test_idempotent_transaction_can_report_unchanged_then_reread() -> None:
    reader = FakeReader(
        [
            _batch(freshness=EvidenceFreshness.STALE),
            _batch(freshness=EvidenceFreshness.FRESH),
        ]
    )
    acquisition = FakeAcquisition(
        AcquisitionSummary(
            attempted=True,
            status=AcquisitionStatus.COMPLETED,
            providers_attempted=("twse_openapi",),
            resource_attempts=(_attempt(),),
            external_calls=1,
        ),
        observations=(_bar(cache_hit=False),),
        receipts=(_receipt(),),
    )
    transaction = FakeTransaction(unchanged=True)

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.PREFER_LIVE, max_calls=1),
        reader=reader,
        descriptors=(_descriptor(),),
        acquisition_port=acquisition,
        transaction_port=transaction,
    )

    assert result.persistence.observations_written == 0
    assert result.persistence.observations_unchanged == 1
    assert reader.calls == 2
    assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED


def test_completed_session_policy_never_calls_acquisition() -> None:
    reader = FakeReader([BarCandidateBatch(dataset_health=_health(DatasetHealthStatus.MISSING))])
    acquisition = FakeAcquisition(
        AcquisitionSummary(attempted=True, status=AcquisitionStatus.COMPLETED, external_calls=1)
    )

    result = MarketDataGateway().resolve_bars(
        _requirement(RealtimePolicy.COMPLETED_SESSION),
        reader=reader,
        acquisition_port=acquisition,
    )

    assert acquisition.calls == 0
    assert result.resolved.health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED
    assert result.acquisition.limitations == ("READ_POLICY_FORBIDS_ACQUISITION",)


def test_actual_tw_repository_can_flow_through_cache_gateway() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        source = SourceRegistry(
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
            source_type="api",
            category="market_data",
            priority=10,
            parser_type="twse_daily_trading",
            reliability_level="official",
        )
        db.add(source)
        db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=NOW,
            raw_text="[]",
            content_hash="fixture-hash",
        )
        db.add(raw)
        db.flush()
        db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=date(2026, 8, 21),
                stock_id="2330",
                open_price=100,
                high_price=110,
                low_price=95,
                close_price=105,
                trade_volume=1000,
            )
        )
        db.commit()
        reader = TaiwanCompletedDailyCandidateReader(TaiwanOfficialDailyBarRepository(db))

        result = MarketDataGateway().resolve_bars(
            _requirement(RealtimePolicy.CACHE_ONLY),
            reader=reader,
        )

        assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
        assert result.resolved.bars[0].lineage.observation_id is not None
        assert result.dataset_health is not None
        assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
        assert result.acquisition.attempted is False
    finally:
        db.close()
        engine.dispose()


def test_auction_has_a_typed_resolved_contract() -> None:
    observation = AuctionObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider="twse_mis",
            source="twse_mis.auction",
            authority=AuthorityClass.EXCHANGE,
            event_at=NOW,
        ),
        auction_type=AuctionType.CLOSING,
        state=ObservationState.INDICATIVE,
        indicative_price=Decimal("105"),
        provisional=True,
    )

    resolved = resolve_auction(
        (
            ResolutionCandidate(
                observation=observation,
                freshness=EvidenceFreshness.LIVE,
                provider_priority=10,
                session=MarketSession.CLOSING_AUCTION,
            ),
        ),
        policy=RealtimePolicy.REQUIRE_LIVE,
        now=NOW,
        max_age=timedelta(minutes=1),
    )

    assert resolved.auction is observation
    assert resolved.health.status is ResolvedEvidenceStatus.SELECTED
