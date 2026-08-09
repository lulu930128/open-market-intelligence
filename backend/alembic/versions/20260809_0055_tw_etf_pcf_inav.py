"""Add Taiwan ETF PCF and intraday estimated NAV storage.

Revision ID: 20260809_0055
Revises: 20260809_0054
Create Date: 2026-08-09 20:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0055"
down_revision: str | Sequence[str] | None = "20260809_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PCF_SNAPSHOT_TABLE = "taiwan_etf_pcf_snapshot"
PCF_COMPONENT_TABLE = "taiwan_etf_pcf_component"
INAV_TABLE = "taiwan_etf_inav_snapshot"


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table(PCF_SNAPSHOT_TABLE):
        op.create_table(
            PCF_SNAPSHOT_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.Column("reference_date", sa.Date(), nullable=True),
            sa.Column("fund_id", sa.String(length=40), nullable=True),
            sa.Column("fund_name", sa.String(length=320), nullable=True),
            sa.Column("full_name", sa.String(length=480), nullable=True),
            sa.Column("name_en", sa.String(length=480), nullable=True),
            sa.Column("total_net_assets", sa.Numeric(precision=24, scale=6), nullable=True),
            sa.Column("issued_units", sa.BigInteger(), nullable=True),
            sa.Column("unit_nav", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("creation_unit", sa.BigInteger(), nullable=True),
            sa.Column(
                "estimated_creation_value",
                sa.Numeric(precision=24, scale=6),
                nullable=True,
            ),
            sa.Column(
                "estimated_cash_component",
                sa.Numeric(precision=24, scale=6),
                nullable=True,
            ),
            sa.Column("unit_change", sa.BigInteger(), nullable=True),
            sa.Column(
                "actual_cash_component",
                sa.Numeric(precision=24, scale=6),
                nullable=True,
            ),
            sa.Column("redemption_method", sa.String(length=40), nullable=False),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "stock_id",
                "effective_date",
                name="uq_taiwan_etf_pcf_snapshot_stock_date",
            ),
        )
        op.create_index("ix_taiwan_etf_pcf_snapshot_id", PCF_SNAPSHOT_TABLE, ["id"])
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_stock_id",
            PCF_SNAPSHOT_TABLE,
            ["stock_id"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_effective_date",
            PCF_SNAPSHOT_TABLE,
            ["effective_date"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_reference_date",
            PCF_SNAPSHOT_TABLE,
            ["reference_date"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_redemption_method",
            PCF_SNAPSHOT_TABLE,
            ["redemption_method"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_source",
            PCF_SNAPSHOT_TABLE,
            ["source"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_snapshot_stock_date",
            PCF_SNAPSHOT_TABLE,
            ["stock_id", "effective_date"],
        )

    if not _has_table(PCF_COMPONENT_TABLE):
        op.create_table(
            PCF_COMPONENT_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_id", sa.Integer(), nullable=False),
            sa.Column("source_section", sa.String(length=40), nullable=False),
            sa.Column("asset_type", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=320), nullable=True),
            sa.Column("name_en", sa.String(length=480), nullable=True),
            sa.Column("contract_month", sa.String(length=20), nullable=True),
            sa.Column("quantity", sa.Numeric(precision=24, scale=6), nullable=True),
            sa.Column("weight_pct", sa.Numeric(precision=14, scale=6), nullable=True),
            sa.Column("cash_in_lieu", sa.String(length=20), nullable=True),
            sa.Column("minimum_creation", sa.Boolean(), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["snapshot_id"],
                ["taiwan_etf_pcf_snapshot.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "snapshot_id",
                "order_index",
                name="uq_taiwan_etf_pcf_component_snapshot_order",
            ),
        )
        op.create_index("ix_taiwan_etf_pcf_component_id", PCF_COMPONENT_TABLE, ["id"])
        op.create_index(
            "ix_taiwan_etf_pcf_component_snapshot_id",
            PCF_COMPONENT_TABLE,
            ["snapshot_id"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_component_source_section",
            PCF_COMPONENT_TABLE,
            ["source_section"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_component_asset_type",
            PCF_COMPONENT_TABLE,
            ["asset_type"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_component_symbol",
            PCF_COMPONENT_TABLE,
            ["symbol"],
        )
        op.create_index(
            "ix_taiwan_etf_pcf_component_snapshot_asset",
            PCF_COMPONENT_TABLE,
            ["snapshot_id", "asset_type"],
        )

    if not _has_table(INAV_TABLE):
        op.create_table(
            INAV_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fund_short_name", sa.String(length=320), nullable=True),
            sa.Column("investment_area", sa.String(length=20), nullable=True),
            sa.Column("estimated_nav", sa.Numeric(precision=20, scale=6), nullable=False),
            sa.Column("nav_change", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("market_price", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("price_change", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column(
                "premium_discount_pct",
                sa.Numeric(precision=14, scale=6),
                nullable=True,
            ),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "stock_id",
                "observed_at",
                name="uq_taiwan_etf_inav_snapshot_stock_time",
            ),
        )
        op.create_index("ix_taiwan_etf_inav_snapshot_id", INAV_TABLE, ["id"])
        op.create_index(
            "ix_taiwan_etf_inav_snapshot_stock_id",
            INAV_TABLE,
            ["stock_id"],
        )
        op.create_index(
            "ix_taiwan_etf_inav_snapshot_observed_at",
            INAV_TABLE,
            ["observed_at"],
        )
        op.create_index(
            "ix_taiwan_etf_inav_snapshot_source",
            INAV_TABLE,
            ["source"],
        )
        op.create_index(
            "ix_taiwan_etf_inav_snapshot_stock_time",
            INAV_TABLE,
            ["stock_id", "observed_at"],
        )


def downgrade() -> None:
    if _has_table(INAV_TABLE):
        op.drop_table(INAV_TABLE)
    if _has_table(PCF_COMPONENT_TABLE):
        op.drop_table(PCF_COMPONENT_TABLE)
    if _has_table(PCF_SNAPSHOT_TABLE):
        op.drop_table(PCF_SNAPSHOT_TABLE)
