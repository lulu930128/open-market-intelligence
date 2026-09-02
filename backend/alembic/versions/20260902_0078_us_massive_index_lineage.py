"""Preserve US index volume status and provider timeframe lineage.

Revision ID: 20260902_0078
Revises: 20260902_0077
Create Date: 2026-09-02 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260902_0078"
down_revision: str | Sequence[str] | None = "20260902_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {item["name"] for item in inspector.get_columns(table_name)}


def _add_nullable_string_if_missing(table_name: str, column_name: str) -> None:
    existing = _column_names(table_name)
    if not existing or column_name in existing:
        return
    op.add_column(
        table_name,
        sa.Column(column_name, sa.String(length=32), nullable=True),
    )


def upgrade() -> None:
    _add_nullable_string_if_missing("market_intraday_bar", "volume_status")
    _add_nullable_string_if_missing(
        "market_intraday_bar_lineage",
        "provider_timeframe",
    )
    _add_nullable_string_if_missing("us_quote_snapshot", "provider_timeframe")


def _drop_if_present(table_name: str, column_name: str) -> None:
    if column_name not in _column_names(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def downgrade() -> None:
    _drop_if_present("us_quote_snapshot", "provider_timeframe")
    _drop_if_present("market_intraday_bar_lineage", "provider_timeframe")
    _drop_if_present("market_intraday_bar", "volume_status")
