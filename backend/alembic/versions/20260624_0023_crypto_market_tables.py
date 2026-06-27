"""Add crypto market read-only tables.

Revision ID: 20260624_0023
Revises: 20260622_0022
Create Date: 2026-06-24 00:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260624_0023"
down_revision: str | Sequence[str] | None = "20260622_0022"
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
    if not _has_table("crypto_ticker_snapshot"):
        op.create_table(
            "crypto_ticker_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("last_price", sa.Float(), nullable=True),
            sa.Column("bid_price", sa.Float(), nullable=True),
            sa.Column("bid_size", sa.Float(), nullable=True),
            sa.Column("ask_price", sa.Float(), nullable=True),
            sa.Column("ask_size", sa.Float(), nullable=True),
            sa.Column("high_24h", sa.Float(), nullable=True),
            sa.Column("low_24h", sa.Float(), nullable=True),
            sa.Column("price_change_24h", sa.Float(), nullable=True),
            sa.Column("price_change_pct_24h", sa.Float(), nullable=True),
            sa.Column("base_volume_24h", sa.Float(), nullable=True),
            sa.Column("quote_volume_24h", sa.Float(), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "instrument_type",
                name="uq_crypto_ticker_provider_symbol_instrument",
            ),
        )
        _create_indexes(
            "crypto_ticker_snapshot",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_order_book_snapshot"):
        op.create_table(
            "crypto_order_book_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("depth_limit", sa.Integer(), nullable=False),
            sa.Column("best_bid_price", sa.Float(), nullable=True),
            sa.Column("best_bid_size", sa.Float(), nullable=True),
            sa.Column("best_ask_price", sa.Float(), nullable=True),
            sa.Column("best_ask_size", sa.Float(), nullable=True),
            sa.Column("spread", sa.Float(), nullable=True),
            sa.Column("spread_pct", sa.Float(), nullable=True),
            sa.Column("bids_json", sa.Text(), nullable=True),
            sa.Column("asks_json", sa.Text(), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "instrument_type",
                "depth_limit",
                name="uq_crypto_order_book_provider_symbol_instrument_depth",
            ),
        )
        _create_indexes(
            "crypto_order_book_snapshot",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "depth_limit",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_ohlcv_bar"):
        op.create_table(
            "crypto_ohlcv_bar",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("interval", sa.String(length=10), nullable=False),
            sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("base_volume", sa.Float(), nullable=True),
            sa.Column("quote_volume", sa.Float(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "instrument_type",
                "interval",
                "bar_time",
                name="uq_crypto_ohlcv_provider_symbol_instrument_interval_time",
            ),
        )
        _create_indexes(
            "crypto_ohlcv_bar",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "interval",
                "bar_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_derivatives_metric"):
        op.create_table(
            "crypto_derivatives_metric",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("mark_price", sa.Float(), nullable=True),
            sa.Column("index_price", sa.Float(), nullable=True),
            sa.Column("funding_rate", sa.Float(), nullable=True),
            sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("open_interest", sa.Float(), nullable=True),
            sa.Column("open_interest_value", sa.Float(), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "instrument_type",
                name="uq_crypto_derivatives_provider_symbol_instrument",
            ),
        )
        _create_indexes(
            "crypto_derivatives_metric",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "next_funding_time",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_market_cap_snapshot"):
        op.create_table(
            "crypto_market_cap_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("coin_id", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column("vs_currency", sa.String(length=10), nullable=False),
            sa.Column("current_price", sa.Float(), nullable=True),
            sa.Column("market_cap", sa.Float(), nullable=True),
            sa.Column("market_cap_rank", sa.Integer(), nullable=True),
            sa.Column("total_volume", sa.Float(), nullable=True),
            sa.Column("high_24h", sa.Float(), nullable=True),
            sa.Column("low_24h", sa.Float(), nullable=True),
            sa.Column("price_change_pct_24h", sa.Float(), nullable=True),
            sa.Column("circulating_supply", sa.Float(), nullable=True),
            sa.Column("total_supply", sa.Float(), nullable=True),
            sa.Column("max_supply", sa.Float(), nullable=True),
            sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "coin_id",
                "vs_currency",
                name="uq_crypto_market_cap_provider_coin_currency",
            ),
        )
        _create_indexes(
            "crypto_market_cap_snapshot",
            [
                "id",
                "provider",
                "coin_id",
                "symbol",
                "vs_currency",
                "market_cap_rank",
                "last_updated",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_spread_snapshot"):
        op.create_table(
            "crypto_spread_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("local_provider", sa.String(length=40), nullable=False),
            sa.Column("global_provider", sa.String(length=40), nullable=False),
            sa.Column("fx_provider", sa.String(length=40), nullable=False),
            sa.Column("local_symbol", sa.String(length=40), nullable=False),
            sa.Column("global_symbol", sa.String(length=40), nullable=False),
            sa.Column("fx_symbol", sa.String(length=40), nullable=False),
            sa.Column("local_price", sa.Float(), nullable=True),
            sa.Column("global_price", sa.Float(), nullable=True),
            sa.Column("fx_rate", sa.Float(), nullable=True),
            sa.Column("implied_twd_price", sa.Float(), nullable=True),
            sa.Column("spread", sa.Float(), nullable=True),
            sa.Column("spread_pct", sa.Float(), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_state_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "base_asset",
                "local_provider",
                "global_provider",
                "local_symbol",
                "global_symbol",
                "fx_symbol",
                name="uq_crypto_spread_base_local_global_fx",
            ),
        )
        _create_indexes(
            "crypto_spread_snapshot",
            [
                "id",
                "base_asset",
                "quote_asset",
                "local_provider",
                "global_provider",
                "fx_provider",
                "local_symbol",
                "global_symbol",
                "fx_symbol",
                "observed_at",
            ],
        )


def downgrade() -> None:
    for table_name, columns in (
        (
            "crypto_spread_snapshot",
            [
                "observed_at",
                "fx_symbol",
                "global_symbol",
                "local_symbol",
                "fx_provider",
                "global_provider",
                "local_provider",
                "quote_asset",
                "base_asset",
                "id",
            ],
        ),
        (
            "crypto_market_cap_snapshot",
            [
                "fetched_at",
                "last_updated",
                "market_cap_rank",
                "vs_currency",
                "symbol",
                "coin_id",
                "provider",
                "id",
            ],
        ),
        (
            "crypto_derivatives_metric",
            [
                "fetched_at",
                "event_time",
                "next_funding_time",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
        (
            "crypto_ohlcv_bar",
            [
                "fetched_at",
                "bar_time",
                "interval",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
        (
            "crypto_order_book_snapshot",
            [
                "fetched_at",
                "event_time",
                "depth_limit",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
        (
            "crypto_ticker_snapshot",
            [
                "fetched_at",
                "event_time",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
    ):
        if _has_table(table_name):
            for column in columns:
                _drop_index(table_name, f"ix_{table_name}_{column}")
            op.drop_table(table_name)
