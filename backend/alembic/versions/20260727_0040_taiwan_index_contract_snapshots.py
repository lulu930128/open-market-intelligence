"""Add fixed-slot Taiwan index contract snapshots.

Revision ID: 20260727_0040
Revises: 20260727_0039
Create Date: 2026-07-27 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0040"
down_revision: str | Sequence[str] | None = "20260727_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("taiwan_index_contract_snapshot"):
        return
    op.create_table(
        "taiwan_index_contract_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("index_id", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("capture_slot", sa.String(length=5), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_phase", sa.String(length=40), nullable=True),
        sa.Column("capture_status", sa.String(length=30), nullable=False),
        sa.Column("selected_candidate", sa.String(length=40), nullable=True),
        sa.Column("selected_value", sa.Float(), nullable=True),
        sa.Column("selection_reason", sa.String(length=160), nullable=True),
        sa.Column("official_close_status", sa.String(length=40), nullable=True),
        sa.Column(
            "source",
            sa.String(length=120),
            nullable=False,
            server_default="taiwan_index_contract_capture",
        ),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_id",
            "trade_date",
            "capture_slot",
            name="uq_tw_index_contract_index_date_slot",
        ),
    )
    for column in (
        "id",
        "index_id",
        "market",
        "trade_date",
        "capture_slot",
        "scheduled_at",
        "captured_at",
        "session_phase",
        "capture_status",
        "official_close_status",
    ):
        op.create_index(
            op.f(f"ix_taiwan_index_contract_snapshot_{column}"),
            "taiwan_index_contract_snapshot",
            [column],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("taiwan_index_contract_snapshot"):
        op.drop_table("taiwan_index_contract_snapshot")
