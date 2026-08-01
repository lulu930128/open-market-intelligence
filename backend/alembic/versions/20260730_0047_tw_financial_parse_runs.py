"""Add immutable Taiwan financial parse-run ownership.

Revision ID: 20260730_0047
Revises: 20260730_0046
Create Date: 2026-07-30 23:10:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0047"
down_revision: str | Sequence[str] | None = "20260730_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTPUT_HASH_VERSION = "tw-financial-parse-output-v1"
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


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _output_hash(rows: Sequence[sa.RowMapping]) -> str:
    facts = [
        {
            field: _canonical_value(row[field])
            for field in _OUTPUT_FIELDS
        }
        for row in rows
    ]
    canonical = {
        "version": _OUTPUT_HASH_VERSION,
        "facts": sorted(facts, key=lambda item: str(item["fact_key"])),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fact_table() -> sa.Table:
    columns: list[sa.Column[Any]] = [
        sa.Column("id", sa.Integer()),
        sa.Column("filing_id", sa.Integer()),
        sa.Column("parse_run_id", sa.Integer()),
        sa.Column("fact_key", sa.String()),
        sa.Column("metric_code", sa.String()),
        sa.Column("source_label", sa.String()),
        sa.Column("source_value", sa.Numeric(30, 10)),
        sa.Column("source_value_text", sa.String()),
        sa.Column("source_unit", sa.String()),
        sa.Column("unit_inference_source", sa.Text()),
        sa.Column("currency", sa.String()),
        sa.Column("statement_type", sa.String()),
        sa.Column("period_kind", sa.String()),
        sa.Column("period_scope", sa.String()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("months_covered", sa.Integer()),
        sa.Column("fiscal_year", sa.Integer()),
        sa.Column("fiscal_quarter", sa.Integer()),
        sa.Column("consolidation_scope", sa.String()),
        sa.Column("attribution_scope", sa.String()),
        sa.Column("eps_kind", sa.String()),
        sa.Column("presentation_role", sa.String()),
        sa.Column("source_share_basis_id", sa.String()),
        sa.Column("source_restated", sa.Boolean()),
        sa.Column("source_restated_status", sa.String()),
    ]
    return sa.Table(
        "tw_financial_statement_fact",
        sa.MetaData(),
        *columns,
    )


def _filing_table() -> sa.Table:
    return sa.Table(
        "tw_financial_filing",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("raw_result_id", sa.Integer()),
        sa.Column("parser_version", sa.String()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def _parse_run_table() -> sa.Table:
    return sa.Table(
        "tw_financial_parse_run",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filing_id", sa.Integer()),
        sa.Column("raw_result_id", sa.Integer()),
        sa.Column("parser_version", sa.String()),
        sa.Column("parsed_at", sa.DateTime(timezone=True)),
        sa.Column("parse_status", sa.String()),
        sa.Column("review_status", sa.String()),
        sa.Column("output_hash", sa.String()),
        sa.Column("fact_count", sa.Integer()),
        sa.Column("diagnostics_json", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tw_financial_statement_fact"):
        raise RuntimeError(
            "tw_financial_statement_fact must exist before applying 20260730_0047."
        )
    parse_run_exists = inspector.has_table("tw_financial_parse_run")
    fact_columns = {
        column["name"]
        for column in inspector.get_columns("tw_financial_statement_fact")
    }
    parse_run_id_exists = "parse_run_id" in fact_columns
    if parse_run_exists and parse_run_id_exists:
        return
    if parse_run_exists != parse_run_id_exists:
        raise RuntimeError(
            "Partial Taiwan financial parse-run schema detected; refusing repair "
            "without an explicit recovery migration."
        )

    op.create_table(
        "tw_financial_parse_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parse_status", sa.String(length=20), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "parse_status IN ('succeeded', 'failed')",
            name="ck_tw_financial_parse_run_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'revoked')",
            name="ck_tw_financial_parse_run_review_status",
        ),
        sa.CheckConstraint(
            "parse_status != 'succeeded' OR output_hash IS NOT NULL",
            name="ck_tw_financial_parse_run_success_hash",
        ),
        sa.ForeignKeyConstraint(
            ["filing_id"],
            ["tw_financial_filing.id"],
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "filing_id",
            "parser_version",
            "output_hash",
            name="uq_tw_financial_parse_run_output",
        ),
    )
    for column in (
        "filing_id",
        "id",
        "output_hash",
        "parsed_at",
        "parse_status",
        "parser_version",
        "raw_result_id",
        "review_status",
        "reviewed_at",
    ):
        op.create_index(
            f"ix_tw_financial_parse_run_{column}",
            "tw_financial_parse_run",
            [column],
        )
    op.create_index(
        "ix_tw_financial_parse_run_canonical_selection",
        "tw_financial_parse_run",
        ["filing_id", "parse_status", "review_status", "id"],
    )
    op.add_column(
        "tw_financial_statement_fact",
        sa.Column("parse_run_id", sa.Integer(), nullable=True),
    )

    filing = _filing_table()
    fact = _fact_table()
    parse_run = _parse_run_table()
    filings = bind.execute(sa.select(filing).order_by(filing.c.id)).mappings().all()
    now = datetime.now(timezone.utc)
    for filing_row in filings:
        fact_rows = (
            bind.execute(
                sa.select(
                    *[fact.c[field] for field in _OUTPUT_FIELDS],
                )
                .where(fact.c.filing_id == filing_row["id"])
                .order_by(fact.c.fact_key)
            )
            .mappings()
            .all()
        )
        parsed_at = filing_row["updated_at"] or filing_row["fetched_at"] or now
        output_hash = _output_hash(fact_rows)
        result = bind.execute(
            parse_run.insert().values(
                filing_id=filing_row["id"],
                raw_result_id=filing_row["raw_result_id"],
                parser_version=filing_row["parser_version"],
                parsed_at=parsed_at,
                parse_status="succeeded",
                review_status="approved",
                output_hash=output_hash,
                fact_count=len(fact_rows),
                diagnostics_json=json.dumps(
                    {
                        "migration": revision,
                        "legacy_facts_adopted": len(fact_rows),
                        "output_hash_contract": _OUTPUT_HASH_VERSION,
                    },
                    sort_keys=True,
                ),
                reviewed_at=parsed_at,
                reviewed_by=f"migration:{revision}",
                created_at=now,
                updated_at=now,
            )
        )
        parse_run_id = result.inserted_primary_key[0]
        bind.execute(
            fact.update()
            .where(fact.c.filing_id == filing_row["id"])
            .values(parse_run_id=parse_run_id)
        )

    with op.batch_alter_table(
        "tw_financial_statement_fact",
        recreate="always",
        naming_convention={
            "uq": "uq_tw_financial_statement_fact_filing_key",
        },
        reflect_kwargs={"resolve_fks": False},
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_tw_financial_statement_fact_filing_key",
            type_="unique",
        )
        batch_op.alter_column(
            "parse_run_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_tw_financial_statement_fact_parse_run_id",
            "tw_financial_parse_run",
            ["parse_run_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_tw_financial_statement_fact_filing_id",
            "tw_financial_filing",
            ["filing_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_tw_financial_statement_fact_parse_run_key",
            ["parse_run_id", "fact_key"],
        )
        batch_op.create_index(
            "ix_tw_financial_statement_fact_parse_run_id",
            ["parse_run_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tw_financial_parse_run"):
        return
    fact_columns = {
        column["name"]
        for column in inspector.get_columns("tw_financial_statement_fact")
    }
    if "parse_run_id" in fact_columns:
        with op.batch_alter_table(
            "tw_financial_statement_fact",
            recreate="always",
            naming_convention={
                "fk": (
                    "fk_tw_financial_statement_fact_%(column_0_name)s"
                ),
                "uq": "uq_tw_financial_statement_fact_parse_run_key",
            },
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_index("ix_tw_financial_statement_fact_parse_run_id")
            batch_op.drop_constraint(
                "uq_tw_financial_statement_fact_parse_run_key",
                type_="unique",
            )
            batch_op.create_unique_constraint(
                "uq_tw_financial_statement_fact_filing_key",
                ["filing_id", "fact_key"],
            )
            batch_op.drop_column("parse_run_id")
            batch_op.create_foreign_key(
                "fk_tw_financial_statement_fact_filing_id",
                "tw_financial_filing",
                ["filing_id"],
                ["id"],
            )

    for index_name in (
        "ix_tw_financial_parse_run_canonical_selection",
        "ix_tw_financial_parse_run_reviewed_at",
        "ix_tw_financial_parse_run_review_status",
        "ix_tw_financial_parse_run_raw_result_id",
        "ix_tw_financial_parse_run_parser_version",
        "ix_tw_financial_parse_run_parse_status",
        "ix_tw_financial_parse_run_parsed_at",
        "ix_tw_financial_parse_run_output_hash",
        "ix_tw_financial_parse_run_id",
        "ix_tw_financial_parse_run_filing_id",
    ):
        op.drop_index(index_name, table_name="tw_financial_parse_run")
    op.drop_table("tw_financial_parse_run")
