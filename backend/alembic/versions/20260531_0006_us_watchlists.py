"""Add isolated US watchlist tables.

Revision ID: 20260531_0006
Revises: 20260531_0005
Create Date: 2026-05-31 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260531_0006"
down_revision: str | Sequence[str] | None = "20260531_0005"
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
    if not _has_table("us_watchlist_group"):
        op.create_table(
            "us_watchlist_group",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("group_name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["parent_id"], ["us_watchlist_group.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_us_watchlist_group_group_name"), "us_watchlist_group", ["group_name"], unique=False)
        op.create_index(op.f("ix_us_watchlist_group_id"), "us_watchlist_group", ["id"], unique=False)
        op.create_index(op.f("ix_us_watchlist_group_is_active"), "us_watchlist_group", ["is_active"], unique=False)
        op.create_index(op.f("ix_us_watchlist_group_parent_id"), "us_watchlist_group", ["parent_id"], unique=False)
        op.create_index(op.f("ix_us_watchlist_group_sort_order"), "us_watchlist_group", ["sort_order"], unique=False)

    if not _has_table("us_watchlist_item"):
        op.create_table(
            "us_watchlist_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("tags", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["us_watchlist_group.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "group_id",
                "symbol",
                name="uq_us_watchlist_item_group_symbol",
            ),
        )
        op.create_index(op.f("ix_us_watchlist_item_enabled"), "us_watchlist_item", ["enabled"], unique=False)
        op.create_index(op.f("ix_us_watchlist_item_group_id"), "us_watchlist_item", ["group_id"], unique=False)
        op.create_index(op.f("ix_us_watchlist_item_id"), "us_watchlist_item", ["id"], unique=False)
        op.create_index(op.f("ix_us_watchlist_item_priority"), "us_watchlist_item", ["priority"], unique=False)
        op.create_index(op.f("ix_us_watchlist_item_symbol"), "us_watchlist_item", ["symbol"], unique=False)


def downgrade() -> None:
    if _has_table("us_watchlist_item"):
        _drop_indexes(
            "us_watchlist_item",
            (
                "ix_us_watchlist_item_symbol",
                "ix_us_watchlist_item_priority",
                "ix_us_watchlist_item_id",
                "ix_us_watchlist_item_group_id",
                "ix_us_watchlist_item_enabled",
            ),
        )
        op.drop_table("us_watchlist_item")

    if _has_table("us_watchlist_group"):
        _drop_indexes(
            "us_watchlist_group",
            (
                "ix_us_watchlist_group_sort_order",
                "ix_us_watchlist_group_parent_id",
                "ix_us_watchlist_group_is_active",
                "ix_us_watchlist_group_id",
                "ix_us_watchlist_group_group_name",
            ),
        )
        op.drop_table("us_watchlist_group")
