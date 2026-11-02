"""Add an immutable research-only trade proposal journal; no execution tables."""
from alembic import op
import sqlalchemy as sa


revision = "20261030_0094"
down_revision = "20261025_0093"
branch_labels = None
depends_on = None

TABLE = "research_trade_proposal_version"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("revision_id", sa.String(36), primary_key=True),
        sa.Column("creation_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes", sa.String(36), unique=True),
        sa.Column("recorded_at", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("creation_id", "revision", name="uq_research_proposal_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_research_proposal_revision"),
        sa.ForeignKeyConstraint(["supersedes"], [TABLE + ".revision_id"]),
    )
    if op.get_bind().dialect.name == "sqlite":
        # SQLite REPLACE may bypass DELETE triggers when recursive_triggers is
        # off. Reject conflicting inserts before REPLACE can remove history.
        op.execute(sa.text(
            f"CREATE TRIGGER research_proposal_no_replace BEFORE INSERT ON {TABLE} "
            f"WHEN EXISTS (SELECT 1 FROM {TABLE} WHERE revision_id=NEW.revision_id "
            "OR (creation_id=NEW.creation_id AND revision=NEW.revision) "
            "OR (supersedes IS NOT NULL AND supersedes=NEW.supersedes)) "
            "BEGIN SELECT RAISE(ABORT, 'research proposal versions are immutable'); END"
        ))
        for operation in ("UPDATE", "DELETE"):
            op.execute(sa.text(
                f"CREATE TRIGGER research_proposal_no_{operation.lower()} BEFORE {operation} ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'research proposal versions are immutable'); END"
            ))


def downgrade() -> None:
    # Research history is evidence. An occupied journal must never be discarded.
    if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one():
        raise RuntimeError("Research journal downgrade requires an explicit data retention plan.")
    op.drop_table(TABLE)
