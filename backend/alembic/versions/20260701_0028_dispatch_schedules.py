"""add dispatch schedules

Revision ID: 20260701_0028
Revises: 20260630_0027
Create Date: 2026-07-01 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_0028"
down_revision: str | Sequence[str] | None = "20260630_0027"
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


def upgrade() -> None:
    if _has_table("dispatch_schedule"):
        return

    op.create_table(
        "dispatch_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_group_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("send_time", sa.String(length=5), nullable=False),
        sa.Column("day_of_week", sa.String(length=80), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("scope_id", sa.String(length=120), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("last_run_key", sa.String(length=120), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_delivery_id", sa.Integer(), nullable=True),
        sa.Column("last_job_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["last_delivery_id"], ["dispatch_delivery.id"]),
        sa.ForeignKeyConstraint(["last_job_run_id"], ["job_run.id"]),
        sa.ForeignKeyConstraint(["recipient_group_id"], ["dispatch_recipient_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes(
        "dispatch_schedule",
        [
            "id",
            "recipient_group_id",
            "name",
            "enabled",
            "send_time",
            "day_of_week",
            "timezone",
            "template_key",
            "scope_type",
            "scope_id",
            "last_run_key",
            "last_delivery_id",
            "last_job_run_id",
        ],
    )


def downgrade() -> None:
    if not _has_table("dispatch_schedule"):
        return

    for column in (
        "id",
        "recipient_group_id",
        "name",
        "enabled",
        "send_time",
        "day_of_week",
        "timezone",
        "template_key",
        "scope_type",
        "scope_id",
        "last_run_key",
        "last_delivery_id",
        "last_job_run_id",
    ):
        _drop_index("dispatch_schedule", f"ix_dispatch_schedule_{column}")
    op.drop_table("dispatch_schedule")
