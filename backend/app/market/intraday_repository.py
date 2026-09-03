"""Cache-only canonical repository for Taiwan intraday bars."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session, load_only

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
)
from app.market.trading_calendar import is_taiwan_trading_day
from app.market.tw_bar_contracts import (
    TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_RAW_CONTRACT,
)
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID,
    current_source_binding,
)
from app.market.tw_dataset_lifecycle import evaluate_taiwan_candidate_dataset_health
from app.market.tw_intraday_capabilities import intraday_source_binding
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    EvidenceFreshness,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import BarCandidateBatch
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
)
from app.market_data.resolution import BarSeriesCandidate


TAIPEI_TZ = timezone(timedelta(hours=8))

_RAW_FETCH_LINEAGE_COLUMNS = (
    RawFetchResult.id,
    RawFetchResult.source_id,
    RawFetchResult.content_hash,
    RawFetchResult.parser_version,
)


def _as_taipei(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=TAIPEI_TZ)
    return value.astimezone(TAIPEI_TZ)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _interval_delta(interval: str) -> timedelta:
    if interval.endswith("m") and interval[:-1].isdigit():
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h") and interval[:-1].isdigit():
        return timedelta(hours=int(interval[:-1]))
    raise ValueError("unsupported persisted intraday interval")


class TaiwanIntradayBarRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _validate(requirement: DataRequirementV2) -> tuple[InstrumentTarget, BarCapabilityRequest]:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
            requirement.request,
            BarCapabilityRequest,
        ):
            raise ValueError("intraday repository requires instrument bar request")
        if requirement.target.instrument.market is not Market.TW:
            raise ValueError("intraday repository requires market=TW")
        if requirement.request.interval != "1m":
            raise ValueError("TW_BASE_BAR_INTERVAL_REQUIRED")
        return requirement.target, requirement.request

    def _rows(
        self,
        requirement: DataRequirementV2,
    ) -> list[
        tuple[
            MarketIntradayBar,
            MarketIntradayBarLineage,
            RawFetchResult | None,
            SourceRegistry,
        ]
    ]:
        target, request = self._validate(requirement)
        inspector = inspect(self._db.get_bind())
        if not inspector.has_table(MarketIntradayBar.__tablename__):
            return []
        columns = {
            item["name"]
            for item in inspector.get_columns(MarketIntradayBar.__tablename__)
        }
        if not {
            "source_id",
            "canonical_market",
            "venue",
            "instrument_type",
        }.issubset(columns):
            return []
        rows = (
            self._db.query(
                MarketIntradayBar,
                MarketIntradayBarLineage,
                RawFetchResult,
                SourceRegistry,
            )
            .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
            .join(
                MarketIntradayBarLineage,
                MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
            )
            .outerjoin(
                RawFetchResult,
                RawFetchResult.id == MarketIntradayBarLineage.raw_result_id,
            )
            .join(
                SourceRegistry,
                SourceRegistry.id == MarketIntradayBarLineage.source_id,
            )
            .filter(MarketIntradayBar.stock_id == target.instrument.symbol)
            .filter(MarketIntradayBar.market == target.instrument.venue)
            .filter(MarketIntradayBar.canonical_market == Market.TW.value)
            .filter(MarketIntradayBar.venue == target.instrument.venue)
            .filter(
                MarketIntradayBar.instrument_type
                == target.instrument.instrument_type.value
            )
            .filter(MarketIntradayBar.interval == "1m")
            .filter(MarketIntradayBar.bar_time >= request.start_at)
            .filter(MarketIntradayBar.bar_time <= request.end_at)
            .order_by(
                MarketIntradayBar.provider.asc(),
                MarketIntradayBar.bar_time.desc(),
                MarketIntradayBar.id.desc(),
            )
            .limit(request.max_bars * requirement.bounds.max_candidates + 1)
            .all()
        )
        if len(rows) > request.max_bars * requirement.bounds.max_candidates:
            raise ValueError("intraday repository read exceeded bounded candidate rows")
        return rows

    def _materialized_index_content_hash(
        self,
        *,
        row: MarketIntradayBar,
        lineage: MarketIntradayBarLineage,
        source: SourceRegistry,
    ) -> tuple[str, tuple[str, ...]] | None:
        if (
            row.instrument_type != InstrumentType.INDEX.value
            or lineage.raw_result_id is not None
            or lineage.calculation_version
            != TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION
            or lineage.raw_contract_version != TAIWAN_INDEX_MINUTE_RAW_CONTRACT
        ):
            return None
        binding = current_source_binding(
            provider=row.provider,
            source=row.source,
            capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        )
        if (
            binding is None
            or binding.descriptor.authority.value != lineage.authority
            or source.id != lineage.source_id
            or source.source_name != row.source
        ):
            return None
        try:
            component_ids = tuple(
                int(value)
                for value in json.loads(
                    lineage.component_raw_result_ids_json or "[]"
                )
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not component_ids or len(component_ids) != len(set(component_ids)):
            return None
        component_rows = (
            self._db.query(RawFetchResult)
            .filter(RawFetchResult.id.in_(component_ids))
            .all()
        )
        by_id = {item.id: item for item in component_rows}
        if len(by_id) != len(component_ids):
            return None
        ordered = tuple(by_id[value] for value in component_ids)
        if any(
            item.source_id != source.id
            or item.parser_version != binding.parser_version
            or not item.content_hash
            for item in ordered
        ):
            return None
        payload = [
            {"source_id": source.id, "content_hash": str(item.content_hash)}
            for item in ordered
        ]
        hashes = tuple(str(item.content_hash) for item in ordered)
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return digest, hashes

    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch:
        target, request = self._validate(requirement)
        rows = self._rows(requirement)
        by_provider: dict[tuple[str, str], list[BarObservation]] = defaultdict(list)
        priorities: dict[tuple[str, str], int] = {}
        limitations_by_provider: dict[tuple[str, str], tuple[str, ...]] = {}
        rejections: list[CandidateRowRejection] = []
        accepted_counts: dict[tuple[str, str], int] = defaultdict(int)
        for row, lineage_row, raw, source in rows:
            identity = (row.provider, row.source)
            if accepted_counts[identity] >= request.max_bars:
                continue
            materialized_lineage = self._materialized_index_content_hash(
                row=row,
                lineage=lineage_row,
                source=source,
            )
            materialized_hash = (
                materialized_lineage[0]
                if materialized_lineage is not None
                else None
            )
            binding = intraday_source_binding(provider=row.provider, source=row.source)
            acquired_identity_valid = bool(
                binding is not None
                and raw is not None
                and lineage_row.provider == row.provider
                and lineage_row.source == row.source
                and row.source_id == lineage_row.source_id
                and source.id == lineage_row.source_id
                and source.source_name == row.source
                and raw.id == lineage_row.raw_result_id
                and raw.source_id == source.id
                and raw.parser_version == binding.parser_version
                and raw.content_hash is not None
                and lineage_row.authority == binding.descriptor.authority.value
                and (
                    lineage_row.raw_contract_version == binding.parser_version
                    or lineage_row.raw_contract_version.startswith(
                        f"{binding.parser_version}+"
                    )
                )
            )
            invalid_identity = not acquired_identity_valid and materialized_hash is None
            if invalid_identity:
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=lineage_row.raw_result_id,
                        event_date=_as_taipei(row.bar_time).date(),
                        reason_code="INTRADAY_LINEAGE_IDENTITY_MISMATCH",
                    )
                )
                continue
            missing = tuple(
                name
                for name in (
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                )
                if getattr(row, name) is None
            )
            if missing:
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=(raw.id if raw is not None else None),
                        event_date=_as_taipei(row.bar_time).date(),
                        reason_code="MISSING_REQUIRED_OHLC",
                        missing_fields=missing,
                    )
                )
                continue
            start_at = _as_taipei(row.bar_time)
            if start_at.second != 0 or start_at.microsecond != 0:
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=(raw.id if raw is not None else None),
                        event_date=start_at.date(),
                        reason_code="INTRADAY_BUCKET_NOT_MINUTE_ALIGNED",
                    )
                )
                continue
            try:
                bar = BarObservation(
                    instrument=target.instrument,
                    lineage=SourceLineage(
                        provider=row.provider,
                        source=row.source,
                        authority=AuthorityClass(lineage_row.authority),
                        raw_contract_version=lineage_row.raw_contract_version,
                        event_at=_as_taipei(lineage_row.event_at),
                        received_at=_as_utc(lineage_row.received_at),
                        fetched_at=_as_utc(lineage_row.fetched_at),
                        cache_hit=True,
                        observation_id=f"market_intraday_bar:{row.id}",
                        raw_receipt_id=(
                            f"raw_fetch_result:{raw.id}"
                            if raw is not None
                            else None
                        ),
                        content_hash=(
                            materialized_hash
                            if materialized_hash is not None
                            else raw.content_hash if raw is not None else None
                        ),
                        component_content_hashes=(
                            materialized_lineage[1]
                            if materialized_lineage is not None
                            else ()
                        ),
                        materialization_version=(
                            TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION
                            if materialized_lineage is not None
                            else None
                        ),
                    ),
                    interval=row.interval,
                    start_at=start_at,
                    end_at=start_at + _interval_delta(row.interval),
                    open_price=Decimal(str(row.open_price)),
                    high_price=Decimal(str(row.high_price)),
                    low_price=Decimal(str(row.low_price)),
                    close_price=Decimal(str(row.close_price)),
                    volume=(
                        Quantity(
                            value=Decimal(row.trade_volume),
                            unit=QuantityUnit.SHARE,
                        )
                        if row.trade_volume is not None
                        else None
                    ),
                    volume_status=(
                        "not_applicable"
                        if target.instrument.instrument_type is InstrumentType.INDEX
                        else "observed"
                        if row.trade_volume is not None
                        else "missing"
                    ),
                    price_basis=(
                        "raw"
                        if materialized_hash is not None
                        else "provider_default"
                    ),
                    turnover_value=(
                        Decimal(row.trade_value)
                        if row.trade_value is not None
                        else None
                    ),
                    turnover_currency=("TWD" if row.trade_value is not None else None),
                    finalization=BarFinalization(lineage_row.finalization),
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=(raw.id if raw is not None else None),
                        event_date=start_at.date(),
                        reason_code="INVALID_CANONICAL_INTRADAY_BAR",
                    )
                )
                continue
            by_provider[identity].append(bar)
            descriptor = (
                binding.descriptor
                if binding is not None
                else current_source_binding(
                    provider=row.provider,
                    source=row.source,
                    capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
                ).descriptor
            )
            priorities[identity] = descriptor.priority
            limitations_by_provider[identity] = descriptor.limitations
            accepted_counts[identity] += 1

        candidates: list[BarSeriesCandidate] = []
        event_times: list[datetime] = []
        freshness_values: list[EvidenceFreshness] = []
        for identity, reverse_bars in by_provider.items():
            bars = tuple(sorted(reverse_bars, key=lambda item: item.start_at))
            if not bars:
                continue
            latest_event = bars[-1].lineage.event_at
            age = (
                (requirement.requested_at - latest_event).total_seconds()
                if latest_event is not None
                else float("inf")
            )
            freshness = (
                EvidenceFreshness.LIVE
                if -300 <= age <= requirement.freshness.max_age_seconds
                else EvidenceFreshness.STALE
            )
            if latest_event is not None:
                event_times.append(latest_event)
            freshness_values.append(freshness)
            candidates.append(
                BarSeriesCandidate(
                    bars=bars,
                    freshness=freshness,
                    provider_priority=priorities[identity],
                    session=requirement.session,
                    limitations=limitations_by_provider[identity],
                )
            )
        candidates.sort(key=lambda item: item.provider_priority)
        limitations = (
            ()
            if candidates
            else ("TW_INTRADAY_CANONICAL_CACHE_MISSING",)
        )
        return BarCandidateBatch(
            candidates=tuple(candidates[: requirement.bounds.max_candidates]),
            dataset_health=evaluate_taiwan_candidate_dataset_health(
                requirement,
                dataset_id="tw.intraday.bars",
                eligible=is_taiwan_trading_day(
                    requirement.requested_at.astimezone(TAIPEI_TZ).date()
                ),
                event_times=event_times,
                freshness_values=freshness_values,
                partial=bool(rejections),
            ),
            rejections=tuple(rejections),
            limitations=limitations,
        )

    def lineage_metadata(
        self,
        observation_ids: tuple[str, ...],
    ) -> dict[str, dict[str, object | None]]:
        row_ids: list[int] = []
        for observation_id in observation_ids:
            prefix = "market_intraday_bar:"
            if observation_id.startswith(prefix):
                try:
                    row_ids.append(int(observation_id.removeprefix(prefix)))
                except ValueError:
                    continue
        if not row_ids:
            return {}
        rows = (
            self._db.query(MarketIntradayBarLineage)
            .filter(MarketIntradayBarLineage.bar_id.in_(row_ids))
            .all()
        )
        return {
            f"market_intraday_bar:{row.bar_id}": {
                "source_interval": row.source_interval,
                "calculation_version": row.calculation_version,
                "component_raw_result_ids": row.component_raw_result_ids_json,
            }
            for row in rows
        }


__all__ = ["TaiwanIntradayBarRepository"]
