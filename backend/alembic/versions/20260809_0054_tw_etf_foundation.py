"""Add Taiwan ETF profile and daily NAV storage.

Revision ID: 20260809_0054
Revises: 20260804_0051, 20260809_0053
Create Date: 2026-08-09 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260809_0054"
down_revision: str | Sequence[str] | None = (
    "20260804_0051",
    "20260809_0053",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROFILE_TABLE = "taiwan_etf_profile"
NAV_TABLE = "taiwan_etf_nav_daily"


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _has_table(PROFILE_TABLE):
        op.create_table(
            PROFILE_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=True),
            sa.Column("fund_short_name", sa.String(length=160), nullable=True),
            sa.Column("fund_name", sa.String(length=320), nullable=True),
            sa.Column("fund_name_en", sa.String(length=320), nullable=True),
            sa.Column("fund_type", sa.String(length=160), nullable=True),
            sa.Column("benchmark_name", sa.String(length=320), nullable=True),
            sa.Column("is_customized_index", sa.Boolean(), nullable=True),
            sa.Column("investment_scope", sa.Text(), nullable=True),
            sa.Column("has_performance_benchmark", sa.Boolean(), nullable=True),
            sa.Column("performance_benchmark_name", sa.String(length=320), nullable=True),
            sa.Column("has_foreign_components", sa.Boolean(), nullable=True),
            sa.Column("tax_id", sa.String(length=20), nullable=True),
            sa.Column("established_date", sa.Date(), nullable=True),
            sa.Column("listed_date", sa.Date(), nullable=True),
            sa.Column("fund_manager", sa.String(length=160), nullable=True),
            sa.Column("issued_units", sa.BigInteger(), nullable=True),
            sa.Column("custodian", sa.String(length=160), nullable=True),
            sa.Column("issuer_name", sa.String(length=240), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stock_id", name="uq_taiwan_etf_profile_stock_id"),
        )
        op.create_index("ix_taiwan_etf_profile_id", PROFILE_TABLE, ["id"])
        op.create_index("ix_taiwan_etf_profile_stock_id", PROFILE_TABLE, ["stock_id"])
        op.create_index("ix_taiwan_etf_profile_market", PROFILE_TABLE, ["market"])
        op.create_index("ix_taiwan_etf_profile_report_date", PROFILE_TABLE, ["report_date"])
        op.create_index("ix_taiwan_etf_profile_fund_type", PROFILE_TABLE, ["fund_type"])
        op.create_index("ix_taiwan_etf_profile_source", PROFILE_TABLE, ["source"])

    if not _has_table(NAV_TABLE):
        op.create_table(
            NAV_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("nav_date", sa.Date(), nullable=False),
            sa.Column("issuer_name", sa.String(length=240), nullable=True),
            sa.Column("fund_name", sa.String(length=320), nullable=True),
            sa.Column("nav", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("previous_nav", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("nav_change", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("nav_change_pct", sa.Numeric(precision=14, scale=6), nullable=True),
            sa.Column("close_price", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("premium_discount_pct", sa.Numeric(precision=14, scale=6), nullable=True),
            sa.Column("benchmark_name", sa.String(length=320), nullable=True),
            sa.Column("benchmark_date", sa.Date(), nullable=True),
            sa.Column("benchmark_close", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("benchmark_previous_close", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("benchmark_change", sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column("benchmark_change_pct", sa.Numeric(precision=14, scale=6), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "stock_id",
                "nav_date",
                name="uq_taiwan_etf_nav_daily_stock_date",
            ),
        )
        op.create_index("ix_taiwan_etf_nav_daily_id", NAV_TABLE, ["id"])
        op.create_index("ix_taiwan_etf_nav_daily_stock_id", NAV_TABLE, ["stock_id"])
        op.create_index("ix_taiwan_etf_nav_daily_nav_date", NAV_TABLE, ["nav_date"])
        op.create_index(
            "ix_taiwan_etf_nav_daily_stock_date",
            NAV_TABLE,
            ["stock_id", "nav_date"],
        )
        op.create_index("ix_taiwan_etf_nav_daily_source", NAV_TABLE, ["source"])

def downgrade() -> None:
    if _has_table(NAV_TABLE):
        op.drop_table(NAV_TABLE)
    if _has_table(PROFILE_TABLE):
        op.drop_table(PROFILE_TABLE)
