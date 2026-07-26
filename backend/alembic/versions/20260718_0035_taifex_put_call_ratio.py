"""add TAIFEX put call ratio fields

Revision ID: 20260718_0035
Revises: 20260715_0034
Create Date: 2026-07-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0035"
down_revision: str | Sequence[str] | None = "20260715_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OPTION_COLUMNS = (
    ("put_volume", sa.BigInteger()),
    ("call_volume", sa.BigInteger()),
    ("put_call_volume_ratio_pct", sa.Float()),
    ("put_open_interest", sa.BigInteger()),
    ("call_open_interest", sa.BigInteger()),
    ("put_call_open_interest_ratio_pct", sa.Float()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_chip_daily"):
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("market_chip_daily")
    }
    for column_name, column_type in OPTION_COLUMNS:
        if column_name not in existing_columns:
            op.add_column(
                "market_chip_daily",
                sa.Column(column_name, column_type, nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_chip_daily"):
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("market_chip_daily")
    }
    for column_name, _ in reversed(OPTION_COLUMNS):
        if column_name in existing_columns:
            op.drop_column("market_chip_daily", column_name)
