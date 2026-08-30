"""Add canonical persisted US quote snapshots.

Revision ID: 20260830_0074
Revises: 20260829_0073t
Create Date: 2026-08-30 10:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260830_0074"
down_revision: str | Sequence[str] | None = "20260829_0073t"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "us_quote_snapshot"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE_NAME):
        return
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("venue", sa.String(length=40), nullable=False),
        sa.Column("instrument_type", sa.String(length=24), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("observation_state", sa.String(length=32), nullable=False),
        sa.Column("trade_state", sa.String(length=32), nullable=False),
        sa.Column("last_trade_price", sa.Float(), nullable=True),
        sa.Column("last_trade_quantity", sa.BigInteger(), nullable=True),
        sa.Column("cumulative_quantity", sa.BigInteger(), nullable=True),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("previous_close", sa.Float(), nullable=True),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("raw_contract_version", sa.String(length=96), nullable=False),
        sa.Column("raw_payload_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            "event_at",
            name="uq_us_quote_snapshot_provider_symbol_event",
        ),
    )
    op.create_index("ix_us_quote_snapshot_id", TABLE_NAME, ["id"], unique=False)
    op.create_index("ix_us_quote_snapshot_source_id", TABLE_NAME, ["source_id"], unique=False)
    op.create_index("ix_us_quote_snapshot_raw_result_id", TABLE_NAME, ["raw_result_id"], unique=False)
    op.create_index("ix_us_quote_snapshot_provider", TABLE_NAME, ["provider"], unique=False)
    op.create_index("ix_us_quote_snapshot_source", TABLE_NAME, ["source"], unique=False)
    op.create_index("ix_us_quote_snapshot_symbol", TABLE_NAME, ["symbol"], unique=False)
    op.create_index("ix_us_quote_snapshot_venue", TABLE_NAME, ["venue"], unique=False)
    op.create_index("ix_us_quote_snapshot_trade_date", TABLE_NAME, ["trade_date"], unique=False)
    op.create_index("ix_us_quote_snapshot_event_at", TABLE_NAME, ["event_at"], unique=False)
    op.create_index("ix_us_quote_snapshot_fetched_at", TABLE_NAME, ["fetched_at"], unique=False)
    op.create_index("ix_us_quote_snapshot_raw_payload_hash", TABLE_NAME, ["raw_payload_hash"], unique=False)
    op.create_index(
        "ix_us_quote_snapshot_symbol_event",
        TABLE_NAME,
        ["symbol", "event_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
