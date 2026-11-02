"""Invalidate Taiwan technical inputs on source semantics, not health timestamps."""
from alembic import op

revision = "20261101_0097"
down_revision = "20261031_0096"
branch_labels = None
depends_on = None

# Frozen fields consumed by the official daily candidate/lineage reader.
SOURCE_FIELDS = ("id", "source_name", "priority", "reliability_level", "parser_type")
TRIGGER = "tr_tw_technical_source_registry_update"
BODY = "\n".join(
    "INSERT INTO taiwan_technical_input_revision (stock_id, generation) "
    f"SELECT DISTINCT stock_id, 1 FROM market_daily_price WHERE source_id = {ref}.id "
    "ON CONFLICT (stock_id) DO UPDATE SET generation = taiwan_technical_input_revision.generation + 1;"
    for ref in ("OLD", "NEW")
)


def _install(*, filtered: bool):
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
        condition = " WHEN " + " OR ".join(f"OLD.{field} IS NOT NEW.{field}" for field in SOURCE_FIELDS) if filtered else ""
        op.execute(f"CREATE TRIGGER {TRIGGER} AFTER UPDATE ON source_registry{condition} BEGIN {BODY} END")
    elif dialect == "postgresql":
        condition = "IF " + " OR ".join(f"OLD.{field} IS DISTINCT FROM NEW.{field}" for field in SOURCE_FIELDS) + " THEN " if filtered else ""
        end = " END IF;" if filtered else ""
        op.execute(f"CREATE OR REPLACE FUNCTION {TRIGGER}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {condition}{BODY}{end} RETURN NULL; END $$")
        op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON source_registry")
        op.execute(f"CREATE TRIGGER {TRIGGER} AFTER UPDATE ON source_registry FOR EACH ROW EXECUTE FUNCTION {TRIGGER}_fn()")
    else:
        raise RuntimeError("Technical snapshot revisions require SQLite or PostgreSQL")


def upgrade():
    _install(filtered=True)


def downgrade():
    _install(filtered=False)
