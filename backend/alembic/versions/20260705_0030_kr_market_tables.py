"""add Korean market tables

Revision ID: 20260705_0030
Revises: 20260703_0029
Create Date: 2026-07-05 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260705_0030"
down_revision: str | Sequence[str] | None = "20260703_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_index(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name):
        existing = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        }
        if index_name not in existing:
            op.create_index(op.f(index_name), table_name, columns, unique=False)


def upgrade() -> None:
    if not _has_table("kr_stock_master"):
        op.create_table(
            "kr_stock_master",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("local_code", sa.String(length=20), nullable=True),
            sa.Column("security_name", sa.String(length=240), nullable=True),
            sa.Column("security_name_kr", sa.String(length=240), nullable=True),
            sa.Column("exchange", sa.String(length=80), nullable=True),
            sa.Column("market_segment", sa.String(length=80), nullable=True),
            sa.Column("sector", sa.String(length=120), nullable=True),
            sa.Column("industry", sa.String(length=160), nullable=True),
            sa.Column("asset_type", sa.String(length=40), nullable=False),
            sa.Column("listing_source", sa.String(length=40), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("exchange_timezone_name", sa.String(length=80), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", name="uq_kr_stock_master_symbol"),
        )

    if not _has_table("kr_daily_price"):
        op.create_table(
            "kr_daily_price",
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
            sa.Column("price_change", sa.Float(), nullable=True),
            sa.Column("change_pct", sa.Float(), nullable=True),
            sa.Column("trade_volume", sa.BigInteger(), nullable=True),
            sa.Column("trade_value", sa.BigInteger(), nullable=True),
            sa.Column("market_cap", sa.BigInteger(), nullable=True),
            sa.Column("listed_shares", sa.BigInteger(), nullable=True),
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
                name="uq_kr_daily_price_provider_symbol_date",
            ),
        )

    if not _has_table("kr_company_fundamental"):
        op.create_table(
            "kr_company_fundamental",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("corp_code", sa.String(length=20), nullable=True),
            sa.Column("stock_code", sa.String(length=20), nullable=True),
            sa.Column("company_name", sa.String(length=240), nullable=True),
            sa.Column("fiscal_year", sa.Integer(), nullable=True),
            sa.Column("report_code", sa.String(length=20), nullable=True),
            sa.Column("report_name", sa.String(length=120), nullable=True),
            sa.Column("statement_name", sa.String(length=160), nullable=True),
            sa.Column("account_name", sa.String(length=160), nullable=True),
            sa.Column("account_id", sa.String(length=80), nullable=True),
            sa.Column("current_amount", sa.BigInteger(), nullable=True),
            sa.Column("previous_amount", sa.BigInteger(), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=True),
            sa.Column("disclosed_date", sa.Date(), nullable=True),
            sa.Column("receipt_no", sa.String(length=80), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "fiscal_year",
                "report_code",
                "statement_name",
                "account_name",
                name="uq_kr_company_fundamental_provider_symbol_account",
            ),
        )

    if not _has_table("kr_investor_trade_daily"):
        op.create_table(
            "kr_investor_trade_daily",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("investor_type", sa.String(length=80), nullable=False),
            sa.Column("buy_value", sa.BigInteger(), nullable=True),
            sa.Column("sell_value", sa.BigInteger(), nullable=True),
            sa.Column("net_buy_value", sa.BigInteger(), nullable=True),
            sa.Column("buy_volume", sa.BigInteger(), nullable=True),
            sa.Column("sell_volume", sa.BigInteger(), nullable=True),
            sa.Column("net_buy_volume", sa.BigInteger(), nullable=True),
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
                "investor_type",
                name="uq_kr_investor_trade_provider_symbol_date_type",
            ),
        )

    if not _has_table("kr_watchlist_group"):
        op.create_table(
            "kr_watchlist_group",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("group_name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["parent_id"], ["kr_watchlist_group.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("kr_watchlist_item"):
        op.create_table(
            "kr_watchlist_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("tags", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["kr_watchlist_group.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "group_id",
                "symbol",
                name="uq_kr_watchlist_item_group_symbol",
            ),
        )

    index_specs: tuple[tuple[str, str, list[str]], ...] = (
        ("kr_stock_master", "ix_kr_stock_master_symbol", ["symbol"]),
        ("kr_stock_master", "ix_kr_stock_master_local_code", ["local_code"]),
        ("kr_stock_master", "ix_kr_stock_master_exchange", ["exchange"]),
        ("kr_stock_master", "ix_kr_stock_master_market_segment", ["market_segment"]),
        ("kr_stock_master", "ix_kr_stock_master_sector", ["sector"]),
        ("kr_stock_master", "ix_kr_stock_master_industry", ["industry"]),
        ("kr_stock_master", "ix_kr_stock_master_asset_type", ["asset_type"]),
        ("kr_stock_master", "ix_kr_stock_master_listing_source", ["listing_source"]),
        ("kr_stock_master", "ix_kr_stock_master_currency", ["currency"]),
        ("kr_stock_master", "ix_kr_stock_master_is_active", ["is_active"]),
        ("kr_daily_price", "ix_kr_daily_price_provider", ["provider"]),
        ("kr_daily_price", "ix_kr_daily_price_symbol", ["symbol"]),
        ("kr_daily_price", "ix_kr_daily_price_trade_date", ["trade_date"]),
        ("kr_daily_price", "ix_kr_daily_price_currency", ["currency"]),
        ("kr_daily_price", "ix_kr_daily_price_raw_payload_hash", ["raw_payload_hash"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_provider", ["provider"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_symbol", ["symbol"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_corp_code", ["corp_code"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_stock_code", ["stock_code"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_fiscal_year", ["fiscal_year"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_report_code", ["report_code"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_statement_name", ["statement_name"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_account_name", ["account_name"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_account_id", ["account_id"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_disclosed_date", ["disclosed_date"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_receipt_no", ["receipt_no"]),
        ("kr_company_fundamental", "ix_kr_company_fundamental_raw_payload_hash", ["raw_payload_hash"]),
        ("kr_investor_trade_daily", "ix_kr_investor_trade_daily_provider", ["provider"]),
        ("kr_investor_trade_daily", "ix_kr_investor_trade_daily_symbol", ["symbol"]),
        ("kr_investor_trade_daily", "ix_kr_investor_trade_daily_trade_date", ["trade_date"]),
        ("kr_investor_trade_daily", "ix_kr_investor_trade_daily_investor_type", ["investor_type"]),
        ("kr_investor_trade_daily", "ix_kr_investor_trade_daily_raw_payload_hash", ["raw_payload_hash"]),
        ("kr_watchlist_group", "ix_kr_watchlist_group_parent_id", ["parent_id"]),
        ("kr_watchlist_group", "ix_kr_watchlist_group_group_name", ["group_name"]),
        ("kr_watchlist_group", "ix_kr_watchlist_group_sort_order", ["sort_order"]),
        ("kr_watchlist_group", "ix_kr_watchlist_group_is_active", ["is_active"]),
        ("kr_watchlist_item", "ix_kr_watchlist_item_group_id", ["group_id"]),
        ("kr_watchlist_item", "ix_kr_watchlist_item_symbol", ["symbol"]),
        ("kr_watchlist_item", "ix_kr_watchlist_item_priority", ["priority"]),
        ("kr_watchlist_item", "ix_kr_watchlist_item_enabled", ["enabled"]),
    )
    for table_name, index_name, columns in index_specs:
        _create_index(table_name, index_name, columns)


def downgrade() -> None:
    for table_name in (
        "kr_watchlist_item",
        "kr_watchlist_group",
        "kr_investor_trade_daily",
        "kr_company_fundamental",
        "kr_daily_price",
        "kr_stock_master",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
