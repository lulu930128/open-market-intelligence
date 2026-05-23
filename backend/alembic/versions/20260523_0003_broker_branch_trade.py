"""Add broker branch one-day trade table.

Revision ID: 20260523_0003
Revises: 20260523_0002
Create Date: 2026-05-23 23:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260523_0003"
down_revision: str | Sequence[str] | None = "20260523_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    if _has_table("broker_branch_trade_daily"):
        return

    op.create_table(
        "broker_branch_trade_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=120), nullable=True),
        sa.Column("branch_code", sa.String(length=20), nullable=False),
        sa.Column("branch_name", sa.String(length=160), nullable=False),
        sa.Column("buy_lots", sa.BigInteger(), nullable=True),
        sa.Column("sell_lots", sa.BigInteger(), nullable=True),
        sa.Column("net_lots", sa.BigInteger(), nullable=True),
        sa.Column("buy_avg_price", sa.Float(), nullable=True),
        sa.Column("sell_avg_price", sa.Float(), nullable=True),
        sa.Column("buy_rank", sa.Integer(), nullable=True),
        sa.Column("sell_rank", sa.Integer(), nullable=True),
        sa.Column("source_label", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "stock_id",
            "trade_date",
            "branch_code",
            name="uq_broker_branch_source_stock_date_branch",
        ),
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_branch_code"),
        "broker_branch_trade_daily",
        ["branch_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_branch_name"),
        "broker_branch_trade_daily",
        ["branch_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_id"),
        "broker_branch_trade_daily",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_raw_result_id"),
        "broker_branch_trade_daily",
        ["raw_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_source_id"),
        "broker_branch_trade_daily",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_stock_id"),
        "broker_branch_trade_daily",
        ["stock_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broker_branch_trade_daily_trade_date"),
        "broker_branch_trade_daily",
        ["trade_date"],
        unique=False,
    )


def downgrade() -> None:
    if not _has_table("broker_branch_trade_daily"):
        return

    for index_name in (
        "ix_broker_branch_trade_daily_trade_date",
        "ix_broker_branch_trade_daily_stock_id",
        "ix_broker_branch_trade_daily_source_id",
        "ix_broker_branch_trade_daily_raw_result_id",
        "ix_broker_branch_trade_daily_id",
        "ix_broker_branch_trade_daily_branch_name",
        "ix_broker_branch_trade_daily_branch_code",
    ):
        if _has_index("broker_branch_trade_daily", index_name):
            op.drop_index(op.f(index_name), table_name="broker_branch_trade_daily")

    op.drop_table("broker_branch_trade_daily")
