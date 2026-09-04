"""add bounded Taiwan index-contribution read index

Revision ID: 20260904_0080
Revises: 20260904_0079
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260904_0080"
down_revision: str | Sequence[str] | None = "20260904_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "market_daily_price"
INDEX_NAME = "ix_market_daily_tw_contribution_read"
INDEX_COLUMNS = [
    "trade_date",
    "venue",
    "instrument_type",
    "stock_id",
    "source_id",
]


def _has_index() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        item["name"] == INDEX_NAME
        for item in inspector.get_indexes(TABLE_NAME)
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE_NAME) and not _has_index():
        op.create_index(INDEX_NAME, TABLE_NAME, INDEX_COLUMNS, unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE_NAME) and _has_index():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
