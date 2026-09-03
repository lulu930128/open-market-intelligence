"""Cache-only, backend-owned aggregation for the canonical US index set."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from threading import RLock
import time
from typing import Literal

from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.market.calendar_status import build_us_calendar_status
from app.market_data.contracts import (
    CanonicalModel,
    EvidenceFreshness,
    InstrumentType,
    Market,
)
from app.us_market.market_truth import read_us_market_truth_snapshot
from app.us_market.market_truth_contracts import (
    USChangeCalculationStatus,
    USCloseEvidenceKind,
    USComparisonPurpose,
    USMarketTruthSnapshot,
    USObservationKind,
)
from app.us_market.temporal_expectedness import USMarketPhase, USTradeRecency


US_MARKET_INDEX_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("^GSPC", "S&P 500"),
    ("^DJI", "Dow Jones Industrial Average"),
    ("^IXIC", "Nasdaq Composite"),
    ("^NDX", "Nasdaq-100"),
    ("^SOX", "PHLX Semiconductor Sector"),
    ("^VIX", "CBOE Volatility Index"),
)
US_MARKET_INDEX_SYMBOLS = tuple(symbol for symbol, _ in US_MARKET_INDEX_DEFINITIONS)
_US_MARKET_INDICES_CACHE_TTL_SECONDS = 9.75
_US_MARKET_INDICES_CACHE_LOCK = RLock()
_US_MARKET_INDICES_CACHE: dict[tuple[int, str], tuple[float, "USMarketIndicesSnapshot"]] = {}


class USMarketIndexItem(CanonicalModel):
    contract_version: str = "omi.market.us_index_item.v1"
    canonical_symbol: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=80)
    instrument_type: Literal["index"] = "index"
    value: Decimal | None = Field(default=None, gt=0)
    previous_close: Decimal | None = Field(default=None, gt=0)
    change: Decimal | None = None
    change_pct: Decimal | None = None
    trade_date: date | None = None
    event_at: datetime | None = None
    observation_kind: USObservationKind | None = None
    comparison_purpose: USComparisonPurpose = USComparisonPurpose.HEADLINE_CHANGE
    reference_trade_date: date | None = None
    reference_kind: USCloseEvidenceKind | None = None
    selected_provider: str | None = Field(default=None, max_length=64)
    selected_source: str | None = Field(default=None, max_length=128)
    selection_reason: str = Field(min_length=1, max_length=256)
    fallback_used: bool = False
    freshness_status: EvidenceFreshness
    provider_snapshot_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN
    trade_recency: USTradeRecency = USTradeRecency.UNKNOWN
    current_for_requested_session: bool = False
    facts_usable: bool = False
    decision_usable: bool = False
    truth_revision: str = Field(min_length=16, max_length=128)
    observation_id: str | None = Field(default=None, max_length=256)
    limitations: tuple[str, ...] = ()

    @field_validator("event_at")
    @classmethod
    def _require_aware_event_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("US market index event_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_materialized_item(self) -> "USMarketIndexItem":
        materialized = (
            self.value,
            self.trade_date,
            self.event_at,
            self.observation_kind,
            self.selected_provider,
            self.selected_source,
            self.observation_id,
        )
        if self.facts_usable and any(value is None for value in materialized):
            raise ValueError("facts-usable US index item requires observation lineage")
        calculated = self.change is not None or self.change_pct is not None
        if calculated and (
            self.previous_close is None
            or self.reference_trade_date is None
            or self.reference_kind is None
            or self.change is None
            or self.change_pct is None
        ):
            raise ValueError("calculated US index change requires typed reference semantics")
        if self.decision_usable and not self.facts_usable:
            raise ValueError("decision-usable US index item must be facts usable")
        return self


class USMarketIndicesSnapshot(CanonicalModel):
    contract_version: str = "omi.market.us_indices.v1"
    kind: Literal["us_market_indices"] = "us_market_indices"
    market: Literal["US"] = "US"
    status: Literal["ready", "partial", "missing"]
    evaluated_at: datetime
    as_of: datetime | None = None
    oldest_as_of: datetime | None = None
    newest_as_of: datetime | None = None
    mixed_as_of: bool = False
    mixed_trade_dates: bool = False
    market_session: USMarketPhase
    current_for_requested_session: bool
    is_current: bool
    is_complete: bool
    coverage_status: Literal["complete", "partial", "missing"]
    count: int = Field(ge=0, le=6)
    expected_count: Literal[6] = 6
    facts_usable: bool
    decision_usable: bool
    observation_mix: tuple[USObservationKind, ...] = ()
    items: tuple[USMarketIndexItem, ...]
    source: str = "app.us_market.market_indices"
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @field_validator("evaluated_at", "as_of", "oldest_as_of", "newest_as_of")
    @classmethod
    def _require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("US market indices timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_index_set(self) -> "USMarketIndicesSnapshot":
        symbols = tuple(item.canonical_symbol for item in self.items)
        if symbols != US_MARKET_INDEX_SYMBOLS:
            raise ValueError("US market indices must preserve the canonical six-index order")
        usable_count = sum(item.facts_usable for item in self.items)
        if self.count != usable_count:
            raise ValueError("US market index count must match facts-usable items")
        if self.coverage_status == "complete" and usable_count != self.expected_count:
            raise ValueError("complete US market index coverage requires all six items")
        return self


def _item_from_truth(
    *,
    symbol: str,
    label: str,
    snapshot: USMarketTruthSnapshot,
) -> USMarketIndexItem:
    if (
        snapshot.instrument.market is not Market.US
        or snapshot.instrument.instrument_type is not InstrumentType.INDEX
        or snapshot.instrument.symbol != symbol
    ):
        raise ValueError("US market indices received mismatched Market Truth identity")

    observation = snapshot.headline_observation
    metric = next(
        (
            item
            for item in snapshot.change_metrics
            if item.purpose is USComparisonPurpose.HEADLINE_CHANGE
        ),
        None,
    )
    reference = next(
        (
            item
            for item in snapshot.comparison_references
            if item.purpose is USComparisonPurpose.HEADLINE_CHANGE
        ),
        None,
    )
    evidence_by_id = {item.evidence_id: item for item in snapshot.close_evidence}
    reference_evidence = (
        evidence_by_id.get(reference.evidence_id)
        if reference is not None and reference.evidence_id is not None
        else None
    )
    metric_calculated = bool(
        metric is not None
        and metric.calculation_status
        in {
            USChangeCalculationStatus.CALCULATED,
            USChangeCalculationStatus.LIMITED,
        }
    )
    facts_usable = bool(observation is not None and observation.display_usable)
    current_for_requested_session = bool(
        observation is not None
        and observation.current_session_satisfied
        and snapshot.current_observation is not None
        and observation.observation_id
        == snapshot.current_observation.observation_id
    )
    decision_usable = bool(
        facts_usable
        and current_for_requested_session
        and observation is not None
        and observation.research_usable
        and metric is not None
        and metric.research_usable
    )
    limitations: list[str] = list(snapshot.limitations)
    if observation is None:
        limitations.append("US_INDEX_HEADLINE_OBSERVATION_MISSING")
    else:
        limitations.extend(observation.limitations)
        if observation.freshness is EvidenceFreshness.STALE:
            limitations.append("US_INDEX_OBSERVATION_STALE")
    if reference is not None:
        limitations.extend(reference.limitations)
    if metric is None or not metric_calculated:
        limitations.append("US_INDEX_HEADLINE_CHANGE_UNAVAILABLE")

    return USMarketIndexItem(
        canonical_symbol=symbol,
        label=label,
        value=observation.price if observation is not None else None,
        previous_close=reference.price if reference is not None else None,
        change=metric.absolute_change if metric_calculated and metric is not None else None,
        change_pct=(
            metric.percent_change if metric_calculated and metric is not None else None
        ),
        trade_date=observation.trade_date if observation is not None else None,
        event_at=observation.event_at if observation is not None else None,
        observation_kind=observation.kind if observation is not None else None,
        reference_trade_date=(
            reference.reference_trade_date if reference is not None else None
        ),
        reference_kind=(
            reference_evidence.evidence_kind if reference_evidence is not None else None
        ),
        selected_provider=(
            observation.selected_provider if observation is not None else None
        ),
        selected_source=observation.selected_source if observation is not None else None,
        selection_reason=(
            observation.selection_reason
            if observation is not None
            else "US_INDEX_HEADLINE_OBSERVATION_MISSING"
        ),
        fallback_used=observation.fallback_used if observation is not None else False,
        freshness_status=(
            observation.freshness
            if observation is not None
            else EvidenceFreshness.UNKNOWN
        ),
        provider_snapshot_freshness=(
            observation.provider_snapshot_freshness
            if observation is not None
            else EvidenceFreshness.UNKNOWN
        ),
        trade_recency=(
            observation.trade_recency
            if observation is not None
            else USTradeRecency.UNKNOWN
        ),
        current_for_requested_session=current_for_requested_session,
        facts_usable=facts_usable,
        decision_usable=decision_usable,
        truth_revision=snapshot.truth_revision,
        observation_id=(
            observation.observation_id if observation is not None else None
        ),
        limitations=tuple(dict.fromkeys(limitations)),
    )


def compose_us_market_indices(
    *,
    snapshots: tuple[USMarketTruthSnapshot, ...],
    evaluated_at: datetime,
) -> USMarketIndicesSnapshot:
    """Compose a deterministic aggregate from six already-resolved snapshots."""

    if len(snapshots) != len(US_MARKET_INDEX_DEFINITIONS):
        raise ValueError("US market indices require exactly six Market Truth snapshots")
    items = tuple(
        _item_from_truth(symbol=symbol, label=label, snapshot=snapshot)
        for (symbol, label), snapshot in zip(US_MARKET_INDEX_DEFINITIONS, snapshots)
    )
    usable_count = sum(item.facts_usable for item in items)
    coverage_status = (
        "complete"
        if usable_count == len(items)
        else "missing"
        if usable_count == 0
        else "partial"
    )
    event_times = tuple(item.event_at for item in items if item.event_at is not None)
    trade_dates = {item.trade_date for item in items if item.trade_date is not None}
    phases = {snapshot.market_phase for snapshot in snapshots}
    if len(phases) != 1:
        raise ValueError("US market indices require one shared market phase")
    market_session = next(iter(phases))
    current_for_requested_session = all(
        item.current_for_requested_session for item in items
    )
    is_current = bool(
        coverage_status == "complete"
        and current_for_requested_session
        and all(
            item.freshness_status
            in {EvidenceFreshness.LIVE, EvidenceFreshness.FRESH}
            for item in items
        )
    )
    missing = tuple(item.canonical_symbol for item in items if not item.facts_usable)
    warnings = tuple(
        dict.fromkeys(
            limitation
            for item in items
            for limitation in item.limitations
            if limitation
        )
    )
    return USMarketIndicesSnapshot(
        status=(
            "ready"
            if coverage_status == "complete"
            else "missing"
            if coverage_status == "missing"
            else "partial"
        ),
        evaluated_at=evaluated_at,
        as_of=max(event_times, default=None),
        oldest_as_of=min(event_times, default=None),
        newest_as_of=max(event_times, default=None),
        mixed_as_of=len(set(event_times)) > 1,
        mixed_trade_dates=len(trade_dates) > 1,
        market_session=market_session,
        current_for_requested_session=current_for_requested_session,
        is_current=is_current,
        is_complete=coverage_status == "complete",
        coverage_status=coverage_status,
        count=usable_count,
        facts_usable=usable_count > 0,
        decision_usable=all(item.decision_usable for item in items),
        observation_mix=tuple(
            sorted(
                {
                    item.observation_kind
                    for item in items
                    if item.observation_kind is not None
                },
                key=lambda value: value.value,
            )
        ),
        items=items,
        missing=missing,
        warnings=warnings,
    )


def read_us_market_indices(
    db: Session,
    *,
    evaluated_at: datetime,
) -> USMarketIndicesSnapshot:
    """Read six canonical Market Truth snapshots without provider IO or writes."""

    bind_identity = id(db.get_bind()) if isinstance(db, Session) else id(db)
    market_phase = str(
        build_us_calendar_status(evaluated_at).get("phase") or "market_closed"
    )
    cache_key = (bind_identity, market_phase)
    # The six-symbol aggregate is a frequent shared dashboard dependency. A
    # short backend-owned cache plus one build lock prevents simultaneous UI,
    # AI and MCP reads from each recomputing the same canonical components
    # while materializers are writing. Cached timestamps remain the time of
    # the actual read and are never relabelled as a newer observation.
    with _US_MARKET_INDICES_CACHE_LOCK:
        cached = _US_MARKET_INDICES_CACHE.get(cache_key)
        if cached is not None:
            cached_at, cached_snapshot = cached
            if time.monotonic() - cached_at <= _US_MARKET_INDICES_CACHE_TTL_SECONDS:
                return cached_snapshot
            _US_MARKET_INDICES_CACHE.pop(cache_key, None)

        snapshots = tuple(
            read_us_market_truth_snapshot(
                db,
                symbol=symbol,
                evaluated_at=evaluated_at,
            )
            for symbol in US_MARKET_INDEX_SYMBOLS
        )
        result = compose_us_market_indices(
            snapshots=snapshots,
            evaluated_at=evaluated_at,
        )
        _US_MARKET_INDICES_CACHE[cache_key] = (time.monotonic(), result)
        return result


__all__ = [
    "US_MARKET_INDEX_DEFINITIONS",
    "US_MARKET_INDEX_SYMBOLS",
    "USMarketIndexItem",
    "USMarketIndicesSnapshot",
    "compose_us_market_indices",
    "read_us_market_indices",
]
