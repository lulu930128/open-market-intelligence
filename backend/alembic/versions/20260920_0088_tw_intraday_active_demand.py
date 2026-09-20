"""Deduplicate active single-instrument Taiwan consumer demands only."""

from alembic import op
import sqlalchemy as sa

revision = "20260920_0088"
down_revision = "20260914_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Consumer-demand admission is SQLite-only. Other dialects must not turn
    # sqlite_where into an unconditional unique constraint on legacy jobs.
    if bind.dialect.name != "sqlite":
        return
    # The baseline creates current metadata, including this index, on a fresh DB.
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("job_run")}
    if "uq_job_run_tw_intraday_active_demand" in indexes:
        return
    op.create_index(
        "uq_job_run_tw_intraday_active_demand", "job_run",
        ["job_type", "target"], unique=True,
        sqlite_where=sa.text(
            "job_type = 'tw.bootstrap_intraday_base_1m' "
            "AND substr(target, 1, 10) = 'tw-demand:' "
            "AND status IN ('queued', 'running')"
        ),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.drop_index("uq_job_run_tw_intraday_active_demand", table_name="job_run")
