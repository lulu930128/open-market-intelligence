"""Add component lineage to Taiwan derived intraday state.

Revision ID: 20260826_0072
Revises: 20260826_0071
Create Date: 2026-08-26 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260826_0072"
down_revision: str | Sequence[str] | None = "20260826_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "taiwan_market_minute_state",
    "taiwan_intraday_stock_state",
)
COLUMNS = (
    ("component_raw_result_ids_json", sa.Text(), True, None),
    ("component_sources_json", sa.Text(), True, None),
    ("component_event_times_json", sa.Text(), True, None),
    ("component_time_skew_seconds", sa.Integer(), True, None),
    ("calculation_version", sa.String(length=96), True, None),
    ("lineage_complete", sa.Boolean(), False, sa.text("0")),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in TABLES:
        if not inspector.has_table(table_name):
            continue
        existing = {
            item["name"] for item in inspector.get_columns(table_name)
        }
        with op.batch_alter_table(table_name) as batch_op:
            for name, type_, nullable, server_default in COLUMNS:
                if name in existing:
                    continue
                batch_op.add_column(
                    sa.Column(
                        name,
                        type_,
                        nullable=nullable,
                        server_default=server_default,
                    )
                )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in reversed(TABLES):
        if not inspector.has_table(table_name):
            continue
        existing = {
            item["name"] for item in inspector.get_columns(table_name)
        }
        with op.batch_alter_table(table_name) as batch_op:
            for name, _type, _nullable, _server_default in reversed(COLUMNS):
                if name in existing:
                    batch_op.drop_column(name)
