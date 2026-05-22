from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import service
from app.jobs.schemas import JobRunRead


router = APIRouter()


@router.get("", response_model=list[JobRunRead])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    jobs = service.list_jobs(
        db=db,
        status=status_filter,
        job_type=job_type,
        limit=limit,
    )
    return [service.serialize_job(job) for job in jobs]


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
