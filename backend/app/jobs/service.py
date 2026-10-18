from collections.abc import Callable
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import logging
import re
from threading import BoundedSemaphore, Lock, RLock
import time
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
    "attempted_count",
    "total_count",
    "total_symbol_count",
    "symbol_count",
    "success_count",
    "saved_count",
    "evaluated_count",
    "initialized_evaluation_count",
    "initialized_path_count",
    "initialization_pending_count",
    "due_count_before",
    "attempted_evaluation_count",
    "attempted_path_count",
    "finalized_count",
    "awaiting_daily_bar_count",
    "unevaluable_count",
    "remaining_due_count",
    "current_count",
    "partial_count",
    "stale_count",
    "missing_count",
    "universe_count",
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
    "stock_count",
    "created_source_count",
    "source_attempt_count",
    "source_success_count",
    "source_error_count",
    "quality_rows_created",
    "quality_rows_updated",
    "rows_read",
    "profiles_written",
    "profiles_deleted",
    "candidate_session_count",
    "high_coverage_session_count",
)
FAILED_RESULT_ITEM_LIMIT = 4

_executor: ThreadPoolExecutor | None = None
_executor_lock = RLock()
_admission_closed = False
_admission_pause = None
_active_enqueues = 0


@dataclass
class PendingJobTask:
    lane: str
    job_id: int
    task_name: str
    submitted_at: float
    started_at: float | None = None
    finished_at: float | None = None


_pending_tasks: dict[Future, PendingJobTask] = {}
PENDING_TASK_DIAGNOSTIC_LIMIT = 12
_task_failures = 0
_enqueue_failures = 0
_materialization_executors: dict[str, ThreadPoolExecutor] = {}
MARKET_BACKGROUND_MAX_IN_FLIGHT = 2
_materialization_slots = {
    "market_interactive": BoundedSemaphore(8),
    "market_background": BoundedSemaphore(MARKET_BACKGROUND_MAX_IN_FLIGHT),
    "market_completed": BoundedSemaphore(settings.taiwan_completed_materialization_concurrency),
}
_enqueue_lock = Lock()


class JobRunNotFoundError(Exception):
    pass


class JobAdmissionClosed(RuntimeError):
    pass


@dataclass(frozen=True)
class JobDrainResult:
    admission_closed: bool
    pending_by_lane: dict[str, int]
    active_enqueues: int
    task_failures: int
    unresolved_enqueues: int = 0

    @property
    def drained(self) -> bool:
        return self.admission_closed and not self.pending_by_lane and not self.active_enqueues and not self.unresolved_enqueues


def require_job_admission() -> None:
    with _executor_lock:
        if _admission_closed or _admission_pause is not None:
            raise JobAdmissionClosed("JOB_ADMISSION_CLOSED: new process lifecycle required")


def pause_jobs_if_idle():
    global _admission_pause
    with _executor_lock:
        if _admission_closed or _admission_pause is not None:
            raise JobAdmissionClosed("Job quiescence unavailable")
        if _pending_tasks or _active_enqueues or _enqueue_failures:
            return None
        _admission_pause = object()
        return _admission_pause


def observe_job_quiescence() -> dict[str, Any]:
    """Memory-only diagnosis of the existing job owner; never clears a failure.

    A failed enqueue may have committed an unknown durable JobRun. Only a
    separate, explicit reconciliation may resolve that uncertainty. This
    observation is not a restart gate or proof of writer completion.
    """
    with _executor_lock:
        pending_by_lane: dict[str, int] = {}
        completed_by_lane: dict[str, int] = {}
        cancelled_by_lane: dict[str, int] = {}
        tasks: list[dict[str, Any]] = []
        observed_at = time.monotonic()
        unfinished_count = 0
        for future, task in _pending_tasks.items():
            raw_lane = task.lane
            lane = raw_lane if raw_lane == "default" or raw_lane in _materialization_slots else "other"
            pending_by_lane[lane] = pending_by_lane.get(lane, 0) + 1
            done = future.done()
            if done:
                completed_by_lane[lane] = completed_by_lane.get(lane, 0) + 1
            else:
                unfinished_count += 1
            if future.cancelled():
                cancelled_by_lane[lane] = cancelled_by_lane.get(lane, 0) + 1
            if len(tasks) < PENDING_TASK_DIAGNOSTIC_LIMIT:
                finished_at = task.finished_at if task.finished_at is not None else observed_at
                queue_end = task.started_at if task.started_at is not None else finished_at
                tasks.append({
                    "job_id": task.job_id,
                    "task_name": task.task_name,
                    "execution_lane": lane,
                    "state": "done" if done else "running" if future.running() else "queued",
                    "queue_wait_seconds": round(max(0.0, queue_end - task.submitted_at), 3),
                    "execution_seconds": None if task.started_at is None else round(
                        max(0.0, finished_at - task.started_at), 3),
                })
        reason = (
            "ADMISSION_CLOSED" if _admission_closed else
            "ALREADY_PAUSED" if _admission_pause is not None else
            "UNRESOLVED_ENQUEUE" if _enqueue_failures else
            "ACTIVE_ENQUEUE" if _active_enqueues else
            "PENDING_FUTURES" if pending_by_lane else "IDLE"
        )
        return {
            "reason": reason,
            "admission_closed": _admission_closed,
            "admission_paused": _admission_pause is not None,
            "pending_by_lane": dict(sorted(pending_by_lane.items())),
            "completed_pending_by_lane": dict(sorted(completed_by_lane.items())),
            "cancelled_pending_by_lane": dict(sorted(cancelled_by_lane.items())),
            "active_enqueues": _active_enqueues,
            "unresolved_enqueues": _enqueue_failures,
            "task_failures": _task_failures,
            "unfinished_future_count": unfinished_count,
            "completed_pending_count": sum(completed_by_lane.values()),
            "tasks": tasks,
            "tasks_omitted": max(0, len(_pending_tasks) - len(tasks)),
            "default_executor_max_workers": getattr(_executor, "_max_workers", None),
        }


def resume_jobs(lease):
    global _admission_pause
    with _executor_lock:
        if lease is not _admission_pause or _admission_closed:
            raise JobAdmissionClosed("Invalid job quiescence lease")
        _admission_pause = None


@contextmanager
def _enqueue_admission():
    global _active_enqueues
    with _executor_lock:
        require_job_admission()
        _active_enqueues += 1
    try:
        yield
    finally:
        with _executor_lock:
            _active_enqueues -= 1


def begin_job_drain() -> None:
    global _admission_closed
    with _executor_lock:
        _admission_closed = True


def job_drain_status() -> JobDrainResult:
    with _executor_lock:
        lanes: dict[str, int] = {}
        for task in _pending_tasks.values():
            lane = task.lane
            lanes[lane] = lanes.get(lane, 0) + 1
        return JobDrainResult(_admission_closed, lanes, _active_enqueues, _task_failures, _enqueue_failures)


async def drain_job_executor(*, deadline: float) -> JobDrainResult:
    begin_job_drain()
    while not (result := job_drain_status()).drained:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result
        await asyncio.sleep(min(0.01, remaining))
    shutdown_job_executor(wait=False)
    return job_drain_status()


class JobExecutionError(Exception):
    """Fail a tracked job while preserving structured outcome evidence."""

    def __init__(self, message: str, *, result: Any = None) -> None:
        super().__init__(message)
        self.result = result


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

    result_dict = result if isinstance(result, dict) else {}
    result_status = str(result_dict.get("status") or "").strip().lower()
    public_status = (
        result_status
        if result_status in {"completed", "partial", "failed", "cancelled", "expired"}
        else {
            "queued": "queued",
            "running": "running",
            "success": "completed",
            "error": "failed",
        }.get(str(job.status), str(job.status))
    )

    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "public_status": public_status,
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


def find_active_job_by_target(
    db: Session,
    job_type: str,
    target: str | None = None,
) -> JobRun | None:
    """Find an active lease regardless of request metadata differences."""

    return (
        db.query(JobRun)
        .filter(
            JobRun.job_type == job_type,
            JobRun.status.in_(ACTIVE_STATUSES),
            JobRun.target == target,
        )
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )


def find_recent_successful_job(
    db: Session,
    job_type: str,
    target: str | None = None,
    request: Any = None,
    *,
    within_seconds: float,
) -> JobRun | None:
    if within_seconds <= 0:
        return None

    request_json = _to_json(request)
    query = db.query(JobRun).filter(
        JobRun.job_type == job_type,
        JobRun.status == "success",
        JobRun.target == target,
        JobRun.ended_at.isnot(None),
        JobRun.ended_at >= utc_now() - timedelta(seconds=within_seconds),
    )
    if request_json is None:
        query = query.filter(JobRun.request_json.is_(None))
    else:
        query = query.filter(JobRun.request_json == request_json)

    return query.order_by(JobRun.ended_at.desc(), JobRun.id.desc()).first()


def create_job_record(
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
    return job


def create_job(
    db: Session,
    *,
    job_type: str,
    target: str | None = None,
    request: Any = None,
    progress_total: int = 1,
    message: str | None = "Queued.",
) -> JobRun:
    job = create_job_record(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=progress_total,
        message=message,
    )
    db.commit()
    db.refresh(job)
    return job


def _get_executor() -> ThreadPoolExecutor:
    global _executor

    with _executor_lock:
        require_job_admission()
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=max(settings.job_worker_max_concurrency, 1),
                thread_name_prefix="omi-job",
            )
            logger.info("JOB_DEFAULT_EXECUTOR max_workers=%s", _executor._max_workers)

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


def submit_job_task(task: JobTask, job_id: int, *task_args: Any,
                    execution_lane: str = "default") -> None:
    # Submit and register under the same fence. Immediate callbacks may re-enter.
    with _executor_lock:
        require_job_admission()
        slots = None
        if execution_lane != "default":
            slots = _materialization_slots.get(execution_lane)
            if slots is None:
                raise ValueError("Unknown job execution lane")
            if not slots.acquire(blocking=False):
                raise RuntimeError("MARKET_MATERIALIZATION_QUEUE_FULL")
        try:
            if execution_lane == "default":
                executor = _get_executor()
            else:
                executor = _materialization_executors.get(execution_lane)
                if executor is None:
                    workers = settings.taiwan_completed_materialization_concurrency if execution_lane == "market_completed" else 1
                    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"omi-{execution_lane}")
                    _materialization_executors[execution_lane] = executor
            # Only source identifiers are retained, never arguments or repr(task).
            raw_name = getattr(task, "__name__", "")
            task_name = raw_name if isinstance(raw_name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", raw_name) else "job_task"
            tracked = PendingJobTask(execution_lane, job_id, task_name, time.monotonic())

            def run_task():
                with _executor_lock:
                    tracked.started_at = time.monotonic()
                try:
                    return task(job_id, *task_args)
                finally:
                    with _executor_lock:
                        tracked.finished_at = time.monotonic()

            future = executor.submit(run_task)
        except BaseException:
            if slots is not None:
                slots.release()
            raise
        _pending_tasks[future] = tracked

        def completed(done: Future) -> None:
            global _task_failures
            try:
                _log_unhandled_task_exception(done)
            finally:
                with _executor_lock:
                    if not done.cancelled() and done.exception() is not None:
                        _task_failures += 1
                    if slots is not None:
                        slots.release()
                    _pending_tasks.pop(done, None)

        future.add_done_callback(completed)


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
    reuse_success_within_seconds: float = 0,
) -> tuple[JobRun, bool]:
    global _enqueue_failures
    with _enqueue_admission():
        try:
            return _enqueue_job(
                db, job_type=job_type, target=target, request=request,
                progress_total=progress_total, message=message, task=task,
                task_args=task_args, dedupe_active=dedupe_active,
                reuse_success_within_seconds=reuse_success_within_seconds,
            )
        except BaseException:
            # Commit/refresh/compensation may have failed after a durable insert.
            # Rollback alone cannot prove that no queued record remains.
            with _executor_lock:
                _enqueue_failures += 1
            db.rollback()
            raise


def _enqueue_job(
    db: Session, *, job_type: str, target: str | None, request: Any,
    progress_total: int, message: str | None, task: JobTask,
    task_args: tuple[Any, ...], dedupe_active: bool | None,
    reuse_success_within_seconds: float,
) -> tuple[JobRun, bool]:
    should_dedupe = settings.job_dedupe_active if dedupe_active is None else dedupe_active

    # Keep the read-then-create decision atomic inside one application process.
    # This closes the common duplicate-submit race caused by concurrent React
    # effects or multiple UI panels requesting the exact same refresh.
    with _enqueue_lock:
        if should_dedupe:
            existing = find_active_job(
                db=db,
                job_type=job_type,
                target=target,
                request=request,
            )
            if existing is None:
                existing = find_recent_successful_job(
                    db=db,
                    job_type=job_type,
                    target=target,
                    request=request,
                    within_seconds=reuse_success_within_seconds,
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
    # Permanently fence this process and retain executor identity. Runtime uses
    # async drain_job_executor. A timeout never cancels a running transaction.
    begin_job_drain()
    if wait:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use async drain_job_executor on the event loop")
        deadline = time.monotonic() + 30.0
        while not job_drain_status().drained:
            if time.monotonic() >= deadline:
                raise TimeoutError("Job executor drain deadline exceeded")
            time.sleep(0.01)
    with _executor_lock:
        executors = list(_materialization_executors.values())
        if _executor is not None:
            executors.append(_executor)
    for executor in executors:
        executor.shutdown(wait=False, cancel_futures=False)


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
    partial = isinstance(result, dict) and result.get("status") == "partial"
    if not partial:
        job.progress_current = max(job.progress_current, job.progress_total)
    job.message = message or (result.get("message") if partial else None) or "Job completed."
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
    except JobExecutionError as exc:
        fail_job(db, job_id, error_message=str(exc), result=exc.result)
        logger.warning("Tracked job %s failed its outcome contract: %s", job_id, exc)
    except Exception as exc:
        fail_job(db, job_id, error_message=str(exc))
        logger.exception("Tracked job %s failed.", job_id)
    finally:
        db.close()
