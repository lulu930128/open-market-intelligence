"""Add Taiwan intraday market-state quality and rolling snapshot tables.

Revision ID: 20260730_0044
Revises: 20260729_0043
Create Date: 2026-07-30 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0044"
down_revision: str | Sequence[str] | None = "20260729_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {
        str(column["name"])
        for column in _inspector().get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {
        str(index["name"])
        for index in _inspector().get_indexes(table_name)
    }


def _add_index(
    table_name: str,
    column_name: str,
    *,
    index_name: str | None = None,
) -> None:
    name = index_name or f"ix_{table_name}_{column_name}"
    if not _has_index(table_name, name):
        op.create_index(name, table_name, [column_name], unique=False)


def upgrade() -> None:
    minute_table = "taiwan_market_minute_state"
    if _has_table(minute_table):
        additions = (
            (
                "quote_quality_status",
                sa.Column(
                    "quote_quality_status",
                    sa.String(length=30),
                    nullable=False,
                    server_default="unknown",
                ),
            ),
            (
                "trade_value_quality_status",
                sa.Column(
                    "trade_value_quality_status",
                    sa.String(length=30),
                    nullable=False,
                    server_default="unknown",
                ),
            ),
            (
                "trade_value_semantics",
                sa.Column(
                    "trade_value_semantics",
                    sa.String(length=120),
                    nullable=True,
                ),
            ),
            (
                "trade_value_confidence",
                sa.Column(
                    "trade_value_confidence",
                    sa.String(length=20),
                    nullable=True,
                ),
            ),
            (
                "trade_value_is_estimate",
                sa.Column(
                    "trade_value_is_estimate",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            ),
        )
        for name, column in additions:
            if not _has_column(minute_table, name):
                op.add_column(minute_table, column)
        op.execute(
            sa.text(
                """
                UPDATE taiwan_market_minute_state
                SET quote_quality_status = CASE
                        WHEN index_value IS NOT NULL THEN 'ready'
                        ELSE 'missing'
                    END
                WHERE quote_quality_status = 'unknown'
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE taiwan_market_minute_state
                SET trade_value_quality_status = CASE
                        WHEN cumulative_trade_value IS NOT NULL THEN 'ready'
                        ELSE 'missing'
                    END,
                    trade_value_semantics = CASE
                        WHEN cumulative_trade_value IS NOT NULL
                            AND trade_value_semantics IS NULL
                        THEN 'legacy_cumulative_trade_value'
                        ELSE trade_value_semantics
                    END,
                    trade_value_confidence = CASE
                        WHEN cumulative_trade_value IS NOT NULL
                            AND trade_value_confidence IS NULL
                        THEN 'unknown'
                        ELSE trade_value_confidence
                    END
                WHERE trade_value_quality_status = 'unknown'
                """
            )
        )
        _add_index(minute_table, "quote_quality_status")
        _add_index(minute_table, "trade_value_quality_status")

    if not _has_table("taiwan_index_minute_snapshot"):
        op.create_table(
            "taiwan_index_minute_snapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("index_id", sa.String(length=20), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("minute_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("open_value", sa.Float(), nullable=True),
            sa.Column("high_value", sa.Float(), nullable=True),
            sa.Column("low_value", sa.Float(), nullable=True),
            sa.Column("close_value", sa.Float(), nullable=True),
            sa.Column("previous_close", sa.Float(), nullable=True),
            sa.Column(
                "source_interval",
                sa.String(length=20),
                nullable=False,
                server_default="snapshot",
            ),
            sa.Column(
                "source_point_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "synthetic",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "indicator_eligible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "quality_status",
                sa.String(length=30),
                nullable=False,
                server_default="partial",
            ),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "index_id",
                "minute_at",
                name="uq_tw_index_minute_provider_index_time",
            ),
        )
        for column in (
            "id",
            "provider",
            "index_id",
            "market",
            "trade_date",
            "minute_at",
            "event_time",
            "source_interval",
            "synthetic",
            "indicator_eligible",
            "quality_status",
            "source",
        ):
            _add_index("taiwan_index_minute_snapshot", column)

    if not _has_table("taiwan_intraday_stock_state"):
        op.create_table(
            "taiwan_intraday_stock_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("current_price", sa.Float(), nullable=True),
            sa.Column("previous_close", sa.Float(), nullable=True),
            sa.Column("open_price", sa.Float(), nullable=True),
            sa.Column("high_price", sa.Float(), nullable=True),
            sa.Column("low_price", sa.Float(), nullable=True),
            sa.Column("cumulative_volume_lots", sa.BigInteger(), nullable=True),
            sa.Column("estimated_trade_value", sa.BigInteger(), nullable=True),
            sa.Column("change_pct", sa.Float(), nullable=True),
            sa.Column("distance_from_high_pct", sa.Float(), nullable=True),
            sa.Column("rebound_from_low_pct", sa.Float(), nullable=True),
            sa.Column("five_minute_return", sa.Float(), nullable=True),
            sa.Column("fifteen_minute_return", sa.Float(), nullable=True),
            sa.Column("intraday_range_pct", sa.Float(), nullable=True),
            sa.Column("vwap_estimate", sa.Float(), nullable=True),
            sa.Column("vwap_deviation_pct", sa.Float(), nullable=True),
            sa.Column("order_book_imbalance", sa.Float(), nullable=True),
            sa.Column(
                "sample_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("samples_json", sa.Text(), nullable=True),
            sa.Column(
                "freshness_status",
                sa.String(length=30),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column(
                "quality_status",
                sa.String(length=30),
                nullable=False,
                server_default="partial",
            ),
            sa.Column(
                "trade_value_semantics",
                sa.String(length=120),
                nullable=False,
                server_default=(
                    "estimated_current_price_x_cumulative_volume_lots"
                ),
            ),
            sa.Column("source", sa.String(length=120), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "market",
                "stock_id",
                name="uq_tw_intraday_state_provider_market_stock",
            ),
        )
        for column in (
            "id",
            "provider",
            "market",
            "stock_id",
            "trade_date",
            "event_time",
            "freshness_status",
            "quality_status",
            "source",
        ):
            _add_index("taiwan_intraday_stock_state", column)


def downgrade() -> None:
    if _has_table("taiwan_intraday_stock_state"):
        op.drop_table("taiwan_intraday_stock_state")
    if _has_table("taiwan_index_minute_snapshot"):
        op.drop_table("taiwan_index_minute_snapshot")

    minute_table = "taiwan_market_minute_state"
    if _has_table(minute_table):
        for index_name in (
            "ix_taiwan_market_minute_state_trade_value_quality_status",
            "ix_taiwan_market_minute_state_quote_quality_status",
        ):
            if _has_index(minute_table, index_name):
                op.drop_index(index_name, table_name=minute_table)
        for column_name in (
            "trade_value_is_estimate",
            "trade_value_confidence",
            "trade_value_semantics",
            "trade_value_quality_status",
            "quote_quality_status",
        ):
            if _has_column(minute_table, column_name):
                op.drop_column(minute_table, column_name)
