"""add watchlist radar snapshot outcome tables

Revision ID: 20260707_0032
Revises: 20260706_0031
Create Date: 2026-07-07 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260707_0032"
down_revision: str | Sequence[str] | None = "20260706_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _create_index(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(op.f(index_name), table_name, columns, unique=False)


def upgrade() -> None:
    if not _has_table("watchlist_radar_snapshot_run"):
        op.create_table(
            "watchlist_radar_snapshot_run",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("include_children", sa.Boolean(), nullable=False),
            sa.Column("enabled_only", sa.Boolean(), nullable=False),
            sa.Column("mode", sa.String(length=40), nullable=False),
            sa.Column("max_results", sa.Integer(), nullable=False),
            sa.Column("calculation_limit", sa.Integer(), nullable=False),
            sa.Column("radar_rule_version", sa.String(length=80), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=True),
            sa.Column("target_trade_date", sa.Date(), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False),
            sa.Column("current_stock_count", sa.Integer(), nullable=False),
            sa.Column("stale_stock_count", sa.Integer(), nullable=False),
            sa.Column("requested_stock_count", sa.Integer(), nullable=False),
            sa.Column("ranked_count", sa.Integer(), nullable=False),
            sa.Column("matched_count", sa.Integer(), nullable=False),
            sa.Column("radar_count", sa.Integer(), nullable=False),
            sa.Column("no_data_count", sa.Integer(), nullable=False),
            sa.Column("error_count", sa.Integer(), nullable=False),
            sa.Column("buckets_json", sa.Text(), nullable=False),
            sa.Column("data_limitations_json", sa.Text(), nullable=False),
            sa.Column("request_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["watchlist_group.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "group_id",
                "mode",
                "snapshot_date",
                "radar_rule_version",
                "include_children",
                "enabled_only",
                name="uq_watchlist_radar_snapshot_scope",
            ),
        )

    if not _has_table("watchlist_radar_snapshot_item"):
        op.create_table(
            "watchlist_radar_snapshot_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_run_id", sa.Integer(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("source_rank", sa.Integer(), nullable=True),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("stock_name", sa.String(length=120), nullable=True),
            sa.Column("bucket", sa.String(length=80), nullable=False),
            sa.Column("bucket_label", sa.String(length=120), nullable=False),
            sa.Column("urgency", sa.String(length=40), nullable=False),
            sa.Column("priority_score", sa.Float(), nullable=False),
            sa.Column("technical_evidence_score", sa.Float(), nullable=False),
            sa.Column("technical_score", sa.Float(), nullable=False),
            sa.Column("technical_grade", sa.String(length=40), nullable=False),
            sa.Column("direction", sa.String(length=40), nullable=False),
            sa.Column("signal_trade_date", sa.Date(), nullable=True),
            sa.Column("close_price", sa.Float(), nullable=True),
            sa.Column("volume", sa.BigInteger(), nullable=True),
            sa.Column("change_pct", sa.Float(), nullable=True),
            sa.Column("previous_close", sa.Float(), nullable=True),
            sa.Column("limit_status", sa.String(length=40), nullable=True),
            sa.Column("action_label", sa.Text(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("signal_keys_json", sa.Text(), nullable=False),
            sa.Column("matched_signal_keys_json", sa.Text(), nullable=False),
            sa.Column("context_signals_json", sa.Text(), nullable=False),
            sa.Column("factor_scores_json", sa.Text(), nullable=False),
            sa.Column("price_levels_json", sa.Text(), nullable=False),
            sa.Column("raw_item_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["snapshot_run_id"], ["watchlist_radar_snapshot_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "snapshot_run_id",
                "rank",
                "stock_id",
                "bucket",
                name="uq_watchlist_radar_snapshot_item_rank",
            ),
        )

    if not _has_table("watchlist_radar_outcome"):
        op.create_table(
            "watchlist_radar_outcome",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("snapshot_run_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_item_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("stock_id", sa.String(length=20), nullable=False),
            sa.Column("bucket", sa.String(length=80), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("outcome_trade_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("signal_close_price", sa.Float(), nullable=True),
            sa.Column("outcome_open_price", sa.Float(), nullable=True),
            sa.Column("outcome_high_price", sa.Float(), nullable=True),
            sa.Column("outcome_low_price", sa.Float(), nullable=True),
            sa.Column("outcome_close_price", sa.Float(), nullable=True),
            sa.Column("outcome_volume", sa.BigInteger(), nullable=True),
            sa.Column("open_gap_pct", sa.Float(), nullable=True),
            sa.Column("close_return_pct", sa.Float(), nullable=True),
            sa.Column("max_favorable_pct", sa.Float(), nullable=True),
            sa.Column("max_adverse_pct", sa.Float(), nullable=True),
            sa.Column("intraday_range_pct", sa.Float(), nullable=True),
            sa.Column("volume_change_pct", sa.Float(), nullable=True),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["snapshot_item_id"], ["watchlist_radar_snapshot_item.id"]),
            sa.ForeignKeyConstraint(["snapshot_run_id"], ["watchlist_radar_snapshot_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("snapshot_item_id", name="uq_watchlist_radar_outcome_item"),
        )

    index_specs: tuple[tuple[str, str, list[str]], ...] = (
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_group_id", ["group_id"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_mode", ["mode"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_snapshot_date", ["snapshot_date"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_trade_date", ["trade_date"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_target_trade_date", ["target_trade_date"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_is_current", ["is_current"]),
        ("watchlist_radar_snapshot_run", "ix_watchlist_radar_snapshot_run_radar_rule_version", ["radar_rule_version"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_snapshot_run_id", ["snapshot_run_id"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_rank", ["rank"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_stock_id", ["stock_id"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_bucket", ["bucket"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_urgency", ["urgency"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_technical_grade", ["technical_grade"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_direction", ["direction"]),
        ("watchlist_radar_snapshot_item", "ix_watchlist_radar_snapshot_item_signal_trade_date", ["signal_trade_date"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_snapshot_run_id", ["snapshot_run_id"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_snapshot_item_id", ["snapshot_item_id"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_group_id", ["group_id"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_stock_id", ["stock_id"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_bucket", ["bucket"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_snapshot_date", ["snapshot_date"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_outcome_trade_date", ["outcome_trade_date"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_status", ["status"]),
        ("watchlist_radar_outcome", "ix_watchlist_radar_outcome_evaluated_at", ["evaluated_at"]),
    )
    for table_name, index_name, columns in index_specs:
        _create_index(table_name, index_name, columns)


def downgrade() -> None:
    for table_name in (
        "watchlist_radar_outcome",
        "watchlist_radar_snapshot_item",
        "watchlist_radar_snapshot_run",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
