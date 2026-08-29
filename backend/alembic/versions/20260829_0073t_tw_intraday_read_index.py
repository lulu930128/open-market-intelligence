"""Add the bounded Taiwan intraday read index.

Revision ID: 20260829_0073t
Revises: 20260829_0073
Create Date: 2026-08-29 19:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_0073t"
down_revision: str | Sequence[str] | None = "20260829_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "market_intraday_bar"
INDEX_NAME = "ix_market_intraday_bar_stock_market_interval_time"
INDEX_COLUMNS = ["stock_id", "market", "interval", "bar_time", "id"]


def _has_index() -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(TABLE_NAME) and any(
        item["name"] == INDEX_NAME
        for item in inspector.get_indexes(TABLE_NAME)
    )


def upgrade() -> None:
    if not _has_index():
        op.create_index(INDEX_NAME, TABLE_NAME, INDEX_COLUMNS, unique=False)


def downgrade() -> None:
    if _has_index():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
