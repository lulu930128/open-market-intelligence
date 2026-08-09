"""Add point-in-time cross-market signal snapshots.

Revision ID: 20260809_0053
Revises: 20260809_0052
Create Date: 2026-08-09 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0053"
down_revision: str | Sequence[str] | None = "20260809_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "cross_market_signal_snapshot"


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table(TABLE_NAME):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=60), nullable=False),
        sa.Column("methodology_version", sa.String(length=80), nullable=False),
        sa.Column("relation_snapshot_version", sa.String(length=120), nullable=False),
        sa.Column("target_market", sa.String(length=16), nullable=False),
        sa.Column("target_canonical_symbol", sa.String(length=80), nullable=False),
        sa.Column("target_provider_symbol", sa.String(length=80), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("decision_usable", sa.Boolean(), nullable=False),
        sa.Column("coverage_ratio", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("materialized_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'partial', 'stale', 'limited', 'blocked', 'not_applicable')",
            name="ck_cross_market_signal_snapshot_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            name="uq_cross_market_signal_snapshot_id",
        ),
        sa.UniqueConstraint(
            "target_canonical_symbol",
            "decision_at",
            "methodology_version",
            name="uq_cross_market_signal_snapshot_target_decision_method",
        ),
    )

    for column_name in (
        "id",
        "schema_version",
        "methodology_version",
        "relation_snapshot_version",
        "target_market",
        "target_canonical_symbol",
        "target_provider_symbol",
        "decision_at",
        "as_of",
        "status",
        "decision_usable",
        "payload_hash",
        "created_at",
    ):
        op.create_index(
            f"ix_cross_market_signal_snapshot_{column_name}",
            TABLE_NAME,
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_cross_market_signal_snapshot_target_decision",
        TABLE_NAME,
        ["target_canonical_symbol", "decision_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    if _has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
