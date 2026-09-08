"""Persist independent indicative breadth and acquisition diagnostics.

Revision ID: 20260908_0081
Revises: 20260904_0080
"""
from alembic import op
import sqlalchemy as sa

revision = "20260908_0081"
down_revision = "20260904_0080"
branch_labels = None
depends_on = None

TABLE = "taiwan_current_breadth_snapshot"
COLUMNS = ("auction_observation_json", "acquisition_diagnostics_json")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    existing = {column["name"] for column in inspector.get_columns(TABLE)}
    for name in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    existing = {column["name"] for column in inspector.get_columns(TABLE)}
    for name in reversed(COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
