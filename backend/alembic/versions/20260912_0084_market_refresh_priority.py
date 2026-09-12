"""Persist bounded foreground demand for the shared market repair scheduler."""

from alembic import op
import sqlalchemy as sa

revision = "20260912_0084"
down_revision = "20260908_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline bootstraps current metadata, so fresh databases may already
    # contain this table before Alembic reaches this revision.
    if not sa.inspect(op.get_bind()).has_table("market_refresh_priority"):
        op.create_table(
            "market_refresh_priority",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("market", sa.String(8), nullable=False),
            sa.Column("venue", sa.String(32), nullable=False),
            sa.Column("symbol", sa.String(40), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("market", "venue", "symbol", name="uq_market_refresh_priority_identity"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("market_refresh_priority")}
    if "ix_market_refresh_priority_expiry" not in indexes:
        op.create_index("ix_market_refresh_priority_expiry", "market_refresh_priority", ["market", "expires_at"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("market_refresh_priority"):
        op.drop_table("market_refresh_priority")
