"""Add AI memory, report, and tool-call tables.

Revision ID: 20260527_0004
Revises: 20260523_0003
Create Date: 2026-05-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260527_0004"
down_revision: str | Sequence[str] | None = "20260523_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _drop_indexes(table_name: str, index_names: tuple[str, ...]) -> None:
    for index_name in index_names:
        if _has_index(table_name, index_name):
            op.drop_index(op.f(index_name), table_name=table_name)


def upgrade() -> None:
    if not _has_table("ai_memory"):
        op.create_table(
            "ai_memory",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("memory_type", sa.String(length=50), nullable=False),
            sa.Column("scope_type", sa.String(length=50), nullable=False),
            sa.Column("scope_id", sa.String(length=120), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags_json", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("importance", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("created_by", sa.String(length=120), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ai_memory_id"), "ai_memory", ["id"], unique=False)
        op.create_index(op.f("ix_ai_memory_memory_type"), "ai_memory", ["memory_type"], unique=False)
        op.create_index(op.f("ix_ai_memory_scope_id"), "ai_memory", ["scope_id"], unique=False)
        op.create_index(op.f("ix_ai_memory_scope_type"), "ai_memory", ["scope_type"], unique=False)
        op.create_index(op.f("ix_ai_memory_status"), "ai_memory", ["status"], unique=False)
        op.create_index(op.f("ix_ai_memory_title"), "ai_memory", ["title"], unique=False)
        op.create_index(op.f("ix_ai_memory_importance"), "ai_memory", ["importance"], unique=False)

    if not _has_table("ai_report"):
        op.create_table(
            "ai_report",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("report_type", sa.String(length=80), nullable=False),
            sa.Column("scope_type", sa.String(length=50), nullable=False),
            sa.Column("scope_id", sa.String(length=120), nullable=True),
            sa.Column("strategy_profile", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=True),
            sa.Column("as_of", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("model_name", sa.String(length=120), nullable=True),
            sa.Column("job_run_id", sa.Integer(), nullable=True),
            sa.Column("summary_json", sa.Text(), nullable=True),
            sa.Column("prompt_json", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("missing_json", sa.Text(), nullable=True),
            sa.Column("warnings_json", sa.Text(), nullable=True),
            sa.Column("source_refs_json", sa.Text(), nullable=True),
            sa.Column("memory_refs_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_run_id"], ["job_run.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ai_report_as_of"), "ai_report", ["as_of"], unique=False)
        op.create_index(op.f("ix_ai_report_id"), "ai_report", ["id"], unique=False)
        op.create_index(op.f("ix_ai_report_job_run_id"), "ai_report", ["job_run_id"], unique=False)
        op.create_index(op.f("ix_ai_report_report_type"), "ai_report", ["report_type"], unique=False)
        op.create_index(op.f("ix_ai_report_scope_id"), "ai_report", ["scope_id"], unique=False)
        op.create_index(op.f("ix_ai_report_scope_type"), "ai_report", ["scope_type"], unique=False)
        op.create_index(op.f("ix_ai_report_status"), "ai_report", ["status"], unique=False)
        op.create_index(op.f("ix_ai_report_strategy_profile"), "ai_report", ["strategy_profile"], unique=False)

    if not _has_table("ai_tool_call"):
        op.create_table(
            "ai_tool_call",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("report_id", sa.Integer(), nullable=True),
            sa.Column("tool_name", sa.String(length=140), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("arguments_json", sa.Text(), nullable=True),
            sa.Column("result_summary_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["report_id"], ["ai_report.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ai_tool_call_id"), "ai_tool_call", ["id"], unique=False)
        op.create_index(op.f("ix_ai_tool_call_report_id"), "ai_tool_call", ["report_id"], unique=False)
        op.create_index(op.f("ix_ai_tool_call_status"), "ai_tool_call", ["status"], unique=False)
        op.create_index(op.f("ix_ai_tool_call_tool_name"), "ai_tool_call", ["tool_name"], unique=False)


def downgrade() -> None:
    if _has_table("ai_tool_call"):
        _drop_indexes(
            "ai_tool_call",
            (
                "ix_ai_tool_call_tool_name",
                "ix_ai_tool_call_status",
                "ix_ai_tool_call_report_id",
                "ix_ai_tool_call_id",
            ),
        )
        op.drop_table("ai_tool_call")

    if _has_table("ai_report"):
        _drop_indexes(
            "ai_report",
            (
                "ix_ai_report_strategy_profile",
                "ix_ai_report_status",
                "ix_ai_report_scope_type",
                "ix_ai_report_scope_id",
                "ix_ai_report_report_type",
                "ix_ai_report_job_run_id",
                "ix_ai_report_id",
                "ix_ai_report_as_of",
            ),
        )
        op.drop_table("ai_report")

    if _has_table("ai_memory"):
        _drop_indexes(
            "ai_memory",
            (
                "ix_ai_memory_importance",
                "ix_ai_memory_title",
                "ix_ai_memory_status",
                "ix_ai_memory_scope_type",
                "ix_ai_memory_scope_id",
                "ix_ai_memory_memory_type",
                "ix_ai_memory_id",
            ),
        )
        op.drop_table("ai_memory")
