"""add resource market query indexes

Revision ID: 20260703_0029
Revises: 20260701_0028
Create Date: 2026-07-03 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260703_0029"
down_revision: str | Sequence[str] | None = "20260701_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_SPECS: tuple[tuple[str, str, list[str]], ...] = (
    (
        "resource_quote_snapshot",
        "ix_resource_quote_symbol_fetched",
        ["symbol", "fetched_at", "id"],
    ),
    (
        "resource_quote_snapshot",
        "ix_resource_quote_contract_fetched",
        ["provider", "symbol", "instrument_type", "contract_key", "fetched_at", "id"],
    ),
    (
        "resource_ohlcv_bar",
        "ix_resource_ohlcv_symbol_interval_bar_time",
        ["symbol", "interval", "bar_time", "id"],
    ),
    (
        "resource_ohlcv_bar",
        "ix_resource_ohlcv_contract_interval_bar_time",
        ["provider", "symbol", "instrument_type", "contract_key", "interval", "bar_time", "id"],
    ),
    (
        "resource_ohlcv_bar",
        "ix_resource_ohlcv_contract_interval_fetched",
        ["provider", "symbol", "instrument_type", "contract_key", "interval", "fetched_at", "id"],
    ),
    (
        "provider_event",
        "ix_provider_event_market_resource_target_time",
        ["market", "resource", "target", "event_time", "id"],
    ),
    (
        "provider_event",
        "ix_provider_event_market_resource_provider_target_time",
        ["market", "resource", "provider", "target", "event_time", "id"],
    ),
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    for table_name, index_name, columns in INDEX_SPECS:
        if _has_table(table_name) and not _has_index(table_name, index_name):
            op.create_index(op.f(index_name), table_name, columns, unique=False)


def downgrade() -> None:
    for table_name, index_name, _columns in reversed(INDEX_SPECS):
        if _has_table(table_name) and _has_index(table_name, index_name):
            op.drop_index(op.f(index_name), table_name=table_name)
