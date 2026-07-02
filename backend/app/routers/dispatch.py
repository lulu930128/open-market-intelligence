from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dispatch import service
from app.dispatch.schemas import (
    DispatchDeleteResultRead,
    DispatchDeliveryRead,
    DispatchPreviewRead,
    DispatchPreviewRequest,
    DispatchRecipientGroupCreate,
    DispatchRecipientGroupRead,
    DispatchRecipientGroupUpdate,
    DispatchScheduleCreate,
    DispatchScheduleRead,
    DispatchScheduleUpdate,
    DispatchSendRead,
    DispatchSendRequest,
)
from app.watchlists import service as watchlist_service


router = APIRouter()


def _handle_dispatch_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            service.DispatchRecipientGroupNotFoundError,
            service.DispatchDeliveryNotFoundError,
            service.DispatchScheduleNotFoundError,
            watchlist_service.WatchlistGroupNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (service.DispatchValidationError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/recipient-groups", response_model=list[DispatchRecipientGroupRead])
def list_recipient_groups(
    enabled: bool | None = None,
    db: Session = Depends(get_db),
):
    return service.list_recipient_groups(db=db, enabled=enabled)


@router.post(
    "/recipient-groups",
    response_model=DispatchRecipientGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_recipient_group(
    payload: DispatchRecipientGroupCreate,
    db: Session = Depends(get_db),
):
    try:
        return service.create_recipient_group(db=db, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.patch("/recipient-groups/{group_id}", response_model=DispatchRecipientGroupRead)
def update_recipient_group(
    group_id: int,
    payload: DispatchRecipientGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_recipient_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.delete("/recipient-groups/{group_id}", response_model=DispatchDeleteResultRead)
def delete_recipient_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.delete_recipient_group(db=db, group_id=group_id)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.post("/preview", response_model=DispatchPreviewRead)
def preview_dispatch(
    payload: DispatchPreviewRequest,
    db: Session = Depends(get_db),
):
    try:
        return service.build_preview(db=db, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.post("/send", response_model=DispatchSendRead)
def send_dispatch(
    payload: DispatchSendRequest,
    db: Session = Depends(get_db),
):
    try:
        return service.queue_delivery(db=db, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.get("/schedules", response_model=list[DispatchScheduleRead])
def list_schedules(
    enabled: bool | None = None,
    db: Session = Depends(get_db),
):
    return service.list_schedules(db=db, enabled=enabled)


@router.post(
    "/schedules",
    response_model=DispatchScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    payload: DispatchScheduleCreate,
    db: Session = Depends(get_db),
):
    try:
        return service.create_schedule(db=db, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.patch("/schedules/{schedule_id}", response_model=DispatchScheduleRead)
def update_schedule(
    schedule_id: int,
    payload: DispatchScheduleUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_schedule(db=db, schedule_id=schedule_id, payload=payload)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.delete("/schedules/{schedule_id}", response_model=DispatchDeleteResultRead)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.delete_schedule(db=db, schedule_id=schedule_id)
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.post("/schedules/{schedule_id}/run", response_model=DispatchSendRead)
def run_schedule_now(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    try:
        result = service.run_schedule_now(db=db, schedule_id=schedule_id)
        return {
            "job": result["job"],
            "delivery": result["delivery"],
        }
    except Exception as exc:
        raise _handle_dispatch_error(exc) from exc


@router.get("/deliveries", response_model=list[DispatchDeliveryRead])
def list_deliveries(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return service.list_deliveries(db=db, limit=limit)
