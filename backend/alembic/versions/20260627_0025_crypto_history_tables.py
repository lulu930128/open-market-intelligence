"""add crypto sampled history tables

Revision ID: 20260627_0025
Revises: 20260625_0024
Create Date: 2026-06-27 17:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260627_0025"
down_revision: str | Sequence[str] | None = "20260625_0024"
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
    if not _has_table("crypto_ticker_history"):
        op.create_table(
            "crypto_ticker_history",
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
            sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
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
                "sampled_at",
                name="uq_crypto_ticker_history_provider_symbol_instrument_sampled",
            ),
        )
        _create_indexes(
            "crypto_ticker_history",
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
                "sampled_at",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_liquidity_history"):
        op.create_table(
            "crypto_liquidity_history",
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
            sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
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
                "sampled_at",
                name="uq_crypto_liquidity_history_provider_symbol_instrument_depth_sampled",
            ),
        )
        _create_indexes(
            "crypto_liquidity_history",
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
                "sampled_at",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_derivatives_metric_history"):
        op.create_table(
            "crypto_derivatives_metric_history",
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
            sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
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
                "sampled_at",
                name="uq_crypto_derivatives_history_provider_symbol_instrument_sampled",
            ),
        )
        _create_indexes(
            "crypto_derivatives_metric_history",
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
                "sampled_at",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_spread_history"):
        op.create_table(
            "crypto_spread_history",
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
            sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
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
                "sampled_at",
                name="uq_crypto_spread_history_base_local_global_fx_sampled",
            ),
        )
        _create_indexes(
            "crypto_spread_history",
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
                "sampled_at",
            ],
        )


def downgrade() -> None:
    for table_name, columns in (
        (
            "crypto_spread_history",
            [
                "sampled_at",
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
            "crypto_derivatives_metric_history",
            [
                "fetched_at",
                "sampled_at",
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
            "crypto_liquidity_history",
            [
                "fetched_at",
                "sampled_at",
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
            "crypto_ticker_history",
            [
                "fetched_at",
                "sampled_at",
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
