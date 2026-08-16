from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import tracemalloc
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.us_market.providers import sec as sec_provider  # noqa: E402
from app.us_market.sec_ownership.archive import (  # noqa: E402
    validate_zip_archive,
    write_bounded_stream,
)
from app.us_market.sec_ownership.form13f import (  # noqa: E402
    iter_13f_table_rows,
    normalize_cusip,
    parse_reported_value,
    parse_section_13f_list,
    table_members,
)


RELEASES = (
    (
        "2026Q1",
        "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
    ),
    (
        "2025Q4",
        "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip",
    ),
)
SECTION_LIST = (
    "2026Q2",
    "https://www.sec.gov/files/investment/13flist2026q2-txt.txt",
)


def _download(url: str, destination: Path, *, target: str, max_bytes: int) -> Path:
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    response = sec_provider.open_sec_dataset_stream(
        url=url,
        resource="sec_13f_capacity_probe",
        target=target,
        sec_user_agent=str(settings.us_sec_user_agent),
        timeout_seconds=120,
    )
    try:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if destination.suffix == ".zip" and not any(
            token in content_type for token in ("zip", "octet-stream")
        ):
            raise ValueError(f"Unexpected ZIP content type: {content_type or 'missing'}")
        write_bounded_stream(
            response.iter_content(chunk_size=1024 * 1024),
            destination,
            max_bytes=max_bytes,
        )
    finally:
        response.close()
    return destination


def _open_pilot_db(path: Path) -> sqlite3.Connection:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE filing (
          period_key TEXT NOT NULL,
          accession_number TEXT NOT NULL,
          submission_type TEXT NOT NULL,
          cik TEXT NOT NULL,
          period_of_report TEXT NOT NULL,
          PRIMARY KEY (period_key, accession_number)
        ) WITHOUT ROWID;
        CREATE TABLE holding (
          period_key TEXT NOT NULL,
          accession_number TEXT NOT NULL,
          infotable_sk TEXT NOT NULL,
          cusip TEXT,
          reported_value_raw TEXT,
          shares_or_principal TEXT,
          amount_type TEXT,
          put_call TEXT,
          investment_discretion TEXT,
          other_manager TEXT,
          voting_sole TEXT,
          voting_shared TEXT,
          voting_none TEXT,
          PRIMARY KEY (period_key, accession_number, infotable_sk)
        ) WITHOUT ROWID;
        """
    )
    return connection


def _scan_release(
    period_key: str,
    archive_path: Path,
    *,
    securities: dict[str, object],
    connection: sqlite3.Connection,
) -> dict[str, object]:
    started = time.perf_counter()
    table_counts: Counter[str] = Counter()
    submission_types: Counter[str] = Counter()
    total_value = Decimal("0")
    reference_value = Decimal("0")
    valid_value = Decimal("0")
    valid_cusip_rows = 0
    reference_rows = 0
    malformed_value_rows = 0
    batch: list[tuple[str, ...]] = []

    with zipfile.ZipFile(archive_path) as archive:
        members = table_members(archive)
        for row in iter_13f_table_rows(archive, members["SUBMISSION"]):
            table_counts["SUBMISSION"] += 1
            submission_type = row.get("SUBMISSIONTYPE", "")
            submission_types[submission_type] += 1
            connection.execute(
                "INSERT INTO filing VALUES (?, ?, ?, ?, ?)",
                (
                    period_key,
                    row.get("ACCESSION_NUMBER", ""),
                    submission_type,
                    row.get("CIK", ""),
                    row.get("PERIODOFREPORT", ""),
                ),
            )
        for table, member in members.items():
            if table in {"SUBMISSION", "INFOTABLE"}:
                continue
            for _ in iter_13f_table_rows(archive, member):
                table_counts[table] += 1
        for row in iter_13f_table_rows(archive, members["INFOTABLE"]):
            table_counts["INFOTABLE"] += 1
            cusip = normalize_cusip(row.get("CUSIP"))
            value = parse_reported_value(row)
            if value is None:
                malformed_value_rows += 1
            else:
                total_value += value
            if cusip is not None:
                valid_cusip_rows += 1
                if value is not None:
                    valid_value += value
                if cusip in securities:
                    reference_rows += 1
                    if value is not None:
                        reference_value += value
            batch.append(
                (
                    period_key,
                    row.get("ACCESSION_NUMBER", ""),
                    row.get("INFOTABLE_SK", ""),
                    cusip or "",
                    str(value) if value is not None else "",
                    row.get("SSHPRNAMT", ""),
                    row.get("SSHPRNAMTTYPE", ""),
                    row.get("PUTCALL", ""),
                    row.get("INVESTMENTDISCRETION", ""),
                    row.get("OTHERMANAGER", ""),
                    row.get("VOTING_AUTH_SOLE", ""),
                    row.get("VOTING_AUTH_SHARED", ""),
                    row.get("VOTING_AUTH_NONE", ""),
                )
            )
            if len(batch) >= 10_000:
                connection.executemany("INSERT INTO holding VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
                connection.commit()
                batch.clear()
        if batch:
            connection.executemany("INSERT INTO holding VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            connection.commit()

    holdings = table_counts["INFOTABLE"]
    return {
        "period_key": period_key,
        "table_counts": dict(sorted(table_counts.items())),
        "submission_types": dict(sorted(submission_types.items())),
        "reported_value_raw": str(total_value),
        "malformed_value_rows": malformed_value_rows,
        "valid_cusip_rows": valid_cusip_rows,
        "official_list_reference_rows": reference_rows,
        "official_list_reference_row_coverage": reference_rows / holdings if holdings else 1.0,
        "official_list_reference_value_coverage": float(reference_value / total_value) if total_value else 1.0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded two-quarter SEC Form 13F capacity proof.")
    parser.add_argument("--cache-root", type=Path, default=Path(settings.us_sec_ownership_cache_path))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cache_root = args.cache_root.resolve()
    archive_root = cache_root / "archives" / "form-13f"
    list_root = cache_root / "archives" / "section-13f-list"
    pilot_root = cache_root / "capacity"
    archive_root.mkdir(parents=True, exist_ok=True)
    list_root.mkdir(parents=True, exist_ok=True)
    pilot_root.mkdir(parents=True, exist_ok=True)

    disk = shutil.disk_usage(cache_root)
    required_free = int(float(settings.us_sec_ownership_min_free_space_gb) * 1024**3)
    if disk.free < required_free:
        raise RuntimeError("Insufficient free disk space for the bounded Form 13F capacity proof.")

    list_period, list_url = SECTION_LIST
    list_path = _download(
        list_url,
        list_root / list_period / "13flist.txt",
        target=list_period,
        max_bytes=64 * 1024 * 1024,
    )
    securities = parse_section_13f_list(list_path.read_bytes())

    archive_inventories: dict[str, object] = {}
    archive_paths: dict[str, Path] = {}
    for period_key, url in RELEASES:
        archive_path = _download(
            url,
            archive_root / period_key / "form13f.zip",
            target=period_key,
            max_bytes=int(settings.us_sec_ownership_max_archive_bytes),
        )
        inventory = validate_zip_archive(
            archive_path,
            max_archive_bytes=int(settings.us_sec_ownership_max_archive_bytes),
            max_uncompressed_bytes=int(settings.us_sec_ownership_max_uncompressed_bytes),
        )
        archive_paths[period_key] = archive_path
        archive_inventories[period_key] = {
            "source_url": url,
            "archive_size_bytes": inventory.archive_size_bytes,
            "uncompressed_size_bytes": inventory.uncompressed_size_bytes,
            "entry_count": inventory.entry_count,
            "sha256": inventory.sha256,
            "entries": [
                {"name": name, "compressed_bytes": compressed, "uncompressed_bytes": uncompressed}
                for name, compressed, uncompressed in inventory.entries
            ],
        }

    pilot_db = pilot_root / "two-quarter-pilot.sqlite"
    connection = _open_pilot_db(pilot_db)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        releases = [
            _scan_release(period_key, archive_paths[period_key], securities=securities, connection=connection)
            for period_key, _ in RELEASES
        ]
        before_indexes = pilot_db.stat().st_size
        connection.executescript(
            """
            CREATE INDEX ix_holding_cusip_period ON holding(cusip, period_key);
            CREATE INDEX ix_holding_accession ON holding(accession_number);
            ANALYZE;
            """
        )
        connection.commit()
        after_indexes = pilot_db.stat().st_size
    finally:
        connection.close()
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    holding_rows = sum(int(item["table_counts"].get("INFOTABLE", 0)) for item in releases)
    pilot_quarters = len(RELEASES)
    published_quarters = 52
    projected_db = int(after_indexes * published_quarters / pilot_quarters)
    projected_archives = int(
        sum(int(item["archive_size_bytes"]) for item in archive_inventories.values())
        * published_quarters
        / pilot_quarters
    )
    storage_budget = int(float(settings.us_sec_ownership_storage_budget_gb) * 1024**3)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "latest_two_complete_official_form13f_datasets",
        "official_section_13f_list": {
            "period_key": list_period,
            "source_url": list_url,
            "security_count": len(securities),
        },
        "archives": archive_inventories,
        "releases": releases,
        "pilot": {
            "holding_rows": holding_rows,
            "database_bytes_before_indexes": before_indexes,
            "database_bytes_after_indexes": after_indexes,
            "bytes_per_holding_with_indexes": after_indexes / holding_rows if holding_rows else None,
            "python_tracemalloc_peak_bytes": peak_memory,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
        "mapping_gate": {
            "official_cusip_reference_row_coverage": sum(
                float(item["official_list_reference_row_coverage"]) for item in releases
            ) / pilot_quarters,
            "official_cusip_reference_value_coverage": sum(
                float(item["official_list_reference_value_coverage"]) for item in releases
            ) / pilot_quarters,
            "production_exact_cusip_to_symbol_row_coverage": 0.0,
            "production_exact_cusip_to_symbol_value_coverage": 0.0,
            "reason": "Current us_stock_master has no CUSIP/FIGI identifier column; issuer-name-only matching is not approved for ready projections.",
            "required_row_coverage": 0.90,
            "required_value_coverage": 0.95,
            "passed": False,
        },
        "full_history_projection": {
            "published_quarters_assumption": published_quarters,
            "projected_database_bytes": projected_db,
            "projected_compressed_archive_bytes": projected_archives,
            "projected_combined_bytes": projected_db + projected_archives,
            "storage_budget_bytes": storage_budget,
            "passed": projected_db + projected_archives <= storage_budget,
            "method": "Conservative linear extrapolation from the two latest, largest complete releases; staging headroom is evaluated separately.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
