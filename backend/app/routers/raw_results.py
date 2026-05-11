from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.sources import service
from app.sources.schemas import RawFetchResultRead
from app.market.schemas import ParseTwseDailyResultRead
from app.pipelines.parse_pipeline import parse_twse_daily_raw_result


router = APIRouter()


@router.get("/{raw_result_id}", response_model=RawFetchResultRead)
def get_raw_result(
    raw_result_id: int,
    preview_chars: int = Query(default=20000, ge=0, le=200000),
    db: Session = Depends(get_db),
):
    try:
        raw_result = service.get_raw_result(db, raw_result_id)
    except service.SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    raw_text = raw_result.raw_text or ""
    raw_text_length = len(raw_text)

    if preview_chars == 0:
        preview = None
    else:
        preview = raw_text[:preview_chars]

    return {
        "id": raw_result.id,
        "source_id": raw_result.source_id,
        "fetch_log_id": raw_result.fetch_log_id,
        "fetched_at": raw_result.fetched_at,
        "url": raw_result.url,
        "method": raw_result.method,
        "status_code": raw_result.status_code,
        "content_type": raw_result.content_type,
        "content_hash": raw_result.content_hash,
        "raw_text_preview": preview,
        "raw_text_length": raw_text_length,
        "raw_text_truncated": raw_text_length > preview_chars if preview_chars > 0 else raw_text_length > 0,
        "raw_file_path": raw_result.raw_file_path,
        "parser_version": raw_result.parser_version,
        "error_message": raw_result.error_message,
    }


@router.post("/{raw_result_id}/parse/twse-daily", response_model=ParseTwseDailyResultRead)
def parse_twse_daily(
    raw_result_id: int,
    db: Session = Depends(get_db),
):
    try:
        return parse_twse_daily_raw_result(db, raw_result_id)
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