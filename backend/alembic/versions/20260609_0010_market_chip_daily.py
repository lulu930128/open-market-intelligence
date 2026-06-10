"""Add market chip daily summary.

Revision ID: 20260609_0010
Revises: 20260608_0009
Create Date: 2026-06-09 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260609_0010"
down_revision: str | Sequence[str] | None = "20260608_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("market_chip_daily"):
        return

    op.create_table(
        "market_chip_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("index_id", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close_value", sa.Float(), nullable=True),
        sa.Column("price_change", sa.Float(), nullable=True),
        sa.Column("price_change_pct", sa.Float(), nullable=True),
        sa.Column("trade_value", sa.BigInteger(), nullable=True),
        sa.Column("foreign_futures_net_oi", sa.Integer(), nullable=True),
        sa.Column("foreign_futures_net_oi_change", sa.Integer(), nullable=True),
        sa.Column("retail_futures_net_oi", sa.Integer(), nullable=True),
        sa.Column("retail_futures_net_oi_change", sa.Integer(), nullable=True),
        sa.Column("total_institutional_net_value", sa.BigInteger(), nullable=True),
        sa.Column("foreign_investor_net_value", sa.BigInteger(), nullable=True),
        sa.Column("investment_trust_net_value", sa.BigInteger(), nullable=True),
        sa.Column("dealer_net_value", sa.BigInteger(), nullable=True),
        sa.Column("dealer_self_net_value", sa.BigInteger(), nullable=True),
        sa.Column("dealer_hedge_net_value", sa.BigInteger(), nullable=True),
        sa.Column("government_bank_net_value", sa.BigInteger(), nullable=True),
        sa.Column("margin_balance_change_value", sa.BigInteger(), nullable=True),
        sa.Column("margin_balance_change_shares", sa.BigInteger(), nullable=True),
        sa.Column("short_balance_change_shares", sa.BigInteger(), nullable=True),
        sa.Column("source_grade", sa.String(length=50), nullable=False),
        sa.Column("source_details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_id",
            "trade_date",
            name="uq_market_chip_daily_index_date",
        ),
    )
    op.create_index(
        op.f("ix_market_chip_daily_id"),
        "market_chip_daily",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_chip_daily_index_id"),
        "market_chip_daily",
        ["index_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_chip_daily_market"),
        "market_chip_daily",
        ["market"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_chip_daily_source_grade"),
        "market_chip_daily",
        ["source_grade"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_chip_daily_trade_date"),
        "market_chip_daily",
        ["trade_date"],
        unique=False,
    )


def downgrade() -> None:
    if _has_table("market_chip_daily"):
        op.drop_table("market_chip_daily")
