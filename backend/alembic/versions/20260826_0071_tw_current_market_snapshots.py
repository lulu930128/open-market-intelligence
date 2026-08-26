"""Add typed Taiwan current-session index and breadth snapshots.

Revision ID: 20260826_0071
Revises: 20260826_0070
Create Date: 2026-08-26 13:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260826_0071"
down_revision: str | Sequence[str] | None = "20260826_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_TABLE = "taiwan_current_index_snapshot"
BREADTH_TABLE = "taiwan_current_breadth_snapshot"


def _lineage_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_result_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("authority", sa.String(length=40), nullable=False),
        sa.Column("raw_contract_version", sa.String(length=96), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def _constraints(prefix: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_registry.id"],
            name=f"fk_{prefix}_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["raw_result_id"],
            ["raw_fetch_result.id"],
            name=f"fk_{prefix}_raw_result_id",
        ),
    )


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(INDEX_TABLE):
        op.create_table(
            INDEX_TABLE,
            *_lineage_columns(),
            sa.Column("index_id", sa.String(length=20), nullable=False),
            sa.Column("venue", sa.String(length=20), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("session", sa.String(length=40), nullable=False),
            sa.Column("close_value", sa.Float(), nullable=False),
            sa.Column("price_change", sa.Float(), nullable=False),
            sa.Column("trade_volume", sa.BigInteger(), nullable=True),
            sa.Column("trade_volume_unit", sa.String(length=24), nullable=True),
            sa.Column("trade_value", sa.BigInteger(), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("transaction_count", sa.BigInteger(), nullable=True),
            sa.Column("observation_state", sa.String(length=24), nullable=False),
            sa.Column("value_semantics", sa.String(length=64), nullable=False),
            sa.Column("finalization", sa.String(length=24), nullable=False),
            sa.Column("official", sa.Boolean(), nullable=False),
            sa.Column("provisional", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            *_constraints("tw_current_index"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "source",
                "index_id",
                "event_at",
                name="uq_tw_current_index_provider_source_event",
            ),
        )
        _indexes(
            INDEX_TABLE,
            (
                "id",
                "source_id",
                "raw_result_id",
                "provider",
                "source",
                "event_at",
                "fetched_at",
                "index_id",
                "venue",
                "trade_date",
                "session",
                "observation_state",
                "finalization",
            ),
        )
    if not inspector.has_table(BREADTH_TABLE):
        op.create_table(
            BREADTH_TABLE,
            *_lineage_columns(),
            sa.Column("venue", sa.String(length=20), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("session", sa.String(length=40), nullable=False),
            sa.Column("scope", sa.String(length=64), nullable=False),
            sa.Column("universe_source", sa.String(length=192), nullable=False),
            sa.Column("universe_count", sa.Integer(), nullable=False),
            sa.Column("advance_count", sa.Integer(), nullable=False),
            sa.Column("decline_count", sa.Integer(), nullable=False),
            sa.Column("unchanged_count", sa.Integer(), nullable=False),
            sa.Column("received_unclassified_count", sa.Integer(), nullable=False),
            sa.Column("not_received_count", sa.Integer(), nullable=False),
            sa.Column("trade_value", sa.BigInteger(), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("observation_state", sa.String(length=24), nullable=False),
            sa.Column("price_semantics", sa.String(length=64), nullable=False),
            sa.Column("official", sa.Boolean(), nullable=False),
            sa.Column("provisional", sa.Boolean(), nullable=False),
            sa.Column("decision_usable", sa.Boolean(), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            *_constraints("tw_current_breadth"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "source",
                "venue",
                "event_at",
                name="uq_tw_current_breadth_provider_source_event",
            ),
        )
        _indexes(
            BREADTH_TABLE,
            (
                "id",
                "source_id",
                "raw_result_id",
                "provider",
                "source",
                "event_at",
                "fetched_at",
                "venue",
                "trade_date",
                "session",
                "scope",
                "observation_state",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(BREADTH_TABLE):
        op.drop_table(BREADTH_TABLE)
    if inspector.has_table(INDEX_TABLE):
        op.drop_table(INDEX_TABLE)
