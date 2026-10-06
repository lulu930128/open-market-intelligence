"""Write-owned intraday generation on the existing Taiwan revision owner."""

from alembic import op
import sqlalchemy as sa

revision = "20261006_0091"
down_revision = "20260922_0090"
branch_labels = None
depends_on = None

# Frozen persistence dependencies. OLD and NEW both invalidate reassigned rows.
DEPENDENCIES = {
    "market_intraday_bar": lambda ref: f"SELECT {ref}.stock_id AS stock_id",
    "market_intraday_bar_lineage": lambda ref: f"SELECT stock_id FROM market_intraday_bar WHERE id = {ref}.bar_id",
    "stock_master": lambda ref: f"SELECT {ref}.stock_id AS stock_id",
    "raw_fetch_result": lambda ref: f"SELECT DISTINCT b.stock_id FROM market_intraday_bar b JOIN market_intraday_bar_lineage l ON l.bar_id = b.id WHERE l.raw_result_id = {ref}.id",
    "source_registry": lambda ref: f"SELECT DISTINCT stock_id FROM market_intraday_bar WHERE source_id = {ref}.id",
}


def upgrade() -> None:
    bind = op.get_bind()
    if "intraday_generation" not in {c["name"] for c in sa.inspect(bind).get_columns("taiwan_technical_input_revision")}:
        op.add_column("taiwan_technical_input_revision", sa.Column("intraday_generation", sa.BigInteger(), nullable=False, server_default="0"))
    for table, symbols in DEPENDENCIES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            if table in {"raw_fetch_result", "source_registry"} and event == "INSERT":
                continue
            name = f"tr_tw_intraday_revision_{table}_{event.lower()}"
            refs = ("OLD", "NEW") if event == "UPDATE" else (("OLD",) if event == "DELETE" else ("NEW",))
            body = "\n".join(
                "INSERT INTO taiwan_technical_input_revision (stock_id, generation, intraday_generation) "
                f"SELECT stock_id, 0, 1 FROM ({symbols(ref)}) AS symbols WHERE stock_id IS NOT NULL "
                "ON CONFLICT (stock_id) DO UPDATE SET intraday_generation = taiwan_technical_input_revision.intraday_generation + 1;"
                for ref in refs
            )
            if bind.dialect.name == "sqlite":
                op.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} BEGIN {body} END")
            elif bind.dialect.name == "postgresql":
                op.execute(f"CREATE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} RETURN NULL; END $$")
                op.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_fn()")
            else:
                raise RuntimeError("Intraday revisions require SQLite or PostgreSQL")


def downgrade() -> None:
    bind = op.get_bind()
    for table in DEPENDENCIES:
        for event in ("insert", "update", "delete"):
            name = f"tr_tw_intraday_revision_{table}_{event}"
            if bind.dialect.name == "sqlite":
                op.execute(f"DROP TRIGGER IF EXISTS {name}")
            else:
                op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                op.execute(f"DROP FUNCTION IF EXISTS {name}_fn()")
    op.drop_column("taiwan_technical_input_revision", "intraday_generation")
