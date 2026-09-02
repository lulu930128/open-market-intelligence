"""Add bounded latest-read indexes for Taiwan current market snapshots.

Revision ID: 20260902_0077
Revises: 20260901_0076
Create Date: 2026-09-02 16:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260902_0077"
down_revision: str | Sequence[str] | None = "20260901_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_TABLE = "taiwan_current_index_snapshot"
BREADTH_TABLE = "taiwan_current_breadth_snapshot"
INDEX_NAME = "ix_tw_current_index_scope_provider_latest"
BREADTH_INDEX_NAME = "ix_tw_current_breadth_scope_provider_latest"


def _index_names(table_name: str) -> set[str]:
    return {
        str(item["name"])
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if (
        inspector.has_table(INDEX_TABLE)
        and INDEX_NAME not in _index_names(INDEX_TABLE)
    ):
        op.create_index(
            INDEX_NAME,
            INDEX_TABLE,
            [
                "index_id",
                "provider",
                sa.text("event_at DESC"),
                sa.text("id DESC"),
                "trade_date",
            ],
            unique=False,
        )
    if (
        inspector.has_table(BREADTH_TABLE)
        and BREADTH_INDEX_NAME not in _index_names(BREADTH_TABLE)
    ):
        op.create_index(
            BREADTH_INDEX_NAME,
            BREADTH_TABLE,
            [
                "venue",
                "provider",
                sa.text("event_at DESC"),
                sa.text("id DESC"),
                "trade_date",
            ],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if (
        inspector.has_table(BREADTH_TABLE)
        and BREADTH_INDEX_NAME in _index_names(BREADTH_TABLE)
    ):
        op.drop_index(BREADTH_INDEX_NAME, table_name=BREADTH_TABLE)
    if (
        inspector.has_table(INDEX_TABLE)
        and INDEX_NAME in _index_names(INDEX_TABLE)
    ):
        op.drop_index(INDEX_NAME, table_name=INDEX_TABLE)
