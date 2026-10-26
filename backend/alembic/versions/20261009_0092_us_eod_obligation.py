"""One durable US completed-session obligation per canonical target."""

from alembic import op
import sqlalchemy as sa
import re

revision = "20261009_0092"
down_revision = "20261006_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("US EOD durable admission currently requires SQLite")
    # The empty-DB baseline uses current metadata and may already create this
    # canonical index. Never treat name equality as definition equality.
    existing = bind.execute(sa.text(
        "SELECT type,tbl_name,sql FROM sqlite_master WHERE name=:name"
    ), {"name": "uq_job_run_us_eod_obligation"}).fetchall()
    if existing:
        def normalized(sql):
            value = sql or ""
            for name in ("uq_job_run_us_eod_obligation", "job_run", "job_type", "target"):
                value = value.replace('"' + name + '"', name)
            return re.sub(r"\s+", " ", value).strip()
        expected = ("CREATE UNIQUE INDEX uq_job_run_us_eod_obligation ON job_run "
                    "(job_type, target) WHERE job_type = 'us.intraday_eod_obligation'")
        if (len(existing) != 1 or existing[0][0:2] != ("index", "job_run") or
                normalized(existing[0][2]) != expected):
            raise RuntimeError("US_EOD_OBLIGATION_INDEX_DEFINITION_MISMATCH")
        return
    op.create_index(
        "uq_job_run_us_eod_obligation", "job_run", ["job_type", "target"],
        unique=True, sqlite_where=sa.text("job_type = 'us.intraday_eod_obligation'"),
    )


def downgrade() -> None:
    op.drop_index("uq_job_run_us_eod_obligation", table_name="job_run")
