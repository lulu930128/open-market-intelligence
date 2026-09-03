from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockAuctionSnapshot,
    TaiwanStockDepthLevel,
    TaiwanStockDepthSnapshot,
    TaiwanStockQuoteSnapshot,
)
from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter,
    KgiRealtimeProviderSnapshot,
)
from app.market.providers.twse_mis_canonical import MIS_SOURCE
from app.market.realtime_snapshot_repository import (
    TaiwanAuctionRepository,
    TaiwanDepthRepository,
)
from app.market.realtime_snapshot_transaction import TaiwanDepthTransaction
from app.market.taiwan_realtime_platform import (
    acquire_taiwan_auction,
    acquire_taiwan_depth,
    build_taiwan_realtime_requirement,
    read_taiwan_auction,
    read_taiwan_depth,
)
from app.market.tw_realtime_capabilities import (
    KGI_AUCTION_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    MIS_AUCTION_DESCRIPTOR,
    MIS_ORDER_BOOK_DESCRIPTOR,
    TW_ORDER_BOOK_CAPABILITY_ID,
)
from app.market_data.contracts import (
    AuctionType,
    ConnectionStatus,
    DatasetHealthStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.integration_contracts import RequestBounds
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _quote(*, indicative: bool = False) -> dict[str, object]:
    return {
        "symbol": "2330",
        "datetime": "20260826100000",
        "received_at": "2026-08-26T02:00:00+00:00",
        "simtrade": 1 if indicative else 0,
        "close": 1180,
        "volume": 2,
        "total_volume": 100 if not indicative else 0,
        "open": 1170,
        "high": 1185,
        "low": 1165,
        "price_chg": 10,
        "bid_prices": [1175, 1170],
        "bid_volumes": [4, 5],
        "ask_prices": [1180, 1185],
        "ask_volumes": [3, 6],
    }


def _adapter(*, indicative: bool = False) -> KgiRealtimeAcquisitionAdapter:
    return KgiRealtimeAcquisitionAdapter(
        lambda _symbol: KgiRealtimeProviderSnapshot(
            quote=_quote(indicative=indicative),
            status="live",
        ),
        clock=lambda: NOW,
    )


def _health(capability_id: str) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=KGI_PROVIDER,
        market=Market.TW,
        capability=capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.LIVE,
        checked_at=NOW,
    )


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def test_depth_acquisition_persists_typed_lineage_then_rereads(db: Session) -> None:
    result = acquire_taiwan_depth(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
        acquisition=_adapter(),
        provider_health=(_health(KGI_ORDER_BOOK_DESCRIPTOR.capability_id),),
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )

    assert result.result_kind == "depth"
    assert result.persistence.committed is True
    assert result.persistence.observations_written == 1
    assert result.resolved.depth is not None
    assert result.resolved.depth.lineage.cache_hit is True
    assert result.resolved.depth.lineage.raw_receipt_id.startswith(
        "raw_fetch_result:"
    )
    assert result.resolved.depth.lineage.content_hash
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
    assert len(result.resolved.depth.bids) == 2
    assert len(result.resolved.depth.asks) == 2
    assert db.query(SourceRegistry).count() == 1
    assert db.query(RawFetchResult).count() == 1
    assert db.query(TaiwanStockDepthSnapshot).count() == 1
    assert db.query(TaiwanStockDepthLevel).count() == 4
    assert db.query(TaiwanStockQuoteSnapshot).count() == 0

    cached = read_taiwan_depth(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )
    assert cached.acquisition.attempted is False
    assert cached.resolved.depth == result.resolved.depth


def test_depth_candidate_read_is_provider_fair_before_total_bound(db: Session) -> None:
    acquire_taiwan_depth(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
        acquisition=_adapter(),
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )
    base = db.query(TaiwanStockDepthSnapshot).one()
    values = {
        column.name: getattr(base, column.name)
        for column in TaiwanStockDepthSnapshot.__table__.columns
        if column.name != "id"
    }
    db.add(
        TaiwanStockDepthSnapshot(
            **{
                **values,
                "provider": MIS_ORDER_BOOK_DESCRIPTOR.provider_key,
                "source": MIS_SOURCE,
                "event_at": NOW - timedelta(seconds=1),
            }
        )
    )
    for offset in range(1, 41):
        db.add(
            TaiwanStockDepthSnapshot(
                **{
                    **values,
                    "event_at": NOW + timedelta(seconds=offset),
                }
            )
        )
    db.commit()

    reads = TaiwanDepthRepository(db).load_candidates(
        _instrument(),
        max_candidates=2,
    )

    assert {read.provider for read in reads} == {
        KGI_ORDER_BOOK_DESCRIPTOR.provider_key,
        MIS_ORDER_BOOK_DESCRIPTOR.provider_key,
    }

    mis_row = db.query(TaiwanStockDepthSnapshot).filter_by(
        provider=MIS_ORDER_BOOK_DESCRIPTOR.provider_key
    ).one()
    mis_row.market_session = "close_resolution"
    mis_row.event_at = datetime(2026, 8, 26, 13, 30, tzinfo=TAIPEI)
    db.commit()
    closing_reads = TaiwanDepthRepository(db).load_candidates(
        _instrument(),
        max_candidates=2,
        trade_date=NOW.date(),
        allowed_sessions=(MarketSession.CLOSE_RESOLUTION,),
    )

    assert len(closing_reads) == 1
    assert closing_reads[0].provider == MIS_ORDER_BOOK_DESCRIPTOR.provider_key


def test_trial_auction_stays_provisional_and_never_becomes_quote(db: Session) -> None:
    result = acquire_taiwan_auction(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_AUCTION_DESCRIPTOR,),
        acquisition=_adapter(indicative=True),
        provider_health=(_health(KGI_AUCTION_DESCRIPTOR.capability_id),),
        requested_at=NOW,
        session=MarketSession.CLOSING_AUCTION,
    )

    assert result.persistence.committed is True
    assert result.resolved.auction is not None
    assert result.resolved.auction.state is ObservationState.INDICATIVE
    assert result.resolved.auction.provisional is True
    assert result.resolved.auction.lineage.cache_hit is True
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.HEALTHY
    assert db.query(TaiwanStockAuctionSnapshot).count() == 1
    assert db.query(TaiwanStockDepthSnapshot).count() == 0
    assert db.query(TaiwanStockQuoteSnapshot).count() == 0

    cached = read_taiwan_auction(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CLOSING_AUCTION,
    )
    assert cached.acquisition.attempted is False
    assert cached.resolved.auction == result.resolved.auction


def test_auction_candidate_read_is_provider_fair_before_total_bound(db: Session) -> None:
    acquire_taiwan_auction(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_AUCTION_DESCRIPTOR,),
        acquisition=_adapter(indicative=True),
        requested_at=NOW,
        session=MarketSession.CLOSING_AUCTION,
    )
    base = db.query(TaiwanStockAuctionSnapshot).one()
    values = {
        column.name: getattr(base, column.name)
        for column in TaiwanStockAuctionSnapshot.__table__.columns
        if column.name != "id"
    }
    db.add(
        TaiwanStockAuctionSnapshot(
            **{
                **values,
                "provider": MIS_AUCTION_DESCRIPTOR.provider_key,
                "source": MIS_SOURCE,
                "event_at": NOW - timedelta(seconds=1),
            }
        )
    )
    for offset in range(1, 41):
        db.add(
            TaiwanStockAuctionSnapshot(
                **{
                    **values,
                    "event_at": NOW + timedelta(seconds=offset),
                }
            )
        )
    db.commit()

    reads = TaiwanAuctionRepository(db).load_candidates(
        _instrument(),
        max_candidates=2,
        auction_type=AuctionType.CLOSING,
    )

    assert {read.provider for read in reads} == {
        KGI_AUCTION_DESCRIPTOR.provider_key,
        MIS_AUCTION_DESCRIPTOR.provider_key,
    }


def test_previous_session_auction_is_rejected_from_current_outward_read(
    db: Session,
) -> None:
    result = acquire_taiwan_auction(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_AUCTION_DESCRIPTOR,),
        acquisition=_adapter(indicative=True),
        requested_at=NOW,
        session=MarketSession.CLOSING_AUCTION,
    )
    assert result.persistence.committed is True

    stored = db.query(TaiwanStockAuctionSnapshot).one()
    stored.event_at = stored.event_at - timedelta(days=1)
    db.commit()

    cached = read_taiwan_auction(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CLOSING_AUCTION,
    )

    assert cached.resolved.auction is None
    assert cached.resolved.health.facts_usable is False
    assert cached.candidate_rejections[0].reason_code == "TW_AUCTION_EVENT_DATE_MISMATCH"
    assert "TW_AUCTION_EVENT_DATE_MISMATCH" in cached.limitations


def test_previous_session_depth_is_rejected_from_current_outward_read(
    db: Session,
) -> None:
    result = acquire_taiwan_depth(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
        acquisition=_adapter(),
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )
    assert result.persistence.committed is True

    stored = db.query(TaiwanStockDepthSnapshot).one()
    stored.event_at = stored.event_at - timedelta(days=1)
    db.commit()

    cached = read_taiwan_depth(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
    )

    assert cached.resolved.depth is None
    assert cached.resolved.health.facts_usable is False
    assert cached.candidate_rejections[0].reason_code == "TW_DEPTH_EVENT_DATE_MISMATCH"
    assert "TW_DEPTH_EVENT_DATE_MISMATCH" in cached.limitations


def test_auction_dataset_is_not_applicable_outside_auction_session(
    db: Session,
) -> None:
    result = read_taiwan_auction(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        disposition_status={"cache_status": "current", "is_active": False},
    )

    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.NOT_APPLICABLE


def test_disposition_intraday_auction_persists_and_rereads_by_type(
    db: Session,
) -> None:
    disposition = {"cache_status": "current", "is_active": True}
    result = acquire_taiwan_auction(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        descriptors=(KGI_AUCTION_DESCRIPTOR,),
        acquisition=_adapter(indicative=True),
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        disposition_status=disposition,
    )

    assert result.resolved.auction is not None
    assert result.resolved.auction.auction_type is AuctionType.INTRADAY
    assert result.persistence.committed is True
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.HEALTHY

    cached = read_taiwan_auction(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        disposition_status=disposition,
    )
    assert cached.resolved.auction is not None
    assert cached.resolved.auction.auction_type is AuctionType.INTRADAY


def test_unknown_disposition_cache_makes_intraday_auction_health_unknown(
    db: Session,
) -> None:
    result = read_taiwan_auction(
        db,
        stock_id="2330",
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        disposition_status={"cache_status": "missing", "is_active": False},
    )

    assert result.resolved.auction is None
    assert result.dataset_health is not None
    assert result.dataset_health.status is DatasetHealthStatus.UNKNOWN
    assert "DISPOSITION_CACHE_MISSING" in result.limitations


def test_depth_transaction_rolls_back_receipt_when_lineage_mismatches(
    db: Session,
) -> None:
    requirement = build_taiwan_realtime_requirement(
        instrument=_instrument(),
        capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=0,
            max_subscriptions=1,
            max_candidates=1,
            max_rows=1,
        ),
    )
    plan = plan_data_acquisition_v2(
        requirement,
        (KGI_ORDER_BOOK_DESCRIPTOR,),
        (_health(KGI_ORDER_BOOK_DESCRIPTOR.capability_id),),
    )
    acquired = _adapter().acquire_depth_observations(requirement, plan)
    bad = replace(
        acquired,
        observations=(
            acquired.observations[0].model_copy(
                update={
                    "lineage": acquired.observations[0].lineage.model_copy(
                        update={"content_hash": "0" * 64}
                    )
                }
            ),
        ),
    )

    with pytest.raises(ValueError, match="content hash"):
        TaiwanDepthTransaction(db).persist_depth_acquisition(requirement, bad)

    assert db.query(SourceRegistry).count() == 0
    assert db.query(RawFetchResult).count() == 0
    assert db.query(TaiwanStockDepthSnapshot).count() == 0


def test_depth_transaction_persists_event_session_instead_of_request_session(
    db: Session,
) -> None:
    requirement = build_taiwan_realtime_requirement(
        instrument=_instrument(),
        capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=NOW,
        session=MarketSession.CONTINUOUS,
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=0,
            max_subscriptions=1,
            max_candidates=1,
            max_rows=1,
        ),
    )
    plan = plan_data_acquisition_v2(
        requirement,
        (KGI_ORDER_BOOK_DESCRIPTOR,),
        (_health(KGI_ORDER_BOOK_DESCRIPTOR.capability_id),),
    )
    acquired = _adapter().acquire_depth_observations(requirement, plan)
    request_session_changed = requirement.model_copy(
        update={"session": MarketSession.OPENING_AUCTION}
    )

    TaiwanDepthTransaction(db).persist_depth_acquisition(
        request_session_changed,
        acquired,
    )

    assert db.query(TaiwanStockDepthSnapshot).one().market_session == "continuous"
