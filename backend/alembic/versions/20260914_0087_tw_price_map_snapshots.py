"""Revisioned Taiwan technical snapshots; no historical market rows are rewritten."""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0087"
down_revision = "20260912_0086"
branch_labels = None
depends_on = None

# Frozen migration inventory, not a provider/capability inventory.
DEPENDENCIES = {
    "stock_master": lambda ref: f"SELECT {ref}.stock_id",
    "market_daily_price": lambda ref: f"SELECT {ref}.stock_id",
    "market_daily_price_lineage": lambda ref: f"SELECT stock_id FROM market_daily_price WHERE id = {ref}.daily_price_id",
    "market_daily_price_reconciliation": lambda ref: f"SELECT stock_id FROM market_daily_price WHERE id = {ref}.daily_price_id",
    "raw_fetch_result": lambda ref: f"SELECT DISTINCT stock_id FROM market_daily_price WHERE raw_result_id = {ref}.id",
    "source_registry": lambda ref: f"SELECT DISTINCT stock_id FROM market_daily_price WHERE source_id = {ref}.id",
}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("taiwan_technical_input_revision"):
        op.create_table(
            "taiwan_technical_input_revision",
            sa.Column("stock_id", sa.String(20), primary_key=True),
            sa.Column("generation", sa.BigInteger(), nullable=False),
        )
    if not sa.inspect(bind).has_table("taiwan_price_map_snapshot"):
        op.create_table(
            "taiwan_price_map_snapshot",
            sa.Column("stock_id", sa.String(20), primary_key=True),
            sa.Column("timeframe", sa.String(16), primary_key=True),
            sa.Column("claim_token", sa.String(64), nullable=False),
            sa.Column("input_revision", sa.BigInteger(), nullable=False),
            sa.Column("parameter_revision", sa.String(64), nullable=False),
            sa.Column("corporate_revision", sa.String(64), nullable=False),
            sa.Column("methodology_version", sa.String(32), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("basis_date", sa.Date(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("retry_after", sa.DateTime(timezone=True)),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("error_code", sa.String(120)),
            sa.Column("payload_json", sa.Text()),
        )
    for table, select_symbols in DEPENDENCIES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            # Receipts are immutable on insert; the later daily insert records it.
            if table in {"raw_fetch_result", "source_registry"} and event == "INSERT":
                continue
            name = f"tr_tw_technical_{table}_{event.lower()}"
            refs = ("OLD", "NEW") if event == "UPDATE" else (("OLD",) if event == "DELETE" else ("NEW",))
            statements = []
            for ref in refs:
                statements.append(
                    "INSERT INTO taiwan_technical_input_revision (stock_id, generation) "
                    f"SELECT stock_id, 1 FROM ({select_symbols(ref)}) AS symbols WHERE stock_id IS NOT NULL "
                    "ON CONFLICT (stock_id) DO UPDATE SET generation = taiwan_technical_input_revision.generation + 1;"
                )
            # SELECT NEW.stock_id needs a named column on SQLite and PostgreSQL.
            body = "\n".join(statements).replace("SELECT NEW.stock_id)", "SELECT NEW.stock_id AS stock_id)").replace("SELECT OLD.stock_id)", "SELECT OLD.stock_id AS stock_id)")
            if bind.dialect.name == "sqlite":
                op.execute(f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} ON {table} BEGIN {body} END")
            elif bind.dialect.name == "postgresql":
                op.execute(f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} RETURN NULL; END $$")
                op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                op.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_fn()")
            else:
                raise RuntimeError("Technical snapshot revisions require SQLite or PostgreSQL")


def downgrade() -> None:
    bind = op.get_bind()
    for table in DEPENDENCIES:
        for event in ("insert", "update", "delete"):
            name = f"tr_tw_technical_{table}_{event}"
            if bind.dialect.name == "sqlite":
                op.execute(f"DROP TRIGGER IF EXISTS {name}")
            else:
                op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                op.execute(f"DROP FUNCTION IF EXISTS {name}_fn()")
    op.drop_table("taiwan_price_map_snapshot")
    op.drop_table("taiwan_technical_input_revision")
