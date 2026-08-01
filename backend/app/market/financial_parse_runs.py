from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    TaiwanFinancialParseRun,
    TaiwanFinancialParseRunReview,
    TaiwanFinancialStatementFact,
)


PARSE_OUTPUT_HASH_VERSION = "tw-financial-parse-output-v1"
APPROVED_PARSE_STATUS = "succeeded"
APPROVED_REVIEW_STATUS = "approved"

_OUTPUT_FIELDS = (
    "fact_key",
    "metric_code",
    "source_label",
    "source_value",
    "source_value_text",
    "source_unit",
    "unit_inference_source",
    "currency",
    "statement_type",
    "period_kind",
    "period_scope",
    "period_start",
    "period_end",
    "months_covered",
    "fiscal_year",
    "fiscal_quarter",
    "consolidation_scope",
    "attribution_scope",
    "eps_kind",
    "presentation_role",
    "source_share_basis_id",
    "source_restated",
    "source_restated_status",
)


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def canonical_fact_output_payload(facts: Iterable[Any]) -> list[dict[str, Any]]:
    payload = [
        {
            field: _canonical_value(_field(item, field))
            for field in _OUTPUT_FIELDS
        }
        for item in facts
    ]
    return sorted(payload, key=lambda item: str(item["fact_key"]))


def canonical_fact_output_hash(facts: Iterable[Any]) -> str:
    canonical = {
        "version": PARSE_OUTPUT_HASH_VERSION,
        "facts": canonical_fact_output_payload(facts),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_diagnostics(
    *,
    contexts_seen: int,
    units_seen: int,
    numeric_facts_seen: int,
    facts: Iterable[Any],
    replayed_from_raw: bool,
) -> str:
    materialized = tuple(facts)
    scope_counts = Counter(str(_field(item, "period_scope")) for item in materialized)
    metric_counts = Counter(str(_field(item, "metric_code")) for item in materialized)
    return json.dumps(
        {
            "output_hash_contract": PARSE_OUTPUT_HASH_VERSION,
            "contexts_seen": contexts_seen,
            "units_seen": units_seen,
            "numeric_facts_seen": numeric_facts_seen,
            "canonical_facts_selected": len(materialized),
            "period_scope_counts": dict(sorted(scope_counts.items())),
            "metric_counts": dict(sorted(metric_counts.items())),
            "replayed_from_raw": replayed_from_raw,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def canonical_parse_run_id_for_filing(
    filing_id_column: Any,
    *,
    reviewed_as_of: datetime | None = None,
) -> Any:
    query = select(TaiwanFinancialParseRun.id).where(
        TaiwanFinancialParseRun.filing_id == filing_id_column,
        TaiwanFinancialParseRun.parse_status == APPROVED_PARSE_STATUS,
    )
    if reviewed_as_of is not None:
        if reviewed_as_of.tzinfo is None:
            raise ValueError("reviewed_as_of must include timezone evidence")
        latest_decision_as_of = (
            select(TaiwanFinancialParseRunReview.decision)
            .where(
                TaiwanFinancialParseRunReview.parse_run_id
                == TaiwanFinancialParseRun.id,
                TaiwanFinancialParseRunReview.decided_at <= reviewed_as_of,
            )
            .order_by(
                TaiwanFinancialParseRunReview.decided_at.desc(),
                TaiwanFinancialParseRunReview.id.desc(),
            )
            .limit(1)
            .correlate(TaiwanFinancialParseRun)
            .scalar_subquery()
        )
        latest_decided_at_as_of = (
            select(TaiwanFinancialParseRunReview.decided_at)
            .where(
                TaiwanFinancialParseRunReview.parse_run_id
                == TaiwanFinancialParseRun.id,
                TaiwanFinancialParseRunReview.decided_at <= reviewed_as_of,
            )
            .order_by(
                TaiwanFinancialParseRunReview.decided_at.desc(),
                TaiwanFinancialParseRunReview.id.desc(),
            )
            .limit(1)
            .correlate(TaiwanFinancialParseRun)
            .scalar_subquery()
        )
        query = query.where(
            TaiwanFinancialParseRun.parsed_at <= reviewed_as_of,
            latest_decision_as_of == APPROVED_REVIEW_STATUS,
        ).order_by(
            latest_decided_at_as_of.desc(),
            TaiwanFinancialParseRun.id.desc(),
        )
    else:
        query = query.where(
            TaiwanFinancialParseRun.review_status == APPROVED_REVIEW_STATUS,
        ).order_by(TaiwanFinancialParseRun.id.desc())
    return (
        query.limit(1)
        .correlate(TaiwanFinancialStatementFact)
        .scalar_subquery()
    )


def get_canonical_parse_run(
    db: Session,
    *,
    filing_id: int,
    reviewed_as_of: datetime | None = None,
) -> TaiwanFinancialParseRun | None:
    query = db.query(TaiwanFinancialParseRun).filter(
        TaiwanFinancialParseRun.filing_id == filing_id,
        TaiwanFinancialParseRun.parse_status == APPROVED_PARSE_STATUS,
    )
    if reviewed_as_of is not None:
        if reviewed_as_of.tzinfo is None:
            raise ValueError("reviewed_as_of must include timezone evidence")
        latest_decision_as_of = (
            select(TaiwanFinancialParseRunReview.decision)
            .where(
                TaiwanFinancialParseRunReview.parse_run_id
                == TaiwanFinancialParseRun.id,
                TaiwanFinancialParseRunReview.decided_at <= reviewed_as_of,
            )
            .order_by(
                TaiwanFinancialParseRunReview.decided_at.desc(),
                TaiwanFinancialParseRunReview.id.desc(),
            )
            .limit(1)
            .correlate(TaiwanFinancialParseRun)
            .scalar_subquery()
        )
        latest_decided_at_as_of = (
            select(TaiwanFinancialParseRunReview.decided_at)
            .where(
                TaiwanFinancialParseRunReview.parse_run_id
                == TaiwanFinancialParseRun.id,
                TaiwanFinancialParseRunReview.decided_at <= reviewed_as_of,
            )
            .order_by(
                TaiwanFinancialParseRunReview.decided_at.desc(),
                TaiwanFinancialParseRunReview.id.desc(),
            )
            .limit(1)
            .correlate(TaiwanFinancialParseRun)
            .scalar_subquery()
        )
        query = query.filter(
            TaiwanFinancialParseRun.parsed_at <= reviewed_as_of,
            latest_decision_as_of == APPROVED_REVIEW_STATUS,
        ).order_by(
            latest_decided_at_as_of.desc(),
            TaiwanFinancialParseRun.id.desc(),
        )
    else:
        query = query.filter(
            TaiwanFinancialParseRun.review_status == APPROVED_REVIEW_STATUS,
        ).order_by(TaiwanFinancialParseRun.id.desc())
    return query.first()


def review_financial_parse_run(
    db: Session,
    *,
    parse_run_id: int,
    expected_output_hash: str,
    reviewer: str,
    decision: str = "approved",
    apply: bool = False,
    reviewed_at: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if decision not in {"approved", "rejected", "revoked"}:
        raise ValueError("decision must be approved, rejected, or revoked")
    normalized_reviewer = reviewer.strip()
    if not normalized_reviewer:
        raise ValueError("reviewer is required")
    normalized_reason = reason.strip() if reason and reason.strip() else None
    if decision == "revoked" and normalized_reason is None:
        raise ValueError("reason is required when revoking a parse run")
    run = (
        db.query(TaiwanFinancialParseRun)
        .filter(TaiwanFinancialParseRun.id == parse_run_id)
        .one_or_none()
    )
    if run is None:
        raise ValueError(f"parse run not found: {parse_run_id}")
    if run.parse_status != "succeeded" or run.output_hash is None:
        raise ValueError("only a successful parse run with an output hash may be reviewed")
    if run.output_hash != expected_output_hash:
        raise ValueError(
            "parse output hash changed; refusing review: "
            f"expected={expected_output_hash} actual={run.output_hash}"
        )
    facts = (
        db.query(TaiwanFinancialStatementFact)
        .filter(TaiwanFinancialStatementFact.parse_run_id == run.id)
        .order_by(TaiwanFinancialStatementFact.fact_key)
        .all()
    )
    if len(facts) != run.fact_count:
        raise ValueError(
            "parse run fact count mismatch: "
            f"declared={run.fact_count} actual={len(facts)}"
        )
    if canonical_fact_output_hash(facts) != run.output_hash:
        raise ValueError("stored parse facts no longer match the immutable output hash")

    timestamp = reviewed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("reviewed_at must include timezone evidence")
    timestamp = timestamp.astimezone(timezone.utc)
    latest_event = (
        db.query(TaiwanFinancialParseRunReview)
        .filter(TaiwanFinancialParseRunReview.parse_run_id == run.id)
        .order_by(
            TaiwanFinancialParseRunReview.decided_at.desc(),
            TaiwanFinancialParseRunReview.id.desc(),
        )
        .first()
    )
    event_matches = (
        latest_event is not None
        and latest_event.decision == decision
        and latest_event.decided_by == normalized_reviewer
        and latest_event.output_hash_snapshot == run.output_hash
    )
    changed = (
        run.review_status != decision
        or run.reviewed_by != normalized_reviewer
        or run.reviewed_at is None
        or not event_matches
    )
    previous_review_status = run.review_status
    review_event_id = latest_event.id if event_matches else None
    if apply and changed:
        event = TaiwanFinancialParseRunReview(
            parse_run_id=run.id,
            decision=decision,
            decided_at=timestamp,
            decided_by=normalized_reviewer,
            output_hash_snapshot=run.output_hash,
            reason=normalized_reason,
        )
        db.add(event)
        run.review_status = decision
        run.reviewed_by = normalized_reviewer
        run.reviewed_at = timestamp
        db.flush()
        review_event_id = event.id
    return {
        "mode": "apply" if apply else "dry_run",
        "parse_run_id": run.id,
        "review_event_id": review_event_id,
        "filing_id": run.filing_id,
        "parser_version": run.parser_version,
        "parse_status": run.parse_status,
        "previous_review_status": previous_review_status,
        "decision": decision,
        "reason": normalized_reason,
        "output_hash": run.output_hash,
        "fact_count": run.fact_count,
        "changed": changed,
    }


__all__ = [
    "APPROVED_PARSE_STATUS",
    "APPROVED_REVIEW_STATUS",
    "PARSE_OUTPUT_HASH_VERSION",
    "canonical_fact_output_hash",
    "canonical_fact_output_payload",
    "canonical_parse_run_id_for_filing",
    "get_canonical_parse_run",
    "parse_diagnostics",
    "review_financial_parse_run",
]
