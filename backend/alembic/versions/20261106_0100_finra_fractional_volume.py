"""Preserve FINRA fractional share quantities without rounding legacy rows."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0100"
down_revision = "20261104_0099"
branch_labels = None
depends_on = None

TABLE = "us_short_volume_daily"
COLUMNS = ("short_volume", "short_exempt_volume", "total_volume")


def upgrade() -> None:
    # Fresh-database baseline already uses current model metadata.
    columns = {item["name"]: item for item in sa.inspect(op.get_bind()).get_columns(TABLE)}
    changes = [name for name in COLUMNS if not (
        isinstance(columns[name]["type"], sa.Numeric) and columns[name]["type"].scale == 6
    )]
    if changes:
        with op.batch_alter_table(TABLE) as batch:
            for name in changes:
                batch.alter_column(name, existing_type=columns[name]["type"],
                                   type_=sa.Numeric(24, 6), existing_nullable=True)


def downgrade() -> None:
    # Rounding fractional evidence is not an acceptable source rollback.
    bind = op.get_bind()
    for name in COLUMNS:
        fractional = bind.execute(sa.text(
            f"SELECT 1 FROM {TABLE} WHERE {name} IS NOT NULL "
            f"AND {name} != CAST({name} AS BIGINT) LIMIT 1"
        )).first()
        if fractional:
            raise RuntimeError("FINRA fractional evidence exists; retain the schema on source rollback.")
    with op.batch_alter_table(TABLE) as batch:
        for name in COLUMNS:
            batch.alter_column(name, existing_type=sa.Numeric(24, 6),
                               type_=sa.BigInteger(), existing_nullable=True)
