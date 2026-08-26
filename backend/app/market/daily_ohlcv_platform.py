"""Taiwan official daily OHLCV application service and stable projection seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
    TW_OFFICIAL_DAILY_DESCRIPTORS,
)
from app.market.taiwan_rules import expected_daily_price_date
from app.market_data.contracts import (
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
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
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
        ),
        purpose=DataPurpose.REPAIR,
        realtime_policy=RealtimePolicy.COMPLETED_SESSION,
        session=MarketSession.CLOSED,
        requested_at=refresh.requested_at,
        freshness=FreshnessRequirement(max_age_seconds=2_678_400),
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
    effective_to_date = to_date or expected_daily_price_date(
        now=effective_requested_at.astimezone(TAIWAN_TZ)
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
    repository = TaiwanOfficialDailyBarRepository(db)
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
    return MarketDataGateway().resolve_bars(
        requirement,
        reader=TaiwanCompletedDailyCandidateReader(
            repository
        ),
    )


def read_taiwan_latest_daily_evidence(
    db: Session,
    stock_id: str,
    *,
    requested_at: datetime | None = None,
) -> TaiwanLatestDailyEvidence:
    """Project the latest canonical official bar for AI/valuation consumers."""

    result = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
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
        max_provider_attempts=1,
        max_external_calls=1,
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


__all__ = [
    "TaiwanDailyPriceEvidence",
    "TaiwanDailyRefreshResult",
    "TaiwanLatestDailyEvidence",
    "TaiwanOfficialDailyPlatform",
    "build_taiwan_daily_read_requirement",
    "build_taiwan_daily_cache_requirement",
    "read_taiwan_official_daily",
    "read_taiwan_latest_daily_evidence",
    "refresh_taiwan_official_daily",
]
