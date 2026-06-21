"""Add Japan company fundamentals.

Revision ID: 20260620_0019
Revises: 20260620_0018
Create Date: 2026-06-20 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260620_0019"
down_revision: str | Sequence[str] | None = "20260620_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _drop_indexes(table_name: str, index_names: tuple[str, ...]) -> None:
    for index_name in index_names:
        if _has_index(table_name, index_name):
            op.drop_index(op.f(index_name), table_name=table_name)


def upgrade() -> None:
    if _has_table("jp_company_fundamental"):
        return

    op.create_table(
        "jp_company_fundamental",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("company_name", sa.String(length=240), nullable=True),
        sa.Column("exchange", sa.String(length=80), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("market_cap", sa.BigInteger(), nullable=True),
        sa.Column("enterprise_value", sa.BigInteger(), nullable=True),
        sa.Column("trailing_pe", sa.Float(), nullable=True),
        sa.Column("forward_pe", sa.Float(), nullable=True),
        sa.Column("price_to_book", sa.Float(), nullable=True),
        sa.Column("dividend_yield", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("disclosed_date", sa.Date(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=40), nullable=True),
        sa.Column("fiscal_year_end", sa.Date(), nullable=True),
        sa.Column("document_type", sa.String(length=120), nullable=True),
        sa.Column("eps_ttm", sa.Float(), nullable=True),
        sa.Column("forward_eps", sa.Float(), nullable=True),
        sa.Column("revenue_ttm", sa.BigInteger(), nullable=True),
        sa.Column("net_sales", sa.BigInteger(), nullable=True),
        sa.Column("operating_profit", sa.BigInteger(), nullable=True),
        sa.Column("ordinary_profit", sa.BigInteger(), nullable=True),
        sa.Column("profit", sa.BigInteger(), nullable=True),
        sa.Column("forecast_net_sales", sa.BigInteger(), nullable=True),
        sa.Column("forecast_operating_profit", sa.BigInteger(), nullable=True),
        sa.Column("forecast_ordinary_profit", sa.BigInteger(), nullable=True),
        sa.Column("forecast_profit", sa.BigInteger(), nullable=True),
        sa.Column("gross_margin", sa.Float(), nullable=True),
        sa.Column("operating_margin", sa.Float(), nullable=True),
        sa.Column("profit_margin", sa.Float(), nullable=True),
        sa.Column("return_on_equity", sa.Float(), nullable=True),
        sa.Column("return_on_assets", sa.Float(), nullable=True),
        sa.Column("revenue_growth", sa.Float(), nullable=True),
        sa.Column("earnings_growth", sa.Float(), nullable=True),
        sa.Column("total_assets", sa.BigInteger(), nullable=True),
        sa.Column("equity", sa.BigInteger(), nullable=True),
        sa.Column("equity_to_asset_ratio", sa.Float(), nullable=True),
        sa.Column("total_cash", sa.BigInteger(), nullable=True),
        sa.Column("total_debt", sa.BigInteger(), nullable=True),
        sa.Column("operating_cash_flow", sa.BigInteger(), nullable=True),
        sa.Column("investing_cash_flow", sa.BigInteger(), nullable=True),
        sa.Column("financing_cash_flow", sa.BigInteger(), nullable=True),
        sa.Column("debt_to_equity", sa.Float(), nullable=True),
        sa.Column("current_ratio", sa.Float(), nullable=True),
        sa.Column("quick_ratio", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.BigInteger(), nullable=True),
        sa.Column("book_value", sa.Float(), nullable=True),
        sa.Column("earnings_date", sa.Date(), nullable=True),
        sa.Column("ex_dividend_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            name="uq_jp_company_fundamental_provider_symbol",
        ),
    )
    op.create_index(op.f("ix_jp_company_fundamental_currency"), "jp_company_fundamental", ["currency"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_disclosed_date"), "jp_company_fundamental", ["disclosed_date"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_earnings_date"), "jp_company_fundamental", ["earnings_date"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_ex_dividend_date"), "jp_company_fundamental", ["ex_dividend_date"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_exchange"), "jp_company_fundamental", ["exchange"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_fiscal_period"), "jp_company_fundamental", ["fiscal_period"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_fiscal_year_end"), "jp_company_fundamental", ["fiscal_year_end"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_id"), "jp_company_fundamental", ["id"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_industry"), "jp_company_fundamental", ["industry"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_provider"), "jp_company_fundamental", ["provider"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_raw_payload_hash"), "jp_company_fundamental", ["raw_payload_hash"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_sector"), "jp_company_fundamental", ["sector"], unique=False)
    op.create_index(op.f("ix_jp_company_fundamental_symbol"), "jp_company_fundamental", ["symbol"], unique=False)


def downgrade() -> None:
    if not _has_table("jp_company_fundamental"):
        return

    _drop_indexes(
        "jp_company_fundamental",
        (
            "ix_jp_company_fundamental_symbol",
            "ix_jp_company_fundamental_sector",
            "ix_jp_company_fundamental_raw_payload_hash",
            "ix_jp_company_fundamental_provider",
            "ix_jp_company_fundamental_industry",
            "ix_jp_company_fundamental_id",
            "ix_jp_company_fundamental_fiscal_year_end",
            "ix_jp_company_fundamental_fiscal_period",
            "ix_jp_company_fundamental_exchange",
            "ix_jp_company_fundamental_ex_dividend_date",
            "ix_jp_company_fundamental_earnings_date",
            "ix_jp_company_fundamental_disclosed_date",
            "ix_jp_company_fundamental_currency",
        ),
    )
    op.drop_table("jp_company_fundamental")
