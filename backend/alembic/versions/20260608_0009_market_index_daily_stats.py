"""Add market index daily statistics.

Revision ID: 20260608_0009
Revises: 20260605_0008
Create Date: 2026-06-08 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260608_0009"
down_revision: str | Sequence[str] | None = "20260605_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("market_index_daily_stat"):
        return

    op.create_table(
        "market_index_daily_stat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("index_id", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_volume", sa.BigInteger(), nullable=True),
        sa.Column("trade_value", sa.BigInteger(), nullable=True),
        sa.Column("transaction_count", sa.BigInteger(), nullable=True),
        sa.Column("close_value", sa.Float(), nullable=True),
        sa.Column("price_change", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_id",
            "trade_date",
            name="uq_market_index_daily_stat_index_date",
        ),
    )
    op.create_index(
        op.f("ix_market_index_daily_stat_id"),
        "market_index_daily_stat",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_index_daily_stat_index_id"),
        "market_index_daily_stat",
        ["index_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_index_daily_stat_market"),
        "market_index_daily_stat",
        ["market"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_index_daily_stat_source"),
        "market_index_daily_stat",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_index_daily_stat_trade_date"),
        "market_index_daily_stat",
        ["trade_date"],
        unique=False,
    )


def downgrade() -> None:
    if _has_table("market_index_daily_stat"):
        op.drop_table("market_index_daily_stat")
