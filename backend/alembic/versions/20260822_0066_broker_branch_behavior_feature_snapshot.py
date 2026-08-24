"""Add broker-branch shadow behavior feature snapshots.

Revision ID: 20260822_0066
Revises: 20260822_0065
Create Date: 2026-08-22 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260822_0066"
down_revision: str | Sequence[str] | None = "20260822_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "broker_branch_behavior_feature_snapshot"
INDEX_COLUMNS = {
    "ix_broker_branch_behavior_feature_snapshot_id": ["id"],
    "ix_broker_branch_behavior_feature_snapshot_source_id": ["source_id"],
    "ix_broker_branch_behavior_feature_snapshot_branch_identity_key": [
        "branch_identity_key"
    ],
    "ix_broker_branch_behavior_feature_snapshot_as_of_trade_date": [
        "as_of_trade_date"
    ],
    "ix_broker_branch_behavior_feature_snapshot_methodology_version": [
        "methodology_version"
    ],
    "ix_broker_branch_behavior_feature_snapshot_history_status": [
        "history_status"
    ],
    "ix_broker_branch_behavior_feature_snapshot_derived_as_of": [
        "derived_as_of"
    ],
    "ix_broker_branch_behavior_feature_latest": [
        "source_id",
        "as_of_trade_date",
        "history_status",
    ],
}


REQUIRED_COLUMNS = {
    "id",
    "source_id",
    "branch_identity_key",
    "branch_code",
    "scope_type",
    "scope_id",
    "as_of_trade_date",
    "lookback_sessions",
    "methodology_version",
    "observation_count",
    "eligible_initial_count",
    "reobserved_count",
    "opposite_observed_count",
    "same_direction_observed_count",
    "censored_count",
    "session_count",
    "stock_count",
    "gross_visible_lots",
    "net_visible_lots",
    "reappearance_rate",
    "reappearance_interval_low",
    "reappearance_interval_high",
    "reverse_given_reappearance_rate",
    "reverse_interval_low",
    "reverse_interval_high",
    "same_direction_given_reappearance_rate",
    "same_direction_interval_low",
    "same_direction_interval_high",
    "censored_rate",
    "censored_interval_low",
    "censored_interval_high",
    "gross_netting_ratio",
    "observed_sequence_persistence",
    "max_stock_observation_share",
    "candidate_session_count",
    "high_coverage_session_count",
    "universe_count",
    "min_session_coverage_ratio",
    "coverage_status",
    "history_status",
    "calibration_status",
    "decision_usable",
    "source_as_of",
    "price_source_as_of",
    "derived_as_of",
    "computed_at",
    "input_fingerprint",
    "warnings_json",
    "created_at",
    "updated_at",
}


def _ensure_existing_table_contract() -> None:
    inspector = sa.inspect(op.get_bind())
    actual_columns = {
        item["name"] for item in inspector.get_columns(TABLE_NAME)
    }
    missing_columns = sorted(REQUIRED_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(
            "Existing broker-branch behavior feature table is incomplete; "
            "missing columns: " + ", ".join(missing_columns)
        )

    existing_indexes = {
        item["name"] for item in inspector.get_indexes(TABLE_NAME)
    }
    for index_name, columns in INDEX_COLUMNS.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, TABLE_NAME, columns, unique=False)


def _count_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def _rate_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Float(), nullable=True)


def upgrade() -> None:
    if TABLE_NAME in sa.inspect(op.get_bind()).get_table_names():
        _ensure_existing_table_contract()
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("branch_identity_key", sa.String(length=96), nullable=False),
        sa.Column("branch_code", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("as_of_trade_date", sa.Date(), nullable=False),
        sa.Column("lookback_sessions", sa.Integer(), nullable=False),
        sa.Column("methodology_version", sa.String(length=80), nullable=False),
        _count_column("observation_count"),
        _count_column("eligible_initial_count"),
        _count_column("reobserved_count"),
        _count_column("opposite_observed_count"),
        _count_column("same_direction_observed_count"),
        _count_column("censored_count"),
        _count_column("session_count"),
        _count_column("stock_count"),
        sa.Column(
            "gross_visible_lots",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "net_visible_lots",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        _rate_column("reappearance_rate"),
        _rate_column("reappearance_interval_low"),
        _rate_column("reappearance_interval_high"),
        _rate_column("reverse_given_reappearance_rate"),
        _rate_column("reverse_interval_low"),
        _rate_column("reverse_interval_high"),
        _rate_column("same_direction_given_reappearance_rate"),
        _rate_column("same_direction_interval_low"),
        _rate_column("same_direction_interval_high"),
        _rate_column("censored_rate"),
        _rate_column("censored_interval_low"),
        _rate_column("censored_interval_high"),
        _rate_column("gross_netting_ratio"),
        _rate_column("observed_sequence_persistence"),
        _rate_column("max_stock_observation_share"),
        _count_column("candidate_session_count"),
        _count_column("high_coverage_session_count"),
        _count_column("universe_count"),
        _rate_column("min_session_coverage_ratio"),
        sa.Column("coverage_status", sa.String(length=40), nullable=False),
        sa.Column("history_status", sa.String(length=40), nullable=False),
        sa.Column("calibration_status", sa.String(length=40), nullable=False),
        sa.Column(
            "decision_usable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_as_of", sa.Date(), nullable=True),
        sa.Column("price_source_as_of", sa.Date(), nullable=True),
        sa.Column("derived_as_of", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "warnings_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "observation_count >= 0 AND eligible_initial_count >= 0 "
            "AND reobserved_count >= 0 AND opposite_observed_count >= 0 "
            "AND same_direction_observed_count >= 0 AND censored_count >= 0 "
            "AND session_count >= 0 AND stock_count >= 0",
            name="ck_broker_branch_behavior_counts_non_negative",
        ),
        sa.CheckConstraint(
            "reobserved_count + censored_count = eligible_initial_count",
            name="ck_broker_branch_behavior_eligible_partition",
        ),
        sa.CheckConstraint(
            "opposite_observed_count + same_direction_observed_count = "
            "reobserved_count",
            name="ck_broker_branch_behavior_reobserved_partition",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "branch_identity_key",
            "scope_type",
            "scope_id",
            "as_of_trade_date",
            "lookback_sessions",
            "methodology_version",
            name="uq_broker_branch_behavior_feature_identity",
        ),
    )
    _ensure_existing_table_contract()


def downgrade() -> None:
    if TABLE_NAME in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE_NAME)
