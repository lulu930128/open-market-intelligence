"""Add immutable KR canonical bars without rewriting existing price or identity rows."""

from alembic import op
import sqlalchemy as sa

revision = "20260912_0086"
down_revision = "20260912_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline creates current metadata before later revisions run.
    if not sa.inspect(op.get_bind()).has_table("kr_bar_evidence"):
        op.create_table(
            "kr_bar_evidence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("observation_id", sa.String(128), nullable=False),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("venue", sa.String(32), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("interval", sa.String(16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), sa.ForeignKey("raw_fetch_result.id"), nullable=False),
            sa.Column("observation_json", sa.Text(), nullable=False),
            sa.Column("observation_hash", sa.String(64), nullable=False),
            sa.UniqueConstraint("observation_id", name="uq_kr_bar_evidence_observation"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("kr_bar_evidence")}
    if "ix_kr_bar_evidence_read" not in indexes:
        op.create_index("ix_kr_bar_evidence_read", "kr_bar_evidence",
                        ["symbol", "venue", "interval", "trade_date", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_kr_bar_evidence_read", table_name="kr_bar_evidence")
    op.drop_table("kr_bar_evidence")
