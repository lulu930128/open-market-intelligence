"""Add Taiwan breadth session and formal-trade provenance.

Revision ID: 20260803_0050
Revises: 20260731_0049
Create Date: 2026-08-03 19:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0050"
down_revision: str | Sequence[str] | None = "20260731_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {
        str(column["name"]) for column in _inspector().get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {
        str(index["name"]) for index in _inspector().get_indexes(table_name)
    }


def _add_columns(
    table_name: str,
    columns: tuple[tuple[str, sa.Column], ...],
) -> None:
    if not _has_table(table_name):
        return
    for name, column in columns:
        if not _has_column(table_name, name):
            op.add_column(table_name, column)


def _add_index(table_name: str, column_name: str) -> None:
    index_name = f"ix_{table_name}_{column_name}"
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, [column_name], unique=False)


def upgrade() -> None:
    stock_table = "taiwan_intraday_stock_state"
    _add_columns(
        stock_table,
        (
            ("snapshot_as_of", sa.Column("snapshot_as_of", sa.DateTime(timezone=True), nullable=True)),
            ("price_as_of", sa.Column("price_as_of", sa.DateTime(timezone=True), nullable=True)),
            (
                "price_semantics",
                sa.Column(
                    "price_semantics",
                    sa.String(length=40),
                    nullable=False,
                    server_default="legacy_unverified",
                ),
            ),
            ("price_source", sa.Column("price_source", sa.String(length=40), nullable=True)),
            (
                "has_actual_trade",
                sa.Column(
                    "has_actual_trade",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            ),
            (
                "indicative_match_available",
                sa.Column(
                    "indicative_match_available",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            ),
            ("indicative_match_price", sa.Column("indicative_match_price", sa.Float(), nullable=True)),
            (
                "indicative_match_volume_lots",
                sa.Column("indicative_match_volume_lots", sa.BigInteger(), nullable=True),
            ),
            (
                "session_phase",
                sa.Column(
                    "session_phase",
                    sa.String(length=30),
                    nullable=False,
                    server_default="unknown",
                ),
            ),
            (
                "state_contract_version",
                sa.Column(
                    "state_contract_version",
                    sa.String(length=80),
                    nullable=False,
                    server_default="tw.intraday_stock_state.v1",
                ),
            ),
            (
                "decision_usable",
                sa.Column(
                    "decision_usable",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            ),
        ),
    )
    for column_name in (
        "snapshot_as_of",
        "price_as_of",
        "price_semantics",
        "has_actual_trade",
        "session_phase",
        "state_contract_version",
        "decision_usable",
    ):
        _add_index(stock_table, column_name)

    minute_table = "taiwan_market_minute_state"
    _add_columns(
        minute_table,
        (
            (
                "breadth_session_phase",
                sa.Column(
                    "breadth_session_phase",
                    sa.String(length=30),
                    nullable=False,
                    server_default="unknown",
                ),
            ),
            (
                "breadth_contract_version",
                sa.Column(
                    "breadth_contract_version",
                    sa.String(length=80),
                    nullable=False,
                    server_default="legacy_unverified",
                ),
            ),
            (
                "breadth_decision_usable",
                sa.Column(
                    "breadth_decision_usable",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            ),
            (
                "breadth_is_provisional",
                sa.Column(
                    "breadth_is_provisional",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            ),
            (
                "breadth_snapshot_as_of",
                sa.Column("breadth_snapshot_as_of", sa.DateTime(timezone=True), nullable=True),
            ),
            (
                "breadth_oldest_price_as_of",
                sa.Column("breadth_oldest_price_as_of", sa.DateTime(timezone=True), nullable=True),
            ),
            (
                "breadth_newest_price_as_of",
                sa.Column("breadth_newest_price_as_of", sa.DateTime(timezone=True), nullable=True),
            ),
        ),
    )
    for column_name in (
        "breadth_session_phase",
        "breadth_contract_version",
        "breadth_decision_usable",
        "breadth_snapshot_as_of",
    ):
        _add_index(minute_table, column_name)


def downgrade() -> None:
    minute_table = "taiwan_market_minute_state"
    if _has_table(minute_table):
        for column_name in (
            "breadth_snapshot_as_of",
            "breadth_decision_usable",
            "breadth_contract_version",
            "breadth_session_phase",
        ):
            index_name = f"ix_{minute_table}_{column_name}"
            if _has_index(minute_table, index_name):
                op.drop_index(index_name, table_name=minute_table)
        for column_name in (
            "breadth_newest_price_as_of",
            "breadth_oldest_price_as_of",
            "breadth_snapshot_as_of",
            "breadth_is_provisional",
            "breadth_decision_usable",
            "breadth_contract_version",
            "breadth_session_phase",
        ):
            if _has_column(minute_table, column_name):
                op.drop_column(minute_table, column_name)

    stock_table = "taiwan_intraday_stock_state"
    if _has_table(stock_table):
        for column_name in (
            "decision_usable",
            "state_contract_version",
            "session_phase",
            "has_actual_trade",
            "price_semantics",
            "price_as_of",
            "snapshot_as_of",
        ):
            index_name = f"ix_{stock_table}_{column_name}"
            if _has_index(stock_table, index_name):
                op.drop_index(index_name, table_name=stock_table)
        for column_name in (
            "decision_usable",
            "state_contract_version",
            "session_phase",
            "indicative_match_volume_lots",
            "indicative_match_price",
            "indicative_match_available",
            "has_actual_trade",
            "price_source",
            "price_semantics",
            "price_as_of",
            "snapshot_as_of",
        ):
            if _has_column(stock_table, column_name):
                op.drop_column(stock_table, column_name)
