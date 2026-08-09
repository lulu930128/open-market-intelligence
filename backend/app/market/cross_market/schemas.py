from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.market.schemas import AdrParityRead


class InstrumentRefRead(BaseModel):
    market: str
    instrument_type: str
    canonical_symbol: str
    provider_symbol: str | None = None
    exchange: str | None = None
    currency: str | None = None


class CrossMarketRelationEvidenceRead(BaseModel):
    evidence_id: int
    source_type: str
    source_grade: str
    source_label: str
    source_url: str
    statement: str
    published_at: datetime | None = None
    verified_at: datetime
    content_hash: str
    is_primary: bool
    review_status: str


class CrossMarketRelationRead(BaseModel):
    relation_id: int
    relation_version: int
    source: InstrumentRefRead
    target: InstrumentRefRead
    relation_type: str
    relation_subtype: str | None = None
    bucket: str
    directionality: str
    base_weight: float
    confidence_tier: str
    evidence_grade: str
    ratio_numerator: float | None = None
    ratio_denominator: float | None = None
    depositary: str | None = None
    listing_tier: str | None = None
    valid_from: date
    valid_to: date | None = None
    verified_at: datetime
    review_status: str
    status: str
    decision_usable: bool
    evidence: list[CrossMarketRelationEvidenceRead] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CrossMarketRelationRegistryRead(BaseModel):
    kind: str
    schema_version: str
    status: str
    decision_usable: bool
    target: InstrumentRefRead
    as_of: date
    generated_at: datetime
    relation_count: int
    relations: list[CrossMarketRelationRead] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    freshness: dict[str, object] = Field(default_factory=dict)


class CrossMarketRelationEvidenceCandidate(BaseModel):
    source_type: str
    source_grade: str
    source_label: str
    source_url: str
    statement: str
    published_at: datetime | None = None
    verified_at: datetime
    content_hash: str | None = None
    is_primary: bool = False


class CrossMarketRelationCandidate(BaseModel):
    source: InstrumentRefRead
    target: InstrumentRefRead
    relation_type: str
    relation_subtype: str | None = None
    bucket: str
    directionality: str = "positive"
    base_weight: float = Field(ge=0.0, le=1.0)
    confidence_tier: str
    evidence_grade: str
    ratio_numerator: float | None = None
    ratio_denominator: float | None = None
    depositary: str | None = None
    listing_tier: str | None = None
    valid_from: date
    valid_to: date | None = None
    verified_at: datetime
    evidence: list[CrossMarketRelationEvidenceCandidate] = Field(default_factory=list)


class CrossMarketContextSummaryRead(BaseModel):
    stance: str
    score: float | None = None
    confidence: str
    title: str
    reason_codes: list[str] = Field(default_factory=list)


class CrossMarketContextSignalRead(BaseModel):
    signal_id: str
    relation_id: int | None = None
    relation_version: int | None = None
    source: InstrumentRefRead
    target: InstrumentRefRead
    bucket: str
    relation_type: str
    relation_subtype: str | None = None
    event_context: str | None = None
    calculation: dict[str, Any] = Field(default_factory=dict)
    direction: str
    configured_weight: float
    quality_multiplier: float
    effective_weight: float
    normalized_weight: float | None = None
    contribution: float | None = None
    status: str
    decision_usable: bool
    confidence_tier: str
    freshness: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None


class CrossMarketContextCoverageRead(BaseModel):
    configured_signal_count: int
    available_signal_count: int
    decision_usable_signal_count: int
    configured_weight: float
    available_weight: float
    decision_usable_weight: float
    coverage_ratio: float
    excluded_by_reason: dict[str, int] = Field(default_factory=dict)


class CrossMarketTargetContextRead(BaseModel):
    kind: str
    schema_version: str
    target: InstrumentRefRead
    status: str
    decision_usable: bool
    as_of: date | None = None
    decision_at: datetime
    methodology_version: str
    relation_snapshot_version: str
    snapshot_id: str
    summary: CrossMarketContextSummaryRead
    direct_equivalents: list[AdrParityRead] = Field(default_factory=list)
    signals: list[CrossMarketContextSignalRead] = Field(default_factory=list)
    bucket_scores: dict[str, float | None] = Field(default_factory=dict)
    coverage: CrossMarketContextCoverageRead
    freshness: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    evidence_passport: dict[str, Any] = Field(default_factory=dict)
