"""Preserve fractional canonical US shares without altering legacy integers."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_0093"
down_revision = "20261009_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The repository's baseline creates current metadata on an empty database.
    if "trade_volume_decimal" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("us_daily_price")}:
        op.add_column("us_daily_price", sa.Column("trade_volume_decimal", sa.String(64), nullable=True))


def downgrade() -> None:
    # Do not silently lose fractions or values outside the legacy integer range.
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM us_daily_price WHERE trade_volume_decimal IS NOT NULL AND trade_volume IS NULL"
    )).scalar_one()
    if count:
        raise RuntimeError("Exact US volume downgrade requires an explicit data retention plan")
    op.drop_column("us_daily_price", "trade_volume_decimal")
