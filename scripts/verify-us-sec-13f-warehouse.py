from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.db.models import USSec13FWarehousePartition, USSecDatasetRelease  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.us_market.ownership_13f_manifest import load_cached_13f_manifest  # noqa: E402


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _json_dict(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify SEC Form 13F manifest, Parquet paths, sizes, and optional hashes."
    )
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--require-full-history", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    warehouse_root = Path(settings.us_sec_13f_warehouse_path).resolve()
    manifest = load_cached_13f_manifest()
    db = SessionLocal()
    parquet = duckdb.connect(config={"threads": 1})
    try:
        rows = (
            db.query(USSec13FWarehousePartition, USSecDatasetRelease)
            .join(
                USSecDatasetRelease,
                USSecDatasetRelease.id == USSec13FWarehousePartition.dataset_release_id,
            )
            .filter(USSec13FWarehousePartition.is_current.is_(True))
            .order_by(USSec13FWarehousePartition.period_key.asc())
            .all()
        )
        completed_urls: set[str] = set()
        issues: list[dict[str, str]] = []
        verified_bytes = 0
        source_holdings = 0
        canonical_holdings = 0
        retained_holdings = 0
        invalid_cusip = 0
        invalid_value = 0
        for partition, release in rows:
            source_counts = _json_dict(release.source_row_counts_json)
            persisted_counts = _json_dict(release.persisted_row_counts_json)
            quarantined_counts = _json_dict(release.quarantined_row_counts_json)
            source_holdings += int(source_counts.get("INFOTABLE") or 0)
            canonical_holdings += int(persisted_counts.get("holdings") or 0)
            retained_holdings += int(
                persisted_counts.get("retained_holdings_including_quarantine") or 0
            )
            invalid_cusip += int(quarantined_counts.get("invalid_cusip") or 0)
            invalid_value += int(quarantined_counts.get("invalid_reported_value") or 0)
            path = Path(partition.holdings_path).resolve()
            if not _is_within(path, warehouse_root):
                issues.append({"period_key": partition.period_key, "code": "path_outside_warehouse"})
                continue
            if partition.status != "completed":
                issues.append({"period_key": partition.period_key, "code": "partition_not_completed"})
                continue
            if not path.is_file():
                issues.append({"period_key": partition.period_key, "code": "parquet_missing"})
                continue
            size = path.stat().st_size
            verified_bytes += size
            if size != partition.file_size_bytes:
                issues.append({"period_key": partition.period_key, "code": "parquet_size_mismatch"})
                continue
            metadata = {
                bytes(key).decode("utf-8", errors="replace"): bytes(value).decode(
                    "utf-8", errors="replace"
                )
                for key, value in parquet.execute(
                    "SELECT key, value FROM parquet_kv_metadata(?)",
                    [str(path)],
                ).fetchall()
            }
            if metadata.get("contract_version") != "omi.sec.13f.parquet.v3":
                issues.append({"period_key": partition.period_key, "code": "schema_version_mismatch"})
                continue
            row_count = int(
                parquet.execute(
                    "SELECT num_rows FROM parquet_file_metadata(?)",
                    [str(path)],
                ).fetchone()[0]
            )
            if row_count != partition.row_count:
                issues.append({"period_key": partition.period_key, "code": "parquet_row_count_mismatch"})
                continue
            if args.verify_hashes and _file_sha256(path) != partition.holdings_sha256:
                issues.append({"period_key": partition.period_key, "code": "parquet_hash_mismatch"})
                continue
            completed_urls.add(release.source_url)

        manifest_entries = (
            [item for item in manifest.get("entries") or [] if isinstance(item, dict)]
            if manifest
            else []
        )
        expected_urls = {str(item.get("source_url") or "") for item in manifest_entries}
        pending_urls = sorted(expected_urls - completed_urls)
        budget_bytes = int(float(settings.us_sec_13f_storage_budget_gb) * 1024**3)
        if verified_bytes > budget_bytes:
            issues.append({"period_key": "all", "code": "storage_budget_exceeded"})
        if manifest is None:
            issues.append({"period_key": "all", "code": "manifest_missing"})
        if args.require_full_history and pending_urls:
            issues.append({"period_key": "all", "code": "published_history_incomplete"})
        if retained_holdings != source_holdings:
            issues.append({"period_key": "all", "code": "retained_source_row_mismatch"})
        if canonical_holdings + invalid_cusip != source_holdings:
            issues.append({"period_key": "all", "code": "source_row_reconciliation_mismatch"})
        if invalid_value:
            issues.append({"period_key": "all", "code": "invalid_reported_value_present"})

        result = {
            "contract_version": "omi.sec.13f.warehouse-verification.v1",
            "status": "current" if not issues else "partial",
            "partition_count": len(rows),
            "manifest_entry_count": len(manifest_entries),
            "completed_manifest_count": len(expected_urls & completed_urls),
            "pending_manifest_count": len(pending_urls),
            "verified_file_size_bytes": verified_bytes,
            "storage_budget_bytes": budget_bytes,
            "hashes_verified": bool(args.verify_hashes),
            "reconciliation": {
                "source_holdings": source_holdings,
                "retained_holdings": retained_holdings,
                "canonical_holdings": canonical_holdings,
                "quarantined_invalid_cusip": invalid_cusip,
                "quarantined_invalid_value": invalid_value,
            },
            "issues": issues,
            "pending_period_keys": [
                str(item.get("period_key") or "")
                for item in manifest_entries
                if str(item.get("source_url") or "") in set(pending_urls)
            ],
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if not issues else 1
    finally:
        parquet.close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
