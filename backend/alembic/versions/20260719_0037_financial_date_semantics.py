"""separate financial period release filing and fetch dates

Revision ID: 20260719_0037
Revises: 20260718_0036
Create Date: 2026-07-19 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260719_0037"
down_revision: str | Sequence[str] | None = "20260718_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("financial_metric_quarterly"):
        return

    columns = {column["name"] for column in inspector.get_columns("financial_metric_quarterly")}
    if "released_at" not in columns:
        op.add_column(
            "financial_metric_quarterly",
            sa.Column("released_at", sa.Date(), nullable=True),
        )
        op.create_index(
            "ix_financial_metric_quarterly_released_at",
            "financial_metric_quarterly",
            ["released_at"],
        )
    if "filed_at" not in columns:
        op.add_column(
            "financial_metric_quarterly",
            sa.Column("filed_at", sa.Date(), nullable=True),
        )
        op.create_index(
            "ix_financial_metric_quarterly_filed_at",
            "financial_metric_quarterly",
            ["filed_at"],
        )

    op.execute(
        sa.text(
            "UPDATE financial_metric_quarterly "
            "SET released_at = report_date "
            "WHERE report_date IS NOT NULL "
            "AND NOT EXISTS ("
            "SELECT 1 FROM raw_fetch_result "
            "WHERE raw_fetch_result.id = financial_metric_quarterly.raw_result_id "
            "AND raw_fetch_result.parser_version = 'mops-financial-metrics-history-v1'"
            ")"
        )
    )
    op.execute(
        sa.text(
            "UPDATE financial_metric_quarterly "
            "SET report_date = NULL, released_at = NULL "
            "WHERE EXISTS ("
            "SELECT 1 FROM raw_fetch_result "
            "WHERE raw_fetch_result.id = financial_metric_quarterly.raw_result_id "
            "AND raw_fetch_result.parser_version = 'mops-financial-metrics-history-v1'"
            ")"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("financial_metric_quarterly"):
        return
    columns = {column["name"] for column in inspector.get_columns("financial_metric_quarterly")}
    if "filed_at" in columns:
        op.drop_index("ix_financial_metric_quarterly_filed_at", table_name="financial_metric_quarterly")
        op.drop_column("financial_metric_quarterly", "filed_at")
    if "released_at" in columns:
        op.drop_index("ix_financial_metric_quarterly_released_at", table_name="financial_metric_quarterly")
        op.drop_column("financial_metric_quarterly", "released_at")
