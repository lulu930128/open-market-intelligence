"""Add reviewed Taiwan financial basis assessments.

Revision ID: 20260731_0048
Revises: 20260730_0047
Create Date: 2026-07-31 02:35:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0048"
down_revision: str | Sequence[str] | None = "20260730_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("tw_financial_basis_assessment"):
        return
    op.create_table(
        "tw_financial_basis_assessment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("normalization_mode", sa.String(length=30), nullable=False),
        sa.Column("assessment_type", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("issue_code", sa.String(length=120), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("resolution_requirements_json", sa.Text(), nullable=False),
        sa.Column("evidence_package_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalization_mode IN ('current_comparable', 'as_reported_as_of')",
            name="ck_tw_financial_basis_assessment_mode",
        ),
        sa.CheckConstraint(
            "outcome IN ('blocked', 'resolved', 'revoked')",
            name="ck_tw_financial_basis_assessment_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "normalization_mode",
            "assessment_type",
            "evidence_package_hash",
            name="uq_tw_financial_basis_assessment_evidence",
        ),
    )
    for column in (
        "id",
        "raw_result_id",
        "stock_id",
        "normalization_mode",
        "assessment_type",
        "outcome",
        "effective_date",
        "issue_code",
        "evidence_package_hash",
        "known_at",
        "reviewed_at",
    ):
        op.create_index(
            f"ix_tw_financial_basis_assessment_{column}",
            "tw_financial_basis_assessment",
            [column],
        )
    op.create_index(
        "ix_tw_financial_basis_assessment_active",
        "tw_financial_basis_assessment",
        ["stock_id", "normalization_mode", "assessment_type", "reviewed_at"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tw_financial_basis_assessment"):
        return
    for index_name in (
        "ix_tw_financial_basis_assessment_active",
        "ix_tw_financial_basis_assessment_reviewed_at",
        "ix_tw_financial_basis_assessment_known_at",
        "ix_tw_financial_basis_assessment_evidence_package_hash",
        "ix_tw_financial_basis_assessment_issue_code",
        "ix_tw_financial_basis_assessment_effective_date",
        "ix_tw_financial_basis_assessment_outcome",
        "ix_tw_financial_basis_assessment_assessment_type",
        "ix_tw_financial_basis_assessment_normalization_mode",
        "ix_tw_financial_basis_assessment_stock_id",
        "ix_tw_financial_basis_assessment_raw_result_id",
        "ix_tw_financial_basis_assessment_id",
    ):
        op.drop_index(
            index_name,
            table_name="tw_financial_basis_assessment",
        )
    op.drop_table("tw_financial_basis_assessment")
