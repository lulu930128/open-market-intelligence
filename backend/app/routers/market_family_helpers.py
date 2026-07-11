from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.jobs import service as job_service


ExceptionTypes = Sequence[type[Exception]]


def fetch_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


def watchlist_group_error(
    exc: Exception,
    *,
    not_found_errors: ExceptionTypes,
    bad_request_errors: ExceptionTypes = (),
) -> HTTPException:
    if isinstance(exc, tuple(not_found_errors)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, tuple(bad_request_errors)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def watchlist_item_error(
    exc: Exception,
    *,
    not_found_errors: ExceptionTypes,
    duplicate_errors: ExceptionTypes,
) -> HTTPException:
    if isinstance(exc, tuple(not_found_errors)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, tuple(duplicate_errors)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def watchlist_group_target(group_id: int | None) -> str:
    return f"group:{group_id}" if group_id is not None else "all"


def enqueue_serialized_job(
    *,
    db: Session,
    job_type: str,
    target: str,
    request: dict[str, Any],
    message: str,
    task: Callable[..., Any],
    task_args: tuple[Any, ...],
    progress_total: int = 1,
) -> dict[str, Any]:
    job, _created = job_service.enqueue_job(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=progress_total,
        message=message,
        task=task,
        task_args=task_args,
    )
    return job_service.serialize_job(job)
