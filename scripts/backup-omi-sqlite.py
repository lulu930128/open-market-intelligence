from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any


WAL_SNAPSHOT_LIMIT_BYTES = 2 * 1024**3


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


def _check_deadline(deadline: float | None, cancel_file: Path | None = None) -> None:
    if cancel_file is not None and cancel_file.exists():
        raise InterruptedError("backup cancelled cooperatively; unpublished partial is preserved")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("backup deadline exceeded; unpublished partial is preserved")


def _sha256(path: Path, *, deadline: float | None = None, cancel_file: Path | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            _check_deadline(deadline, cancel_file)
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite_database(
    *,
    source: Path,
    output: Path,
    integrity_check: str,
    max_seconds: float | None = None,
    pin_wal_snapshot: bool = False,
    cancel_file: Path | None = None,
) -> dict[str, Any]:
    # Invalid limits fail before any filesystem or database access.
    if max_seconds is not None and (
        isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds <= 0
    ):
        raise ValueError("max_seconds must be finite and positive")
    if pin_wal_snapshot and max_seconds is None:
        raise ValueError("pinned WAL snapshot requires a finite max_seconds")
    started = time.monotonic()
    deadline = None if max_seconds is None else started + max_seconds
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
    # One copy plus a small working reserve. Independent restore needs additional
    # separately verified capacity; this check is not a complete rollback gate.
    if shutil.disk_usage(output.parent).free < source.stat().st_size + 64 * 1024 * 1024:
        raise ValueError("insufficient free space for backup and working reserve")

    source_uri = source.as_uri() + "?mode=ro"
    source_db = None
    destination_db = None
    last_reported = -1
    source_snapshot_active = False

    def query_should_abort() -> int:
        if source_snapshot_active:
            try:
                check_copy_budget()
            except (OSError, ValueError, RuntimeError):
                return 1
        return int(
            (deadline is not None and time.monotonic() >= deadline)
            or (cancel_file is not None and cancel_file.exists())
        )

    def check_copy_budget() -> None:
        _check_deadline(deadline, cancel_file)
        if pin_wal_snapshot:
            wal = source.with_name(source.name + "-wal")
            try:
                wal_bytes = wal.stat().st_size
            except FileNotFoundError:
                wal_bytes = 0
            if wal_bytes > WAL_SNAPSHOT_LIMIT_BYTES:
                raise RuntimeError("WAL snapshot size limit exceeded; reader will close")
            if shutil.disk_usage(source.parent).free < WAL_SNAPSHOT_LIMIT_BYTES:
                raise RuntimeError("WAL snapshot free-space reserve exhausted; reader will close")

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal last_reported
        check_copy_budget()
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
        check_copy_budget()
        source_db = sqlite3.connect(source_uri, uri=True, timeout=min(60, max_seconds or 60))
        source_db.execute("PRAGMA query_only = ON")
        if deadline is not None or cancel_file is not None:
            source_db.set_progress_handler(query_should_abort, 1000)
        if pin_wal_snapshot:
            # Explicit opt-in only: a WAL read transaction pins one snapshot while
            # concurrent writers keep using WAL. Never change the source's mode.
            # Check duration and observed WAL/free space cooperatively. Close
            # releases the reader on success, cancellation, pressure, or error.
            if source_db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                raise ValueError("pinned snapshot requires an already-WAL source")
            source_db.execute("BEGIN")
            source_snapshot_active = True
        source_snapshot = _database_snapshot(source_db)
        check_copy_budget()
        # Reserve exclusively. A concurrent invocation must never open/truncate
        # another backup's partial. Keep failed partials for operator inspection.
        with partial.open("xb"):
            pass
        destination_db = sqlite3.connect(partial.as_uri() + "?mode=rw", uri=True, timeout=1)
        source_db.backup(
            destination_db,
            pages=4096,
            progress=progress,
            sleep=0.05,
        )
        destination_db.commit()
    finally:
        if destination_db is not None:
            destination_db.close()
        if source_db is not None:
            source_db.close()
        source_snapshot_active = False

    _check_deadline(deadline, cancel_file)
    verification_db = sqlite3.connect(partial.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        verification_db.execute("PRAGMA query_only = ON")
        if deadline is not None or cancel_file is not None:
            verification_db.set_progress_handler(query_should_abort, 1000)
        pragma = "PRAGMA quick_check" if integrity_check == "quick" else "PRAGMA integrity_check"
        integrity_rows = verification_db.execute(pragma).fetchall()
        integrity_result = "ok" if integrity_rows == [("ok",)] else repr(integrity_rows)
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

    sha256 = (_sha256(partial) if deadline is None and cancel_file is None else
              _sha256(partial, deadline=deadline, cancel_file=cancel_file))
    _check_deadline(deadline, cancel_file)
    # link is exclusive on Windows and POSIX; replace/rename can overwrite a
    # destination that appeared after the preflight. Unsupported filesystems fail
    # closed with the verified partial retained, without an overwrite fallback.
    os.link(partial, output)
    partial.unlink()
    return {
        "contract_version": "omi.sqlite-backup.v1",
        "source": str(source),
        "output": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": sha256,
        "integrity_check": integrity_result,
        "source_snapshot_mode": "bounded_wal_read_transaction" if pin_wal_snapshot else "incremental_online",
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
    parser.add_argument("--pin-wal-snapshot", action="store_true",
                        help="Pin an existing WAL read snapshot; requires --max-seconds. Abort at progress checks if observed WAL exceeds 2 GiB.")
    parser.add_argument("--cancel-file", type=Path,
                        help="Stop cooperatively if this operator-owned marker appears; never kills a process.")
    parser.add_argument(
        "--max-seconds", type=float, default=None,
        help="Cooperative copy/check/hash deadline; never kills a process. Failed partials remain.",
    )
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
            max_seconds=args.max_seconds,
            pin_wal_snapshot=args.pin_wal_snapshot,
            cancel_file=args.cancel_file,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
