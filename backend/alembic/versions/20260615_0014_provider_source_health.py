"""Add provider event and source health snapshot tables.

Revision ID: 20260615_0014
Revises: 20260613_0013
Create Date: 2026-06-15 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260615_0014"
down_revision: str | Sequence[str] | None = "20260613_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_provider_event_table() -> None:
    op.create_table(
        "provider_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("resource", sa.String(length=120), nullable=False),
        sa.Column("target", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("rate_limited", sa.Boolean(), nullable=False),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("job_run_id", sa.Integer(), nullable=True),
        sa.Column("fetch_log_id", sa.Integer(), nullable=True),
        sa.Column("raw_result_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fetch_log_id"], ["fetch_log.id"]),
        sa.ForeignKeyConstraint(["job_run_id"], ["job_run.id"]),
        sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in (
        "id",
        "market",
        "provider",
        "resource",
        "target",
        "status",
        "severity",
        "event_type",
        "event_time",
        "observed_at",
        "http_status_code",
        "rate_limited",
        "job_run_id",
        "fetch_log_id",
        "raw_result_id",
    ):
        op.create_index(
            op.f(f"ix_provider_event_{column}"),
            "provider_event",
            [column],
            unique=False,
        )


def _create_source_health_snapshot_table() -> None:
    op.create_table(
        "source_health_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("resource", sa.String(length=120), nullable=False),
        sa.Column("target", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("data_quality", sa.String(length=60), nullable=False),
        sa.Column("latest_data_date", sa.Date(), nullable=True),
        sa.Column("latest_data_key", sa.String(length=120), nullable=True),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_data_date", sa.Date(), nullable=True),
        sa.Column("freshness_lag_days", sa.Integer(), nullable=True),
        sa.Column("release_status", sa.String(length=60), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("latest_event_id", sa.Integer(), nullable=True),
        sa.Column("latest_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_status", sa.String(length=40), nullable=True),
        sa.Column("latest_event_severity", sa.String(length=30), nullable=True),
        sa.Column("latest_event_message", sa.Text(), nullable=True),
        sa.Column("recent_event_count", sa.Integer(), nullable=False),
        sa.Column("recent_error_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_error_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["latest_event_id"], ["provider_event.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "resource",
            "target",
            "provider",
            name="uq_source_health_market_resource_target_provider",
        ),
    )

    for column in (
        "id",
        "market",
        "resource",
        "target",
        "provider",
        "status",
        "ok",
        "required",
        "data_quality",
        "latest_data_date",
        "latest_data_key",
        "latest_observed_at",
        "expected_data_date",
        "release_status",
        "latest_event_id",
        "latest_event_at",
        "latest_event_status",
        "latest_event_severity",
        "checked_at",
    ):
        op.create_index(
            op.f(f"ix_source_health_snapshot_{column}"),
            "source_health_snapshot",
            [column],
            unique=False,
        )


def upgrade() -> None:
    if not _has_table("provider_event"):
        _create_provider_event_table()

    if not _has_table("source_health_snapshot"):
        _create_source_health_snapshot_table()


def downgrade() -> None:
    if _has_table("source_health_snapshot"):
        op.drop_table("source_health_snapshot")

    if _has_table("provider_event"):
        op.drop_table("provider_event")
