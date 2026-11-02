"""Retain acquired Taiwan canonical daily revisions without changing current rows."""
from alembic import op
import sqlalchemy as sa

revision = "20261031_0096"
down_revision = "20261030_0095"
branch_labels = None
depends_on = None


def upgrade():
    # Clone the established 0095 row shape; no historical prices are invented or
    # backfilled. The transaction owner retains existing rows on its next write.
    columns = sa.inspect(op.get_bind()).get_columns("market_daily_price")
    op.create_table("market_daily_price_revision", *(
        sa.Column(column["name"], column["type"],
                  primary_key=column["name"] in {"id", "raw_result_id"},
                  nullable=False if column["name"] in {"id", "raw_result_id"}
                  else column["nullable"])
        for column in columns
    ))
    op.create_index("ix_market_daily_revision_source_stock_date",
                    "market_daily_price_revision", ["source_id", "stock_id", "trade_date"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM market_daily_price_revision")).scalar_one():
        raise RuntimeError("Daily revisions require retention before downgrade.")
    op.drop_table("market_daily_price_revision")
