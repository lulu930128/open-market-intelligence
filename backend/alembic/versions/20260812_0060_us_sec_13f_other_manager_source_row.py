"""Preserve repeated SEC 13F other-manager sequence numbers.

Revision ID: 20260812_0060
Revises: 20260812_0059
Create Date: 2026-08-12 20:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0060"
down_revision: str | Sequence[str] | None = "20260812_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("us_sec_13f_other_manager"):
        return
    columns = {item["name"] for item in inspector.get_columns("us_sec_13f_other_manager")}
    if "source_row_sequence" not in columns:
        op.add_column(
            "us_sec_13f_other_manager",
            sa.Column("source_row_sequence", sa.Integer(), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE us_sec_13f_other_manager "
                "SET source_row_sequence = id WHERE source_row_sequence IS NULL"
            )
        )

    unique_names = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_unique_constraints(
            "us_sec_13f_other_manager"
        )
    }
    with op.batch_alter_table("us_sec_13f_other_manager") as batch:
        if "uq_us_sec_13f_other_manager_sequence" in unique_names:
            batch.drop_constraint(
                "uq_us_sec_13f_other_manager_sequence",
                type_="unique",
            )
        batch.alter_column(
            "source_row_sequence",
            existing_type=sa.Integer(),
            nullable=False,
        )
        if "uq_us_sec_13f_other_manager_source_row" not in unique_names:
            batch.create_unique_constraint(
                "uq_us_sec_13f_other_manager_source_row",
                ["filing_id", "source_row_sequence"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("us_sec_13f_other_manager"):
        return
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT filing_id, sequence_number FROM us_sec_13f_other_manager "
            "GROUP BY filing_id, sequence_number HAVING count(*) > 1"
            ")"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            "Cannot downgrade SEC 13F other-manager identity without losing repeated official rows."
        )
    unique_names = {
        item["name"]
        for item in inspector.get_unique_constraints("us_sec_13f_other_manager")
    }
    with op.batch_alter_table("us_sec_13f_other_manager") as batch:
        if "uq_us_sec_13f_other_manager_source_row" in unique_names:
            batch.drop_constraint(
                "uq_us_sec_13f_other_manager_source_row",
                type_="unique",
            )
        batch.create_unique_constraint(
            "uq_us_sec_13f_other_manager_sequence",
            ["filing_id", "sequence_number"],
        )
        batch.drop_column("source_row_sequence")
