from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PriceMapStatus = Literal[
    "ready", "partial", "pending", "stale", "missing", "not_applicable"
]
PriceMapZoneSide = Literal["upside", "downside", "current"]
PriceMapTriggerLinkStatus = Literal["linked", "unlinked"]


class StockPriceMapReferenceRead(BaseModel):
    price: float | None = None
    trade_date: date | None = None
    finalization: str
    authority: str
    source_capability: str
    freshness_status: str


class StockPriceMapLevelRead(BaseModel):
    evidence_id: str
    label: str
    source_type: str
    price: float
    raw_price: float
    role: str
    confirmation: str
    strength: str
    confidence: str
    timeframe: str
    evidence_state: str
    distance_pct: float | None = None
    source_ref: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)


class StockPriceMapZoneRead(BaseModel):
    zone_id: str
    evidence_lower_bound: float
    evidence_upper_bound: float
    lower_bound: float
    upper_bound: float
    anchor_price: float
    role: str
    side: PriceMapZoneSide
    tier_index: int = Field(ge=0)
    tier_label: str
    strength: str
    confidence: str
    distance_pct: float | None = None
    timeframes: list[str] = Field(default_factory=list)
    evidence_state: str
    evidence_count: int = Field(ge=1)
    source_count: int = Field(ge=1)
    method_family_count: int = Field(ge=1)
    strength_components: dict[str, int] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    primary_evidence_id: str
    primary_label: str
    trigger_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class StockPriceMapNearestZoneRead(BaseModel):
    zone_id: str
    anchor_price: float
    lower_bound: float
    upper_bound: float
    role: str
    side: PriceMapZoneSide
    tier_index: int = Field(ge=1)
    tier_label: str
    strength: str
    distance_pct: float | None = None


class StockPriceMapCandidateProjectionRead(BaseModel):
    period: int
    candidate_close: float
    projected_ma: float
    transition_price: float
    relation: str
    role: str


class StockPriceMapCandidateRead(BaseModel):
    semantics: str
    target_trade_date: date | None = None
    candidate_close: float | None = None
    tick_normalized: bool
    projections: list[StockPriceMapCandidateProjectionRead] = Field(
        default_factory=list
    )


class StockPriceMapTechnicalSummaryRead(BaseModel):
    headline: str
    summary: str
    score: int
    value: float | None = None
    value_label: str
    confidence: str
    evidence_summary: list[dict[str, Any]] = Field(default_factory=list)


class StockPriceMapAxisTickRead(BaseModel):
    percent: float
    price: float


class StockPriceMapAxisRead(BaseModel):
    basis_price: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    range_kind: Literal["display_range", "unavailable"]
    range_percent: float | None = None
    authority: str
    is_legal_limit: bool
    ticks: list[StockPriceMapAxisTickRead] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class StockPriceMapMarkerRead(BaseModel):
    kind: Literal["completed_reference", "current_intraday", "provisional"]
    label: str
    price: float
    timeframe: str
    finalization: str
    decision_usable: bool


class StockPriceMapDecisionChangeRead(BaseModel):
    key: str
    label: str
    tone: str
    relation: Literal["at_or_above", "below", "observe"]
    threshold_price: float | None = None
    level_key: str | None = None
    timeframe: str
    evidence_state: str
    decision_usable: bool
    zone_id: str | None = None
    tier_label: str | None = None
    result_summary: str
    link_status: PriceMapTriggerLinkStatus
    link_reason: str


class StockPriceMapMethodologyRead(BaseModel):
    id: str
    version: str
    owner: str
    cluster_rule: str
    cluster_threshold_pct: float
    cluster_min_ticks: int
    zone_padding_pct: float
    zone_padding_ticks: int
    zone_merge_gap_ticks: int
    max_zone_width_pct: float
    side_rule: str
    tier_rule: str
    tick_rule: str
    price_basis: str


class StockPriceMapRead(BaseModel):
    kind: str
    version: str
    market: str
    stock_id: str
    stock_name: str | None = None
    status: PriceMapStatus
    decision_usable: bool
    generated_at: datetime
    basis_revision: str
    evidence_timeframes: list[str] = Field(default_factory=list)
    reference: StockPriceMapReferenceRead
    axis: StockPriceMapAxisRead
    markers: list[StockPriceMapMarkerRead] = Field(default_factory=list)
    technical: StockPriceMapTechnicalSummaryRead
    methodology: StockPriceMapMethodologyRead
    parameter_contract: dict[str, Any]
    levels: list[StockPriceMapLevelRead] = Field(default_factory=list)
    zones: list[StockPriceMapZoneRead] = Field(default_factory=list)
    nearest_upside: StockPriceMapNearestZoneRead | None = None
    nearest_downside: StockPriceMapNearestZoneRead | None = None
    decision_changes: list[StockPriceMapDecisionChangeRead] = Field(
        default_factory=list
    )
    candidate: StockPriceMapCandidateRead
    corporate_action: dict[str, Any]
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


__all__ = ["StockPriceMapRead"]
