from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


COPY_TABLES = ("source_registry", "stock_master")


def quote_identifier(value: str) -> str:
    if "\x00" in value:
        raise ValueError("SQLite identifiers cannot contain NUL bytes.")

    return '"' + value.replace('"', '""') + '"'


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def object_exists(connection: sqlite3.Connection, object_type: str, name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = ?
          AND name = ?
        LIMIT 1
        """,
        (object_type, name),
    ).fetchone()
    return row is not None


def table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(
        f"PRAGMA table_info({quote_identifier(table_name)})"
    ).fetchall()
    return [row["name"] for row in rows]


def table_count(connection: sqlite3.Connection, table_name: str) -> int:
    if not object_exists(connection, "table", table_name):
        return 0

    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
        ).fetchone()[0]
    )


def ensure_schema(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    rows = source.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type
            WHEN 'table' THEN 0
            WHEN 'view' THEN 1
            WHEN 'index' THEN 2
            WHEN 'trigger' THEN 3
            ELSE 4
        END, name
        """
    ).fetchall()

    for row in rows:
        object_type = row["type"]
        name = row["name"]

        if object_exists(target, object_type, name):
            continue

        target.execute(row["sql"])

    target.commit()


def copy_table_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table_name: str,
    *,
    insert_or_ignore: bool,
) -> int:
    source_columns = table_columns(source, table_name)
    target_columns = table_columns(target, table_name)

    if not source_columns:
        raise RuntimeError(f"Source table is missing or empty schema: {table_name}")

    missing_columns = [column for column in source_columns if column not in target_columns]
    if missing_columns:
        raise RuntimeError(
            f"Target table {table_name} is missing columns: {', '.join(missing_columns)}"
        )

    column_list = ", ".join(quote_identifier(column) for column in source_columns)
    placeholders = ", ".join("?" for _ in source_columns)
    insert_verb = "INSERT OR IGNORE" if insert_or_ignore else "INSERT"
    insert_sql = (
        f"{insert_verb} INTO {quote_identifier(table_name)} "
        f"({column_list}) VALUES ({placeholders})"
    )
    select_sql = f"SELECT {column_list} FROM {quote_identifier(table_name)}"

    before_count = table_count(target, table_name)
    batch: list[tuple[object, ...]] = []

    for row in source.execute(select_sql):
        batch.append(tuple(row[column] for column in source_columns))

        if len(batch) >= 1000:
            target.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        target.executemany(insert_sql, batch)

    target.commit()
    return table_count(target, table_name) - before_count


def validate_stock_master(
    connection: sqlite3.Connection,
    *,
    require_stock: str | None,
) -> int:
    stock_count = table_count(connection, "stock_master")
    if stock_count <= 0:
        raise RuntimeError("stock_master seed is empty.")

    if require_stock:
        row = connection.execute(
            """
            SELECT 1
            FROM stock_master
            WHERE stock_id = ?
            LIMIT 1
            """,
            (require_stock,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Required stock_id={require_stock!r} was not found in stock_master."
            )

    return stock_count


def create_seed(source_db: Path, target_db: Path, require_stock: str | None) -> None:
    if not source_db.exists():
        raise FileNotFoundError(f"Source database was not found: {source_db}")

    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()

    with connect(source_db) as source, connect(target_db) as target:
        ensure_schema(source, target)

        copied_counts = {
            table_name: copy_table_rows(
                source,
                target,
                table_name,
                insert_or_ignore=False,
            )
            for table_name in COPY_TABLES
        }
        stock_count = validate_stock_master(target, require_stock=require_stock)
        target.execute("VACUUM")

    print(
        "Created stock master seed: "
        f"target={target_db} "
        f"stock_master_rows={stock_count} "
        f"copied={copied_counts}"
    )


def apply_seed(seed_db: Path, target_db: Path, require_stock: str | None) -> None:
    if not seed_db.exists():
        raise FileNotFoundError(f"Seed database was not found: {seed_db}")

    seed_path = seed_db.resolve()
    target_path = target_db.resolve()

    if seed_path == target_path:
        with connect(target_path) as target:
            stock_count = validate_stock_master(target, require_stock=require_stock)
        print(f"Seed target is already initialized: stock_master_rows={stock_count}")
        return

    target_db.parent.mkdir(parents=True, exist_ok=True)

    if not target_db.exists():
        shutil.copyfile(seed_db, target_db)
        with connect(target_db) as target:
            stock_count = validate_stock_master(target, require_stock=require_stock)
        print(f"Copied seed database: target={target_db} stock_master_rows={stock_count}")
        return

    with connect(seed_db) as seed, connect(target_db) as target:
        validate_stock_master(seed, require_stock=require_stock)
        ensure_schema(seed, target)

        copied_counts = {
            table_name: copy_table_rows(
                seed,
                target,
                table_name,
                insert_or_ignore=True,
            )
            for table_name in COPY_TABLES
        }
        stock_count = validate_stock_master(target, require_stock=require_stock)

    print(
        "Applied stock master seed: "
        f"target={target_db} "
        f"stock_master_rows={stock_count} "
        f"inserted={copied_counts}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or apply a lightweight stock_master seed database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--source-db", required=True, type=Path)
    create_parser.add_argument("--target-db", required=True, type=Path)
    create_parser.add_argument("--require-stock")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--seed-db", required=True, type=Path)
    apply_parser.add_argument("--target-db", required=True, type=Path)
    apply_parser.add_argument("--require-stock")

    args = parser.parse_args()

    if args.command == "create":
        create_seed(
            source_db=args.source_db,
            target_db=args.target_db,
            require_stock=args.require_stock,
        )
        return

    apply_seed(
        seed_db=args.seed_db,
        target_db=args.target_db,
        require_stock=args.require_stock,
    )


if __name__ == "__main__":
    main()
