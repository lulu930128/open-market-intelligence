"""Taiwan official daily OHLCV application service and stable projection seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.providers.tw_official_daily import (
    TW_DAILY_DATASET_ID,
    TW_FULL_MARKET_DAILY_DATASET_ID,
    TW_OFFICIAL_DAILY_DESCRIPTORS,
)
from app.market.tw_universe import list_taiwan_stock_universe
from app.market.taiwan_rules import expected_daily_price_date
from app.market_data.contracts import (
    AuthorityClass,
    BarObservation,
    CanonicalModel,
    DatasetHealth,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    ProviderResourceHealth,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
)
from app.market_data.gateway import BarAcquisitionResult, MarketDataGateway
from app.market_data.integration_contracts import (
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    BarSeriesResolutionMode,
    DataRequirementV2,
    DatasetTarget,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    PersistenceSummary,
    QualityRequirement,
    RefreshRequirementV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import (
    ProviderCapabilityDescriptorV2,
    RefreshAcquisitionPlanV1,
    plan_refresh_acquisition_v1,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class TaiwanDailyPriceEvidence:
    trade_date: date
    stock_id: str
    stock_name: str | None
    trade_volume: int | None
    trade_value: Decimal | None
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    price_change: Decimal | None
    transaction_count: int | None
    provider: str
    source: str
    event_at: datetime | None
    raw_result_id: str | None


@dataclass(frozen=True, slots=True)
class TaiwanLatestDailyEvidence:
    daily: TaiwanDailyPriceEvidence | None
    resolved_health: ResolvedEvidenceHealth
    dataset_health: DatasetHealth | None
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaiwanCanonicalDailyRow:
    """Compatibility projection backed by a selected canonical daily bar."""

    id: int
    source_id: int
    raw_result_id: int
    trade_date: date
    stock_id: str
    stock_name: str | None
    trade_volume: int | None
    trade_value: int | None
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    price_change: float | None
    transaction_count: int | None
    created_at: datetime
    updated_at: datetime
    selected_provider: str
    selected_source: str
    volume_unit: str = "shares"
    trade_value_unit: str = "TWD"


class TaiwanDailyRefreshResult(CanonicalModel):
    contract_version: str = "omi.market.tw_daily_refresh_result.v1"
    requirement: RefreshRequirementV1
    plan: RefreshAcquisitionPlanV1
    acquisition: AcquisitionSummary
    persistence: PersistenceSummary
    result: MarketDataResultV1
    postcondition_satisfied: bool
    limitations: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _validate_postcondition(self) -> TaiwanDailyRefreshResult:
        selected = self.result.resolved.health.status in {
            ResolvedEvidenceStatus.SELECTED,
            ResolvedEvidenceStatus.FALLBACK,
        }
        if self.postcondition_satisfied and not selected:
            raise ValueError("refresh postcondition requires selected persisted evidence")
        return self


def build_taiwan_daily_read_requirement(
    refresh: RefreshRequirementV1,
) -> DataRequirementV2:
    if not isinstance(refresh.target, InstrumentTarget):
        raise ValueError("per-instrument Taiwan daily refresh requires instrument target")
    if refresh.target.instrument.market is not Market.TW:
        raise ValueError("Taiwan daily refresh requires market=TW")
    if refresh.from_date is None or refresh.to_date is None:
        raise ValueError("Taiwan daily refresh requires bounded from_date and to_date")
    start_at = datetime.combine(refresh.from_date, time(9), tzinfo=TAIWAN_TZ)
    end_at = datetime.combine(refresh.to_date, time(13, 30), tzinfo=TAIWAN_TZ)
    range_days = (refresh.to_date - refresh.from_date).days + 1
    return DataRequirementV2(
        target=refresh.target,
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=start_at,
            end_at=end_at,
            max_bars=min(max(range_days, 1), 5000),
            completed_only=True,
            price_basis="raw",
            series_resolution=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
        ),
        purpose=DataPurpose.REPAIR,
        realtime_policy=RealtimePolicy.COMPLETED_SESSION,
        session=MarketSession.CLOSED,
        requested_at=refresh.requested_at,
        freshness=FreshnessRequirement(max_age_seconds=2_678_400),
        quality=QualityRequirement(
            required_fields=(
                "open_price",
                "high_price",
                "low_price",
                "close_price",
            ),
            minimum_authority=AuthorityClass.EXCHANGE,
            allow_partial=False,
        ),
        bounds=RequestBounds(
            max_provider_attempts=0,
            max_external_calls=0,
            max_subscriptions=0,
            timeout_seconds=refresh.timeout_seconds,
            max_candidates=8,
            max_rows=min(max(range_days, 1), 5000),
        ),
    )


def build_taiwan_daily_cache_requirement(
    *,
    instrument: InstrumentKey,
    from_date: date,
    to_date: date,
    requested_at: datetime,
    max_rows: int,
    minimum_authority: AuthorityClass = AuthorityClass.EXCHANGE,
) -> DataRequirementV2:
    """Build a zero-I/O completed-session read for viewer/research consumers."""

    if instrument.market is not Market.TW:
        raise ValueError("Taiwan daily read requires market=TW")
    if instrument.venue not in {"TWSE", "TPEX"}:
        raise ValueError("Taiwan daily read requires TWSE/TPEX venue")
    if from_date > to_date:
        raise ValueError("Taiwan daily read from_date cannot be after to_date")
    if (to_date - from_date).days > 36_600:
        raise ValueError("Taiwan daily read range cannot exceed 36,600 days")
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if max_rows < 1 or max_rows > 5000:
        raise ValueError("Taiwan daily read max_rows must be between 1 and 5000")
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=datetime.combine(from_date, time(9), tzinfo=TAIWAN_TZ),
            end_at=datetime.combine(to_date, time(13, 30), tzinfo=TAIWAN_TZ),
            max_bars=max_rows,
            completed_only=True,
            price_basis="raw",
            series_resolution=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=RealtimePolicy.COMPLETED_SESSION,
        session=MarketSession.CLOSED,
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=2_678_400),
        quality=QualityRequirement(
            required_fields=(
                "open_price",
                "high_price",
                "low_price",
                "close_price",
            ),
            minimum_authority=minimum_authority,
            allow_partial=False,
        ),
        bounds=RequestBounds(
            max_provider_attempts=0,
            max_external_calls=0,
            max_subscriptions=0,
            timeout_seconds=30,
            max_candidates=8,
            max_rows=max_rows,
        ),
    )


def read_taiwan_official_daily(
    db: Session,
    *,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    """Resolve persisted official daily candidates without provider acquisition."""

    normalized_stock_id = str(stock_id or "").strip().upper()
    if not normalized_stock_id:
        raise ValueError("stock_id is required")
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    if stock is None or not stock.is_active:
        raise ValueError(f"active Taiwan stock_id='{normalized_stock_id}' was not found")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("official Taiwan daily read requires TWSE/TPEX venue")
    if limit < 1 or limit > 5000:
        raise ValueError("limit must be between 1 and 5000")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    latest_potentially_released_date = expected_daily_price_date(
        now=effective_requested_at.astimezone(TAIWAN_TZ)
    )
    effective_to_date = (
        min(to_date, latest_potentially_released_date)
        if to_date
        else latest_potentially_released_date
    )
    boundary_limitations: tuple[str, ...] = ()
    if to_date is not None and to_date > latest_potentially_released_date:
        boundary_limitations = (
            "REQUESTED_TO_DATE_EXCEEDS_LATEST_RELEASED_DAILY_DATE",
        )
    instrument_type = (
        InstrumentType.ETF
        if "etf" in str(stock.instrument_type or "").strip().lower()
        else InstrumentType.STOCK
    )
    instrument = InstrumentKey(
        market=Market.TW,
        symbol=normalized_stock_id,
        instrument_type=instrument_type,
        venue=venue,
    )
    repository = TaiwanOfficialDailyBarRepository(
        db,
        available_at=effective_requested_at,
    )
    effective_from_date = from_date
    if effective_from_date is None:
        effective_from_date = repository.latest_candidate_start_date(
            instrument=instrument,
            end_date=effective_to_date,
            max_rows=limit,
        ) or effective_to_date
    requirement = build_taiwan_daily_cache_requirement(
        instrument=instrument,
        from_date=effective_from_date,
        to_date=effective_to_date,
        requested_at=effective_requested_at,
        max_rows=limit,
    )
    result = MarketDataGateway().resolve_bars(
        requirement,
        reader=TaiwanCompletedDailyCandidateReader(
            repository
        ),
    )
    composition_limitations: list[str] = []
    if "BAR_SERIES_COMPOSED_FROM_MULTIPLE_CANDIDATES" in result.limitations:
        composition_limitations.append("OFFICIAL_DAILY_SERIES_RECONCILED")
    if "BAR_SERIES_SAME_TIMESTAMP_CONFLICT_RESOLVED" in result.limitations:
        composition_limitations.append("OFFICIAL_DAILY_SAME_DATE_CONFLICT_RESOLVED")
    if composition_limitations:
        result = result.model_copy(
            update={
                "limitations": tuple(
                    dict.fromkeys((*result.limitations, *composition_limitations))
                )
            }
        )
    if not boundary_limitations:
        return result
    return result.model_copy(
        update={
            "limitations": tuple(
                dict.fromkeys((*result.limitations, *boundary_limitations))
            )
        }
    )


def read_taiwan_latest_daily_evidence(
    db: Session,
    stock_id: str,
    *,
    to_date: date | None = None,
    requested_at: datetime | None = None,
) -> TaiwanLatestDailyEvidence:
    """Project the latest canonical official bar for AI/valuation consumers."""

    result = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        to_date=to_date,
        limit=1,
        requested_at=requested_at,
    )
    bar = result.resolved.bars[-1] if result.resolved.bars else None
    daily = None
    limitations = list(result.limitations)
    if bar is not None:
        trade_volume = None
        if bar.volume is not None:
            if bar.volume.unit.value == "share":
                trade_volume = int(bar.volume.value)
            else:
                limitations.append("DAILY_VOLUME_NOT_NORMALIZED_TO_SHARES")
        daily = TaiwanDailyPriceEvidence(
            trade_date=bar.end_at.astimezone(TAIWAN_TZ).date(),
            stock_id=bar.instrument.symbol,
            stock_name=bar.instrument_name,
            trade_volume=trade_volume,
            trade_value=bar.turnover_value,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price,
            price_change=bar.price_change,
            transaction_count=bar.trade_count,
            provider=bar.lineage.provider,
            source=bar.lineage.source,
            event_at=bar.lineage.event_at,
            raw_result_id=bar.lineage.raw_receipt_id,
        )
    return TaiwanLatestDailyEvidence(
        daily=daily,
        resolved_health=result.resolved.health,
        dataset_health=result.dataset_health,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def project_taiwan_daily_rows(
    db: Session,
    result: MarketDataResultV1,
) -> list[TaiwanCanonicalDailyRow]:
    """Project selected bars for legacy readers without exposing raw candidates."""

    return project_taiwan_daily_bars(db, tuple(result.resolved.bars))


def project_taiwan_daily_bars(
    db: Session,
    bars: tuple[BarObservation, ...],
) -> list[TaiwanCanonicalDailyRow]:
    """Project an already-selected canonical bar collection."""

    metadata = TaiwanOfficialDailyBarRepository(db).lineage_metadata(
        tuple(
            bar.lineage.observation_id
            for bar in bars
            if bar.lineage.observation_id is not None
        )
    )
    projected: list[TaiwanCanonicalDailyRow] = []
    for bar in bars:
        item = metadata.get(bar.lineage.observation_id or "")
        if item is None:
            continue
        volume = None
        if bar.volume is not None and bar.volume.unit.value == "share":
            volume = int(bar.volume.value)
        projected.append(
            TaiwanCanonicalDailyRow(
                id=int(item["id"]),
                source_id=int(item["source_id"]),
                raw_result_id=int(item["raw_result_id"]),
                trade_date=bar.end_at.astimezone(TAIWAN_TZ).date(),
                stock_id=bar.instrument.symbol,
                stock_name=bar.instrument_name,
                trade_volume=volume,
                trade_value=(
                    int(bar.turnover_value)
                    if bar.turnover_value is not None
                    else None
                ),
                open_price=float(bar.open_price),
                high_price=float(bar.high_price),
                low_price=float(bar.low_price),
                close_price=float(bar.close_price),
                price_change=(
                    float(bar.price_change) if bar.price_change is not None else None
                ),
                transaction_count=bar.trade_count,
                created_at=item["created_at"],
                updated_at=item["updated_at"],
                selected_provider=bar.lineage.provider,
                selected_source=bar.lineage.source,
            )
        )
    return projected


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


class TaiwanOfficialDailyPlatform:
    def __init__(
        self,
        *,
        reader: TaiwanCompletedDailyCandidateReader,
        transaction: TaiwanOfficialDailyTransaction,
        acquisition: TaiwanOfficialDailyAcquisitionExecutor | None = None,
        descriptors: tuple[
            ProviderCapabilityDescriptorV2, ...
        ] = TW_OFFICIAL_DAILY_DESCRIPTORS,
    ) -> None:
        self._reader = reader
        self._transaction = transaction
        self._acquisition = acquisition or TaiwanOfficialDailyAcquisitionExecutor()
        self._descriptors = descriptors
        self._gateway = MarketDataGateway()

    def refresh_instrument(
        self,
        requirement: RefreshRequirementV1,
        *,
        provider_health: tuple[ProviderResourceHealth, ...] = (),
    ) -> TaiwanDailyRefreshResult:
        read_requirement = build_taiwan_daily_read_requirement(requirement)
        plan = plan_refresh_acquisition_v1(
            requirement,
            self._descriptors,
            provider_health,
        )
        if plan.unfillable:
            acquisition = BarAcquisitionResult(
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
            assert isinstance(requirement.target, InstrumentTarget)
            acquisition = self._acquisition.acquire_routes(
                requirement.target.instrument,
                plan.routes,
                trade_date=requirement.to_date,
            )
            if acquisition.receipts or acquisition.observations:
                persistence = self._transaction.persist_bar_acquisition(
                    requirement,
                    acquisition,
                )
            else:
                persistence = PersistenceSummary(
                    attempted=False,
                    limitations=("NO_PERSISTABLE_ACQUISITION_EVIDENCE",),
                )

        persisted = self._gateway.resolve_bars(
            read_requirement,
            reader=self._reader,
        )
        result = MarketDataResultV1(
            requirement=persisted.requirement,
            result_kind="bar_series",
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
        latest_date = (
            result.resolved.bars[-1].end_at.astimezone(TAIWAN_TZ).date()
            if result.resolved.bars
            else None
        )
        postcondition_satisfied = (
            requirement.to_date is not None
            and latest_date is not None
            and latest_date >= requirement.to_date
            and result.resolved.health.status
            in {ResolvedEvidenceStatus.SELECTED, ResolvedEvidenceStatus.FALLBACK}
        )
        limitations = list(result.limitations)
        if not postcondition_satisfied:
            limitations.append("REFRESH_POSTCONDITION_UNSATISFIED")
        return TaiwanDailyRefreshResult(
            requirement=requirement,
            plan=plan,
            acquisition=acquisition.summary,
            persistence=persistence,
            result=result,
            postcondition_satisfied=postcondition_satisfied,
            limitations=tuple(dict.fromkeys(limitations)),
        )


def refresh_taiwan_official_daily(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
    requested_at: datetime | None = None,
    acquisition: TaiwanOfficialDailyAcquisitionExecutor | None = None,
) -> TaiwanDailyRefreshResult:
    """Execute one explicit, bounded official completed-session refresh."""

    normalized_stock_id = str(stock_id or "").strip().upper()
    if not normalized_stock_id:
        raise ValueError("stock_id is required")
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    if stock is None or not stock.is_active:
        raise ValueError(f"active Taiwan stock_id='{normalized_stock_id}' was not found")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("official Taiwan daily refresh requires TWSE/TPEX venue")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    expected_date = expected_daily_price_date(now=effective_requested_at)
    if expected_date is None or trade_date != expected_date:
        raise ValueError(
            "official daily refresh trade_date must equal the latest expected "
            f"completed Taiwan session ({expected_date})"
        )
    instrument_type = (
        InstrumentType.ETF
        if "etf" in str(stock.instrument_type or "").strip().lower()
        else InstrumentType.STOCK
    )
    requirement = RefreshRequirementV1(
        dataset_id=TW_DAILY_DATASET_ID,
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol=normalized_stock_id,
                instrument_type=instrument_type,
                venue=venue,
            )
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=effective_requested_at,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=2 if venue == "TWSE" else 1,
        max_external_calls=2 if venue == "TWSE" else 1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition=(
            f"Latest persisted official {venue} bar for {normalized_stock_id} "
            f"reaches {trade_date.isoformat()}."
        ),
    )
    return TaiwanOfficialDailyPlatform(
        reader=TaiwanCompletedDailyCandidateReader(
            TaiwanOfficialDailyBarRepository(db)
        ),
        transaction=TaiwanOfficialDailyTransaction(db),
        acquisition=acquisition,
    ).refresh_instrument(requirement)


def refresh_taiwan_official_daily_venue(
    db: Session,
    *,
    venue: str,
    trade_date: date,
    requested_at: datetime | None = None,
    acquisition: TaiwanOfficialDailyAcquisitionExecutor | None = None,
) -> dict[str, object]:
    """Refresh one official venue receipt through the existing daily owner.

    This is the dataset-scoped command used by the full-market EOD job.  It
    reuses the same descriptors, canonical bars, transaction owner and source
    lineage as per-instrument refresh; it does not create another EOD store.
    """

    normalized_venue = str(venue or "").strip().upper()
    if normalized_venue not in {"TWSE", "TPEX"}:
        raise ValueError("official Taiwan daily venue must be TWSE or TPEX")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    if effective_requested_at.tzinfo is None or effective_requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    instruments: dict[str, InstrumentKey] = {}
    for stock in list_taiwan_stock_universe(db):
        stock_venue = str(stock.market or "").strip().upper()
        if stock_venue != normalized_venue:
            continue
        instruments[stock.stock_id] = InstrumentKey(
            market=Market.TW,
            symbol=stock.stock_id,
            instrument_type=InstrumentType.STOCK,
            venue=normalized_venue,
        )
    if not instruments:
        raise ValueError(
            f"active Taiwan ordinary-stock universe is empty for venue={normalized_venue}"
        )

    attempt_bound = 2 if normalized_venue == "TWSE" else 1
    requirement = RefreshRequirementV1(
        dataset_id=TW_FULL_MARKET_DAILY_DATASET_ID,
        target=DatasetTarget(
            market=Market.TW,
            dataset_id=TW_FULL_MARKET_DAILY_DATASET_ID,
            scope_key=normalized_venue,
        ),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=effective_requested_at,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=attempt_bound,
        max_external_calls=attempt_bound,
        timeout_seconds=30,
        max_symbols=len(instruments),
        max_range_days=1,
        postcondition=(
            f"Official {normalized_venue} daily observations reach "
            f"{trade_date.isoformat()} and commit atomically."
        ),
    )
    plan = plan_refresh_acquisition_v1(
        requirement,
        TW_OFFICIAL_DAILY_DESCRIPTORS,
    )
    if plan.unfillable:
        return {
            "fetch_status": "skipped",
            "parse_status": "skipped",
            "parsed_count": 0,
            "data_quality_status": "unavailable",
            "raw_result_id": None,
            "fetched_at": effective_requested_at,
            "replaced_trade_dates": [],
            "error_message": "Official daily acquisition plan is unfillable.",
            "limitations": list(plan.limitations),
            "resource_attempts": [],
        }

    executor = acquisition or TaiwanOfficialDailyAcquisitionExecutor()
    acquired = executor.acquire_dataset_routes(
        instruments,
        plan.routes,
        trade_date=trade_date,
    )
    persistence = (
        TaiwanOfficialDailyTransaction(db).persist_bar_acquisition(
            requirement,
            acquired,
        )
        if acquired.receipts or acquired.observations
        else PersistenceSummary(
            attempted=False,
            limitations=("NO_PERSISTABLE_ACQUISITION_EVIDENCE",),
        )
    )
    observed_dates = sorted(
        {
            bar.end_at.astimezone(TAIWAN_TZ).date()
            for bar in acquired.observations
        }
    )
    observed_sources = list(
        dict.fromkeys(bar.lineage.source for bar in acquired.observations)
    )
    parse_success = bool(acquired.observations)
    fetch_success = parse_success and any(
        receipt.error_message is None
        and receipt.status_code is not None
        and 200 <= receipt.status_code < 300
        for receipt in acquired.receipts
    )
    return {
        "fetch_status": "success" if fetch_success else "error",
        "parse_status": "success" if parse_success else "error",
        "source_name": observed_sources[0] if len(observed_sources) == 1 else None,
        "parsed_count": len(acquired.observations),
        "inserted_count": persistence.observations_written,
        "unchanged_observation_count": persistence.observations_unchanged,
        "data_quality_status": (
            "valid"
            if parse_success and not acquired.summary.limitations
            else "warning"
            if parse_success
            else "error"
        ),
        "raw_result_id": (
            persistence.raw_result_ids[-1] if persistence.raw_result_ids else None
        ),
        "raw_result_ids": list(persistence.raw_result_ids),
        "fetched_at": (
            acquired.receipts[-1].fetched_at
            if acquired.receipts
            else effective_requested_at
        ),
        "replaced_trade_dates": observed_dates,
        "error_message": None if parse_success else "Expected official daily observations were not acquired.",
        "limitations": list(
            dict.fromkeys(
                (*acquired.summary.limitations, *persistence.limitations)
            )
        ),
        "resource_attempts": [
            item.model_dump(mode="json")
            for item in acquired.summary.resource_attempts
        ],
    }


__all__ = [
    "TaiwanCanonicalDailyRow",
    "TaiwanDailyPriceEvidence",
    "TaiwanDailyRefreshResult",
    "TaiwanLatestDailyEvidence",
    "TaiwanOfficialDailyPlatform",
    "build_taiwan_daily_read_requirement",
    "build_taiwan_daily_cache_requirement",
    "read_taiwan_official_daily",
    "read_taiwan_latest_daily_evidence",
    "project_taiwan_daily_bars",
    "project_taiwan_daily_rows",
    "refresh_taiwan_official_daily",
    "refresh_taiwan_official_daily_venue",
]
