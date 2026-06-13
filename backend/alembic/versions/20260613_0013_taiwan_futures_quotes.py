"""Add Taiwan futures quote and bar tables.

Revision ID: 20260613_0013
Revises: 20260612_0012
Create Date: 2026-06-13 15:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260613_0013"
down_revision: str | Sequence[str] | None = "20260612_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_quote_table() -> None:
    op.create_table(
        "taiwan_futures_quote_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("product_code", sa.String(length=20), nullable=False),
        sa.Column("product_name", sa.String(length=80), nullable=False),
        sa.Column("contract_symbol", sa.String(length=40), nullable=False),
        sa.Column("contract_month", sa.String(length=20), nullable=True),
        sa.Column("session", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("reference_price", sa.Float(), nullable=True),
        sa.Column("settlement_price", sa.Float(), nullable=True),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("amplitude_pct", sa.Float(), nullable=True),
        sa.Column("total_volume", sa.BigInteger(), nullable=True),
        sa.Column("open_interest", sa.BigInteger(), nullable=True),
        sa.Column("bid_price", sa.Float(), nullable=True),
        sa.Column("bid_size", sa.BigInteger(), nullable=True),
        sa.Column("ask_price", sa.Float(), nullable=True),
        sa.Column("ask_size", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "session",
            "quote_time",
            name="uq_tw_futures_quote_provider_symbol_contract_session_time",
        ),
    )

    for column in (
        "id",
        "provider",
        "market",
        "symbol",
        "product_code",
        "contract_symbol",
        "contract_month",
        "session",
        "trade_date",
        "quote_time",
        "source",
        "fetched_at",
    ):
        op.create_index(
            op.f(f"ix_taiwan_futures_quote_snapshot_{column}"),
            "taiwan_futures_quote_snapshot",
            [column],
            unique=False,
        )


def _create_intraday_table() -> None:
    op.create_table(
        "taiwan_futures_intraday_bar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("product_code", sa.String(length=20), nullable=False),
        sa.Column("product_name", sa.String(length=80), nullable=False),
        sa.Column("contract_symbol", sa.String(length=40), nullable=False),
        sa.Column("contract_month", sa.String(length=20), nullable=True),
        sa.Column("session", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("total_volume", sa.BigInteger(), nullable=True),
        sa.Column("open_interest", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "interval",
            "bar_time",
            name="uq_tw_futures_bar_provider_symbol_contract_interval_time",
        ),
    )

    for column in (
        "id",
        "provider",
        "market",
        "symbol",
        "product_code",
        "contract_symbol",
        "contract_month",
        "session",
        "interval",
        "bar_time",
        "source",
    ):
        op.create_index(
            op.f(f"ix_taiwan_futures_intraday_bar_{column}"),
            "taiwan_futures_intraday_bar",
            [column],
            unique=False,
        )


def _create_daily_table() -> None:
    op.create_table(
        "taiwan_futures_daily_bar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("product_code", sa.String(length=20), nullable=False),
        sa.Column("product_name", sa.String(length=80), nullable=False),
        sa.Column("contract_symbol", sa.String(length=40), nullable=False),
        sa.Column("contract_month", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=True),
        sa.Column("high_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("settlement_price", sa.Float(), nullable=True),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("after_hours_volume", sa.BigInteger(), nullable=True),
        sa.Column("regular_volume", sa.BigInteger(), nullable=True),
        sa.Column("total_volume", sa.BigInteger(), nullable=True),
        sa.Column("open_interest", sa.BigInteger(), nullable=True),
        sa.Column("bid_price", sa.Float(), nullable=True),
        sa.Column("ask_price", sa.Float(), nullable=True),
        sa.Column("historical_high_price", sa.Float(), nullable=True),
        sa.Column("historical_low_price", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            "contract_month",
            "trade_date",
            name="uq_tw_futures_daily_provider_symbol_contract_date",
        ),
    )

    for column in (
        "id",
        "provider",
        "market",
        "symbol",
        "product_code",
        "contract_symbol",
        "contract_month",
        "trade_date",
        "source",
        "fetched_at",
    ):
        op.create_index(
            op.f(f"ix_taiwan_futures_daily_bar_{column}"),
            "taiwan_futures_daily_bar",
            [column],
            unique=False,
        )


def upgrade() -> None:
    if not _has_table("taiwan_futures_quote_snapshot"):
        _create_quote_table()

    if not _has_table("taiwan_futures_intraday_bar"):
        _create_intraday_table()

    if not _has_table("taiwan_futures_daily_bar"):
        _create_daily_table()


def downgrade() -> None:
    if _has_table("taiwan_futures_daily_bar"):
        op.drop_table("taiwan_futures_daily_bar")

    if _has_table("taiwan_futures_intraday_bar"):
        op.drop_table("taiwan_futures_intraday_bar")

    if _has_table("taiwan_futures_quote_snapshot"):
        op.drop_table("taiwan_futures_quote_snapshot")
