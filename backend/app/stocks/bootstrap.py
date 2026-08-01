from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import SourceRegistry, StockMaster
from app.db.session import SessionLocal
from app.jobs import service as job_service
from app.pipelines.fetch_pipeline import refresh_source
from app.scripts.seed_sources import DEFAULT_SOURCES
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TPEX_DOMESTIC_COMPANY_PROFILE_SOURCE_NAME,
    TPEX_FOREIGN_COMPANY_PROFILE_SOURCE_NAME,
    TWSE_COMPANY_PROFILE_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)
from app.stocks.service import sync_stocks_from_market_daily


logger = logging.getLogger(__name__)

BOOTSTRAP_JOB_TYPE = "system.stock_master_bootstrap"
BOOTSTRAP_TARGET = "TWSE,TPEX"
ProgressCallback = Callable[[int | None, int | None, str | None], None]


def _stock_master_count(db: Session) -> int:
    return int(db.query(func.count(StockMaster.id)).scalar() or 0)


def _market_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(func.upper(StockMaster.market), func.count(StockMaster.id))
        .filter(StockMaster.is_active.is_(True))
        .group_by(func.upper(StockMaster.market))
        .all()
    )
    return {str(market): int(count) for market, count in rows if market}


def _ensure_default_sources(db: Session) -> list[str]:
    source_names = [payload["source_name"] for payload in DEFAULT_SOURCES]
    existing_names = {
        row.source_name
        for row in db.query(SourceRegistry)
        .filter(SourceRegistry.source_name.in_(source_names))
        .all()
    }
    created_names: list[str] = []

    for payload in DEFAULT_SOURCES:
        if payload["source_name"] in existing_names:
            continue

        db.add(SourceRegistry(**payload))
        created_names.append(payload["source_name"])

    if created_names:
        db.commit()

    return created_names


def _refresh_named_source(db: Session, source_name: str) -> dict[str, Any]:
    source = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == source_name)
        .one()
    )

    try:
        result = refresh_source(db, source.id)
        return {
            "source_name": source_name,
            "status": (
                "success"
                if result.get("fetch_status") == "success"
                and result.get("parse_status") == "success"
                else result.get("fetch_status") or result.get("parse_status") or "error"
            ),
            "fetch_status": result.get("fetch_status"),
            "parse_status": result.get("parse_status"),
            "parsed_count": result.get("parsed_count"),
            "error_message": result.get("error_message"),
        }
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Stock master bootstrap source failed. source=%s error=%s",
            source_name,
            exc,
        )
        return {
            "source_name": source_name,
            "status": "error",
            "fetch_status": "error",
            "parse_status": None,
            "parsed_count": None,
            "error_message": str(exc),
        }


def bootstrap_stock_master(
    db: Session,
    progress: ProgressCallback | None = None,
    allow_existing: bool = False,
) -> dict[str, Any]:
    initial_count = _stock_master_count(db)
    if initial_count > 0 and not allow_existing:
        return {
            "status": "skipped",
            "initial_count": initial_count,
            "stock_count": initial_count,
            "created_source_count": 0,
            "source_attempt_count": 0,
            "source_success_count": 0,
            "source_error_count": 0,
            "market_counts": _market_counts(db),
            "message": "Stock master already contains data; first-run bootstrap was skipped.",
        }

    created_sources = _ensure_default_sources(db)
    attempts: list[dict[str, Any]] = []
    total_steps = 6

    def report(step: int, message: str) -> None:
        if progress is not None:
            progress(step, total_steps, message)

    report(1, "Refreshing the official TWSE daily symbol universe.")
    attempts.append(_refresh_named_source(db, TWSE_DAILY_TRADING_SOURCE_NAME))

    report(2, "Refreshing the official TPEx daily symbol universe.")
    attempts.append(_refresh_named_source(db, TPEX_DAILY_QUOTES_SOURCE_NAME))

    report(3, "Building the local stock master from refreshed daily data.")
    sync_result = sync_stocks_from_market_daily(db)
    counts = _market_counts(db)

    if counts.get("TWSE", 0) == 0:
        report(4, "Using the official TWSE company list as a bounded fallback.")
        attempts.append(_refresh_named_source(db, TWSE_COMPANY_PROFILE_SOURCE_NAME))
    else:
        report(4, "TWSE stock symbols are ready.")

    counts = _market_counts(db)
    if counts.get("TPEX", 0) == 0:
        report(5, "Using the official TPEx domestic company list as a bounded fallback.")
        attempts.append(_refresh_named_source(db, TPEX_DOMESTIC_COMPANY_PROFILE_SOURCE_NAME))
        attempts.append(_refresh_named_source(db, TPEX_FOREIGN_COMPANY_PROFILE_SOURCE_NAME))
    else:
        report(5, "TPEx stock symbols are ready.")

    report(6, "Finalizing first-run stock symbol coverage.")
    counts = _market_counts(db)
    stock_count = _stock_master_count(db)
    successful_attempts = [row for row in attempts if row["status"] == "success"]
    failed_attempts = [row for row in attempts if row["status"] != "success"]

    if stock_count == 0:
        failures = "; ".join(
            f"{row['source_name']}: {row.get('error_message') or row['status']}"
            for row in failed_attempts
        )
        raise RuntimeError(
            "First-run stock symbol bootstrap did not produce any stock master rows. "
            f"{failures or 'No official source returned usable rows.'}"
        )

    coverage_ready = counts.get("TWSE", 0) > 0 and counts.get("TPEX", 0) > 0
    return {
        "status": "ready" if coverage_ready else "partial",
        "initial_count": initial_count,
        "stock_count": stock_count,
        "created_source_count": len(created_sources),
        "source_attempt_count": len(attempts),
        "source_success_count": len(successful_attempts),
        "source_error_count": len(failed_attempts),
        "market_counts": counts,
        "sync": sync_result,
        "results": attempts,
        "message": (
            "First-run Taiwan stock symbols were fetched from official sources."
            if coverage_ready
            else "First-run stock symbols are partially available; source failures remain visible."
        ),
    }


def run_stock_master_bootstrap_job(
    job_id: int,
    allow_existing: bool = False,
) -> None:
    job_service.run_tracked_job(
        job_id,
        lambda db, progress: bootstrap_stock_master(
            db,
            progress,
            allow_existing=allow_existing,
        ),
    )


def enqueue_stock_master_bootstrap_if_needed() -> tuple[int | None, bool]:
    if not settings.enable_stock_master_bootstrap:
        return None, False

    db = SessionLocal()
    try:
        if _stock_master_count(db) > 0:
            return None, False

        _ensure_default_sources(db)

        request = {
            "reason": "empty_stock_master",
            "markets": ["TWSE", "TPEX"],
            "provider_policy": "official_bounded",
        }
        job, created = job_service.enqueue_job(
            db=db,
            job_type=BOOTSTRAP_JOB_TYPE,
            target=BOOTSTRAP_TARGET,
            request=request,
            progress_total=6,
            message="Queued first-run Taiwan stock symbol bootstrap.",
            task=run_stock_master_bootstrap_job,
            dedupe_active=True,
        )
        return job.id, created
    finally:
        db.close()


__all__ = [
    "BOOTSTRAP_JOB_TYPE",
    "bootstrap_stock_master",
    "enqueue_stock_master_bootstrap_if_needed",
    "run_stock_master_bootstrap_job",
]
