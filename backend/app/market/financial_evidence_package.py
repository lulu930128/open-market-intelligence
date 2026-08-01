from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialCorporateAction,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_parse_runs import canonical_parse_run_id_for_filing
from app.market.financial_metric_normalization import (
    NORMALIZATION_VERSION,
    PerShareFinancialFact,
    ShareAdjustmentAction,
    normalize_per_share_series,
    source_decimal_places,
)


EVIDENCE_PACKAGE_VERSION = "omi.tw-financial-evidence.v1"
EVIDENCE_PARSER_VERSION = "tw-fin-evidence-v1"
TRUSTED_RELIABILITY_LEVELS = frozenset(
    {"official", "regulated_filing", "verified_official_mirror"}
)


def _utc_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("evidence timestamps must include a timezone offset")
    return value.astimezone(timezone.utc)


class EvidenceSourceDefinition(BaseModel):
    source_name: str = Field(min_length=1, max_length=120)
    source_type: str = Field(min_length=1, max_length=50)
    category: str = Field(min_length=1, max_length=80)
    endpoint_url: str | None = None
    priority: int = Field(ge=1, le=10_000)
    reliability_level: Literal[
        "official",
        "regulated_filing",
        "verified_official_mirror",
    ]


class EvidenceDocumentReference(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1)
    description: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, max_length=128)
    content_hash_status: Literal[
        "verified_source_bytes",
        "package_assertion_only",
        "unavailable",
    ]


class EvidenceFactAdjudication(BaseModel):
    source_name: str = Field(min_length=1, max_length=120)
    fiscal_year: int = Field(ge=1990, le=2200)
    fiscal_quarter: int = Field(ge=1, le=4)
    metric_code: Literal["basic_eps", "diluted_eps", "book_value_per_share"]
    expected_source_value: Decimal
    source_share_basis_id: str = Field(min_length=1, max_length=160)
    source_restated_status: Literal["confirmed", "not_restated"]
    expected_normalized_value: Decimal
    evidence_document_ids: tuple[str, ...] = Field(min_length=1)
    source_document_id: str | None = Field(default=None, max_length=160)
    presentation_role: Literal["current_period", "comparative_period"] | None = None
    fact_key: str | None = Field(default=None, max_length=180)
    period_scope: Literal[
        "ytd_3m",
        "ytd_6m",
        "ytd_9m",
        "annual_12m",
        "discrete_3m",
    ] | None = None
    normalization_treatment: Literal["official_restated"] | None = None


class EvidenceCorporateAction(BaseModel):
    source_name: str = Field(min_length=1, max_length=120)
    action_key: str = Field(min_length=1, max_length=160)
    action_type: str = Field(min_length=1, max_length=40)
    announced_at: datetime | None = None
    record_date: date | None = None
    effective_date: date
    old_share_basis: Decimal | None = None
    new_share_basis: Decimal | None = None
    adjustment_ratio: Decimal = Field(gt=0)
    adjustment_purpose: Literal[
        "price_series",
        "per_share_financials",
        "shares_outstanding",
        "informational_only",
    ]
    source_document_id: str = Field(min_length=1, max_length=160)
    source_document_url: str | None = None
    status: Literal["confirmed", "unverified", "disputed", "revoked"]


class EvidenceShareBasisAssessment(BaseModel):
    status: Literal[
        "verified_unchanged",
        "confirmed_action_adjusted",
    ]
    verification_method: Literal[
        "cross_filing_comparative_reconciliation",
        "official_corporate_action_document",
    ]
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_document_ids: tuple[str, ...] = Field(min_length=1)


class TaiwanFinancialEvidencePackage(BaseModel):
    package_version: Literal["omi.tw-financial-evidence.v1"]
    package_id: str = Field(min_length=1, max_length=160)
    approval_scope: Literal["clone_only", "production"]
    review_status: Literal["approved"]
    reviewer: str = Field(min_length=1, max_length=160)
    reviewed_at: datetime
    stock_id: str = Field(min_length=1, max_length=20)
    mode: Literal["current_comparable"]
    comparison_basis_id: str = Field(min_length=1, max_length=160)
    target_basis_date: date
    normalization_version: str = Field(
        default=NORMALIZATION_VERSION,
        min_length=1,
        max_length=80,
    )
    evidence_source_name: str = Field(min_length=1, max_length=120)
    sources: tuple[EvidenceSourceDefinition, ...] = Field(min_length=1)
    documents: tuple[EvidenceDocumentReference, ...] = Field(min_length=1)
    actions: tuple[EvidenceCorporateAction, ...] = ()
    share_basis_assessment: EvidenceShareBasisAssessment | None = None
    facts: tuple[EvidenceFactAdjudication, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "TaiwanFinancialEvidencePackage":
        source_names = [item.source_name for item in self.sources]
        if len(source_names) != len(set(source_names)):
            raise ValueError("source definitions must be unique")
        if self.evidence_source_name not in set(source_names):
            raise ValueError("evidence_source_name must reference a defined source")

        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("document references must be unique")
        known_documents = set(document_ids)
        known_sources = set(source_names)
        per_share_actions = [
            action
            for action in self.actions
            if action.adjustment_purpose == "per_share_financials"
        ]
        if not per_share_actions:
            if self.share_basis_assessment is None:
                raise ValueError(
                    "share_basis_assessment is required when no per-share "
                    "corporate action is supplied"
                )
            if self.share_basis_assessment.status != "verified_unchanged":
                raise ValueError(
                    "an action-free package must verify an unchanged share basis"
                )
        elif (
            self.share_basis_assessment is not None
            and self.share_basis_assessment.status != "confirmed_action_adjusted"
        ):
            raise ValueError(
                "a package with per-share actions must use "
                "confirmed_action_adjusted assessment status"
            )
        if self.share_basis_assessment is not None:
            missing = (
                set(self.share_basis_assessment.evidence_document_ids)
                - known_documents
            )
            if missing:
                raise ValueError(
                    "share-basis assessment references unknown evidence "
                    f"documents: {sorted(missing)}"
                )
        fact_period_scopes: dict[
            tuple[int, int, str],
            set[str | None],
        ] = {}
        action_document_ids = {
            action.source_document_id for action in per_share_actions
        }
        for fact in self.facts:
            if fact.source_name not in known_sources:
                raise ValueError(
                    f"fact source is not defined: {fact.source_name}"
                )
            missing = set(fact.evidence_document_ids) - known_documents
            if missing:
                raise ValueError(
                    f"fact references unknown evidence documents: {sorted(missing)}"
                )
            period_key = (
                fact.fiscal_year,
                fact.fiscal_quarter,
                fact.metric_code,
            )
            scopes = fact_period_scopes.setdefault(period_key, set())
            if scopes and (
                fact.period_scope is None
                or None in scopes
                or fact.period_scope in scopes
            ):
                raise ValueError(
                    "duplicate fact adjudication: "
                    f"{period_key} scope={fact.period_scope}"
                )
            scopes.add(fact.period_scope)
            if fact.normalization_treatment == "official_restated":
                if fact.source_restated_status != "confirmed":
                    raise ValueError(
                        "official_restated facts require confirmed source "
                        "restatement status"
                    )
                if not action_document_ids.intersection(
                    fact.evidence_document_ids
                ):
                    raise ValueError(
                        "official_restated facts must cite the confirmed "
                        "per-share action document"
                    )
        for action in self.actions:
            if action.source_name not in known_sources:
                raise ValueError(
                    f"action source is not defined: {action.source_name}"
                )
            if action.source_document_id not in known_documents:
                raise ValueError(
                    "action source_document_id must reference a document"
                )
        return self


def canonical_package_json(package: TaiwanFinancialEvidencePackage) -> str:
    payload = package.model_dump(mode="json")
    for fact in payload.get("facts", []):
        # Added v1-compatible selectors must not alter hashes of previously
        # approved packages when they are absent.
        if fact.get("period_scope") is None:
            fact.pop("period_scope", None)
        if fact.get("normalization_treatment") is None:
            fact.pop("normalization_treatment", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def evidence_package_hash(package: TaiwanFinancialEvidencePackage) -> str:
    return hashlib.sha256(canonical_package_json(package).encode("utf-8")).hexdigest()


def _ensure_sources(
    db: Session,
    *,
    package: TaiwanFinancialEvidencePackage,
    apply: bool,
) -> tuple[dict[str, SourceRegistry | EvidenceSourceDefinition], int, int]:
    source_names = [item.source_name for item in package.sources]
    existing = {
        source.source_name: source
        for source in (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_name.in_(source_names))
            .all()
        )
    }
    resolved: dict[str, SourceRegistry | EvidenceSourceDefinition] = {}
    created = 0
    reused = 0
    for definition in package.sources:
        source = existing.get(definition.source_name)
        if source is not None:
            if source.reliability_level not in TRUSTED_RELIABILITY_LEVELS:
                raise ValueError(
                    "existing evidence source is not trusted: "
                    f"{source.source_name} ({source.reliability_level})"
                )
            resolved[definition.source_name] = source
            reused += 1
            continue
        created += 1
        if not apply:
            resolved[definition.source_name] = definition
            continue
        source = SourceRegistry(
            source_name=definition.source_name,
            source_type=definition.source_type,
            category=definition.category,
            endpoint_url=definition.endpoint_url,
            enabled=True,
            priority=definition.priority,
            parser_type=EVIDENCE_PARSER_VERSION,
            auth_type="none",
            reliability_level=definition.reliability_level,
        )
        db.add(source)
        db.flush()
        resolved[definition.source_name] = source
    return resolved, created, reused


def _select_source_fact(
    db: Session,
    *,
    stock_id: str,
    adjudication: EvidenceFactAdjudication,
) -> tuple[
    TaiwanFinancialStatementFact,
    TaiwanFinancialFiling,
    SourceRegistry,
]:
    rows = (
        db.query(
            TaiwanFinancialStatementFact,
            TaiwanFinancialFiling,
            SourceRegistry,
        )
        .join(
            TaiwanFinancialParseRun,
            TaiwanFinancialParseRun.id
            == TaiwanFinancialStatementFact.parse_run_id,
        )
        .join(
            TaiwanFinancialFiling,
            TaiwanFinancialFiling.id
            == TaiwanFinancialParseRun.filing_id,
        )
        .join(
            SourceRegistry,
            SourceRegistry.id == TaiwanFinancialFiling.source_id,
        )
        .filter(
            TaiwanFinancialStatementFact.stock_id == stock_id,
            TaiwanFinancialStatementFact.fiscal_year
            == adjudication.fiscal_year,
            TaiwanFinancialStatementFact.fiscal_quarter
            == adjudication.fiscal_quarter,
            TaiwanFinancialStatementFact.metric_code
            == adjudication.metric_code,
            TaiwanFinancialStatementFact.filing_id
            == TaiwanFinancialFiling.id,
            TaiwanFinancialParseRun.parse_status == "succeeded",
            TaiwanFinancialParseRun.review_status == "approved",
            TaiwanFinancialParseRun.id
            == canonical_parse_run_id_for_filing(
                TaiwanFinancialStatementFact.filing_id
            ),
            SourceRegistry.source_name == adjudication.source_name,
        )
    )
    if adjudication.source_document_id is not None:
        rows = rows.filter(
            TaiwanFinancialFiling.source_document_id
            == adjudication.source_document_id
        )
    if adjudication.presentation_role is not None:
        rows = rows.filter(
            TaiwanFinancialStatementFact.presentation_role
            == adjudication.presentation_role
        )
    if adjudication.period_scope is not None:
        rows = rows.filter(
            TaiwanFinancialStatementFact.period_scope
            == adjudication.period_scope
        )
    if adjudication.fact_key is not None:
        rows = rows.filter(
            TaiwanFinancialStatementFact.fact_key == adjudication.fact_key
        )
    rows = rows.all()
    if len(rows) != 1:
        raise ValueError(
            "fact selector must resolve exactly one row: "
            f"{stock_id} {adjudication.fiscal_year}Q"
            f"{adjudication.fiscal_quarter} {adjudication.metric_code} "
            f"from {adjudication.source_name}; matched={len(rows)}"
        )
    fact, filing, source = rows[0]
    if source.reliability_level not in TRUSTED_RELIABILITY_LEVELS:
        raise ValueError(
            f"fact source is not trusted: {source.source_name} "
            f"({source.reliability_level})"
        )
    if fact.source_value != adjudication.expected_source_value:
        raise ValueError(
            "source value changed; package must be re-reviewed: "
            f"{stock_id} {adjudication.fiscal_year}Q"
            f"{adjudication.fiscal_quarter} expected="
            f"{adjudication.expected_source_value} actual={fact.source_value}"
        )
    if (
        fact.source_share_basis_id is not None
        and fact.source_share_basis_id != adjudication.source_share_basis_id
    ):
        raise ValueError(
            "source share basis changed; package must be re-reviewed: "
            f"expected={adjudication.source_share_basis_id} "
            f"actual={fact.source_share_basis_id}"
        )
    reviewed_official_restatement_override = (
        adjudication.normalization_treatment == "official_restated"
        and adjudication.source_restated_status == "confirmed"
    )
    if (
        fact.source_restated_status != "unknown"
        and fact.source_restated_status != adjudication.source_restated_status
        and not reviewed_official_restatement_override
    ):
        raise ValueError(
            "source restatement status changed; package must be re-reviewed: "
            f"expected={adjudication.source_restated_status} "
            f"actual={fact.source_restated_status}"
        )
    return fact, filing, source


def _package_raw_result(
    db: Session,
    *,
    package: TaiwanFinancialEvidencePackage,
    package_hash: str,
    source: SourceRegistry | EvidenceSourceDefinition,
    apply: bool,
) -> tuple[RawFetchResult | None, bool]:
    if isinstance(source, EvidenceSourceDefinition):
        return None, True
    existing = (
        db.query(RawFetchResult)
        .filter(
            RawFetchResult.source_id == source.id,
            RawFetchResult.method == "EVIDENCE_PACKAGE",
            RawFetchResult.content_hash == package_hash,
            RawFetchResult.parser_version == EVIDENCE_PARSER_VERSION,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    if not apply:
        return None, True
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=_utc_timestamp(package.reviewed_at),
        url=next(
            (
                document.url
                for document in package.documents
                if document.document_id
                == package.actions[0].source_document_id
            ),
            None,
        )
        if package.actions
        else None,
        method="EVIDENCE_PACKAGE",
        status_code=200,
        content_type="application/json",
        content_hash=package_hash,
        raw_text=canonical_package_json(package),
        parser_version=EVIDENCE_PARSER_VERSION,
    )
    db.add(raw)
    db.flush()
    return raw, True


def _persist_actions(
    db: Session,
    *,
    package: TaiwanFinancialEvidencePackage,
    package_hash: str,
    sources: dict[str, SourceRegistry | EvidenceSourceDefinition],
    raw_result: RawFetchResult | None,
    apply: bool,
) -> tuple[list[ShareAdjustmentAction], int, int]:
    normalized_actions: list[ShareAdjustmentAction] = []
    created = 0
    reused = 0
    for item in package.actions:
        source = sources[item.source_name]
        existing = None
        if isinstance(source, SourceRegistry):
            existing = (
                db.query(TaiwanFinancialCorporateAction)
                .filter(
                    TaiwanFinancialCorporateAction.source_id == source.id,
                    TaiwanFinancialCorporateAction.stock_id == package.stock_id,
                    TaiwanFinancialCorporateAction.action_type
                    == item.action_type,
                    TaiwanFinancialCorporateAction.effective_date
                    == item.effective_date,
                    TaiwanFinancialCorporateAction.adjustment_purpose
                    == item.adjustment_purpose,
                    TaiwanFinancialCorporateAction.source_document_id
                    == item.source_document_id,
                )
                .first()
            )
        if existing is None:
            created += 1
            if apply:
                if not isinstance(source, SourceRegistry):
                    raise RuntimeError("source must be persisted before action")
                existing = TaiwanFinancialCorporateAction(
                    source_id=source.id,
                    raw_result_id=raw_result.id if raw_result else None,
                    stock_id=package.stock_id,
                    action_type=item.action_type,
                    announced_at=_utc_timestamp(item.announced_at),
                    record_date=item.record_date,
                    effective_date=item.effective_date,
                    old_share_basis=item.old_share_basis,
                    new_share_basis=item.new_share_basis,
                    adjustment_ratio=item.adjustment_ratio,
                    adjustment_purpose=item.adjustment_purpose,
                    source_document_id=item.source_document_id,
                    source_document_url=item.source_document_url,
                    content_hash=package_hash,
                    status=item.status,
                )
                db.add(existing)
                db.flush()
        else:
            reused += 1
            if (
                existing.adjustment_ratio != item.adjustment_ratio
                or existing.status != item.status
            ):
                raise ValueError(
                    f"existing corporate action conflicts with {item.action_key}"
                )
        normalized_actions.append(
            ShareAdjustmentAction(
                action_id=item.action_key,
                stock_id=package.stock_id,
                action_type=item.action_type,
                effective_date=item.effective_date,
                adjustment_ratio=item.adjustment_ratio,
                adjustment_purpose=item.adjustment_purpose,
                status=item.status,
                known_at=_utc_timestamp(item.announced_at),
            )
        )
    return normalized_actions, created, reused


def apply_financial_evidence_package(
    db: Session,
    *,
    package: TaiwanFinancialEvidencePackage,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate and optionally persist a reviewed, auditable normalization package.

    The caller owns commit and rollback. A package never overwrites source facts.
    """

    package_hash = evidence_package_hash(package)
    sources, sources_created, sources_reused = _ensure_sources(
        db,
        package=package,
        apply=apply,
    )
    evidence_source = sources[package.evidence_source_name]
    raw_result, raw_created = _package_raw_result(
        db,
        package=package,
        package_hash=package_hash,
        source=evidence_source,
        apply=apply,
    )
    actions, actions_created, actions_reused = _persist_actions(
        db,
        package=package,
        package_hash=package_hash,
        sources=sources,
        raw_result=raw_result,
        apply=apply,
    )

    selected: list[
        tuple[
            EvidenceFactAdjudication,
            TaiwanFinancialStatementFact,
            TaiwanFinancialFiling,
            SourceRegistry,
        ]
    ] = []
    per_share_facts: list[PerShareFinancialFact] = []
    for adjudication in package.facts:
        fact, filing, source = _select_source_fact(
            db,
            stock_id=package.stock_id,
            adjudication=adjudication,
        )
        selected.append((adjudication, fact, filing, source))
        per_share_facts.append(
            PerShareFinancialFact(
                fact_id=str(fact.id),
                stock_id=fact.stock_id,
                fiscal_year=fact.fiscal_year,
                fiscal_quarter=fact.fiscal_quarter or 0,
                metric_code=fact.metric_code,
                period_scope=fact.period_scope,
                period_end=fact.period_end,
                value=fact.source_value,
                unit=fact.source_unit,
                source_share_basis_id=adjudication.source_share_basis_id,
                source_restated_status=adjudication.source_restated_status,
                known_at=filing.known_at,
                source_decimal_places=source_decimal_places(
                    fact.source_value_text
                ),
                adjustment_treatment=(
                    adjudication.normalization_treatment or "automatic"
                ),
            )
        )

    normalized = normalize_per_share_series(
        facts=per_share_facts,
        actions=actions,
        target_basis_date=package.target_basis_date,
        comparison_basis_id=package.comparison_basis_id,
        mode=package.mode,
        normalization_version=package.normalization_version,
    )
    normalized_by_fact_id = {
        item.source_fact_id: item for item in normalized
    }
    created = 0
    reused = 0
    results: list[dict[str, Any]] = []
    document_by_id = {
        document.document_id: document for document in package.documents
    }
    for adjudication, fact, filing, source in selected:
        result = normalized_by_fact_id[str(fact.id)]
        if not result.decision_usable or result.normalized_value is None:
            raise ValueError(
                "adjudicated fact did not normalize to a usable value: "
                f"{package.stock_id} {fact.fiscal_year}Q{fact.fiscal_quarter} "
                f"issues={list(result.issue_codes)}"
            )
        if result.normalized_value != adjudication.expected_normalized_value:
            raise ValueError(
                "normalized value differs from reviewed expectation: "
                f"{package.stock_id} {fact.fiscal_year}Q{fact.fiscal_quarter} "
                f"expected={adjudication.expected_normalized_value} "
                f"actual={result.normalized_value}"
            )
        lineage = {
            "package_version": package.package_version,
            "package_id": package.package_id,
            "package_hash": package_hash,
            "approval_scope": package.approval_scope,
            "review_status": package.review_status,
            "reviewer": package.reviewer,
            "reviewed_at": package.reviewed_at.isoformat(),
            "source_fact_id": fact.id,
            "parse_run_id": fact.parse_run_id,
            "filing_id": filing.id,
            "source_id": source.id,
            "source_parser_restatement_status": fact.source_restated_status,
            "reviewed_restatement_status": adjudication.source_restated_status,
            "adjustment_treatment": (
                adjudication.normalization_treatment or "automatic"
            ),
            "corporate_action_ids": list(result.action_ids),
            "share_basis_assessment": (
                package.share_basis_assessment.model_dump(mode="json")
                if package.share_basis_assessment is not None
                else None
            ),
            "evidence_documents": [
                document_by_id[document_id].model_dump(mode="json")
                for document_id in adjudication.evidence_document_ids
            ],
        }
        existing = (
            db.query(TaiwanFinancialNormalizedFact)
            .filter(
                TaiwanFinancialNormalizedFact.source_fact_id == fact.id,
                TaiwanFinancialNormalizedFact.comparison_basis_id
                == package.comparison_basis_id,
                TaiwanFinancialNormalizedFact.normalization_version
                == package.normalization_version,
                TaiwanFinancialNormalizedFact.normalization_mode
                == package.mode,
            )
            .first()
        )
        if existing is not None:
            if (
                existing.normalized_value != result.normalized_value
                or existing.normalization_status != result.normalization_status
                or json.loads(existing.lineage_json).get("package_hash")
                != package_hash
            ):
                raise ValueError(
                    "existing normalized fact conflicts with reviewed package: "
                    f"source_fact_id={fact.id}"
                )
            reused += 1
        else:
            created += 1
            if apply:
                db.add(
                    TaiwanFinancialNormalizedFact(
                        source_fact_id=fact.id,
                        comparison_basis_id=package.comparison_basis_id,
                        normalization_mode=package.mode,
                        normalized_value=result.normalized_value,
                        normalized_unit=result.normalized_unit,
                        adjustment_factor=result.adjustment_factor,
                        normalization_status=result.normalization_status,
                        normalization_version=package.normalization_version,
                        derived_at=_utc_timestamp(package.reviewed_at),
                        decision_usable=result.decision_usable,
                        issue_codes_json=json.dumps(
                            list(result.issue_codes),
                            ensure_ascii=False,
                        ),
                        lineage_json=json.dumps(
                            lineage,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                )
        results.append(
            {
                "source_fact_id": fact.id,
                "period": f"{fact.fiscal_year}Q{fact.fiscal_quarter}",
                "period_scope": fact.period_scope,
                "source_value": str(fact.source_value),
                "adjustment_factor": str(result.adjustment_factor),
                "adjustment_treatment": (
                    adjudication.normalization_treatment or "automatic"
                ),
                "normalized_value": str(result.normalized_value),
                "normalization_status": result.normalization_status,
                "action_ids": list(result.action_ids),
            }
        )
    if apply:
        db.flush()
    return {
        "package_version": package.package_version,
        "package_id": package.package_id,
        "package_hash": package_hash,
        "approval_scope": package.approval_scope,
        "mode": "apply" if apply else "dry_run",
        "stock_id": package.stock_id,
        "sources_created": sources_created,
        "sources_reused": sources_reused,
        "raw_evidence_created": int(raw_created),
        "actions_created": actions_created,
        "actions_reused": actions_reused,
        "share_basis_assessment": (
            package.share_basis_assessment.model_dump(mode="json")
            if package.share_basis_assessment is not None
            else None
        ),
        "normalized_facts_created": created,
        "normalized_facts_reused": reused,
        "results": results,
    }
