"""Shared Data Core application platform for Taiwan current-session aggregates."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Literal

from pydantic import Field
from sqlalchemy.orm import Session

from app.market.official_index_platform import read_taiwan_official_index
from app.market.trading_calendar import (
    TAIWAN_TZ,
    previous_taiwan_trading_day,
    taiwan_market_session,
    taiwan_presentation_session,
)
from app.market.tw_current_market_acquisition import (
    TaiwanCurrentBreadthAcquisitionExecutor,
    TaiwanCurrentIndexAcquisitionExecutor,
)
from app.market.tw_current_market_capabilities import (
    FUGLE_CURRENT_INDEX_DESCRIPTOR,
    TW_CURRENT_BREADTH_CAPABILITY_ID,
    TW_CURRENT_BREADTH_DATASET_ID,
    TW_CURRENT_BREADTH_DESCRIPTORS,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TW_CURRENT_INDEX_DATASET_ID,
    TW_CURRENT_INDEX_DESCRIPTORS,
)
from app.market.tw_current_market_repository import TaiwanCurrentMarketRepository
from app.market.tw_current_market_transaction import TaiwanCurrentMarketTransaction
from app.market_data.contracts import (
    AuthorityClass,
    CanonicalModel,
    Market,
    MarketSession,
)
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    FreshnessRequirement,
    MarketDataResultV1,
    QualityRequirement,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2


class TaiwanIndexPreviousCloseSeed(CanonicalModel):
    """Market-owned lineage for deriving one current-session index change."""

    contract_version: str = "omi.market.tw_index_previous_close_seed.v1"
    index_id: str = Field(min_length=1, max_length=32)
    event_trade_date: date
    reference_trade_date: date
    previous_close: Decimal = Field(gt=0)
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    basis: Literal[
        "official_completed_session",
        "same_session_non_fugle",
    ]


def current_taiwan_market_session(requested_at: datetime) -> MarketSession:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    return taiwan_market_session(requested_at)


def build_taiwan_current_requirement(
    *,
    dataset_id: str,
    capability_id: str,
    scope_key: str,
    requested_at: datetime,
    policy: RealtimePolicy,
    acquiring: bool,
) -> DataRequirementV2:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if dataset_id == TW_CURRENT_INDEX_DATASET_ID:
        normalized_scope = str(scope_key or "").strip().upper()
        if normalized_scope not in {"TAIEX", "TPEX"}:
            raise ValueError("current Taiwan index requires TAIEX or TPEX")
    elif dataset_id == TW_CURRENT_BREADTH_DATASET_ID:
        normalized_scope = str(scope_key or "").strip().upper()
        if normalized_scope not in {"TWSE", "TPEX"}:
            raise ValueError("current Taiwan breadth requires TWSE or TPEX")
    else:
        raise ValueError("unsupported Taiwan current dataset")
    presentation = taiwan_presentation_session(requested_at)
    trade_date = presentation["trade_date"]
    required_fields = (
        (
            "close_value",
            "price_change",
            "trade_date",
            "lineage.event_at",
        )
        if dataset_id == TW_CURRENT_INDEX_DATASET_ID
        else ()
    )
    max_external_calls = (
        20 if dataset_id == TW_CURRENT_BREADTH_DATASET_ID else 2
    )
    return DataRequirementV2(
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=dataset_id,
            scope_key=normalized_scope,
        ),
        request=DatasetCapabilityRequest(
            capability_id=capability_id,
            from_date=trade_date,
            to_date=trade_date,
            minimum_coverage_ratio=0.0,
        ),
        purpose=DataPurpose.REPAIR if acquiring else DataPurpose.VIEWER,
        realtime_policy=policy,
        session=current_taiwan_market_session(requested_at),
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=60),
        quality=QualityRequirement(
            minimum_authority=AuthorityClass.VENDOR,
            allow_partial=True,
            require_canonical_lineage=True,
            required_fields=required_fields,
        ),
        bounds=RequestBounds(
            max_provider_attempts=2 if acquiring else 0,
            max_external_calls=max_external_calls if acquiring else 0,
            max_subscriptions=0,
            timeout_seconds=40 if acquiring else 30,
            max_candidates=3,
            max_rows=10,
        ),
    )


def read_taiwan_current_index(
    db: Session,
    *,
    index_id: str,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_INDEX_DATASET_ID,
        capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        scope_key=index_id,
        requested_at=now,
        policy=RealtimePolicy.CACHE_ONLY,
        acquiring=False,
    )
    return MarketDataGateway().resolve_market_index(
        requirement,
        reader=TaiwanCurrentMarketRepository(db),
        # Current-session resilience may prefer a fresher, higher-priority
        # vendor stream. Completed official index readers retain the Gateway
        # default (official-first) selection contract.
        official_first=False,
    )


def read_taiwan_index_previous_close_seed(
    db: Session,
    *,
    index_id: str,
    event_at: datetime,
    requested_at: datetime,
) -> TaiwanIndexPreviousCloseSeed | None:
    """Resolve an exact-date, non-circular previous close for a live index tick."""

    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("event_at must be timezone-aware")
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    normalized_index_id = str(index_id or "").strip().upper()
    event_trade_date = event_at.astimezone(TAIWAN_TZ).date()
    reference_trade_date = previous_taiwan_trading_day(
        event_trade_date,
        include_value=False,
    )
    official = read_taiwan_official_index(
        db,
        index_id=normalized_index_id,
        trade_date=reference_trade_date,
        requested_at=requested_at,
    ).resolved.market_index
    if (
        official is not None
        and official.trade_date == reference_trade_date
        and official.official
        and not official.provisional
        and official.close_value > 0
    ):
        return TaiwanIndexPreviousCloseSeed(
            index_id=normalized_index_id,
            event_trade_date=event_trade_date,
            reference_trade_date=reference_trade_date,
            previous_close=official.close_value,
            provider=official.lineage.provider,
            source=official.lineage.source,
            basis="official_completed_session",
        )

    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_INDEX_DATASET_ID,
        capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        scope_key=normalized_index_id,
        requested_at=requested_at,
        policy=RealtimePolicy.CACHE_ONLY,
        acquiring=False,
    )
    batch = TaiwanCurrentMarketRepository(db).read_market_index_candidates(
        requirement
    )
    fugle_provider = FUGLE_CURRENT_INDEX_DESCRIPTOR.provider_key
    for candidate in batch.candidates:
        observation = candidate.observation
        observed_at = observation.lineage.event_at
        previous_close = observation.close_value - observation.price_change
        if (
            observation.trade_date != event_trade_date
            or observation.lineage.provider == fugle_provider
            or observed_at is None
            or any(
                lineage_at is not None and lineage_at > requested_at
                for lineage_at in (
                    observed_at,
                    observation.lineage.received_at,
                    observation.lineage.fetched_at,
                )
            )
            or previous_close <= 0
        ):
            continue
        return TaiwanIndexPreviousCloseSeed(
            index_id=normalized_index_id,
            event_trade_date=event_trade_date,
            reference_trade_date=event_trade_date,
            previous_close=previous_close,
            provider=observation.lineage.provider,
            source=observation.lineage.source,
            basis="same_session_non_fugle",
        )
    return None


def refresh_taiwan_current_index(
    db: Session,
    *,
    index_id: str,
    requested_at: datetime | None = None,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    descriptors: Iterable[
        ProviderCapabilityDescriptorV2
    ] = TW_CURRENT_INDEX_DESCRIPTORS,
    acquisition: TaiwanCurrentIndexAcquisitionExecutor,
) -> MarketDataResultV1:
    if policy not in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}:
        raise ValueError("current index refresh requires prefer_live or require_live")
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_INDEX_DATASET_ID,
        capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        scope_key=index_id,
        requested_at=now,
        policy=policy,
        acquiring=True,
    )
    return MarketDataGateway().resolve_market_index(
        requirement,
        reader=TaiwanCurrentMarketRepository(db),
        descriptors=tuple(descriptors),
        acquisition_port=acquisition,
        transaction_port=TaiwanCurrentMarketTransaction(db),
        official_first=False,
    )


def read_taiwan_current_breadth(
    db: Session,
    *,
    venue: str,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_BREADTH_DATASET_ID,
        capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
        scope_key=venue,
        requested_at=now,
        policy=RealtimePolicy.CACHE_ONLY,
        acquiring=False,
    )
    return MarketDataGateway().resolve_market_breadth(
        requirement,
        reader=TaiwanCurrentMarketRepository(db),
    )


def refresh_taiwan_current_breadth(
    db: Session,
    *,
    venue: str,
    requested_at: datetime | None = None,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    descriptors: Iterable[
        ProviderCapabilityDescriptorV2
    ] = TW_CURRENT_BREADTH_DESCRIPTORS,
    acquisition: TaiwanCurrentBreadthAcquisitionExecutor,
) -> MarketDataResultV1:
    if policy not in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}:
        raise ValueError("current breadth refresh requires prefer_live or require_live")
    now = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_BREADTH_DATASET_ID,
        capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
        scope_key=venue,
        requested_at=now,
        policy=policy,
        acquiring=True,
    )
    return MarketDataGateway().resolve_market_breadth(
        requirement,
        reader=TaiwanCurrentMarketRepository(db),
        descriptors=tuple(descriptors),
        acquisition_port=acquisition,
        transaction_port=TaiwanCurrentMarketTransaction(db),
    )


def project_taiwan_current_index(result: MarketDataResultV1) -> dict[str, object]:
    limitations = list(
        dict.fromkeys((*result.limitations, *result.resolved.health.limitations))
    )
    observation = result.resolved.market_index
    if observation is None:
        return {
            "status": "missing",
            "index_id": result.requirement.target.scope_key,
            "provider": None,
            "source": "unavailable",
            "close": None,
            "change": None,
            "previous_close": None,
            "as_of": None,
            "trade_date": None,
            "provisional": True,
            "decision_usable": False,
            "resolved_health": result.resolved.health.model_dump(mode="json"),
            "limitations": limitations,
        }
    previous_close = observation.close_value - observation.price_change
    return {
        "status": observation.state.value,
        "index_id": observation.index_id,
        "provider": observation.lineage.provider,
        "source": observation.lineage.source,
        "close": float(observation.close_value),
        "change": float(observation.price_change),
        "previous_close": float(previous_close) if previous_close > 0 else None,
        "as_of": observation.lineage.event_at,
        "trade_date": observation.trade_date,
        "session": observation.session.value,
        "provisional": observation.provisional,
        "official": observation.official,
        "raw_result_id": observation.lineage.raw_receipt_id,
        "decision_usable": result.resolved.health.research_usable,
        "resolved_health": result.resolved.health.model_dump(mode="json"),
        "candidate_rejections": [
            item.model_dump(mode="json") for item in result.candidate_rejections
        ],
        "limitations": limitations,
    }


def project_taiwan_current_breadth(result: MarketDataResultV1) -> dict[str, object]:
    observation = result.resolved.breadth
    if observation is None:
        return {
            "status": "missing",
            "market": result.requirement.target.scope_key,
            "source": "unavailable",
            "decision_usable": False,
            "provisional": True,
            "resolved_health": result.resolved.health.model_dump(mode="json"),
            "limitations": list(result.limitations),
        }
    coverage_ratio = (
        observation.classified_count / observation.universe_count
        if observation.universe_count > 0
        else 0.0
    )
    return {
        "version": observation.contract_version,
        "status": observation.state.value,
        "market": observation.venue,
        "market_session": observation.session.value,
        "price_semantics": observation.price_semantics,
        "scope": observation.scope,
        "trade_date": observation.trade_date,
        "as_of": observation.lineage.event_at,
        "snapshot_as_of": observation.lineage.event_at,
        "advance_count": observation.advance_count,
        "decline_count": observation.decline_count,
        "unchanged_count": observation.unchanged_count,
        "classified_count": observation.classified_count,
        "received_unclassified_count": observation.unknown_count,
        "not_received_count": observation.missing_count,
        "unknown_count": observation.unknown_count,
        "missing_count": observation.missing_count,
        "universe_count": observation.universe_count,
        "total_count": observation.universe_count,
        "coverage_count": observation.classified_count,
        "coverage_ratio": coverage_ratio,
        "trade_value": (
            int(observation.trade_value)
            if observation.trade_value is not None
            else None
        ),
        "source": observation.lineage.source,
        "provider": observation.lineage.provider,
        "raw_result_id": observation.lineage.raw_receipt_id,
        "is_provisional": observation.provisional,
        "provisional": observation.provisional,
        "decision_usable": result.resolved.health.research_usable,
        "resolved_health": result.resolved.health.model_dump(mode="json"),
        "candidate_rejections": [
            item.model_dump(mode="json") for item in result.candidate_rejections
        ],
        "limitations": list(result.limitations),
        "warnings": list(result.limitations),
    }


__all__ = [
    "TaiwanIndexPreviousCloseSeed",
    "build_taiwan_current_requirement",
    "current_taiwan_market_session",
    "project_taiwan_current_breadth",
    "project_taiwan_current_index",
    "read_taiwan_current_breadth",
    "read_taiwan_current_index",
    "read_taiwan_index_previous_close_seed",
    "refresh_taiwan_current_breadth",
    "refresh_taiwan_current_index",
]
