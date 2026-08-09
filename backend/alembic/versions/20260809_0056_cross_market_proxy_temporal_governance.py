"""Revalidate the seeded MU-to-2408 proxy with truthful availability time.

Revision ID: 20260809_0056
Revises: 20260809_0055
Create Date: 2026-08-09 19:30:00
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from typing import Any

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0056"
down_revision: str | Sequence[str] | None = "20260809_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_SEED_ACTOR = "migration:20260809_0052"
REPAIR_ACTOR = "migration:20260809_0056"
BAD_VERIFIED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
OLD_CHANGE_REASON = (
    "seed reviewed Tier C DRAM industry proxy; non-causal and "
    "residualized against the governed benchmark policy"
)
REVOKE_REASON = (
    "revoked by 20260809_0056 because the original seed used a future "
    "verification timestamp"
)
NEW_CHANGE_REASON = (
    "forward-only temporal revalidation of the reviewed Tier C DRAM industry "
    "proxy; non-causal and effective no earlier than the next UTC date"
)

PROXY = {
    "source_market": "US",
    "source_instrument_type": "stock",
    "source_canonical_symbol": "US:MU",
    "source_provider_symbol": "MU",
    "source_exchange": "NASDAQ",
    "source_currency": "USD",
    "target_market": "TW",
    "target_instrument_type": "stock",
    "target_canonical_symbol": "TW:2408",
    "target_provider_symbol": "2408",
    "target_exchange": "TWSE",
    "target_currency": "TWD",
    "relation_type": "industry_peer",
    "relation_subtype": "dram_memory_cycle_proxy",
    "bucket": "industry_peer",
    "directionality": "positive",
    "base_weight": Decimal("0.4"),
    "confidence_tier": "C",
    "evidence_grade": "industry_mechanism",
    "listing_tier": "primary",
}

EVIDENCE = (
    {
        "source_type": "company_profile",
        "source_grade": "C",
        "source_label": "Micron corporate profile",
        "source_url": "https://www.micron.com/about/company/corporate-profile",
        "statement": (
            "Micron officially describes its portfolio as including DRAM; "
            "this supports an industry-cycle proxy only."
        ),
    },
    {
        "source_type": "company_profile",
        "source_grade": "C",
        "source_label": "Nanya Technology company profile",
        "source_url": "https://www.nanya.com/en/About",
        "statement": (
            "Nanya officially describes its business as DRAM research, design, "
            "manufacturing, and sales. MU to 2408 is therefore a DRAM industry "
            "proxy, not evidence of a supplier, customer, or ownership relation."
        ),
    },
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _content_hash(evidence: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        f"{evidence['source_url']}|{evidence['statement']}".encode("utf-8")
    ).hexdigest()


def _relation_rows() -> list[Mapping[str, Any]]:
    return list(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT *
                FROM cross_market_relation
                WHERE source_canonical_symbol = :source_symbol
                  AND target_canonical_symbol = :target_symbol
                  AND relation_type = :relation_type
                ORDER BY version, id
                """
            ),
            {
                "source_symbol": PROXY["source_canonical_symbol"],
                "target_symbol": PROXY["target_canonical_symbol"],
                "relation_type": PROXY["relation_type"],
            },
        )
        .mappings()
        .all()
    )


def _evidence_rows(relation_id: int) -> list[Mapping[str, Any]]:
    return list(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT *
                FROM cross_market_relation_evidence
                WHERE relation_id = :relation_id
                ORDER BY content_hash, id
                """
            ),
            {"relation_id": relation_id},
        )
        .mappings()
        .all()
    )


def _relation_shape_matches(row: Mapping[str, Any]) -> bool:
    scalar_fields = (
        "source_market",
        "source_instrument_type",
        "source_canonical_symbol",
        "source_provider_symbol",
        "source_exchange",
        "source_currency",
        "target_market",
        "target_instrument_type",
        "target_canonical_symbol",
        "target_provider_symbol",
        "target_exchange",
        "target_currency",
        "relation_type",
        "relation_subtype",
        "bucket",
        "directionality",
        "confidence_tier",
        "evidence_grade",
        "listing_tier",
    )
    return (
        all(row[field] == PROXY[field] for field in scalar_fields)
        and _as_decimal(row["base_weight"]) == PROXY["base_weight"]
        and row["ratio_numerator"] is None
        and row["ratio_denominator"] is None
        and row["depositary"] is None
    )


def _require_expected_evidence(
    relation_id: int,
    *,
    actor: str,
    verified_at: datetime,
) -> None:
    rows = _evidence_rows(relation_id)
    expected_by_hash = {_content_hash(item): item for item in EVIDENCE}
    if len(rows) != len(expected_by_hash):
        raise RuntimeError(
            "cross-market proxy temporal repair aborted: evidence count mismatch"
        )
    for row in rows:
        expected = expected_by_hash.get(str(row["content_hash"]))
        if expected is None:
            raise RuntimeError(
                "cross-market proxy temporal repair aborted: evidence hash mismatch"
            )
        matches = (
            row["source_type"] == expected["source_type"]
            and row["source_grade"] == expected["source_grade"]
            and row["source_label"] == expected["source_label"]
            and row["source_url"] == expected["source_url"]
            and row["statement"] == expected["statement"]
            and row["published_at"] is None
            and _as_utc(row["verified_at"]) == verified_at
            and not bool(row["is_primary"])
            and row["review_status"] == "approved"
            and row["supersedes_evidence_id"] is None
            and row["created_by"] == actor
            and row["reviewed_by"] == actor
            and _as_utc(row["reviewed_at"]) == verified_at
            and _as_utc(row["created_at"]) == verified_at
            and _as_utc(row["updated_at"]) == verified_at
        )
        if not matches:
            raise RuntimeError(
                "cross-market proxy temporal repair aborted: evidence fingerprint mismatch"
            )


def _require_bad_seed(row: Mapping[str, Any]) -> None:
    matches = (
        _relation_shape_matches(row)
        and int(row["version"]) == 1
        and _as_date(row["valid_from"]) == BAD_VERIFIED_AT.date()
        and row["valid_to"] is None
        and _as_utc(row["verified_at"]) == BAD_VERIFIED_AT
        and row["review_status"] == "approved"
        and bool(row["is_active"])
        and row["created_by"] == OLD_SEED_ACTOR
        and row["reviewed_by"] == OLD_SEED_ACTOR
        and _as_utc(row["reviewed_at"]) == BAD_VERIFIED_AT
        and row["change_reason"] == OLD_CHANGE_REASON
        and _as_utc(row["created_at"]) == BAD_VERIFIED_AT
        and _as_utc(row["updated_at"]) == BAD_VERIFIED_AT
    )
    if not matches:
        raise RuntimeError(
            "cross-market proxy temporal repair aborted: relation seed fingerprint mismatch"
        )
    _require_expected_evidence(
        int(row["id"]),
        actor=OLD_SEED_ACTOR,
        verified_at=BAD_VERIFIED_AT,
    )


def _require_revoked_seed(
    row: Mapping[str, Any],
    *,
    repaired_at: datetime,
) -> None:
    matches = (
        _relation_shape_matches(row)
        and int(row["version"]) == 1
        and _as_date(row["valid_from"]) == BAD_VERIFIED_AT.date()
        and row["valid_to"] is None
        and _as_utc(row["verified_at"]) == BAD_VERIFIED_AT
        and row["review_status"] == "revoked"
        and not bool(row["is_active"])
        and row["created_by"] == OLD_SEED_ACTOR
        and row["reviewed_by"] == REPAIR_ACTOR
        and _as_utc(row["reviewed_at"]) == repaired_at
        and row["change_reason"] == f"{OLD_CHANGE_REASON}; {REVOKE_REASON}"
        and _as_utc(row["created_at"]) == BAD_VERIFIED_AT
        and _as_utc(row["updated_at"]) == repaired_at
    )
    if not matches:
        raise RuntimeError(
            "cross-market proxy temporal repair aborted: revoked seed conflict"
        )
    _require_expected_evidence(
        int(row["id"]),
        actor=OLD_SEED_ACTOR,
        verified_at=BAD_VERIFIED_AT,
    )


def _require_repaired(row: Mapping[str, Any]) -> None:
    verified_at = _as_utc(row["verified_at"])
    matches = (
        _relation_shape_matches(row)
        and int(row["version"]) in {1, 2}
        and _as_date(row["valid_from"]) == verified_at.date() + timedelta(days=1)
        and row["valid_to"] is None
        and row["review_status"] == "approved"
        and bool(row["is_active"])
        and row["created_by"] == REPAIR_ACTOR
        and row["reviewed_by"] == REPAIR_ACTOR
        and _as_utc(row["reviewed_at"]) == verified_at
        and row["change_reason"] == NEW_CHANGE_REASON
        and _as_utc(row["created_at"]) == verified_at
        and _as_utc(row["updated_at"]) == verified_at
    )
    if not matches:
        raise RuntimeError(
            "cross-market proxy temporal repair aborted: repaired relation conflict"
        )
    _require_expected_evidence(
        int(row["id"]),
        actor=REPAIR_ACTOR,
        verified_at=verified_at,
    )


def _insert_repaired_relation(*, version: int, repair_at: datetime) -> int:
    valid_from = repair_at.date() + timedelta(days=1)
    result = op.get_bind().execute(
        sa.text(
            """
            INSERT INTO cross_market_relation (
                source_market, source_instrument_type,
                source_canonical_symbol, source_provider_symbol,
                source_exchange, source_currency,
                target_market, target_instrument_type,
                target_canonical_symbol, target_provider_symbol,
                target_exchange, target_currency,
                relation_type, relation_subtype, bucket, directionality,
                base_weight, confidence_tier, evidence_grade,
                ratio_numerator, ratio_denominator, depositary, listing_tier,
                valid_from, valid_to, verified_at, review_status, is_active,
                version, created_by, reviewed_by, reviewed_at, change_reason,
                created_at, updated_at
            ) VALUES (
                :source_market, :source_instrument_type,
                :source_canonical_symbol, :source_provider_symbol,
                :source_exchange, :source_currency,
                :target_market, :target_instrument_type,
                :target_canonical_symbol, :target_provider_symbol,
                :target_exchange, :target_currency,
                :relation_type, :relation_subtype, :bucket, :directionality,
                :base_weight, :confidence_tier, :evidence_grade,
                NULL, NULL, NULL, :listing_tier,
                :valid_from, NULL, :verified_at, 'approved', 1,
                :version, :actor, :actor, :verified_at, :change_reason,
                :verified_at, :verified_at
            )
            """
        ),
        {
            **PROXY,
            "base_weight": float(PROXY["base_weight"]),
            "valid_from": valid_from,
            "verified_at": repair_at,
            "version": version,
            "actor": REPAIR_ACTOR,
            "change_reason": NEW_CHANGE_REASON,
        },
    )
    relation_id = int(result.lastrowid)
    for evidence in EVIDENCE:
        op.get_bind().execute(
            sa.text(
                """
                INSERT INTO cross_market_relation_evidence (
                    relation_id, source_type, source_grade, source_label,
                    source_url, statement, published_at, verified_at,
                    content_hash, is_primary, review_status,
                    supersedes_evidence_id, created_by, reviewed_by,
                    reviewed_at, created_at, updated_at
                ) VALUES (
                    :relation_id, :source_type, :source_grade, :source_label,
                    :source_url, :statement, NULL, :verified_at,
                    :content_hash, 0, 'approved', NULL, :actor, :actor,
                    :verified_at, :verified_at, :verified_at
                )
                """
            ),
            {
                "relation_id": relation_id,
                **evidence,
                "verified_at": repair_at,
                "content_hash": _content_hash(evidence),
                "actor": REPAIR_ACTOR,
            },
        )
    return relation_id


def upgrade() -> None:
    rows = _relation_rows()
    repaired_rows = [row for row in rows if row["created_by"] == REPAIR_ACTOR]
    if repaired_rows:
        if len(repaired_rows) != 1:
            raise RuntimeError(
                "cross-market proxy temporal repair aborted: multiple repaired versions"
            )
        repaired = repaired_rows[0]
        _require_repaired(repaired)
        unexpected = [
            row
            for row in rows
            if row["created_by"] not in {OLD_SEED_ACTOR, REPAIR_ACTOR}
        ]
        if unexpected:
            raise RuntimeError(
                "cross-market proxy temporal repair aborted: unmanaged relation version"
            )
        old_rows = [row for row in rows if row["created_by"] == OLD_SEED_ACTOR]
        if int(repaired["version"]) == 2:
            if len(old_rows) != 1:
                raise RuntimeError(
                    "cross-market proxy temporal repair aborted: revoked seed missing"
                )
            _require_revoked_seed(
                old_rows[0],
                repaired_at=_as_utc(repaired["verified_at"]),
            )
        elif old_rows:
            raise RuntimeError(
                "cross-market proxy temporal repair aborted: unexpected legacy seed"
            )
        return

    repair_at = _utc_now()
    if not rows:
        relation_id = _insert_repaired_relation(version=1, repair_at=repair_at)
        repaired = next(
            row for row in _relation_rows() if int(row["id"]) == relation_id
        )
        _require_repaired(repaired)
        return

    if len(rows) != 1:
        raise RuntimeError(
            "cross-market proxy temporal repair aborted: unexpected relation versions"
        )
    old = rows[0]
    _require_bad_seed(old)
    op.get_bind().execute(
        sa.text(
            """
            UPDATE cross_market_relation
            SET review_status = 'revoked',
                is_active = 0,
                reviewed_by = :actor,
                reviewed_at = :reviewed_at,
                change_reason = :change_reason,
                updated_at = :reviewed_at
            WHERE id = :relation_id
            """
        ),
        {
            "actor": REPAIR_ACTOR,
            "reviewed_at": repair_at,
            "change_reason": f"{OLD_CHANGE_REASON}; {REVOKE_REASON}",
            "relation_id": int(old["id"]),
        },
    )
    relation_id = _insert_repaired_relation(version=2, repair_at=repair_at)
    repaired = next(
        row for row in _relation_rows() if int(row["id"]) == relation_id
    )
    _require_repaired(repaired)


def downgrade() -> None:
    # This revision repairs audit semantics without changing schema.  Keep both
    # the revoked bad seed and the forward-only reviewed version so a version
    # marker rollback cannot erase governance history.  Re-upgrade is idempotent.
    pass
