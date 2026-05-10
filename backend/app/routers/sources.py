from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.sources import service
from app.sources.schemas import SourceCreate, SourceRead, SourceUpdate

router = APIRouter()


@router.get("/", response_model=list[SourceRead])
def list_sources(db: Session = Depends(get_db)):
    return service.list_sources(db)


@router.post("/", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    try:
        return service.create_source(db, payload)
    except service.SourceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: int, db: Session = Depends(get_db)):
    try:
        return service.get_source(db, source_id)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_source(db, source_id, payload)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except service.SourceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    try:
        service.delete_source(db, source_id)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return None