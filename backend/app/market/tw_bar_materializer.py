"""Deterministic Taiwan Bar materialization from canonical event evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json

from sqlalchemy.orm import Session

from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_contracts import (
    TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_RAW_CONTRACT,
    TPEX_DERIVED_DAILY_PROVIDER,
    TPEX_DERIVED_DAILY_SOURCE,
)
from app.market.tw_bar_aggregation import aggregate_completed_session_to_1d
from app.market.tw_current_market_repository import (
    TaiwanCurrentMarketRepository,
    TaiwanIndexSeriesRow,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_instrument_trading_policy import (
    is_taiwan_continuous_time_bar_start,
)
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    BarFinalization,
    BarObservation,
    SourceLineage,
)


@dataclass(frozen=True, slots=True)
class TaiwanMaterializedBarCandidate:
    observation: BarObservation
    source_id: int
    component_raw_result_ids: tuple[int, ...]
    component_content_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaiwanIndexMinuteMaterializationBatch:
    candidates: tuple[TaiwanMaterializedBarCandidate, ...] = ()
    rejections: tuple[CandidateRowRejection, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaiwanMaterializedDailyCandidate:
    observation: BarObservation
    component_raw_result_ids: tuple[int, ...]
    component_content_hashes: tuple[str, ...]
    source_interval: str


def _component_digest(rows: tuple[TaiwanIndexSeriesRow, ...]) -> str:
    payload = [
        {
            "source_id": row.source_id,
            "content_hash": row.content_hash,
        }
        for row in rows
    ]
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def materialize_index_minute_candidates(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
    as_of: datetime,
    page_size: int = 1000,
) -> TaiwanIndexMinuteMaterializationBatch:
    """Build one 1m candidate per provider/source without selecting a winner."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    instrument = resolve_taiwan_instrument(db, index_id)
    if instrument.instrument_type.value != "index":
        raise ValueError("index minute materialization requires INDEX instrument")
    batch = TaiwanCurrentMarketRepository(db).read_market_index_series_rows(
        index_id=instrument.symbol,
        trade_date=trade_date,
        max_rows=page_size,
    )
    grouped: dict[
        tuple[str, str, int, datetime],
        list[TaiwanIndexSeriesRow],
    ] = defaultdict(list)
    for row in batch.rows:
        local_event = row.event_at.astimezone(TAIWAN_TZ)
        # The formal 13:30 match remains a marker until its exact component
        # contract is accepted. It cannot enter Base-1m or technical input.
        if not is_taiwan_continuous_time_bar_start(local_event):
            continue
        minute_start = local_event.replace(second=0, microsecond=0)
        grouped[(row.provider, row.source, row.source_id, minute_start)].append(row)

    candidates: list[TaiwanMaterializedBarCandidate] = []
    for (provider, source, source_id, minute_start), values in sorted(
        grouped.items(),
        key=lambda item: (item[0][0], item[0][1], item[0][3]),
    ):
        rows = tuple(
            sorted(values, key=lambda item: (item.event_at, item.storage_row_id))
        )
        first = rows[0]
        last = rows[-1]
        if any(
            row.provider != provider
            or row.source != source
            or row.source_id != source_id
            or row.authority is not first.authority
            for row in rows
        ):
            raise ValueError("index minute candidate crossed source identity")
        prices = tuple(row.close_value for row in rows)
        minute_end = minute_start + timedelta(minutes=1)
        candidates.append(
            TaiwanMaterializedBarCandidate(
                observation=BarObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=provider,
                        source=source,
                        authority=first.authority,
                        raw_contract_version=TAIWAN_INDEX_MINUTE_RAW_CONTRACT,
                        event_at=last.event_at,
                        received_at=last.received_at,
                        fetched_at=last.fetched_at,
                        content_hash=_component_digest(rows),
                    ),
                    interval="1m",
                    start_at=minute_start,
                    end_at=minute_end,
                    open_price=first.close_value,
                    high_price=max(prices),
                    low_price=min(prices),
                    close_price=last.close_value,
                    volume=None,
                    volume_status="not_applicable",
                    price_basis="raw",
                    finalization=(
                        BarFinalization.FINAL
                        if minute_end <= as_of.astimezone(TAIWAN_TZ)
                        else BarFinalization.PROVISIONAL
                    ),
                ),
                source_id=source_id,
                component_raw_result_ids=tuple(
                    dict.fromkeys(row.raw_result_id for row in rows)
                ),
                component_content_hashes=tuple(
                    dict.fromkeys(row.content_hash for row in rows)
                ),
            )
        )
    limitations = list(batch.limitations)
    if not candidates:
        limitations.append("TW_INDEX_MINUTE_CANDIDATES_MISSING")
    return TaiwanIndexMinuteMaterializationBatch(
        candidates=tuple(candidates),
        rejections=batch.rejections,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def materialize_tpex_completed_daily_candidate(
    components: tuple[BarObservation, ...],
    *,
    formal_close_component: BarObservation,
    component_raw_result_ids: tuple[int, ...],
    component_content_hashes: tuple[str, ...],
    coverage_complete: bool,
    as_of: datetime,
) -> TaiwanMaterializedDailyCandidate:
    if not components or any(item.instrument.symbol != "TPEX" for item in components):
        raise ValueError("TPEX daily materialization requires TPEX components")
    if any(
        item.instrument != components[0].instrument
        or item.interval != "5s"
        or item.lineage.authority.value != "exchange"
        for item in components
    ):
        raise ValueError(
            "TPEX daily materialization requires one qualified exchange 5s series"
        )
    if (
        formal_close_component.instrument != components[0].instrument
        or formal_close_component.interval != "closing_match"
        or formal_close_component.lineage.authority.value != "exchange"
        or formal_close_component.finalization
        not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
    ):
        raise ValueError(
            "TPEX daily materialization requires an explicit exchange closing match"
        )
    if not component_raw_result_ids or not component_content_hashes:
        raise ValueError("TPEX daily materialization requires component evidence")
    if len(set(component_raw_result_ids)) != len(component_raw_result_ids):
        raise ValueError("TPEX daily component raw ids must be unique")
    if len(set(component_content_hashes)) != len(component_content_hashes):
        raise ValueError("TPEX daily component hashes must be unique")
    ordered = tuple(sorted(components, key=lambda item: item.start_at))
    session_date = ordered[0].start_at.astimezone(TAIWAN_TZ).date()
    expected_start = datetime.combine(session_date, time(9), tzinfo=TAIWAN_TZ)
    expected_end = datetime.combine(session_date, time(13, 30), tzinfo=TAIWAN_TZ)
    qualified_complete = bool(
        ordered[0].start_at.astimezone(TAIWAN_TZ) == expected_start
        and ordered[-1].end_at.astimezone(TAIWAN_TZ) == expected_end
        and all(
            item.finalization in {BarFinalization.FINAL, BarFinalization.CORRECTED}
            and item.end_at - item.start_at == timedelta(seconds=5)
            for item in ordered
        )
        and all(
            current.end_at == following.start_at
            for current, following in zip(ordered, ordered[1:])
        )
    )
    if coverage_complete and not qualified_complete:
        raise ValueError("TPEX completed daily coverage proof failed")
    observation = aggregate_completed_session_to_1d(
        ordered,
        output_provider=TPEX_DERIVED_DAILY_PROVIDER,
        output_source=TPEX_DERIVED_DAILY_SOURCE,
        source_interval=components[0].interval,
        coverage_complete=coverage_complete,
        as_of=as_of,
        formal_close_component=formal_close_component,
    )
    observation = observation.model_copy(
        update={
            "lineage": observation.lineage.model_copy(
                update={
                    "component_content_hashes": component_content_hashes,
                    "materialization_version": TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
                }
            )
        }
    )
    return TaiwanMaterializedDailyCandidate(
        observation=observation,
        component_raw_result_ids=component_raw_result_ids,
        component_content_hashes=component_content_hashes,
        source_interval=components[0].interval,
    )


__all__ = [
    "TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION",
    "TAIWAN_INDEX_MINUTE_RAW_CONTRACT",
    "TaiwanIndexMinuteMaterializationBatch",
    "TaiwanMaterializedBarCandidate",
    "TaiwanMaterializedDailyCandidate",
    "materialize_index_minute_candidates",
    "materialize_tpex_completed_daily_candidate",
]
