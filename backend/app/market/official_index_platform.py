"""Application service for official completed-session Taiwan index data."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from app.market.official_index_acquisition import (
    TaiwanOfficialIndexAcquisitionExecutor,
)
from app.market.official_index_contract import TW_INDEX_DATASET_ID
from app.market.official_index_repository import TaiwanOfficialIndexRepository
from app.market.official_index_transaction import TaiwanOfficialIndexTransaction
from app.market.providers.tw_official_index import (
    TW_OFFICIAL_INDEX_DESCRIPTORS,
)
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import (
    CanonicalModel,
    EvidenceFreshness,
    Market,
    MarketSession,
    ProviderResourceHealth,
    ResolvedEvidenceStatus,
)
from app.market_data.gateway import (
    MarketDataGateway,
    MarketIndexAcquisitionResult,
    MarketIndexCandidateBatch,
)
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    FreshnessRequirement,
    MarketDataResultV1,
    PersistenceSummary,
    RefreshRequirementV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    ProviderCapabilityDescriptorV2,
    RefreshAcquisitionPlanV1,
    plan_refresh_acquisition_v1,
)
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import ResolutionCandidate


def _normalize_index_id(index_id: str) -> str:
    normalized = str(index_id or "").strip().upper()
    if normalized not in {"TAIEX", "TPEX"}:
        raise ValueError("official Taiwan index_id must be TAIEX or TPEX")
    return normalized


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(value for group in groups for value in group if value)
    )


def _merge_health(
    *groups: tuple[ProviderResourceHealth, ...],
) -> tuple[ProviderResourceHealth, ...]:
    values: dict[tuple[str, str, str], ProviderResourceHealth] = {}
    for group in groups:
        for item in group:
            values[(item.provider, item.market.value, item.capability)] = item
    return tuple(values.values())


class TaiwanOfficialIndexCandidateReader:
    def __init__(self, repository: TaiwanOfficialIndexRepository) -> None:
        self._repository = repository

    def read_market_index_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketIndexCandidateBatch:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("Taiwan index requires a dataset target")
        if requirement.target.market is not Market.TW:
            raise ValueError("Taiwan index requires market=TW")
        if requirement.target.dataset_id != TW_INDEX_DATASET_ID:
            raise ValueError("Taiwan index dataset_id mismatch")
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("Taiwan index requires a dataset capability")
        request = requirement.request
        if request.capability_id != "market.index.daily":
            raise ValueError("Taiwan index capability mismatch")
        if request.from_date is None or request.to_date is None:
            raise ValueError("Taiwan index requires an exact trade date")
        if request.from_date != request.to_date:
            raise ValueError("Taiwan index read supports one completed session")
        trade_date = request.to_date
        stored = self._repository.load_market_index(
            index_id=requirement.target.scope_key,
            trade_date=trade_date,
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
        spec = DATASET_REGISTRY.get(TW_INDEX_DATASET_ID)
        return MarketIndexCandidateBatch(
            candidates=candidates,
            dataset_health=evaluate_dataset_health(
                spec,
                expected_date=trade_date,
                latest_date=latest_date,
                checked_at=requirement.requested_at,
                eligible=True,
                partial=partial,
            ),
            limitations=stored.limitations,
        )


def build_taiwan_official_index_read_requirement(
    *,
    index_id: str,
    trade_date: date,
    requested_at: datetime,
) -> DataRequirementV2:
    normalized_index_id = _normalize_index_id(index_id)
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    return DataRequirementV2(
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_INDEX_DATASET_ID,
            scope_key=normalized_index_id,
        ),
        request=DatasetCapabilityRequest(
            capability_id="market.index.daily",
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
            max_rows=1,
        ),
    )


class TaiwanIndexRefreshResult(CanonicalModel):
    contract_version: str = "omi.market.tw_index_refresh_result.v1"
    requirement: RefreshRequirementV1
    plan: RefreshAcquisitionPlanV1
    acquisition: AcquisitionSummary
    persistence: PersistenceSummary
    result: MarketDataResultV1
    postcondition_satisfied: bool
    limitations: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _validate_postcondition(self) -> TaiwanIndexRefreshResult:
        if self.postcondition_satisfied and self.result.resolved.health.status not in {
            ResolvedEvidenceStatus.SELECTED,
            ResolvedEvidenceStatus.FALLBACK,
        }:
            raise ValueError("index refresh postcondition requires selected evidence")
        return self


class TaiwanOfficialIndexPlatform:
    def __init__(
        self,
        *,
        reader: TaiwanOfficialIndexCandidateReader,
        transaction: TaiwanOfficialIndexTransaction,
        acquisition: TaiwanOfficialIndexAcquisitionExecutor | None = None,
        descriptors: tuple[
            ProviderCapabilityDescriptorV2, ...
        ] = TW_OFFICIAL_INDEX_DESCRIPTORS,
    ) -> None:
        self._reader = reader
        self._transaction = transaction
        self._acquisition = acquisition or TaiwanOfficialIndexAcquisitionExecutor()
        self._descriptors = descriptors
        self._gateway = MarketDataGateway()

    def refresh_index(
        self,
        requirement: RefreshRequirementV1,
        *,
        provider_health: tuple[ProviderResourceHealth, ...] = (),
    ) -> TaiwanIndexRefreshResult:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("Taiwan index refresh requires dataset target")
        index_id = _normalize_index_id(requirement.target.scope_key)
        if requirement.from_date is None or requirement.to_date is None:
            raise ValueError("Taiwan index refresh requires exact bounded date")
        if requirement.from_date != requirement.to_date:
            raise ValueError("Taiwan index refresh supports one completed session")
        trade_date = requirement.to_date
        read_requirement = build_taiwan_official_index_read_requirement(
            index_id=index_id,
            trade_date=trade_date,
            requested_at=requirement.requested_at,
        )
        plan = plan_refresh_acquisition_v1(
            requirement,
            self._descriptors,
            provider_health,
        )
        if plan.unfillable:
            acquisition = MarketIndexAcquisitionResult(
                summary=AcquisitionSummary(
                    attempted=False,
                    status=AcquisitionStatus.NOT_ATTEMPTED,
                    limitations=_unique(
                        plan.limitations,
                        tuple(item.reason_code for item in plan.skipped_resources),
                    ),
                )
            )
            persistence = PersistenceSummary(
                attempted=False,
                limitations=("REFRESH_PLAN_UNFILLABLE",),
            )
        else:
            acquisition = self._acquisition.acquire_routes(
                index_id=index_id,
                trade_date=trade_date,
                routes=plan.routes,
            )
            if acquisition.receipts or acquisition.observations:
                persistence = self._transaction.persist_index_acquisition(
                    requirement,
                    acquisition,
                )
            else:
                persistence = PersistenceSummary(
                    attempted=False,
                    limitations=("NO_PERSISTABLE_ACQUISITION_EVIDENCE",),
                )
        persisted = self._gateway.resolve_market_index(
            read_requirement,
            reader=self._reader,
        )
        result = MarketDataResultV1(
            requirement=persisted.requirement,
            result_kind="market_index",
            resolved=persisted.resolved,
            provider_health=_merge_health(
                persisted.provider_health,
                acquisition.provider_health,
            ),
            dataset_health=persisted.dataset_health,
            acquisition=acquisition.summary,
            persistence=persistence,
            candidate_rejections=persisted.candidate_rejections,
            limitations=_unique(
                persisted.limitations,
                acquisition.summary.limitations,
                persistence.limitations,
            ),
        )
        selected = result.resolved.market_index
        postcondition_satisfied = (
            selected is not None
            and selected.index_id == index_id
            and selected.trade_date == trade_date
            and result.resolved.health.status
            in {ResolvedEvidenceStatus.SELECTED, ResolvedEvidenceStatus.FALLBACK}
        )
        limitations = list(result.limitations)
        if not postcondition_satisfied:
            limitations.append("REFRESH_POSTCONDITION_UNSATISFIED")
        return TaiwanIndexRefreshResult(
            requirement=requirement,
            plan=plan,
            acquisition=acquisition.summary,
            persistence=persistence,
            result=result,
            postcondition_satisfied=postcondition_satisfied,
            limitations=tuple(dict.fromkeys(limitations)),
        )


def read_taiwan_official_index(
    db: Session,
    *,
    index_id: str,
    trade_date: date | None = None,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    latest_completed = expected_daily_price_date(now=effective_requested_at)
    effective_trade_date = (
        min(trade_date, latest_completed)
        if trade_date is not None and latest_completed is not None
        else trade_date or latest_completed
    )
    if effective_trade_date is None:
        raise ValueError("latest completed Taiwan trade date is unavailable")
    requirement = build_taiwan_official_index_read_requirement(
        index_id=index_id,
        trade_date=effective_trade_date,
        requested_at=effective_requested_at,
    )
    result = MarketDataGateway().resolve_market_index(
        requirement,
        reader=TaiwanOfficialIndexCandidateReader(
            TaiwanOfficialIndexRepository(
                db,
                available_at=effective_requested_at,
            )
        ),
    )
    if trade_date is None or trade_date <= effective_trade_date:
        return result
    return result.model_copy(
        update={
            "limitations": tuple(
                dict.fromkeys(
                    (
                        *result.limitations,
                        "REQUESTED_INDEX_DATE_EXCEEDS_LATEST_RELEASED_DATE",
                    )
                )
            )
        }
    )


def read_taiwan_official_index_series(
    db: Session,
    *,
    index_id: str,
    to_date: date | None = None,
    limit: int = 250,
    requested_at: datetime | None = None,
) -> tuple[MarketDataResultV1, ...]:
    """Read a bounded canonical completed-session index series."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    latest_completed = expected_daily_price_date(now=effective_requested_at)
    if latest_completed is None:
        return ()
    effective_to_date = min(to_date, latest_completed) if to_date else latest_completed
    repository = TaiwanOfficialIndexRepository(
        db,
        available_at=effective_requested_at,
    )
    trade_dates = repository.preload_market_index_series(
        index_id=index_id,
        to_date=effective_to_date,
        limit=limit,
    )
    gateway = MarketDataGateway()
    reader = TaiwanOfficialIndexCandidateReader(repository)
    return tuple(
        gateway.resolve_market_index(
            build_taiwan_official_index_read_requirement(
                index_id=index_id,
                trade_date=trade_date,
                requested_at=effective_requested_at,
            ),
            reader=reader,
        )
        for trade_date in trade_dates
    )


def refresh_taiwan_official_index(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
    requested_at: datetime | None = None,
    acquisition: TaiwanOfficialIndexAcquisitionExecutor | None = None,
) -> TaiwanIndexRefreshResult:
    normalized_index_id = _normalize_index_id(index_id)
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    expected_date = expected_daily_price_date(now=effective_requested_at)
    if expected_date is None or trade_date != expected_date:
        raise ValueError(
            "official index refresh trade_date must equal the latest expected "
            f"completed Taiwan session ({expected_date})"
        )
    requirement = RefreshRequirementV1(
        dataset_id=TW_INDEX_DATASET_ID,
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_INDEX_DATASET_ID,
            scope_key=normalized_index_id,
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=effective_requested_at,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition=(
            f"Official {normalized_index_id} row reaches {trade_date.isoformat()} "
            "with raw receipt lineage."
        ),
    )
    return TaiwanOfficialIndexPlatform(
        reader=TaiwanOfficialIndexCandidateReader(
            TaiwanOfficialIndexRepository(db)
        ),
        transaction=TaiwanOfficialIndexTransaction(db),
        acquisition=acquisition,
    ).refresh_index(requirement)


__all__ = [
    "TaiwanIndexRefreshResult",
    "TaiwanOfficialIndexCandidateReader",
    "TaiwanOfficialIndexPlatform",
    "build_taiwan_official_index_read_requirement",
    "read_taiwan_official_index",
    "read_taiwan_official_index_series",
    "refresh_taiwan_official_index",
]
