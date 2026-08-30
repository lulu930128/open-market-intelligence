"""Tracked owner for explicit, bounded US current-market cache bootstrap."""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as job_service
from app.jobs.job_types import US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE
from app.us_market.intraday_materializer import (
    bootstrap_us_current_market,
    resolve_us_materializer_universe,
)
from app.us_market.intraday_profiles import (
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
)


def _configured_symbols(value: str | list[str] | tuple[str, ...]) -> str:
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def normalize_us_current_market_bootstrap_targets(
    *,
    equity_symbols: str | list[str] | tuple[str, ...],
    index_symbols: str | list[str] | tuple[str, ...],
) -> tuple[list[str], list[str]]:
    equity = resolve_us_materializer_universe(
        _configured_symbols(equity_symbols),
        max_symbols=2,
        lane_id="equity_research",
        instrument_type="stock",
    )["symbols"]
    indexes = resolve_us_materializer_universe(
        _configured_symbols(index_symbols),
        max_symbols=6,
        lane_id="index_current",
        instrument_type="index",
    )["symbols"]
    if not equity or not indexes:
        raise ValueError(
            "bootstrap requires valid equity and index configured symbols"
        )
    return equity, indexes


def run_us_current_market_bootstrap_job(
    job_id: int,
    equity_symbols: str,
    index_symbols: str,
    max_external_calls: int,
) -> None:
    def worker(_db: Session, progress: job_service.ProgressCallback):
        progress(0, 3, "Running bounded US current-market cache bootstrap.")
        result = bootstrap_us_current_market(
            equity_symbols=equity_symbols,
            index_symbols=index_symbols,
            max_external_calls=max_external_calls,
        )
        progress(len(result.get("runs") or ()), 3, "US current-market bootstrap finished.")
        if result.get("status") != "success":
            raise job_service.JobExecutionError(
                "US current-market bootstrap postcondition was not fully satisfied.",
                result=result,
            )
        return result

    job_service.run_tracked_job(job_id, worker)


def enqueue_us_current_market_bootstrap(
    db: Session,
    *,
    equity_symbols: str,
    index_symbols: str,
    max_external_calls: int = US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
    message: str = "Queued bounded US current-market cache bootstrap.",
) -> tuple[JobRun, bool]:
    if max_external_calls < 1 or max_external_calls > 20:
        raise ValueError("bootstrap max_external_calls must be between 1 and 20")
    equity, indexes = normalize_us_current_market_bootstrap_targets(
        equity_symbols=equity_symbols,
        index_symbols=index_symbols,
    )
    normalized_equity = ",".join(equity)
    normalized_indexes = ",".join(indexes)
    target_material = f"equity={normalized_equity}|index={normalized_indexes}"
    target = "us_current:" + hashlib.sha256(
        target_material.encode("utf-8")
    ).hexdigest()[:20]
    active = job_service.find_active_job_by_target(
        db,
        US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {
        "equity_symbols": equity,
        "index_symbols": indexes,
        "max_external_calls": max_external_calls,
    }
    return job_service.enqueue_job(
        db=db,
        job_type=US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE,
        target=target,
        request=request,
        progress_total=3,
        message=message,
        task=run_us_current_market_bootstrap_job,
        task_args=(
            normalized_equity,
            normalized_indexes,
            max_external_calls,
        ),
    )


__all__ = [
    "enqueue_us_current_market_bootstrap",
    "normalize_us_current_market_bootstrap_targets",
    "run_us_current_market_bootstrap_job",
]
