from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockQuoteSnapshot,
)
from app.market.providers.kgi_canonical import KGI_PROVIDER, KGI_SOURCE
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter,
    KgiRealtimeProviderSnapshot,
)
from app.market.providers.tw_public_quote import (
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
    TWSE_MIS_QUOTE_PARSER_VERSION,
    quote_observation_from_twse_mis,
)
from app.market.public_quote_acquisition import TaiwanPublicQuoteAcquisitionExecutor
from app.market.public_quote_platform import (
    TaiwanPublicQuoteCandidateReader,
    acquire_taiwan_public_last_trade_quote,
    build_taiwan_public_quote_requirement,
    read_taiwan_public_last_trade_quote,
    read_taiwan_session_close,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.tw_public_quote_contract import (
    TWSE_MIS_QUOTE_PROVIDER,
    TWSE_MIS_QUOTE_SOURCE_NAME,
)
from app.market.tw_realtime_capabilities import KGI_QUOTE_SNAPSHOT_DESCRIPTOR
from app.market_data.contracts import (
    AuthorityClass,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ResolvedEvidenceStatus,
)
from app.market_data.gateway import MarketDataGateway, QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    QualityRequirement,
    RawFetchReceiptV1,
    RequestBounds,
)
from app.market_data.policies import RealtimePolicy


TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=TAIPEI)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
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


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _kgi_quote() -> dict[str, object]:
    return {
        "symbol": "2330",
        "datetime": "20260826100000",
        "received_at": "2026-08-26T02:00:00+00:00",
        "simtrade": 0,
        "close": 1180,
        "volume": 2,
        "total_volume": 100,
        "open": 1170,
        "high": 1185,
        "low": 1165,
        "price_chg": 10,
        "bid_prices": [1175],
        "bid_volumes": [4],
        "ask_prices": [1180],
        "ask_volumes": [3],
    }


def _kgi_adapter() -> KgiRealtimeAcquisitionAdapter:
    return KgiRealtimeAcquisitionAdapter(
        lambda _symbol: KgiRealtimeProviderSnapshot(
            quote=_kgi_quote(),
            status="live",
        ),
        clock=lambda: NOW,
    )


def _persist_kgi(db: Session):
    descriptor = KGI_QUOTE_SNAPSHOT_DESCRIPTOR.model_copy(
        update={"allow_unknown_health": True}
    )
    return acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=NOW,
        acquisition=_kgi_adapter(),
        descriptors=(descriptor,),
    )


def _persist_mis(db: Session) -> None:
    raw_text = json.dumps(
        {
            "c": "2330",
            "d": "20260826",
            "t": "10:00:00",
            "z": "1181",
            "tv": "1",
            "v": "101",
            "o": "1170",
            "h": "1185",
            "l": "1165",
            "y": "1170",
            "ts": "0",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
    receipt = RawFetchReceiptV1(
        provider=TWSE_MIS_QUOTE_PROVIDER,
        source=TWSE_MIS_QUOTE_SOURCE_NAME,
        resource_id=TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id,
        fetched_at=NOW,
        method="GET",
        status_code=200,
        content_type="application/json",
        content_hash=content_hash,
        raw_text=raw_text,
        parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
    )
    observation = quote_observation_from_twse_mis(
        instrument=_instrument(),
        message=json.loads(raw_text),
        session=MarketSession.CONTINUOUS,
        received_at=NOW,
        fetched_at=NOW,
        content_hash=content_hash,
    )
    requirement = build_taiwan_public_quote_requirement(
        instrument=_instrument(),
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=NOW,
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=1,
            max_subscriptions=0,
            max_candidates=2,
            max_rows=1,
        ),
    )
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(
        requirement,
        QuoteAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(TWSE_MIS_QUOTE_PROVIDER,),
                resource_attempts=(
                    AcquisitionResourceAttempt(
                        provider=TWSE_MIS_QUOTE_PROVIDER,
                        resource_id=TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id,
                    ),
                ),
                external_calls=1,
            ),
            observations=(observation,),
            receipts=(receipt,),
        ),
    )


def test_kgi_quote_persists_raw_lineage_then_gateway_rereads_candidate(
    db: Session,
) -> None:
    result = _persist_kgi(db)

    assert result.persistence.committed is True
    assert result.persistence.receipts_written == 1
    assert result.acquisition.external_calls == 0
    assert result.resolved.health.status is ResolvedEvidenceStatus.SELECTED
    assert result.resolved.health.fallback_used is False
    assert result.resolved.quote is not None
    assert result.resolved.quote.lineage.provider == KGI_PROVIDER
    assert result.resolved.quote.lineage.source == KGI_SOURCE
    assert result.resolved.quote.lineage.cache_hit is True
    assert result.resolved.quote.lineage.observation_id is not None
    assert result.resolved.quote.lineage.raw_receipt_id == "raw_fetch_result:1"
    assert result.resolved.quote.lineage.content_hash is not None

    source = db.query(SourceRegistry).one()
    raw = db.query(RawFetchResult).one()
    row = db.query(TaiwanStockQuoteSnapshot).one()
    assert source.source_name == KGI_SOURCE
    assert source.source_type == "stream"
    assert source.auth_type == "broker_credentials"
    assert source.priority == KGI_QUOTE_SNAPSHOT_DESCRIPTOR.priority
    assert raw.source_id == source.id
    assert row.source_id == source.id
    assert row.raw_result_id == raw.id
    assert row.provider == KGI_PROVIDER


def test_quote_transport_failure_falls_back_after_gateway_reread(
    db: Session,
) -> None:
    calls: list[str] = []
    kgi = KgiRealtimeAcquisitionAdapter(
        lambda _symbol: KgiRealtimeProviderSnapshot(
            quote=None,
            status="disconnected",
            error="fixture unavailable",
        ),
        clock=lambda: NOW,
    )
    mis_payload = json.dumps(
        {
            "rtcode": "0000",
            "msgArray": [
                {
                    "c": "2330",
                    "d": "20260826",
                    "t": "10:00:00",
                    "z": "1181",
                    "tv": "1",
                    "v": "101",
                    "o": "1170",
                    "h": "1185",
                    "l": "1165",
                    "y": "1170",
                    "ts": "0",
                }
            ],
        }
    )

    class Response:
        status_code = 200
        text = mis_payload
        headers = {"content-type": "application/json"}
        url = "https://example.test/twse-mis"

    mis = TaiwanPublicQuoteAcquisitionExecutor(
        fetchers={
            TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.resource_id: (
                lambda _route, _instrument: Response()
            )
        },
        clock=lambda: NOW,
    )

    class CompositeQuoteAcquisition:
        def acquire_quote_observations(self, requirement, plan):
            assert len(plan.routes) == 1
            provider = plan.routes[0].provider_key
            calls.append(provider)
            if provider == KGI_PROVIDER:
                return kgi.acquire_quote_observations(requirement, plan)
            return mis.acquire_quote_observations(requirement, plan)

    result = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=NOW,
        descriptors=(
            KGI_QUOTE_SNAPSHOT_DESCRIPTOR.model_copy(
                update={"allow_unknown_health": True}
            ),
            TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
        ),
        acquisition=CompositeQuoteAcquisition(),
    )

    assert calls == [KGI_PROVIDER, TWSE_MIS_QUOTE_PROVIDER]
    assert result.acquisition.providers_attempted == (
        KGI_PROVIDER,
        TWSE_MIS_QUOTE_PROVIDER,
    )
    assert result.persistence.receipts_written == 1
    assert result.resolved.quote is not None
    assert result.resolved.quote.lineage.provider == TWSE_MIS_QUOTE_PROVIDER
    assert result.resolved.health.status is ResolvedEvidenceStatus.FALLBACK
    assert result.resolved.health.fallback_used is True
    assert any(
        item.startswith(f"ROUTE_REQUIREMENT_UNSATISFIED:{KGI_PROVIDER}:")
        for item in result.acquisition.limitations
    )


def test_kgi_and_mis_candidates_resolve_deterministically_from_descriptors(
    db: Session,
) -> None:
    _persist_kgi(db)
    _persist_mis(db)

    result = read_taiwan_public_last_trade_quote(
        db,
        stock_id="2330",
        requested_at=NOW,
    )

    assert len(result.resolved.candidates) == 2
    assert result.resolved.quote is not None
    assert result.resolved.quote.lineage.provider == KGI_PROVIDER
    assert result.resolved.quote.last_trade_price is not None
    assert result.resolved.quote.last_trade_price == 1180


def test_candidate_read_is_provider_fair_before_total_bound(db: Session) -> None:
    _persist_kgi(db)
    _persist_mis(db)
    base = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.provider == KGI_PROVIDER)
        .one()
    )
    for offset in range(1, 41):
        values = {
            column.name: getattr(base, column.name)
            for column in TaiwanStockQuoteSnapshot.__table__.columns
            if column.name != "id"
        }
        values["quote_time"] = NOW + timedelta(seconds=offset)
        values["received_at"] = NOW + timedelta(seconds=offset)
        values["fetched_at"] = NOW + timedelta(seconds=offset)
        db.add(TaiwanStockQuoteSnapshot(**values))
    db.commit()

    reads = TaiwanPublicQuoteRepository(db).load_quote_candidates(
        _instrument(),
        max_candidates=2,
    )

    assert {read.provider for read in reads} == {
        KGI_PROVIDER,
        TWSE_MIS_QUOTE_PROVIDER,
    }


def test_kgi_broker_quote_cannot_finalize_session_close(db: Session) -> None:
    requested_at = datetime(2026, 8, 26, 13, 31, tzinfo=TAIPEI)
    _persist_kgi(db)
    row = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.provider == KGI_PROVIDER)
        .one()
    )
    row.quote_time = requested_at.replace(minute=30)
    row.received_at = requested_at
    row.fetched_at = requested_at
    row.market_session = MarketSession.CLOSE_RESOLUTION.value
    raw = db.query(RawFetchResult).filter(RawFetchResult.id == row.raw_result_id).one()
    raw.fetched_at = requested_at
    db.commit()

    result = read_taiwan_session_close(
        db,
        stock_id="2330",
        requested_at=requested_at,
    )

    assert result.resolved.quote is None
    assert "SESSION_CLOSE_AUTHORITY_UNVERIFIED" in result.limitations


def test_minimum_exchange_authority_rejects_kgi_and_selects_mis(db: Session) -> None:
    _persist_kgi(db)
    _persist_mis(db)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_instrument(),
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=NOW,
    ).model_copy(
        update={
            "quality": QualityRequirement(
                required_fields=("last_trade_price",),
                minimum_authority=AuthorityClass.EXCHANGE,
                require_canonical_lineage=True,
            )
        }
    )

    result = MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db)
        ),
    )

    assert result.resolved.quote is not None
    assert result.resolved.quote.lineage.provider == TWSE_MIS_QUOTE_PROVIDER
    rejected = {
        candidate.provider: candidate.reason_code
        for candidate in result.resolved.candidates
        if not candidate.eligible
    }
    assert rejected[KGI_PROVIDER] == "QUALITY_AUTHORITY_BELOW_MINIMUM"


def test_transaction_rejects_forged_provider_source_resource_identity(
    db: Session,
) -> None:
    requirement = build_taiwan_public_quote_requirement(
        instrument=_instrument(),
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=NOW,
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=1,
            max_candidates=2,
            max_rows=1,
        ),
    )
    forged = RawFetchReceiptV1(
        provider=KGI_PROVIDER,
        source=TWSE_MIS_QUOTE_SOURCE_NAME,
        resource_id=KGI_QUOTE_SNAPSHOT_DESCRIPTOR.resource_id,
        fetched_at=NOW,
        method="STREAM",
        content_hash="a" * 64,
        parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
    )

    with pytest.raises(
        ValueError,
        match="unsupported Taiwan public quote provider/source/resource",
    ):
        TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(
            requirement,
            QuoteAcquisitionResult(
                summary=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.FAILED,
                    providers_attempted=(KGI_PROVIDER,),
                    resource_attempts=(
                        AcquisitionResourceAttempt(
                            provider=KGI_PROVIDER,
                            resource_id=KGI_QUOTE_SNAPSHOT_DESCRIPTOR.resource_id,
                        ),
                    ),
                    external_calls=1,
                ),
                receipts=(forged,),
            ),
        )

    assert db.query(SourceRegistry).count() == 0
    assert db.query(RawFetchResult).count() == 0
