"""Add expanded US market resource tables.

Revision ID: 20260531_0007
Revises: 20260531_0006
Create Date: 2026-05-31 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260531_0007"
down_revision: str | Sequence[str] | None = "20260531_0006"
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
    if not _has_table("us_company_profile"):
        op.create_table(
            "us_company_profile",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("company_name", sa.String(length=240), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("exchange", sa.String(length=80), nullable=True),
            sa.Column("sector", sa.String(length=120), nullable=True),
            sa.Column("industry", sa.String(length=160), nullable=True),
            sa.Column("country", sa.String(length=80), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=True),
            sa.Column("market_cap", sa.BigInteger(), nullable=True),
            sa.Column("ebitda", sa.BigInteger(), nullable=True),
            sa.Column("pe_ratio", sa.Float(), nullable=True),
            sa.Column("peg_ratio", sa.Float(), nullable=True),
            sa.Column("beta", sa.Float(), nullable=True),
            sa.Column("dividend_yield", sa.Float(), nullable=True),
            sa.Column("eps", sa.Float(), nullable=True),
            sa.Column("revenue_ttm", sa.BigInteger(), nullable=True),
            sa.Column("profit_margin", sa.Float(), nullable=True),
            sa.Column("fiscal_year_end", sa.String(length=40), nullable=True),
            sa.Column("latest_quarter", sa.Date(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "symbol", name="uq_us_company_profile_provider_symbol"),
        )
        op.create_index(op.f("ix_us_company_profile_country"), "us_company_profile", ["country"], unique=False)
        op.create_index(op.f("ix_us_company_profile_currency"), "us_company_profile", ["currency"], unique=False)
        op.create_index(op.f("ix_us_company_profile_exchange"), "us_company_profile", ["exchange"], unique=False)
        op.create_index(op.f("ix_us_company_profile_id"), "us_company_profile", ["id"], unique=False)
        op.create_index(op.f("ix_us_company_profile_industry"), "us_company_profile", ["industry"], unique=False)
        op.create_index(op.f("ix_us_company_profile_latest_quarter"), "us_company_profile", ["latest_quarter"], unique=False)
        op.create_index(op.f("ix_us_company_profile_provider"), "us_company_profile", ["provider"], unique=False)
        op.create_index(op.f("ix_us_company_profile_raw_payload_hash"), "us_company_profile", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_us_company_profile_sector"), "us_company_profile", ["sector"], unique=False)
        op.create_index(op.f("ix_us_company_profile_symbol"), "us_company_profile", ["symbol"], unique=False)

    if not _has_table("us_corporate_action"):
        op.create_table(
            "us_corporate_action",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("action_type", sa.String(length=40), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("declaration_date", sa.Date(), nullable=True),
            sa.Column("record_date", sa.Date(), nullable=True),
            sa.Column("payment_date", sa.Date(), nullable=True),
            sa.Column("amount", sa.Float(), nullable=True),
            sa.Column("split_from", sa.Float(), nullable=True),
            sa.Column("split_to", sa.Float(), nullable=True),
            sa.Column("split_ratio", sa.Float(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "symbol",
                "action_type",
                "event_date",
                name="uq_us_corporate_action_provider_symbol_type_date",
            ),
        )
        op.create_index(op.f("ix_us_corporate_action_action_type"), "us_corporate_action", ["action_type"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_declaration_date"), "us_corporate_action", ["declaration_date"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_event_date"), "us_corporate_action", ["event_date"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_id"), "us_corporate_action", ["id"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_payment_date"), "us_corporate_action", ["payment_date"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_provider"), "us_corporate_action", ["provider"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_raw_payload_hash"), "us_corporate_action", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_record_date"), "us_corporate_action", ["record_date"], unique=False)
        op.create_index(op.f("ix_us_corporate_action_symbol"), "us_corporate_action", ["symbol"], unique=False)

    if not _has_table("us_short_volume_daily"):
        op.create_table(
            "us_short_volume_daily",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("market_center", sa.String(length=40), nullable=False),
            sa.Column("short_volume", sa.BigInteger(), nullable=True),
            sa.Column("short_exempt_volume", sa.BigInteger(), nullable=True),
            sa.Column("total_volume", sa.BigInteger(), nullable=True),
            sa.Column("short_ratio", sa.Float(), nullable=True),
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
                "market_center",
                name="uq_us_short_volume_provider_symbol_date_market",
            ),
        )
        op.create_index(op.f("ix_us_short_volume_daily_id"), "us_short_volume_daily", ["id"], unique=False)
        op.create_index(op.f("ix_us_short_volume_daily_market_center"), "us_short_volume_daily", ["market_center"], unique=False)
        op.create_index(op.f("ix_us_short_volume_daily_provider"), "us_short_volume_daily", ["provider"], unique=False)
        op.create_index(op.f("ix_us_short_volume_daily_raw_payload_hash"), "us_short_volume_daily", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_us_short_volume_daily_symbol"), "us_short_volume_daily", ["symbol"], unique=False)
        op.create_index(op.f("ix_us_short_volume_daily_trade_date"), "us_short_volume_daily", ["trade_date"], unique=False)

    if not _has_table("macro_series_observation"):
        op.create_table(
            "macro_series_observation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("series_id", sa.String(length=80), nullable=False),
            sa.Column("series_name", sa.String(length=240), nullable=True),
            sa.Column("observation_date", sa.Date(), nullable=False),
            sa.Column("value", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(length=80), nullable=True),
            sa.Column("frequency", sa.String(length=80), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "series_id",
                "observation_date",
                name="uq_macro_series_observation_provider_series_date",
            ),
        )
        op.create_index(op.f("ix_macro_series_observation_id"), "macro_series_observation", ["id"], unique=False)
        op.create_index(op.f("ix_macro_series_observation_observation_date"), "macro_series_observation", ["observation_date"], unique=False)
        op.create_index(op.f("ix_macro_series_observation_provider"), "macro_series_observation", ["provider"], unique=False)
        op.create_index(op.f("ix_macro_series_observation_raw_payload_hash"), "macro_series_observation", ["raw_payload_hash"], unique=False)
        op.create_index(op.f("ix_macro_series_observation_series_id"), "macro_series_observation", ["series_id"], unique=False)


def downgrade() -> None:
    if _has_table("macro_series_observation"):
        _drop_indexes(
            "macro_series_observation",
            (
                "ix_macro_series_observation_series_id",
                "ix_macro_series_observation_raw_payload_hash",
                "ix_macro_series_observation_provider",
                "ix_macro_series_observation_observation_date",
                "ix_macro_series_observation_id",
            ),
        )
        op.drop_table("macro_series_observation")

    if _has_table("us_short_volume_daily"):
        _drop_indexes(
            "us_short_volume_daily",
            (
                "ix_us_short_volume_daily_trade_date",
                "ix_us_short_volume_daily_symbol",
                "ix_us_short_volume_daily_raw_payload_hash",
                "ix_us_short_volume_daily_provider",
                "ix_us_short_volume_daily_market_center",
                "ix_us_short_volume_daily_id",
            ),
        )
        op.drop_table("us_short_volume_daily")

    if _has_table("us_corporate_action"):
        _drop_indexes(
            "us_corporate_action",
            (
                "ix_us_corporate_action_symbol",
                "ix_us_corporate_action_record_date",
                "ix_us_corporate_action_raw_payload_hash",
                "ix_us_corporate_action_provider",
                "ix_us_corporate_action_payment_date",
                "ix_us_corporate_action_id",
                "ix_us_corporate_action_event_date",
                "ix_us_corporate_action_declaration_date",
                "ix_us_corporate_action_action_type",
            ),
        )
        op.drop_table("us_corporate_action")

    if _has_table("us_company_profile"):
        _drop_indexes(
            "us_company_profile",
            (
                "ix_us_company_profile_symbol",
                "ix_us_company_profile_sector",
                "ix_us_company_profile_raw_payload_hash",
                "ix_us_company_profile_provider",
                "ix_us_company_profile_latest_quarter",
                "ix_us_company_profile_industry",
                "ix_us_company_profile_id",
                "ix_us_company_profile_exchange",
                "ix_us_company_profile_currency",
                "ix_us_company_profile_country",
            ),
        )
        op.drop_table("us_company_profile")
