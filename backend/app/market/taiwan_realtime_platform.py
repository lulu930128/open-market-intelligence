"""Platform-owned typed Taiwan order-book and auction Shared Core paths."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.realtime_snapshot_repository import (
    TaiwanAuctionRepository,
    TaiwanDepthRepository,
)
from app.market.realtime_snapshot_transaction import (
    TaiwanAuctionTransaction,
    TaiwanDepthTransaction,
)
from app.market.providers.twse_mis_realtime_acquisition import (
    TwseMisRealtimeAcquisitionAdapter,
)
from app.market.public_quote_platform import (
    acquire_taiwan_public_last_trade_quote,
    read_taiwan_quote_snapshot,
)
from app.market.tw_disposition import get_taiwan_disposition_status
from app.market.tw_instrument_trading_policy import (
    TaiwanAuctionApplicability,
    resolve_taiwan_auction_applicability,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session,
)
from app.market.tw_dataset_lifecycle import evaluate_taiwan_candidate_dataset_health
from app.market.tw_realtime_capabilities import (
    MIS_AUCTION_DESCRIPTOR,
    MIS_ORDER_BOOK_DESCRIPTOR,
    TW_AUCTION_CAPABILITY_ID,
    TW_AUCTION_DATASET_ID,
    TW_ORDER_BOOK_CAPABILITY_ID,
    TW_ORDER_BOOK_DATASET_ID,
    TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
)
from app.market.providers.tw_public_quote import TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR
from app.market_data.candidate_repository import CandidateRowRejection
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
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.gateway import (
    AuctionAcquisitionPort,
    AuctionCandidateBatch,
    DepthAcquisitionPort,
    DepthCandidateBatch,
    MarketDataGateway,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.market_data.resolution import ResolutionCandidate


TW_REALTIME_MAX_AGE_SECONDS = 15


@dataclass(frozen=True, slots=True)
class TaiwanRealtimeRefreshResult:
    quote: MarketDataResultV1
    depth: MarketDataResultV1
    auction: MarketDataResultV1 | None


def _market_session(now: datetime) -> MarketSession:
    return taiwan_market_session(now)


def _load_instrument(db: Session, stock_id: str) -> InstrumentKey:
    normalized = str(stock_id or "").strip().upper()
    if not normalized:
        raise ValueError("stock_id must not be empty")
    stock = db.query(StockMaster).filter(StockMaster.stock_id == normalized).first()
    if stock is None:
        raise ValueError(f"Taiwan stock_id is not registered: {normalized}")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("Taiwan realtime capability requires TWSE or TPEX")
    return InstrumentKey(
        market=Market.TW,
        symbol=normalized,
        instrument_type=(
            InstrumentType.ETF
            if str(stock.instrument_type or "").strip().casefold() == "etf"
            else InstrumentType.STOCK
        ),
        venue=venue,
    )


def _bounds(
    descriptors: tuple[ProviderCapabilityDescriptorV2, ...],
) -> RequestBounds:
    if not descriptors or len(descriptors) > 8:
        raise ValueError("Taiwan realtime descriptor catalog must contain 1-8 routes")
    calls = sum(item.max_external_calls_per_attempt for item in descriptors)
    subscriptions = sum(item.max_subscriptions_per_attempt for item in descriptors)
    if calls > 20 or subscriptions > 8:
        raise ValueError("Taiwan realtime descriptor work exceeds shared bounds")
    return RequestBounds(
        max_provider_attempts=len(descriptors),
        max_external_calls=calls,
        max_subscriptions=subscriptions,
        timeout_seconds=max(item.max_timeout_seconds for item in descriptors),
        max_candidates=max(2, len(descriptors)),
        max_rows=max(1, len(descriptors)),
    )


def build_taiwan_realtime_requirement(
    *,
    instrument: InstrumentKey,
    capability_id: str,
    policy: RealtimePolicy,
    requested_at: datetime,
    session: MarketSession | None = None,
    auction_type: AuctionType | None = None,
    bounds: RequestBounds | None = None,
) -> DataRequirementV2:
    if capability_id not in {TW_ORDER_BOOK_CAPABILITY_ID, TW_AUCTION_CAPABILITY_ID}:
        raise ValueError("unsupported Taiwan realtime capability")
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if policy not in {
        RealtimePolicy.CACHE_ONLY,
        RealtimePolicy.PREFER_LIVE,
        RealtimePolicy.REQUIRE_LIVE,
    }:
        raise ValueError("unsupported Taiwan realtime policy")
    acquiring = policy in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}
    effective_bounds = bounds or RequestBounds(
        max_provider_attempts=0,
        max_external_calls=0,
        max_subscriptions=0,
        max_candidates=2,
        max_rows=2,
    )
    if acquiring and bounds is None:
        raise ValueError("acquiring Taiwan realtime requirement needs explicit bounds")
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=SnapshotCapabilityRequest(
            capability_id=capability_id,
            required_fields=(
                ("capability",)
                if capability_id == TW_ORDER_BOOK_CAPABILITY_ID
                else ("provisional",)
            ),
            depth_levels=5 if capability_id == TW_ORDER_BOOK_CAPABILITY_ID else None,
            auction_type=(
                auction_type if capability_id == TW_AUCTION_CAPABILITY_ID else None
            ),
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=policy,
        session=session or _market_session(requested_at),
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=TW_REALTIME_MAX_AGE_SECONDS),
        quality=QualityRequirement(
            require_canonical_lineage=True,
            allow_partial=False,
        ),
        bounds=effective_bounds,
    )


def _freshness(requirement: DataRequirementV2, event_at: datetime) -> EvidenceFreshness:
    age = (requirement.requested_at - event_at).total_seconds()
    if -300 <= age <= TW_REALTIME_MAX_AGE_SECONDS:
        return EvidenceFreshness.LIVE
    return EvidenceFreshness.STALE


def _health(
    requirement: DataRequirementV2,
    *,
    provider: str,
    freshness: EvidenceFreshness,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=provider,
        market=Market.TW,
        capability=requirement.request.capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.UNKNOWN,
        entitlement=EntitlementStatus.UNKNOWN,
        operational=OperationalStatus.UNKNOWN,
        freshness=freshness,
        checked_at=requirement.requested_at,
        detail_code="PERSISTED_TW_REALTIME_CANDIDATE",
    )


class TaiwanDepthCandidateReader:
    def __init__(
        self,
        repository: TaiwanDepthRepository,
        *,
        provider_health: Iterable[ProviderResourceHealth] = (),
    ) -> None:
        self._repository = repository
        self._provider_health = tuple(provider_health)

    def read_depth_candidates(self, requirement: DataRequirementV2) -> DepthCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("depth reader requires instrument target")
        reads = self._repository.load_candidates(
            requirement.target.instrument,
            max_candidates=requirement.bounds.max_candidates,
        )
        candidates: list[ResolutionCandidate] = []
        health: list[ProviderResourceHealth] = list(self._provider_health)
        rejections: list[CandidateRowRejection] = []
        event_times: list[datetime] = []
        freshness_values: list[EvidenceFreshness] = []
        limitations = [item for read in reads for item in read.limitations]
        for read in reads:
            if read.observation is None:
                if (
                    read.provider
                    and read.source
                    and read.storage_row_id is not None
                    and read.raw_result_id is not None
                    and read.limitations
                ):
                    rejections.append(
                        CandidateRowRejection(
                            provider=read.provider,
                            source=read.source,
                            storage_row_id=read.storage_row_id,
                            raw_result_id=read.raw_result_id,
                            event_date=requirement.requested_at.astimezone(TAIWAN_TZ).date(),
                            reason_code=read.limitations[0],
                        )
                    )
                continue
            event_at = read.observation.lineage.event_at
            assert event_at is not None
            freshness = _freshness(requirement, event_at)
            event_times.append(event_at)
            freshness_values.append(freshness)
            candidates.append(
                ResolutionCandidate(
                    observation=read.observation,
                    freshness=freshness,
                    provider_priority=read.provider_priority,
                    session=requirement.session,
                )
            )
            health.append(
                _health(
                    requirement,
                    provider=read.observation.lineage.provider,
                    freshness=freshness,
                )
            )
        return DepthCandidateBatch(
            candidates=tuple(candidates),
            provider_health=tuple(health),
            dataset_health=evaluate_taiwan_candidate_dataset_health(
                requirement,
                dataset_id=TW_ORDER_BOOK_DATASET_ID,
                eligible=(
                    is_taiwan_trading_day(
                        requirement.requested_at.astimezone(TAIWAN_TZ).date()
                    )
                    and requirement.session
                    in {
                        MarketSession.PRE_OPEN,
                        MarketSession.OPENING_AUCTION,
                        MarketSession.CONTINUOUS,
                        MarketSession.CLOSING_AUCTION,
                    }
                ),
                event_times=event_times,
                freshness_values=freshness_values,
                partial=bool(rejections),
            ),
            rejections=tuple(rejections),
            limitations=tuple(dict.fromkeys(limitations)),
        )


class TaiwanAuctionCandidateReader:
    def __init__(
        self,
        repository: TaiwanAuctionRepository,
        *,
        provider_health: Iterable[ProviderResourceHealth] = (),
        applicability: TaiwanAuctionApplicability,
    ) -> None:
        self._repository = repository
        self._provider_health = tuple(provider_health)
        self._applicability = applicability

    def read_auction_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> AuctionCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("auction reader requires instrument target")
        reads = (
            self._repository.load_candidates(
                requirement.target.instrument,
                max_candidates=requirement.bounds.max_candidates,
                auction_type=self._applicability.auction_type,
            )
            if self._applicability.applicable is True
            and self._applicability.auction_type is not None
            else ()
        )
        candidates: list[ResolutionCandidate] = []
        health: list[ProviderResourceHealth] = list(self._provider_health)
        rejections: list[CandidateRowRejection] = []
        event_times: list[datetime] = []
        freshness_values: list[EvidenceFreshness] = []
        limitations = [
            *self._applicability.reason_codes,
            *(item for read in reads for item in read.limitations),
        ]
        for read in reads:
            if read.observation is None:
                if (
                    read.provider
                    and read.source
                    and read.storage_row_id is not None
                    and read.raw_result_id is not None
                    and read.limitations
                ):
                    rejections.append(
                        CandidateRowRejection(
                            provider=read.provider,
                            source=read.source,
                            storage_row_id=read.storage_row_id,
                            raw_result_id=read.raw_result_id,
                            event_date=requirement.requested_at.astimezone(
                                TAIWAN_TZ
                            ).date(),
                            reason_code=read.limitations[0],
                        )
                    )
                continue
            event_at = read.observation.lineage.event_at
            assert event_at is not None
            freshness = _freshness(requirement, event_at)
            event_times.append(event_at)
            freshness_values.append(freshness)
            candidates.append(
                ResolutionCandidate(
                    observation=read.observation,
                    freshness=freshness,
                    provider_priority=read.provider_priority,
                    session=requirement.session,
                )
            )
            health.append(
                _health(
                    requirement,
                    provider=read.observation.lineage.provider,
                    freshness=freshness,
                )
            )
        return AuctionCandidateBatch(
            candidates=tuple(candidates),
            provider_health=tuple(health),
            dataset_health=evaluate_taiwan_candidate_dataset_health(
                requirement,
                dataset_id=TW_AUCTION_DATASET_ID,
                eligible=(
                    False
                    if not is_taiwan_trading_day(
                        requirement.requested_at.astimezone(TAIWAN_TZ).date()
                    )
                    else self._applicability.applicable
                ),
                event_times=event_times,
                freshness_values=freshness_values,
                partial=bool(rejections),
            ),
            rejections=tuple(rejections),
            limitations=tuple(dict.fromkeys(limitations)),
        )


def read_taiwan_depth(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
    session: MarketSession | None = None,
) -> MarketDataResultV1:
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_realtime_requirement(
        instrument=_load_instrument(db, stock_id),
        capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=now,
        session=session,
    )
    return MarketDataGateway().resolve_depth(
        requirement,
        reader=TaiwanDepthCandidateReader(TaiwanDepthRepository(db)),
    )


def acquire_taiwan_depth(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy,
    descriptors: Iterable[ProviderCapabilityDescriptorV2],
    acquisition: DepthAcquisitionPort,
    provider_health: Iterable[ProviderResourceHealth] = (),
    requested_at: datetime | None = None,
    session: MarketSession | None = None,
) -> MarketDataResultV1:
    catalog = tuple(descriptors)
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_realtime_requirement(
        instrument=_load_instrument(db, stock_id),
        capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
        policy=policy,
        requested_at=now,
        session=session,
        bounds=_bounds(catalog),
    )
    return MarketDataGateway().resolve_depth(
        requirement,
        reader=TaiwanDepthCandidateReader(
            TaiwanDepthRepository(db),
            provider_health=provider_health,
        ),
        descriptors=catalog,
        acquisition_port=acquisition,
        transaction_port=TaiwanDepthTransaction(db),
    )


def _resolve_auction_applicability(
    db: Session,
    *,
    instrument: InstrumentKey,
    requested_at: datetime,
    session: MarketSession,
    disposition_status: Mapping[str, object] | None = None,
) -> TaiwanAuctionApplicability:
    disposition = disposition_status
    if session is MarketSession.CONTINUOUS and disposition is None:
        disposition = get_taiwan_disposition_status(
            instrument.symbol,
            market=instrument.venue,
            now=requested_at,
        )
    return resolve_taiwan_auction_applicability(
        session=session,
        disposition=disposition,
    )


def acquire_taiwan_auction(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy,
    descriptors: Iterable[ProviderCapabilityDescriptorV2],
    acquisition: AuctionAcquisitionPort,
    provider_health: Iterable[ProviderResourceHealth] = (),
    requested_at: datetime | None = None,
    session: MarketSession | None = None,
    disposition_status: Mapping[str, object] | None = None,
) -> MarketDataResultV1:
    catalog = tuple(descriptors)
    now = requested_at or datetime.now(TAIWAN_TZ)
    instrument = _load_instrument(db, stock_id)
    effective_session = session or _market_session(now)
    applicability = _resolve_auction_applicability(
        db,
        instrument=instrument,
        requested_at=now,
        session=effective_session,
        disposition_status=disposition_status,
    )
    requirement = build_taiwan_realtime_requirement(
        instrument=instrument,
        capability_id=TW_AUCTION_CAPABILITY_ID,
        policy=policy,
        requested_at=now,
        session=effective_session,
        auction_type=applicability.auction_type,
        bounds=_bounds(catalog),
    )
    reader = TaiwanAuctionCandidateReader(
        TaiwanAuctionRepository(db),
        provider_health=provider_health,
        applicability=applicability,
    )
    if applicability.applicable is not True:
        return MarketDataGateway().resolve_auction(
            requirement,
            reader=reader,
        )
    return MarketDataGateway().resolve_auction(
        requirement,
        reader=reader,
        descriptors=catalog,
        acquisition_port=acquisition,
        transaction_port=TaiwanAuctionTransaction(db),
    )


def read_taiwan_auction(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
    session: MarketSession | None = None,
    disposition_status: Mapping[str, object] | None = None,
) -> MarketDataResultV1:
    now = requested_at or datetime.now(TAIWAN_TZ)
    instrument = _load_instrument(db, stock_id)
    effective_session = session or _market_session(now)
    applicability = _resolve_auction_applicability(
        db,
        instrument=instrument,
        requested_at=now,
        session=effective_session,
        disposition_status=disposition_status,
    )
    requirement = build_taiwan_realtime_requirement(
        instrument=instrument,
        capability_id=TW_AUCTION_CAPABILITY_ID,
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=now,
        session=effective_session,
        auction_type=applicability.auction_type,
    )
    return MarketDataGateway().resolve_auction(
        requirement,
        reader=TaiwanAuctionCandidateReader(
            TaiwanAuctionRepository(db),
            applicability=applicability,
        ),
    )


def refresh_taiwan_realtime_snapshot(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    requested_at: datetime | None = None,
    acquisition: TwseMisRealtimeAcquisitionAdapter | None = None,
    requested_capabilities: Iterable[str] | None = None,
) -> TaiwanRealtimeRefreshResult:
    """Explicit bounded MIS refresh; callers must expose it through POST/job."""

    if policy not in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}:
        raise ValueError("Taiwan realtime refresh requires a live acquisition policy")
    now = requested_at or datetime.now(TAIWAN_TZ)
    requested = frozenset(
        requested_capabilities
        if requested_capabilities is not None
        else {
            TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
            TW_ORDER_BOOK_CAPABILITY_ID,
            TW_AUCTION_CAPABILITY_ID,
        }
    )
    supported = {
        TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
        TW_ORDER_BOOK_CAPABILITY_ID,
        TW_AUCTION_CAPABILITY_ID,
    }
    unsupported = requested - supported
    if unsupported:
        raise ValueError(
            "unsupported Taiwan realtime refresh capabilities: "
            + ", ".join(sorted(unsupported))
        )
    adapter = acquisition or TwseMisRealtimeAcquisitionAdapter(
        clock=lambda: datetime.now(TAIWAN_TZ)
    )
    quote = (
        acquire_taiwan_public_last_trade_quote(
            db,
            stock_id=stock_id,
            policy=policy,
            requested_at=now,
            acquisition=adapter,
            descriptors=(TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,),
        )
        if TW_QUOTE_SNAPSHOT_CAPABILITY_ID in requested
        else read_taiwan_quote_snapshot(db, stock_id=stock_id, requested_at=now)
    )
    depth = (
        acquire_taiwan_depth(
            db,
            stock_id=stock_id,
            policy=policy,
            descriptors=(MIS_ORDER_BOOK_DESCRIPTOR,),
            acquisition=adapter,
            requested_at=now,
            session=quote.requirement.session,
        )
        if TW_ORDER_BOOK_CAPABILITY_ID in requested
        else read_taiwan_depth(
            db,
            stock_id=stock_id,
            requested_at=now,
            session=quote.requirement.session,
        )
    )
    auction_session = (
        MarketSession.OPENING_AUCTION
        if quote.requirement.session is MarketSession.PRE_OPEN
        else quote.requirement.session
    )
    auction = None
    if TW_AUCTION_CAPABILITY_ID in requested:
        acquired_auction = acquire_taiwan_auction(
            db,
            stock_id=stock_id,
            policy=policy,
            descriptors=(MIS_AUCTION_DESCRIPTOR,),
            acquisition=adapter,
            requested_at=now,
            session=auction_session,
        )
        if (
            acquired_auction.dataset_health is not None
            and acquired_auction.dataset_health.status
            not in {
                DatasetHealthStatus.NOT_APPLICABLE,
                DatasetHealthStatus.UNKNOWN,
            }
        ):
            auction = acquired_auction
    return TaiwanRealtimeRefreshResult(
        quote=quote,
        depth=depth,
        auction=auction,
    )


__all__ = [
    "TW_REALTIME_MAX_AGE_SECONDS",
    "TaiwanAuctionCandidateReader",
    "TaiwanDepthCandidateReader",
    "TaiwanRealtimeRefreshResult",
    "acquire_taiwan_auction",
    "acquire_taiwan_depth",
    "build_taiwan_realtime_requirement",
    "read_taiwan_auction",
    "read_taiwan_depth",
    "refresh_taiwan_realtime_snapshot",
]
