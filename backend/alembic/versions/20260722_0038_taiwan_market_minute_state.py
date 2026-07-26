"""Add Taiwan minute-level market state history.

Revision ID: 20260722_0038
Revises: 20260719_0037
Create Date: 2026-07-22 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260722_0038"
down_revision: str | Sequence[str] | None = "20260719_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("taiwan_market_minute_state"):
        return

    op.create_table(
        "taiwan_market_minute_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("index_id", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("minute_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_status", sa.String(length=30), nullable=False),
        sa.Column("breadth_status", sa.String(length=30), nullable=False),
        sa.Column("breadth_scope", sa.String(length=40), nullable=True),
        sa.Column("quality_status", sa.String(length=30), nullable=False),
        sa.Column("index_value", sa.Float(), nullable=True),
        sa.Column("index_change", sa.Float(), nullable=True),
        sa.Column("index_change_pct", sa.Float(), nullable=True),
        sa.Column("advance_count", sa.Integer(), nullable=True),
        sa.Column("decline_count", sa.Integer(), nullable=True),
        sa.Column("unchanged_count", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("limit_up_count", sa.Integer(), nullable=True),
        sa.Column("limit_down_count", sa.Integer(), nullable=True),
        sa.Column("unknown_count", sa.Integer(), nullable=True),
        sa.Column("missing_count", sa.Integer(), nullable=True),
        sa.Column("cumulative_trade_value", sa.BigInteger(), nullable=True),
        sa.Column("estimated_full_day_trade_value", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_category", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("official_flag", sa.Boolean(), nullable=False),
        sa.Column("derived_flag", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "index_id",
            "minute_at",
            name="uq_tw_market_minute_state_market_index_time",
        ),
    )
    for column in (
        "id",
        "market",
        "index_id",
        "trade_date",
        "minute_at",
        "session_status",
        "breadth_status",
        "quality_status",
        "source",
        "source_category",
    ):
        op.create_index(
            op.f(f"ix_taiwan_market_minute_state_{column}"),
            "taiwan_market_minute_state",
            [column],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("taiwan_market_minute_state"):
        op.drop_table("taiwan_market_minute_state")
