from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import math
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import CrossMarketRelation, CrossMarketRelationEvidence
from app.market.cross_market.schemas import (
    CrossMarketRelationCandidate,
    CrossMarketRelationEvidenceCandidate,
    CrossMarketRelationEvidenceRead,
    CrossMarketRelationRead,
    CrossMarketRelationRegistryRead,
    InstrumentRefRead,
)
from app.market.cross_market.types import (
    DIRECT_RELATION_TYPES,
    PRODUCTION_EVIDENCE_GRADES,
    RELATION_BUCKET_BY_TYPE,
    CrossMarketReviewStatus,
    InstrumentRef,
    taiwan_stock_ref,
)


REGISTRY_SCHEMA_VERSION = "cross_market.relations.v1"
APPROVED = CrossMarketReviewStatus.APPROVED.value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _instrument_read(
    *,
    market: str,
    instrument_type: str,
    canonical_symbol: str,
    provider_symbol: str | None,
    exchange: str | None,
    currency: str | None,
) -> InstrumentRefRead:
    return InstrumentRefRead(
        market=market,
        instrument_type=instrument_type,
        canonical_symbol=canonical_symbol,
        provider_symbol=provider_symbol,
        exchange=exchange,
        currency=currency,
    )


def _evidence_read(
    evidence: CrossMarketRelationEvidence,
) -> CrossMarketRelationEvidenceRead:
    return CrossMarketRelationEvidenceRead(
        evidence_id=evidence.id,
        source_type=evidence.source_type,
        source_grade=evidence.source_grade,
        source_label=evidence.source_label,
        source_url=evidence.source_url,
        statement=evidence.statement,
        published_at=evidence.published_at,
        verified_at=evidence.verified_at,
        content_hash=evidence.content_hash,
        is_primary=evidence.is_primary,
        review_status=evidence.review_status,
    )


def _relation_diagnostics(
    relation: CrossMarketRelation,
    *,
    approved_evidence: list[CrossMarketRelationEvidence],
) -> tuple[str, bool, list[str], list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    limitations: list[str] = []

    expected_bucket = RELATION_BUCKET_BY_TYPE.get(relation.relation_type)
    if expected_bucket is None:
        missing.append("relation_type_unsupported")
    elif relation.bucket != expected_bucket:
        missing.append("relation_bucket_mismatch")

    numerator = (
        float(relation.ratio_numerator)
        if relation.ratio_numerator is not None
        else None
    )
    denominator = (
        float(relation.ratio_denominator)
        if relation.ratio_denominator is not None
        else None
    )
    if relation.relation_type in DIRECT_RELATION_TYPES:
        if (
            numerator is None
            or denominator is None
            or not math.isfinite(numerator)
            or not math.isfinite(denominator)
            or numerator <= 0
            or denominator <= 0
        ):
            missing.append("direct_relation_ratio_invalid")
    elif numerator is not None or denominator is not None:
        missing.append("proxy_relation_ratio_must_be_null")

    if not approved_evidence:
        missing.append("relation_evidence_missing")
    if relation.confidence_tier in {"A", "B"} and not any(
        item.is_primary and item.source_grade in {"A", "B"}
        for item in approved_evidence
    ):
        missing.append("relation_primary_evidence_missing")

    if relation.confidence_tier == "D":
        limitations.append("evidence_grade_shadow_only")
    if relation.valid_from == relation.verified_at.date():
        limitations.append("historical_validity_before_verification_not_asserted")

    missing = list(dict.fromkeys(missing))
    if missing:
        return "blocked", False, missing, warnings, limitations
    if relation.confidence_tier not in PRODUCTION_EVIDENCE_GRADES:
        return "limited", False, missing, warnings, limitations
    return "ready", True, missing, warnings, limitations


def list_effective_relation_models(
    db: Session,
    *,
    target: InstrumentRef,
    as_of: date,
    available_at: datetime | None = None,
) -> list[CrossMarketRelation]:
    rows = (
        db.query(CrossMarketRelation)
        .options(joinedload(CrossMarketRelation.evidence))
        .filter(
            CrossMarketRelation.target_market == target.market,
            CrossMarketRelation.target_canonical_symbol == target.canonical_symbol,
            CrossMarketRelation.review_status == APPROVED,
            CrossMarketRelation.is_active.is_(True),
            CrossMarketRelation.valid_from <= as_of,
            or_(
                CrossMarketRelation.valid_to.is_(None),
                CrossMarketRelation.valid_to >= as_of,
            ),
        )
        .order_by(
            CrossMarketRelation.bucket.asc(),
            CrossMarketRelation.source_canonical_symbol.asc(),
            CrossMarketRelation.version.desc(),
            CrossMarketRelation.id.asc(),
        )
        .all()
    )
    # `valid_from` is effective-time governance; `verified_at` is the
    # information-availability boundary.  Filtering both prevents a historical
    # read from seeing a relation that OMI had not verified yet.
    cutoff = _utc(available_at) if available_at is not None else None
    return [
        row
        for row in rows
        if row.verified_at.date() <= as_of
        and (cutoff is None or _utc(row.verified_at) <= cutoff)
    ]


def build_relation_registry_read(
    db: Session,
    stock_id: str,
    *,
    as_of: date | None = None,
    generated_at: datetime | None = None,
    data_available_at: datetime | None = None,
) -> CrossMarketRelationRegistryRead:
    target = taiwan_stock_ref(stock_id)
    effective_date = as_of or date.today()
    built_at = generated_at or _now()
    relation_models = list_effective_relation_models(
        db,
        target=target,
        as_of=effective_date,
        available_at=data_available_at or built_at,
    )

    relations: list[CrossMarketRelationRead] = []
    aggregate_missing: list[str] = []
    aggregate_warnings: list[str] = []
    latest_verified_at: datetime | None = None
    for relation in relation_models:
        approved_evidence = sorted(
            (
                item
                for item in relation.evidence
                if item.review_status == APPROVED
                and item.verified_at.date() <= effective_date
                and _utc(item.verified_at) <= _utc(data_available_at or built_at)
            ),
            key=lambda item: (not item.is_primary, item.id),
        )
        status, decision_usable, missing, warnings, limitations = (
            _relation_diagnostics(
                relation,
                approved_evidence=approved_evidence,
            )
        )
        verified_candidates = [
            relation.verified_at,
            *(item.verified_at for item in approved_evidence),
        ]
        relation_latest_verified_at = max(verified_candidates)
        latest_verified_at = (
            relation_latest_verified_at
            if latest_verified_at is None
            else max(latest_verified_at, relation_latest_verified_at)
        )
        relations.append(
            CrossMarketRelationRead(
                relation_id=relation.id,
                relation_version=relation.version,
                source=_instrument_read(
                    market=relation.source_market,
                    instrument_type=relation.source_instrument_type,
                    canonical_symbol=relation.source_canonical_symbol,
                    provider_symbol=relation.source_provider_symbol,
                    exchange=relation.source_exchange,
                    currency=relation.source_currency,
                ),
                target=_instrument_read(
                    market=relation.target_market,
                    instrument_type=relation.target_instrument_type,
                    canonical_symbol=relation.target_canonical_symbol,
                    provider_symbol=relation.target_provider_symbol,
                    exchange=relation.target_exchange,
                    currency=relation.target_currency,
                ),
                relation_type=relation.relation_type,
                relation_subtype=relation.relation_subtype,
                bucket=relation.bucket,
                directionality=relation.directionality,
                base_weight=float(relation.base_weight),
                confidence_tier=relation.confidence_tier,
                evidence_grade=relation.evidence_grade,
                ratio_numerator=(
                    float(relation.ratio_numerator)
                    if relation.ratio_numerator is not None
                    else None
                ),
                ratio_denominator=(
                    float(relation.ratio_denominator)
                    if relation.ratio_denominator is not None
                    else None
                ),
                depositary=relation.depositary,
                listing_tier=relation.listing_tier,
                valid_from=relation.valid_from,
                valid_to=relation.valid_to,
                verified_at=relation.verified_at,
                review_status=relation.review_status,
                status=status,
                decision_usable=decision_usable,
                evidence=[_evidence_read(item) for item in approved_evidence],
                missing=missing,
                warnings=warnings,
                limitations=limitations,
            )
        )
        aggregate_missing.extend(missing)
        aggregate_warnings.extend(warnings)

    decision_usable_count = sum(item.decision_usable for item in relations)
    if not relations:
        status = "not_applicable"
        decision_usable = False
    elif decision_usable_count == len(relations):
        status = "ready"
        decision_usable = True
    elif decision_usable_count > 0:
        status = "partial"
        decision_usable = True
    else:
        status = "blocked"
        decision_usable = False

    return CrossMarketRelationRegistryRead(
        kind="cross_market_relations",
        schema_version=REGISTRY_SCHEMA_VERSION,
        status=status,
        decision_usable=decision_usable,
        target=InstrumentRefRead(**target.__dict__),
        as_of=effective_date,
        generated_at=built_at,
        relation_count=len(relations),
        relations=relations,
        missing=list(dict.fromkeys(aggregate_missing)),
        warnings=list(dict.fromkeys(aggregate_warnings)),
        source_refs=[
            {"type": "table", "name": "cross_market_relation"},
            {"type": "table", "name": "cross_market_relation_evidence"},
        ],
        freshness={
            "status": "current" if relations else "not_applicable",
            "as_of": effective_date,
            "latest_verified_at": latest_verified_at,
            "market_data_included": False,
            "semantics": "relation_registry_governance_only",
        },
    )


def _validated_ref(value: InstrumentRefRead) -> InstrumentRef:
    return InstrumentRef.create(
        market=value.market,
        instrument_type=value.instrument_type,
        symbol=value.canonical_symbol,
        provider_symbol=value.provider_symbol,
        exchange=value.exchange,
        currency=value.currency,
    )


def _evidence_hash(value: CrossMarketRelationEvidenceCandidate) -> str:
    if value.content_hash:
        normalized = value.content_hash.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("evidence content_hash must be a SHA-256 hex digest")
        return normalized
    return hashlib.sha256(
        f"{value.source_url}|{value.statement}".encode("utf-8")
    ).hexdigest()


def validate_candidate(
    candidate: CrossMarketRelationCandidate,
    *,
    require_approvable_evidence: bool = False,
) -> None:
    _validated_ref(candidate.source)
    _validated_ref(candidate.target)
    expected_bucket = RELATION_BUCKET_BY_TYPE.get(candidate.relation_type)
    if expected_bucket is None:
        raise ValueError(f"unsupported relation_type: {candidate.relation_type}")
    if candidate.bucket != expected_bucket:
        raise ValueError(
            f"relation bucket must be {expected_bucket} for {candidate.relation_type}"
        )
    if candidate.confidence_tier not in {"A", "B", "C", "D"}:
        raise ValueError("confidence_tier must be A, B, C, or D")
    if candidate.valid_to is not None and candidate.valid_to < candidate.valid_from:
        raise ValueError("valid_to cannot be earlier than valid_from")
    if candidate.relation_type in DIRECT_RELATION_TYPES:
        if (
            candidate.ratio_numerator is None
            or candidate.ratio_denominator is None
            or not math.isfinite(candidate.ratio_numerator)
            or not math.isfinite(candidate.ratio_denominator)
            or candidate.ratio_numerator <= 0
            or candidate.ratio_denominator <= 0
        ):
            raise ValueError("direct relation requires positive ratio values")
    elif candidate.ratio_numerator is not None or candidate.ratio_denominator is not None:
        raise ValueError("proxy relation ratio values must be null")

    for evidence in candidate.evidence:
        if evidence.source_grade not in {"A", "B", "C", "D"}:
            raise ValueError("evidence source_grade must be A, B, C, or D")
        if not evidence.source_url.startswith("https://"):
            raise ValueError("evidence source_url must use https")
        _evidence_hash(evidence)

    if require_approvable_evidence:
        if not candidate.evidence:
            raise ValueError("approved relation requires evidence")
        if candidate.confidence_tier in {"A", "B"} and not any(
            item.is_primary and item.source_grade in {"A", "B"}
            for item in candidate.evidence
        ):
            raise ValueError("A/B relation requires primary A/B evidence")


def candidate_from_model(
    relation: CrossMarketRelation,
) -> CrossMarketRelationCandidate:
    return CrossMarketRelationCandidate(
        source=_instrument_read(
            market=relation.source_market,
            instrument_type=relation.source_instrument_type,
            canonical_symbol=relation.source_canonical_symbol,
            provider_symbol=relation.source_provider_symbol,
            exchange=relation.source_exchange,
            currency=relation.source_currency,
        ),
        target=_instrument_read(
            market=relation.target_market,
            instrument_type=relation.target_instrument_type,
            canonical_symbol=relation.target_canonical_symbol,
            provider_symbol=relation.target_provider_symbol,
            exchange=relation.target_exchange,
            currency=relation.target_currency,
        ),
        relation_type=relation.relation_type,
        relation_subtype=relation.relation_subtype,
        bucket=relation.bucket,
        directionality=relation.directionality,
        base_weight=float(relation.base_weight),
        confidence_tier=relation.confidence_tier,
        evidence_grade=relation.evidence_grade,
        ratio_numerator=(
            float(relation.ratio_numerator)
            if relation.ratio_numerator is not None
            else None
        ),
        ratio_denominator=(
            float(relation.ratio_denominator)
            if relation.ratio_denominator is not None
            else None
        ),
        depositary=relation.depositary,
        listing_tier=relation.listing_tier,
        valid_from=relation.valid_from,
        valid_to=relation.valid_to,
        verified_at=relation.verified_at,
        evidence=[
            CrossMarketRelationEvidenceCandidate(
                source_type=item.source_type,
                source_grade=item.source_grade,
                source_label=item.source_label,
                source_url=item.source_url,
                statement=item.statement,
                published_at=item.published_at,
                verified_at=item.verified_at,
                content_hash=item.content_hash,
                is_primary=item.is_primary,
            )
            for item in relation.evidence
            if item.review_status not in {
                CrossMarketReviewStatus.REJECTED.value,
                CrossMarketReviewStatus.REVOKED.value,
            }
        ],
    )


def find_approved_overlaps(
    db: Session,
    candidate: CrossMarketRelationCandidate,
    *,
    exclude_relation_ids: set[int] | None = None,
) -> list[CrossMarketRelation]:
    exclude_ids = exclude_relation_ids or set()
    query = db.query(CrossMarketRelation).filter(
        CrossMarketRelation.source_canonical_symbol
        == candidate.source.canonical_symbol,
        CrossMarketRelation.target_canonical_symbol
        == candidate.target.canonical_symbol,
        CrossMarketRelation.relation_type == candidate.relation_type,
        CrossMarketRelation.review_status == APPROVED,
        CrossMarketRelation.is_active.is_(True),
        or_(
            CrossMarketRelation.valid_to.is_(None),
            CrossMarketRelation.valid_to >= candidate.valid_from,
        ),
    )
    if candidate.valid_to is not None:
        query = query.filter(CrossMarketRelation.valid_from <= candidate.valid_to)
    if exclude_ids:
        query = query.filter(CrossMarketRelation.id.notin_(exclude_ids))
    return query.order_by(CrossMarketRelation.valid_from.asc()).all()


def decimal_or_none(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
