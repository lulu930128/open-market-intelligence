"""Repair Radar v2 point-in-time, universe, and event contracts.

Revision ID: 20260729_0043
Revises: 20260729_0042
Create Date: 2026-07-29 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_0043"
down_revision: str | Sequence[str] | None = "20260729_0042"
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


def _add_index(table_name: str, column_name: str) -> None:
    index_name = f"ix_{table_name}_{column_name}"
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, [column_name], unique=False)


def _add_point_in_time_columns() -> None:
    if not _has_column("radar_feature_snapshot", "source_available_at"):
        op.add_column(
            "radar_feature_snapshot",
            sa.Column("source_available_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE radar_feature_snapshot "
                "SET source_available_at = available_at "
                "WHERE source_available_at IS NULL"
            )
        )
        with op.batch_alter_table("radar_feature_snapshot") as batch_op:
            batch_op.alter_column(
                "source_available_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    if not _has_column("radar_feature_snapshot", "observed_at"):
        op.add_column(
            "radar_feature_snapshot",
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE radar_feature_snapshot "
                "SET observed_at = created_at "
                "WHERE observed_at IS NULL"
            )
        )
        with op.batch_alter_table("radar_feature_snapshot") as batch_op:
            batch_op.alter_column(
                "observed_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    if not _has_column("radar_rule_evaluation", "decision_at"):
        op.add_column(
            "radar_rule_evaluation",
            sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE radar_rule_evaluation "
                "SET decision_at = evaluated_at "
                "WHERE decision_at IS NULL"
            )
        )
        with op.batch_alter_table("radar_rule_evaluation") as batch_op:
            batch_op.alter_column(
                "decision_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    if not _has_column("radar_signal_event", "last_observed_trade_date"):
        op.add_column(
            "radar_signal_event",
            sa.Column("last_observed_trade_date", sa.Date(), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE radar_signal_event "
                "SET last_observed_trade_date = last_active_trade_date "
                "WHERE last_observed_trade_date IS NULL"
            )
        )
        with op.batch_alter_table("radar_signal_event") as batch_op:
            batch_op.alter_column(
                "last_observed_trade_date",
                existing_type=sa.Date(),
                nullable=False,
            )
    if not _has_column("radar_signal_event", "observation_status"):
        op.add_column(
            "radar_signal_event",
            sa.Column(
                "observation_status",
                sa.String(length=30),
                nullable=False,
                server_default="observed_active",
            ),
        )
    if not _has_column("radar_outcome_path", "reference_direction"):
        op.add_column(
            "radar_outcome_path",
            sa.Column(
                "reference_direction",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        op.execute(
            sa.text(
                "UPDATE radar_outcome_path "
                "SET reference_direction = direction"
            )
        )

    for table_name, columns in {
        "radar_feature_snapshot": ("source_available_at", "observed_at"),
        "radar_rule_evaluation": ("decision_at",),
        "radar_signal_event": (
            "last_observed_trade_date",
            "observation_status",
        ),
        "radar_outcome_path": ("reference_direction",),
    }.items():
        for column_name in columns:
            _add_index(table_name, column_name)


def _create_universe_observation() -> None:
    if _has_table("radar_universe_observation"):
        return
    op.create_table(
        "radar_universe_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=120), nullable=True),
        sa.Column("observation_status", sa.String(length=30), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=True),
        sa.Column("source_rank", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("universe_scope", sa.String(length=50), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("rule_config_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["watchlist_group.id"]),
        sa.ForeignKeyConstraint(["evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id",
            "mode",
            "snapshot_date",
            "stock_id",
            "rule_version",
            "rule_config_hash",
            name="uq_radar_universe_observation_scope",
        ),
    )
    for column_name in (
        "id",
        "group_id",
        "mode",
        "snapshot_date",
        "market",
        "stock_id",
        "observation_status",
        "selected",
        "evaluation_id",
        "universe_scope",
        "rule_version",
        "rule_config_hash",
        "observed_at",
    ):
        _add_index("radar_universe_observation", column_name)


def _create_evaluation_event_link() -> None:
    if _has_table("radar_evaluation_event_link"):
        return
    op.create_table(
        "radar_evaluation_event_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("signal_event_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=30), nullable=False),
        sa.Column("contribution_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.ForeignKeyConstraint(["signal_event_id"], ["radar_signal_event.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "signal_event_id",
            name="uq_radar_evaluation_event_link",
        ),
    )
    for column_name in ("id", "evaluation_id", "signal_event_id", "relation"):
        _add_index("radar_evaluation_event_link", column_name)


def _create_outcome_event_link() -> None:
    if _has_table("radar_outcome_event_link"):
        return
    op.create_table(
        "radar_outcome_event_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outcome_path_id", sa.Integer(), nullable=False),
        sa.Column("signal_event_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outcome_path_id"], ["radar_outcome_path.id"]),
        sa.ForeignKeyConstraint(["signal_event_id"], ["radar_signal_event.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outcome_path_id",
            "signal_event_id",
            name="uq_radar_outcome_event_link",
        ),
    )
    for column_name in ("id", "outcome_path_id", "signal_event_id"):
        _add_index("radar_outcome_event_link", column_name)


def upgrade() -> None:
    _add_point_in_time_columns()
    _create_universe_observation()
    _create_evaluation_event_link()
    _create_outcome_event_link()


def downgrade() -> None:
    for table_name in (
        "radar_outcome_event_link",
        "radar_evaluation_event_link",
        "radar_universe_observation",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)

    for table_name, column_name in (
        ("radar_outcome_path", "reference_direction"),
        ("radar_signal_event", "observation_status"),
        ("radar_signal_event", "last_observed_trade_date"),
        ("radar_rule_evaluation", "decision_at"),
        ("radar_feature_snapshot", "observed_at"),
        ("radar_feature_snapshot", "source_available_at"),
    ):
        if _has_column(table_name, column_name):
            index_name = f"ix_{table_name}_{column_name}"
            if _has_index(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_column(column_name)
