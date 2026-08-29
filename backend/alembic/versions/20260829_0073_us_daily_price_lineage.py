"""Add canonical receipt lineage and applicability to US daily prices.

Revision ID: 20260829_0073
Revises: 20260826_0072
Create Date: 2026-08-29 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_0073"
down_revision: str | Sequence[str] | None = "20260826_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMNS = (
    ("source_id", sa.Integer(), True),
    ("raw_result_id", sa.Integer(), True),
    ("authority", sa.String(length=32), True),
    ("raw_contract_version", sa.String(length=96), True),
    ("event_at", sa.DateTime(timezone=True), True),
    ("finalization", sa.String(length=32), True),
    ("price_basis", sa.String(length=32), True),
    ("volume_unit", sa.String(length=32), True),
    ("volume_status", sa.String(length=32), True),
)
INDEXES = (
    ("ix_us_daily_price_source_id", ("source_id",)),
    ("ix_us_daily_price_raw_result_id", ("raw_result_id",)),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("us_daily_price"):
        return
    existing = {item["name"] for item in inspector.get_columns("us_daily_price")}
    with op.batch_alter_table("us_daily_price") as batch_op:
        for name, type_, nullable in COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, type_, nullable=nullable))
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {
        item["name"] for item in inspector.get_indexes("us_daily_price")
    }
    for name, columns in INDEXES:
        if name not in existing_indexes:
            op.create_index(name, "us_daily_price", list(columns), unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("us_daily_price"):
        return
    existing_indexes = {
        item["name"] for item in inspector.get_indexes("us_daily_price")
    }
    for name, _columns in reversed(INDEXES):
        if name in existing_indexes:
            op.drop_index(name, table_name="us_daily_price")
    existing = {item["name"] for item in inspector.get_columns("us_daily_price")}
    with op.batch_alter_table("us_daily_price") as batch_op:
        for name, _type, _nullable in reversed(COLUMNS):
            if name in existing:
                batch_op.drop_column(name)
