"""add crypto advanced metric tables

Revision ID: 20260629_0026
Revises: 20260627_0025
Create Date: 2026-06-29 00:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_0026"
down_revision: str | Sequence[str] | None = "20260627_0025"
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
    if not _has_table("crypto_liquidation_event"):
        op.create_table(
            "crypto_liquidation_event",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("liquidation_side", sa.String(length=20), nullable=False),
            sa.Column("order_side", sa.String(length=20), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("average_price", sa.Float(), nullable=True),
            sa.Column("quantity", sa.Float(), nullable=True),
            sa.Column("notional", sa.Float(), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
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
                "event_time",
                "liquidation_side",
                "price",
                "quantity",
                name="uq_crypto_liquidation_event_identity",
            ),
        )
        _create_indexes(
            "crypto_liquidation_event",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "liquidation_side",
                "order_side",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_liquidation_heatmap_cell"):
        op.create_table(
            "crypto_liquidation_heatmap_cell",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("source_kind", sa.String(length=40), nullable=False),
            sa.Column("method", sa.String(length=80), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("time_bucket", sa.DateTime(timezone=True), nullable=False),
            sa.Column("bucket_seconds", sa.Integer(), nullable=False),
            sa.Column("price_bucket", sa.Float(), nullable=False),
            sa.Column("price_bucket_size", sa.Float(), nullable=True),
            sa.Column("liquidation_side", sa.String(length=20), nullable=False),
            sa.Column("liquidation_notional", sa.Float(), nullable=True),
            sa.Column("liquidation_quantity", sa.Float(), nullable=True),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("intensity", sa.Float(), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "source_kind",
                "method",
                "symbol",
                "instrument_type",
                "time_bucket",
                "bucket_seconds",
                "price_bucket",
                "liquidation_side",
                name="uq_crypto_liquidation_heatmap_cell_identity",
            ),
        )
        _create_indexes(
            "crypto_liquidation_heatmap_cell",
            [
                "id",
                "provider",
                "source_kind",
                "method",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "time_bucket",
                "bucket_seconds",
                "price_bucket",
                "liquidation_side",
                "generated_at",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_cvd_history"):
        op.create_table(
            "crypto_cvd_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("bucket_seconds", sa.Integer(), nullable=False),
            sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("buy_base_volume", sa.Float(), nullable=True),
            sa.Column("sell_base_volume", sa.Float(), nullable=True),
            sa.Column("buy_quote_volume", sa.Float(), nullable=True),
            sa.Column("sell_quote_volume", sa.Float(), nullable=True),
            sa.Column("net_base_volume", sa.Float(), nullable=True),
            sa.Column("net_quote_volume", sa.Float(), nullable=True),
            sa.Column("cumulative_base_delta", sa.Float(), nullable=True),
            sa.Column("cumulative_quote_delta", sa.Float(), nullable=True),
            sa.Column("trade_count", sa.Integer(), nullable=False),
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
                "bucket_seconds",
                "sampled_at",
                name="uq_crypto_cvd_history_provider_symbol_instrument_bucket_sampled",
            ),
        )
        _create_indexes(
            "crypto_cvd_history",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "bucket_seconds",
                "sampled_at",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("crypto_long_short_ratio_history"):
        op.create_table(
            "crypto_long_short_ratio_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=60), nullable=False),
            sa.Column("base_asset", sa.String(length=20), nullable=False),
            sa.Column("quote_asset", sa.String(length=20), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("ratio_scope", sa.String(length=60), nullable=False),
            sa.Column("long_ratio", sa.Float(), nullable=True),
            sa.Column("short_ratio", sa.Float(), nullable=True),
            sa.Column("long_short_ratio", sa.Float(), nullable=True),
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
                "ratio_scope",
                "sampled_at",
                name="uq_crypto_long_short_ratio_provider_symbol_scope_sampled",
            ),
        )
        _create_indexes(
            "crypto_long_short_ratio_history",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "ratio_scope",
                "event_time",
                "sampled_at",
                "fetched_at",
            ],
        )


def downgrade() -> None:
    for table_name, columns in (
        (
            "crypto_long_short_ratio_history",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "ratio_scope",
                "event_time",
                "sampled_at",
                "fetched_at",
            ],
        ),
        (
            "crypto_cvd_history",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "bucket_seconds",
                "sampled_at",
                "event_time",
                "fetched_at",
            ],
        ),
        (
            "crypto_liquidation_heatmap_cell",
            [
                "id",
                "provider",
                "source_kind",
                "method",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "time_bucket",
                "bucket_seconds",
                "price_bucket",
                "liquidation_side",
                "generated_at",
                "fetched_at",
            ],
        ),
        (
            "crypto_liquidation_event",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "liquidation_side",
                "order_side",
                "event_time",
                "fetched_at",
            ],
        ),
    ):
        if _has_table(table_name):
            for column in columns:
                _drop_index(table_name, f"ix_{table_name}_{column}")
            op.drop_table(table_name)
