"""Append-only journal. Caller owns Session.begin()/commit()/rollback().

No engine, schema bootstrap, provider read, or implicit transaction is created.
The additive migration owns the table and SQLite immutability triggers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, func, insert, select
from sqlalchemy.orm import Session

from app.market.trading_calendar import TAIWAN_TZ, has_taiwan_calendar_year
from app.research.trade_proposal import (
    PaperCosts, PaperStrategy, ProposalEvidence, ProposalVersion, content_hash, utc_text,
)


metadata = MetaData()
proposal_versions = Table(
    "research_trade_proposal_version", metadata,
    Column("revision_id", String(36), primary_key=True),
    Column("creation_id", String(36), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("supersedes", String(36), unique=True),
    Column("recorded_at", String(32), nullable=False),
    Column("effective_at", String(32), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    UniqueConstraint("creation_id", "revision", name="uq_research_proposal_revision"),
)


def _decode(row) -> ProposalVersion:
    version = ProposalVersion.model_validate_json(row.payload_json)
    if content_hash(version.model_dump(mode="json")) != row.payload_hash:
        raise ValueError("Journal payload integrity check failed.")
    if version.evidence_hash != content_hash(version.evidence.model_dump(mode="json")):
        raise ValueError("Journal evidence integrity check failed.")
    return version


def _insert(db: Session, version: ProposalVersion) -> ProposalVersion:
    db.execute(insert(proposal_versions).values(
        revision_id=version.revision_id, creation_id=version.creation_id,
        revision=version.revision, supersedes=version.supersedes,
        recorded_at=utc_text(version.recorded_at), effective_at=utc_text(version.effective_at),
        payload_json=version.model_dump_json(), payload_hash=content_hash(version.model_dump(mode="json")),
    ))
    return version


def create_proposal(
    db: Session, *, symbol: str, evidence: ProposalEvidence, strategy: PaperStrategy,
    costs: PaperCosts, effective_at: datetime, change_reason: str,
    now: datetime | None = None, creation_id: str | None = None, horizon_sessions: int | None = None,
) -> ProposalVersion:
    """Explicit write entry; ``now`` is injectable only for historical fixtures."""
    recorded = now or datetime.now(timezone.utc)
    utc_text(recorded)
    utc_text(effective_at)
    if effective_at < recorded or evidence.cutoff > recorded:
        raise ValueError("Creation cannot backdate effectiveness or use future evidence.")
    if horizon_sessions is not None and (type(horizon_sessions) is not int or not 7 <= horizon_sessions <= 20):
        raise ValueError("Outcome horizon must be 7 to 20 trading sessions.")
    distance = abs(strategy.entry_price - strategy.stop_price)
    from app.watchlists.radar_outcome_v2_service import trading_dates_after
    anchor = effective_at.astimezone(TAIWAN_TZ).date()
    dates = tuple(trading_dates_after(anchor, max(15, horizon_sessions or 15)))
    return _insert(db, ProposalVersion(
        creation_id=creation_id or str(uuid4()), revision_id=str(uuid4()), revision=1, supersedes=None,
        symbol=symbol, evidence=evidence, evidence_hash=content_hash(evidence.model_dump(mode="json")),
        strategy=strategy, costs=costs, recorded_at=recorded, effective_at=effective_at,
        change_reason=change_reason, initial_stop_distance=distance,
        initial_risk_amount=distance * strategy.shares,
        planned_trade_dates=dates,
        outcome_horizon_sessions=horizon_sessions,
        calendar_verified=all(has_taiwan_calendar_year(day.year) for day in (anchor, *dates)),
    ))


def list_versions(db: Session, *, creation_id: str, as_of: datetime) -> tuple[ProposalVersion, ...]:
    """Only versions already recorded by the requested knowledge time are visible."""
    rows = db.execute(select(proposal_versions).where(
        proposal_versions.c.creation_id == creation_id,
        proposal_versions.c.recorded_at <= utc_text(as_of),
    ).order_by(proposal_versions.c.revision)).all()
    return tuple(_decode(row) for row in rows)


def list_proposal_heads(db: Session, *, as_of: datetime, limit: int, offset: int) -> tuple[ProposalVersion, ...]:
    """Bounded latest-known revisions; scheduled heads remain visible."""
    heads = select(proposal_versions.c.creation_id,
                   func.max(proposal_versions.c.revision).label("revision")).where(
        proposal_versions.c.recorded_at <= utc_text(as_of)).group_by(proposal_versions.c.creation_id).subquery()
    rows = db.execute(select(proposal_versions).join(heads,
        (proposal_versions.c.creation_id == heads.c.creation_id)
        & (proposal_versions.c.revision == heads.c.revision)).order_by(
        proposal_versions.c.recorded_at.desc(), proposal_versions.c.creation_id).limit(limit).offset(offset)).all()
    return tuple(_decode(row) for row in rows)


def proposal_at(db: Session, *, creation_id: str, decision_at: datetime) -> ProposalVersion:
    versions = list_versions(db, creation_id=creation_id, as_of=decision_at)
    active = [version for version in versions if version.effective_at <= decision_at]
    if not active:
        raise LookupError("No proposal version was effective and known at decision_at.")
    return active[-1]


def revise_proposal(
    db: Session, *, creation_id: str, expected_revision_id: str,
    strategy: PaperStrategy, costs: PaperCosts, effective_at: datetime,
    change_reason: str, now: datetime | None = None,
) -> ProposalVersion:
    recorded = now or datetime.now(timezone.utc)
    versions = list_versions(db, creation_id=creation_id, as_of=recorded)
    if not versions:
        raise LookupError("Unknown proposal.")
    previous = versions[-1]
    utc_text(effective_at)
    if previous.revision_id != expected_revision_id:
        raise ValueError("Revision conflict: expected_revision_id is no longer the journal head.")
    if effective_at < recorded or effective_at <= previous.effective_at:
        raise ValueError("A revision must take effect prospectively after the previous version.")
    if strategy.direction != previous.strategy.direction:
        raise ValueError("Changing direction requires a separate proposal.")
    # Frozen evidence and original 1R are inherited, never recalculated on revision.
    values = previous.model_dump()
    from app.watchlists.radar_outcome_v2_service import trading_dates_after
    anchor = effective_at.astimezone(TAIWAN_TZ).date()
    dates = tuple(trading_dates_after(anchor, max(15, previous.outcome_horizon_sessions or 15)))
    values.update(revision_id=str(uuid4()), revision=previous.revision + 1,
                  supersedes=previous.revision_id, strategy=strategy, costs=costs,
                  recorded_at=recorded, effective_at=effective_at, change_reason=change_reason,
                  planned_trade_dates=dates,
                  calendar_verified=all(has_taiwan_calendar_year(day.year) for day in (anchor, *dates)))
    return _insert(db, ProposalVersion.model_validate(values))
