from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import utc_now


DEFAULT_MIN_RAW_CHARS = 10_000
DEFAULT_BATCH_SIZE = 500


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _sqlite_database_path() -> Path | None:
    try:
        url = make_url(settings.database_url)
    except Exception:
        return None
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def backup_sqlite_database(*, suffix: str = "resource-ohlcv-raw-compact") -> Path:
    database_path = _sqlite_database_path()
    if database_path is None:
        raise RuntimeError("Resource OHLCV compaction backup only supports file-backed SQLite.")
    if not database_path.exists():
        raise RuntimeError(f"SQLite database was not found: {database_path}")

    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{database_path.stem}-{suffix}-{timestamp}{database_path.suffix}"

    source = sqlite3.connect(str(database_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def vacuum_sqlite_database() -> None:
    database_path = _sqlite_database_path()
    if database_path is None:
        raise RuntimeError("Resource OHLCV compaction VACUUM only supports file-backed SQLite.")
    if not database_path.exists():
        raise RuntimeError(f"SQLite database was not found: {database_path}")

    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute("VACUUM")
    finally:
        connection.close()


def compact_resource_ohlcv_raw_payloads(
    db: Session,
    *,
    apply: bool = False,
    min_raw_chars: int = DEFAULT_MIN_RAW_CHARS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
) -> dict[str, Any]:
    min_raw_chars = max(int(min_raw_chars), 1)
    batch_size = max(int(batch_size), 1)
    compacted_at = utc_now()
    total_candidates = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM resource_ohlcv_bar
                WHERE LENGTH(COALESCE(raw_payload_json, '')) >= :min_raw_chars
                """
            ),
            {"min_raw_chars": min_raw_chars},
        ).scalar()
        or 0
    )
    if not apply:
        stats = db.execute(
            text(
                """
                SELECT
                    COUNT(*) AS candidate_count,
                    MAX(LENGTH(COALESCE(raw_payload_json, ''))) AS max_raw_chars,
                    AVG(LENGTH(COALESCE(raw_payload_json, ''))) AS avg_raw_chars
                FROM resource_ohlcv_bar
                WHERE LENGTH(COALESCE(raw_payload_json, '')) >= :min_raw_chars
                """
            ),
            {"min_raw_chars": min_raw_chars},
        ).mappings().one()
        return {
            "applied": False,
            "candidate_count": int(stats["candidate_count"] or 0),
            "max_raw_chars": int(stats["max_raw_chars"] or 0),
            "avg_raw_chars": float(stats["avg_raw_chars"] or 0),
            "min_raw_chars": min_raw_chars,
        }

    update_statement = text(
        """
        UPDATE resource_ohlcv_bar
        SET raw_payload_json = :raw_payload_json,
            updated_at = :updated_at
        WHERE id = :id
        """
    ).bindparams(bindparam("updated_at", type_=DateTime(timezone=True)))
    compacted_count = 0
    before_chars = 0
    after_chars = 0
    while True:
        if max_rows is not None and compacted_count >= max_rows:
            break
        remaining_limit = batch_size
        if max_rows is not None:
            remaining_limit = min(remaining_limit, max_rows - compacted_count)
        rows = (
            db.execute(
                text(
                    """
                    SELECT
                        id,
                        provider,
                        symbol,
                        provider_symbol,
                        interval,
                        bar_time,
                        source_url,
                        fetched_at,
                        LENGTH(COALESCE(raw_payload_json, '')) AS raw_chars
                    FROM resource_ohlcv_bar
                    WHERE LENGTH(COALESCE(raw_payload_json, '')) >= :min_raw_chars
                    ORDER BY raw_chars DESC, id ASC
                    LIMIT :batch_size
                    """
                ),
                {
                    "min_raw_chars": min_raw_chars,
                    "batch_size": remaining_limit,
                },
            )
            .mappings()
            .all()
        )
        if not rows:
            break

        for row in rows:
            before_chars += int(row["raw_chars"] or 0)
            compact_payload = {
                "source": row["provider"],
                "compacted_from": "legacy_resource_ohlcv_full_payload",
                "symbol": row["provider_symbol"] or row["symbol"],
                "interval": row["interval"],
                "bar_time": str(row["bar_time"]) if row["bar_time"] else None,
                "source_url": row["source_url"],
                "fetched_at": str(row["fetched_at"]) if row["fetched_at"] else None,
                "compacted_at": compacted_at.isoformat(),
            }
            compact_json = _json_dumps(compact_payload)
            after_chars += len(compact_json)
            db.execute(
                update_statement,
                {
                    "id": row["id"],
                    "raw_payload_json": compact_json,
                    "updated_at": compacted_at,
                },
            )
            compacted_count += 1
        db.commit()

    return {
        "applied": True,
        "candidate_count": total_candidates,
        "compacted_count": compacted_count,
        "before_chars": before_chars,
        "after_chars": after_chars,
        "saved_chars": max(before_chars - after_chars, 0),
        "min_raw_chars": min_raw_chars,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compact legacy resource OHLCV raw Yahoo payloads in the local SQLite cache."
    )
    parser.add_argument("--apply", action="store_true", help="Apply compaction. Without this, only report candidates.")
    parser.add_argument("--backup", action="store_true", help="Create a SQLite backup before applying compaction.")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup even when --apply is set.")
    parser.add_argument("--vacuum", action="store_true", help="Run SQLite VACUUM after compaction.")
    parser.add_argument("--min-raw-chars", type=int, default=DEFAULT_MIN_RAW_CHARS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    backup_path = None
    if args.apply and args.backup and not args.no_backup:
        backup_path = backup_sqlite_database()

    with SessionLocal() as db:
        result = compact_resource_ohlcv_raw_payloads(
            db,
            apply=args.apply,
            min_raw_chars=args.min_raw_chars,
            batch_size=args.batch_size,
            max_rows=args.max_rows,
        )
    if args.apply and args.vacuum:
        vacuum_sqlite_database()

    if backup_path is not None:
        result["backup_path"] = str(backup_path)
    print(_json_dumps(result))


if __name__ == "__main__":
    main()
