"""Bound stock/date PIT history reads without altering market observations."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0101"
down_revision = "20261106_0100"
branch_labels = None
depends_on = None

INDEXES = (
    ("market_daily_price", "ix_market_daily_stock_date_read"),
    ("market_daily_price_revision", "ix_market_daily_revision_stock_date_read"),
)


def upgrade() -> None:
    for table, name in INDEXES:
        existing = {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if name in existing:
            if existing[name]["column_names"] != ["stock_id", "trade_date"]:
                raise RuntimeError(f"Unexpected existing index definition: {name}")
        else:
            op.create_index(name, table, ["stock_id", "trade_date"], unique=False)


def downgrade() -> None:
    for table, name in reversed(INDEXES):
        op.drop_index(name, table_name=table)
