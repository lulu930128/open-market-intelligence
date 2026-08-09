from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.models import CrossMarketRelation, CrossMarketRelationEvidence
from app.db.session import SessionLocal
from app.market.cross_market.relation_store import (
    APPROVED,
    _evidence_hash,
    candidate_from_model,
    decimal_or_none,
    find_approved_overlaps,
    validate_candidate,
)
from app.market.cross_market.schemas import CrossMarketRelationCandidate
from app.market.cross_market.types import CrossMarketReviewStatus


def create_relation_candidate(
    db: Session,
    candidate: CrossMarketRelationCandidate,
    *,
    actor: str,
    reason: str,
) -> CrossMarketRelation:
    validate_candidate(candidate)
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")

    source = candidate.source
    target = candidate.target
    next_version = int(
        db.query(func.max(CrossMarketRelation.version))
        .filter(
            CrossMarketRelation.source_canonical_symbol == source.canonical_symbol,
            CrossMarketRelation.target_canonical_symbol == target.canonical_symbol,
            CrossMarketRelation.relation_type == candidate.relation_type,
        )
        .scalar()
        or 0
    ) + 1
    relation = CrossMarketRelation(
        source_market=source.market,
        source_instrument_type=source.instrument_type,
        source_canonical_symbol=source.canonical_symbol,
        source_provider_symbol=source.provider_symbol,
        source_exchange=source.exchange,
        source_currency=source.currency,
        target_market=target.market,
        target_instrument_type=target.instrument_type,
        target_canonical_symbol=target.canonical_symbol,
        target_provider_symbol=target.provider_symbol,
        target_exchange=target.exchange,
        target_currency=target.currency,
        relation_type=candidate.relation_type,
        relation_subtype=candidate.relation_subtype,
        bucket=candidate.bucket,
        directionality=candidate.directionality,
        base_weight=decimal_or_none(candidate.base_weight),
        confidence_tier=candidate.confidence_tier,
        evidence_grade=candidate.evidence_grade,
        ratio_numerator=decimal_or_none(candidate.ratio_numerator),
        ratio_denominator=decimal_or_none(candidate.ratio_denominator),
        depositary=candidate.depositary,
        listing_tier=candidate.listing_tier,
        valid_from=candidate.valid_from,
        valid_to=candidate.valid_to,
        verified_at=candidate.verified_at,
        review_status=CrossMarketReviewStatus.CANDIDATE.value,
        is_active=False,
        version=next_version,
        created_by=actor,
        change_reason=reason,
    )
    relation.evidence = [
        CrossMarketRelationEvidence(
            source_type=item.source_type,
            source_grade=item.source_grade,
            source_label=item.source_label,
            source_url=item.source_url,
            statement=item.statement,
            published_at=item.published_at,
            verified_at=item.verified_at,
            content_hash=_evidence_hash(item),
            is_primary=item.is_primary,
            review_status=CrossMarketReviewStatus.CANDIDATE.value,
            created_by=actor,
        )
        for item in candidate.evidence
    ]
    try:
        db.add(relation)
        db.commit()
        db.refresh(relation)
        return relation
    except Exception:
        db.rollback()
        raise


def approve_relation(
    db: Session,
    relation_id: int,
    *,
    actor: str,
    reason: str,
    supersedes_relation_id: int | None = None,
) -> CrossMarketRelation:
    relation = (
        db.query(CrossMarketRelation)
        .options(joinedload(CrossMarketRelation.evidence))
        .filter(CrossMarketRelation.id == relation_id)
        .one_or_none()
    )
    if relation is None:
        raise ValueError(f"relation not found: {relation_id}")
    if relation.review_status != CrossMarketReviewStatus.CANDIDATE.value:
        raise ValueError("only candidate relation can be approved")
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")

    candidate = candidate_from_model(relation)
    validate_candidate(candidate, require_approvable_evidence=True)
    reviewed_at = datetime.now(timezone.utc)
    excluded_ids = {relation.id}
    superseded: CrossMarketRelation | None = None
    if supersedes_relation_id is not None:
        superseded = db.get(CrossMarketRelation, supersedes_relation_id)
        if superseded is None:
            raise ValueError(f"superseded relation not found: {supersedes_relation_id}")
        if superseded.review_status != APPROVED or not superseded.is_active:
            raise ValueError("superseded relation must be active and approved")
        if (
            superseded.source_canonical_symbol
            != relation.source_canonical_symbol
            or superseded.target_canonical_symbol
            != relation.target_canonical_symbol
            or superseded.relation_type != relation.relation_type
        ):
            raise ValueError("superseded relation identity must match candidate")
        if superseded.valid_from >= relation.valid_from:
            raise ValueError("superseding relation must start after the prior version")
        superseded.valid_to = relation.valid_from - timedelta(days=1)
        superseded.reviewed_by = actor
        superseded.reviewed_at = reviewed_at
        superseded.change_reason = (
            f"{superseded.change_reason}; superseded by relation {relation.id}: {reason}"
        )
        excluded_ids.add(superseded.id)

    overlaps = find_approved_overlaps(
        db,
        candidate,
        exclude_relation_ids=excluded_ids,
    )
    if overlaps:
        overlap_ids = ",".join(str(item.id) for item in overlaps)
        db.rollback()
        raise ValueError(f"approved relation validity overlaps: {overlap_ids}")

    relation.review_status = APPROVED
    relation.is_active = True
    relation.reviewed_by = actor
    relation.reviewed_at = reviewed_at
    relation.change_reason = reason
    for evidence in relation.evidence:
        if evidence.review_status == CrossMarketReviewStatus.CANDIDATE.value:
            evidence.review_status = APPROVED
            evidence.reviewed_by = actor
            evidence.reviewed_at = reviewed_at
    try:
        db.commit()
        db.refresh(relation)
        return relation
    except Exception:
        db.rollback()
        raise


def reject_relation(
    db: Session,
    relation_id: int,
    *,
    actor: str,
    reason: str,
) -> CrossMarketRelation:
    relation = db.get(CrossMarketRelation, relation_id)
    if relation is None:
        raise ValueError(f"relation not found: {relation_id}")
    if relation.review_status != CrossMarketReviewStatus.CANDIDATE.value:
        raise ValueError("only candidate relation can be rejected")
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    relation.review_status = CrossMarketReviewStatus.REJECTED.value
    relation.is_active = False
    relation.reviewed_by = actor
    relation.reviewed_at = datetime.now(timezone.utc)
    relation.change_reason = reason
    try:
        db.commit()
        db.refresh(relation)
        return relation
    except Exception:
        db.rollback()
        raise


def disable_relation(
    db: Session,
    relation_id: int,
    *,
    actor: str,
    reason: str,
) -> CrossMarketRelation:
    relation = db.get(CrossMarketRelation, relation_id)
    if relation is None:
        raise ValueError(f"relation not found: {relation_id}")
    if relation.review_status != APPROVED or not relation.is_active:
        raise ValueError("only active approved relation can be disabled")
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    relation.review_status = CrossMarketReviewStatus.REVOKED.value
    relation.is_active = False
    relation.reviewed_by = actor
    relation.reviewed_at = datetime.now(timezone.utc)
    relation.change_reason = reason
    try:
        db.commit()
        db.refresh(relation)
        return relation
    except Exception:
        db.rollback()
        raise


def validate_registry(db: Session) -> dict[str, Any]:
    relations = (
        db.query(CrossMarketRelation)
        .options(joinedload(CrossMarketRelation.evidence))
        .order_by(CrossMarketRelation.id.asc())
        .all()
    )
    issues: list[dict[str, Any]] = []
    approved_active = [
        item for item in relations if item.review_status == APPROVED and item.is_active
    ]
    for relation in relations:
        try:
            validate_candidate(
                candidate_from_model(relation),
                require_approvable_evidence=(
                    relation.review_status == APPROVED and relation.is_active
                ),
            )
        except ValueError as exc:
            issues.append(
                {
                    "relation_id": relation.id,
                    "code": "relation_contract_invalid",
                    "detail": str(exc),
                }
            )
    for index, relation in enumerate(approved_active):
        candidate = candidate_from_model(relation)
        for other in approved_active[index + 1 :]:
            if (
                relation.source_canonical_symbol
                != other.source_canonical_symbol
                or relation.target_canonical_symbol
                != other.target_canonical_symbol
                or relation.relation_type != other.relation_type
            ):
                continue
            if (
                relation.valid_to is None
                or relation.valid_to >= other.valid_from
            ) and (other.valid_to is None or other.valid_to >= relation.valid_from):
                issues.append(
                    {
                        "relation_id": relation.id,
                        "other_relation_id": other.id,
                        "code": "relation_validity_overlap",
                        "detail": (
                            f"{candidate.source.canonical_symbol} -> "
                            f"{candidate.target.canonical_symbol}"
                        ),
                    }
                )
    return {
        "status": "ready" if not issues else "blocked",
        "relation_count": len(relations),
        "approved_active_count": len(approved_active),
        "issue_count": len(issues),
        "issues": issues,
    }


def _read_candidate(path: Path) -> CrossMarketRelationCandidate:
    return CrossMarketRelationCandidate.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trusted cross-market relation registry maintenance.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("list")

    create = subparsers.add_parser("create-candidate")
    create.add_argument("--input", required=True, type=Path)
    create.add_argument("--actor", required=True)
    create.add_argument("--reason", required=True)

    for command in ("approve", "reject", "disable"):
        action = subparsers.add_parser(command)
        action.add_argument("relation_id", type=int)
        action.add_argument("--actor", required=True)
        action.add_argument("--reason", required=True)
        if command == "approve":
            action.add_argument("--supersedes-relation-id", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with SessionLocal() as db:
        if args.command == "validate":
            payload = validate_registry(db)
        elif args.command == "list":
            rows = db.query(CrossMarketRelation).order_by(CrossMarketRelation.id).all()
            payload = {
                "relation_count": len(rows),
                "relations": [
                    {
                        "id": row.id,
                        "source": row.source_canonical_symbol,
                        "target": row.target_canonical_symbol,
                        "relation_type": row.relation_type,
                        "valid_from": row.valid_from.isoformat(),
                        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                        "review_status": row.review_status,
                        "is_active": row.is_active,
                        "version": row.version,
                        "created_by": row.created_by,
                        "reviewed_by": row.reviewed_by,
                        "reviewed_at": row.reviewed_at,
                        "change_reason": row.change_reason,
                    }
                    for row in rows
                ],
            }
        elif args.command == "create-candidate":
            row = create_relation_candidate(
                db,
                _read_candidate(args.input),
                actor=args.actor,
                reason=args.reason,
            )
            payload = {"status": "candidate", "relation_id": row.id}
        elif args.command == "approve":
            row = approve_relation(
                db,
                args.relation_id,
                actor=args.actor,
                reason=args.reason,
                supersedes_relation_id=args.supersedes_relation_id,
            )
            payload = {"status": row.review_status, "relation_id": row.id}
        elif args.command == "reject":
            row = reject_relation(
                db,
                args.relation_id,
                actor=args.actor,
                reason=args.reason,
            )
            payload = {"status": row.review_status, "relation_id": row.id}
        else:
            row = disable_relation(
                db,
                args.relation_id,
                actor=args.actor,
                reason=args.reason,
            )
            payload = {"status": row.review_status, "relation_id": row.id}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
