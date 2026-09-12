"""Store exchange-published breadth separately from per-stock threshold coverage."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0083"
down_revision = "20260908_0082"
branch_labels = None
depends_on = None
TABLE = "taiwan_published_breadth_snapshot"


def upgrade() -> None:
    if TABLE not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("venue", sa.String(32), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), sa.ForeignKey("raw_fetch_result.id"), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(120), nullable=True),
        )
        op.create_index("ix_tw_published_breadth_date", TABLE, ["venue", "trade_date", "raw_result_id"])


def downgrade() -> None:
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE)
