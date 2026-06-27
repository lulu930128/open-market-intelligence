"""add resource market tables

Revision ID: 20260625_0024
Revises: 20260624_0023
Create Date: 2026-06-25 00:30:00
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260625_0024"
down_revision: str | Sequence[str] | None = "20260624_0023"
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


def _table_row_count(table_name: str) -> int:
    return int(op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)


def _seed_resource_instruments() -> None:
    if _table_row_count("resource_market_instrument") > 0:
        return

    table = sa.table(
        "resource_market_instrument",
        sa.column("key", sa.String),
        sa.column("root_folder", sa.String),
        sa.column("group", sa.String),
        sa.column("asset_class", sa.String),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("symbol", sa.String),
        sa.column("provider", sa.String),
        sa.column("exchange", sa.String),
        sa.column("provider_symbol", sa.String),
        sa.column("base_asset", sa.String),
        sa.column("quote_asset", sa.String),
        sa.column("instrument_type", sa.String),
        sa.column("contract_type", sa.String),
        sa.column("tradable", sa.Boolean),
        sa.column("trade_candidate", sa.Boolean),
        sa.column("resources_json", sa.Text),
        sa.column("provider_status", sa.String),
        sa.column("notes", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    common = {
        "root_folder": "commodity",
        "asset_class": "commodity_futures",
        "provider": "provider_pending",
        "quote_asset": "USDT",
        "instrument_type": "futures",
        "contract_type": "front_month",
        "tradable": False,
        "trade_candidate": False,
        "resources_json": json.dumps(["quote", "ohlcv"], ensure_ascii=False),
        "provider_status": "provider_pending",
        "created_at": now,
        "updated_at": now,
    }
    op.bulk_insert(
        table,
        [
            {
                **common,
                "key": "commodity:metals:GC",
                "group": "metals",
                "name": "Gold Futures",
                "display_name": "黃金",
                "symbol": "GC",
                "exchange": "COMEX",
                "provider_symbol": "GC",
                "base_asset": "GOLD",
                "notes": "Gold futures watch-only resource context.",
            },
            {
                **common,
                "key": "commodity:metals:SI",
                "group": "metals",
                "name": "Silver Futures",
                "display_name": "白銀",
                "symbol": "SI",
                "exchange": "COMEX",
                "provider_symbol": "SI",
                "base_asset": "SILVER",
                "notes": "Silver futures watch-only resource context.",
            },
            {
                **common,
                "key": "commodity:metals:HG",
                "group": "metals",
                "name": "Copper Futures",
                "display_name": "銅",
                "symbol": "HG",
                "exchange": "COMEX",
                "provider_symbol": "HG",
                "base_asset": "COPPER",
                "notes": "Copper futures watch-only resource context.",
            },
            {
                **common,
                "key": "commodity:energy:CL",
                "group": "energy",
                "name": "WTI Crude Oil Futures",
                "display_name": "WTI 原油",
                "symbol": "CL",
                "exchange": "NYMEX",
                "provider_symbol": "CL",
                "base_asset": "WTI_CRUDE",
                "notes": "WTI crude oil futures watch-only resource context.",
            },
            {
                **common,
                "key": "commodity:energy:BZ",
                "group": "energy",
                "name": "Brent Crude Oil Futures",
                "display_name": "Brent 原油",
                "symbol": "BZ",
                "exchange": "NYMEX",
                "provider_symbol": "BZ",
                "base_asset": "BRENT_CRUDE",
                "notes": "Brent crude oil futures watch-only resource context.",
            },
            {
                **common,
                "key": "commodity:energy:NG",
                "group": "energy",
                "name": "Henry Hub Natural Gas Futures",
                "display_name": "天然氣",
                "symbol": "NG",
                "exchange": "NYMEX",
                "provider_symbol": "NG",
                "base_asset": "NATURAL_GAS",
                "notes": "Natural gas futures watch-only resource context.",
            },
        ],
    )


def upgrade() -> None:
    if not _has_table("resource_market_instrument"):
        op.create_table(
            "resource_market_instrument",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=80), nullable=False),
            sa.Column("root_folder", sa.String(length=40), nullable=False),
            sa.Column("group", sa.String(length=40), nullable=False),
            sa.Column("asset_class", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("provider_symbol", sa.String(length=80), nullable=False),
            sa.Column("base_asset", sa.String(length=30), nullable=False),
            sa.Column("quote_asset", sa.String(length=30), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("contract_type", sa.String(length=40), nullable=False),
            sa.Column("tradable", sa.Boolean(), nullable=False),
            sa.Column("trade_candidate", sa.Boolean(), nullable=False),
            sa.Column("resources_json", sa.Text(), nullable=True),
            sa.Column("provider_status", sa.String(length=40), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key", name="uq_resource_market_instrument_key"),
        )
        _create_indexes(
            "resource_market_instrument",
            [
                "id",
                "key",
                "root_folder",
                "group",
                "asset_class",
                "symbol",
                "provider",
                "exchange",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "contract_type",
                "tradable",
                "trade_candidate",
                "provider_status",
            ],
        )

    if not _has_table("resource_quote_snapshot"):
        op.create_table(
            "resource_quote_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column("root_folder", sa.String(length=40), nullable=False),
            sa.Column("group", sa.String(length=40), nullable=False),
            sa.Column("asset_class", sa.String(length=40), nullable=False),
            sa.Column("base_asset", sa.String(length=30), nullable=False),
            sa.Column("quote_asset", sa.String(length=30), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("contract_key", sa.String(length=80), nullable=False),
            sa.Column("contract_month", sa.String(length=20), nullable=True),
            sa.Column("last_price", sa.Float(), nullable=True),
            sa.Column("bid_price", sa.Float(), nullable=True),
            sa.Column("ask_price", sa.Float(), nullable=True),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("previous_close", sa.Float(), nullable=True),
            sa.Column("price_change", sa.Float(), nullable=True),
            sa.Column("price_change_pct", sa.Float(), nullable=True),
            sa.Column("volume", sa.Float(), nullable=True),
            sa.Column("open_interest", sa.Float(), nullable=True),
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
                "contract_key",
                name="uq_resource_quote_provider_symbol_instrument_contract",
            ),
        )
        _create_indexes(
            "resource_quote_snapshot",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "root_folder",
                "group",
                "asset_class",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "contract_key",
                "contract_month",
                "event_time",
                "fetched_at",
            ],
        )

    if not _has_table("resource_ohlcv_bar"):
        op.create_table(
            "resource_ohlcv_bar",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("exchange", sa.String(length=80), nullable=False),
            sa.Column("symbol", sa.String(length=40), nullable=False),
            sa.Column("provider_symbol", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column("root_folder", sa.String(length=40), nullable=False),
            sa.Column("group", sa.String(length=40), nullable=False),
            sa.Column("asset_class", sa.String(length=40), nullable=False),
            sa.Column("base_asset", sa.String(length=30), nullable=False),
            sa.Column("quote_asset", sa.String(length=30), nullable=False),
            sa.Column("instrument_type", sa.String(length=30), nullable=False),
            sa.Column("contract_key", sa.String(length=80), nullable=False),
            sa.Column("contract_month", sa.String(length=20), nullable=True),
            sa.Column("interval", sa.String(length=10), nullable=False),
            sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("volume", sa.Float(), nullable=True),
            sa.Column("open_interest", sa.Float(), nullable=True),
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
                "contract_key",
                "interval",
                "bar_time",
                name="uq_resource_ohlcv_provider_symbol_instrument_contract_interval_time",
            ),
        )
        _create_indexes(
            "resource_ohlcv_bar",
            [
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "root_folder",
                "group",
                "asset_class",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "contract_key",
                "contract_month",
                "interval",
                "bar_time",
                "fetched_at",
            ],
        )

    _seed_resource_instruments()


def downgrade() -> None:
    for table_name, columns in (
        (
            "resource_ohlcv_bar",
            [
                "fetched_at",
                "bar_time",
                "interval",
                "contract_month",
                "contract_key",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "asset_class",
                "group",
                "root_folder",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
        (
            "resource_quote_snapshot",
            [
                "fetched_at",
                "event_time",
                "contract_month",
                "contract_key",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "asset_class",
                "group",
                "root_folder",
                "provider_symbol",
                "symbol",
                "exchange",
                "provider",
                "id",
            ],
        ),
        (
            "resource_market_instrument",
            [
                "provider_status",
                "trade_candidate",
                "tradable",
                "contract_type",
                "instrument_type",
                "quote_asset",
                "base_asset",
                "provider_symbol",
                "exchange",
                "provider",
                "symbol",
                "asset_class",
                "group",
                "root_folder",
                "key",
                "id",
            ],
        ),
    ):
        if _has_table(table_name):
            for column in columns:
                _drop_index(table_name, f"ix_{table_name}_{column}")
            op.drop_table(table_name)
