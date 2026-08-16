from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    USSec13FWarehousePartition,
    USSecDatasetRelease,
    USSecIngestionCheckpoint,
)
from app.observability.provider_health import record_provider_event
from app.us_market.errors import USMarketConfigurationError, USMarketDataFetchError
from app.us_market.ownership_13f_store import persist_13f_release_metadata
from app.us_market import ownership_13f_analytics, ownership_13f_manifest
from app.us_market.providers import sec as sec_provider
from app.us_market.sec_ownership.archive import validate_zip_archive, write_bounded_stream
from app.us_market.sec_ownership.form13f import FORM13F_PARSER_VERSION
from app.us_market.sec_ownership.form13f_warehouse import (
    WAREHOUSE_SCHEMA_VERSION,
    build_13f_holdings_parquet,
)


ProgressCallback = Callable[[int | None, int | None, str | None], None]
FORM13F_DATASET_CODE = "form_13f"
FORM13F_SOURCE_SCHEMA_VERSION = "sec.form13f.dataset.v1"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sec_user_agent() -> str:
    value = str(settings.us_sec_user_agent or "").strip().strip('"').strip("'")
    if not value or "set US_SEC_USER_AGENT" in value:
        raise USMarketConfigurationError(
            "US_SEC_USER_AGENT is not configured. Set a descriptive User-Agent before calling SEC EDGAR APIs."
        )
    return value


def _warehouse_usage_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(
        path.stat().st_size
        for path in root.rglob("*.parquet")
        if path.is_file()
    )


def _partition_is_valid(partition: USSec13FWarehousePartition) -> bool:
    path = Path(partition.holdings_path)
    return (
        partition.status == "completed"
        and path.is_file()
        and path.stat().st_size == partition.file_size_bytes
        and partition.row_count > 0
    )


def _checkpoint(
    db: Session,
    *,
    release_id: int,
    stage_code: str,
    period_key: str,
    processed_count: int,
    status: str,
    error_count: int = 0,
) -> USSecIngestionCheckpoint:
    row = (
        db.query(USSecIngestionCheckpoint)
        .filter(
            USSecIngestionCheckpoint.dataset_release_id == release_id,
            USSecIngestionCheckpoint.stage_code == stage_code,
            USSecIngestionCheckpoint.partition_key == period_key,
        )
        .first()
    )
    now = _utc_now()
    if row is None:
        row = USSecIngestionCheckpoint(
            dataset_release_id=release_id,
            stage_code=stage_code,
            partition_key=period_key,
            started_at=now,
        )
        db.add(row)
    row.processed_count = processed_count
    row.error_count = error_count
    row.status = status
    row.completed_at = now if status in {"completed", "failed"} else None
    return row


def ingest_13f_release(
    db: Session,
    *,
    period_key: str,
    source_url: str,
    archive_path: Path,
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_period = str(period_key or "").strip().upper()
    if not normalized_period or len(normalized_period) > 40:
        raise ValueError("period_key must be a non-empty value of at most 40 characters.")
    source = str(source_url or "").strip()
    if not source.startswith("https://www.sec.gov/"):
        raise ValueError("source_url must be an official https://www.sec.gov/ URL.")
    archive = Path(archive_path)
    if progress_callback:
        progress_callback(0, 4, f"Validating SEC 13F archive for {normalized_period}.")
    inventory = validate_zip_archive(
        archive,
        max_archive_bytes=int(settings.us_sec_ownership_max_archive_bytes),
        max_uncompressed_bytes=int(settings.us_sec_ownership_max_uncompressed_bytes),
    )
    release = (
        db.query(USSecDatasetRelease)
        .filter(
            USSecDatasetRelease.dataset_code == FORM13F_DATASET_CODE,
            USSecDatasetRelease.period_key == normalized_period,
            USSecDatasetRelease.source_sha256 == inventory.sha256,
        )
        .first()
    )
    now = _utc_now()
    if release is None:
        release = USSecDatasetRelease(
            dataset_code=FORM13F_DATASET_CODE,
            period_key=normalized_period,
            source_url=source,
            source_sha256=inventory.sha256,
            source_size_bytes=inventory.archive_size_bytes,
            checked_at=now,
            downloaded_at=now,
            schema_version=FORM13F_SOURCE_SCHEMA_VERSION,
            parser_version=FORM13F_PARSER_VERSION,
            status="downloaded",
        )
        db.add(release)
        db.commit()
        db.refresh(release)
    else:
        release.source_url = source
        release.source_size_bytes = inventory.archive_size_bytes
        release.checked_at = now
        release.downloaded_at = release.downloaded_at or now
        existing_partition = (
            db.query(USSec13FWarehousePartition)
            .filter(USSec13FWarehousePartition.dataset_release_id == release.id)
            .first()
        )
        if not force and existing_partition is not None and _partition_is_valid(existing_partition):
            return {
                "status": "current",
                "idempotent": True,
                "period_key": normalized_period,
                "dataset_release_id": release.id,
                "partition_id": existing_partition.id,
                "row_count": existing_partition.row_count,
                "distinct_cusip_count": existing_partition.distinct_cusip_count,
                "file_size_bytes": existing_partition.file_size_bytes,
                "source_sha256": inventory.sha256,
                "holdings_sha256": existing_partition.holdings_sha256,
            }
        release.status = "downloaded"
        release.error_summary = None
        db.commit()

    warehouse_root = Path(settings.us_sec_13f_warehouse_path)
    destination = (
        warehouse_root
        / f"period_key={normalized_period}"
        / f"release={inventory.sha256}"
        / "holdings.parquet"
    )
    staging = warehouse_root / ".staging" / f"{normalized_period}-{inventory.sha256[:12]}"
    try:
        if progress_callback:
            progress_callback(1, 4, f"Building SEC 13F Parquet partition for {normalized_period}.")
        build = build_13f_holdings_parquet(
            archive_path=archive,
            output_path=destination,
            staging_dir=staging,
            dataset_release_id=release.id,
            period_key=normalized_period,
            source_sha256=inventory.sha256,
            max_archive_bytes=int(settings.us_sec_ownership_max_archive_bytes),
            max_uncompressed_bytes=int(settings.us_sec_ownership_max_uncompressed_bytes),
            min_free_space_bytes=max(
                int(float(settings.us_sec_ownership_min_free_space_gb) * 1024**3), 0
            ),
            compression=settings.us_sec_13f_parquet_compression,
        )
        budget_bytes = max(int(float(settings.us_sec_13f_storage_budget_gb) * 1024**3), 1)
        usage_bytes = _warehouse_usage_bytes(warehouse_root)
        if usage_bytes > budget_bytes:
            destination.unlink(missing_ok=True)
            raise ValueError(
                f"SEC 13F warehouse usage {usage_bytes} exceeds the configured budget {budget_bytes}."
            )

        if progress_callback:
            progress_callback(2, 4, f"Persisting SEC 13F filing metadata for {normalized_period}.")
        metadata = persist_13f_release_metadata(
            db,
            release=release,
            archive_path=archive,
        )
        partition = (
            db.query(USSec13FWarehousePartition)
            .filter(USSec13FWarehousePartition.dataset_release_id == release.id)
            .first()
        )
        if partition is None:
            partition = USSec13FWarehousePartition(dataset_release_id=release.id)
            db.add(partition)
        partition.period_key = normalized_period
        partition.source_sha256 = inventory.sha256
        partition.holdings_path = str(build.holdings_path.resolve())
        partition.holdings_sha256 = build.holdings_sha256
        partition.row_count = build.row_count
        partition.file_size_bytes = build.file_size_bytes
        partition.distinct_cusip_count = build.distinct_cusip_count
        partition.total_reported_value_usd_text = build.total_reported_value_usd_text
        partition.status = "completed"
        db.query(USSec13FWarehousePartition).filter(
            USSec13FWarehousePartition.period_key == normalized_period,
            USSec13FWarehousePartition.dataset_release_id != release.id,
        ).update({USSec13FWarehousePartition.is_current: False}, synchronize_session=False)
        partition.is_current = True

        source_counts = {
            **metadata["table_counts"],
            "INFOTABLE": build.row_count,
        }
        persisted_counts = {
            "filings": metadata["filing_count"],
            "managers": metadata["manager_count"],
            "other_managers": metadata["other_manager_count"],
            "holdings": build.row_count - build.invalid_cusip_count,
            "retained_holdings_including_quarantine": build.row_count,
            "distinct_cusips": build.distinct_cusip_count,
        }
        quarantined_counts = {
            "missing_filing_identity": metadata.get("skipped_missing_identity", 0),
            "invalid_cusip": build.invalid_cusip_count,
            "invalid_reported_value": build.invalid_value_count,
        }
        release.source_row_counts_json = _json(source_counts)
        release.persisted_row_counts_json = _json(persisted_counts)
        release.quarantined_row_counts_json = _json(quarantined_counts)
        release.status = "completed"
        release.error_summary = None
        _checkpoint(
            db,
            release_id=release.id,
            stage_code="warehouse_promoted",
            period_key=normalized_period,
            processed_count=build.row_count,
            status="completed",
        )
        detail = {
            "period_key": normalized_period,
            "dataset_release_id": release.id,
            "row_count": build.row_count,
            "distinct_cusip_count": build.distinct_cusip_count,
            "file_size_bytes": build.file_size_bytes,
            "warehouse_usage_bytes": usage_bytes,
            "storage_budget_bytes": budget_bytes,
            "quarantined_counts": quarantined_counts,
        }
        record_provider_event(
            db,
            market="us",
            provider="sec_edgar",
            resource="sec_13f",
            target=normalized_period,
            status="success",
            source_url=source,
            message="SEC Form 13F analytical partition promoted.",
            detail=detail,
        )
        db.commit()
        db.refresh(partition)
        if progress_callback:
            progress_callback(4, 4, f"Completed SEC 13F ingestion for {normalized_period}.")
        return {
            "status": "current",
            "idempotent": False,
            **detail,
            "partition_id": partition.id,
            "source_sha256": inventory.sha256,
            "holdings_sha256": build.holdings_sha256,
            "filing_count": metadata["filing_count"],
            "manager_count": metadata["manager_count"],
        }
    except Exception as exc:
        db.rollback()
        failed_release = (
            db.query(USSecDatasetRelease)
            .filter(USSecDatasetRelease.id == release.id)
            .first()
        )
        if failed_release is not None:
            failed_release.status = "failed"
            failed_release.error_summary = str(exc)[:4000]
            _checkpoint(
                db,
                release_id=failed_release.id,
                stage_code="warehouse_promoted",
                period_key=normalized_period,
                processed_count=0,
                error_count=1,
                status="failed",
            )
        record_provider_event(
            db,
            market="us",
            provider="sec_edgar",
            resource="sec_13f",
            target=normalized_period,
            status="error",
            source_url=source,
            message="SEC Form 13F ingestion failed; the prior current partition was retained.",
            error_message=str(exc),
            detail={"period_key": normalized_period, "dataset_release_id": release.id},
        )
        db.commit()
        if isinstance(exc, (USMarketConfigurationError, ValueError)):
            raise
        if isinstance(exc, USMarketDataFetchError):
            raise
        raise USMarketDataFetchError(str(exc)) from exc


def sync_13f_release(
    db: Session,
    *,
    period_key: str,
    source_url: str,
    force_download: bool = False,
    force_rebuild: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    normalized_period = str(period_key or "").strip().upper()
    archive = (
        Path(settings.us_sec_ownership_cache_path)
        / "archives"
        / "form-13f"
        / normalized_period
        / "form13f.zip"
    )
    downloaded = False
    if force_download or not archive.is_file():
        if progress_callback:
            progress_callback(0, 5, f"Downloading official SEC 13F archive for {normalized_period}.")
        response = sec_provider.open_sec_dataset_stream(
            url=source_url,
            resource="sec_13f",
            target=normalized_period,
            sec_user_agent=_sec_user_agent(),
            timeout_seconds=max(int(settings.us_market_http_timeout_seconds), 1),
        )
        incoming = archive.with_name("form13f.incoming.zip")
        try:
            write_bounded_stream(
                response.iter_content(chunk_size=1024 * 1024),
                incoming,
                max_bytes=int(settings.us_sec_ownership_max_archive_bytes),
            )
            validate_zip_archive(
                incoming,
                max_archive_bytes=int(settings.us_sec_ownership_max_archive_bytes),
                max_uncompressed_bytes=int(settings.us_sec_ownership_max_uncompressed_bytes),
            )
            archive.parent.mkdir(parents=True, exist_ok=True)
            incoming.replace(archive)
            downloaded = True
        except Exception:
            incoming.unlink(missing_ok=True)
            raise
    elif progress_callback:
        progress_callback(1, 5, f"Using validated local SEC 13F archive for {normalized_period}.")
    result = ingest_13f_release(
        db,
        period_key=normalized_period,
        source_url=source_url,
        archive_path=archive,
        force=force_rebuild,
        progress_callback=(
            (lambda current, _total, message: progress_callback(
                min((current or 0) + 1, 5), 5, message
            ))
            if progress_callback
            else None
        ),
    )
    return {**result, "downloaded": downloaded, "archive_path": str(archive.resolve())}


def sync_13f_history(
    db: Session,
    *,
    max_releases: int = 4,
    refresh_manifest: bool = True,
    include_completed: bool = False,
    force_download: bool = False,
    force_rebuild: bool = False,
    stop_on_error: bool = False,
    rebuild_projections: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    if max_releases < 1 or max_releases > 60:
        raise ValueError("max_releases must be between 1 and 60.")
    manifest = (
        ownership_13f_manifest.refresh_13f_manifest()
        if refresh_manifest
        else ownership_13f_manifest.load_cached_13f_manifest()
    )
    if manifest is None:
        raise USMarketDataFetchError(
            "No cached SEC Form 13F manifest is available; run with refresh_manifest=true."
        )
    entries = [item for item in manifest.get("entries") or [] if isinstance(item, dict)]
    if not entries:
        raise USMarketDataFetchError("SEC Form 13F manifest has no usable entries.")

    current_partitions = (
        db.query(USSec13FWarehousePartition, USSecDatasetRelease)
        .join(
            USSecDatasetRelease,
            USSecDatasetRelease.id == USSec13FWarehousePartition.dataset_release_id,
        )
        .filter(
            USSec13FWarehousePartition.is_current.is_(True),
            USSec13FWarehousePartition.status == "completed",
        )
        .all()
    )
    completed_urls = {
        release.source_url
        for partition, release in current_partitions
        if _partition_is_valid(partition)
    }
    candidates = [
        item
        for item in entries
        if include_completed or str(item.get("source_url") or "") not in completed_urls
    ][:max_releases]
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    skipped_count = min(len(entries), max_releases) - len(candidates) if include_completed is False else 0
    total = max(len(candidates), 1)
    if progress_callback:
        progress_callback(0, total, f"Preparing {len(candidates)} SEC Form 13F releases.")

    for index, item in enumerate(candidates, start=1):
        period_key = str(item.get("period_key") or "")
        source_url = str(item.get("source_url") or "")
        if progress_callback:
            progress_callback(index - 1, total, f"Synchronizing {period_key} ({index}/{total}).")
        try:
            result = sync_13f_release(
                db,
                period_key=period_key,
                source_url=source_url,
                force_download=force_download,
                force_rebuild=force_rebuild,
            )
            completed.append({**result, "source_url": source_url})
        except Exception as exc:
            failed.append({"period_key": period_key, "source_url": source_url, "error": str(exc)})
            if stop_on_error:
                raise
        if progress_callback:
            progress_callback(index, total, f"Processed SEC Form 13F release {period_key}.")

    projection = None
    if rebuild_projections and completed:
        projection = ownership_13f_analytics.rebuild_13f_symbol_quarter_projections(db)

    completed_urls_after = completed_urls | {
        str(item.get("source_url") or "") for item in completed
    }
    pending_count = sum(
        1 for item in entries if str(item.get("source_url") or "") not in completed_urls_after
    )
    status = "current" if pending_count == 0 and not failed else "partial"
    return {
        "status": status,
        "manifest_contract_version": manifest.get("contract_version"),
        "manifest_checked_at": manifest.get("checked_at"),
        "manifest_entry_count": len(entries),
        "selected_count": len(candidates),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "skipped_count": max(skipped_count, 0),
        "pending_count": pending_count,
        "completed": completed,
        "failed": failed,
        "projection": projection,
    }


__all__ = [
    "FORM13F_DATASET_CODE",
    "FORM13F_SOURCE_SCHEMA_VERSION",
    "ingest_13f_release",
    "sync_13f_history",
    "sync_13f_release",
]
