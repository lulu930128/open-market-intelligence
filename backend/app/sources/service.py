from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import FetchLog, RawFetchResult, SourceRegistry
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