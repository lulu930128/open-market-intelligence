from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any


def _database_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    revision_row = connection.execute(
        "SELECT version_num FROM alembic_version LIMIT 1"
    ).fetchone()
    counts: dict[str, int] = {}
    for table in (
        "tw_financial_filing",
        "tw_financial_parse_run",
        "tw_financial_parse_run_review",
        "tw_financial_statement_fact",
        "tw_financial_normalized_fact",
        "tw_financial_basis_assessment",
    ):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists is not None:
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
    return {
        "revision": str(revision_row[0]) if revision_row else None,
        "counts": counts,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite_database(
    *,
    source: Path,
    output: Path,
    integrity_check: str,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    partial = output.with_name(f"{output.name}.partial")
    if not source.is_file():
        raise ValueError(f"source database does not exist: {source}")
    if output.exists():
        raise ValueError(f"refusing to overwrite existing backup: {output}")
    if partial.exists():
        raise ValueError(f"partial backup already exists: {partial}")
    if not output.parent.is_dir():
        raise ValueError(f"backup directory does not exist: {output.parent}")
    if source == output or source == partial:
        raise ValueError("source and backup paths must be different")
    if integrity_check not in {"quick", "full"}:
        raise ValueError("integrity_check must be quick or full")

    started = time.monotonic()
    source_uri = f"file:{source.as_posix()}?mode=ro"
    source_db = sqlite3.connect(source_uri, uri=True, timeout=60)
    destination_db = sqlite3.connect(str(partial), timeout=60)
    last_reported = -1

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal last_reported
        if total <= 0:
            return
        percent = int(((total - remaining) * 100) / total)
        bucket = min(100, (percent // 10) * 10)
        if bucket != last_reported:
            last_reported = bucket
            print(
                json.dumps(
                    {
                        "phase": "backup",
                        "percent": bucket,
                        "remaining_pages": remaining,
                        "total_pages": total,
                        "sqlite_status": status,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )

    try:
        source_db.execute("PRAGMA query_only = ON")
        source_snapshot = _database_snapshot(source_db)
        source_db.backup(
            destination_db,
            pages=4096,
            progress=progress,
            sleep=0.05,
        )
        destination_db.commit()
    finally:
        destination_db.close()
        source_db.close()

    verification_db = sqlite3.connect(str(partial), timeout=60)
    try:
        pragma = "PRAGMA quick_check" if integrity_check == "quick" else "PRAGMA integrity_check"
        integrity_result = str(verification_db.execute(pragma).fetchone()[0])
        backup_snapshot = _database_snapshot(verification_db)
    finally:
        verification_db.close()
    if integrity_result != "ok":
        raise ValueError(
            f"backup integrity check failed; partial preserved at {partial}: "
            f"{integrity_result}"
        )
    if backup_snapshot != source_snapshot:
        raise ValueError(
            "backup snapshot differs from source; partial preserved at "
            f"{partial}: source={source_snapshot} backup={backup_snapshot}"
        )

    sha256 = _sha256(partial)
    partial.replace(output)
    return {
        "contract_version": "omi.sqlite-backup.v1",
        "source": str(source),
        "output": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": sha256,
        "integrity_check": integrity_result,
        "snapshot": backup_snapshot,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "boundaries": [
            "source_opened_read_only",
            "existing_output_is_never_overwritten",
            "backup_is_published_only_after_integrity_and_snapshot_match",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a consistent, verified SQLite backup. The source is opened "
            "read-only and the final path is published only after verification."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--integrity-check",
        choices=("quick", "full"),
        default="quick",
    )
    args = parser.parse_args()

    try:
        summary = backup_sqlite_database(
            source=args.source,
            output=args.output,
            integrity_check=args.integrity_check,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
