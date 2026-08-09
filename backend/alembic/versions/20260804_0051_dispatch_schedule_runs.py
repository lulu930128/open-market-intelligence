"""Add reliable dispatch schedule runs.

Revision ID: 20260804_0051
Revises: 20260803_0050
Create Date: 2026-08-04 20:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_0051"
down_revision: str | Sequence[str] | None = "20260803_0050"
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
        str(column["name"]) for column in _inspector().get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {
        str(index["name"]) for index in _inspector().get_indexes(table_name)
    }


def _add_columns(
    table_name: str,
    columns: tuple[tuple[str, sa.Column], ...],
) -> None:
    if not _has_table(table_name):
        return
    for name, column in columns:
        if not _has_column(table_name, name):
            op.add_column(table_name, column)


def _add_index(
    table_name: str,
    column_name: str,
    *,
    unique: bool = False,
) -> None:
    index_name = f"ix_{table_name}_{column_name}"
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(
            index_name,
            table_name,
            [column_name],
            unique=unique,
        )


def upgrade() -> None:
    delivery_table = "dispatch_delivery"
    _add_columns(
        delivery_table,
        (
            (
                "message_id",
                sa.Column("message_id", sa.String(length=240), nullable=True),
            ),
        ),
    )
    _add_index(delivery_table, "message_id", unique=True)

    schedule_table = "dispatch_schedule"
    _add_columns(
        schedule_table,
        (
            ("next_run_at", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True)),
            (
                "calendar_mode",
                sa.Column(
                    "calendar_mode",
                    sa.String(length=30),
                    nullable=False,
                    server_default="weekdays",
                ),
            ),
            (
                "catchup_mode",
                sa.Column(
                    "catchup_mode",
                    sa.String(length=30),
                    nullable=False,
                    server_default="latest_only",
                ),
            ),
            (
                "misfire_policy",
                sa.Column(
                    "misfire_policy",
                    sa.String(length=20),
                    nullable=False,
                    server_default="catch_up",
                ),
            ),
            (
                "misfire_grace_minutes",
                sa.Column(
                    "misfire_grace_minutes",
                    sa.Integer(),
                    nullable=False,
                    server_default="15",
                ),
            ),
            (
                "max_retries",
                sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
            ),
            (
                "retry_interval_seconds",
                sa.Column(
                    "retry_interval_seconds",
                    sa.Integer(),
                    nullable=False,
                    server_default="300",
                ),
            ),
            (
                "readiness_profile",
                sa.Column(
                    "readiness_profile",
                    sa.String(length=40),
                    nullable=False,
                    server_default="generic",
                ),
            ),
            (
                "readiness_policy",
                sa.Column(
                    "readiness_policy",
                    sa.String(length=30),
                    nullable=False,
                    server_default="immediate",
                ),
            ),
            (
                "readiness_deadline_minutes",
                sa.Column(
                    "readiness_deadline_minutes",
                    sa.Integer(),
                    nullable=False,
                    server_default="60",
                ),
            ),
            (
                "readiness_retry_interval_seconds",
                sa.Column(
                    "readiness_retry_interval_seconds",
                    sa.Integer(),
                    nullable=False,
                    server_default="300",
                ),
            ),
            ("last_queued_at", sa.Column("last_queued_at", sa.DateTime(timezone=True), nullable=True)),
            ("last_sent_at", sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True)),
            ("last_skipped_at", sa.Column("last_skipped_at", sa.DateTime(timezone=True), nullable=True)),
            (
                "last_status",
                sa.Column(
                    "last_status",
                    sa.String(length=30),
                    nullable=False,
                    server_default="never_run",
                ),
            ),
            ("archived_at", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)),
        ),
    )
    for column_name in (
        "next_run_at",
        "calendar_mode",
        "catchup_mode",
        "misfire_policy",
        "readiness_profile",
        "readiness_policy",
        "last_status",
        "archived_at",
    ):
        _add_index(schedule_table, column_name)

    run_table = "dispatch_schedule_run"
    if not _has_table(run_table):
        op.create_table(
            run_table,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_token", sa.String(length=36), nullable=False),
            sa.Column("schedule_id", sa.Integer(), nullable=False),
            sa.Column("retry_of_run_id", sa.Integer(), nullable=True),
            sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default="scheduled"),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scheduled_slot_key", sa.String(length=80), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="claimed"),
            sa.Column("schedule_snapshot_json", sa.Text(), nullable=False),
            sa.Column("readiness_json", sa.Text(), nullable=True),
            sa.Column("readiness_check_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("delivery_attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_delivery_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("delivery_id", sa.Integer(), nullable=True),
            sa.Column("job_run_id", sa.Integer(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sending_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["delivery_id"], ["dispatch_delivery.id"]),
            sa.ForeignKeyConstraint(["job_run_id"], ["job_run.id"]),
            sa.ForeignKeyConstraint(["retry_of_run_id"], ["dispatch_schedule_run.id"]),
            sa.ForeignKeyConstraint(["schedule_id"], ["dispatch_schedule.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("delivery_id", name="uq_dispatch_schedule_run_delivery_id"),
            sa.UniqueConstraint("run_token", name="uq_dispatch_schedule_run_run_token"),
            sa.UniqueConstraint(
                "schedule_id",
                "scheduled_slot_key",
                name="uq_dispatch_schedule_run_scheduled_slot",
            ),
        )
        for column_name in (
            "id",
            "run_token",
            "schedule_id",
            "retry_of_run_id",
            "trigger_type",
            "scheduled_for",
            "scheduled_slot_key",
            "status",
            "next_action_at",
            "retryable",
            "error_code",
            "delivery_id",
            "job_run_id",
        ):
            op.create_index(
                f"ix_{run_table}_{column_name}",
                run_table,
                [column_name],
                unique=False,
            )
        op.create_index(
            "ix_dispatch_schedule_run_action_due",
            run_table,
            ["status", "next_action_at"],
            unique=False,
        )


def downgrade() -> None:
    run_table = "dispatch_schedule_run"
    if _has_table(run_table):
        for index_name in (
            "ix_dispatch_schedule_run_action_due",
            "ix_dispatch_schedule_run_job_run_id",
            "ix_dispatch_schedule_run_delivery_id",
            "ix_dispatch_schedule_run_error_code",
            "ix_dispatch_schedule_run_retryable",
            "ix_dispatch_schedule_run_next_action_at",
            "ix_dispatch_schedule_run_status",
            "ix_dispatch_schedule_run_scheduled_slot_key",
            "ix_dispatch_schedule_run_scheduled_for",
            "ix_dispatch_schedule_run_trigger_type",
            "ix_dispatch_schedule_run_retry_of_run_id",
            "ix_dispatch_schedule_run_schedule_id",
            "ix_dispatch_schedule_run_run_token",
            "ix_dispatch_schedule_run_id",
        ):
            if _has_index(run_table, index_name):
                op.drop_index(index_name, table_name=run_table)
        op.drop_table(run_table)

    schedule_table = "dispatch_schedule"
    if _has_table(schedule_table):
        for column_name in (
            "archived_at",
            "last_status",
            "readiness_policy",
            "readiness_profile",
            "misfire_policy",
            "catchup_mode",
            "calendar_mode",
            "next_run_at",
        ):
            index_name = f"ix_{schedule_table}_{column_name}"
            if _has_index(schedule_table, index_name):
                op.drop_index(index_name, table_name=schedule_table)
        for column_name in (
            "archived_at",
            "last_status",
            "last_skipped_at",
            "last_sent_at",
            "last_queued_at",
            "readiness_retry_interval_seconds",
            "readiness_deadline_minutes",
            "readiness_policy",
            "readiness_profile",
            "retry_interval_seconds",
            "max_retries",
            "misfire_grace_minutes",
            "misfire_policy",
            "catchup_mode",
            "calendar_mode",
            "next_run_at",
        ):
            if _has_column(schedule_table, column_name):
                op.drop_column(schedule_table, column_name)

    delivery_table = "dispatch_delivery"
    if _has_table(delivery_table):
        index_name = "ix_dispatch_delivery_message_id"
        if _has_index(delivery_table, index_name):
            op.drop_index(index_name, table_name=delivery_table)
        if _has_column(delivery_table, "message_id"):
            op.drop_column(delivery_table, "message_id")
