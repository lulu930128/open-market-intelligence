"""add taiwan stock quote depth snapshots

Revision ID: 20260630_0027
Revises: 20260629_0026
Create Date: 2026-06-30 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260630_0027"
down_revision: str | Sequence[str] | None = "20260629_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _drop_index(table_name: str, index_name: str) -> None:
    if _has_index(table_name, index_name):
        op.drop_index(op.f(index_name), table_name=table_name)


def _create_indexes(table_name: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(op.f(f"ix_{table_name}_{column}"), table_name, [column], unique=False)


def upgrade() -> None:
    if _has_table("taiwan_stock_quote_snapshot"):
        return

    op.create_table(
        "taiwan_stock_quote_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=120), nullable=True),
        sa.Column("exchange_channel", sa.String(length=40), nullable=True),
        sa.Column("session_phase", sa.String(length=40), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("previous_close", sa.Float(), nullable=True),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("total_volume_lots", sa.BigInteger(), nullable=True),
        sa.Column("best_bid_price", sa.Float(), nullable=True),
        sa.Column("best_bid_size_lots", sa.BigInteger(), nullable=True),
        sa.Column("best_ask_price", sa.Float(), nullable=True),
        sa.Column("best_ask_size_lots", sa.BigInteger(), nullable=True),
        sa.Column("bid_total_size_lots", sa.BigInteger(), nullable=True),
        sa.Column("ask_total_size_lots", sa.BigInteger(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("spread_pct", sa.Float(), nullable=True),
        sa.Column("bid_levels_json", sa.Text(), nullable=True),
        sa.Column("ask_levels_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "stock_id",
            "quote_time",
            name="uq_tw_stock_quote_provider_stock_time",
        ),
    )
    _create_indexes(
        "taiwan_stock_quote_snapshot",
        [
            "id",
            "provider",
            "market",
            "stock_id",
            "exchange_channel",
            "session_phase",
            "trade_date",
            "quote_time",
            "source",
            "fetched_at",
        ],
    )


def downgrade() -> None:
    if not _has_table("taiwan_stock_quote_snapshot"):
        return

    for column in (
        "id",
        "provider",
        "market",
        "stock_id",
        "exchange_channel",
        "session_phase",
        "trade_date",
        "quote_time",
        "source",
        "fetched_at",
    ):
        _drop_index("taiwan_stock_quote_snapshot", f"ix_taiwan_stock_quote_snapshot_{column}")
    op.drop_table("taiwan_stock_quote_snapshot")
