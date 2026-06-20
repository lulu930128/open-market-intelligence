"""Add Japan market data tables.

Revision ID: 20260620_0016
Revises: 20260619_0015
Create Date: 2026-06-20 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260620_0016"
down_revision: str | Sequence[str] | None = "20260619_0015"
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
    if not _has_table("jp_stock_master"):
        op.create_table(
            "jp_stock_master",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("local_code", sa.String(length=20), nullable=True),
            sa.Column("security_name", sa.String(length=240), nullable=True),
            sa.Column("exchange", sa.String(length=80), nullable=True),
            sa.Column("market_segment", sa.String(length=80), nullable=True),
            sa.Column("sector_33_code", sa.String(length=20), nullable=True),
            sa.Column("sector_33_name", sa.String(length=120), nullable=True),
            sa.Column("sector_17_code", sa.String(length=20), nullable=True),
            sa.Column("sector_17_name", sa.String(length=120), nullable=True),
            sa.Column("size_code", sa.String(length=20), nullable=True),
            sa.Column("size_name", sa.String(length=80), nullable=True),
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
            sa.UniqueConstraint("symbol", name="uq_jp_stock_master_symbol"),
        )
        op.create_index(op.f("ix_jp_stock_master_asset_type"), "jp_stock_master", ["asset_type"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_currency"), "jp_stock_master", ["currency"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_exchange"), "jp_stock_master", ["exchange"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_id"), "jp_stock_master", ["id"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_is_active"), "jp_stock_master", ["is_active"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_listing_source"), "jp_stock_master", ["listing_source"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_local_code"), "jp_stock_master", ["local_code"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_market_segment"), "jp_stock_master", ["market_segment"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_sector_17_code"), "jp_stock_master", ["sector_17_code"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_sector_17_name"), "jp_stock_master", ["sector_17_name"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_sector_33_code"), "jp_stock_master", ["sector_33_code"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_sector_33_name"), "jp_stock_master", ["sector_33_name"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_size_code"), "jp_stock_master", ["size_code"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_size_name"), "jp_stock_master", ["size_name"], unique=False)
        op.create_index(op.f("ix_jp_stock_master_symbol"), "jp_stock_master", ["symbol"], unique=True)

    if not _has_table("jp_daily_price"):
        op.create_table(
            "jp_daily_price",
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
                name="uq_jp_daily_price_provider_symbol_date",
            ),
        )
        op.create_index(op.f("ix_jp_daily_price_currency"), "jp_daily_price", ["currency"], unique=False)
        op.create_index(op.f("ix_jp_daily_price_id"), "jp_daily_price", ["id"], unique=False)
        op.create_index(op.f("ix_jp_daily_price_provider"), "jp_daily_price", ["provider"], unique=False)
        op.create_index(op.f("ix_jp_daily_price_raw_payload_hash"), "jp_daily_price", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_jp_daily_price_symbol"), "jp_daily_price", ["symbol"], unique=False)
        op.create_index(op.f("ix_jp_daily_price_trade_date"), "jp_daily_price", ["trade_date"], unique=False)


def downgrade() -> None:
    if _has_table("jp_daily_price"):
        _drop_indexes(
            "jp_daily_price",
            (
                "ix_jp_daily_price_trade_date",
                "ix_jp_daily_price_symbol",
                "ix_jp_daily_price_raw_payload_hash",
                "ix_jp_daily_price_provider",
                "ix_jp_daily_price_id",
                "ix_jp_daily_price_currency",
            ),
        )
        op.drop_table("jp_daily_price")

    if _has_table("jp_stock_master"):
        _drop_indexes(
            "jp_stock_master",
            (
                "ix_jp_stock_master_symbol",
                "ix_jp_stock_master_size_name",
                "ix_jp_stock_master_size_code",
                "ix_jp_stock_master_sector_33_name",
                "ix_jp_stock_master_sector_33_code",
                "ix_jp_stock_master_sector_17_name",
                "ix_jp_stock_master_sector_17_code",
                "ix_jp_stock_master_market_segment",
                "ix_jp_stock_master_local_code",
                "ix_jp_stock_master_listing_source",
                "ix_jp_stock_master_is_active",
                "ix_jp_stock_master_id",
                "ix_jp_stock_master_exchange",
                "ix_jp_stock_master_currency",
                "ix_jp_stock_master_asset_type",
            ),
        )
        op.drop_table("jp_stock_master")
