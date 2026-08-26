"""Add canonical lineage to Taiwan public quote snapshots.

Revision ID: 20260825_0068
Revises: 20260825_0067
Create Date: 2026-08-25 20:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260825_0068"
down_revision: str | Sequence[str] | None = "20260825_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "taiwan_stock_quote_snapshot"
INDEXES = {
    "ix_taiwan_stock_quote_snapshot_source_id": ["source_id"],
    "ix_taiwan_stock_quote_snapshot_raw_result_id": ["raw_result_id"],
    "ix_taiwan_stock_quote_snapshot_received_at": ["received_at"],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE_NAME not in inspector.get_table_names():
        # Historical repair tests may start from a stamped partial schema.
        # The table belongs to 0027; do not recreate it in a lineage migration.
        return
    columns = {item["name"] for item in inspector.get_columns(TABLE_NAME)}
    additions = {
        "source_id": sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey(
                "source_registry.id",
                name="fk_taiwan_stock_quote_snapshot_source_id",
            ),
            nullable=True,
        ),
        "raw_result_id": sa.Column(
            "raw_result_id",
            sa.Integer(),
            sa.ForeignKey(
                "raw_fetch_result.id",
                name="fk_taiwan_stock_quote_snapshot_raw_result_id",
            ),
            nullable=True,
        ),
        "received_at": sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        "observation_state": sa.Column(
            "observation_state",
            sa.String(length=30),
            nullable=True,
        ),
        "market_session": sa.Column(
            "market_session",
            sa.String(length=40),
            nullable=True,
        ),
        "trade_state": sa.Column(
            "trade_state",
            sa.String(length=40),
            nullable=True,
        ),
        "raw_contract_version": sa.Column(
            "raw_contract_version",
            sa.String(length=64),
            nullable=True,
        ),
    }
    if any(name not in columns for name in additions):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            for name, column in additions.items():
                if name not in columns:
                    batch_op.add_column(column)
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
        for column_name in (
            "raw_contract_version",
            "trade_state",
            "market_session",
            "observation_state",
            "received_at",
            "raw_result_id",
            "source_id",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
