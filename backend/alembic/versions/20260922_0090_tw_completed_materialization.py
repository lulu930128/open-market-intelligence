"""Keep normal completed-session admission separate from residual recovery."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0090"
down_revision = "20260922_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tw_intraday_repair_item")}
    for column in (
        sa.Column("acquisition_lane", sa.String(16), nullable=False, server_default="repair"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normal_attempted_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("tw_intraday_repair_item", column)
    # The coordinator freezes each existing date before classifying untouched
    # legacy discovery rows. Tried/active recovery episodes retain their lane.


def downgrade() -> None:
    with op.batch_alter_table("tw_intraday_repair_item") as batch:
        batch.drop_column("normal_attempted_at")
        batch.drop_column("scanned_at")
        batch.drop_column("acquisition_lane")
