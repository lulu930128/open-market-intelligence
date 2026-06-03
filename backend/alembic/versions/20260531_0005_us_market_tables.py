"""Add isolated US market data tables.

Revision ID: 20260531_0005
Revises: 20260527_0004
Create Date: 2026-05-31 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260531_0005"
down_revision: str | Sequence[str] | None = "20260527_0004"
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
    if not _has_table("us_stock_master"):
        op.create_table(
            "us_stock_master",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("security_name", sa.String(length=240), nullable=True),
            sa.Column("exchange", sa.String(length=40), nullable=True),
            sa.Column("asset_type", sa.String(length=40), nullable=False),
            sa.Column("listing_source", sa.String(length=40), nullable=False),
            sa.Column("market_category", sa.String(length=40), nullable=True),
            sa.Column("financial_status", sa.String(length=40), nullable=True),
            sa.Column("cqs_symbol", sa.String(length=32), nullable=True),
            sa.Column("nasdaq_symbol", sa.String(length=32), nullable=True),
            sa.Column("cik", sa.String(length=20), nullable=True),
            sa.Column("sec_company_name", sa.String(length=240), nullable=True),
            sa.Column("is_etf", sa.Boolean(), nullable=True),
            sa.Column("is_test_issue", sa.Boolean(), nullable=False),
            sa.Column("round_lot_size", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", name="uq_us_stock_master_symbol"),
        )
        op.create_index(op.f("ix_us_stock_master_asset_type"), "us_stock_master", ["asset_type"], unique=False)
        op.create_index(op.f("ix_us_stock_master_cik"), "us_stock_master", ["cik"], unique=False)
        op.create_index(op.f("ix_us_stock_master_cqs_symbol"), "us_stock_master", ["cqs_symbol"], unique=False)
        op.create_index(op.f("ix_us_stock_master_exchange"), "us_stock_master", ["exchange"], unique=False)
        op.create_index(op.f("ix_us_stock_master_id"), "us_stock_master", ["id"], unique=False)
        op.create_index(op.f("ix_us_stock_master_is_active"), "us_stock_master", ["is_active"], unique=False)
        op.create_index(op.f("ix_us_stock_master_is_etf"), "us_stock_master", ["is_etf"], unique=False)
        op.create_index(op.f("ix_us_stock_master_is_test_issue"), "us_stock_master", ["is_test_issue"], unique=False)
        op.create_index(op.f("ix_us_stock_master_listing_source"), "us_stock_master", ["listing_source"], unique=False)
        op.create_index(op.f("ix_us_stock_master_nasdaq_symbol"), "us_stock_master", ["nasdaq_symbol"], unique=False)
        op.create_index(op.f("ix_us_stock_master_symbol"), "us_stock_master", ["symbol"], unique=True)

    if not _has_table("us_daily_price"):
        op.create_table(
            "us_daily_price",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("adjusted_close", sa.Float(), nullable=True),
            sa.Column("trade_volume", sa.BigInteger(), nullable=True),
            sa.Column("dividend_amount", sa.Float(), nullable=True),
            sa.Column("split_coefficient", sa.Float(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "trade_date",
                name="uq_us_daily_price_provider_symbol_date",
            ),
        )
        op.create_index(op.f("ix_us_daily_price_currency"), "us_daily_price", ["currency"], unique=False)
        op.create_index(op.f("ix_us_daily_price_id"), "us_daily_price", ["id"], unique=False)
        op.create_index(op.f("ix_us_daily_price_provider"), "us_daily_price", ["provider"], unique=False)
        op.create_index(op.f("ix_us_daily_price_raw_payload_hash"), "us_daily_price", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_us_daily_price_symbol"), "us_daily_price", ["symbol"], unique=False)
        op.create_index(op.f("ix_us_daily_price_trade_date"), "us_daily_price", ["trade_date"], unique=False)

    if not _has_table("us_sec_company_fact"):
        op.create_table(
            "us_sec_company_fact",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("fact_key", sa.String(length=128), nullable=False),
            sa.Column("cik", sa.String(length=20), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=True),
            sa.Column("entity_name", sa.String(length=240), nullable=True),
            sa.Column("taxonomy", sa.String(length=40), nullable=False),
            sa.Column("tag", sa.String(length=160), nullable=False),
            sa.Column("label", sa.String(length=240), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("unit", sa.String(length=80), nullable=False),
            sa.Column("fiscal_year", sa.Integer(), nullable=True),
            sa.Column("fiscal_period", sa.String(length=20), nullable=True),
            sa.Column("form", sa.String(length=20), nullable=True),
            sa.Column("filed_date", sa.Date(), nullable=True),
            sa.Column("period_start_date", sa.Date(), nullable=True),
            sa.Column("period_end_date", sa.Date(), nullable=True),
            sa.Column("accession_number", sa.String(length=40), nullable=True),
            sa.Column("frame", sa.String(length=80), nullable=True),
            sa.Column("value_numeric", sa.Float(), nullable=True),
            sa.Column("value_text", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("fact_key", name="uq_us_sec_company_fact_key"),
        )
        op.create_index(op.f("ix_us_sec_company_fact_accession_number"), "us_sec_company_fact", ["accession_number"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_cik"), "us_sec_company_fact", ["cik"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_fact_key"), "us_sec_company_fact", ["fact_key"], unique=True)
        op.create_index(op.f("ix_us_sec_company_fact_filed_date"), "us_sec_company_fact", ["filed_date"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_fiscal_period"), "us_sec_company_fact", ["fiscal_period"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_fiscal_year"), "us_sec_company_fact", ["fiscal_year"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_form"), "us_sec_company_fact", ["form"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_frame"), "us_sec_company_fact", ["frame"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_id"), "us_sec_company_fact", ["id"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_period_end_date"), "us_sec_company_fact", ["period_end_date"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_period_start_date"), "us_sec_company_fact", ["period_start_date"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_symbol"), "us_sec_company_fact", ["symbol"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_tag"), "us_sec_company_fact", ["tag"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_taxonomy"), "us_sec_company_fact", ["taxonomy"], unique=False)
        op.create_index(op.f("ix_us_sec_company_fact_unit"), "us_sec_company_fact", ["unit"], unique=False)


def downgrade() -> None:
    if _has_table("us_sec_company_fact"):
        _drop_indexes(
            "us_sec_company_fact",
            (
                "ix_us_sec_company_fact_unit",
                "ix_us_sec_company_fact_taxonomy",
                "ix_us_sec_company_fact_tag",
                "ix_us_sec_company_fact_symbol",
                "ix_us_sec_company_fact_period_start_date",
                "ix_us_sec_company_fact_period_end_date",
                "ix_us_sec_company_fact_id",
                "ix_us_sec_company_fact_frame",
                "ix_us_sec_company_fact_form",
                "ix_us_sec_company_fact_fiscal_year",
                "ix_us_sec_company_fact_fiscal_period",
                "ix_us_sec_company_fact_filed_date",
                "ix_us_sec_company_fact_fact_key",
                "ix_us_sec_company_fact_cik",
                "ix_us_sec_company_fact_accession_number",
            ),
        )
        op.drop_table("us_sec_company_fact")

    if _has_table("us_daily_price"):
        _drop_indexes(
            "us_daily_price",
            (
                "ix_us_daily_price_trade_date",
                "ix_us_daily_price_symbol",
                "ix_us_daily_price_raw_payload_hash",
                "ix_us_daily_price_provider",
                "ix_us_daily_price_id",
                "ix_us_daily_price_currency",
            ),
        )
        op.drop_table("us_daily_price")

    if _has_table("us_stock_master"):
        _drop_indexes(
            "us_stock_master",
            (
                "ix_us_stock_master_symbol",
                "ix_us_stock_master_nasdaq_symbol",
                "ix_us_stock_master_listing_source",
                "ix_us_stock_master_is_test_issue",
                "ix_us_stock_master_is_etf",
                "ix_us_stock_master_is_active",
                "ix_us_stock_master_id",
                "ix_us_stock_master_exchange",
                "ix_us_stock_master_cqs_symbol",
                "ix_us_stock_master_cik",
                "ix_us_stock_master_asset_type",
            ),
        )
        op.drop_table("us_stock_master")
