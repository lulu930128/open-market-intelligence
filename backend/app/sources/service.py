from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DataQualityCheck,FetchLog, RawFetchResult, SourceRegistry
from app.sources.schemas import SourceCreate, SourceUpdate


class SourceAlreadyExistsError(Exception):
    pass


class SourceNotFoundError(Exception):
    pass


def list_sources(db: Session) -> list[SourceRegistry]:
    return (
        db.query(SourceRegistry)
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )


def get_source(db: Session, source_id: int) -> SourceRegistry:
    source = db.query(SourceRegistry).filter(SourceRegistry.id == source_id).first()

    if source is None:
        raise SourceNotFoundError(f"Source id={source_id} not found.")

    return source


def create_source(db: Session, payload: SourceCreate) -> SourceRegistry:
    source = SourceRegistry(**payload.model_dump())

    db.add(source)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SourceAlreadyExistsError(
            f"Source name '{payload.source_name}' already exists."
        ) from exc

    db.refresh(source)
    return source


def update_source(db: Session, source_id: int, payload: SourceUpdate) -> SourceRegistry:
    source = get_source(db, source_id)

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(source, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SourceAlreadyExistsError(
            f"Source name '{payload.source_name}' already exists."
        ) from exc

    db.refresh(source)
    return source


def delete_source(db: Session, source_id: int) -> None:
    source = get_source(db, source_id)

    db.delete(source)
    db.commit()


def list_source_logs(
    db: Session,
    source_id: int,
    limit: int = 50,
) -> list[FetchLog]:
    get_source(db, source_id)

    return (
        db.query(FetchLog)
        .filter(FetchLog.source_id == source_id)
        .order_by(FetchLog.started_at.desc(), FetchLog.id.desc())
        .limit(limit)
        .all()
    )


def list_source_raw_results(
    db: Session,
    source_id: int,
    limit: int = 50,
) -> list[RawFetchResult]:
    get_source(db, source_id)

    return (
        db.query(RawFetchResult)
        .filter(RawFetchResult.source_id == source_id)
        .order_by(RawFetchResult.fetched_at.desc(), RawFetchResult.id.desc())
        .limit(limit)
        .all()
    )


def get_raw_result(db: Session, raw_result_id: int) -> RawFetchResult:
    raw_result = (
        db.query(RawFetchResult)
        .filter(RawFetchResult.id == raw_result_id)
        .first()
    )

    if raw_result is None:
        raise SourceNotFoundError(f"Raw fetch result id={raw_result_id} not found.")

    return raw_result


def list_enabled_sources(db: Session) -> list[SourceRegistry]:
    return (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )


def set_source_enabled(
    db: Session,
    source_id: int,
    enabled: bool,
) -> SourceRegistry:
    source = get_source(db, source_id)

    source.enabled = enabled

    db.commit()
    db.refresh(source)

    return source


def get_source_status(db: Session, source_id: int) -> dict:
    source = get_source(db, source_id)

    total_fetch_count = (
        db.query(func.count(FetchLog.id))
        .filter(FetchLog.source_id == source_id)
        .scalar()
        or 0
    )

    success_fetch_count = (
        db.query(func.count(FetchLog.id))
        .filter(FetchLog.source_id == source_id)
        .filter(FetchLog.status == "success")
        .scalar()
        or 0
    )

    error_fetch_count = (
        db.query(func.count(FetchLog.id))
        .filter(FetchLog.source_id == source_id)
        .filter(FetchLog.status == "error")
        .scalar()
        or 0
    )

    raw_result_count = (
        db.query(func.count(RawFetchResult.id))
        .filter(RawFetchResult.source_id == source_id)
        .scalar()
        or 0
    )

    latest_fetch_log = (
        db.query(FetchLog)
        .filter(FetchLog.source_id == source_id)
        .order_by(FetchLog.started_at.desc(), FetchLog.id.desc())
        .first()
    )

    latest_raw_result = (
        db.query(RawFetchResult)
        .filter(RawFetchResult.source_id == source_id)
        .order_by(RawFetchResult.fetched_at.desc(), RawFetchResult.id.desc())
        .first()
    )

    return {
        "id": source.id,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "category": source.category,
        "enabled": source.enabled,
        "parser_type": source.parser_type,
        "reliability_level": source.reliability_level,
        "last_success_at": source.last_success_at,
        "last_error_at": source.last_error_at,
        "last_error_message": source.last_error_message,
        "total_fetch_count": total_fetch_count,
        "success_fetch_count": success_fetch_count,
        "error_fetch_count": error_fetch_count,
        "raw_result_count": raw_result_count,
        "latest_fetch_log_id": latest_fetch_log.id if latest_fetch_log else None,
        "latest_fetch_status": latest_fetch_log.status if latest_fetch_log else None,
        "latest_fetch_message": latest_fetch_log.message if latest_fetch_log else None,
        "latest_fetch_error_message": latest_fetch_log.error_message if latest_fetch_log else None,
        "latest_fetch_duration_ms": latest_fetch_log.duration_ms if latest_fetch_log else None,
        "latest_raw_result_id": latest_raw_result.id if latest_raw_result else None,
        "latest_raw_status_code": latest_raw_result.status_code if latest_raw_result else None,
        "latest_raw_content_hash": latest_raw_result.content_hash if latest_raw_result else None,
    }


def list_raw_result_quality_checks(
    db: Session,
    raw_result_id: int,
) -> list[DataQualityCheck]:
    get_raw_result(db, raw_result_id)

    return (
        db.query(DataQualityCheck)
        .filter(DataQualityCheck.raw_result_id == raw_result_id)
        .order_by(DataQualityCheck.created_at.desc(), DataQualityCheck.id.desc())
        .all()
    )