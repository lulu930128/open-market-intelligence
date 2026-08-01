"""Add versioned Taiwan financial semantic storage.

Revision ID: 20260730_0045
Revises: 20260730_0044
Create Date: 2026-07-30 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0045"
down_revision: str | Sequence[str] | None = "20260730_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    expected_tables = {
        "tw_financial_filing",
        "tw_financial_statement_fact",
        "tw_financial_corporate_action",
        "tw_financial_normalized_fact",
    }
    inspector = sa.inspect(op.get_bind())
    existing_tables = {
        table_name
        for table_name in expected_tables
        if inspector.has_table(table_name)
    }
    if existing_tables == expected_tables:
        return
    if existing_tables:
        missing_tables = sorted(expected_tables - existing_tables)
        raise RuntimeError(
            "Partial Taiwan financial semantic schema detected; "
            f"existing={sorted(existing_tables)} missing={missing_tables}. "
            "Refusing to create a mixed contract."
        )

    op.create_table(
        "tw_financial_filing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_filing_id", sa.Integer(), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("source_document_id", sa.String(length=160), nullable=False),
        sa.Column("source_document_url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("filing_kind", sa.String(length=40), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.ForeignKeyConstraint(
            ["supersedes_filing_id"],
            ["tw_financial_filing.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "stock_id",
            "source_document_id",
            "content_hash",
            name="uq_tw_financial_filing_source_document_version",
        ),
    )
    op.create_index(
        "ix_tw_financial_filing_content_hash",
        "tw_financial_filing",
        ["content_hash"],
    )
    op.create_index("ix_tw_financial_filing_fetched_at", "tw_financial_filing", ["fetched_at"])
    op.create_index("ix_tw_financial_filing_filed_at", "tw_financial_filing", ["filed_at"])
    op.create_index("ix_tw_financial_filing_filing_kind", "tw_financial_filing", ["filing_kind"])
    op.create_index("ix_tw_financial_filing_fiscal_quarter", "tw_financial_filing", ["fiscal_quarter"])
    op.create_index("ix_tw_financial_filing_fiscal_year", "tw_financial_filing", ["fiscal_year"])
    op.create_index("ix_tw_financial_filing_id", "tw_financial_filing", ["id"])
    op.create_index("ix_tw_financial_filing_known_at", "tw_financial_filing", ["known_at"])
    op.create_index("ix_tw_financial_filing_parser_version", "tw_financial_filing", ["parser_version"])
    op.create_index("ix_tw_financial_filing_period_end", "tw_financial_filing", ["period_end"])
    op.create_index(
        "ix_tw_financial_filing_provider_generated_at",
        "tw_financial_filing",
        ["provider_generated_at"],
    )
    op.create_index("ix_tw_financial_filing_raw_result_id", "tw_financial_filing", ["raw_result_id"])
    op.create_index("ix_tw_financial_filing_source_id", "tw_financial_filing", ["source_id"])
    op.create_index("ix_tw_financial_filing_stock_id", "tw_financial_filing", ["stock_id"])
    op.create_index(
        "ix_tw_financial_filing_stock_period_known",
        "tw_financial_filing",
        ["stock_id", "period_end", "known_at"],
    )
    op.create_index(
        "ix_tw_financial_filing_supersedes_filing_id",
        "tw_financial_filing",
        ["supersedes_filing_id"],
    )

    op.create_table(
        "tw_financial_statement_fact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("fact_key", sa.String(length=180), nullable=False),
        sa.Column("metric_code", sa.String(length=100), nullable=False),
        sa.Column("source_label", sa.String(length=240), nullable=False),
        sa.Column("source_value", sa.Numeric(precision=30, scale=10), nullable=False),
        sa.Column("source_value_text", sa.String(length=120), nullable=True),
        sa.Column("source_unit", sa.String(length=40), nullable=False),
        sa.Column("unit_inference_source", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("statement_type", sa.String(length=30), nullable=False),
        sa.Column("period_kind", sa.String(length=20), nullable=False),
        sa.Column("period_scope", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("months_covered", sa.Integer(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("consolidation_scope", sa.String(length=40), nullable=False),
        sa.Column("attribution_scope", sa.String(length=60), nullable=False),
        sa.Column("eps_kind", sa.String(length=20), nullable=False),
        sa.Column("presentation_role", sa.String(length=30), nullable=False),
        sa.Column("source_share_basis_id", sa.String(length=160), nullable=True),
        sa.Column("source_restated", sa.Boolean(), nullable=True),
        sa.Column("source_restated_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "eps_kind IN ('basic', 'diluted', 'not_applicable')",
            name="ck_tw_financial_statement_fact_eps_kind",
        ),
        sa.CheckConstraint(
            "period_kind IN ('duration', 'instant')",
            name="ck_tw_financial_statement_fact_period_kind",
        ),
        sa.CheckConstraint(
            "presentation_role IN ('current_period', 'comparative_period')",
            name="ck_tw_financial_statement_fact_presentation_role",
        ),
        sa.CheckConstraint(
            "source_restated_status IN ('confirmed', 'not_restated', 'unknown')",
            name="ck_tw_financial_statement_fact_restatement",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["tw_financial_filing.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "filing_id",
            "fact_key",
            name="uq_tw_financial_statement_fact_filing_key",
        ),
    )
    for column in (
        "attribution_scope",
        "consolidation_scope",
        "currency",
        "eps_kind",
        "filing_id",
        "fiscal_quarter",
        "fiscal_year",
        "id",
        "metric_code",
        "period_end",
        "period_kind",
        "period_scope",
        "period_start",
        "presentation_role",
        "source_restated_status",
        "source_share_basis_id",
        "source_unit",
        "statement_type",
        "stock_id",
    ):
        op.create_index(
            f"ix_tw_financial_statement_fact_{column}",
            "tw_financial_statement_fact",
            [column],
        )
    op.create_index(
        "ix_tw_financial_statement_fact_stock_metric_period",
        "tw_financial_statement_fact",
        ["stock_id", "metric_code", "period_end"],
    )

    op.create_table(
        "tw_financial_corporate_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("old_share_basis", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("new_share_basis", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("adjustment_ratio", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("adjustment_purpose", sa.String(length=40), nullable=False),
        sa.Column("source_document_id", sa.String(length=160), nullable=False),
        sa.Column("source_document_url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "adjustment_purpose IN "
            "('price_series', 'per_share_financials', 'shares_outstanding', "
            "'informational_only')",
            name="ck_tw_financial_corporate_action_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'unverified', 'disputed', 'revoked')",
            name="ck_tw_financial_corporate_action_status",
        ),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "stock_id",
            "action_type",
            "effective_date",
            "adjustment_purpose",
            "source_document_id",
            name="uq_tw_financial_corporate_action_source_identity",
        ),
    )
    for column in (
        "action_type",
        "adjustment_purpose",
        "announced_at",
        "content_hash",
        "effective_date",
        "id",
        "raw_result_id",
        "record_date",
        "source_id",
        "status",
        "stock_id",
    ):
        op.create_index(
            f"ix_tw_financial_corporate_action_{column}",
            "tw_financial_corporate_action",
            [column],
        )
    op.create_index(
        "ix_tw_financial_corporate_action_stock_effective",
        "tw_financial_corporate_action",
        ["stock_id", "effective_date"],
    )

    op.create_table(
        "tw_financial_normalized_fact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_fact_id", sa.Integer(), nullable=False),
        sa.Column("comparison_basis_id", sa.String(length=160), nullable=False),
        sa.Column("normalization_mode", sa.String(length=30), nullable=False),
        sa.Column("normalized_value", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("normalized_unit", sa.String(length=40), nullable=True),
        sa.Column("adjustment_factor", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("normalization_status", sa.String(length=30), nullable=False),
        sa.Column("normalization_version", sa.String(length=80), nullable=False),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_usable", sa.Boolean(), nullable=False),
        sa.Column("issue_codes_json", sa.Text(), nullable=False),
        sa.Column("lineage_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalization_mode IN ('current_comparable', 'as_reported_as_of')",
            name="ck_tw_financial_normalized_fact_mode",
        ),
        sa.CheckConstraint(
            "normalization_status IN "
            "('normalized', 'unchanged', 'blocked', 'disputed', 'not_applicable')",
            name="ck_tw_financial_normalized_fact_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_fact_id"],
            ["tw_financial_statement_fact.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_fact_id",
            "comparison_basis_id",
            "normalization_version",
            "normalization_mode",
            name="uq_tw_financial_normalized_fact_version",
        ),
    )
    for column in (
        "comparison_basis_id",
        "decision_usable",
        "derived_at",
        "id",
        "normalization_mode",
        "normalization_status",
        "normalization_version",
        "normalized_unit",
        "source_fact_id",
    ):
        op.create_index(
            f"ix_tw_financial_normalized_fact_{column}",
            "tw_financial_normalized_fact",
            [column],
        )
    op.create_index(
        "ix_tw_financial_normalized_fact_basis_status",
        "tw_financial_normalized_fact",
        ["comparison_basis_id", "normalization_status"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in (
        "tw_financial_normalized_fact",
        "tw_financial_corporate_action",
        "tw_financial_statement_fact",
        "tw_financial_filing",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
