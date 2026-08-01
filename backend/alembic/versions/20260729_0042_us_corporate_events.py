"""Add normalized US corporate events.

Revision ID: 20260729_0042
Revises: 20260729_0041
Create Date: 2026-07-29 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_0042"
down_revision: str | Sequence[str] | None = "20260729_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("us_corporate_event"):
        return

    op.create_table(
        "us_corporate_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_uid", sa.String(length=180), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("source_event_id", sa.String(length=160), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("company_name", sa.String(length=240), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_subtype", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=320), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "event_status",
            sa.String(length=40),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column(
            "verification_status",
            sa.String(length=40),
            nullable=False,
            server_default="third_party",
        ),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column(
            "timezone_name",
            sa.String(length=80),
            nullable=False,
            server_default="America/New_York",
        ),
        sa.Column(
            "market_session",
            sa.String(length=30),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "is_all_day",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_quarter", sa.String(length=20), nullable=True),
        sa.Column("fiscal_period_end", sa.Date(), nullable=True),
        sa.Column("estimated_eps", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_hash", sa.String(length=128), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uid", name="uq_us_corporate_event_uid"),
    )
    for column in (
        "id",
        "event_uid",
        "provider",
        "source_event_id",
        "symbol",
        "event_type",
        "event_subtype",
        "event_status",
        "verification_status",
        "event_date",
        "market_session",
        "is_all_day",
        "fiscal_year",
        "fiscal_quarter",
        "fiscal_period_end",
        "currency",
        "raw_payload_hash",
        "fetched_at",
        "is_active",
    ):
        op.create_index(
            op.f(f"ix_us_corporate_event_{column}"),
            "us_corporate_event",
            [column],
            unique=column == "event_uid",
        )


def downgrade() -> None:
    if _has_table("us_corporate_event"):
        op.drop_table("us_corporate_event")
