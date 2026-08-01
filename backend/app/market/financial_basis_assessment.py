from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialBasisAssessment,
)


BASIS_ASSESSMENT_VERSION = "omi.tw-financial-basis-assessment.v1"
BASIS_ASSESSMENT_PARSER_VERSION = "tw-fin-basis-assessment-v1"
TRUSTED_RELIABILITY_LEVELS = frozenset(
    {"official", "regulated_filing", "verified_official_mirror"}
)


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("basis-assessment timestamps must include a timezone offset")
    return value.astimezone(timezone.utc)


class BasisAssessmentDocument(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1)
    description: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash_status: Literal["verified_source_bytes"]


class BasisAssessmentObservation(BaseModel):
    observation_code: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    document_ids: tuple[str, ...] = Field(min_length=1)


class TaiwanFinancialBasisAssessmentPackage(BaseModel):
    package_version: Literal["omi.tw-financial-basis-assessment.v1"]
    package_id: str = Field(min_length=1, max_length=160)
    approval_scope: Literal["clone_only", "production"]
    review_status: Literal["approved"]
    reviewer: str = Field(min_length=1, max_length=160)
    reviewed_at: datetime
    known_at: datetime
    stock_id: str = Field(min_length=1, max_length=20)
    normalization_mode: Literal["current_comparable", "as_reported_as_of"]
    assessment_type: Literal["accounting_basis_transition"]
    outcome: Literal["blocked", "resolved", "revoked"]
    effective_date: date
    issue_code: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=4_000)
    resolution_requirements: tuple[str, ...]
    evidence_source_name: str = Field(min_length=1, max_length=120)
    documents: tuple[BasisAssessmentDocument, ...] = Field(min_length=1)
    observations: tuple[BasisAssessmentObservation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_package(self) -> "TaiwanFinancialBasisAssessmentPackage":
        _utc_timestamp(self.reviewed_at)
        _utc_timestamp(self.known_at)
        if self.reviewed_at < self.known_at:
            raise ValueError("reviewed_at cannot precede known_at")
        if self.outcome == "blocked" and not self.resolution_requirements:
            raise ValueError("blocked assessment requires resolution requirements")
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("basis-assessment documents must be unique")
        known_documents = set(document_ids)
        for observation in self.observations:
            missing = set(observation.document_ids) - known_documents
            if missing:
                raise ValueError(
                    "basis-assessment observation references unknown documents: "
                    f"{sorted(missing)}"
                )
        return self


def canonical_basis_assessment_json(
    package: TaiwanFinancialBasisAssessmentPackage,
) -> str:
    return json.dumps(
        package.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def basis_assessment_package_hash(
    package: TaiwanFinancialBasisAssessmentPackage,
) -> str:
    return hashlib.sha256(
        canonical_basis_assessment_json(package).encode("utf-8")
    ).hexdigest()


def apply_financial_basis_assessment(
    db: Session,
    *,
    package: TaiwanFinancialBasisAssessmentPackage,
    apply: bool,
) -> dict[str, Any]:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == package.evidence_source_name)
        .one_or_none()
    )
    if source is None:
        raise ValueError(
            "basis-assessment evidence source is not registered: "
            f"{package.evidence_source_name}"
        )
    if source.reliability_level not in TRUSTED_RELIABILITY_LEVELS:
        raise ValueError(
            "basis-assessment evidence source is not trusted: "
            f"{source.source_name} ({source.reliability_level})"
        )

    package_hash = basis_assessment_package_hash(package)
    canonical_json = canonical_basis_assessment_json(package)
    existing = (
        db.query(TaiwanFinancialBasisAssessment)
        .filter(
            TaiwanFinancialBasisAssessment.stock_id == package.stock_id,
            TaiwanFinancialBasisAssessment.normalization_mode
            == package.normalization_mode,
            TaiwanFinancialBasisAssessment.assessment_type
            == package.assessment_type,
            TaiwanFinancialBasisAssessment.evidence_package_hash == package_hash,
        )
        .one_or_none()
    )
    if existing is not None:
        if (
            existing.outcome != package.outcome
            or existing.issue_code != package.issue_code
            or existing.evidence_json != canonical_json
        ):
            raise ValueError(
                "existing basis assessment conflicts with reviewed package"
            )
        return {
            "package_version": package.package_version,
            "package_id": package.package_id,
            "package_hash": package_hash,
            "approval_scope": package.approval_scope,
            "mode": "apply" if apply else "dry_run",
            "stock_id": package.stock_id,
            "assessment_created": 0,
            "assessment_reused": 1,
            "assessment_id": existing.id,
            "outcome": existing.outcome,
            "issue_code": existing.issue_code,
        }

    raw = (
        db.query(RawFetchResult)
        .filter(
            RawFetchResult.source_id == source.id,
            RawFetchResult.method == "BASIS_ASSESSMENT",
            RawFetchResult.content_hash == package_hash,
            RawFetchResult.parser_version == BASIS_ASSESSMENT_PARSER_VERSION,
        )
        .one_or_none()
    )
    raw_created = raw is None
    if apply and raw is None:
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=_utc_timestamp(package.reviewed_at),
            url=package.documents[0].url,
            method="BASIS_ASSESSMENT",
            status_code=200,
            content_type="application/json",
            content_hash=package_hash,
            raw_text=canonical_json,
            parser_version=BASIS_ASSESSMENT_PARSER_VERSION,
        )
        db.add(raw)
        db.flush()

    assessment_id = None
    if apply:
        assessment = TaiwanFinancialBasisAssessment(
            raw_result_id=raw.id if raw is not None else None,
            stock_id=package.stock_id,
            normalization_mode=package.normalization_mode,
            assessment_type=package.assessment_type,
            outcome=package.outcome,
            effective_date=package.effective_date,
            issue_code=package.issue_code,
            rationale=package.rationale,
            resolution_requirements_json=json.dumps(
                list(package.resolution_requirements),
                ensure_ascii=False,
            ),
            evidence_package_hash=package_hash,
            evidence_json=canonical_json,
            known_at=_utc_timestamp(package.known_at),
            reviewed_at=_utc_timestamp(package.reviewed_at),
            reviewed_by=package.reviewer,
        )
        db.add(assessment)
        db.flush()
        assessment_id = assessment.id

    return {
        "package_version": package.package_version,
        "package_id": package.package_id,
        "package_hash": package_hash,
        "approval_scope": package.approval_scope,
        "mode": "apply" if apply else "dry_run",
        "stock_id": package.stock_id,
        "raw_evidence_created": int(raw_created),
        "assessment_created": 1,
        "assessment_reused": 0,
        "assessment_id": assessment_id,
        "outcome": package.outcome,
        "issue_code": package.issue_code,
    }


__all__ = [
    "BASIS_ASSESSMENT_VERSION",
    "TaiwanFinancialBasisAssessmentPackage",
    "apply_financial_basis_assessment",
    "basis_assessment_package_hash",
    "canonical_basis_assessment_json",
]
