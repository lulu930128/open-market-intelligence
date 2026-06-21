from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks, service
from app.jobs.job_types import (
    JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
)
from app.jobs.schemas import JobRunRead


router = APIRouter()


def _parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value

    return date.fromisoformat(str(value))


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    return []


def _request_dict(job: Any) -> dict[str, Any]:
    request = service.serialize_job(job).get("request")

    return request if isinstance(request, dict) else {}


def _retry_config(job: Any) -> tuple[Any, tuple[Any, ...], dict[str, Any]]:
    request = _request_dict(job)
    job_type = job.job_type

    if job_type == "market.twse_daily_price_backfill":
        return (
            backfill_tasks.run_twse_daily_price_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", False)),
            ),
            request,
        )

    if job_type == "market.tpex_daily_price_backfill":
        return (
            backfill_tasks.run_tpex_daily_price_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", False)),
            ),
            request,
        )

    if job_type in {"market.daily_metrics_backfill", "scheduler.market_daily_refresh"}:
        return (
            backfill_tasks.run_market_daily_metrics_job,
            (
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                list(request.get("categories") or []),
                int(request.get("lookback_days", 30)),
                bool(request.get("include_today", False)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type in {
        "market.market_chip_daily_refresh",
        "scheduler.market_chip_daily_refresh",
    }:
        include_today = request.get("include_today")
        return (
            backfill_tasks.run_market_chip_daily_refresh_job,
            (
                _parse_string_list(request.get("index_ids")) or ["TAIEX", "TPEX"],
                _parse_date(request.get("trade_date")),
                include_today if isinstance(include_today, bool) else None,
                bool(request.get("force", False)),
            ),
            request,
        )

    if job_type == "market.stock_daily_metrics_history_backfill":
        return (
            backfill_tasks.run_stock_daily_metrics_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                list(request.get("categories") or []),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.fundamental_metrics_backfill":
        return (
            backfill_tasks.run_market_fundamental_metrics_job,
            (
                list(request.get("categories") or []),
                bool(request.get("force", False)),
                float(request.get("sleep_seconds", 0.2)),
            ),
            request,
        )

    if job_type == "market.stock_fundamental_metrics_backfill":
        return (
            backfill_tasks.run_stock_fundamental_metrics_job,
            (
                str(request.get("stock_id") or job.target),
                list(request.get("categories") or []),
                bool(request.get("force", False)),
                float(request.get("sleep_seconds", 0.2)),
            ),
            request,
        )

    if job_type == "market.stock_shareholding_history_backfill":
        return (
            backfill_tasks.run_stock_shareholding_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("from_date")),
                _parse_date(request.get("to_date")),
                int(request.get("lookback_weeks", 52)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_monthly_revenue_history_backfill":
        return (
            backfill_tasks.run_stock_monthly_revenue_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("from_period")),
                _parse_date(request.get("to_period")),
                int(request.get("lookback_months", 120)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_financial_metrics_history_backfill":
        return (
            backfill_tasks.run_stock_financial_metrics_history_job,
            (
                str(request.get("stock_id") or job.target),
                request.get("from_fiscal_year"),
                request.get("from_quarter"),
                request.get("to_fiscal_year"),
                request.get("to_quarter"),
                int(request.get("lookback_quarters", 40)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_selection_refresh":
        return (
            backfill_tasks.run_stock_selection_refresh_job,
            (
                str(request.get("stock_id") or job.target),
                request.get("include_today"),
                float(request.get("sleep_seconds", 0.05)),
                str(request.get("profile") or "full"),
            ),
            request,
        )

    if job_type == "watchlist.group_daily_price_backfill":
        return (
            backfill_tasks.run_watchlist_group_backfill_job,
            (
                int(request.get("group_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                request.get("tpex_source_id"),
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", True)),
            ),
            request,
        )

    if job_type == "watchlist.group_daily_price_refresh_latest":
        return (
            backfill_tasks.run_watchlist_group_refresh_latest_job,
            (
                int(request.get("group_id") or job.target),
                _parse_date(request.get("to_date")),
                int(request.get("lookback_days", 14)),
                bool(request.get("include_today", False)),
                request.get("source_id"),
                request.get("tpex_source_id"),
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", True)),
            ),
            request,
        )

    if job_type in {"us_market.watchlist_daily_refresh", "scheduler.us_market_daily_refresh"}:
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_us_watchlist_daily_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 12.0)),
            ),
            request,
        )

    if job_type == "us_market.watchlist_resource_refresh":
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_us_watchlist_resource_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                bool(request.get("include_daily", True)),
                bool(request.get("include_sec_facts", True)),
                bool(request.get("include_profile", True)),
                bool(request.get("include_actions", False)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 12.0)),
            ),
            request,
        )

    if job_type in {
        JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
        JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    }:
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_jp_watchlist_resource_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                bool(request.get("include_daily", True)),
                bool(request.get("include_fundamentals", False)),
                str(request.get("outputsize") or "compact"),
                str(request.get("provider") or "auto"),
                float(request.get("sleep_seconds", 1.0)),
            ),
            request,
        )

    if job_type == "us_market.daily_price_quality_repair":
        return (
            backfill_tasks.run_us_daily_price_quality_repair_job,
            (
                request.get("symbol"),
                bool(request.get("dry_run", True)),
                int(request.get("limit", 1000)),
                bool(request.get("refresh", False)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 0.0)),
            ),
            request,
        )

    raise ValueError(f"Job type '{job_type}' does not support retry.")


@router.get("", response_model=list[JobRunRead])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    include_payload: bool = Query(
        default=True,
        description="When false, omit request payload and return a compact result summary for polling UIs.",
    ),
    db: Session = Depends(get_db),
):
    jobs = service.list_jobs(
        db=db,
        status=status_filter,
        job_type=job_type,
        limit=limit,
        include_payload=include_payload,
    )
    return [service.serialize_job(job, include_payload=include_payload) for job in jobs]


@router.get("/{job_id}", response_model=JobRunRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.serialize_job(service.get_job(db, job_id))
    except service.JobRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{job_id}/retry", response_model=JobRunRead, status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    try:
        previous_job = service.get_job(db, job_id)
        task, task_args, request = _retry_config(previous_job)
    except service.JobRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    job, _created = service.enqueue_job(
        db=db,
        job_type=previous_job.job_type,
        target=previous_job.target,
        request=request,
        progress_total=max(previous_job.progress_total, 1),
        message=f"Retry queued from job {previous_job.id}.",
        task=task,
        task_args=task_args,
        dedupe_active=False,
    )
    return service.serialize_job(job)
