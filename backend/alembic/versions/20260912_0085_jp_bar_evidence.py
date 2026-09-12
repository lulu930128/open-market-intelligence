"""Add immutable JP canonical bar evidence without changing legacy rows."""

from alembic import op
import sqlalchemy as sa

revision = "20260912_0085"
down_revision = "20260912_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("jp_bar_evidence"):
        op.create_table(
            "jp_bar_evidence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("observation_id", sa.String(128), nullable=False),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("venue", sa.String(32), nullable=False),
            sa.Column("instrument_type", sa.String(24), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("interval", sa.String(16), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("price_basis", sa.String(24), nullable=False),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("raw_result_id", sa.Integer(), sa.ForeignKey("raw_fetch_result.id"), nullable=False),
            sa.Column("observation_json", sa.Text(), nullable=False),
            sa.UniqueConstraint("observation_id", name="uq_jp_bar_evidence_observation"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("jp_bar_evidence")}
    if "ix_jp_bar_evidence_read" not in indexes:
        op.create_index("ix_jp_bar_evidence_read", "jp_bar_evidence", ["symbol", "venue", "interval", "trade_date", "available_at"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("jp_bar_evidence"):
        op.drop_table("jp_bar_evidence")
