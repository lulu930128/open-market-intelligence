"""Cache-only canonical repository for Taiwan current-session aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session, load_only

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanCurrentBreadthSnapshot,
    TaiwanCurrentIndexSnapshot,
)
from app.market.trading_calendar import is_taiwan_trading_day
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_BREADTH_CAPABILITY_ID,
    TW_CURRENT_BREADTH_DATASET_ID,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TW_CURRENT_INDEX_DATASET_ID,
    TW_CURRENT_INDEX_MAX_ABS_CHANGE_RATIO,
    current_source_binding,
    expected_index_symbol,
)
from app.market.tw_dataset_lifecycle import evaluate_taiwan_candidate_dataset_health
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    EvidenceFreshness,
    Market,
    MarketBreadthObservation,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import (
    MarketBreadthCandidateBatch,
    MarketIndexCandidateBatch,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
)
from app.market_data.resolution import ResolutionCandidate


TAIPEI_TZ = timezone(timedelta(hours=8))
CURRENT_INDEX_MAX_ABS_CHANGE_RATIO = TW_CURRENT_INDEX_MAX_ABS_CHANGE_RATIO

_RAW_FETCH_LINEAGE_COLUMNS = (
    RawFetchResult.id,
    RawFetchResult.source_id,
    RawFetchResult.content_hash,
    RawFetchResult.parser_version,
)


@dataclass(frozen=True, slots=True)
class TaiwanIndexSeriesRow:
    storage_row_id: int
    provider: str
    source: str
    authority: AuthorityClass
    provider_priority: int
    raw_result_id: int
    content_hash: str
    trade_date: date
    event_at: datetime
    received_at: datetime
    fetched_at: datetime
    session: MarketSession
    close_value: Decimal
    price_change: Decimal
    finalization: BarFinalization
    official: bool
    provisional: bool


@dataclass(frozen=True, slots=True)
class TaiwanIndexSeriesBatch:
    rows: tuple[TaiwanIndexSeriesRow, ...] = ()
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


def _aware(value: datetime, *, tz=timezone.utc) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _freshness(requirement: DataRequirementV2, event_at: datetime) -> EvidenceFreshness:
    age = (requirement.requested_at - _aware(event_at, tz=TAIPEI_TZ)).total_seconds()
    return (
        EvidenceFreshness.LIVE
        if -300 <= age <= requirement.freshness.max_age_seconds
        else EvidenceFreshness.STALE
    )


class TaiwanCurrentMarketRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _target(
        requirement: DataRequirementV2,
        *,
        dataset_id: str,
        capability_id: str,
    ) -> DatasetTarget:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("current market repository requires dataset target")
        if requirement.target.market is not Market.TW:
            raise ValueError("current market repository requires market=TW")
        if requirement.target.dataset_id != dataset_id:
            raise ValueError("current market repository dataset mismatch")
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("current market repository requires dataset capability")
        if requirement.request.capability_id != capability_id:
            raise ValueError("current market repository capability mismatch")
        return requirement.target

    @staticmethod
    def _identity_valid(
        *,
        provider: str,
        source_name: str,
        authority: str,
        parser_version: str,
        source_id: int,
        raw_result_id: int,
        source: SourceRegistry,
        raw: RawFetchResult,
        capability_id: str,
    ) -> bool:
        binding = current_source_binding(
            provider=provider,
            source=source_name,
            capability_id=capability_id,
        )
        return bool(
            binding is not None
            and binding.descriptor.authority.value == authority
            and binding.parser_version == parser_version
            and source.id == source_id
            and source.source_name == source_name
            and raw.id == raw_result_id
            and raw.source_id == source.id
            and raw.parser_version == parser_version
            and raw.content_hash
        )

    @staticmethod
    def _raw_scope_identity_valid(
        *,
        binding,
        scope_key: str,
        raw: RawFetchResult,
    ) -> bool:
        expected_symbol = expected_index_symbol(binding, index_id=scope_key)
        if expected_symbol is None:
            return True
        try:
            payload = json.loads(raw.raw_text or "")
            actual_symbol = str(payload["data"]["symbol"]).strip().upper()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return actual_symbol == expected_symbol

    def read_market_index_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketIndexCandidateBatch:
        target = self._target(
            requirement,
            dataset_id=TW_CURRENT_INDEX_DATASET_ID,
            capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        )
        if not inspect(self._db.get_bind()).has_table(
            TaiwanCurrentIndexSnapshot.__tablename__
        ):
            return MarketIndexCandidateBatch(
                dataset_health=evaluate_taiwan_candidate_dataset_health(
                    requirement,
                    dataset_id=TW_CURRENT_INDEX_DATASET_ID,
                    eligible=is_taiwan_trading_day(
                        requirement.requested_at.astimezone(TAIPEI_TZ).date()
                    ),
                ),
                limitations=("TW_CURRENT_INDEX_SCHEMA_UNAVAILABLE",),
            )
        providers = (
            self._db.query(TaiwanCurrentIndexSnapshot.provider)
            .filter(TaiwanCurrentIndexSnapshot.index_id == target.scope_key)
            .distinct()
            .order_by(TaiwanCurrentIndexSnapshot.provider.asc())
            .limit(requirement.bounds.max_candidates * 4)
            .all()
        )
        rows = []
        for (provider,) in providers:
            latest = (
                self._db.query(
                    TaiwanCurrentIndexSnapshot,
                    RawFetchResult,
                    SourceRegistry,
                )
                .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
                .join(
                    RawFetchResult,
                    RawFetchResult.id == TaiwanCurrentIndexSnapshot.raw_result_id,
                )
                .join(
                    SourceRegistry,
                    SourceRegistry.id == TaiwanCurrentIndexSnapshot.source_id,
                )
                .filter(TaiwanCurrentIndexSnapshot.index_id == target.scope_key)
                .filter(TaiwanCurrentIndexSnapshot.provider == provider)
                .order_by(
                    TaiwanCurrentIndexSnapshot.event_at.desc(),
                    TaiwanCurrentIndexSnapshot.id.desc(),
                )
                .first()
            )
            if latest is not None:
                rows.append(latest)
        seen: set[str] = set()
        candidates: list[ResolutionCandidate[MarketIndexObservation]] = []
        rejections: list[CandidateRowRejection] = []
        event_times: list[datetime] = []
        freshness_values: list[EvidenceFreshness] = []
        for row, raw, source in rows:
            if row.provider in seen:
                continue
            seen.add(row.provider)
            binding = current_source_binding(
                provider=row.provider,
                source=row.source,
                capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
            )
            if binding is None or not self._identity_valid(
                provider=row.provider,
                source_name=row.source,
                authority=row.authority,
                parser_version=row.raw_contract_version,
                source_id=row.source_id,
                raw_result_id=row.raw_result_id,
                source=source,
                raw=raw,
                capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_INDEX_LINEAGE_IDENTITY_MISMATCH",
                    )
                )
                continue
            if not self._raw_scope_identity_valid(
                binding=binding,
                scope_key=target.scope_key,
                raw=raw,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_INDEX_RAW_SCOPE_IDENTITY_MISMATCH",
                    )
                )
                continue
            close_value = Decimal(str(row.close_value))
            price_change = Decimal(str(row.price_change))
            previous_close = close_value - price_change
            if (
                previous_close <= 0
                or abs(price_change) / previous_close
                > CURRENT_INDEX_MAX_ABS_CHANGE_RATIO
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_INDEX_CHANGE_IMPLAUSIBLE",
                    )
                )
                continue
            try:
                observation = MarketIndexObservation(
                    market=Market.TW,
                    index_id=row.index_id,
                    venue=row.venue,
                    lineage=SourceLineage(
                        provider=row.provider,
                        source=row.source,
                        authority=AuthorityClass(row.authority),
                        raw_contract_version=row.raw_contract_version,
                        event_at=_aware(row.event_at, tz=TAIPEI_TZ),
                        received_at=_aware(row.received_at),
                        fetched_at=_aware(row.fetched_at),
                        cache_hit=True,
                        observation_id=f"taiwan_current_index_snapshot:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw.id}",
                        content_hash=raw.content_hash,
                    ),
                    session=MarketSession(row.session),
                    trade_date=row.trade_date,
                    close_value=close_value,
                    price_change=price_change,
                    trade_volume=(
                        Quantity(
                            value=Decimal(row.trade_volume),
                            unit=QuantityUnit(row.trade_volume_unit),
                        )
                        if row.trade_volume is not None and row.trade_volume_unit
                        else None
                    ),
                    trade_value=(
                        Decimal(row.trade_value) if row.trade_value is not None else None
                    ),
                    currency=row.currency,
                    transaction_count=row.transaction_count,
                    state=ObservationState(row.observation_state),
                    value_semantics=row.value_semantics,
                    finalization=BarFinalization(row.finalization),
                    official=row.official,
                    provisional=row.provisional,
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_CURRENT_INDEX",
                    )
                )
                continue
            freshness = _freshness(requirement, observation.lineage.event_at)
            event_times.append(observation.lineage.event_at)
            freshness_values.append(freshness)
            candidates.append(
                ResolutionCandidate(
                    observation=observation,
                    freshness=freshness,
                    provider_priority=binding.descriptor.priority,
                    session=observation.session,
                    limitations=binding.persistent_limitations,
                )
            )
        candidates.sort(key=lambda item: item.provider_priority)
        return MarketIndexCandidateBatch(
            candidates=tuple(candidates[: requirement.bounds.max_candidates]),
            dataset_health=evaluate_taiwan_candidate_dataset_health(
                requirement,
                dataset_id=TW_CURRENT_INDEX_DATASET_ID,
                eligible=is_taiwan_trading_day(
                    requirement.requested_at.astimezone(TAIPEI_TZ).date()
                ),
                event_times=event_times,
                freshness_values=freshness_values,
                partial=bool(rejections),
            ),
            rejections=tuple(rejections),
            limitations=(
                () if candidates else ("TW_CURRENT_INDEX_CANONICAL_CACHE_MISSING",)
            ),
        )

    def read_market_breadth_candidates(
        self,
        requirement: DataRequirementV2,
    ) -> MarketBreadthCandidateBatch:
        target = self._target(
            requirement,
            dataset_id=TW_CURRENT_BREADTH_DATASET_ID,
            capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
        )
        if not inspect(self._db.get_bind()).has_table(
            TaiwanCurrentBreadthSnapshot.__tablename__
        ):
            return MarketBreadthCandidateBatch(
                dataset_health=evaluate_taiwan_candidate_dataset_health(
                    requirement,
                    dataset_id=TW_CURRENT_BREADTH_DATASET_ID,
                    eligible=is_taiwan_trading_day(
                        requirement.requested_at.astimezone(TAIPEI_TZ).date()
                    ),
                ),
                limitations=("TW_CURRENT_BREADTH_SCHEMA_UNAVAILABLE",),
            )
        rows = (
            self._db.query(
                TaiwanCurrentBreadthSnapshot,
                RawFetchResult,
                SourceRegistry,
            )
            .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
            .join(RawFetchResult, RawFetchResult.id == TaiwanCurrentBreadthSnapshot.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == TaiwanCurrentBreadthSnapshot.source_id)
            .filter(TaiwanCurrentBreadthSnapshot.venue == target.scope_key)
            .order_by(
                TaiwanCurrentBreadthSnapshot.provider.asc(),
                TaiwanCurrentBreadthSnapshot.event_at.desc(),
                TaiwanCurrentBreadthSnapshot.id.desc(),
            )
            .limit(requirement.bounds.max_candidates * 4)
            .all()
        )
        seen: set[str] = set()
        candidates: list[ResolutionCandidate[MarketBreadthObservation]] = []
        rejections: list[CandidateRowRejection] = []
        limitations: list[str] = []
        event_times: list[datetime] = []
        freshness_values: list[EvidenceFreshness] = []
        partial = False
        for row, raw, source in rows:
            if row.provider in seen:
                continue
            seen.add(row.provider)
            binding = current_source_binding(
                provider=row.provider,
                source=row.source,
                capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
            )
            if binding is None or not self._identity_valid(
                provider=row.provider,
                source_name=row.source,
                authority=row.authority,
                parser_version=row.raw_contract_version,
                source_id=row.source_id,
                raw_result_id=row.raw_result_id,
                source=source,
                raw=raw,
                capability_id=TW_CURRENT_BREADTH_CAPABILITY_ID,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_BREADTH_LINEAGE_IDENTITY_MISMATCH",
                    )
                )
                continue
            try:
                observation = MarketBreadthObservation(
                    market=Market.TW,
                    venue=row.venue,
                    lineage=SourceLineage(
                        provider=row.provider,
                        source=row.source,
                        authority=AuthorityClass(row.authority),
                        raw_contract_version=row.raw_contract_version,
                        event_at=_aware(row.event_at, tz=TAIPEI_TZ),
                        received_at=_aware(row.received_at),
                        fetched_at=_aware(row.fetched_at),
                        cache_hit=True,
                        observation_id=f"taiwan_current_breadth_snapshot:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw.id}",
                        content_hash=raw.content_hash,
                    ),
                    session=MarketSession(row.session),
                    trade_date=row.trade_date,
                    scope=row.scope,
                    universe_source=row.universe_source,
                    universe_count=row.universe_count,
                    advance_count=row.advance_count,
                    decline_count=row.decline_count,
                    unchanged_count=row.unchanged_count,
                    unknown_count=row.received_unclassified_count,
                    missing_count=row.not_received_count,
                    trade_value=(
                        Decimal(row.trade_value) if row.trade_value is not None else None
                    ),
                    currency=row.currency,
                    state=ObservationState(row.observation_state),
                    price_semantics=row.price_semantics,
                    official=row.official,
                    provisional=row.provisional,
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_CURRENT_BREADTH",
                    )
                )
                continue
            try:
                limitations.extend(json.loads(row.limitations_json or "[]"))
            except (TypeError, ValueError):
                limitations.append("CURRENT_BREADTH_LIMITATIONS_MALFORMED")
            freshness = _freshness(requirement, observation.lineage.event_at)
            event_times.append(observation.lineage.event_at)
            freshness_values.append(freshness)
            partial = partial or observation.state is ObservationState.PARTIAL
            candidates.append(
                ResolutionCandidate(
                    observation=observation,
                    freshness=freshness,
                    provider_priority=binding.descriptor.priority,
                    session=observation.session,
                )
            )
        candidates.sort(key=lambda item: item.provider_priority)
        if not candidates:
            limitations.append("TW_CURRENT_BREADTH_CANONICAL_CACHE_MISSING")
        return MarketBreadthCandidateBatch(
            candidates=tuple(candidates[: requirement.bounds.max_candidates]),
            dataset_health=evaluate_taiwan_candidate_dataset_health(
                requirement,
                dataset_id=TW_CURRENT_BREADTH_DATASET_ID,
                eligible=is_taiwan_trading_day(
                    requirement.requested_at.astimezone(TAIPEI_TZ).date()
                ),
                event_times=event_times,
                freshness_values=freshness_values,
                partial=partial or bool(rejections),
            ),
            rejections=tuple(rejections),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def read_market_index_series_rows(
        self,
        *,
        index_id: str,
        trade_date: date,
        max_rows: int = 5000,
    ) -> TaiwanIndexSeriesBatch:
        """Read lineage-valid current-index events for a derived minute series."""

        normalized_index_id = str(index_id or "").strip().upper()
        if normalized_index_id not in {"TAIEX", "TPEX"}:
            raise ValueError("Taiwan index series requires TAIEX or TPEX")
        bounded_rows = max(min(int(max_rows), 10_000), 1)
        if not inspect(self._db.get_bind()).has_table(
            TaiwanCurrentIndexSnapshot.__tablename__
        ):
            return TaiwanIndexSeriesBatch(
                limitations=("TW_CURRENT_INDEX_SCHEMA_UNAVAILABLE",)
            )
        rows = (
            self._db.query(
                TaiwanCurrentIndexSnapshot,
                RawFetchResult,
                SourceRegistry,
            )
            .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
            .join(
                RawFetchResult,
                RawFetchResult.id == TaiwanCurrentIndexSnapshot.raw_result_id,
            )
            .join(
                SourceRegistry,
                SourceRegistry.id == TaiwanCurrentIndexSnapshot.source_id,
            )
            .filter(TaiwanCurrentIndexSnapshot.index_id == normalized_index_id)
            .filter(TaiwanCurrentIndexSnapshot.trade_date == trade_date)
            .order_by(
                TaiwanCurrentIndexSnapshot.event_at.asc(),
                TaiwanCurrentIndexSnapshot.id.asc(),
            )
            .limit(bounded_rows)
            .all()
        )
        accepted: list[TaiwanIndexSeriesRow] = []
        rejections: list[CandidateRowRejection] = []
        limitations: list[str] = []
        for row, raw, source in rows:
            binding = current_source_binding(
                provider=row.provider,
                source=row.source,
                capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
            )
            if binding is None or not self._identity_valid(
                provider=row.provider,
                source_name=row.source,
                authority=row.authority,
                parser_version=row.raw_contract_version,
                source_id=row.source_id,
                raw_result_id=row.raw_result_id,
                source=source,
                raw=raw,
                capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_INDEX_LINEAGE_IDENTITY_MISMATCH",
                    )
                )
                continue
            if not self._raw_scope_identity_valid(
                binding=binding,
                scope_key=normalized_index_id,
                raw=raw,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="CURRENT_INDEX_RAW_SCOPE_IDENTITY_MISMATCH",
                    )
                )
                continue
            try:
                close_value = Decimal(str(row.close_value))
                price_change = Decimal(str(row.price_change))
                previous_close = close_value - price_change
                authority = AuthorityClass(row.authority)
                session = MarketSession(row.session)
                if (
                    close_value <= 0
                    or previous_close <= 0
                    or abs(price_change) / previous_close
                    > CURRENT_INDEX_MAX_ABS_CHANGE_RATIO
                ):
                    raise ValueError("implausible current index value")
                accepted.append(
                    TaiwanIndexSeriesRow(
                        storage_row_id=row.id,
                        provider=row.provider,
                        source=row.source,
                        authority=authority,
                        provider_priority=binding.descriptor.priority,
                        raw_result_id=row.raw_result_id,
                        content_hash=str(raw.content_hash),
                        trade_date=row.trade_date,
                        event_at=_aware(row.event_at, tz=TAIPEI_TZ),
                        received_at=_aware(row.received_at),
                        fetched_at=_aware(row.fetched_at),
                        session=session,
                        close_value=close_value,
                        price_change=price_change,
                        finalization=BarFinalization(row.finalization),
                        official=bool(row.official),
                        provisional=bool(row.provisional),
                    )
                )
            except (TypeError, ValueError):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=row.raw_result_id,
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_CURRENT_INDEX_SERIES_ROW",
                    )
                )
        if len(rows) >= bounded_rows:
            limitations.append("TW_INDEX_INTRADAY_ROW_BOUND_REACHED")
        if not accepted:
            limitations.append("TW_INDEX_INTRADAY_CANONICAL_CACHE_MISSING")
        if rejections:
            limitations.append("TW_INDEX_INTRADAY_CANDIDATES_REJECTED")
        return TaiwanIndexSeriesBatch(
            rows=tuple(accepted),
            rejections=tuple(rejections),
            limitations=tuple(dict.fromkeys(limitations)),
        )


__all__ = [
    "TaiwanCurrentMarketRepository",
    "TaiwanIndexSeriesBatch",
    "TaiwanIndexSeriesRow",
]
