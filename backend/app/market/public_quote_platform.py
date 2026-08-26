"""Platform-owned TW public last-trade quote read and bounded acquisition."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.providers.tw_public_quote import (
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
)
from app.market.public_quote_acquisition import (
    TaiwanPublicQuoteAcquisitionExecutor,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.trading_calendar import (
    TAIWAN_TZ,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.tw_public_quote_contract import (
    TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
    TW_PUBLIC_QUOTE_DATASET_ID,
    TWSE_MIS_QUOTE_PROVIDER,
)
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    TradeObservationState,
)
from app.market_data.gateway import (
    MarketDataGateway,
    QuoteCandidateBatch,
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
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import ResolutionCandidate


PUBLIC_QUOTE_MAX_AGE_SECONDS = 15
_ACTIVE_SESSIONS = {
    MarketSession.PRE_OPEN,
    MarketSession.OPENING_AUCTION,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
}


def _market_session(now: datetime) -> MarketSession:
    return {
        "preopen": MarketSession.PRE_OPEN,
        "regular": MarketSession.CONTINUOUS,
        "closing_auction": MarketSession.CLOSING_AUCTION,
        "post_close": MarketSession.POST_CLOSE,
        "preopen_pending": MarketSession.CLOSED,
        "market_closed": MarketSession.CLOSED,
    }.get(taiwan_market_session_phase(now), MarketSession.UNKNOWN)


def _instrument_type(value: str | None) -> InstrumentType:
    return (
        InstrumentType.ETF
        if str(value or "").strip().casefold() == "etf"
        else InstrumentType.STOCK
    )


def _load_instrument(db: Session, stock_id: str) -> InstrumentKey:
    normalized_stock_id = str(stock_id or "").strip().upper()
    if not normalized_stock_id:
        raise ValueError("stock_id must not be empty")
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    if stock is None:
        raise ValueError(f"Taiwan stock_id is not registered: {normalized_stock_id}")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("public Taiwan quote requires a TWSE or TPEX instrument")
    return InstrumentKey(
        market=Market.TW,
        symbol=normalized_stock_id,
        instrument_type=_instrument_type(stock.instrument_type),
        venue=venue,
    )


def build_taiwan_public_quote_requirement(
    *,
    instrument: InstrumentKey,
    policy: RealtimePolicy,
    requested_at: datetime,
) -> DataRequirementV2:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if policy not in {
        RealtimePolicy.CACHE_ONLY,
        RealtimePolicy.PREFER_LIVE,
        RealtimePolicy.REQUIRE_LIVE,
    }:
        raise ValueError("public last-trade quote policy is unsupported")
    acquiring = policy in {
        RealtimePolicy.PREFER_LIVE,
        RealtimePolicy.REQUIRE_LIVE,
    }
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=SnapshotCapabilityRequest(
            capability_id=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
            required_fields=("last_trade_price",),
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=policy,
        session=_market_session(requested_at),
        requested_at=requested_at,
        freshness=FreshnessRequirement(
            max_age_seconds=PUBLIC_QUOTE_MAX_AGE_SECONDS
        ),
        quality=QualityRequirement(
            required_fields=("last_trade_price",),
            allow_partial=False,
        ),
        bounds=RequestBounds(
            max_provider_attempts=1 if acquiring else 0,
            max_external_calls=1 if acquiring else 0,
            max_subscriptions=0,
            timeout_seconds=10,
            max_candidates=1,
            max_rows=1,
        ),
    )


class TaiwanPublicQuoteCandidateReader:
    def __init__(self, repository: TaiwanPublicQuoteRepository) -> None:
        self._repository = repository

    def read_quote_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> QuoteCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("public quote requires instrument target")
        if not isinstance(requirement.request, SnapshotCapabilityRequest):
            raise ValueError("public quote requires snapshot capability")
        if requirement.request.capability_id != TW_PUBLIC_LAST_TRADE_CAPABILITY_ID:
            raise ValueError("public quote capability mismatch")
        stored = self._repository.load_latest_quote(
            requirement.target.instrument
        )
        observation = stored.observation
        limitations = list(stored.limitations)
        candidates: tuple = ()
        rejections: tuple[CandidateRowRejection, ...] = ()
        freshness = EvidenceFreshness.MISSING
        expected_trade_date = taiwan_presentation_session(
            requirement.requested_at
        )["trade_date"]
        partial = False
        latest_date = observation.trade_date if observation is not None else None
        if observation is not None:
            missing_fields = tuple(
                field
                for field in requirement.request.required_fields
                if getattr(observation, field, None) is None
            )
            if observation.trade_date != expected_trade_date:
                missing_fields = (*missing_fields, "expected_trade_date")
                limitations.append("PUBLIC_QUOTE_TRADE_DATE_MISMATCH")
            event_at = observation.lineage.event_at
            if event_at is None:
                missing_fields = (*missing_fields, "event_at")
            if missing_fields:
                partial = True
                if stored.storage_row_id is None or stored.raw_result_id is None:
                    raise ValueError("persisted quote rejection requires lineage IDs")
                event_date = (
                    observation.trade_date
                    or requirement.requested_at.astimezone(TAIWAN_TZ).date()
                )
                rejections = (
                    CandidateRowRejection(
                        provider=observation.lineage.provider,
                        source=observation.lineage.source,
                        storage_row_id=stored.storage_row_id,
                        raw_result_id=stored.raw_result_id,
                        event_date=event_date,
                        reason_code="QUOTE_REQUIRED_FIELD_MISSING",
                        missing_fields=tuple(dict.fromkeys(missing_fields)),
                    ),
                )
                limitations.append("PUBLIC_LAST_TRADE_REQUIRED_FIELD_MISSING")
            else:
                assert event_at is not None
                age_seconds = (
                    requirement.requested_at - event_at
                ).total_seconds()
                same_trade_date = observation.trade_date == expected_trade_date
                if (
                    requirement.session in _ACTIVE_SESSIONS
                    and same_trade_date
                    and -300 <= age_seconds <= PUBLIC_QUOTE_MAX_AGE_SECONDS
                ):
                    freshness = EvidenceFreshness.LIVE
                elif (
                    same_trade_date
                    and -300 <= age_seconds <= PUBLIC_QUOTE_MAX_AGE_SECONDS
                ):
                    freshness = EvidenceFreshness.FRESH
                else:
                    freshness = EvidenceFreshness.STALE
                candidates = (
                    ResolutionCandidate(
                        observation=observation,
                        freshness=freshness,
                        provider_priority=stored.provider_priority,
                        session=requirement.session,
                    ),
                )
        spec = DATASET_REGISTRY.get(TW_PUBLIC_QUOTE_DATASET_ID)
        provider_health = (
            ProviderResourceHealth(
                provider=TWSE_MIS_QUOTE_PROVIDER,
                market=Market.TW,
                capability=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
                enablement=EnablementStatus.ENABLED,
                connection=ConnectionStatus.UNKNOWN,
                entitlement=EntitlementStatus.UNKNOWN,
                operational=OperationalStatus.UNKNOWN,
                freshness=freshness,
                checked_at=requirement.requested_at,
                detail_code="PERSISTED_PUBLIC_QUOTE_CANDIDATE",
            ),
        )
        return QuoteCandidateBatch(
            candidates=candidates,
            provider_health=provider_health,
            dataset_health=evaluate_dataset_health(
                spec,
                expected_date=expected_trade_date,
                latest_date=latest_date,
                checked_at=requirement.requested_at,
                eligible=True,
                partial=partial,
                stale=freshness is EvidenceFreshness.STALE,
            ),
            rejections=rejections,
            limitations=tuple(dict.fromkeys(limitations)),
        )


def read_taiwan_public_last_trade_quote(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=effective_requested_at,
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db)
        ),
    )


def acquire_taiwan_public_last_trade_quote(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy,
    requested_at: datetime | None = None,
    acquisition: TaiwanPublicQuoteAcquisitionExecutor | None = None,
) -> MarketDataResultV1:
    if policy not in {
        RealtimePolicy.PREFER_LIVE,
        RealtimePolicy.REQUIRE_LIVE,
    }:
        raise ValueError("refresh policy must be prefer_live or require_live")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=policy,
        requested_at=effective_requested_at,
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db)
        ),
        descriptors=(TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,),
        acquisition_port=acquisition or TaiwanPublicQuoteAcquisitionExecutor(),
        transaction_port=TaiwanPublicQuoteTransaction(db),
    )


def _decimal_value(value: object) -> float | None:
    return float(value) if value is not None else None


def _board_lot_value(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    if quantity.original_unit is QuantityUnit.BOARD_LOT:
        return int(quantity.original_value) if quantity.original_value is not None else None
    if quantity.unit is QuantityUnit.BOARD_LOT:
        return int(quantity.value)
    return None


def project_taiwan_public_last_trade_quote(
    result: MarketDataResultV1,
) -> dict[str, object]:
    """Compatibility projection for AI/UI consumers without provider control.

    The projection intentionally exposes no order-book fields because the
    public capability owns last-trade evidence only. Missing depth therefore
    remains unavailable instead of being filled from a legacy quote service.
    """

    if result.result_kind != "quote":
        raise ValueError("public quote projection requires quote result")
    quote = result.resolved.quote
    health = result.resolved.health
    requirement = result.requirement
    presentation = taiwan_presentation_session(requirement.requested_at)
    dataset_status = result.dataset_health.status.value if result.dataset_health else "unknown"
    freshness = (
        result.resolved.candidates[0].freshness
        if result.resolved.candidates
        else EvidenceFreshness.MISSING
    )
    freshness_status = {
        EvidenceFreshness.LIVE: "live",
        EvidenceFreshness.FRESH: "current",
        EvidenceFreshness.STALE: "stale",
        EvidenceFreshness.MISSING: "missing",
        EvidenceFreshness.NOT_APPLICABLE: "not_applicable",
        EvidenceFreshness.UNKNOWN: "unknown",
    }[freshness]
    event_at = quote.lineage.event_at if quote is not None else None
    age_seconds = (
        max(int((requirement.requested_at - event_at).total_seconds()), 0)
        if event_at is not None
        else None
    )
    last_trade = quote.last_trade_price if quote is not None else None
    previous_close = quote.previous_close if quote is not None else None
    change = (
        last_trade - previous_close
        if last_trade is not None and previous_close is not None
        else None
    )
    change_pct = (
        (change / previous_close) * 100
        if change is not None and previous_close is not None and previous_close != 0
        else None
    )
    actual_trade = bool(
        quote is not None
        and quote.trade_state is TradeObservationState.TRADE_OBSERVED
        and last_trade is not None
    )
    same_session = bool(
        quote is not None
        and quote.trade_date is not None
        and quote.trade_date == presentation["trade_date"]
    )
    source_error = None
    if quote is None and result.limitations:
        source_error = "; ".join(result.limitations)
    acquisition_status = result.acquisition.status.value
    refresh_outcome = (
        "not_attempted"
        if not result.acquisition.attempted
        else "updated"
        if result.persistence.committed and result.persistence.observations_written > 0
        else "unchanged"
        if result.persistence.committed
        else "failed"
    )
    return {
        "contract_version": "omi.market.tw_public_quote_projection.v1",
        "provider": quote.lineage.provider if quote is not None else health.selected_provider,
        "source": quote.lineage.source if quote is not None else health.selected_source,
        "market": "TW",
        "stock_id": (
            quote.instrument.symbol
            if quote is not None
            else requirement.target.instrument.symbol
        ),
        "session_phase": taiwan_market_session_phase(requirement.requested_at),
        "trade_date": quote.trade_date if quote is not None else None,
        "quote_time": event_at,
        "provider_event_time": event_at,
        "event_time": event_at,
        "received_at": quote.lineage.received_at if quote is not None else None,
        "fetched_at": quote.lineage.fetched_at if quote is not None else None,
        "last_price": _decimal_value(last_trade),
        "last_trade_price": _decimal_value(last_trade),
        "price_available": last_trade is not None,
        "last_trade_available": actual_trade,
        "last_trade_time": event_at if actual_trade else None,
        "last_trade_is_current_session": actual_trade and same_session,
        "actual_trade_occurred": actual_trade,
        "actual_trade_price_cached": bool(quote and quote.lineage.cache_hit),
        "actual_trade_price_source": quote.lineage.source if actual_trade and quote else None,
        "actual_trade_price_as_of": event_at if actual_trade else None,
        "previous_close": _decimal_value(previous_close),
        "open_price": _decimal_value(quote.open_price) if quote is not None else None,
        "high_price": _decimal_value(quote.high_price) if quote is not None else None,
        "low_price": _decimal_value(quote.low_price) if quote is not None else None,
        "change": _decimal_value(change),
        "change_pct": _decimal_value(change_pct),
        "cumulative_volume_lots": _board_lot_value(
            quote.cumulative_quantity if quote is not None else None
        ),
        "total_volume_lots": _board_lot_value(
            quote.cumulative_quantity if quote is not None else None
        ),
        "last_trade_volume_lots": _board_lot_value(
            quote.last_trade_quantity if quote is not None else None
        ),
        "depth_available": False,
        "depth_status": "unavailable",
        "bid_levels": [],
        "ask_levels": [],
        "fallback_used": health.fallback_used,
        "refresh_outcome": refresh_outcome,
        "acquisition_status": acquisition_status,
        "provider_attempts": [
            attempt.model_dump(mode="json")
            for attempt in result.acquisition.resource_attempts
        ],
        "resolved_health": health.model_dump(mode="json"),
        "dataset_health": (
            result.dataset_health.model_dump(mode="json")
            if result.dataset_health is not None
            else None
        ),
        "freshness": {
            "status": freshness_status,
            "is_live": freshness is EvidenceFreshness.LIVE,
            "is_stale": freshness is EvidenceFreshness.STALE,
            "age_seconds": age_seconds,
            "expected_trade_date": presentation["trade_date"],
            "latest_trade_date": quote.trade_date if quote is not None else None,
            "dataset_status": dataset_status,
            "source_error": source_error,
        },
        "limitations": list(
            dict.fromkeys((*result.limitations, *health.limitations))
        ),
    }


def read_taiwan_public_quote_projection(
    db: Session,
    *,
    stock_id: str,
    refresh: bool = False,
    requested_at: datetime | None = None,
) -> dict[str, object]:
    """Provider-neutral compatibility reader used by existing consumers."""

    result = (
        acquire_taiwan_public_last_trade_quote(
            db,
            stock_id=stock_id,
            policy=RealtimePolicy.PREFER_LIVE,
            requested_at=requested_at,
        )
        if refresh
        else read_taiwan_public_last_trade_quote(
            db,
            stock_id=stock_id,
            requested_at=requested_at,
        )
    )
    return project_taiwan_public_last_trade_quote(result)


__all__ = [
    "PUBLIC_QUOTE_MAX_AGE_SECONDS",
    "TaiwanPublicQuoteCandidateReader",
    "acquire_taiwan_public_last_trade_quote",
    "build_taiwan_public_quote_requirement",
    "project_taiwan_public_last_trade_quote",
    "read_taiwan_public_quote_projection",
    "read_taiwan_public_last_trade_quote",
]
