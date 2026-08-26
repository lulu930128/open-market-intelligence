"""Add canonical lineage for Taiwan intraday bars.

Revision ID: 20260826_0070
Revises: 20260826_0069
Create Date: 2026-08-26 13:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260826_0070"
down_revision: str | Sequence[str] | None = "20260826_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "market_intraday_bar_lineage"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        return
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bar_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("authority", sa.String(length=30), nullable=False),
        sa.Column("raw_contract_version", sa.String(length=128), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalization", sa.String(length=30), nullable=False),
        sa.Column("source_interval", sa.String(length=16), nullable=False),
        sa.Column("calculation_version", sa.String(length=64), nullable=True),
        sa.Column("component_raw_result_ids_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bar_id"],
            ["market_intraday_bar.id"],
            name="fk_intraday_bar_lineage_bar_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_registry.id"],
            name="fk_intraday_bar_lineage_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
            name="fk_intraday_bar_lineage_raw_result_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bar_id",
            name="uq_market_intraday_bar_lineage_bar_id",
        ),
    )
    for column_name in (
        "id",
        "bar_id",
        "source_id",
        "raw_result_id",
        "provider",
        "source",
        "event_at",
        "fetched_at",
    ):
        op.create_index(
            f"ix_{TABLE_NAME}_{column_name}",
            TABLE_NAME,
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
