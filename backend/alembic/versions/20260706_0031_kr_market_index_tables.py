"""add Korean market index tables

Revision ID: 20260706_0031
Revises: 20260705_0030
Create Date: 2026-07-06 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260706_0031"
down_revision: str | Sequence[str] | None = "20260705_0030"
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
    if not _has_table("kr_market_index"):
        op.create_table(
            "kr_market_index",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("index_id", sa.String(length=32), nullable=False),
            sa.Column("provider_symbol", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("short_name", sa.String(length=80), nullable=False),
            sa.Column("name_kr", sa.String(length=160), nullable=True),
            sa.Column("market_segment", sa.String(length=80), nullable=False),
            sa.Column("index_family", sa.String(length=80), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("exchange_timezone_name", sa.String(length=80), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("index_id", name="uq_kr_market_index_index_id"),
        )

    if not _has_table("kr_index_daily_price"):
        op.create_table(
            "kr_index_daily_price",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("index_id", sa.String(length=32), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("open_value", sa.Float(), nullable=True),
            sa.Column("high_value", sa.Float(), nullable=True),
            sa.Column("low_value", sa.Float(), nullable=True),
            sa.Column("close_value", sa.Float(), nullable=True),
            sa.Column("price_change", sa.Float(), nullable=True),
            sa.Column("change_pct", sa.Float(), nullable=True),
            sa.Column("trade_volume", sa.BigInteger(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "index_id",
                "trade_date",
                name="uq_kr_index_daily_provider_index_date",
            ),
        )

    index_specs: tuple[tuple[str, str, list[str]], ...] = (
        ("kr_market_index", "ix_kr_market_index_index_id", ["index_id"]),
        ("kr_market_index", "ix_kr_market_index_provider_symbol", ["provider_symbol"]),
        ("kr_market_index", "ix_kr_market_index_market_segment", ["market_segment"]),
        ("kr_market_index", "ix_kr_market_index_index_family", ["index_family"]),
        ("kr_market_index", "ix_kr_market_index_provider", ["provider"]),
        ("kr_market_index", "ix_kr_market_index_currency", ["currency"]),
        ("kr_market_index", "ix_kr_market_index_sort_order", ["sort_order"]),
        ("kr_market_index", "ix_kr_market_index_is_active", ["is_active"]),
        ("kr_index_daily_price", "ix_kr_index_daily_provider", ["provider"]),
        ("kr_index_daily_price", "ix_kr_index_daily_index_id", ["index_id"]),
        ("kr_index_daily_price", "ix_kr_index_daily_trade_date", ["trade_date"]),
        ("kr_index_daily_price", "ix_kr_index_daily_currency", ["currency"]),
        ("kr_index_daily_price", "ix_kr_index_daily_raw_payload_hash", ["raw_payload_hash"]),
    )
    for table_name, index_name, columns in index_specs:
        _create_index(table_name, index_name, columns)


def downgrade() -> None:
    for table_name in (
        "kr_index_daily_price",
        "kr_market_index",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
