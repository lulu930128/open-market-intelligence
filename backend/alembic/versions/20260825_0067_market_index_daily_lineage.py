"""Add raw receipt lineage to Taiwan market index daily rows.

Revision ID: 20260825_0067
Revises: 20260822_0066
Create Date: 2026-08-25 19:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260825_0067"
down_revision: str | Sequence[str] | None = "20260822_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "market_index_daily_stat"
INDEXES = {
    "ix_market_index_daily_stat_source_id": ["source_id"],
    "ix_market_index_daily_stat_raw_result_id": ["raw_result_id"],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE_NAME not in inspector.get_table_names():
        # Historical repair tests intentionally start from a stamped partial
        # schema that predates this table.  Do not manufacture a table outside
        # its owning migration, and do not prevent unrelated legacy repair from
        # reaching head.  Normal databases created through 0009 always have it.
        return
    columns = {item["name"] for item in inspector.get_columns(TABLE_NAME)}
    if "source_id" not in columns or "raw_result_id" not in columns:
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            if "source_id" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "source_id",
                        sa.Integer(),
                        sa.ForeignKey(
                            "source_registry.id",
                            name="fk_market_index_daily_stat_source_id",
                        ),
                        nullable=True,
                    )
                )
            if "raw_result_id" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "raw_result_id",
                        sa.Integer(),
                        sa.ForeignKey(
                            "raw_fetch_result.id",
                            name="fk_market_index_daily_stat_raw_result_id",
                        ),
                        nullable=True,
                    )
                )
    existing_indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)
    }
    for index_name, column_names in INDEXES.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, TABLE_NAME, column_names, unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE_NAME not in inspector.get_table_names():
        return
    existing_indexes = {
        item["name"] for item in inspector.get_indexes(TABLE_NAME)
    }
    for index_name in INDEXES:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=TABLE_NAME)
    columns = {item["name"] for item in inspector.get_columns(TABLE_NAME)}
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        if "raw_result_id" in columns:
            batch_op.drop_column("raw_result_id")
        if "source_id" in columns:
            batch_op.drop_column("source_id")
