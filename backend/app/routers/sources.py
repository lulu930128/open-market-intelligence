from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.pipelines.fetch_pipeline import refresh_source,run_source_fetch
from app.db.session import get_db
from app.sources import service
from app.sources.schemas import (
    FetchLogRead,
    RawFetchResultListRead,
    SourceCreate,
    SourceRead,
    SourceRefreshRead,
    SourceRunRead,
    SourceUpdate,
)

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


@router.post("/{source_id}/run", response_model=SourceRunRead)
def run_source(source_id: int, db: Session = Depends(get_db)):
    try:
        return run_source_fetch(db, source_id)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    

@router.post("/{source_id}/refresh", response_model=SourceRefreshRead)
def refresh_source_data(source_id: int, db: Session = Depends(get_db)):
    try:
        return refresh_source(db, source_id)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{source_id}/logs", response_model=list[FetchLogRead])
def list_source_logs(
    source_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    try:
        return service.list_source_logs(db, source_id, limit=limit)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{source_id}/raw-results", response_model=list[RawFetchResultListRead])
def list_source_raw_results(
    source_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    try:
        raw_results = service.list_source_raw_results(db, source_id, limit=limit)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        {
            "id": item.id,
            "source_id": item.source_id,
            "fetch_log_id": item.fetch_log_id,
            "fetched_at": item.fetched_at,
            "url": item.url,
            "method": item.method,
            "status_code": item.status_code,
            "content_type": item.content_type,
            "content_hash": item.content_hash,
            "raw_text_length": len(item.raw_text) if item.raw_text else 0,
            "parser_version": item.parser_version,
            "error_message": item.error_message,
        }
        for item in raw_results
    ]


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