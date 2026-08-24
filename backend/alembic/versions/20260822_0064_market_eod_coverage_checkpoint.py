"""Add durable full-market EOD coverage checkpoints.

Revision ID: 20260822_0064
Revises: 20260819_0063
Create Date: 2026-08-22 10:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260822_0064"
down_revision: str | Sequence[str] | None = "20260819_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "market_dataset_coverage_checkpoint"
INDEX_COLUMNS = {
    "ix_market_dataset_coverage_checkpoint_id": ["id"],
    "ix_market_dataset_coverage_checkpoint_dataset_id": ["dataset_id"],
    "ix_market_dataset_coverage_checkpoint_market": ["market"],
    "ix_market_dataset_coverage_checkpoint_scope_kind": ["scope_kind"],
    "ix_market_dataset_coverage_checkpoint_scope_key": ["scope_key"],
    "ix_market_dataset_coverage_checkpoint_expected_trade_date": ["expected_trade_date"],
    "ix_market_dataset_coverage_checkpoint_latest_data_date": ["latest_data_date"],
    "ix_market_dataset_coverage_checkpoint_universe_hash": ["universe_hash"],
    "ix_market_dataset_coverage_checkpoint_status": ["status"],
    "ix_market_dataset_coverage_checkpoint_repair_status": ["repair_status"],
    "ix_market_dataset_coverage_checkpoint_repair_provider": ["repair_provider"],
    "ix_market_dataset_coverage_checkpoint_last_job_id": ["last_job_id"],
    "ix_market_dataset_coverage_checkpoint_next_retry_at": ["next_retry_at"],
    "ix_market_dataset_coverage_checkpoint_checked_at": ["checked_at"],
    "ix_market_dataset_coverage_latest": [
        "market",
        "dataset_id",
        "scope_key",
        "expected_trade_date",
        "checked_at",
    ],
}


def _ensure_existing_table_contract() -> None:
    inspector = sa.inspect(op.get_bind())
    required_columns = {
        "id",
        "checkpoint_version",
        "dataset_id",
        "market",
        "scope_kind",
        "scope_key",
        "expected_trade_date",
        "latest_data_date",
        "universe_source",
        "universe_hash",
        "universe_count",
        "current_count",
        "partial_count",
        "stale_count",
        "missing_count",
        "status",
        "repair_status",
        "repair_provider",
        "cursor_symbol",
        "attempted_count",
        "succeeded_count",
        "failed_count",
        "consecutive_error_count",
        "last_job_id",
        "last_attempt_at",
        "last_success_at",
        "next_retry_at",
        "detail_json",
        "checked_at",
        "created_at",
        "updated_at",
    }
    actual_columns = {
        item["name"] for item in inspector.get_columns(TABLE_NAME)
    }
    missing_columns = sorted(required_columns - actual_columns)
    if missing_columns:
        raise RuntimeError(
            "Existing market EOD coverage table is incomplete; missing columns: "
            + ", ".join(missing_columns)
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
        sa.Column(
            "checkpoint_version",
            sa.String(length=64),
            nullable=False,
            server_default="omi.market.eod_coverage.v1",
        ),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("scope_kind", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("expected_trade_date", sa.Date(), nullable=False),
        sa.Column("latest_data_date", sa.Date(), nullable=True),
        sa.Column("universe_source", sa.String(length=128), nullable=False),
        sa.Column("universe_hash", sa.String(length=64), nullable=False),
        sa.Column("universe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("repair_status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("repair_provider", sa.String(length=80), nullable=True),
        sa.Column("cursor_symbol", sa.String(length=64), nullable=True),
        sa.Column("attempted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_job_id", sa.Integer(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "universe_count >= 0 AND current_count >= 0 AND partial_count >= 0 "
            "AND stale_count >= 0 AND missing_count >= 0",
            name="ck_market_dataset_coverage_non_negative",
        ),
        sa.CheckConstraint(
            "current_count + partial_count + stale_count + missing_count = universe_count",
            name="ck_market_dataset_coverage_partition",
        ),
        sa.ForeignKeyConstraint(["last_job_id"], ["job_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "scope_key",
            "expected_trade_date",
            "universe_hash",
            name="uq_market_dataset_coverage_identity",
        ),
    )
    _ensure_existing_table_contract()


def downgrade() -> None:
    if TABLE_NAME in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE_NAME)
