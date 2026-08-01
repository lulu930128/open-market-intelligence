"""Add canonical Radar v2 feature, evaluation, event, outcome, and backtest tables.

Revision ID: 20260729_0041
Revises: 20260727_0040
Create Date: 2026-07-29 20:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_0041"
down_revision: str | Sequence[str] | None = "20260727_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_indexes(table_name: str, columns: Sequence[str]) -> None:
    for column in columns:
        op.create_index(
            op.f(f"ix_{table_name}_{column}"),
            table_name,
            [column],
            unique=False,
        )


def _create_rule_config() -> None:
    table_name = "radar_rule_config"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contract_type", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("code_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contract_type",
            "version",
            "config_hash",
            name="uq_radar_rule_config_contract_version_hash",
        ),
    )
    _create_indexes(
        table_name,
        ("id", "contract_type", "version", "config_hash", "status", "code_commit_sha"),
    )


def _create_feature_snapshot() -> None:
    table_name = "radar_feature_snapshot"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=120), nullable=True),
        sa.Column("signal_trade_date", sa.Date(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_basis", sa.String(length=40), nullable=False),
        sa.Column("source_timeframe", sa.String(length=20), nullable=False),
        sa.Column("feature_version", sa.String(length=80), nullable=False),
        sa.Column("feature_config_hash", sa.String(length=64), nullable=False),
        sa.Column("input_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("market_data_revision", sa.String(length=128), nullable=True),
        sa.Column("data_status", sa.String(length=30), nullable=False),
        sa.Column("freshness_status", sa.String(length=30), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("completeness_score", sa.Float(), nullable=False),
        sa.Column("source_quality_score", sa.Float(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("is_provisional", sa.Boolean(), nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("previous_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("signal_atr", sa.Float(), nullable=True),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("signals_json", sa.Text(), nullable=False),
        sa.Column("input_manifest_json", sa.Text(), nullable=False),
        sa.Column("data_limitations_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "stock_id",
            "signal_trade_date",
            "feature_basis",
            "feature_version",
            "feature_config_hash",
            "input_manifest_hash",
            name="uq_radar_feature_snapshot_identity",
        ),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "market",
            "stock_id",
            "signal_trade_date",
            "effective_at",
            "available_at",
            "feature_basis",
            "source_timeframe",
            "feature_version",
            "feature_config_hash",
            "input_manifest_hash",
            "data_status",
            "freshness_status",
            "is_provisional",
            "is_stale",
        ),
    )


def _create_rule_evaluation() -> None:
    table_name = "radar_rule_evaluation"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("rule_config_hash", sa.String(length=64), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("signal_trade_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("direction_score", sa.Float(), nullable=False),
        sa.Column("evidence_score", sa.Float(), nullable=False),
        sa.Column("within_family_conflict_score", sa.Float(), nullable=False),
        sa.Column("cross_family_conflict_score", sa.Float(), nullable=False),
        sa.Column("timeframe_conflict_score", sa.Float(), nullable=False),
        sa.Column("conflict_score", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("context_alignment_score", sa.Float(), nullable=False),
        sa.Column("primary_bucket", sa.String(length=80), nullable=False),
        sa.Column("urgency", sa.String(length=30), nullable=False),
        sa.Column("evidence_grade", sa.String(length=30), nullable=False),
        sa.Column("instrument_regime", sa.String(length=40), nullable=False),
        sa.Column("market_regime", sa.String(length=40), nullable=True),
        sa.Column("instrument_regime_clarity", sa.Float(), nullable=False),
        sa.Column("market_regime_clarity", sa.Float(), nullable=True),
        sa.Column("state_tags_json", sa.Text(), nullable=False),
        sa.Column("risk_tags_json", sa.Text(), nullable=False),
        sa.Column("family_scores_json", sa.Text(), nullable=False),
        sa.Column("signal_contributions_json", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False),
        sa.Column("raw_evaluation_json", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feature_snapshot_id"], ["radar_feature_snapshot.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "feature_snapshot_id",
            "rule_version",
            "rule_config_hash",
            name="uq_radar_rule_evaluation_feature_rule_hash",
        ),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "feature_snapshot_id",
            "rule_version",
            "rule_config_hash",
            "stock_id",
            "signal_trade_date",
            "direction",
            "primary_bucket",
            "urgency",
            "evidence_grade",
            "instrument_regime",
            "market_regime",
            "evaluated_at",
        ),
    )


def _create_signal_event() -> None:
    table_name = "radar_signal_event"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("event_key", sa.String(length=120), nullable=False),
        sa.Column("family", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("rule_config_hash", sa.String(length=64), nullable=False),
        sa.Column("onset_feature_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("onset_evaluation_id", sa.Integer(), nullable=False),
        sa.Column("latest_evaluation_id", sa.Integer(), nullable=False),
        sa.Column("onset_trade_date", sa.Date(), nullable=False),
        sa.Column("last_active_trade_date", sa.Date(), nullable=False),
        sa.Column("exit_trade_date", sa.Date(), nullable=True),
        sa.Column("persistence_trading_days", sa.Integer(), nullable=False),
        sa.Column("retrigger_count", sa.Integer(), nullable=False),
        sa.Column("alert_cooldown_until", sa.Date(), nullable=True),
        sa.Column("event_metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["onset_feature_snapshot_id"],
            ["radar_feature_snapshot.id"],
        ),
        sa.ForeignKeyConstraint(["onset_evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.ForeignKeyConstraint(["latest_evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "stock_id",
            "event_key",
            "direction",
            "onset_trade_date",
            "rule_version",
            "rule_config_hash",
            name="uq_radar_signal_event_identity",
        ),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "market",
            "stock_id",
            "event_key",
            "family",
            "direction",
            "signal_type",
            "status",
            "rule_version",
            "rule_config_hash",
            "onset_feature_snapshot_id",
            "onset_evaluation_id",
            "latest_evaluation_id",
            "onset_trade_date",
            "last_active_trade_date",
            "exit_trade_date",
        ),
    )


def _create_watchlist_projection() -> None:
    table_name = "radar_watchlist_projection"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_run_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_item_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("rank_percentile", sa.Float(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["watchlist_group.id"]),
        sa.ForeignKeyConstraint(
            ["snapshot_run_id"],
            ["watchlist_radar_snapshot_run.id"],
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_item_id"],
            ["watchlist_radar_snapshot_item.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "group_id",
            "mode",
            "snapshot_date",
            name="uq_radar_watchlist_projection_scope",
        ),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "evaluation_id",
            "group_id",
            "snapshot_run_id",
            "snapshot_item_id",
            "mode",
            "snapshot_date",
            "rank",
            "selected",
        ),
    )


def _create_outcome_path() -> None:
    table_name = "radar_outcome_path"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("signal_event_id", sa.Integer(), nullable=True),
        sa.Column("stock_id", sa.String(length=20), nullable=False),
        sa.Column("signal_trade_date", sa.Date(), nullable=False),
        sa.Column("horizon_trading_days", sa.Integer(), nullable=False),
        sa.Column("horizon_end_trade_date", sa.Date(), nullable=True),
        sa.Column("outcome_contract_version", sa.String(length=80), nullable=False),
        sa.Column("outcome_config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary_state", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=True),
        sa.Column("reference_price_type", sa.String(length=40), nullable=False),
        sa.Column("entry_proxy_price", sa.Float(), nullable=True),
        sa.Column("entry_proxy_price_type", sa.String(length=40), nullable=True),
        sa.Column("entry_proxy_trade_date", sa.Date(), nullable=True),
        sa.Column("signal_atr", sa.Float(), nullable=True),
        sa.Column("path_open_price", sa.Float(), nullable=True),
        sa.Column("path_high_price", sa.Float(), nullable=True),
        sa.Column("path_low_price", sa.Float(), nullable=True),
        sa.Column("path_close_price", sa.Float(), nullable=True),
        sa.Column("path_volume", sa.BigInteger(), nullable=True),
        sa.Column("signal_open_gap_pct", sa.Float(), nullable=True),
        sa.Column("signal_close_return_pct", sa.Float(), nullable=True),
        sa.Column("signal_mfe_pct", sa.Float(), nullable=True),
        sa.Column("signal_mae_pct", sa.Float(), nullable=True),
        sa.Column("entry_close_return_pct", sa.Float(), nullable=True),
        sa.Column("entry_mfe_pct", sa.Float(), nullable=True),
        sa.Column("entry_mae_pct", sa.Float(), nullable=True),
        sa.Column("close_r", sa.Float(), nullable=True),
        sa.Column("mfe_r", sa.Float(), nullable=True),
        sa.Column("mae_r", sa.Float(), nullable=True),
        sa.Column("intraday_triggered", sa.Boolean(), nullable=False),
        sa.Column("close_confirmed", sa.Boolean(), nullable=False),
        sa.Column("adverse_triggered", sa.Boolean(), nullable=False),
        sa.Column("reversed", sa.Boolean(), nullable=False),
        sa.Column("whipsaw", sa.Boolean(), nullable=False),
        sa.Column("invalidated", sa.Boolean(), nullable=False),
        sa.Column("return_basis", sa.String(length=40), nullable=False),
        sa.Column("corporate_action_status", sa.String(length=30), nullable=False),
        sa.Column("corporate_actions_json", sa.Text(), nullable=False),
        sa.Column("outcome_source", sa.String(length=80), nullable=True),
        sa.Column("outcome_quality", sa.String(length=30), nullable=False),
        sa.Column("path_order_quality", sa.String(length=30), nullable=False),
        sa.Column("tradability_status", sa.String(length=30), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False),
        sa.Column("raw_path_json", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["radar_rule_evaluation.id"]),
        sa.ForeignKeyConstraint(["signal_event_id"], ["radar_signal_event.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "outcome_contract_version",
            "outcome_config_hash",
            "horizon_trading_days",
            name="uq_radar_outcome_path_evaluation_contract_horizon",
        ),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "evaluation_id",
            "signal_event_id",
            "stock_id",
            "signal_trade_date",
            "horizon_trading_days",
            "horizon_end_trade_date",
            "outcome_contract_version",
            "outcome_config_hash",
            "status",
            "summary_state",
            "direction",
            "intraday_triggered",
            "close_confirmed",
            "adverse_triggered",
            "reversed",
            "whipsaw",
            "invalidated",
            "return_basis",
            "corporate_action_status",
            "outcome_source",
            "outcome_quality",
            "path_order_quality",
            "tradability_status",
            "evaluated_at",
        ),
    )


def _create_backtest_run() -> None:
    table_name = "radar_backtest_run"
    if _has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("rule_config_hash", sa.String(length=64), nullable=False),
        sa.Column("feature_version", sa.String(length=80), nullable=False),
        sa.Column("feature_config_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome_contract_version", sa.String(length=80), nullable=False),
        sa.Column("outcome_config_hash", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("purge_trading_days", sa.Integer(), nullable=False),
        sa.Column("embargo_trading_days", sa.Integer(), nullable=False),
        sa.Column("requested_sample_count", sa.Integer(), nullable=False),
        sa.Column("eligible_sample_count", sa.Integer(), nullable=False),
        sa.Column("excluded_sample_count", sa.Integer(), nullable=False),
        sa.Column("coverage_ratio", sa.Float(), nullable=False),
        sa.Column("horizons_json", sa.Text(), nullable=False),
        sa.Column("universe_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.Column("split_json", sa.Text(), nullable=False),
        sa.Column("baseline_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key"),
    )
    _create_indexes(
        table_name,
        (
            "id",
            "run_key",
            "status",
            "rule_version",
            "rule_config_hash",
            "feature_version",
            "feature_config_hash",
            "outcome_contract_version",
            "outcome_config_hash",
            "period_start",
            "period_end",
        ),
    )


def upgrade() -> None:
    _create_rule_config()
    _create_feature_snapshot()
    _create_rule_evaluation()
    _create_signal_event()
    _create_watchlist_projection()
    _create_outcome_path()
    _create_backtest_run()


def downgrade() -> None:
    for table_name in (
        "radar_backtest_run",
        "radar_outcome_path",
        "radar_watchlist_projection",
        "radar_signal_event",
        "radar_rule_evaluation",
        "radar_feature_snapshot",
        "radar_rule_config",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
