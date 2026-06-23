"""Add mail dispatch v1 tables.

Revision ID: 20260622_0022
Revises: 20260621_0021
Create Date: 2026-06-22 20:58:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260622_0022"
down_revision: str | Sequence[str] | None = "20260621_0021"
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


def upgrade() -> None:
    if not _has_table("dispatch_recipient_group"):
        op.create_table(
            "dispatch_recipient_group",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("emails_json", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_dispatch_recipient_group_name"),
        )
        op.create_index(op.f("ix_dispatch_recipient_group_enabled"), "dispatch_recipient_group", ["enabled"], unique=False)
        op.create_index(op.f("ix_dispatch_recipient_group_id"), "dispatch_recipient_group", ["id"], unique=False)
        op.create_index(op.f("ix_dispatch_recipient_group_name"), "dispatch_recipient_group", ["name"], unique=False)

    if not _has_table("dispatch_delivery"):
        op.create_table(
            "dispatch_delivery",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_run_id", sa.Integer(), nullable=True),
            sa.Column("recipient_group_id", sa.Integer(), nullable=True),
            sa.Column("template_key", sa.String(length=80), nullable=False),
            sa.Column("scope_type", sa.String(length=50), nullable=False),
            sa.Column("scope_id", sa.String(length=120), nullable=True),
            sa.Column("subject", sa.String(length=240), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("recipient_count", sa.Integer(), nullable=False),
            sa.Column("recipients_json", sa.Text(), nullable=True),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("preview_json", sa.Text(), nullable=True),
            sa.Column("request_json", sa.Text(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_run_id"], ["job_run.id"]),
            sa.ForeignKeyConstraint(["recipient_group_id"], ["dispatch_recipient_group.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_dispatch_delivery_id"), "dispatch_delivery", ["id"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_job_run_id"), "dispatch_delivery", ["job_run_id"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_recipient_group_id"), "dispatch_delivery", ["recipient_group_id"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_scope_id"), "dispatch_delivery", ["scope_id"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_scope_type"), "dispatch_delivery", ["scope_type"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_status"), "dispatch_delivery", ["status"], unique=False)
        op.create_index(op.f("ix_dispatch_delivery_template_key"), "dispatch_delivery", ["template_key"], unique=False)


def downgrade() -> None:
    if _has_table("dispatch_delivery"):
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_template_key")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_status")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_scope_type")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_scope_id")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_recipient_group_id")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_job_run_id")
        _drop_index("dispatch_delivery", "ix_dispatch_delivery_id")
        op.drop_table("dispatch_delivery")

    if _has_table("dispatch_recipient_group"):
        _drop_index("dispatch_recipient_group", "ix_dispatch_recipient_group_name")
        _drop_index("dispatch_recipient_group", "ix_dispatch_recipient_group_id")
        _drop_index("dispatch_recipient_group", "ix_dispatch_recipient_group_enabled")
        op.drop_table("dispatch_recipient_group")
