"""Frozen research inputs, independent of the execution and outward contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from app.research.market_policy import ResearchMarket, market_timezone, session_close


ResearchHorizon = Annotated[int, Field(ge=7, le=20, strict=True)]


class FrozenInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class EvidenceItem(FrozenInput):
    source_ref: str = Field(min_length=1)
    source_available_at: AwareDatetime
    received_at: AwareDatetime
    data_revision: str = Field(min_length=1)
    # The exact evidence used, rather than a pointer to a mutable current row.
    snapshot_json: str

    @model_validator(mode="after")
    def valid_snapshot(self):
        canonical_json(json.loads(self.snapshot_json))
        return self


class ProposalEvidence(FrozenInput):
    market: ResearchMarket = Field(default="TW", exclude_if=lambda value: value == "TW")
    as_of_trade_date: date
    cutoff: AwareDatetime
    price_basis: str = Field(min_length=1)
    items: tuple[EvidenceItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def known_at_cutoff(self):
        if self.as_of_trade_date > self.cutoff.astimezone(market_timezone(self.market)).date():
            raise ValueError("Evidence trade date is after the cutoff.")
        if any(max(item.source_available_at, item.received_at) > self.cutoff for item in self.items):
            raise ValueError("Evidence was unavailable at the frozen cutoff.")
        return self


class PaperCosts(FrozenInput):
    version: str = Field(min_length=1)
    commission_rate: float | None = Field(default=None, ge=0)
    minimum_commission: float | None = Field(default=None, ge=0)
    sell_tax_rate: float | None = Field(default=None, ge=0)
    slippage_per_share: float | None = Field(default=None, ge=0)
    short_borrow_per_share_session: float | None = Field(default=None, ge=0)
    other_cost: float | None = Field(default=None, ge=0)
    assumptions: tuple[str, ...] = ()


class PaperTarget(FrozenInput):
    price: float = Field(gt=0)
    fraction: float = Field(gt=0, le=1)


class PaperStrategy(FrozenInput):
    version: str = Field(min_length=1)
    direction: Literal[1, -1]
    mode: Literal["aggressive", "confirmed"]
    entry_rule: Literal["next_open", "at_or_above", "at_or_below"]
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    targets: tuple[PaperTarget, ...] = Field(min_length=1)
    shares: int = Field(gt=0, strict=True)
    thesis: str = Field(min_length=1)
    counter_evidence: tuple[str, ...] = ()
    # This is an input from the qualification owner, never inferred from OHLC.
    paper_eligibility: Literal["eligible", "unknown", "ineligible"] = "unknown"
    qualification_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_levels(self):
        if self.direction * (self.entry_price - self.stop_price) <= 0:
            raise ValueError("Stop must be on the adverse side of entry.")
        moves = [self.direction * (target.price - self.entry_price) for target in self.targets]
        if any(move <= 0 for move in moves) or moves != sorted(set(moves)):
            raise ValueError("Targets must be favorable and strictly ordered.")
        if abs(sum(target.fraction for target in self.targets) - 1.0) > 1e-9:
            raise ValueError("Target fractions must sum to one.")
        if self.paper_eligibility != "unknown" and not self.qualification_refs:
            raise ValueError("A paper eligibility assessment requires evidence references.")
        return self


class ProposalVersion(FrozenInput):
    contract_version: Literal["research.trade_proposal.v1"] = "research.trade_proposal.v1"
    creation_id: str
    revision_id: str
    revision: int = Field(ge=1)
    supersedes: str | None
    symbol: str = Field(min_length=1)
    market: ResearchMarket = "TW"
    evidence: ProposalEvidence
    evidence_hash: str
    strategy: PaperStrategy
    costs: PaperCosts
    recorded_at: AwareDatetime
    effective_at: AwareDatetime
    change_reason: str = Field(min_length=1)
    initial_stop_distance: float = Field(gt=0)
    initial_risk_amount: float = Field(gt=0)
    # Freeze the calendar too: later closure announcements must not silently
    # shift a previously journaled outcome window during historical replay.
    planned_trade_dates: tuple[date, ...] = Field(min_length=15, max_length=20)
    calendar_verified: bool
    # Excluding an absent additive field preserves legacy payload/evidence hashes.
    outcome_horizon_sessions: ResearchHorizon | None = Field(default=None, exclude_if=lambda value: value is None)
    # A terminal visibility event retains the original strategy and calendar.
    # Old payloads omit this field so their immutable hashes remain valid.
    deleted_at: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)
    workflow_origin: Literal["USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"] | None = Field(
        default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def valid_window(self):
        if self.deleted_at is not None and (
            self.deleted_at != self.recorded_at or self.revision < 2 or self.supersedes is None
        ):
            raise ValueError("Deletion must be a timestamped successor of an existing proposal.")
        if self.market != self.evidence.market:
            raise ValueError("Proposal market disagrees with frozen evidence.")
        if list(self.planned_trade_dates) != sorted(set(self.planned_trade_dates)):
            raise ValueError("Planned sessions must be unique and ordered.")
        if self.planned_trade_dates[0] <= self.effective_at.astimezone(market_timezone(self.market)).date():
            raise ValueError("Planned outcome sessions must follow strategy effectiveness.")
        if self.outcome_horizon_sessions is not None and len(self.planned_trade_dates) < self.outcome_horizon_sessions:
            raise ValueError("The selected outcome horizon exceeds the frozen calendar.")
        known_refs = {item.source_ref for item in self.evidence.items}
        if not set(self.strategy.qualification_refs).issubset(known_refs):
            raise ValueError("Qualification references must be part of frozen evidence.")
        return self


class PaperBar(FrozenInput):
    market: ResearchMarket = Field(default="TW", exclude_if=lambda value: value == "TW")
    symbol: str = Field(min_length=1)
    trade_date: date
    open_price: float = Field(gt=0)
    high_price: float = Field(gt=0)
    low_price: float = Field(gt=0)
    close_price: float = Field(gt=0)
    source_ref: str = Field(min_length=1)
    data_revision: str = Field(min_length=1)
    source_available_at: AwareDatetime
    received_at: AwareDatetime
    price_basis: str = Field(min_length=1)
    final: bool = True
    corporate_action: Literal["clear", "unknown", "discontinuous"] = "unknown"

    @model_validator(mode="after")
    def valid_ohlc(self):
        if self.high_price < max(self.open_price, self.low_price, self.close_price):
            raise ValueError("Inconsistent OHLC high.")
        if self.low_price > min(self.open_price, self.high_price, self.close_price):
            raise ValueError("Inconsistent OHLC low.")
        close_at = session_close(self.market, self.trade_date)
        if self.source_available_at < close_at or self.received_at < close_at:
            raise ValueError("Daily OHLC receipt precedes session close.")
        return self
