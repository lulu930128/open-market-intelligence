"""Append-only AGENT_SPACE candidates and pending selections, no broker ledger."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0095"
down_revision = "20261030_0094"
branch_labels = None
depends_on = None

TABLES = ("research_candidate_revision", "research_candidate_pending_revision")


def upgrade():
    for table in TABLES:
        op.create_table(table,
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("revision", sa.Integer(), primary_key=True),
            sa.Column("candidate_id", sa.String(64), nullable=False),
            sa.Column("recorded_at", sa.String(40), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.CheckConstraint("revision >= 1", name="ck_" + table + "_revision"),
            sa.UniqueConstraint("id", "revision", name="uq_" + table + "_revision"))
        op.create_index("ix_" + table + "_candidate_id", table, ["candidate_id"])
        if op.get_bind().dialect.name == "sqlite":
            for operation in ("UPDATE", "DELETE"):
                op.execute(sa.text(f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                                  "BEGIN SELECT RAISE(ABORT, 'candidate history is immutable'); END"))
            op.execute(sa.text(f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
                f"WHEN EXISTS(SELECT 1 FROM {table} WHERE id=NEW.id AND revision=NEW.revision) "
                "BEGIN SELECT RAISE(ABORT, 'candidate history is immutable'); END"))


def downgrade():
    for table in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("Candidate history requires retention before downgrade.")
    for table in reversed(TABLES):
        op.drop_table(table)
