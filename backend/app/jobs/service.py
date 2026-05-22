from collections.abc import Callable
from datetime import date, datetime
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import JobRun, utc_now
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"success", "error"}
ProgressCallback = Callable[[int | None, int | None, str | None], None]
JobWorker = Callable[[Session, ProgressCallback], Any]


class JobRunNotFoundError(Exception):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return str(value)


def _to_json(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def serialize_job(job: JobRun) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "target": job.target,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "message": job.message,
        "error_message": job.error_message,
        "request": _from_json(job.request_json),
        "result": _from_json(job.result_json),
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
) -> list[JobRun]:
    query = db.query(JobRun)

    if status:
        query = query.filter(JobRun.status == status)

    if job_type:
        query = query.filter(JobRun.job_type == job_type)

    return (
        query.order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .limit(limit)
        .all()
    )


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
