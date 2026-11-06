"""Durable US observation ordering without changing materialized provenance."""

from alembic import op
import sqlalchemy as sa


revision = "20261104_0099"
down_revision = "20261101_0098"
branch_labels = None
depends_on = None

TABLE = "us_intraday_observation_state"
TRIGGER = "tr_us_intraday_observation_state_bar_delete"


def upgrade() -> None:
    bind = op.get_bind()
    # The historical baseline uses current metadata on a brand-new database.
    if TABLE not in sa.inspect(bind).get_table_names():
        op.create_table(
            TABLE,
            sa.Column("bar_id", sa.Integer(), sa.ForeignKey("market_intraday_bar.id", ondelete="CASCADE"),
                      primary_key=True, autoincrement=False),
            sa.Column("observed_fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("observed_content_hash", sa.String(128), nullable=False),
        )
    if bind.dialect.name == "sqlite":
        # Scoped lifecycle cleanup works even when SQLite foreign_keys is OFF.
        op.execute(f"CREATE TRIGGER {TRIGGER} AFTER DELETE ON market_intraday_bar "
                   f"BEGIN DELETE FROM {TABLE} WHERE bar_id = OLD.id; END")


def downgrade() -> None:
    # Destructive to observation evidence; source rollback should retain this
    # additive schema. No canonical/raw rows or existing triggers are changed.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    op.drop_table(TABLE)
