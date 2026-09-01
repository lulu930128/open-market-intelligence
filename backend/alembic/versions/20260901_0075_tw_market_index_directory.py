"""Add durable Taiwan market-index directory snapshots.

Revision ID: 20260901_0075
Revises: 20260830_0074
Create Date: 2026-09-01 01:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260901_0075"
down_revision: str | Sequence[str] | None = "20260830_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SNAPSHOT_TABLE = "taiwan_market_index_directory_snapshot"
ITEM_TABLE = "taiwan_market_index_directory_item"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(SNAPSHOT_TABLE):
        op.create_table(
            SNAPSHOT_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=80), nullable=False),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("authority", sa.String(length=40), nullable=False),
            sa.Column("raw_contract_version", sa.String(length=96), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("content_hash", sa.String(length=128), nullable=False),
            sa.Column("item_count", sa.Integer(), nullable=False),
            sa.Column("observation_state", sa.String(length=24), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
            sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "raw_result_id",
                name="uq_tw_market_index_directory_raw_result",
            ),
        )
        for column in (
            "id",
            "source_id",
            "raw_result_id",
            "provider",
            "source",
            "authority",
            "market",
            "fetched_at",
            "content_hash",
            "observation_state",
        ):
            op.create_index(
                f"ix_{SNAPSHOT_TABLE}_{column}",
                SNAPSHOT_TABLE,
                [column],
                unique=column == "raw_result_id",
            )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(ITEM_TABLE):
        op.create_table(
            ITEM_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("close_value", sa.Float(), nullable=True),
            sa.Column("price_change", sa.Float(), nullable=True),
            sa.Column("change_pct", sa.Float(), nullable=True),
            sa.Column("trade_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["snapshot_id"],
                [f"{SNAPSHOT_TABLE}.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "snapshot_id",
                "rank",
                name="uq_tw_market_index_directory_snapshot_rank",
            ),
            sa.UniqueConstraint(
                "snapshot_id",
                "name",
                name="uq_tw_market_index_directory_snapshot_name",
            ),
        )
        for column in ("id", "snapshot_id", "market", "name", "trade_date"):
            op.create_index(
                f"ix_{ITEM_TABLE}_{column}",
                ITEM_TABLE,
                [column],
                unique=False,
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(ITEM_TABLE):
        op.drop_table(ITEM_TABLE)
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(SNAPSHOT_TABLE):
        op.drop_table(SNAPSHOT_TABLE)
