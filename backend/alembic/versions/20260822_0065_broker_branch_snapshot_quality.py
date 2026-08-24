"""Add broker-branch snapshot quality selected state.

Revision ID: 20260822_0065
Revises: 20260822_0064
Create Date: 2026-08-22 14:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260822_0065"
down_revision: str | Sequence[str] | None = "20260822_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "broker_branch_snapshot_quality"
INDEX_COLUMNS = {
    "ix_broker_branch_snapshot_quality_id": ["id"],
    "ix_broker_branch_snapshot_quality_source_id": ["source_id"],
    "ix_broker_branch_snapshot_quality_raw_result_id": ["raw_result_id"],
    "ix_broker_branch_snapshot_quality_stock_id": ["stock_id"],
    "ix_broker_branch_snapshot_quality_expected_trade_date": [
        "expected_trade_date"
    ],
    "ix_broker_branch_snapshot_quality_provider_trade_date": [
        "provider_trade_date"
    ],
    "ix_broker_branch_snapshot_quality_fetched_at": ["fetched_at"],
    "ix_broker_branch_snapshot_quality_coverage_mode": ["coverage_mode"],
    "ix_broker_branch_snapshot_quality_absence_semantics": [
        "absence_semantics"
    ],
    "ix_broker_branch_snapshot_quality_coverage_status": ["coverage_status"],
    "ix_broker_branch_snapshot_quality_fetch_status": ["fetch_status"],
    "ix_broker_branch_snapshot_quality_source_contract_version": [
        "source_contract_version"
    ],
    "ix_broker_branch_snapshot_quality_date_status": [
        "expected_trade_date",
        "coverage_status",
    ],
}


def _ensure_existing_table_contract() -> None:
    inspector = sa.inspect(op.get_bind())
    required_columns = {
        "id",
        "source_id",
        "raw_result_id",
        "stock_id",
        "expected_trade_date",
        "provider_trade_date",
        "fetched_at",
        "coverage_mode",
        "buy_rank_limit",
        "sell_rank_limit",
        "observed_branch_count",
        "absence_semantics",
        "coverage_status",
        "fetch_status",
        "source_contract_version",
        "includes_block_trades",
        "warnings_json",
        "created_at",
        "updated_at",
    }
    actual_columns = {
        item["name"] for item in inspector.get_columns(TABLE_NAME)
    }
    missing_columns = sorted(required_columns - actual_columns)
    if missing_columns:
        raise RuntimeError(
            "Existing broker-branch snapshot quality table is incomplete; "
            "missing columns: " + ", ".join(missing_columns)
        )

    existing_indexes = {
        item["name"] for item in inspector.get_indexes(TABLE_NAME)
    }
    for index_name, columns in INDEX_COLUMNS.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, TABLE_NAME, columns, unique=False)


def upgrade() -> None:
    if TABLE_NAME in sa.inspect(op.get_bind()).get_table_names():
        _ensure_existing_table_contract()
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("expected_trade_date", sa.Date(), nullable=False),
        sa.Column("provider_trade_date", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_mode", sa.String(length=32), nullable=False),
        sa.Column("buy_rank_limit", sa.Integer(), nullable=True),
        sa.Column("sell_rank_limit", sa.Integer(), nullable=True),
        sa.Column(
            "observed_branch_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("absence_semantics", sa.String(length=40), nullable=False),
        sa.Column("coverage_status", sa.String(length=32), nullable=False),
        sa.Column("fetch_status", sa.String(length=40), nullable=False),
        sa.Column("source_contract_version", sa.String(length=80), nullable=False),
        sa.Column("includes_block_trades", sa.Boolean(), nullable=True),
        sa.Column(
            "warnings_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "observed_branch_count >= 0",
            name="ck_broker_branch_snapshot_quality_observed_non_negative",
        ),
        sa.CheckConstraint(
            "buy_rank_limit IS NULL OR buy_rank_limit > 0",
            name="ck_broker_branch_snapshot_quality_buy_rank_positive",
        ),
        sa.CheckConstraint(
            "sell_rank_limit IS NULL OR sell_rank_limit > 0",
            name="ck_broker_branch_snapshot_quality_sell_rank_positive",
        ),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "stock_id",
            "expected_trade_date",
            name="uq_broker_branch_snapshot_quality_selected_state",
        ),
    )
    _ensure_existing_table_contract()


def downgrade() -> None:
    if TABLE_NAME in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE_NAME)
