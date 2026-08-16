from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal


ResolutionStatus = Literal["ready", "partial", "blocked", "disputed"]
StatementKind = Literal["duration", "instant"]
PeriodScope = Literal[
    "instant",
    "discrete_3m",
    "ytd_3m",
    "ytd_6m",
    "ytd_9m",
    "annual_12m",
    "ambiguous",
]
UnitKind = Literal["money", "per_share", "shares", "pure", "unsupported"]


@dataclass(frozen=True, slots=True)
class SecFact:
    fact_id: str
    cik: str
    taxonomy: str
    tag: str
    unit: str
    value_text: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed_date: date | None
    period_start_date: date | None
    period_end_date: date | None
    accession_number: str | None
    frame: str | None = None
    source_url: str | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> SecFact:
        """Create a pure fact from a parsed record or persisted ORM row."""

        fact_id = getattr(raw, "fact_key", None)
        if not fact_id:
            row_id = getattr(raw, "id", None)
            fact_id = f"row:{row_id}" if row_id is not None else "unknown"

        return cls(
            fact_id=str(fact_id),
            cik=str(getattr(raw, "cik")),
            taxonomy=str(getattr(raw, "taxonomy")),
            tag=str(getattr(raw, "tag")),
            unit=str(getattr(raw, "unit")),
            value_text=getattr(raw, "value_text", None),
            fiscal_year=getattr(raw, "fiscal_year", None),
            fiscal_period=getattr(raw, "fiscal_period", None),
            form=getattr(raw, "form", None),
            filed_date=getattr(raw, "filed_date", None),
            period_start_date=getattr(raw, "period_start_date", None),
            period_end_date=getattr(raw, "period_end_date", None),
            accession_number=getattr(raw, "accession_number", None),
            frame=getattr(raw, "frame", None),
            source_url=getattr(raw, "source_url", None),
        )


@dataclass(frozen=True, slots=True)
class PeriodResolution:
    statement_kind: StatementKind
    scope: PeriodScope
    fiscal_year: int | None
    fiscal_quarter: int | None
    period_start: date | None
    period_end: date | None
    duration_days: int | None
    status: ResolutionStatus
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnitResolution:
    raw_unit: str
    kind: UnitKind
    normalized_unit: str | None
    currency: str | None
    status: ResolutionStatus
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricTag:
    taxonomy: str
    tag: str


@dataclass(frozen=True, slots=True)
class CanonicalMetricSpec:
    metric_code: str
    statement_kind: StatementKind
    unit_kind: UnitKind
    tags: tuple[MetricTag, ...]
    required: bool = False
    applicability: str = "whole_company"


@dataclass(frozen=True, slots=True)
class CanonicalFact:
    metric_code: str
    source_fact: SecFact
    value: Decimal
    period: PeriodResolution
    unit: UnitResolution
    revision_kind: Literal["as_reported", "amendment", "later_filing"]


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    metric_code: str
    status: ResolutionStatus
    selected: CanonicalFact | None
    considered_fact_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedValue:
    metric_code: str
    fiscal_year: int | None
    fiscal_quarter: int | None
    period_end: date | None
    value: Decimal | None
    unit: str
    status: ResolutionStatus
    derivation: str
    formula: str | None
    input_fact_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
