from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import json
import logging
from threading import Lock
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, load_only

from app.config import settings
from app.db.models import JobRun, utc_now
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"success", "error"}
ProgressCallback = Callable[[int | None, int | None, str | None], None]
JobWorker = Callable[[Session, ProgressCallback], Any]
JobTask = Callable[..., None]
SUMMARY_COUNT_KEYS = (
    "requested_count",
    "requested_stock_count",
    "requested_symbol_count",
    "total_count",
    "total_symbol_count",
    "symbol_count",
    "success_count",
    "current_count",
    "refreshed_symbol_count",
    "complete_symbol_count",
    "partial_symbol_count",
    "failed_symbol_count",
    "partial_success_count",
    "warning_count",
    "error_count",
    "failed_count",
    "symbol_error_count",
    "resource_attempt_count",
    "resource_success_count",
    "resource_error_count",
    "inserted_count",
    "updated_count",
    "fetched_count",
    "skipped_existing_count",
    "skipped_count",
)
FAILED_RESULT_ITEM_LIMIT = 4

_executor: ThreadPoolExecutor | None = None
_executor_lock = Lock()


class JobRunNotFoundError(Exception):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return str(value)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _loaded_attr(item: Any, attr_name: str) -> Any:
    state = sa_inspect(item, raiseerr=False)
    if state is not None and attr_name in state.unloaded:
        return None

    return getattr(item, attr_name, None)


def _summary_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _summary_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None

    return value if isinstance(value, (int, float)) else None


def _compact_result_item(item: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "stock_id",
        "stock_name",
        "symbol",
        "source_name",
        "category",
        "resource",
        "trade_date",
        "status",
        "message",
        "error_message",
    ):
        value = item.get(key)
        if value is not None:
            compact[key] = value

    return compact


def _failed_result_items(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    failed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        status_value = _summary_string(row.get("status"))
        error_message = _summary_string(row.get("error_message")) or _summary_string(row.get("message"))
        nested_failed: list[dict[str, Any]] = []
        for key, value in row.items():
            if not isinstance(value, dict):
                continue
            nested_status = _summary_string(value.get("status"))
            nested_error_message = (
                _summary_string(value.get("error_message")) or _summary_string(value.get("message"))
            )
            if nested_status not in {"error", "partial_success"} and not _summary_string(value.get("error_message")):
                continue
            compact_nested = _compact_result_item(
                {
                    **value,
                    "symbol": value.get("symbol") or row.get("symbol"),
                    "resource": value.get("resource") or key,
                    "status": nested_status or value.get("status") or "error",
                }
            )
            if nested_error_message and "error_message" not in compact_nested:
                compact_nested["error_message"] = nested_error_message
            nested_failed.append(compact_nested)

        if status_value not in {"error", "partial_success"} and not _summary_string(row.get("error_message")):
            failed.extend(nested_failed[: max(FAILED_RESULT_ITEM_LIMIT - len(failed), 0)])
            if len(failed) >= FAILED_RESULT_ITEM_LIMIT:
                break
            continue

        compact = _compact_result_item(row)
        if error_message and "error_message" not in compact:
            compact["error_message"] = error_message
        failed.append(compact)
        failed.extend(nested_failed[: max(FAILED_RESULT_ITEM_LIMIT - len(failed), 0)])

        if len(failed) >= FAILED_RESULT_ITEM_LIMIT:
            break

    return failed


def _error_items(errors: Any) -> list[dict[str, Any]]:
    if not isinstance(errors, list):
        return []

    items: list[dict[str, Any]] = []
    for row in errors[:FAILED_RESULT_ITEM_LIMIT]:
        if not isinstance(row, dict):
            continue

        compact = _compact_result_item({**row, "status": row.get("status") or "error"})
        message = _summary_string(row.get("error_message")) or _summary_string(row.get("message"))
        if message and "error_message" not in compact:
            compact["error_message"] = message
        items.append(compact)

    return items


def _summarize_result(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    summary: dict[str, Any] = {}
    status_value = _summary_string(value.get("status"))
    message_value = _summary_string(value.get("message"))

    if status_value:
        summary["status"] = status_value
    if message_value:
        summary["message"] = message_value

    for key in SUMMARY_COUNT_KEYS:
        if (number_value := _summary_number(value.get(key))) is not None:
            summary[key] = number_value

    rows = value.get("results")
    if isinstance(rows, list):
        summary["result_count"] = len(rows)
        failed_rows = _failed_result_items(rows)
        if failed_rows:
            summary["results"] = failed_rows

    errors = value.get("errors")
    if isinstance(errors, list):
        summary["errors_count"] = len(errors)
        if "error_count" not in summary and errors:
            summary["error_count"] = len(errors)
        if "results" not in summary:
            error_rows = _error_items(errors)
            if error_rows:
                summary["results"] = error_rows

    return summary or None


def _to_result_summary_json(result: Any) -> str | None:
    return _to_json(_summarize_result(result))


def serialize_job(job: JobRun, *, include_payload: bool = True) -> dict[str, Any]:
    if include_payload:
        request = _from_json(getattr(job, "request_json", None))
        result = _from_json(getattr(job, "result_json", None))
    else:
        request = None
        summary_json = _loaded_attr(job, "result_summary_json")
        if summary_json is not None:
            result = _from_json(summary_json)
        else:
            result_json = _loaded_attr(job, "result_json")
            result = _summarize_result(_from_json(result_json)) if result_json is not None else None

    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "target": job.target,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "message": job.message,
        "error_message": job.error_message,
        "request": request,
        "result": result,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "updated_at": job.updated_at,
    }


def get_job(db: Session, job_id: int) -> JobRun:
    job = db.query(JobRun).filter(JobRun.id == job_id).first()

    if job is None:
        raise JobRunNotFoundError(f"Job id={job_id} not found.")

    return job


def list_jobs(
    db: Session,
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
    include_payload: bool = True,
) -> list[JobRun]:
    query = db.query(JobRun)

    if not include_payload:
        query = query.options(
            load_only(
                JobRun.id,
                JobRun.job_type,
                JobRun.status,
                JobRun.target,
                JobRun.progress_current,
                JobRun.progress_total,
                JobRun.message,
                JobRun.error_message,
                JobRun.result_summary_json,
                JobRun.created_at,
                JobRun.started_at,
                JobRun.ended_at,
                JobRun.updated_at,
            )
        )

    if status:
        query = query.filter(JobRun.status == status)

    if job_type:
        query = query.filter(JobRun.job_type == job_type)

    return (
        query.order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .limit(limit)
        .all()
    )


def find_active_job(
    db: Session,
    job_type: str,
    target: str | None = None,
    request: Any = None,
) -> JobRun | None:
    request_json = _to_json(request)
    query = db.query(JobRun).filter(
        JobRun.job_type == job_type,
        JobRun.status.in_(ACTIVE_STATUSES),
        JobRun.target == target,
    )

    if request_json is None:
        query = query.filter(JobRun.request_json.is_(None))
    else:
        query = query.filter(JobRun.request_json == request_json)

    return query.order_by(JobRun.created_at.desc(), JobRun.id.desc()).first()


def create_job(
    db: Session,
    job_type: str,
    target: str | None = None,
    request: Any = None,
    progress_total: int = 1,
    message: str | None = None,
) -> JobRun:
    job = JobRun(
        job_type=job_type,
        status="queued",
        target=target,
        progress_current=0,
        progress_total=max(progress_total, 1),
        message=message,
        request_json=_to_json(request),
    )

    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _get_executor() -> ThreadPoolExecutor:
    global _executor

    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=max(settings.job_worker_max_concurrency, 1),
                thread_name_prefix="omi-job",
            )

        return _executor


def _log_unhandled_task_exception(future) -> None:
    if future.cancelled():
        return

    try:
        exc = future.exception()
    except Exception as callback_exc:
        logger.exception("Failed to inspect background job future: %s", callback_exc)
        return

    if exc is not None:
        logger.error(
            "Background job task crashed outside job tracking.",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def submit_job_task(task: JobTask, job_id: int, *task_args: Any) -> None:
    future = _get_executor().submit(task, job_id, *task_args)
    future.add_done_callback(_log_unhandled_task_exception)


def enqueue_job(
    db: Session,
    *,
    job_type: str,
    target: str | None = None,
    request: Any = None,
    progress_total: int = 1,
    message: str | None = "Queued.",
    task: JobTask,
    task_args: tuple[Any, ...] = (),
    dedupe_active: bool | None = None,
) -> tuple[JobRun, bool]:
    should_dedupe = settings.job_dedupe_active if dedupe_active is None else dedupe_active

    if should_dedupe:
        existing = find_active_job(
            db=db,
            job_type=job_type,
            target=target,
            request=request,
        )

        if existing is not None:
            return existing, False

    job = create_job(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=progress_total,
        message=message,
    )

    try:
        submit_job_task(task, job.id, *task_args)
    except Exception as exc:
        fail_job(db, job.id, error_message=f"Failed to submit job: {exc}")
        db.refresh(job)

    return job, True


def shutdown_job_executor(wait: bool = False) -> None:
    global _executor

    with _executor_lock:
        executor = _executor
        _executor = None

    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=not wait)


def mark_interrupted_jobs(db: Session) -> int:
    jobs = (
        db.query(JobRun)
        .filter(JobRun.status.in_(ACTIVE_STATUSES))
        .all()
    )

    if not jobs:
        return 0

    now = utc_now()

    for job in jobs:
        job.status = "error"
        job.error_message = "Job interrupted by application restart."
        job.message = "Job stopped before completion."
        job.ended_at = now
        job.updated_at = now

    db.commit()
    return len(jobs)


def start_job(db: Session, job_id: int, message: str | None = None) -> JobRun:
    job = get_job(db, job_id)
    now = utc_now()
    job.status = "running"
    job.started_at = job.started_at or now
    job.updated_at = now

    if message is not None:
        job.message = message

    db.commit()
    db.refresh(job)
    return job


def update_progress(
    db: Session,
    job_id: int,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> JobRun:
    job = get_job(db, job_id)
    job.status = "running"
    job.updated_at = utc_now()

    if current is not None:
        job.progress_current = max(current, 0)

    if total is not None:
        job.progress_total = max(total, 1)

    if message is not None:
        job.message = message

    db.commit()
    db.refresh(job)
    return job


def complete_job(
    db: Session,
    job_id: int,
    result: Any = None,
    message: str | None = None,
) -> JobRun:
    job = get_job(db, job_id)
    now = utc_now()
    job.status = "success"
    job.progress_current = max(job.progress_current, job.progress_total)
    job.message = message or "Job completed."
    job.error_message = None
    job.result_json = _to_json(result)
    job.result_summary_json = _to_result_summary_json(result)
    job.ended_at = now
    job.updated_at = now

    db.commit()
    db.refresh(job)
    return job


def fail_job(
    db: Session,
    job_id: int,
    error_message: str,
    result: Any = None,
) -> JobRun:
    db.rollback()
    job = get_job(db, job_id)
    now = utc_now()
    job.status = "error"
    job.error_message = error_message
    job.message = "Job failed."
    job.result_json = _to_json(result)
    job.result_summary_json = _to_result_summary_json(result)
    job.ended_at = now
    job.updated_at = now

    db.commit()
    db.refresh(job)
    return job


def run_tracked_job(job_id: int, worker: JobWorker) -> None:
    db = SessionLocal()

    def progress(
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        update_progress(
            db=db,
            job_id=job_id,
            current=current,
            total=total,
            message=message,
        )

    try:
        start_job(db, job_id, message="Job started.")
        result = worker(db, progress)
        complete_job(db, job_id, result=result)
    except Exception as exc:
        fail_job(db, job_id, error_message=str(exc))
        logger.exception("Tracked job %s failed.", job_id)
    finally:
        db.close()
