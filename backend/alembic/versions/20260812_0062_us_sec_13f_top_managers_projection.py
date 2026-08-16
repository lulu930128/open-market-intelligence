"""Add bounded top-manager materialization for SEC 13F symbol reads.

Revision ID: 20260812_0062
Revises: 20260812_0061
Create Date: 2026-08-12 21:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0062"
down_revision: str | Sequence[str] | None = "20260812_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("us_sec_13f_symbol_quarter")
    }
    if "top_managers_json" not in columns:
        op.add_column(
            "us_sec_13f_symbol_quarter",
            sa.Column("top_managers_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("us_sec_13f_symbol_quarter")
    }
    if "top_managers_json" in columns:
        op.drop_column("us_sec_13f_symbol_quarter", "top_managers_json")
