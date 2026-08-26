"""Platform-owned cache read for official Taiwan completed-session breadth."""

from __future__ import annotations

from datetime import date, datetime
from sqlalchemy.orm import Session

from app.market.official_breadth_repository import TaiwanOfficialBreadthRepository
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import EvidenceFreshness, Market, MarketSession
from app.market_data.gateway import MarketBreadthCandidateBatch, MarketDataGateway
from app.market_data.integration_contracts import (
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    FreshnessRequirement,
    MarketDataResultV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import ResolutionCandidate


TW_BREADTH_DATASET_ID = "tw.market_breadth.daily"


class TaiwanOfficialBreadthCandidateReader:
    def __init__(self, repository: TaiwanOfficialBreadthRepository) -> None:
        self._repository = repository

    def read_market_breadth_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketBreadthCandidateBatch:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("Taiwan breadth requires a dataset target")
        if requirement.target.market is not Market.TW:
            raise ValueError("Taiwan breadth requires market=TW")
        if requirement.target.dataset_id != TW_BREADTH_DATASET_ID:
            raise ValueError("Taiwan breadth dataset_id mismatch")
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("Taiwan breadth requires a dataset capability")
        request = requirement.request
        if request.capability_id != "market.breadth":
            raise ValueError("Taiwan breadth requires capability=market.breadth")
        if request.from_date is None or request.to_date is None:
            raise ValueError("Taiwan breadth requires an exact trade date")
        if request.from_date != request.to_date:
            raise ValueError("Taiwan breadth read supports one completed session")
        trade_date = request.to_date
        stored = self._repository.load_market_breadth(
            venue=requirement.target.scope_key,
            trade_date=trade_date,
            max_rows=requirement.bounds.max_rows,
        )
        candidates = ()
        latest_date = None
        partial = False
        if stored.observation is not None:
            latest_date = stored.observation.trade_date
            partial = stored.observation.state.value == "partial"
            candidates = (
                ResolutionCandidate(
                    observation=stored.observation,
                    freshness=EvidenceFreshness.FRESH,
                    provider_priority=stored.provider_priority,
                    session=MarketSession.CLOSED,
                ),
            )
        spec = DATASET_REGISTRY.get(TW_BREADTH_DATASET_ID)
        dataset_health = evaluate_dataset_health(
            spec,
            expected_date=trade_date,
            latest_date=latest_date,
            checked_at=requirement.requested_at,
            eligible=True,
            partial=partial,
        )
        return MarketBreadthCandidateBatch(
            candidates=candidates,
            dataset_health=dataset_health,
            limitations=stored.limitations,
        )


def build_taiwan_official_breadth_requirement(
    *,
    venue: str,
    trade_date: date,
    requested_at: datetime,
) -> DataRequirementV2:
    normalized_venue = str(venue or "").strip().upper()
    if normalized_venue not in {"TWSE", "TPEX"}:
        raise ValueError("official Taiwan breadth requires venue=TWSE or TPEX")
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    return DataRequirementV2(
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_BREADTH_DATASET_ID,
            scope_key=normalized_venue,
        ),
        request=DatasetCapabilityRequest(
            capability_id="market.breadth",
            from_date=trade_date,
            to_date=trade_date,
            minimum_coverage_ratio=1.0,
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=RealtimePolicy.COMPLETED_SESSION,
        session=MarketSession.CLOSED,
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=2_678_400),
        bounds=RequestBounds(
            max_provider_attempts=0,
            max_external_calls=0,
            max_subscriptions=0,
            timeout_seconds=30,
            max_candidates=1,
            max_rows=5000,
        ),
    )


def read_taiwan_official_breadth(
    db: Session,
    *,
    venue: str,
    trade_date: date | None = None,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    effective_trade_date = trade_date or expected_daily_price_date(
        now=effective_requested_at
    )
    if effective_trade_date is None:
        raise ValueError("latest completed Taiwan trade date is unavailable")
    requirement = build_taiwan_official_breadth_requirement(
        venue=venue,
        trade_date=effective_trade_date,
        requested_at=effective_requested_at,
    )
    return MarketDataGateway().resolve_market_breadth(
        requirement,
        reader=TaiwanOfficialBreadthCandidateReader(
            TaiwanOfficialBreadthRepository(db)
        ),
    )


__all__ = [
    "TW_BREADTH_DATASET_ID",
    "TaiwanOfficialBreadthCandidateReader",
    "build_taiwan_official_breadth_requirement",
    "read_taiwan_official_breadth",
]
