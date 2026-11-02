"""Explicit HTTP inputs around the unchanged F05 research contracts."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.research.trade_proposal import (
    FrozenInput, PaperBar, PaperCosts, PaperStrategy, ProposalEvidence, ProposalVersion, ResearchHorizon,
)


class ProposalCreate(FrozenInput):
    symbol: str = Field(min_length=1, max_length=20)
    evidence: ProposalEvidence
    strategy: PaperStrategy
    costs: PaperCosts
    effective_at: AwareDatetime | None = None
    change_reason: str = Field(min_length=1)
    horizon_sessions: ResearchHorizon | None = None


class ProposalRevise(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    strategy: PaperStrategy
    costs: PaperCosts
    effective_at: AwareDatetime | None = None
    change_reason: str = Field(min_length=1)


class ProposalPromote(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    owner_id: str = Field(min_length=1, max_length=128)


class ProposalRead(FrozenInput):
    status: Literal["proposed", "scheduled"]
    proposal: ProposalVersion
    setup_evaluation: dict[str, Any] | None = None
    valid_from_date: str | None = None
    valid_until_date: str | None = None
    eligibility: dict[str, Any] | None = None


class RevisionListRead(FrozenInput):
    creation_id: str
    as_of: AwareDatetime
    revisions: tuple[ProposalRead, ...]


class ProposalListRead(FrozenInput):
    as_of: AwareDatetime
    items: tuple[ProposalRead, ...]
    limit: int
    offset: int
    has_more: bool


class PaperEvaluationRequest(FrozenInput):
    decision_at: AwareDatetime
    outcome_as_of: AwareDatetime
    expected_revision_id: str | None = Field(default=None, min_length=1, max_length=36)
    horizon_sessions: ResearchHorizon | None = None
    # None reads the existing canonical owner; [] explicitly means no supplied
    # evidence. Each supplied PaperBar requires source and receipt timestamps.
    bars: tuple[PaperBar, ...] | None = Field(default=None, max_length=60)


class HorizonAssessment(FrozenInput):
    horizon_sessions: ResearchHorizon
    status: Literal["evaluated", "insufficient_evidence", "ambiguous", "unfilled"]
    insufficient_evidence: tuple[str, ...]


class PaperEvaluationRead(FrozenInput):
    status: Literal["evaluated", "insufficient_evidence", "ambiguous", "unfilled"]
    proposal: ProposalVersion
    bar_source: Literal["canonical_cache", "supplied_snapshot"]
    insufficient_evidence: tuple[str, ...]
    assessments: tuple[HorizonAssessment, ...]
    # Preserve the exact research.paper_outcome.v1 payload, including MFE/MAE,
    # Trade-R, bar receipts, limitations and its original replay_hash.
    evaluation: dict[str, Any]
    owner_limitations: tuple[str, ...]
    replay_request: PaperEvaluationRequest
    setup_evaluation: dict[str, Any] | None = None
