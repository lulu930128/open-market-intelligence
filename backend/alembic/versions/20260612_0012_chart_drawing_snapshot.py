"""Add chart drawing snapshots.

Revision ID: 20260612_0012
Revises: 20260610_0011
Create Date: 2026-06-12 20:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260612_0012"
down_revision: str | Sequence[str] | None = "20260610_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("chart_drawing_snapshot"):
        return

    op.create_table(
        "chart_drawing_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("time_mode", sa.String(length=20), nullable=True),
        sa.Column("selected_drawing_id", sa.String(length=120), nullable=True),
        sa.Column("drawing_count", sa.Integer(), nullable=False),
        sa.Column("drawings_json", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "symbol",
            "timeframe",
            name="uq_chart_drawing_snapshot_market_symbol_timeframe",
        ),
    )
    op.create_index(
        op.f("ix_chart_drawing_snapshot_id"),
        "chart_drawing_snapshot",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chart_drawing_snapshot_market"),
        "chart_drawing_snapshot",
        ["market"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chart_drawing_snapshot_source"),
        "chart_drawing_snapshot",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chart_drawing_snapshot_symbol"),
        "chart_drawing_snapshot",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chart_drawing_snapshot_timeframe"),
        "chart_drawing_snapshot",
        ["timeframe"],
        unique=False,
    )


def downgrade() -> None:
    if _has_table("chart_drawing_snapshot"):
        op.drop_table("chart_drawing_snapshot")
