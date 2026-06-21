"""Repair Japan company fundamental columns on pre-existing tables.

Revision ID: 20260621_0020
Revises: 20260620_0019
Create Date: 2026-06-21 00:00:00
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260621_0020"
down_revision: str | Sequence[str] | None = "20260620_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JP_COMPANY_FUNDAMENTAL_REPAIR_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    ("disclosed_date", lambda: sa.Column("disclosed_date", sa.Date(), nullable=True)),
    ("fiscal_period", lambda: sa.Column("fiscal_period", sa.String(length=40), nullable=True)),
    ("fiscal_year_end", lambda: sa.Column("fiscal_year_end", sa.Date(), nullable=True)),
    ("document_type", lambda: sa.Column("document_type", sa.String(length=120), nullable=True)),
    ("net_sales", lambda: sa.Column("net_sales", sa.BigInteger(), nullable=True)),
    ("operating_profit", lambda: sa.Column("operating_profit", sa.BigInteger(), nullable=True)),
    ("ordinary_profit", lambda: sa.Column("ordinary_profit", sa.BigInteger(), nullable=True)),
    ("profit", lambda: sa.Column("profit", sa.BigInteger(), nullable=True)),
    ("forecast_net_sales", lambda: sa.Column("forecast_net_sales", sa.BigInteger(), nullable=True)),
    (
        "forecast_operating_profit",
        lambda: sa.Column("forecast_operating_profit", sa.BigInteger(), nullable=True),
    ),
    (
        "forecast_ordinary_profit",
        lambda: sa.Column("forecast_ordinary_profit", sa.BigInteger(), nullable=True),
    ),
    ("forecast_profit", lambda: sa.Column("forecast_profit", sa.BigInteger(), nullable=True)),
    ("total_assets", lambda: sa.Column("total_assets", sa.BigInteger(), nullable=True)),
    ("equity", lambda: sa.Column("equity", sa.BigInteger(), nullable=True)),
    ("equity_to_asset_ratio", lambda: sa.Column("equity_to_asset_ratio", sa.Float(), nullable=True)),
    ("operating_cash_flow", lambda: sa.Column("operating_cash_flow", sa.BigInteger(), nullable=True)),
    ("investing_cash_flow", lambda: sa.Column("investing_cash_flow", sa.BigInteger(), nullable=True)),
    ("financing_cash_flow", lambda: sa.Column("financing_cash_flow", sa.BigInteger(), nullable=True)),
)

JP_COMPANY_FUNDAMENTAL_REPAIR_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_jp_company_fundamental_disclosed_date", "disclosed_date"),
    ("ix_jp_company_fundamental_fiscal_period", "fiscal_period"),
    ("ix_jp_company_fundamental_fiscal_year_end", "fiscal_year_end"),
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
    if not _has_table("jp_company_fundamental"):
        return

    existing_columns = _column_names("jp_company_fundamental")
    for column_name, column_factory in JP_COMPANY_FUNDAMENTAL_REPAIR_COLUMNS:
        if column_name not in existing_columns:
            op.add_column("jp_company_fundamental", column_factory())
            existing_columns.add(column_name)

    existing_indexes = _index_names("jp_company_fundamental")
    for index_name, column_name in JP_COMPANY_FUNDAMENTAL_REPAIR_INDEXES:
        if column_name in existing_columns and index_name not in existing_indexes:
            op.create_index(
                op.f(index_name),
                "jp_company_fundamental",
                [column_name],
                unique=False,
            )


def downgrade() -> None:
    # This migration repairs local databases that were already stamped at 0019
    # with a partial create_all-era table. Downgrade intentionally leaves data
    # and repaired columns intact.
    return
