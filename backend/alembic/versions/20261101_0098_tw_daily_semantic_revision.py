"""Invalidate technical inputs on semantics, retaining every receipt/PIT row."""
from alembic import op

revision = "20261101_0098"
down_revision = "20261101_0097"
branch_labels = None
depends_on = None

# Frozen persisted dependencies, not a second provider/dataset inventory.
DAILY_FIELDS = (
    "id", "source_id", "stock_id", "trade_date", "stock_name", "canonical_market", "venue",
    "instrument_type", "trade_volume", "trade_value", "open_price", "high_price", "low_price",
    "close_price", "price_change", "transaction_count", "authority", "finalization", "official",
    "release_status", "reconciliation_status", "derivation_kind", "aggregation_version",
)
LINEAGE_FIELDS = (
    "daily_price_id", "evidence_kind", "source_interval", "materialization_version",
    "component_raw_result_ids_json", "component_content_hashes_json",
)
STOCK_FIELDS = (
    "id", "stock_id", "stock_name", "market", "instrument_type", "industry", "category",
    "is_active", "notes", "first_seen_at",
)
TABLES = ("market_daily_price", "market_daily_price_lineage", "stock_master")


def _different(left, right, dialect):
    return f"{left} IS NOT {right}" if dialect == "sqlite" else f"{left} IS DISTINCT FROM {right}"


def _equivalent_receipts(dialect, *, lineage=False):
    # Receipt ID/time and the whole-venue payload hash are audit identity. Only
    # qualified acquired receipts may be rebound without invalidating geometry.
    # In-place Raw mutations still use the existing unconditional Raw triggers.
    if lineage:
        day, source, instrument_type = "p.trade_date", "p.source_id", "p.instrument_type"
        price_join = " JOIN market_daily_price p ON p.id = NEW.daily_price_id"
        acquired = " AND OLD.evidence_kind = 'acquired' AND NEW.evidence_kind = 'acquired'"
    else:
        day, source, instrument_type = "NEW.trade_date", "NEW.source_id", "NEW.instrument_type"
        price_join, acquired = "", ""
    release_time = f"CASE WHEN {instrument_type} = 'index' THEN '05:35:00' ELSE '07:15:00' END"
    if dialect == "sqlite":
        released = lambda ref: f"(date({ref}.fetched_at) > date({day}) OR (date({ref}.fetched_at) = date({day}) AND time({ref}.fetched_at) >= {release_time}))"
    else:
        released = lambda ref: f"{ref}.fetched_at >= ((CAST({day} AS date) + CAST(({release_time}) AS time)) AT TIME ZONE 'UTC')"
    return ("EXISTS (SELECT 1 FROM raw_fetch_result a JOIN raw_fetch_result b ON b.id = NEW.raw_result_id"
        f"{price_join} WHERE a.id = OLD.raw_result_id AND a.source_id = {source} AND b.source_id = a.source_id"
        " AND a.status_code = 200 AND b.status_code = 200 AND a.error_message IS NULL AND b.error_message IS NULL"
        " AND a.parser_version IS NOT NULL AND a.parser_version <> '' AND a.parser_version = b.parser_version"
        " AND a.content_hash IS NOT NULL AND a.content_hash <> '' AND b.content_hash IS NOT NULL AND b.content_hash <> ''"
        f" AND {released('a')} AND {released('b')}{acquired})")


def _condition(table, dialect):
    if table == "stock_master":
        return " OR ".join(_different(f"OLD.{field}", f"NEW.{field}", dialect) for field in STOCK_FIELDS)
    fields = DAILY_FIELDS if table == "market_daily_price" else LINEAGE_FIELDS
    changes = [_different(f"OLD.{field}", f"NEW.{field}", dialect) for field in fields]
    equivalent = _equivalent_receipts(dialect, lineage=table == "market_daily_price_lineage")
    changes.append(f"({_different('OLD.raw_result_id', 'NEW.raw_result_id', dialect)} AND NOT {equivalent})")
    if table == "market_daily_price_lineage":
        # Acquired digest follows the Raw hash, which can change when another
        # symbol in the venue payload changes. Arbitrary lineage corrections
        # and all materialized lineage/digest changes remain invalidating.
        digest_rebind = (f"({_different('OLD.raw_result_id', 'NEW.raw_result_id', dialect)} AND {equivalent}"
            " AND EXISTS (SELECT 1 FROM raw_fetch_result a JOIN raw_fetch_result b ON b.id = NEW.raw_result_id"
            " WHERE a.id = OLD.raw_result_id AND a.content_hash = OLD.lineage_digest AND b.content_hash = NEW.lineage_digest))")
        changes.append(f"({_different('OLD.lineage_digest', 'NEW.lineage_digest', dialect)} AND NOT {digest_rebind})")
    return " OR ".join(changes)


def _install(*, filtered):
    dialect = op.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("Technical snapshot revisions require SQLite or PostgreSQL")
    for table in TABLES:
        name = f"tr_tw_technical_{table}_update"
        symbols = (lambda ref: f"SELECT {ref}.stock_id AS stock_id") if table != "market_daily_price_lineage" else (
            lambda ref: f"SELECT stock_id FROM market_daily_price WHERE id = {ref}.daily_price_id")
        body = "\n".join(
            "INSERT INTO taiwan_technical_input_revision (stock_id, generation) "
            f"SELECT stock_id, 1 FROM ({symbols(ref)}) AS symbols WHERE stock_id IS NOT NULL "
            "ON CONFLICT (stock_id) DO UPDATE SET generation = taiwan_technical_input_revision.generation + 1;"
            for ref in ("OLD", "NEW"))
        if dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
            when = f" WHEN {_condition(table, dialect)}" if filtered else ""
            op.execute(f"CREATE TRIGGER {name} AFTER UPDATE ON {table}{when} BEGIN {body} END")
        else:
            condition = f"IF {_condition(table, dialect)} THEN " if filtered else ""
            end = " END IF;" if filtered else ""
            op.execute(f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {condition}{body}{end} RETURN NULL; END $$")
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            op.execute(f"CREATE TRIGGER {name} AFTER UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_fn()")


def upgrade():
    _install(filtered=True)


def downgrade():
    # Restore 0087 behavior without deleting Raw, prices, PIT, revisions or headers.
    _install(filtered=False)
