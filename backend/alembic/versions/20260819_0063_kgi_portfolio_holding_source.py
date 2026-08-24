"""Add KGI portfolio source metadata and nullable cost basis.

Revision ID: 20260819_0063
Revises: 20260812_0062
Create Date: 2026-08-19 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260819_0063"
down_revision: str | Sequence[str] | None = "20260812_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("portfolio_holding")
    }


def upgrade() -> None:
    columns = _columns()
    if "source" not in columns:
        op.add_column(
            "portfolio_holding",
            sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        )
        op.create_index(
            "ix_portfolio_holding_source",
            "portfolio_holding",
            ["source"],
            unique=False,
        )
    if "source_updated_at" not in columns:
        op.add_column(
            "portfolio_holding",
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    with op.batch_alter_table("portfolio_holding", recreate="always") as batch_op:
        batch_op.alter_column(
            "cost_amount",
            existing_type=sa.Float(),
            existing_nullable=False,
            nullable=True,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE portfolio_holding SET cost_amount = 0 "
            "WHERE cost_amount IS NULL"
        )
    )
    with op.batch_alter_table("portfolio_holding", recreate="always") as batch_op:
        batch_op.alter_column(
            "cost_amount",
            existing_type=sa.Float(),
            existing_nullable=True,
            nullable=False,
        )

    columns = _columns()
    if "source_updated_at" in columns:
        op.drop_column("portfolio_holding", "source_updated_at")
    if "source" in columns:
        indexes = {
            item["name"]
            for item in sa.inspect(op.get_bind()).get_indexes("portfolio_holding")
        }
        if "ix_portfolio_holding_source" in indexes:
            op.drop_index("ix_portfolio_holding_source", table_name="portfolio_holding")
        op.drop_column("portfolio_holding", "source")
