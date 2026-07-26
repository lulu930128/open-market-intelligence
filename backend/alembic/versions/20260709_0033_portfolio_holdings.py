"""add portfolio holding table

Revision ID: 20260709_0033
Revises: 20260707_0032
Create Date: 2026-07-09 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260709_0033"
down_revision: str | Sequence[str] | None = "20260707_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _create_index(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(op.f(index_name), table_name, columns, unique=False)


def upgrade() -> None:
    if not _has_table("portfolio_holding"):
        op.create_table(
            "portfolio_holding",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("market", sa.String(length=10), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("symbol_name", sa.String(length=240), nullable=True),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("cost_amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("tags", sa.Text(), nullable=True),
            sa.Column("strategy_horizon", sa.String(length=40), nullable=True),
            sa.Column("opened_at", sa.Date(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "market",
                "symbol",
                name="uq_portfolio_holding_market_symbol",
            ),
        )

    index_specs: tuple[tuple[str, str, list[str]], ...] = (
        ("portfolio_holding", "ix_portfolio_holding_id", ["id"]),
        ("portfolio_holding", "ix_portfolio_holding_market", ["market"]),
        ("portfolio_holding", "ix_portfolio_holding_symbol", ["symbol"]),
        ("portfolio_holding", "ix_portfolio_holding_market_symbol", ["market", "symbol"]),
        ("portfolio_holding", "ix_portfolio_holding_currency", ["currency"]),
        ("portfolio_holding", "ix_portfolio_holding_is_active", ["is_active"]),
    )
    for table_name, index_name, columns in index_specs:
        _create_index(table_name, index_name, columns)


def downgrade() -> None:
    if _has_table("portfolio_holding"):
        op.drop_table("portfolio_holding")
