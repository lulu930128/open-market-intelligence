"""Persist nullable Taiwan breadth limit coverage and classification diagnostics."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0082"
down_revision = "20260908_0081"
branch_labels = None
depends_on = None

TABLE = "taiwan_current_breadth_snapshot"
COLUMNS = ("limits_json", "classification_diagnostics_json", "price_states_json")


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    for name in COLUMNS:
        if name not in columns:
            op.add_column(TABLE, sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        for name in reversed(COLUMNS):
            if name in columns:
                batch.drop_column(name)
