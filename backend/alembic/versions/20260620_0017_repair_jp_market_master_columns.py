"""Repair Japan market master columns on pre-existing tables.

Revision ID: 20260620_0017
Revises: 20260620_0016
Create Date: 2026-06-20 00:00:00
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260620_0017"
down_revision: str | Sequence[str] | None = "20260620_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JP_STOCK_MASTER_REPAIR_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    ("market_segment", lambda: sa.Column("market_segment", sa.String(length=80), nullable=True)),
    ("sector_33_code", lambda: sa.Column("sector_33_code", sa.String(length=20), nullable=True)),
    ("sector_33_name", lambda: sa.Column("sector_33_name", sa.String(length=120), nullable=True)),
    ("sector_17_code", lambda: sa.Column("sector_17_code", sa.String(length=20), nullable=True)),
    ("sector_17_name", lambda: sa.Column("sector_17_name", sa.String(length=120), nullable=True)),
    ("size_code", lambda: sa.Column("size_code", sa.String(length=20), nullable=True)),
    ("size_name", lambda: sa.Column("size_name", sa.String(length=80), nullable=True)),
)

JP_STOCK_MASTER_REPAIR_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_jp_stock_master_market_segment", "market_segment"),
    ("ix_jp_stock_master_sector_33_code", "sector_33_code"),
    ("ix_jp_stock_master_sector_33_name", "sector_33_name"),
    ("ix_jp_stock_master_sector_17_code", "sector_17_code"),
    ("ix_jp_stock_master_sector_17_name", "sector_17_name"),
    ("ix_jp_stock_master_size_code", "size_code"),
    ("ix_jp_stock_master_size_name", "size_name"),
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    if not _has_table("jp_stock_master"):
        return

    existing_columns = _column_names("jp_stock_master")
    for column_name, column_factory in JP_STOCK_MASTER_REPAIR_COLUMNS:
        if column_name not in existing_columns:
            op.add_column("jp_stock_master", column_factory())
            existing_columns.add(column_name)

    existing_indexes = _index_names("jp_stock_master")
    for index_name, column_name in JP_STOCK_MASTER_REPAIR_INDEXES:
        if column_name in existing_columns and index_name not in existing_indexes:
            op.create_index(op.f(index_name), "jp_stock_master", [column_name], unique=False)


def downgrade() -> None:
    # This migration repairs databases that reached 0016 with a partial JP master
    # table. The canonical 0016 schema already includes these columns, so downgrade
    # intentionally leaves the repaired schema intact.
    return
