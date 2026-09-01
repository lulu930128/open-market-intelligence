"""Add Taiwan unified Bar identity and materialized daily lineage.

Revision ID: 20260901_0076
Revises: 20260901_0075
Create Date: 2026-09-01 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260901_0076"
down_revision: str | Sequence[str] | None = "20260901_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INTRADAY_TABLE = "market_intraday_bar"
INTRADAY_LINEAGE_TABLE = "market_intraday_bar_lineage"
DAILY_TABLE = "market_daily_price"
DAILY_LINEAGE_TABLE = "market_daily_price_lineage"
DAILY_RECONCILIATION_TABLE = "market_daily_price_reconciliation"


def _column_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _create_index_if_missing(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    sqlite_where: str | None = None,
) -> None:
    if index_name in _index_names(table_name):
        return
    kwargs: dict[str, object] = {}
    if sqlite_where is not None:
        kwargs["sqlite_where"] = sa.text(sqlite_where)
        kwargs["postgresql_where"] = sa.text(sqlite_where)
    op.create_index(
        index_name,
        table_name,
        columns,
        unique=unique,
        **kwargs,
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(INTRADAY_TABLE):
        existing = _column_names(INTRADAY_TABLE)
        additions = (
            sa.Column(
                "source_id",
                sa.Integer(),
                sa.ForeignKey(
                    "source_registry.id",
                    name="fk_market_intraday_bar_source_id",
                ),
                nullable=True,
            ),
            sa.Column("canonical_market", sa.String(length=20), nullable=True),
            sa.Column("venue", sa.String(length=20), nullable=True),
            sa.Column("instrument_type", sa.String(length=32), nullable=True),
        )
        # SQLite can add nullable columns in-place.  Using batch mode here
        # recreates the multi-million-row intraday table and makes normal API
        # startup an unbounded migration operation.
        for column in additions:
            if column.name not in existing:
                if (
                    column.name == "source_id"
                    and op.get_bind().dialect.name == "sqlite"
                ):
                    op.execute(
                        "ALTER TABLE market_intraday_bar ADD COLUMN "
                        "source_id INTEGER REFERENCES source_registry(id)"
                    )
                else:
                    op.add_column(INTRADAY_TABLE, column)
        for name in ("source_id", "canonical_market", "venue", "instrument_type"):
            _create_index_if_missing(
                INTRADAY_TABLE,
                f"ix_{INTRADAY_TABLE}_{name}",
                [name],
            )
        _create_index_if_missing(
            INTRADAY_TABLE,
            "uq_market_intraday_tw_canonical_candidate",
            [
                "source_id",
                "canonical_market",
                "venue",
                "instrument_type",
                "stock_id",
                "interval",
                "bar_time",
            ],
            unique=True,
            sqlite_where="canonical_market IS NOT NULL AND source_id IS NOT NULL",
        )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(INTRADAY_TABLE) and inspector.has_table(
        INTRADAY_LINEAGE_TABLE
    ):
        raw_column = next(
            item
            for item in inspector.get_columns(INTRADAY_LINEAGE_TABLE)
            if item["name"] == "raw_result_id"
        )
        if not raw_column["nullable"]:
            with op.batch_alter_table(INTRADAY_LINEAGE_TABLE) as batch_op:
                batch_op.alter_column(
                    "raw_result_id",
                    existing_type=sa.Integer(),
                    nullable=True,
                )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_TABLE):
        existing = _column_names(DAILY_TABLE)
        additions = (
            sa.Column("canonical_market", sa.String(length=20), nullable=True),
            sa.Column("venue", sa.String(length=20), nullable=True),
            sa.Column("instrument_type", sa.String(length=32), nullable=True),
            sa.Column("authority", sa.String(length=32), nullable=True),
            sa.Column("finalization", sa.String(length=32), nullable=True),
            sa.Column("official", sa.Boolean(), nullable=True),
            sa.Column("release_status", sa.String(length=32), nullable=True),
            sa.Column("reconciliation_status", sa.String(length=32), nullable=True),
            sa.Column("derivation_kind", sa.String(length=96), nullable=True),
            sa.Column("aggregation_version", sa.String(length=96), nullable=True),
        )
        raw_column = next(
            item
            for item in inspector.get_columns(DAILY_TABLE)
            if item["name"] == "raw_result_id"
        )
        for column in additions:
            if column.name not in existing:
                op.add_column(DAILY_TABLE, column)
        with op.batch_alter_table(DAILY_TABLE) as batch_op:
            if not raw_column["nullable"]:
                batch_op.alter_column(
                    "raw_result_id",
                    existing_type=sa.Integer(),
                    nullable=True,
                )
        for name in (
            "canonical_market",
            "venue",
            "instrument_type",
            "authority",
            "finalization",
            "official",
            "release_status",
            "reconciliation_status",
        ):
            _create_index_if_missing(
                DAILY_TABLE,
                f"ix_{DAILY_TABLE}_{name}",
                [name],
            )
        _create_index_if_missing(
            DAILY_TABLE,
            "uq_market_daily_tw_canonical_candidate",
            [
                "source_id",
                "canonical_market",
                "venue",
                "instrument_type",
                "stock_id",
                "trade_date",
            ],
            unique=True,
            sqlite_where="canonical_market IS NOT NULL",
        )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_TABLE) and not inspector.has_table(
        DAILY_LINEAGE_TABLE
    ):
        op.create_table(
            DAILY_LINEAGE_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("daily_price_id", sa.Integer(), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), nullable=True),
            sa.Column("evidence_kind", sa.String(length=48), nullable=False),
            sa.Column("source_interval", sa.String(length=16), nullable=False),
            sa.Column("materialization_version", sa.String(length=96), nullable=True),
            sa.Column("component_raw_result_ids_json", sa.Text(), nullable=True),
            sa.Column("component_content_hashes_json", sa.Text(), nullable=True),
            sa.Column("lineage_digest", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["daily_price_id"],
                ["market_daily_price.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "daily_price_id",
                name="uq_market_daily_price_lineage_daily_price_id",
            ),
        )
        for name in (
            "id",
            "daily_price_id",
            "raw_result_id",
            "evidence_kind",
            "lineage_digest",
        ):
            op.create_index(
                f"ix_{DAILY_LINEAGE_TABLE}_{name}",
                DAILY_LINEAGE_TABLE,
                [name],
                unique=False,
            )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_TABLE) and not inspector.has_table(
        DAILY_RECONCILIATION_TABLE
    ):
        op.create_table(
            DAILY_RECONCILIATION_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("daily_price_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("candidate_close", sa.Float(), nullable=True),
            sa.Column("official_close", sa.Float(), nullable=True),
            sa.Column("detail_json", sa.Text(), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["daily_price_id"],
                ["market_daily_price.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["source_id"], ["source_registry.id"]),
            sa.ForeignKeyConstraint(["raw_result_id"], ["raw_fetch_result.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "daily_price_id",
                "source_id",
                "raw_result_id",
                name="uq_market_daily_reconciliation_evidence",
            ),
        )
        for name in (
            "id",
            "daily_price_id",
            "source_id",
            "raw_result_id",
            "checked_at",
        ):
            op.create_index(
                f"ix_{DAILY_RECONCILIATION_TABLE}_{name}",
                DAILY_RECONCILIATION_TABLE,
                [name],
                unique=False,
            )
        op.create_index(
            "ix_market_daily_reconciliation_evidence_status",
            DAILY_RECONCILIATION_TABLE,
            ["status"],
            unique=False,
        )


def _assert_no_null_materialized_rows(table_name: str) -> None:
    count = op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE raw_result_id IS NULL")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade {revision}: {table_name} contains {count} "
            "materialized rows without a single raw receipt"
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_RECONCILIATION_TABLE):
        op.drop_table(DAILY_RECONCILIATION_TABLE)
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_LINEAGE_TABLE):
        op.drop_table(DAILY_LINEAGE_TABLE)

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(DAILY_TABLE):
        _assert_no_null_materialized_rows(DAILY_TABLE)
        indexes = _index_names(DAILY_TABLE)
        if "uq_market_daily_tw_canonical_candidate" in indexes:
            op.drop_index(
                "uq_market_daily_tw_canonical_candidate", table_name=DAILY_TABLE
            )
        for name in (
            "canonical_market",
            "venue",
            "instrument_type",
            "authority",
            "finalization",
            "official",
            "release_status",
            "reconciliation_status",
        ):
            index_name = f"ix_{DAILY_TABLE}_{name}"
            if index_name in _index_names(DAILY_TABLE):
                op.drop_index(index_name, table_name=DAILY_TABLE)
        existing = _column_names(DAILY_TABLE)
        with op.batch_alter_table(DAILY_TABLE) as batch_op:
            batch_op.alter_column(
                "raw_result_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            for name in (
                "aggregation_version",
                "derivation_kind",
                "reconciliation_status",
                "release_status",
                "official",
                "finalization",
                "authority",
                "instrument_type",
                "venue",
                "canonical_market",
            ):
                if name in existing:
                    batch_op.drop_column(name)

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(INTRADAY_LINEAGE_TABLE):
        _assert_no_null_materialized_rows(INTRADAY_LINEAGE_TABLE)
        with op.batch_alter_table(INTRADAY_LINEAGE_TABLE) as batch_op:
            batch_op.alter_column(
                "raw_result_id",
                existing_type=sa.Integer(),
                nullable=False,
            )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(INTRADAY_TABLE):
        indexes = _index_names(INTRADAY_TABLE)
        if "uq_market_intraday_tw_canonical_candidate" in indexes:
            op.drop_index(
                "uq_market_intraday_tw_canonical_candidate",
                table_name=INTRADAY_TABLE,
            )
        for name in ("source_id", "canonical_market", "venue", "instrument_type"):
            index_name = f"ix_{INTRADAY_TABLE}_{name}"
            if index_name in _index_names(INTRADAY_TABLE):
                op.drop_index(index_name, table_name=INTRADAY_TABLE)
        existing = _column_names(INTRADAY_TABLE)
        with op.batch_alter_table(INTRADAY_TABLE) as batch_op:
            for name in ("instrument_type", "venue", "canonical_market", "source_id"):
                if name in existing:
                    batch_op.drop_column(name)
