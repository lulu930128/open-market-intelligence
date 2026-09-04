"""add canonical Taiwan issued shares daily evidence

Revision ID: 20260904_0079
Revises: 20260902_0078
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0079"
down_revision: str | Sequence[str] | None = "20260902_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("taiwan_issued_shares_daily"):
        return
    op.create_table(
        "taiwan_issued_shares_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("issued_shares", sa.BigInteger(), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "stock_id",
            "trade_date",
            name="uq_tw_issued_shares_market_stock_date",
        ),
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_id"),
        "taiwan_issued_shares_daily",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_market"),
        "taiwan_issued_shares_daily",
        ["market"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_raw_result_id"),
        "taiwan_issued_shares_daily",
        ["raw_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_source_id"),
        "taiwan_issued_shares_daily",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_stock_id"),
        "taiwan_issued_shares_daily",
        ["stock_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taiwan_issued_shares_daily_trade_date"),
        "taiwan_issued_shares_daily",
        ["trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_tw_issued_shares_market_date_stock",
        "taiwan_issued_shares_daily",
        ["market", "trade_date", "stock_id"],
        unique=False,
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("taiwan_issued_shares_daily"):
        return
    op.drop_index(
        "ix_tw_issued_shares_market_date_stock",
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_trade_date"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_stock_id"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_source_id"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_raw_result_id"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_market"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_index(
        op.f("ix_taiwan_issued_shares_daily_id"),
        table_name="taiwan_issued_shares_daily",
    )
    op.drop_table("taiwan_issued_shares_daily")
