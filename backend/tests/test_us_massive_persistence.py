from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    USDailyPrice,
    USQuoteSnapshot,
)
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    SourceLineage,
)
from app.market_data.gateway import BarAcquisitionResult, QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    ProviderTimeframe,
    RawFetchReceiptV1,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.us_market.intraday_repository import (
    USIntradayBarRepository,
    USQuoteRepository,
)
from app.us_market.daily_price_repository import USDailyBarRepository
from app.us_market.daily_price_transaction import USDailyPriceTransaction
from app.us_market.intraday_transaction import (
    USIntradayBarTransaction,
    USQuoteTransaction,
)
from app.us_market.market_data.descriptors import (
    MASSIVE_INDEX_DAILY_DESCRIPTOR,
    MASSIVE_INDEX_DAILY_RESOURCE_ID,
    MASSIVE_INDEX_INTRADAY_DESCRIPTOR,
    MASSIVE_INDEX_INTRADAY_RESOURCE_ID,
    MASSIVE_INDEX_QUOTE_DESCRIPTOR,
    MASSIVE_INDEX_QUOTE_RESOURCE_ID,
)
from app.us_market.providers.canonical import canonical_massive_index_snapshot_payload


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol="^GSPC",
        instrument_type=InstrumentType.INDEX,
        venue="INDEX",
    )


def _bounds() -> RequestBounds:
    return RequestBounds(
        max_provider_attempts=1,
        max_external_calls=1,
        max_rows=100,
        max_candidates=8,
    )


def _summary(resource_id: str) -> AcquisitionSummary:
    return AcquisitionSummary(
        attempted=True,
        status=AcquisitionStatus.COMPLETED,
        providers_attempted=("massive",),
        resource_attempts=(
            AcquisitionResourceAttempt(
                provider="massive",
                resource_id=resource_id,
            ),
        ),
        external_calls=1,
    )


def _receipt(
    *,
    resource_id: str,
    source: str,
    parser_version: str,
    raw_text: str,
    fetched_at: datetime,
    timeframe: ProviderTimeframe | None = None,
) -> RawFetchReceiptV1:
    return RawFetchReceiptV1(
        provider="massive",
        source=source,
        resource_id=resource_id,
        fetched_at=fetched_at,
        method="GET",
        url="https://api.massive.com/redacted",
        status_code=200,
        content_type="application/json",
        content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        raw_text=raw_text,
        parser_version=parser_version,
        provider_timeframe=timeframe,
    )


def test_massive_quote_round_trip_preserves_delayed_timeframe() -> None:
    db = _db()
    event_at = datetime(2026, 9, 1, 19, 59, tzinfo=timezone.utc)
    fetched_at = event_at + timedelta(seconds=30)
    raw_text = '{"fixture":"massive-snapshot"}'
    receipt = _receipt(
        resource_id=MASSIVE_INDEX_QUOTE_RESOURCE_ID,
        source="massive.indices.snapshot",
        parser_version="massive.indices.snapshot.v3",
        raw_text=raw_text,
        fetched_at=fetched_at,
        timeframe=ProviderTimeframe.DELAYED,
    )
    batch = canonical_massive_index_snapshot_payload(
        instrument=_instrument(),
        payload={
            "results": [
                {
                    "ticker": "I:SPX",
                    "value": 6512.34,
                    "last_updated": int(event_at.timestamp() * 1_000_000_000),
                    "timeframe": "DELAYED",
                }
            ]
        },
        fetched_at=fetched_at,
    )
    quote = batch.snapshot.quote.model_copy(
        update={
            "lineage": batch.snapshot.quote.lineage.model_copy(
                update={"content_hash": receipt.content_hash}
            )
        }
    )
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=SnapshotCapabilityRequest(capability_id="quote.snapshot"),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=fetched_at,
        freshness=FreshnessRequirement(max_age_seconds=180),
        bounds=_bounds(),
    )
    acquisition = QuoteAcquisitionResult(
        summary=_summary(MASSIVE_INDEX_QUOTE_RESOURCE_ID),
        observations=(quote,),
        receipts=(receipt,),
    )

    USQuoteTransaction(db).persist_quote_acquisition(requirement, acquisition)
    row = db.query(USQuoteSnapshot).one()
    assert row.provider_timeframe == "delayed"
    assert USQuoteRepository(db).read_quote_candidates(requirement).candidates == ()
    reread = USQuoteRepository(
        db,
        descriptors=(MASSIVE_INDEX_QUOTE_DESCRIPTOR,),
    ).read_quote_candidates(requirement)
    assert len(reread.candidates) == 1
    assert reread.candidates[0].freshness is EvidenceFreshness.STALE
    assert "MASSIVE_PROVIDER_TIMEFRAME_DELAYED" in reread.candidates[0].limitations


def test_massive_intraday_round_trip_preserves_not_applicable_volume() -> None:
    db = _db()
    start_at = datetime(2026, 9, 1, 19, 58, tzinfo=timezone.utc)
    end_at = start_at + timedelta(minutes=1)
    fetched_at = end_at + timedelta(seconds=15)
    raw_text = '{"fixture":"massive-minute"}'
    receipt = _receipt(
        resource_id=MASSIVE_INDEX_INTRADAY_RESOURCE_ID,
        source="massive.indices.aggregates.1m",
        parser_version="massive.indices.aggregates.v2",
        raw_text=raw_text,
        fetched_at=fetched_at,
    )
    bar = BarObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider="massive",
            source="massive.indices.aggregates.1m",
            authority=AuthorityClass.VENDOR,
            raw_contract_version="massive.indices.aggregates.v2",
            event_at=start_at,
            fetched_at=fetched_at,
            content_hash=receipt.content_hash,
        ),
        interval="1m",
        start_at=start_at,
        end_at=end_at,
        open_price=Decimal("6500"),
        high_price=Decimal("6504"),
        low_price=Decimal("6498"),
        close_price=Decimal("6502"),
        volume=None,
        volume_status="not_applicable",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=BarCapabilityRequest(
            capability_id="intraday.bars",
            interval="1m",
            start_at=start_at,
            end_at=end_at + timedelta(minutes=1),
            max_bars=2,
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=fetched_at,
        freshness=FreshnessRequirement(max_age_seconds=180),
        bounds=_bounds(),
    )
    acquisition = BarAcquisitionResult(
        summary=_summary(MASSIVE_INDEX_INTRADAY_RESOURCE_ID),
        observations=(bar,),
        receipts=(receipt,),
    )

    USIntradayBarTransaction(db).persist_bar_acquisition(requirement, acquisition)
    row = db.query(MarketIntradayBar).one()
    lineage = db.query(MarketIntradayBarLineage).one()
    original_raw_result_id = lineage.raw_result_id
    repeated = USIntradayBarTransaction(db).persist_bar_acquisition(
        requirement,
        acquisition,
    )
    assert row.trade_volume is None
    assert row.volume_status == "not_applicable"
    assert lineage.provider == "massive"
    assert repeated.observations_written == 0
    assert repeated.observations_unchanged == 1
    assert lineage.raw_result_id == original_raw_result_id
    assert USIntradayBarRepository(db).read_bar_candidates(requirement).candidates == ()
    reread = USIntradayBarRepository(
        db,
        descriptors=(MASSIVE_INDEX_INTRADAY_DESCRIPTOR,),
    ).read_bar_candidates(requirement)
    assert len(reread.candidates) == 1
    assert reread.candidates[0].bars[0].volume is None
    assert reread.candidates[0].bars[0].volume_status == "not_applicable"


def test_massive_daily_round_trip_requires_explicit_canary_inventory() -> None:
    db = _db()
    start_at = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    end_at = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)
    fetched_at = end_at + timedelta(hours=1)
    raw_text = '{"fixture":"massive-daily"}'
    receipt = _receipt(
        resource_id=MASSIVE_INDEX_DAILY_RESOURCE_ID,
        source="massive.indices.aggregates.1d",
        parser_version="massive.indices.aggregates.v2",
        raw_text=raw_text,
        fetched_at=fetched_at,
        timeframe=ProviderTimeframe.DELAYED,
    )
    bar = BarObservation(
        instrument=_instrument(),
        lineage=SourceLineage(
            provider="massive",
            source="massive.indices.aggregates.1d",
            authority=AuthorityClass.VENDOR,
            raw_contract_version="massive.indices.aggregates.v2",
            event_at=start_at,
            fetched_at=fetched_at,
            content_hash=receipt.content_hash,
        ),
        interval="1d",
        start_at=start_at,
        end_at=end_at,
        open_price=Decimal("6500"),
        high_price=Decimal("6520"),
        low_price=Decimal("6490"),
        close_price=Decimal("6510"),
        volume=None,
        volume_status="not_applicable",
        price_basis="raw",
        finalization=BarFinalization.FINAL,
    )
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=_instrument()),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=start_at,
            end_at=end_at,
            max_bars=1,
            completed_only=True,
            price_basis="raw",
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CLOSED,
        requested_at=fetched_at,
        freshness=FreshnessRequirement(max_age_seconds=86_400),
        bounds=_bounds(),
    )
    acquisition = BarAcquisitionResult(
        summary=_summary(MASSIVE_INDEX_DAILY_RESOURCE_ID),
        observations=(bar,),
        receipts=(receipt,),
    )

    USDailyPriceTransaction(db).persist_bar_acquisition(requirement, acquisition)
    assert db.query(USDailyPrice).one().volume_status == "not_applicable"
    query = DailyBarCandidateQuery(
        instrument=_instrument(),
        start_date=start_at.date(),
        end_date=end_at.date(),
        max_rows=10,
    )
    production_read = USDailyBarRepository(db).load_daily_bars(query)
    assert production_read.series == ()
    assert production_read.rejections[0].reason_code == "US_DAILY_PROVIDER_UNREGISTERED"
    canary_read = USDailyBarRepository(
        db,
        descriptors=(MASSIVE_INDEX_DAILY_DESCRIPTOR,),
    ).load_daily_bars(query)
    assert len(canary_read.series) == 1
    assert canary_read.series[0].provider == "massive"
    assert canary_read.series[0].bars[0].volume_status == "not_applicable"
