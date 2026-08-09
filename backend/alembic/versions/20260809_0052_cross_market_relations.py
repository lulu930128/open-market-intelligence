"""Add governed cross-market relation and evidence registry.

Revision ID: 20260809_0052
Revises: 20260804_0051
Create Date: 2026-08-09 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0052"
down_revision: str | Sequence[str] | None = "20260731_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VERIFIED_ON = date(2026, 7, 22)
VERIFIED_AT = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
PROXY_VERIFIED_AT = CREATED_AT
SEED_ACTOR = "migration:20260809_0052"

ADR_SEEDS = (
    {
        "stock_id": "2330",
        "stock_name": "台積電",
        "adr_symbol": "TSM",
        "adr_name": "TSMC ADR",
        "adr_exchange": "NYSE",
        "local_shares_per_adr": 5,
        "source_label": "TSMC 2025 Form 20-F",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm",
    },
    {
        "stock_id": "2303",
        "stock_name": "聯電",
        "adr_symbol": "UMC",
        "adr_name": "UMC ADR",
        "adr_exchange": "NYSE",
        "local_shares_per_adr": 5,
        "source_label": "UMC 2025 Form 20-F",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1033767/000119312526193757/d91630d20f.htm",
    },
    {
        "stock_id": "3711",
        "stock_name": "日月光投控",
        "adr_symbol": "ASX",
        "adr_name": "ASE Technology ADR",
        "adr_exchange": "NYSE",
        "local_shares_per_adr": 2,
        "source_label": "ASE Technology 2025 Form 20-F",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1122411/000119312526135585/d50802d20f.htm",
    },
    {
        "stock_id": "8150",
        "stock_name": "南茂",
        "adr_symbol": "IMOS",
        "adr_name": "ChipMOS ADR",
        "adr_exchange": "NASDAQ",
        "local_shares_per_adr": 20,
        "source_label": "ChipMOS 2025 Form 20-F",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1123134/000119312526153743/imos-20251231.htm",
    },
)

PROXY_SEED = {
    "source_symbol": "US:MU",
    "source_provider_symbol": "MU",
    "target_symbol": "TW:2408",
    "target_provider_symbol": "2408",
    "relation_type": "industry_peer",
    "relation_subtype": "dram_memory_cycle_proxy",
    "bucket": "industry_peer",
    "base_weight": 0.4,
    "confidence_tier": "C",
    "evidence_grade": "industry_mechanism",
    "evidence": (
        {
            "source_label": "Micron corporate profile",
            "source_url": "https://www.micron.com/about/company/corporate-profile",
            "statement": (
                "Micron officially describes its portfolio as including DRAM; "
                "this supports an industry-cycle proxy only."
            ),
        },
        {
            "source_label": "Nanya Technology company profile",
            "source_url": "https://www.nanya.com/en/About",
            "statement": (
                "Nanya officially describes its business as DRAM research, design, "
                "manufacturing, and sales. MU to 2408 is therefore a DRAM industry "
                "proxy, not evidence of a supplier, customer, or ownership relation."
            ),
        },
    ),
}


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _create_relation_table() -> None:
    if _has_table("cross_market_relation"):
        return
    op.create_table(
        "cross_market_relation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_market", sa.String(length=16), nullable=False),
        sa.Column("source_instrument_type", sa.String(length=32), nullable=False),
        sa.Column("source_canonical_symbol", sa.String(length=80), nullable=False),
        sa.Column("source_provider_symbol", sa.String(length=80), nullable=True),
        sa.Column("source_exchange", sa.String(length=40), nullable=True),
        sa.Column("source_currency", sa.String(length=12), nullable=True),
        sa.Column("target_market", sa.String(length=16), nullable=False),
        sa.Column("target_instrument_type", sa.String(length=32), nullable=False),
        sa.Column("target_canonical_symbol", sa.String(length=80), nullable=False),
        sa.Column("target_provider_symbol", sa.String(length=80), nullable=True),
        sa.Column("target_exchange", sa.String(length=40), nullable=True),
        sa.Column("target_currency", sa.String(length=12), nullable=True),
        sa.Column("relation_type", sa.String(length=40), nullable=False),
        sa.Column("relation_subtype", sa.String(length=80), nullable=True),
        sa.Column("bucket", sa.String(length=40), nullable=False),
        sa.Column("directionality", sa.String(length=30), nullable=False),
        sa.Column("base_weight", sa.Numeric(8, 6), nullable=False),
        sa.Column("confidence_tier", sa.String(length=2), nullable=False),
        sa.Column("evidence_grade", sa.String(length=40), nullable=False),
        sa.Column("ratio_numerator", sa.Numeric(20, 8), nullable=True),
        sa.Column("ratio_denominator", sa.Numeric(20, 8), nullable=True),
        sa.Column("depositary", sa.String(length=160), nullable=True),
        sa.Column("listing_tier", sa.String(length=40), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "base_weight >= 0 AND base_weight <= 1",
            name="ck_cross_market_relation_base_weight_range",
        ),
        sa.CheckConstraint(
            "confidence_tier IN ('A', 'B', 'C', 'D')",
            name="ck_cross_market_relation_confidence_tier",
        ),
        sa.CheckConstraint(
            "review_status IN ('candidate', 'approved', 'rejected', 'revoked')",
            name="ck_cross_market_relation_review_status",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_cross_market_relation_validity_range",
        ),
        sa.CheckConstraint(
            "((relation_type IN ('same_equity_dr', 'secondary_listing') "
            "AND ratio_numerator IS NOT NULL AND ratio_numerator > 0 "
            "AND ratio_denominator IS NOT NULL AND ratio_denominator > 0) OR "
            "(relation_type NOT IN ('same_equity_dr', 'secondary_listing') "
            "AND ratio_numerator IS NULL AND ratio_denominator IS NULL))",
            name="ck_cross_market_relation_ratio_semantics",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_canonical_symbol",
            "target_canonical_symbol",
            "relation_type",
            "valid_from",
            name="uq_cross_market_relation_identity_valid_from",
        ),
        sa.UniqueConstraint(
            "source_canonical_symbol",
            "target_canonical_symbol",
            "relation_type",
            "version",
            name="uq_cross_market_relation_identity_version",
        ),
    )
    for column_name in (
        "id",
        "source_market",
        "source_instrument_type",
        "source_canonical_symbol",
        "target_market",
        "target_instrument_type",
        "target_canonical_symbol",
        "relation_type",
        "bucket",
        "confidence_tier",
        "evidence_grade",
        "valid_from",
        "valid_to",
        "verified_at",
        "review_status",
        "is_active",
    ):
        op.create_index(
            f"ix_cross_market_relation_{column_name}",
            "cross_market_relation",
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_cross_market_relation_target_validity",
        "cross_market_relation",
        (
            "target_market",
            "target_canonical_symbol",
            "is_active",
            "valid_from",
            "valid_to",
        ),
        unique=False,
    )


def _create_evidence_table() -> None:
    if _has_table("cross_market_relation_evidence"):
        return
    op.create_table(
        "cross_market_relation_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("relation_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_grade", sa.String(length=2), nullable=False),
        sa.Column("source_label", sa.String(length=240), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("supersedes_evidence_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_grade IN ('A', 'B', 'C', 'D')",
            name="ck_cross_market_relation_evidence_source_grade",
        ),
        sa.CheckConstraint(
            "review_status IN ('candidate', 'approved', 'rejected', 'revoked')",
            name="ck_cross_market_relation_evidence_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["relation_id"],
            ["cross_market_relation.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_evidence_id"],
            ["cross_market_relation_evidence.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "relation_id",
            "content_hash",
            name="uq_cross_market_relation_evidence_content",
        ),
    )
    for column_name in (
        "id",
        "relation_id",
        "source_type",
        "source_grade",
        "verified_at",
        "content_hash",
        "is_primary",
        "review_status",
        "supersedes_evidence_id",
    ):
        op.create_index(
            f"ix_cross_market_relation_evidence_{column_name}",
            "cross_market_relation_evidence",
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_cross_market_relation_evidence_primary",
        "cross_market_relation_evidence",
        ("relation_id", "is_primary", "review_status"),
        unique=False,
    )


def _seed_verified_adr_relations() -> None:
    bind = op.get_bind()
    for seed in ADR_SEEDS:
        source_symbol = f"US:{seed['adr_symbol']}"
        target_symbol = f"TW:{seed['stock_id']}"
        existing = (
            bind.execute(
                sa.text(
                    """
                    SELECT id, ratio_numerator, ratio_denominator
                    FROM cross_market_relation
                    WHERE source_canonical_symbol = :source_symbol
                      AND target_canonical_symbol = :target_symbol
                      AND relation_type = 'same_equity_dr'
                      AND valid_from = :valid_from
                    """
                ),
                {
                    "source_symbol": source_symbol,
                    "target_symbol": target_symbol,
                    "valid_from": VERIFIED_ON,
                },
            )
            .mappings()
            .first()
        )
        expected_denominator = Decimal(str(seed["local_shares_per_adr"]))
        if existing is None:
            result = bind.execute(
                sa.text(
                    """
                    INSERT INTO cross_market_relation (
                        source_market,
                        source_instrument_type,
                        source_canonical_symbol,
                        source_provider_symbol,
                        source_exchange,
                        source_currency,
                        target_market,
                        target_instrument_type,
                        target_canonical_symbol,
                        target_provider_symbol,
                        target_exchange,
                        target_currency,
                        relation_type,
                        relation_subtype,
                        bucket,
                        directionality,
                        base_weight,
                        confidence_tier,
                        evidence_grade,
                        ratio_numerator,
                        ratio_denominator,
                        depositary,
                        listing_tier,
                        valid_from,
                        valid_to,
                        verified_at,
                        review_status,
                        is_active,
                        version,
                        created_by,
                        reviewed_by,
                        reviewed_at,
                        change_reason,
                        created_at,
                        updated_at
                    ) VALUES (
                        'US', 'adr', :source_symbol, :provider_symbol,
                        :source_exchange, 'USD',
                        'TW', 'stock', :target_symbol, :target_provider_symbol,
                        'TWSE', 'TWD',
                        'same_equity_dr', 'verified_adr', 'direct_equivalent',
                        'equivalent', 1, 'A', 'official_primary',
                        1, :ratio_denominator, NULL, 'primary',
                        :valid_from, NULL, :verified_at, 'approved', 1, 1,
                        :created_by, :reviewed_by, :reviewed_at,
                        :change_reason, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "source_symbol": source_symbol,
                    "provider_symbol": seed["adr_symbol"],
                    "source_exchange": seed["adr_exchange"],
                    "target_symbol": target_symbol,
                    "target_provider_symbol": seed["stock_id"],
                    # SQLite's raw DB-API binding does not accept Decimal.  Keep
                    # Decimal for deterministic conflict checks, but bind a
                    # plain float for this exact small-integer seed value.
                    "ratio_denominator": float(expected_denominator),
                    "valid_from": VERIFIED_ON,
                    "verified_at": VERIFIED_AT,
                    "created_by": SEED_ACTOR,
                    "reviewed_by": SEED_ACTOR,
                    "reviewed_at": CREATED_AT,
                    "change_reason": (
                        "migrate verified hardcoded ADR mapping; "
                        "validity before verification date is not asserted"
                    ),
                    "created_at": CREATED_AT,
                    "updated_at": CREATED_AT,
                },
            )
            relation_id = int(result.lastrowid)
        else:
            relation_id = int(existing["id"])
            if (
                Decimal(str(existing["ratio_numerator"])) != Decimal("1")
                or Decimal(str(existing["ratio_denominator"]))
                != expected_denominator
            ):
                raise RuntimeError(
                    f"cross-market ADR seed conflict for {target_symbol}"
                )

        statement = (
            f"{seed['adr_name']} represents "
            f"{seed['local_shares_per_adr']} common shares of "
            f"{seed['stock_name']} according to the cited filing."
        )
        content_hash = hashlib.sha256(
            f"{seed['source_url']}|{statement}".encode("utf-8")
        ).hexdigest()
        evidence_exists = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM cross_market_relation_evidence
                WHERE relation_id = :relation_id
                  AND content_hash = :content_hash
                """
            ),
            {"relation_id": relation_id, "content_hash": content_hash},
        ).first()
        if evidence_exists is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO cross_market_relation_evidence (
                        relation_id,
                        source_type,
                        source_grade,
                        source_label,
                        source_url,
                        statement,
                        published_at,
                        verified_at,
                        content_hash,
                        is_primary,
                        review_status,
                        supersedes_evidence_id,
                        created_by,
                        reviewed_by,
                        reviewed_at,
                        created_at,
                        updated_at
                    ) VALUES (
                        :relation_id, 'sec_filing', 'A', :source_label,
                        :source_url, :statement, NULL, :verified_at,
                        :content_hash, 1, 'approved', NULL, :created_by,
                        :reviewed_by, :reviewed_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "relation_id": relation_id,
                    "source_label": seed["source_label"],
                    "source_url": seed["source_url"],
                    "statement": statement,
                    "verified_at": VERIFIED_AT,
                    "content_hash": content_hash,
                    "created_by": SEED_ACTOR,
                    "reviewed_by": SEED_ACTOR,
                    "reviewed_at": CREATED_AT,
                    "created_at": CREATED_AT,
                    "updated_at": CREATED_AT,
                },
            )


def _seed_reviewed_proxy_relation() -> None:
    bind = op.get_bind()
    existing = (
        bind.execute(
            sa.text(
                """
                SELECT id, base_weight, confidence_tier
                FROM cross_market_relation
                WHERE source_canonical_symbol = :source_symbol
                  AND target_canonical_symbol = :target_symbol
                  AND relation_type = :relation_type
                  AND valid_from = :valid_from
                """
            ),
            {
                "source_symbol": PROXY_SEED["source_symbol"],
                "target_symbol": PROXY_SEED["target_symbol"],
                "relation_type": PROXY_SEED["relation_type"],
                "valid_from": PROXY_VERIFIED_AT.date(),
            },
        )
        .mappings()
        .first()
    )
    if existing is None:
        result = bind.execute(
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
                    'US', 'stock', :source_symbol, :source_provider_symbol,
                    'NASDAQ', 'USD',
                    'TW', 'stock', :target_symbol, :target_provider_symbol,
                    'TWSE', 'TWD',
                    :relation_type, :relation_subtype, :bucket, 'positive',
                    :base_weight, :confidence_tier, :evidence_grade,
                    NULL, NULL, NULL, 'primary',
                    :valid_from, NULL, :verified_at, 'approved', 1,
                    1, :created_by, :reviewed_by, :reviewed_at, :change_reason,
                    :created_at, :updated_at
                )
                """
            ),
            {
                **PROXY_SEED,
                "valid_from": PROXY_VERIFIED_AT.date(),
                "verified_at": PROXY_VERIFIED_AT,
                "created_by": SEED_ACTOR,
                "reviewed_by": SEED_ACTOR,
                "reviewed_at": CREATED_AT,
                "change_reason": (
                    "seed reviewed Tier C DRAM industry proxy; non-causal and "
                    "residualized against the governed benchmark policy"
                ),
                "created_at": CREATED_AT,
                "updated_at": CREATED_AT,
            },
        )
        relation_id = int(result.lastrowid)
    else:
        relation_id = int(existing["id"])
        if (
            Decimal(str(existing["base_weight"]))
            != Decimal(str(PROXY_SEED["base_weight"]))
            or existing["confidence_tier"] != PROXY_SEED["confidence_tier"]
        ):
            raise RuntimeError("cross-market proxy seed conflict for TW:2408")

    for evidence in PROXY_SEED["evidence"]:
        content_hash = hashlib.sha256(
            f"{evidence['source_url']}|{evidence['statement']}".encode("utf-8")
        ).hexdigest()
        exists = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM cross_market_relation_evidence
                WHERE relation_id = :relation_id
                  AND content_hash = :content_hash
                """
            ),
            {"relation_id": relation_id, "content_hash": content_hash},
        ).first()
        if exists is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO cross_market_relation_evidence (
                    relation_id, source_type, source_grade, source_label,
                    source_url, statement, published_at, verified_at,
                    content_hash, is_primary, review_status,
                    supersedes_evidence_id, created_by, reviewed_by,
                    reviewed_at, created_at, updated_at
                ) VALUES (
                    :relation_id, 'company_profile', 'C', :source_label,
                    :source_url, :statement, NULL, :verified_at,
                    :content_hash, 0, 'approved', NULL, :created_by,
                    :reviewed_by, :reviewed_at, :created_at, :updated_at
                )
                """
            ),
            {
                "relation_id": relation_id,
                **evidence,
                "verified_at": PROXY_VERIFIED_AT,
                "content_hash": content_hash,
                "created_by": SEED_ACTOR,
                "reviewed_by": SEED_ACTOR,
                "reviewed_at": CREATED_AT,
                "created_at": CREATED_AT,
                "updated_at": CREATED_AT,
            },
        )


def upgrade() -> None:
    _create_relation_table()
    _create_evidence_table()
    _seed_verified_adr_relations()
    _seed_reviewed_proxy_relation()


def downgrade() -> None:
    if _has_table("cross_market_relation_evidence"):
        op.drop_table("cross_market_relation_evidence")
    if _has_table("cross_market_relation"):
        op.drop_table("cross_market_relation")
