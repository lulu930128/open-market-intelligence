"""Taiwan official daily OHLCV application service and stable projection seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from time import monotonic
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import StockMaster, MarketDailyPrice
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.providers.tw_official_daily import (
    TW_DAILY_DATASET_ID,
    TW_FULL_MARKET_DAILY_DATASET_ID,
    TW_OFFICIAL_DAILY_DESCRIPTORS,
    parse_twse_official_daily_payload,
    parse_twse_rwd_official_daily_payload,
    parse_tpex_official_daily_payload,
    parse_tpex_dated_daily_payload,
    source_name_for_resource,
    TWSE_DAILY_RESOURCE_ID,
    TWSE_RWD_DAILY_RESOURCE_ID,
    TPEX_DAILY_RESOURCE_ID,
    TPEX_DAILY_CLOSE_RESOURCE_ID,
    TPEX_DATED_DAILY_RESOURCE_ID,
    TW_BREADTH_DATASET_ID,
    TPEX_OFFICIAL_BREADTH_DESCRIPTOR,
)
from app.market.tw_universe import list_taiwan_stock_universe, list_taiwan_daily_collection_universe
from app.market.trading_calendar import has_taiwan_calendar_year, is_taiwan_trading_day
from app.market.taiwan_rules import (
    TAIWAN_DAILY_REGULAR_RESEARCH_RELEASE, TAIWAN_DAILY_REGULAR_SCOPE,
    expected_daily_price_date, expected_daily_research_date, taiwan_daily_price_release_at,
    taiwan_published_breadth_observation_at,
)
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
    release_status: str = "released"
    official_final: bool = True


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
    purpose: DataPurpose = DataPurpose.VIEWER,
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
        purpose=purpose,
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
    allow_early_regular: bool = False,
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
    latest_potentially_released_date = (expected_daily_research_date if allow_early_regular else expected_daily_price_date)(
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
        if str(stock.instrument_type or "").strip().lower() in {"etf", "exchange_traded_fund"}
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
        allow_early_regular=allow_early_regular,
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
    return project_taiwan_latest_daily_evidence(result)


def project_taiwan_latest_daily_evidence(result: MarketDataResultV1) -> TaiwanLatestDailyEvidence:
    """Shared single/batch outward projection of resolved daily evidence."""
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
                release_status="regular_research" if "OFFICIAL_FINAL_PENDING" in bar.limitations else "released",
                official_final="OFFICIAL_FINAL_PENDING" not in bar.limitations,
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
    if (expected_date is None or trade_date > expected_date
            or (expected_date - trade_date).days > 31
            or not has_taiwan_calendar_year(trade_date.year)
            or not is_taiwan_trading_day(trade_date)):
        raise ValueError(
            "official daily refresh trade_date must be a known trading day within "
            f"31 days of the latest expected completed Taiwan session ({expected_date})"
        )
    historical = trade_date < expected_date
    # Snapshot-only resources cannot answer a historical correction. Keep the
    # existing dated adapters and transaction owner, with one symbol/day/call.
    descriptors = tuple(item for item in TW_OFFICIAL_DAILY_DESCRIPTORS
                        if not historical or item.resource_id in {
                            TWSE_RWD_DAILY_RESOURCE_ID, TPEX_DATED_DAILY_RESOURCE_ID})
    instrument_type = (
        InstrumentType.ETF
        if str(stock.instrument_type or "").strip().lower() in {"etf", "exchange_traded_fund"}
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
        max_provider_attempts=2 if venue == "TWSE" and not historical else 1,
        max_external_calls=2 if venue == "TWSE" and not historical else 1,
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
        descriptors=descriptors,
    ).refresh_instrument(requirement)


def refresh_taiwan_official_daily_venue(
    db: Session,
    *,
    venue: str,
    trade_date: date,
    requested_at: datetime | None = None,
    acquisition: TaiwanOfficialDailyAcquisitionExecutor | None = None,
    refresh_daily: bool = True,
    refresh_published: bool = True,
    timeout_seconds: int = 30,
    max_external_calls: int = 2,
    route_state: dict[str, object] | None = None,
) -> dict[str, object]:
    """Refresh one official venue receipt through the existing daily owner.

    This is the dataset-scoped command used by the full-market EOD job.  It
    reuses the same descriptors, canonical bars, transaction owner and source
    lineage as per-instrument refresh; it does not create another EOD store.
    """

    started_at = monotonic()
    normalized_venue = str(venue or "").strip().upper()
    if normalized_venue not in {"TWSE", "TPEX"}:
        raise ValueError("official Taiwan daily venue must be TWSE or TPEX")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    if effective_requested_at.tzinfo is None or effective_requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if timeout_seconds < 1 or max_external_calls < 1:
        raise ValueError("official venue refresh requires a positive remaining time/call budget")
    instruments: dict[str, InstrumentKey] = {}
    for stock in list_taiwan_daily_collection_universe(db, markets=(normalized_venue,)):
        stock_venue = str(stock.market or "").strip().upper()
        if stock_venue != normalized_venue:
            continue
        instruments[stock.stock_id] = InstrumentKey(
            market=Market.TW,
            symbol=stock.stock_id,
            instrument_type=(InstrumentType.STOCK if str(stock.instrument_type).lower() == "stock" else InstrumentType.ETF),
            venue=normalized_venue,
        )
    if not instruments:
        raise ValueError(
            f"active Taiwan daily collection universe is empty for venue={normalized_venue}"
        )

    # EOD continuation is scoped by the existing date/universe checkpoint. The
    # canonical repository owns qualification; never refetch/overwrite its current
    # members merely because another symbol in this venue remains unresolved.
    if route_state is not None:
        repository = TaiwanOfficialDailyBarRepository(
            db, allow_early_regular=effective_requested_at < taiwan_daily_price_release_at(trade_date),
        )
        # Reuse the bounded canonical reader; its explicit symbol limit is 500.
        symbols = tuple(instruments)
        for offset in range(0, len(symbols), 500):
            qualified = repository.load_market_universe(trade_date=trade_date, include_etf=True,
                venue=normalized_venue, symbols=symbols[offset:offset + 500])
            for bar in qualified.bars:
                instruments.pop(bar.instrument.symbol, None)
        refresh_daily = refresh_daily and bool(instruments)

    # Plan the bounded venue route pool independently of this job's remaining
    # calls. Execution still admits at most attempt_bound calls, including breadth.
    attempt_bound = max(int(max_external_calls), 1)
    early_attempt = effective_requested_at < taiwan_daily_price_release_at(trade_date)
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
        timeout_seconds=min(max(int(timeout_seconds), 1), 30),
        max_symbols=max(1, len(instruments)),
        max_range_days=1,
        postcondition=(
            f"Official {normalized_venue} daily observations reach "
            f"{trade_date.isoformat()} and commit atomically."
        ),
    )
    plan = plan_refresh_acquisition_v1(
        requirement.model_copy(update={"max_provider_attempts": 3, "max_external_calls": 3}),
        TW_OFFICIAL_DAILY_DESCRIPTORS,
    )
    if plan.unfillable:
        return {
            "external_call_count": 0,
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
    companion_routes = ()
    if refresh_published and normalized_venue == "TPEX" and effective_requested_at >= taiwan_published_breadth_observation_at(trade_date):
        breadth_requirement = requirement.model_copy(update={
            "dataset_id": TW_BREADTH_DATASET_ID,
            "target": DatasetTarget(market=Market.TW, dataset_id=TW_BREADTH_DATASET_ID, scope_key="TPEX"),
            "max_provider_attempts": 1, "max_external_calls": 1, "max_symbols": 1,
            "postcondition": "Persist the dated official published breadth receipt in the EOD transaction.",
        })
        companion_routes = plan_refresh_acquisition_v1(
            breadth_requirement, (TPEX_OFFICIAL_BREADTH_DESCRIPTOR,),
        ).routes
    daily_routes = plan.routes if refresh_daily else tuple(
        route for route in plan.routes if refresh_published and route.resource_id == TWSE_RWD_DAILY_RESOURCE_ID
    )
    if early_attempt:
        # Early daily OHLCV remains TWSE RWD only. Published aggregates have
        # their independent post-close boundary and share the same call budget.
        daily_routes = tuple(route for route in daily_routes
            if route.resource_id == TWSE_RWD_DAILY_RESOURCE_ID and (
                refresh_daily and trade_date == expected_daily_research_date(now=effective_requested_at)
                or not refresh_daily and refresh_published
                and effective_requested_at >= taiwan_published_breadth_observation_at(trade_date)))
    route_pool = (*daily_routes, *companion_routes)
    route_keys = {route.resource_id for route in route_pool}
    # Respect both caller admission and the existing planner's finite pool:
    # up to two TWSE resources, or three TPEx daily plus one breadth companion.
    attempt_bound = min(attempt_bound, max(1, len(route_keys)))
    requirement = requirement.model_copy(update={
        "max_provider_attempts": attempt_bound, "max_external_calls": attempt_bound,
    })
    attempted_resources: set[str] = set()
    if route_state:
        if (route_state.get("version") != 1 or route_state.get("venue") != normalized_venue
                or route_state.get("trade_date") != trade_date.isoformat()):
            raise ValueError("official daily route continuation context changed")
        prior = route_state.get("attempted_resources")
        if not isinstance(prior, list) or len(prior) > 4 or any(not isinstance(item, str) for item in prior):
            raise ValueError("invalid official daily route continuation")
        attempted_resources = set(prior) & route_keys
        if not early_attempt and route_state.get("release_phase") == "regular_research":
            attempted_resources.clear()
        # A completed round can retry after the EOD owner's existing backoff.
        # An unfinished round must reach the secondary/companion before replaying.
        if route_keys <= attempted_resources:
            attempted_resources.clear()
    daily_routes = tuple(route for route in daily_routes if route.resource_id not in attempted_resources)
    companion_routes = tuple(route for route in companion_routes if route.resource_id not in attempted_resources)
    acquired = executor.acquire_dataset_routes(
        instruments if refresh_daily else {},
        daily_routes,
        trade_date=trade_date,
        companion_routes=companion_routes,
        timeout_seconds=max(0, requirement.timeout_seconds - (monotonic() - started_at)),
        max_external_calls=attempt_bound,
        published_only=not refresh_daily,
    )
    persistence = (
        TaiwanOfficialDailyTransaction(db).persist_bar_acquisition(
            requirement if refresh_daily else requirement.model_copy(update={
                "dataset_id": TW_BREADTH_DATASET_ID,
                "target": DatasetTarget(market=Market.TW, dataset_id=TW_BREADTH_DATASET_ID,
                                        scope_key=normalized_venue),
            }),
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
    attempted_resources.update(item.resource_id for item in acquired.summary.resource_attempts)
    missing_symbols = set(instruments) - {bar.instrument.symbol for bar in acquired.observations}
    pending_resources = route_keys - attempted_resources
    if not missing_symbols:
        pending_resources -= {route.resource_id for route in daily_routes}
    next_route_state = {
        "version": 1, "venue": normalized_venue, "trade_date": trade_date.isoformat(),
        "attempted_resources": sorted(attempted_resources),
        "pending_resources": sorted(pending_resources),
        "release_phase": "regular_research" if early_attempt else "official_final",
    }
    # Keep the daily command's primary receipt bound to its bars. The aggregate
    # has its own receipt in raw_result_ids, committed in this same transaction.
    primary_receipt_index = next((
        index for index in reversed(range(len(acquired.receipts)))
        if acquired.receipts[index].source in observed_sources
    ), len(acquired.receipts) - 1)
    # A continuation may have only a published companion left in its route pool.
    # Its valid receipt does not imply daily coverage; EOD rereads both axes.
    parse_success = acquired.summary.status in {AcquisitionStatus.COMPLETED, AcquisitionStatus.PARTIAL}
    # Parsing/qualification errors can accompany a successfully received body.
    fetch_success = any(
        receipt.status_code is not None
        and 200 <= receipt.status_code < 300
        for receipt in acquired.receipts
    )
    if not refresh_daily:
        # Transport success is not completion: the job rereads the canonical
        # published receipt after this transaction commits.
        parse_success = acquired.summary.status in {AcquisitionStatus.COMPLETED, AcquisitionStatus.PARTIAL} and any(
            receipt.status_code == 200 and not receipt.error_message for receipt in acquired.receipts
        )
    publication_pending = early_attempt and not acquired.summary.attempted
    return {
        "external_call_count": acquired.summary.external_calls,
        "publication_pending": publication_pending,
        "research_ready_count": sum("OFFICIAL_FINAL_PENDING" in bar.limitations for bar in acquired.observations),
        "release_status": TAIWAN_DAILY_REGULAR_RESEARCH_RELEASE if any(
            "OFFICIAL_FINAL_PENDING" in bar.limitations for bar in acquired.observations
        ) else "released" if acquired.observations else "unavailable",
        "fetch_status": "skipped" if publication_pending else "success" if fetch_success else "error",
        "parse_status": "skipped" if publication_pending else "success" if parse_success else "error",
        "source_name": observed_sources[0] if len(observed_sources) == 1 else (
            acquired.receipts[primary_receipt_index].source if acquired.receipts and not observed_sources else None
        ),
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
            persistence.raw_result_ids[primary_receipt_index] if persistence.raw_result_ids else None
        ),
        "raw_result_ids": list(persistence.raw_result_ids),
        "fetched_at": (
            acquired.receipts[primary_receipt_index].fetched_at
            if acquired.receipts
            else effective_requested_at
        ),
        "replaced_trade_dates": observed_dates,
        "error_message": None if parse_success else "Expected official daily observations were not acquired.",
        "limitations": list(
            dict.fromkeys(
                (*acquired.summary.limitations, *persistence.limitations,
                 *(("EARLY_OFFICIAL_SOURCE_UNVERIFIED",) if publication_pending and normalized_venue == "TPEX" else ()))
            )
        ),
        "resource_attempts": [
            item.model_dump(mode="json")
            for item in acquired.summary.resource_attempts
        ],
        "route_continuation": next_route_state,
    }


def qualify_taiwan_eod_universe(
    db: Session, *, trade_date: date, include_published: bool = False,
) -> dict[str, object]:
    """Batch eligibility port for shared coverage; no refresh or per-stock resolver."""
    batch = TaiwanOfficialDailyBarRepository(db).load_market_universe(trade_date=trade_date)
    collection = list_taiwan_daily_collection_universe(db)
    etfs = [item for item in collection if str(item.instrument_type).lower() != "stock"]
    etf_bars = []
    etf_rejections = []
    repository = TaiwanOfficialDailyBarRepository(db)
    for offset in range(0, len(etfs), 500):
        etf_batch = repository.load_market_universe(trade_date=trade_date, include_etf=True,
            symbols=tuple(item.stock_id for item in etfs[offset:offset + 500]))
        etf_bars.extend(etf_batch.bars)
        etf_rejections.extend(etf_batch.rejection_reasons)
    etf_symbols = tuple(item.stock_id for item in etfs)
    etf_latest = dict(db.query(MarketDailyPrice.stock_id, func.max(MarketDailyPrice.trade_date))
        .filter(MarketDailyPrice.stock_id.in_(etf_symbols))
        .filter(MarketDailyPrice.trade_date <= trade_date).group_by(MarketDailyPrice.stock_id).all()) if etfs else {}
    reasons: dict[str, list[str]] = {}
    for symbol, reason in (*batch.rejection_reasons, *etf_rejections):
        reasons.setdefault(symbol, []).append(reason)
    qualified = {bar.instrument.symbol for bar in (*batch.bars, *etf_bars)}
    universe = list_taiwan_stock_universe(db)
    unresolved = {item.stock_id for item in collection if item.stock_id not in qualified}
    parser_by_source = {
        source_name_for_resource(TWSE_DAILY_RESOURCE_ID): parse_twse_official_daily_payload,
        source_name_for_resource(TWSE_RWD_DAILY_RESOURCE_ID): parse_twse_rwd_official_daily_payload,
        source_name_for_resource(TPEX_DAILY_RESOURCE_ID): parse_tpex_official_daily_payload,
        source_name_for_resource(TPEX_DAILY_CLOSE_RESOURCE_ID): parse_tpex_official_daily_payload,
        source_name_for_resource(TPEX_DATED_DAILY_RESOURCE_ID): parse_tpex_dated_daily_payload,
    }
    diagnostics = []
    if unresolved:
        receipts = TaiwanOfficialDailyBarRepository(db).load_official_daily_receipts(
            trade_date=trade_date, as_of=datetime.now(TAIWAN_TZ),
        )
        for raw, source in receipts:
            diagnostic = {"source": source.source_name, "raw_result_id": raw.id, "fetched_at": raw.fetched_at.isoformat(),
                          "transport_status": "received" if raw.status_code is not None and 200 <= raw.status_code < 300
                          else "failed" if raw.error_message or raw.status_code is not None and raw.status_code >= 400 else "received"}
            diagnostics.append(diagnostic)
            parser = parser_by_source.get(source.source_name)
            if diagnostic["transport_status"] == "failed":
                continue
            if not parser or not raw.raw_text or len(raw.raw_text) > 10_000_000:
                diagnostic["payload_status"] = "unavailable_or_exceeds_bound"
                continue
            try:
                parsed = parser(raw.raw_text)
            except (TypeError, ValueError):
                diagnostic["payload_status"] = "unparseable"
                continue
            dated_records = {record.symbol for record in parsed.records if record.trade_date == trade_date}
            dated_rejections = {record.symbol: record.reason_code for record in parsed.rejected_rows if record.trade_date == trade_date}
            if not dated_records and not dated_rejections:
                diagnostic["payload_status"] = "expected_date_not_observed"
                continue
            diagnostic["payload_status"] = "expected_date_observed"
            diagnostic["observed_symbol_count"] = len(dated_records | dated_rejections.keys())
            diagnostic["symbol_reasons"] = {}
            for member in collection:
                if member.stock_id not in unresolved or str(member.market).upper() != parsed.venue:
                    continue
                reason = ("PROVIDER_" + dated_rejections[member.stock_id] if member.stock_id in dated_rejections
                          else "PROVIDER_ROW_NOT_CANONICALLY_MATERIALIZED" if member.stock_id in dated_records
                          else "SYMBOL_ABSENT_FROM_DATED_PROVIDER_PAYLOAD")
                reasons.setdefault(member.stock_id, []).append(reason)
                diagnostic["symbol_reasons"][member.stock_id] = reason
    from app.market.official_breadth_platform import read_taiwan_official_breadth

    published_breadth = {}
    for venue in (sorted({str(item.market).upper() for item in universe} & {"TWSE", "TPEX"})
                  if include_published else ()):
        resolved = read_taiwan_official_breadth(db, venue=venue, trade_date=trade_date,
                                             allow_universe_fallback=False)
        observation = resolved.resolved.breadth
        published_breadth[venue] = bool(observation is not None and observation.published_limits is not None)
    return {
        "etf_scope": {
            "members": tuple({"symbol": item.stock_id, "venue": str(item.market).upper()} for item in etfs),
            "qualified_symbols": tuple(bar.instrument.symbol for bar in etf_bars),
            "latest_by_symbol": etf_latest,
            "rejection_reasons": {symbol: tuple(dict.fromkeys(reasons.get(symbol, ()))) for symbol in etf_symbols},
        },
        "published_breadth": published_breadth,
        "qualified_symbols": tuple(bar.instrument.symbol for bar in batch.bars),
        "rejection_reasons": {symbol: tuple(dict.fromkeys(values)) for symbol, values in reasons.items()},
        "rows_examined": batch.rows_examined, "rows_rejected": batch.rows_rejected,
        "limitations": batch.limitations,
        "provider_diagnostics": diagnostics,
    }


__all__ = [
    "qualify_taiwan_eod_universe",
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
