"""Add application settings table.

Revision ID: 20260619_0015
Revises: 20260615_0014
Create Date: 2026-06-19 15:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260619_0015"
down_revision: str | Sequence[str] | None = "20260615_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("app_setting"):
        return

    op.create_table(
        "app_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setting_key", sa.String(length=120), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_setting_id"), "app_setting", ["id"], unique=False)
    op.create_index(op.f("ix_app_setting_setting_key"), "app_setting", ["setting_key"], unique=True)
    op.create_index(op.f("ix_app_setting_source"), "app_setting", ["source"], unique=False)


def downgrade() -> None:
    if _has_table("app_setting"):
        op.drop_table("app_setting")
