"""One durable US completed-session obligation per canonical target."""

from alembic import op
import sqlalchemy as sa

revision = "20261009_0092"
down_revision = "20261006_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        raise RuntimeError("US EOD durable admission currently requires SQLite")
    op.create_index(
        "uq_job_run_us_eod_obligation", "job_run", ["job_type", "target"],
        unique=True, sqlite_where=sa.text("job_type = 'us.intraday_eod_obligation'"),
    )


def downgrade() -> None:
    op.drop_index("uq_job_run_us_eod_obligation", table_name="job_run")
