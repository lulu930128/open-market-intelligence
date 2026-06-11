"""Add market intraday bars.

Revision ID: 20260610_0011
Revises: 20260609_0010
Create Date: 2026-06-10 20:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260610_0011"
down_revision: str | Sequence[str] | None = "20260609_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("market_intraday_bar"):
        return

    op.create_table(
        "market_intraday_bar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=True),
        sa.Column("symbol", sa.String(length=40), nullable=True),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("trade_volume", sa.BigInteger(), nullable=True),
        sa.Column("trade_value", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "stock_id",
            "interval",
            "bar_time",
            name="uq_market_intraday_provider_stock_interval_time",
        ),
    )
    op.create_index(
        op.f("ix_market_intraday_bar_id"),
        "market_intraday_bar",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_bar_time"),
        "market_intraday_bar",
        ["bar_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_interval"),
        "market_intraday_bar",
        ["interval"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_market"),
        "market_intraday_bar",
        ["market"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_provider"),
        "market_intraday_bar",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_source"),
        "market_intraday_bar",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_stock_id"),
        "market_intraday_bar",
        ["stock_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_intraday_bar_symbol"),
        "market_intraday_bar",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    if _has_table("market_intraday_bar"):
        op.drop_table("market_intraday_bar")
