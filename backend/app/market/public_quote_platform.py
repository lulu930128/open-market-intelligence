"""Platform-owned TW public last-trade quote read and bounded acquisition."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.market.providers.tw_public_quote import (
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
)
from app.market.public_quote_acquisition import (
    TaiwanPublicQuoteAcquisitionExecutor,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.trading_calendar import (
    TAIWAN_CLOSE_RESOLUTION_TIME,
    TAIWAN_SESSION_CLOSE_TIME,
    TAIWAN_TZ,
    taiwan_market_session,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.tw_public_quote_contract import (
    TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
    TW_PUBLIC_QUOTE_DATASET_ID,
    TWSE_MIS_QUOTE_PROVIDER,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
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
    QuoteAcquisitionPort,
    QuoteCandidateBatch,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    FreshnessBasis,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import ResolutionCandidate


PUBLIC_QUOTE_MAX_AGE_SECONDS = 15
_ACTIVE_SESSIONS = {
    MarketSession.PRE_OPEN,
    MarketSession.OPENING_AUCTION,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
}
_SESSION_CLOSE_ROUTE_DESCRIPTOR = TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.model_copy(
    update={
        "supported_sessions": (
            MarketSession.CLOSE_RESOLUTION,
            MarketSession.POST_CLOSE,
        ),
        "can_produce_live": False,
        "limitations": tuple(
            dict.fromkeys(
                (
                    *TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR.limitations,
                    "SESSION_CLOSE_CONFIRMATION_ROUTE",
                )
            )
        ),
    }
)


def _market_session(now: datetime) -> MarketSession:
    return taiwan_market_session(now)


def _load_instrument(db: Session, stock_id: str) -> InstrumentKey:
    return resolve_taiwan_instrument(db, stock_id)


def build_taiwan_public_quote_requirement(
    *,
    instrument: InstrumentKey,
    policy: RealtimePolicy,
    requested_at: datetime,
    bounds: RequestBounds | None = None,
    require_actual_trade: bool = True,
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
    effective_bounds = bounds or RequestBounds(
        max_provider_attempts=1 if acquiring else 0,
        max_external_calls=1 if acquiring else 0,
        max_subscriptions=0,
        timeout_seconds=10,
        max_candidates=2,
        max_rows=1,
    )
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=SnapshotCapabilityRequest(
            capability_id=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
            required_fields=("last_trade_price",) if require_actual_trade else (),
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=policy,
        session=_market_session(requested_at),
        requested_at=requested_at,
        freshness=FreshnessRequirement(
            max_age_seconds=PUBLIC_QUOTE_MAX_AGE_SECONDS
        ),
        quality=QualityRequirement(
            required_fields=("last_trade_price",) if require_actual_trade else (),
            allow_partial=not require_actual_trade,
            require_canonical_lineage=True,
        ),
        bounds=effective_bounds,
    )


def build_taiwan_session_close_requirement(
    *,
    instrument: InstrumentKey,
    policy: RealtimePolicy,
    requested_at: datetime,
    bounds: RequestBounds | None = None,
) -> DataRequirementV2:
    """Build a completed-session read on the existing public quote dataset."""

    requirement = build_taiwan_public_quote_requirement(
        instrument=instrument,
        policy=policy,
        requested_at=requested_at,
        bounds=bounds,
        require_actual_trade=True,
    )
    presentation = taiwan_presentation_session(requested_at)
    target_session = (
        MarketSession.POST_CLOSE
        if presentation["state"] == "previous_session"
        else requirement.session
    )
    return requirement.model_copy(
        update={
            "purpose": DataPurpose.RESEARCH,
            "session": target_session,
            "freshness": FreshnessRequirement(
                # Session-close validity is owned by the expected Taiwan trade
                # date checked by the candidate reader.  Wall-clock age is not
                # authoritative across weekends or exchange holidays.
                max_age_seconds=PUBLIC_QUOTE_MAX_AGE_SECONDS,
                basis=FreshnessBasis.COMPLETED_SESSION_DATE,
            ),
        }
    )


class TaiwanPublicQuoteCandidateReader:
    def __init__(
        self,
        repository: TaiwanPublicQuoteRepository,
        *,
        session_close: bool = False,
    ) -> None:
        self._repository = repository
        self._session_close = session_close

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
        stored_reads = self._repository.load_quote_candidates(
            requirement.target.instrument,
            max_candidates=requirement.bounds.max_candidates,
        )
        limitations = [
            limitation
            for stored in stored_reads
            for limitation in stored.limitations
        ]
        candidates: list[ResolutionCandidate] = []
        rejections: list[CandidateRowRejection] = []
        provider_health: list[ProviderResourceHealth] = []
        freshness_values: list[EvidenceFreshness] = []
        expected_trade_date = taiwan_presentation_session(
            requirement.requested_at
        )["trade_date"]
        partial = False
        latest_dates = [
            stored.observation.trade_date
            for stored in stored_reads
            if stored.observation is not None
            and stored.observation.trade_date is not None
        ]
        latest_date = max(latest_dates) if latest_dates else None
        confirmation_boundary = datetime.combine(
            expected_trade_date,
            TAIWAN_CLOSE_RESOLUTION_TIME,
            tzinfo=TAIWAN_TZ,
        )
        for stored in stored_reads:
            observation = stored.observation
            if observation is None:
                partial = partial or stored.storage_row_id is not None
                continue
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
                rejections.append(
                    CandidateRowRejection(
                        provider=observation.lineage.provider,
                        source=observation.lineage.source,
                        storage_row_id=stored.storage_row_id,
                        raw_result_id=stored.raw_result_id,
                        event_date=event_date,
                        reason_code="QUOTE_REQUIRED_FIELD_MISSING",
                        missing_fields=tuple(dict.fromkeys(missing_fields)),
                    )
                )
                limitations.append("PUBLIC_LAST_TRADE_REQUIRED_FIELD_MISSING")
                freshness = EvidenceFreshness.MISSING
            else:
                assert event_at is not None
                local_event_at = event_at.astimezone(TAIWAN_TZ)
                age_seconds = (
                    requirement.requested_at - event_at
                ).total_seconds()
                same_trade_date = observation.trade_date == expected_trade_date
                confirmed_at = (
                    stored.confirmed_at.astimezone(TAIWAN_TZ)
                    if stored.confirmed_at is not None
                    else None
                )
                actual_trade = bool(
                    observation.trade_state
                    is TradeObservationState.TRADE_OBSERVED
                    and observation.last_trade_price is not None
                )
                exchange_authority = (
                    observation.lineage.authority.value == "exchange"
                )
                closeout_session = stored.market_session in {
                    MarketSession.CLOSE_RESOLUTION,
                    MarketSession.POST_CLOSE,
                }
                legal_session_event = bool(
                    local_event_at.date() == expected_trade_date
                    and TAIWAN_SESSION_CLOSE_TIME
                    <= local_event_at.time()
                    <= TAIWAN_CLOSE_RESOLUTION_TIME
                    and event_at <= requirement.requested_at
                )
                session_close_confirmed = bool(
                    self._session_close
                    and same_trade_date
                    and actual_trade
                    and exchange_authority
                    and closeout_session
                    and legal_session_event
                    and confirmed_at is not None
                    and confirmed_at >= confirmation_boundary
                )
                if session_close_confirmed:
                    freshness = EvidenceFreshness.FRESH
                elif self._session_close:
                    freshness = EvidenceFreshness.STALE
                    limitations.append(
                        "SESSION_CLOSE_AUTHORITY_UNVERIFIED"
                        if not exchange_authority
                        else "SESSION_CLOSE_CONTROL_SESSION_INVALID"
                        if not closeout_session
                        else "SESSION_CLOSE_EVENT_TIME_INVALID"
                        if not legal_session_event
                        else (
                            "SESSION_CLOSE_RESOLVING"
                            if stored.market_session
                            is MarketSession.CLOSE_RESOLUTION
                            else "SESSION_CLOSE_CONFIRMATION_MISSING"
                        )
                    )
                elif (
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
                candidates.append(
                    ResolutionCandidate(
                        observation=observation,
                        freshness=freshness,
                        provider_priority=stored.provider_priority,
                        session=stored.market_session or requirement.session,
                    )
                )
            freshness_values.append(freshness)
            provider_health.append(
                ProviderResourceHealth(
                    provider=observation.lineage.provider,
                    market=Market.TW,
                    capability=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
                    enablement=EnablementStatus.ENABLED,
                    connection=ConnectionStatus.UNKNOWN,
                    entitlement=EntitlementStatus.UNKNOWN,
                    operational=OperationalStatus.UNKNOWN,
                    freshness=freshness,
                    checked_at=requirement.requested_at,
                    detail_code=(
                        "PERSISTED_SESSION_CLOSE_CANDIDATE"
                        if self._session_close
                        else "PERSISTED_PUBLIC_QUOTE_CANDIDATE"
                    ),
                )
            )
        spec = DATASET_REGISTRY.get(TW_PUBLIC_QUOTE_DATASET_ID)
        if not provider_health:
            provider_health.append(
                ProviderResourceHealth(
                    provider=TWSE_MIS_QUOTE_PROVIDER,
                    market=Market.TW,
                    capability=TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
                    enablement=EnablementStatus.ENABLED,
                    connection=ConnectionStatus.UNKNOWN,
                    entitlement=EntitlementStatus.UNKNOWN,
                    operational=OperationalStatus.UNKNOWN,
                    freshness=EvidenceFreshness.MISSING,
                    checked_at=requirement.requested_at,
                    detail_code="PERSISTED_PUBLIC_QUOTE_CANDIDATE_MISSING",
                )
            )
        return QuoteCandidateBatch(
            candidates=tuple(candidates),
            provider_health=tuple(provider_health),
            dataset_health=evaluate_dataset_health(
                spec,
                expected_date=expected_trade_date,
                latest_date=latest_date,
                checked_at=requirement.requested_at,
                eligible=True,
                partial=partial,
                stale=bool(freshness_values)
                and all(
                    freshness is EvidenceFreshness.STALE
                    for freshness in freshness_values
                ),
            ),
            rejections=tuple(rejections),
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


def read_taiwan_quote_snapshot(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    """Read canonical quote state without requiring an actual last trade."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=effective_requested_at,
        require_actual_trade=False,
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(TaiwanPublicQuoteRepository(db)),
    )


def read_taiwan_session_close(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    """Read completed-session close evidence from the existing quote store."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_session_close_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=effective_requested_at,
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db),
            session_close=True,
        ),
    )


def _acquisition_bounds(
    descriptors: tuple[ProviderCapabilityDescriptorV2, ...],
) -> RequestBounds:
    if not descriptors:
        raise ValueError("public quote acquisition requires provider descriptors")
    if len(descriptors) > 8:
        raise ValueError("public quote descriptor catalog exceeds shared bounds")
    if any(
        descriptor.capability_id != TW_PUBLIC_LAST_TRADE_CAPABILITY_ID
        for descriptor in descriptors
    ):
        raise ValueError("public quote descriptor capability mismatch")
    external_calls = sum(
        descriptor.max_external_calls_per_attempt for descriptor in descriptors
    )
    subscriptions = sum(
        descriptor.max_subscriptions_per_attempt for descriptor in descriptors
    )
    if external_calls > 20 or subscriptions > 8:
        raise ValueError("public quote descriptor work exceeds shared bounds")
    return RequestBounds(
        max_provider_attempts=len(descriptors),
        max_external_calls=external_calls,
        max_subscriptions=subscriptions,
        timeout_seconds=max(descriptor.max_timeout_seconds for descriptor in descriptors),
        max_candidates=max(2, len(descriptors)),
        max_rows=max(1, len(descriptors)),
    )


def acquire_taiwan_public_last_trade_quote(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy,
    requested_at: datetime | None = None,
    acquisition: QuoteAcquisitionPort | None = None,
    descriptors: Iterable[ProviderCapabilityDescriptorV2] | None = None,
) -> MarketDataResultV1:
    if policy not in {
        RealtimePolicy.PREFER_LIVE,
        RealtimePolicy.REQUIRE_LIVE,
    }:
        raise ValueError("refresh policy must be prefer_live or require_live")
    descriptor_catalog = (
        (TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,)
        if descriptors is None
        else tuple(descriptors)
    )
    if descriptors is not None and acquisition is None:
        raise ValueError("custom public quote descriptors require an acquisition port")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=policy,
        requested_at=effective_requested_at,
        bounds=_acquisition_bounds(descriptor_catalog),
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db)
        ),
        descriptors=descriptor_catalog,
        acquisition_port=acquisition or TaiwanPublicQuoteAcquisitionExecutor(),
        transaction_port=TaiwanPublicQuoteTransaction(db),
        route_resolution_gate=True,
    )


def acquire_taiwan_session_close(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
    acquisition: QuoteAcquisitionPort | None = None,
) -> MarketDataResultV1:
    """Confirm a session close through the bounded existing quote transaction."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    descriptor_catalog = (_SESSION_CLOSE_ROUTE_DESCRIPTOR,)
    requirement = build_taiwan_session_close_requirement(
        instrument=_load_instrument(db, stock_id),
        policy=RealtimePolicy.PREFER_LIVE,
        requested_at=effective_requested_at,
        bounds=_acquisition_bounds(descriptor_catalog),
    )
    return MarketDataGateway().resolve_quote(
        requirement,
        reader=TaiwanPublicQuoteCandidateReader(
            TaiwanPublicQuoteRepository(db),
            session_close=True,
        ),
        descriptors=descriptor_catalog,
        acquisition_port=acquisition or TaiwanPublicQuoteAcquisitionExecutor(),
        transaction_port=TaiwanPublicQuoteTransaction(db),
        route_resolution_gate=True,
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


def _share_value(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    if quantity.unit is QuantityUnit.SHARE:
        return int(quantity.value)
    if quantity.unit is QuantityUnit.BOARD_LOT:
        return int(quantity.value * quantity.scale)
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


def project_taiwan_session_close(
    result: MarketDataResultV1,
) -> dict[str, object]:
    """Project a completed Taiwan session close without official-EOD semantics."""

    if result.result_kind != "quote":
        raise ValueError("session close projection requires quote result")
    quote = result.resolved.quote
    health = result.resolved.health
    presentation = taiwan_presentation_session(result.requirement.requested_at)
    event_at = quote.lineage.event_at if quote is not None else None
    confirmed_at = (
        max(
            value
            for value in (
                quote.lineage.received_at,
                quote.lineage.fetched_at,
            )
            if value is not None
        )
        if quote is not None
        and any(
            value is not None
            for value in (
                quote.lineage.received_at,
                quote.lineage.fetched_at,
            )
        )
        else None
    )
    candidate_freshness = (
        result.resolved.candidates[0].freshness
        if result.resolved.candidates
        else EvidenceFreshness.MISSING
    )
    actual_trade = bool(
        quote is not None
        and quote.trade_state is TradeObservationState.TRADE_OBSERVED
        and quote.last_trade_price is not None
    )
    same_session = bool(
        quote is not None
        and quote.trade_date == presentation["trade_date"]
    )
    session_final = bool(
        actual_trade
        and same_session
        and candidate_freshness is EvidenceFreshness.FRESH
    )
    phase = taiwan_market_session_phase(result.requirement.requested_at)
    resolving = bool(
        not session_final
        and actual_trade
        and same_session
        and phase == "close_resolution"
    )
    status = (
        "session_final"
        if session_final
        else "resolving"
        if resolving
        else "unavailable"
    )
    price = quote.last_trade_price if quote is not None else None
    closing_match_volume_shares = (
        _share_value(quote.last_trade_quantity)
        if session_final and quote is not None
        else None
    )
    closing_match_volume_lots = (
        _board_lot_value(quote.last_trade_quantity)
        if session_final and quote is not None
        else None
    )
    session_cumulative_volume_shares = (
        _share_value(quote.cumulative_quantity)
        if session_final and quote is not None
        else None
    )
    session_cumulative_volume_lots = (
        _board_lot_value(quote.cumulative_quantity)
        if session_final and quote is not None
        else None
    )
    volume_available = bool(
        session_final
        and (
            closing_match_volume_shares is not None
            or session_cumulative_volume_shares is not None
        )
    )
    authority_class = (
        quote.lineage.authority.value if quote is not None else None
    )
    authority = {
        "exchange": "official_exchange_realtime",
        "broker": "broker_realtime",
    }.get(str(authority_class or ""), "fallback" if quote is not None else None)
    limitations = list(
        dict.fromkeys((*result.limitations, *health.limitations))
    )
    if session_final:
        limitations.append("OFFICIAL_DAILY_RECONCILIATION_PENDING")
    return {
        "contract_version": "omi.market.tw_session_close.v1",
        "kind": "quote_session_close",
        "status": status,
        "available": session_final,
        "price": _decimal_value(price) if session_final else None,
        "candidate_price": _decimal_value(price) if resolving else None,
        "closing_match_volume_shares": closing_match_volume_shares,
        "closing_match_volume_lots": closing_match_volume_lots,
        "closing_match_volume_semantics": "provider_reported_closing_match_volume",
        "closing_match_volume_source_field": "tv",
        "session_cumulative_volume_shares": session_cumulative_volume_shares,
        "session_cumulative_volume_lots": session_cumulative_volume_lots,
        "session_cumulative_volume_trade_date": (
            quote.trade_date
            if session_final and quote is not None
            and session_cumulative_volume_shares is not None
            else None
        ),
        "session_cumulative_volume_event_time": (
            event_at if session_cumulative_volume_shares is not None else None
        ),
        "session_cumulative_volume_semantics": "provider_reported_session_cumulative_volume",
        "session_cumulative_volume_source_field": "v",
        "volume_available": volume_available,
        "volume_status": (
            "session_final"
            if volume_available
            else "not_provided"
            if session_final
            else status
        ),
        "volume_provider": (
            quote.lineage.provider if volume_available and quote is not None else None
        ),
        "volume_source": (
            quote.lineage.source if volume_available and quote is not None else None
        ),
        "volume_event_time": event_at if volume_available else None,
        "volume_scope": "completed_regular_session",
        "volume_decision_usable": bool(
            session_final and session_cumulative_volume_shares is not None
        ),
        "trade_date": quote.trade_date if quote is not None else None,
        "event_time": event_at,
        "event_time_basis": "provider_event_time",
        "confirmed_at": confirmed_at,
        "confirmation_time_basis": "persisted_provider_receipt_time",
        "provider": quote.lineage.provider if quote is not None else None,
        "source": quote.lineage.source if quote is not None else None,
        "authority": authority,
        "authority_class": authority_class,
        "finalization": status,
        "official_daily": False,
        "session": (
            health.selected_session.value
            if health.selected_session is not None
            else phase
        ),
        "freshness": {
            "status": "current" if session_final else status,
            "is_current": session_final,
            "expected_trade_date": presentation["trade_date"],
            "latest_trade_date": quote.trade_date if quote is not None else None,
            "provider_event_time": event_at,
            "confirmed_at": confirmed_at,
        },
        "facts_usable": session_final,
        "research_usable": session_final,
        "decision_usable": session_final,
        "reconciliation_status": "pending" if session_final else "unavailable",
        "resolved_health": health.model_dump(mode="json"),
        "dataset_health": (
            result.dataset_health.model_dump(mode="json")
            if result.dataset_health is not None
            else None
        ),
        "lineage": (
            quote.lineage.model_dump(mode="json")
            if quote is not None
            else None
        ),
        "limitations": list(dict.fromkeys(limitations)),
    }


def reconcile_taiwan_session_close(
    projection: dict[str, object],
    official_close_result: MarketDataResultV1,
) -> dict[str, object]:
    """Reconcile the market-owned session close with canonical official daily."""

    reconciled = dict(projection)
    bar = (
        official_close_result.resolved.bars[-1]
        if official_close_result.resolved.bars
        else None
    )
    if not reconciled.get("available") or bar is None:
        return reconciled
    official_trade_date = bar.end_at.astimezone(TAIWAN_TZ).date()
    if official_trade_date != reconciled.get("trade_date"):
        return reconciled
    try:
        session_price = Decimal(str(reconciled.get("price")))
    except (InvalidOperation, TypeError, ValueError):
        session_price = None
    reconciliation_status = (
        "matched"
        if session_price is not None and session_price == bar.close_price
        else "mismatched"
    )
    reconciled.update(
        {
            "official_daily": True,
            "reconciliation_status": reconciliation_status,
            "official_close_price": float(bar.close_price),
            "official_close_trade_date": official_trade_date,
            "reconciliation": {
                "status": reconciliation_status,
                "session_close_finalization": reconciled.get("finalization"),
                "official_close_finalization": bar.finalization.value,
                "official_close_provider": bar.lineage.provider,
                "official_close_source": bar.lineage.source,
                "official_close_event_time": bar.lineage.event_at,
            },
        }
    )
    limitations = [
        value
        for value in list(reconciled.get("limitations") or [])
        if value != "OFFICIAL_DAILY_RECONCILIATION_PENDING"
    ]
    if reconciliation_status == "mismatched":
        limitations.append("SESSION_CLOSE_OFFICIAL_DAILY_MISMATCH")
        reconciled["research_usable"] = False
        reconciled["decision_usable"] = False
    reconciled["limitations"] = list(dict.fromkeys(limitations))
    return reconciled


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
    "acquire_taiwan_session_close",
    "acquire_taiwan_public_last_trade_quote",
    "build_taiwan_public_quote_requirement",
    "build_taiwan_session_close_requirement",
    "project_taiwan_public_last_trade_quote",
    "project_taiwan_session_close",
    "reconcile_taiwan_session_close",
    "read_taiwan_public_quote_projection",
    "read_taiwan_public_last_trade_quote",
    "read_taiwan_quote_snapshot",
    "read_taiwan_session_close",
]
