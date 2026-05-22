"""Add tracked job runs.

Revision ID: 20260523_0002
Revises: 20260523_0001
Create Date: 2026-05-23 01:28:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260523_0002"
down_revision: str | Sequence[str] | None = "20260523_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("target", sa.String(length=160), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_run_id"), "job_run", ["id"], unique=False)
    op.create_index(op.f("ix_job_run_job_type"), "job_run", ["job_type"], unique=False)
    op.create_index(op.f("ix_job_run_status"), "job_run", ["status"], unique=False)
    op.create_index(op.f("ix_job_run_target"), "job_run", ["target"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_run_target"), table_name="job_run")
    op.drop_index(op.f("ix_job_run_status"), table_name="job_run")
    op.drop_index(op.f("ix_job_run_job_type"), table_name="job_run")
    op.drop_index(op.f("ix_job_run_id"), table_name="job_run")
    op.drop_table("job_run")
