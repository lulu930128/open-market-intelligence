"""Add typed Taiwan realtime depth and auction observations.

Revision ID: 20260826_0069
Revises: 20260825_0068
Create Date: 2026-08-26 12:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260826_0069"
down_revision: str | Sequence[str] | None = "20260825_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEPTH_TABLE = "taiwan_stock_depth_snapshot"
DEPTH_LEVEL_TABLE = "taiwan_stock_depth_level"
AUCTION_TABLE = "taiwan_stock_auction_snapshot"


def _create_indexes(table_name: str, columns: tuple[str, ...]) -> None:
    for column_name in columns:
        op.create_index(
            f"ix_{table_name}_{column_name}",
            table_name,
            [column_name],
            unique=False,
        )


def upgrade() -> None:
    existing = {
        table_name
        for table_name in (DEPTH_TABLE, DEPTH_LEVEL_TABLE, AUCTION_TABLE)
        if sa.inspect(op.get_bind()).has_table(table_name)
    }
    if existing:
        expected = {DEPTH_TABLE, DEPTH_LEVEL_TABLE, AUCTION_TABLE}
        if existing != expected:
            raise RuntimeError(
                "partial Taiwan realtime schema exists; refusing an ambiguous repair"
            )
        # The baseline migration creates current metadata on a brand-new database.
        # Existing databases at 0068 do not have these tables and continue below.
        return
    op.create_table(
        DEPTH_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_session", sa.String(length=40), nullable=False),
        sa.Column("observation_state", sa.String(length=30), nullable=False),
        sa.Column("depth_capability", sa.String(length=30), nullable=False),
        sa.Column("raw_contract_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_registry.id"],
            name="fk_tw_depth_snapshot_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
            name="fk_tw_depth_snapshot_raw_result_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "stock_id",
            "event_at",
            name="uq_tw_stock_depth_provider_stock_time",
        ),
    )
    _create_indexes(
        DEPTH_TABLE,
        (
            "id",
            "source_id",
            "raw_result_id",
            "provider",
            "source",
            "market",
            "stock_id",
            "event_at",
            "received_at",
            "fetched_at",
            "market_session",
        ),
    )

    op.create_table(
        DEPTH_LEVEL_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=True),
        sa.Column("quantity_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("quantity_unit", sa.String(length=30), nullable=True),
        sa.Column("original_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("original_unit", sa.String(length=30), nullable=True),
        sa.Column("scale", sa.Numeric(28, 8), nullable=True),
        sa.Column("price_state", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "side IN ('bid', 'ask')",
            name="ck_tw_stock_depth_level_side",
        ),
        sa.CheckConstraint(
            "level >= 1 AND level <= 20",
            name="ck_tw_stock_depth_level_rank",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            [f"{DEPTH_TABLE}.id"],
            name="fk_tw_depth_level_snapshot_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "side",
            "level",
            name="uq_tw_stock_depth_level_identity",
        ),
    )
    _create_indexes(DEPTH_LEVEL_TABLE, ("id", "snapshot_id", "side"))

    op.create_table(
        AUCTION_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_session", sa.String(length=40), nullable=False),
        sa.Column("observation_state", sa.String(length=30), nullable=False),
        sa.Column("auction_type", sa.String(length=30), nullable=False),
        sa.Column("indicative_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("indicative_quantity_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("indicative_quantity_unit", sa.String(length=30), nullable=True),
        sa.Column("indicative_original_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("indicative_original_unit", sa.String(length=30), nullable=True),
        sa.Column("indicative_scale", sa.Numeric(28, 8), nullable=True),
        sa.Column("best_bid_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("best_bid_level", sa.Integer(), nullable=True),
        sa.Column("best_bid_quantity_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("best_bid_quantity_unit", sa.String(length=30), nullable=True),
        sa.Column("best_bid_price_state", sa.String(length=30), nullable=True),
        sa.Column("best_ask_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("best_ask_level", sa.Integer(), nullable=True),
        sa.Column("best_ask_quantity_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("best_ask_quantity_unit", sa.String(length=30), nullable=True),
        sa.Column("best_ask_price_state", sa.String(length=30), nullable=True),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("raw_contract_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provisional = 1",
            name="ck_tw_stock_auction_provisional",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_registry.id"],
            name="fk_tw_auction_snapshot_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
            name="fk_tw_auction_snapshot_raw_result_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "stock_id",
            "event_at",
            "auction_type",
            name="uq_tw_stock_auction_provider_stock_time_type",
        ),
    )
    _create_indexes(
        AUCTION_TABLE,
        (
            "id",
            "source_id",
            "raw_result_id",
            "provider",
            "source",
            "market",
            "stock_id",
            "trade_date",
            "event_at",
            "received_at",
            "fetched_at",
            "market_session",
            "auction_type",
        ),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(AUCTION_TABLE):
        op.drop_table(AUCTION_TABLE)
    if inspector.has_table(DEPTH_LEVEL_TABLE):
        op.drop_table(DEPTH_LEVEL_TABLE)
    if inspector.has_table(DEPTH_TABLE):
        op.drop_table(DEPTH_TABLE)
