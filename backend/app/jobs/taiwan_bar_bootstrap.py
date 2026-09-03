"""Tracked explicit commands for bounded Taiwan canonical Bar bootstrap."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as job_service
from app.jobs.job_types import (
    TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
    TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
)
from app.market.tw_index_daily_platform import (
    TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    bootstrap_taiex_official_daily_history,
    bootstrap_tpex_completed_derived_daily_history,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session_phase,
)
from app.market.tw_bar_contracts import TaiwanCurrentSessionSnapshotPhase
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_intraday_platform import bootstrap_taiwan_intraday_bars


# Collapse rapid switch-away/return commands without suppressing a later retry
# when a completed job still left the canonical snapshot in WARMING.
TAIWAN_VIEWER_WARMUP_SUCCESS_REUSE_SECONDS = 15


def _normalize_symbols(symbols: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value or "").strip().upper()
            for value in symbols
            if str(value or "").strip()
        )
    )


def run_taiwan_intraday_bar_bootstrap_job(
    job_id: int,
    symbols: tuple[str, ...],
    max_symbols: int,
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        progress(0, max_symbols, "Running bounded Taiwan Base-1m bootstrap.")
        result = bootstrap_taiwan_intraday_bars(
            db,
            symbols=symbols,
            max_symbols=max_symbols,
        )
        payload = result.model_dump(mode="json")
        progress(
            len(result.per_symbol),
            max_symbols,
            "Taiwan Base-1m bootstrap finished.",
        )
        if result.status in {"failed", "skipped"}:
            raise job_service.JobExecutionError(
                "Taiwan Base-1m bootstrap did not satisfy its postcondition.",
                result=payload,
            )
        return payload

    job_service.run_tracked_job(job_id, worker)


def enqueue_taiwan_intraday_bar_bootstrap(
    db: Session,
    *,
    symbols: list[str] | tuple[str, ...] = (),
    max_symbols: int = 10,
    reuse_success_within_seconds: float = 0,
) -> tuple[JobRun, bool]:
    if max_symbols < 1 or max_symbols > 10:
        raise ValueError("Taiwan intraday bootstrap max_symbols must be between 1 and 10")
    normalized = _normalize_symbols(symbols)
    if len(normalized) > max_symbols:
        raise ValueError("requested symbols exceed Taiwan intraday bootstrap max_symbols")
    target_material = f"symbols={','.join(normalized) or 'tier-a'}|max={max_symbols}"
    target = "tw_intraday:" + hashlib.sha256(
        target_material.encode("utf-8")
    ).hexdigest()[:20]
    active = job_service.find_active_job_by_target(
        db,
        TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {"symbols": list(normalized), "max_symbols": max_symbols}
    return job_service.enqueue_job(
        db=db,
        job_type=TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
        target=target,
        request=request,
        progress_total=max_symbols,
        message="Queued bounded Taiwan Base-1m bootstrap.",
        task=run_taiwan_intraday_bar_bootstrap_job,
        task_args=(normalized, max_symbols),
        reuse_success_within_seconds=reuse_success_within_seconds,
    )


def enqueue_taiwan_intraday_viewer_warmup(
    db: Session,
    stock_id: str,
    requested_at: datetime,
) -> tuple[JobRun | None, bool]:
    """Signal one bounded baseline warmup from a viewer command boundary."""

    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("Taiwan viewer warmup requested_at must be timezone-aware")
    local_now = requested_at.astimezone(TAIWAN_TZ)
    if not is_taiwan_trading_day(local_now.date()) or taiwan_market_session_phase(
        local_now
    ) not in {"regular", "closing_auction"}:
        return None, False

    coverage = TaiwanBarService(db).read_current_session_bars(
        instrument_id=stock_id,
        interval="1m",
        limit=1,
        requested_at=local_now,
    ).current_session_coverage
    if (
        coverage is None
        or coverage.snapshot_phase is not TaiwanCurrentSessionSnapshotPhase.WARMING
    ):
        return None, False

    return enqueue_taiwan_intraday_bar_bootstrap(
        db,
        symbols=[stock_id],
        max_symbols=1,
        reuse_success_within_seconds=TAIWAN_VIEWER_WARMUP_SUCCESS_REUSE_SECONDS,
    )


def run_taiwan_index_daily_bootstrap_job(
    job_id: int,
    index_ids: tuple[str, ...],
    date_from: date,
    date_to: date,
    taiex_max_sessions: int,
    tpex_max_sessions: int,
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        progress(0, len(index_ids), "Running bounded Taiwan index Base-1d bootstrap.")
        results: list[dict] = []
        for index_id in index_ids:
            result = (
                bootstrap_taiex_official_daily_history(
                    db,
                    date_from=date_from,
                    date_to=date_to,
                    max_sessions=taiex_max_sessions,
                )
                if index_id == "TAIEX"
                else bootstrap_tpex_completed_derived_daily_history(
                    db,
                    date_from=date_from,
                    date_to=date_to,
                    max_sessions=tpex_max_sessions,
                )
            )
            results.append(result)
            progress(
                len(results),
                len(index_ids),
                f"Taiwan {index_id} Base-1d bootstrap finished.",
            )
        status = (
            "success"
            if results and all(item.get("status") == "success" for item in results)
            else "partial"
            if any(item.get("status") in {"success", "partial"} for item in results)
            else "failed"
        )
        payload = {
            "contract_version": "tw.index_daily.bootstrap_job.v1",
            "status": status,
            "results": results,
        }
        if status != "success":
            raise job_service.JobExecutionError(
                "Taiwan index Base-1d bootstrap did not satisfy its postcondition.",
                result=payload,
            )
        return payload

    job_service.run_tracked_job(job_id, worker)


def enqueue_taiwan_index_daily_bootstrap(
    db: Session,
    *,
    index_ids: list[str] | tuple[str, ...],
    date_from: date,
    date_to: date,
    taiex_max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    tpex_max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
) -> tuple[JobRun, bool]:
    normalized = tuple(
        dict.fromkeys(str(value or "").strip().upper() for value in index_ids)
    )
    if not normalized or any(value not in {"TAIEX", "TPEX"} for value in normalized):
        raise ValueError("Taiwan index bootstrap supports only TAIEX and TPEX")
    if date_from > date_to:
        raise ValueError("Taiwan index bootstrap date_from must not exceed date_to")
    if not (
        1
        <= taiex_max_sessions
        <= TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("taiex_max_sessions must be between 1 and 300")
    if not (
        1
        <= tpex_max_sessions
        <= TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("tpex_max_sessions must be between 1 and 300")
    material = (
        f"ids={','.join(normalized)}|from={date_from}|to={date_to}|"
        f"taiex={taiex_max_sessions}|tpex={tpex_max_sessions}"
    )
    target = "tw_index_daily:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    active = job_service.find_active_job_by_target(
        db,
        TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {
        "index_ids": list(normalized),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "taiex_max_sessions": taiex_max_sessions,
        "tpex_max_sessions": tpex_max_sessions,
    }
    return job_service.enqueue_job(
        db=db,
        job_type=TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
        target=target,
        request=request,
        progress_total=len(normalized),
        message="Queued bounded Taiwan index Base-1d bootstrap.",
        task=run_taiwan_index_daily_bootstrap_job,
        task_args=(
            normalized,
            date_from,
            date_to,
            taiex_max_sessions,
            tpex_max_sessions,
        ),
    )
__all__ = [
    "TAIWAN_VIEWER_WARMUP_SUCCESS_REUSE_SECONDS",
    "enqueue_taiwan_index_daily_bootstrap",
    "enqueue_taiwan_intraday_bar_bootstrap",
    "enqueue_taiwan_intraday_viewer_warmup",
    "run_taiwan_index_daily_bootstrap_job",
    "run_taiwan_intraday_bar_bootstrap_job",
]
