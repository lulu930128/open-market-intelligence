"""Add immutable Taiwan financial parse review events.

Revision ID: 20260731_0049
Revises: 20260731_0048
Create Date: 2026-07-31 04:10:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0049"
down_revision: str | Sequence[str] | None = "20260731_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    snapshots = (
        bind.execute(
            sa.text(
                """
                SELECT
                    id AS parse_run_id,
                    review_status AS decision,
                    COALESCE(reviewed_at, parsed_at) AS decided_at,
                    COALESCE(
                        reviewed_by,
                        'migration:20260731_0049'
                    ) AS decided_by,
                    output_hash AS output_hash_snapshot,
                    COALESCE(reviewed_at, parsed_at) AS created_at
                FROM tw_financial_parse_run
                WHERE review_status IN ('approved', 'rejected', 'revoked')
                ORDER BY id
                """
            )
        )
        .mappings()
        .all()
    )
    if not inspector.has_table("tw_financial_parse_run_review"):
        op.create_table(
            "tw_financial_parse_run_review",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parse_run_id", sa.Integer(), nullable=False),
            sa.Column("decision", sa.String(length=20), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_by", sa.String(length=160), nullable=False),
            sa.Column("output_hash_snapshot", sa.String(length=64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "decision IN ('approved', 'rejected', 'revoked')",
                name="ck_tw_financial_parse_run_review_decision",
            ),
            sa.ForeignKeyConstraint(
                ["parse_run_id"],
                ["tw_financial_parse_run.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    review_table = sa.table(
        "tw_financial_parse_run_review",
        sa.column("parse_run_id", sa.Integer()),
        sa.column("decision", sa.String()),
        sa.column("decided_at", sa.DateTime(timezone=True)),
        sa.column("decided_by", sa.String()),
        sa.column("output_hash_snapshot", sa.String()),
        sa.column("reason", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    existing_events = (
        bind.execute(
            sa.text(
                """
                SELECT
                    parse_run_id,
                    decision,
                    decided_at,
                    decided_by,
                    output_hash_snapshot
                FROM tw_financial_parse_run_review
                """
            )
        )
        .mappings()
        .all()
    )
    existing_keys = {
        (
            int(event["parse_run_id"]),
            str(event["decision"]),
            str(event["decided_at"]),
            str(event["decided_by"]),
            event["output_hash_snapshot"],
        )
        for event in existing_events
    }
    missing_snapshots = [
        snapshot
        for snapshot in snapshots
        if (
            int(snapshot["parse_run_id"]),
            str(snapshot["decision"]),
            str(snapshot["decided_at"]),
            str(snapshot["decided_by"]),
            snapshot["output_hash_snapshot"],
        )
        not in existing_keys
    ]
    if missing_snapshots:
        op.bulk_insert(
            review_table,
            [
                {
                    **dict(snapshot),
                    "decided_at": _as_datetime(snapshot["decided_at"]),
                    "created_at": _as_datetime(snapshot["created_at"]),
                    "reason": (
                        "adopted current review snapshot during migration"
                    ),
                }
                for snapshot in missing_snapshots
            ],
        )

    inspector = sa.inspect(bind)
    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes("tw_financial_parse_run_review")
    }
    index_specs = {
        "ix_tw_financial_parse_run_review_id": (["id"], False),
        "ix_tw_financial_parse_run_review_parse_run_id": (
            ["parse_run_id"],
            False,
        ),
        "ix_tw_financial_parse_run_review_decision": (["decision"], False),
        "ix_tw_financial_parse_run_review_decided_at": (["decided_at"], False),
        "ix_tw_financial_parse_run_review_output_hash_snapshot": (
            ["output_hash_snapshot"],
            False,
        ),
        "ix_tw_financial_parse_run_review_as_of": (
            ["parse_run_id", "decided_at", "id"],
            False,
        ),
    }
    for index_name, (columns, unique) in index_specs.items():
        if index_name not in existing_indexes:
            op.create_index(
                index_name,
                "tw_financial_parse_run_review",
                columns,
                unique=unique,
            )

    persisted_keys = {
        (
            int(event["parse_run_id"]),
            str(event["decision"]),
            str(event["decided_at"]),
            str(event["decided_by"]),
            event["output_hash_snapshot"],
        )
        for event in bind.execute(
            sa.text(
                """
                SELECT
                    parse_run_id,
                    decision,
                    decided_at,
                    decided_by,
                    output_hash_snapshot
                FROM tw_financial_parse_run_review
                """
            )
        )
        .mappings()
        .all()
    }
    expected_keys = {
        (
            int(snapshot["parse_run_id"]),
            str(snapshot["decision"]),
            str(snapshot["decided_at"]),
            str(snapshot["decided_by"]),
            snapshot["output_hash_snapshot"],
        )
        for snapshot in snapshots
    }
    missing_keys = expected_keys - persisted_keys
    if missing_keys:
        raise RuntimeError(
            "parse review migration snapshot mismatch: "
            f"missing={len(missing_keys)}"
        )
    event_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM tw_financial_parse_run_review"
        )
    ).scalar_one()
    if event_count < len(expected_keys):
        raise RuntimeError(
            "parse review migration snapshot mismatch: "
            f"expected_at_least={len(expected_keys)} actual={event_count}"
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tw_financial_parse_run_review"):
        return
    for index_name in (
        "ix_tw_financial_parse_run_review_as_of",
        "ix_tw_financial_parse_run_review_output_hash_snapshot",
        "ix_tw_financial_parse_run_review_decided_at",
        "ix_tw_financial_parse_run_review_decision",
        "ix_tw_financial_parse_run_review_parse_run_id",
        "ix_tw_financial_parse_run_review_id",
    ):
        op.drop_index(
            index_name,
            table_name="tw_financial_parse_run_review",
        )
    op.drop_table("tw_financial_parse_run_review")
