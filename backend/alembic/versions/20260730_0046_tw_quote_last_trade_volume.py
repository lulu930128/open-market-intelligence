"""Persist the provider-reported Taiwan quote last-trade volume.

Revision ID: 20260730_0046
Revises: 20260730_0045
Create Date: 2026-07-30 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0046"
down_revision: str | Sequence[str] | None = "20260730_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("taiwan_stock_quote_snapshot"):
        raise RuntimeError(
            "taiwan_stock_quote_snapshot must exist before applying "
            "20260730_0046."
        )
    columns = {
        column["name"]
        for column in inspector.get_columns("taiwan_stock_quote_snapshot")
    }
    if "last_trade_volume_lots" not in columns:
        op.add_column(
            "taiwan_stock_quote_snapshot",
            sa.Column("last_trade_volume_lots", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("taiwan_stock_quote_snapshot"):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("taiwan_stock_quote_snapshot")
    }
    if "last_trade_volume_lots" in columns:
        op.drop_column(
            "taiwan_stock_quote_snapshot",
            "last_trade_volume_lots",
        )
