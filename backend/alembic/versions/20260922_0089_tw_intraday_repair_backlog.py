"""Separate durable Taiwan intraday repair obligations from acquisition jobs."""
import json
from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "20260922_0089"
down_revision = "20260920_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("tw_intraday_scheduler_state"):
        op.create_table("tw_intraday_scheduler_state",
            sa.Column("key", sa.String(160), primary_key=True),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    if not sa.inspect(bind).has_table("tw_intraday_repair_item"):
        op.create_table("tw_intraday_repair_item",
            sa.Column("trade_date", sa.Date(), primary_key=True),
            sa.Column("stock_id", sa.String(20), primary_key=True),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("last_job_id", sa.Integer(), nullable=True),
            sa.Column("last_reason", sa.String(160), nullable=True),
            sa.Column("coverage_json", sa.Text(), nullable=False),
            sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('pending','active','complete','unfillable','not_applicable')",
                               name="ck_tw_intraday_repair_status"))
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("tw_intraday_repair_item")}
    if "ix_tw_intraday_repair_due" not in indexes:
        op.create_index("ix_tw_intraday_repair_due", "tw_intraday_repair_item",
                        ["trade_date", "status", "next_check_at"])
    # Old aggregate counts cannot reconstruct missing symbols, and excluded
    # uppercase ETFs. Re-scan each recorded date without erasing stored bars.
    state = sa.table("tw_intraday_scheduler_state", sa.column("key", sa.String()),
                     sa.column("state_json", sa.Text()), sa.column("revision", sa.Integer()),
                     sa.column("updated_at", sa.DateTime(timezone=True)))
    rows = bind.execute(sa.text("SELECT id,target,result_json FROM job_run WHERE "
        "job_type='tw.bootstrap_intraday_base_1m' AND "
        "(target LIKE 'tw-coverage-audit:%' OR target LIKE 'tw-cadence:%')")).mappings()
    for row in rows:
        key = row["target"]
        if bind.execute(sa.select(state.c.key).where(state.c.key == key)).first():
            continue
        if key.startswith("tw-coverage-audit:"):
            try:
                target = date.fromisoformat(key.rsplit(":", 1)[1])
            except ValueError:
                continue
            payload = {"trade_date": target.isoformat(), "scan_cursor": "",
                       "coverage_scan_complete": False, "legacy_checkpoint_id": row["id"]}
        else:
            try:
                payload = json.loads(row["result_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
        bind.execute(state.insert().values(key=key, state_json=json.dumps(payload),
            revision=0, updated_at=datetime.now(timezone.utc)))
    bind.execute(sa.text("UPDATE job_run SET job_type='tw.intraday.scheduler_checkpoint' WHERE "
        "job_type='tw.bootstrap_intraday_base_1m' AND (target LIKE 'tw-coverage-audit:%' "
        "OR target LIKE 'tw-cadence:%' OR target='tw-coverage-repair-cursor')"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE job_run SET job_type='tw.bootstrap_intraday_base_1m' "
        "WHERE job_type='tw.intraday.scheduler_checkpoint' AND (target LIKE 'tw-coverage-audit:%' "
        "OR target LIKE 'tw-cadence:%' OR target='tw-coverage-repair-cursor')"))
    op.drop_table("tw_intraday_repair_item")
    op.drop_table("tw_intraday_scheduler_state")
