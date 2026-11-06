"""Explicit HTTP inputs around the unchanged F05 research contracts."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field
from app.research.market_policy import ResearchMarket

from app.research.trade_proposal import (
    FrozenInput, PaperBar, PaperCosts, PaperStrategy, ProposalEvidence, ProposalVersion, ResearchHorizon,
)


class ProposalCreate(FrozenInput):
    market: ResearchMarket = "TW"
    symbol: str = Field(min_length=1, max_length=20)
    evidence: ProposalEvidence
    strategy: PaperStrategy
    costs: PaperCosts
    effective_at: AwareDatetime | None = None
    change_reason: str = Field(min_length=1)
    horizon_sessions: ResearchHorizon | None = None
    workflow_origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] | None = None


class ProposalRevise(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    strategy: PaperStrategy
    costs: PaperCosts
    effective_at: AwareDatetime | None = None
    change_reason: str = Field(min_length=1)


class ProposalPromote(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    owner_id: str = Field(min_length=1, max_length=128)


class ProposalDelete(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)


class ProposalMove(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    origin: Literal["AI_NOMINATION", "OMI_SCREEN"]


class ProposalStage(FrozenInput):
    expected_revision_id: str = Field(min_length=1, max_length=36)
    client_intent_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_:.-]+$")
    overrides: dict[str, Any] = Field(default_factory=dict)


class ProposalDeleteRead(FrozenInput):
    creation_id: str
    revision_id: str
    deleted_at: AwareDatetime
    status: Literal["deleted"] = "deleted"


class ProposalRead(FrozenInput):
    workflow_origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] | None = None
    currency: Literal["TWD", "USD"] = "TWD"
    promotion_supported: bool = True
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


class ProposalSummaryRead(FrozenInput):
    creation_id: str
    revision_id: str
    revision: int
    market: ResearchMarket
    symbol: str
    stock_name: str | None
    direction: Literal["long", "short"]
    status: Literal["proposed", "scheduled"]
    workflow_origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] | None
    as_of_trade_date: str
    cutoff: AwareDatetime
    recorded_at: AwareDatetime
    effective_at: AwareDatetime
    assessment_status: str | None
    reason_codes: tuple[str, ...]
    evidence_hash: str


class ProposalSummaryListRead(FrozenInput):
    projection: Literal["research.proposal_list.summary.v1"] = "research.proposal_list.summary.v1"
    evidence_included: Literal[False] = False
    execution_ready: Literal[False] = False
    as_of: AwareDatetime
    items: tuple[ProposalSummaryRead, ...]
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
