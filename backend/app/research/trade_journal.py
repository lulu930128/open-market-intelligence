"""Append-only journal. Caller owns Session.begin()/commit()/rollback().

No engine, schema bootstrap, provider read, or implicit transaction is created.
The additive migration owns the table and SQLite immutability triggers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, func, insert, select
from sqlalchemy.orm import Session

from app.research.market_policy import ResearchMarket, frozen_sessions
from app.research.trade_proposal import (
    PaperCosts, PaperStrategy, ProposalEvidence, ProposalVersion, content_hash, utc_text,
)


metadata = MetaData()


class ProposalDeletedError(LookupError):
    """The proposal has been removed at the requested knowledge time."""


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
    market: ResearchMarket = "TW", workflow_origin: str | None = None,
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
    dates, verified = frozen_sessions(market, effective_at, max(15, horizon_sessions or 15))
    return _insert(db, ProposalVersion(
        creation_id=creation_id or str(uuid4()), revision_id=str(uuid4()), revision=1, supersedes=None,
        symbol=symbol, market=market, evidence=evidence, evidence_hash=content_hash(evidence.model_dump(mode="json")),
        strategy=strategy, costs=costs, recorded_at=recorded, effective_at=effective_at,
        change_reason=change_reason, initial_stop_distance=distance,
        initial_risk_amount=distance * strategy.shares,
        planned_trade_dates=dates,
        outcome_horizon_sessions=horizon_sessions,
        calendar_verified=verified,
        workflow_origin=workflow_origin,
    ))


def list_versions(db: Session, *, creation_id: str, as_of: datetime) -> tuple[ProposalVersion, ...]:
    """Only versions already recorded by the requested knowledge time are visible."""
    rows = db.execute(select(proposal_versions).where(
        proposal_versions.c.creation_id == creation_id,
        proposal_versions.c.recorded_at <= utc_text(as_of),
    ).order_by(proposal_versions.c.revision)).all()
    return tuple(_decode(row) for row in rows)


def workflow_origin(version: ProposalVersion) -> str | None:
    if version.workflow_origin is not None:
        return version.workflow_origin
    for item in version.evidence.items:
        if item.source_ref in {"research.stock_nomination.v1", "research.us_watchlist_nomination.v1"}:
            snapshot = json.loads(item.snapshot_json)
            request = snapshot.get("request") if isinstance(snapshot, dict) else None
            origin = request.get("nomination_origin") if isinstance(request, dict) else None
            return origin if isinstance(origin, str) and origin in {"USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"} else None
    return None


def list_proposal_heads(db: Session, *, as_of: datetime, limit: int, offset: int,
                        market: ResearchMarket | None = None, origin: str | None = None,
                        direction: str | None = None, ai_scope: bool = False) -> tuple[ProposalVersion, ...]:
    """Bounded latest-known revisions; scheduled heads remain visible."""
    heads = select(proposal_versions.c.creation_id,
                   func.max(proposal_versions.c.revision).label("revision")).where(
        proposal_versions.c.recorded_at <= utc_text(as_of)).group_by(proposal_versions.c.creation_id).subquery()
    query = select(proposal_versions).join(heads,
        (proposal_versions.c.creation_id == heads.c.creation_id)
        & (proposal_versions.c.revision == heads.c.revision))
    payload = proposal_versions.c.payload_json
    # Filter after choosing the head, before pagination. An older visible
    # revision must never replace its terminal deletion event.
    query = query.where(func.json_extract(payload, "$.deleted_at").is_(None))
    if market:
        query = query.where(func.json_extract(payload, "$.market") == market)
    if direction:
        query = query.where(func.json_extract(payload, "$.strategy.direction") == (1 if direction == "long" else -1))
    if origin or ai_scope:
        evidence_items = func.json_each(payload, "$.evidence.items").table_valued("key", "value")
        snapshot = func.json_extract(evidence_items.c.value, "$.snapshot_json")
        original = select(func.json_extract(snapshot, "$.request.nomination_origin")).select_from(evidence_items).where(
            func.json_extract(evidence_items.c.value, "$.source_ref").in_(
                ("research.stock_nomination.v1", "research.us_watchlist_nomination.v1"))).limit(1).scalar_subquery()
        category = func.coalesce(func.json_extract(payload, "$.workflow_origin"), original)
        if origin:
            query = query.where(category == origin)
        if ai_scope:
            query = query.where(category.in_(("AI_NOMINATION", "OMI_SCREEN")))
    rows = db.execute(query.order_by(proposal_versions.c.recorded_at.desc(),
        proposal_versions.c.creation_id).limit(limit).offset(offset)).all()
    return tuple(_decode(row) for row in rows)


def proposal_at(db: Session, *, creation_id: str, decision_at: datetime) -> ProposalVersion:
    versions = list_versions(db, creation_id=creation_id, as_of=decision_at)
    if versions and versions[-1].deleted_at is not None:
        raise ProposalDeletedError("The research proposal was deleted.")
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
    if previous.deleted_at is not None:
        raise ProposalDeletedError("The research proposal was deleted.")
    utc_text(effective_at)
    if previous.revision_id != expected_revision_id:
        raise ValueError("Revision conflict: expected_revision_id is no longer the journal head.")
    if effective_at < recorded or effective_at <= previous.effective_at:
        raise ValueError("A revision must take effect prospectively after the previous version.")
    if strategy.direction != previous.strategy.direction:
        raise ValueError("Changing direction requires a separate proposal.")
    # Frozen evidence and original 1R are inherited, never recalculated on revision.
    values = previous.model_dump()
    dates, verified = frozen_sessions(previous.market, effective_at, max(15, previous.outcome_horizon_sessions or 15))
    values.update(revision_id=str(uuid4()), revision=previous.revision + 1,
                  supersedes=previous.revision_id, strategy=strategy, costs=costs,
                  recorded_at=recorded, effective_at=effective_at, change_reason=change_reason,
                  planned_trade_dates=dates,
                  calendar_verified=verified)
    return _insert(db, ProposalVersion.model_validate(values))


def move_proposal(db: Session, *, creation_id: str, expected_revision_id: str,
                  origin: str, now: datetime, ai_scope: bool = False) -> ProposalVersion:
    versions = list_versions(db, creation_id=creation_id, as_of=now)
    if not versions:
        raise LookupError("Unknown proposal.")
    previous = versions[-1]
    if ai_scope and workflow_origin(previous) not in {"AI_NOMINATION", "OMI_SCREEN"}:
        raise PermissionError("RESEARCH_OUTSIDE_AI_SCOPE")
    if previous.deleted_at is not None:
        raise ProposalDeletedError("The research proposal was deleted.")
    if previous.revision_id != expected_revision_id:
        raise ValueError("Revision conflict: expected_revision_id is no longer the journal head.")
    if workflow_origin(previous) == origin:
        return previous
    values = previous.model_dump()
    values.update(revision_id=str(uuid4()), revision=previous.revision + 1,
                  supersedes=previous.revision_id, recorded_at=now, workflow_origin=origin,
                  change_reason=f"Moved research to {origin}")
    return _insert(db, ProposalVersion.model_validate(values))


def delete_proposal(db: Session, *, creation_id: str, expected_revision_id: str,
                    now: datetime) -> ProposalVersion:
    """Append a terminal deletion marker; no historical row is changed.

    The existing unique supersedes/revision constraints arbitrate revise/delete
    races. Repeating the same deletion intent returns its original marker.
    Strategy effectiveness stays frozen; deleted_at governs visibility.
    """
    versions = list_versions(db, creation_id=creation_id, as_of=now)
    if not versions:
        raise LookupError("Unknown proposal.")
    previous = versions[-1]
    if previous.deleted_at is not None and previous.supersedes == expected_revision_id:
        return previous
    if previous.revision_id != expected_revision_id or previous.deleted_at is not None:
        raise ValueError("Revision conflict: expected_revision_id is no longer the journal head.")
    values = previous.model_dump()
    values.update(revision_id=str(uuid4()), revision=previous.revision + 1,
                  supersedes=previous.revision_id, recorded_at=now, deleted_at=now,
                  change_reason="User deleted research proposal")
    return _insert(db, ProposalVersion.model_validate(values))
